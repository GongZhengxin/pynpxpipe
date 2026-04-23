# Spec: stages/export.py

## 1. 目标

实现 pipeline 最后一个 stage：**导出（Export）**。

三阶段导出策略：
- **Phase 1**（秒级）：将 units/trials/eye tracking/KS4 sorting/behavior_events 写入 NWB
- **Phase 2**（秒级）：导出 raster.h5 + trial/unit CSV（分析数据就绪，用户可立即开始分析）
- **Phase 3**（分钟级，后台线程）：原始数据压缩写入 AP+LF+NIDQ → NWB（Blosc zstd）

调用 `io/nwb_writer.py` 中的 `NWBWriter` 完成实际格式组装，本 stage 负责编排。

**前置条件（硬性）**：
- `session.session_id` 必须是完整构造的 `SessionID`（4 字段齐全），由 `SessionManager.create()` 在 pipeline 启动时保证。
- `session.probes` 已由上游 `discover` stage 填充，且**每个 `probe.target_area` 必须是非空、非 `"unknown"` 的字符串**（由 discover stage 从 `session.probe_plan` 注入）。Export stage 在 `run()` 最开始做兜底校验。

**错误处理**：若 Phase 1 写出 NWB 过程中发生异常，删除不完整的部分文件（`unlink(missing_ok=True)`），再 re-raise `ExportError`。Phase 3 后台写入失败不影响已导出的分析数据。

---

## 2. 输入

### `ExportStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `probes`、`output_dir`、`subject`、`session_id`、`config` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调 |

### `run()` 依赖的 session 字段（必需前置条件）

| 字段 | 说明 |
|---|---|
| `session.session_id` | `SessionID` 实例，4 字段齐全；`canonical()` 用于生成输出 NWB 文件名 |
| `session.probes` | 非空 `list[ProbeInfo]`；每个 `probe.target_area` 非空且 ≠ `"unknown"` |
| `session.output_dir` | 输出根目录（已由 SessionManager 创建） |
| `session.subject` | DANDI 兼容的动物元信息（传给 NWBWriter） |
| `session.bhv_file` | 眼动读取源 |

### 外部数据依赖

| 文件/目录 | 路径 | 说明 |
|---|---|---|
| SortingAnalyzer（每个 probe） | `{output_dir}/06_06_postprocessed/{probe_id}/` | 含 waveforms/templates/unit_locations 扩展 |
| SLAY 分数 | `{output_dir}/06_06_postprocessed/{probe_id}/slay_scores.json` | 由 postprocess stage 写出，含 slay_score + is_visual |
| behavior_events.parquet | `{output_dir}/04_sync/behavior_events.parquet` | 含 trial 事件表（完整列） |
| KS4 sorter_output（每个 probe） | `{output_dir}/02_02_sorted/{probe_id}/sorter_output/` | spike_templates.npy, amplitudes.npy, params.py |
| BHV2 文件 | `session.bhv_file` | 眼动数据（via BHV2Parser） |
| 原始 AP/LF/NIDQ .bin | `session.probes[*].ap_bin` 等 | Phase 3 原始数据压缩写入 |

---

## 3. 输出

| 输出 | 路径 | 说明 |
|---|---|---|
| NWB 文件 | `{output_dir}/{session.session_id.canonical()}.nwb` | DANDI 兼容 NWB 2.x；文件名按 SessionID 规范（`{date}_{subject}_{experiment}_{region}`）生成，与磁盘上的 `session_dir.name` 解耦 |
| raster HDF5（每个 probe） | `{output_dir}/07_export/raster_{probe_id}.h5` | spike raster 矩阵 |
| trial CSV | `{output_dir}/07_export/trials.csv` | trial 表导出 |
| unit CSV | `{output_dir}/07_export/units.csv` | unit 表导出 |
| stage checkpoint | `{output_dir}/checkpoints/export.json` | 含文件路径和统计数量 |

### stage checkpoint payload

```json
{
  "nwb_path": "/output/251024_FanFan_nsd1w_MSB-V4.nwb",
  "n_probes": 2,
  "n_units_total": 174,
  "n_trials": 120
}
```

---

## 4. 处理步骤

### `run()`

#### Step 0：前置条件兜底校验

1. 检查 stage 级 checkpoint；若完成 → return（在一切校验之前，避免重复工作）
2. **target_area 硬校验**（在任何 phase 之前）：遍历 `self.session.probes`，若任何 `probe.target_area` 为 `"unknown"` 或空字符串（`""`）：
   ```python
   raise ExportError(
       f"Probe {probe.probe_id} has target_area='unknown'; "
       f"discover stage must populate target_area from session.probe_plan before export"
   )
   ```
   设计意图：正常流程下 discover stage 已保证 target_area 从 probe_plan 填入；若用户跳过 discover 直接跑 export，或 probe_plan 为空时外部代码绕过了 discover 校验，此处兜底。校验失败时**不**进入任何 phase、**不**创建 NWB 文件、**不**写 failed checkpoint（纯前置条件失败，不算 stage 启动）。

#### Phase 1：轻量数据写入（秒级）

3. `_report_progress("Starting export", 0.0)`
4. 计算输出 NWB 路径：`nwb_path = _get_output_path()`（基于 `session.session_id.canonical()`）
5. **初始化 NWBWriter**：`writer = NWBWriter(session, nwb_path)`
6. **创建 NWBFile**：`writer.create_file()`（读取 ap.meta 的 fileCreateTime，验证 subject 字段）
7. **读取 behavior_events**：`pd.read_parquet(output_dir / "sync" / "behavior_events.parquet")`
8. **逐 probe 写入 units + electrodes + KS4**（串行，含内存释放）：
   ```
   for probe in session.probes:
       analyzer = si.load(06_postprocessed/{probe_id}/)
       rasters = compute_probe_rasters(analyzer, behavior_events, probe_id)
       writer.add_probe_data(probe, analyzer, rasters=rasters)
       writer.add_ks4_sorting(probe.probe_id, 02_sorted/{probe_id}/sorter_output/)
       del analyzer, rasters; gc.collect()
       _report_progress(f"Exported {probe_id}", ...)
   ```
9. **写入 trials 表**：`writer.add_trials(behavior_events_df)`（含 onset_time_ms、offset_time_ms、stim_name、dataset_name 等完整列）
10. **写入眼动数据**：`writer.add_eye_tracking(bhv_parser, behavior_events_df)`
11. **写出 NWB 文件**：`nwb_path_written = writer.write()`
12. **验证文件可读**：`pynwb.NWBHDF5IO(nwb_path_written, "r")` 打开再关闭；若失败 → raise `ExportError`

#### Phase 2：分析数据导出（秒级）

13. **导出 raster HDF5**：对每个 probe，将 raster 矩阵写入 `{output_dir}/07_export/raster_{probe_id}.h5`
14. **导出 CSV**：从 NWB 或 intermediate 数据导出 `trials.csv` 和 `units.csv`
15. **写 Phase 1+2 checkpoint**：`_write_checkpoint({nwb_path, n_probes, n_units_total, n_trials, phase: "analysis_ready"})`
16. `_report_progress("Analysis data ready", 0.8)`

← 用户已可开始分析（raster.h5 + CSV 已就绪）

#### Phase 3：原始数据压缩写入 + 全文件 bit-exact 校验（分钟级）

17. **调用 `writer.append_raw_data(session, nwb_path, verify_policy="full", progress_callback=...)`**
    - 流式 append AP+LF+NIDQ 到 NWB (`r+` 模式)，Blosc zstd clevel=6
    - 每写一个 chunk 调用 `progress_callback(message, fraction)`
    - 内部再调 `verify_nwb(nwb_path, progress_callback=...)` 逐 chunk bit-exact 扫描
18. **进度分段**（fraction 映射到 Phase 3 全段 0.7-1.0，前段 0-0.7 是 Phase 1+2.5）：
    - AP 写入：`append_ap_{probe_id}`（按 probe 均分）
    - LF 写入：`append_lf_{probe_id}`
    - NIDQ 写入：`append_nidq`
    - 校验：`verify_{probe_id}_{stream}`（占 Phase 3 末段 30%）
19. **运行模式**：
    - **UI（默认）**：`wait_for_raw=True` — ExportStage 的 `run()` 同步等 Phase 3 完成，UI PipelineRunner 线程阻塞但 UI event loop 不阻塞。`run_status="completed"` 后 UI 显示"✅ 处理完成，可安全关闭窗口"横幅
    - **CLI（默认）**：`wait_for_raw=True` — tqdm 进度条显示每个 chunk，tqdm 输出走 stderr 并同步写日志（让 `pynpx run` 的日志文件也能看到进度）
    - **Legacy daemon**：保留 `wait_for_raw=False` 后台 daemon thread 模式用于 harness 旧代码，新 UI/CLI 路径不再使用
20. **更新 checkpoint**：`{phase: "complete", raw_data_verified_at: ISO8601, verify_policy: "full"}`

若 Phase 1 步骤 6-12 中任何一步 raise：
- `nwb_path.unlink(missing_ok=True)`（删除不完整文件）
- `_write_failed_checkpoint(error)`
- re-raise 为 `ExportError`

Phase 3 bit-exact 失败 (`ExportError`) 在 `wait_for_raw=True` 下向上冒泡到 runner → UI 显示红色 banner + 错误详情，不显示"可安全关闭"。

### `_get_output_path() -> Path`

```python
return self.session.output_dir / f"{self.session.session_id.canonical()}.nwb"
```

**文件名规范**：`{date}_{subject}_{experiment}_{region}.nwb`，例如 `251024_FanFan_nsd1w_MSB-V4.nwb`。
路径与 `session.session_dir.name`（磁盘原始目录名）解耦——输入目录名可以是任意字符串（SpikeGLX 的 `*_g0` 约定），但输出 NWB 文件名始终遵循 SessionID 规范。

### `compute_probe_rasters(analyzer, behavior_events, probe_id, pre_onset_ms=50) -> dict`

独立函数（非 ExportStage 方法），计算每个 unit 的 spike raster（1ms bin 分辨率）：

1. 从 `behavior_events` 读取 `stim_onset_imec_s`（JSON 列），解析出该 probe 的 IMEC 时钟 onset
2. 仅保留 `trial_valid == 1.0` 的 trial
3. 读取 `onset_time_ms` 和 `offset_time_ms` 列，计算 `n_bins = pre_onset_ms + onset_time_ms + offset_time_ms`
4. 对每个 unit：
   - 获取 spike_times（IMEC 秒）
   - 对每个 valid trial，提取 `[stim_onset - pre_onset, stim_onset + onset + offset]` 窗口的 spikes
   - 转为 1ms bin 计数 → `np.uint8`
   - 堆叠为 `(n_valid_trials, n_bins)` 数组
5. 返回 `{unit_id: np.ndarray}` 字典

若缺少必要列（`stim_onset_imec_s`、`trial_valid`、`onset_time_ms`、`offset_time_ms`）或无 valid trials → 返回空 dict。

---

## 5. 公开 API

```python
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class ExportStage(BaseStage):
    """Three-phase export: NWB write → analysis CSV/H5 → background raw data.

    Phase 1 (seconds): units/trials/eye/KS4/behavior_events → NWB
    Phase 2 (seconds): raster.h5 + trial/unit CSV (analysis ready)
    Phase 3 (minutes, background): raw AP+LF+NIDQ compression → NWB append

    Preconditions (enforced at start of run()):
    - session.session_id is a fully-populated SessionID (4 fields).
    - Every probe in session.probes has a non-empty, non-"unknown" target_area,
      i.e. discover stage has already injected it from session.probe_plan.

    On Phase 1 failure: deletes partial NWB file before raising ExportError.
    Phase 3 failure does not affect analysis data already exported.

    Raises:
        ExportError: If any probe.target_area is "unknown" or empty, if Phase 1
            NWBWriter raises, or if the written file cannot be read.
    """

    STAGE_NAME = "export"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
        wait_for_raw: bool = True,
    ) -> None: ...

    def run(self) -> None:
        """Write all data to the output NWB file.

        Steps:
        1. Skip if stage checkpoint complete.
        2. Hard-validate every probe.target_area is non-empty and != "unknown".
        3. Run Phase 1 (NWB write), Phase 2.5 (derivatives), Phase 3 (raw + verify).

        Phase 3 behavior:
        - ``wait_for_raw=True`` (default, UI/CLI): blocks in caller thread;
          ``append_raw_data`` + ``verify_nwb`` with ``progress_callback``
          threaded through. On success writes checkpoint
          ``raw_data_verified_at`` + ``verify_policy="full"``.
        - ``wait_for_raw=False`` (legacy): daemon thread, no verify, checkpoint
          stays at Phase 2.5 completion.

        Raises:
            ExportError: On target_area precondition failure, on write failure,
                on bit-exact verification mismatch, or on file verification failure.
        """

    def _get_output_path(self) -> Path:
        """Compute the output NWB path from SessionID.

        Returns:
            ``session.output_dir / f"{session.session_id.canonical()}.nwb"``,
            e.g. ``.../251024_FanFan_nsd1w_MSB-V4.nwb``.

        Note:
            Output filename is derived from the canonical SessionID, not from
            ``session.session_dir.name``. The on-disk recording directory name
            does not influence NWB filename.
        """
```

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_export.py`

测试策略：mock `NWBWriter`（避免真实 pynwb 写盘）；mock `si.load`；用 `tmp_path`；mock `pynwb.NWBHDF5IO` 的打开验证。测试 fixture 中的 `session` 必须提供有效 `session_id`（`SessionID(date, subject, experiment, region)` 完整 4 字段），且每个 `ProbeInfo.target_area` 默认为有效脑区（如 `"MSB"`、`"V4"`）。

### 正常流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_creates_nwb_file` | 1 probe，有效 session | `NWBWriter.write()` 被调用 |
| `test_run_writes_checkpoint` | 成功 | `checkpoints/export.json` status=completed |
| `test_checkpoint_contains_nwb_path` | 成功 | checkpoint 含 `nwb_path` 字段，值以 `session_id.canonical()` 结尾 |
| `test_add_probe_data_called_per_probe` | 2 probes | `add_probe_data` 被调用 2 次 |
| `test_add_trials_called_once` | 正常 | `add_trials` 被调用 1 次 |
| `test_gc_called_after_each_probe` | 2 probes | `gc.collect` 被调用 2 次 |

### 输出路径（NWB 文件名规范）

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_output_path_uses_session_id_canonical` | `SessionID(date="251024", subject="FanFan", experiment="nsd1w", region="MSB-V4")` | `_get_output_path()` 返回 `output_dir/251024_FanFan_nsd1w_MSB-V4.nwb` |
| `test_output_path_ignores_session_dir_name` | `session_dir.name="exp_raw_g0"`，`session_id.canonical()="251024_FanFan_nsd1w_MSB-V4"` | 返回路径基名为 `251024_FanFan_nsd1w_MSB-V4.nwb`，**不**包含 `exp_raw_g0` |
| `test_checkpoint_nwb_path_matches_session_id` | 同上 | checkpoint `nwb_path` 字段与 `_get_output_path()` 一致 |

（**注**：旧的 `test_get_output_path`（断言 `session_dir.name` 作为文件名）应删除或改写为上面两个测试。现有 `tests/test_stages/test_export.py` 中依赖文件名 == `session_dir.name` 的断言全部更新为 `session_id.canonical()`。）

### target_area 硬校验（前置条件）

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_raises_if_probe_target_area_unknown` | 某 probe `target_area="unknown"` | raise `ExportError`，消息含 `"target_area='unknown'"`、`"discover stage"`、该 `probe_id`；`NWBWriter` 未被实例化、不进入 Phase 1 |
| `test_run_raises_if_probe_target_area_empty` | 某 probe `target_area=""` | raise `ExportError`，同上 |
| `test_run_proceeds_when_all_target_areas_valid` | 所有 probes `target_area="MSB"`/`"V4"` | 正常进入 Phase 1，`NWBWriter.create_file()` 被调用 |
| `test_target_area_check_runs_before_writer_init` | 某 probe `target_area=""` | 即使 `output_dir/sync/behavior_events.parquet` 不存在也直接 raise `ExportError`（不是 `FileNotFoundError`），证明校验在所有 I/O 之前 |

### 断点续跑

| 测试名 | 预期行为 |
|---|---|
| `test_skips_if_checkpoint_complete` | stage checkpoint complete → run() 立即返回，不调用 NWBWriter，也不做 target_area 校验（checkpoint 优先） |

### 错误处理（部分文件清理）

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_partial_nwb_deleted_on_write_failure` | `writer.write()` raise | `nwb_path.unlink(missing_ok=True)` 被调用 |
| `test_export_error_raised_on_write_failure` | `writer.write()` raise | raise `ExportError` |
| `test_failed_checkpoint_written_on_error` | Phase 1 任意失败 | `checkpoints/export.json` status=failed |
| `test_nwb_verification_failure_raises` | `NWBHDF5IO` 打开 raise | raise `ExportError`，文件被删除 |

### NWBWriter 调用顺序

| 测试名 | 预期行为 |
|---|---|
| `test_create_file_called_before_add_probe_data` | `create_file()` 先于 `add_probe_data()` 被调用 |
| `test_write_called_after_add_trials` | `write()` 在 `add_trials()` 之后调用 |

### Phase 3 进度回调（新增 TestPhase3Progress）

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_append_raw_data_accepts_progress_callback` | `writer.append_raw_data(..., progress_callback=cb)` | cb 至少被调用 1 次，参数为 `(message: str, fraction: float)` |
| `test_iterator_fires_callback_per_chunk` | 10-chunk recording + cb | cb 调用次数 >= chunks 数；fraction 单调递增 |
| `test_verify_nwb_fires_callback_per_chunk` | `verify_nwb(path, progress_callback=cb)` | cb 至少被调用 chunks 次，message 含 `verify` |
| `test_phase3_progress_covers_all_streams` | 2 probe AP+LF + nidq | callback message 包含 `append_ap_imec0` / `append_lf_imec0` / `append_nidq` / `verify_*` |
| `test_export_stage_wait_for_raw_true_by_default` | `ExportStage(session)` | `stage.wait_for_raw is True` |
| `test_run_blocks_until_phase3_done_when_wait_true` | wait_for_raw=True + mock append_raw_data 记录调用顺序 | `run()` 返回前 `append_raw_data` 已完成 + checkpoint `raw_data_verified_at` 非空 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.ExportError` | 项目内部 | target_area 校验失败或写入失败时抛出 |
| `pynpxpipe.core.session.Session` | 项目内部 | TYPE_CHECKING；读取 `session_id`、`probes[*].target_area` 等字段（不新增 `io.spikeglx` 导入） |
| `pynpxpipe.io.nwb_writer.NWBWriter` | 项目内部 | NWB 文件组装与写盘 |
| `pynpxpipe.io.bhv.BHV2Parser` | 项目内部 | 眼动数据读取 |
| `spikeinterface.core` | 第三方 | `load`（加载 SortingAnalyzer，SI ≥0.101） |
| `pynwb` | 第三方 | `NWBHDF5IO`（验证可读） |
| `neuroconv` | 第三方 | `SpikeGLXConverterPipe`（Phase 3 原始数据写入） |
| `pandas` | 第三方 | 读取 behavior_events.parquet |
| `threading` | 标准库 | Phase 3 `wait_for_raw=False` legacy daemon |
| `tqdm` | 第三方 | CLI 进度条（Phase 3 chunk-level），同时把每个更新行通过 logger 汇出 |
| `gc` | 标准库 | 显式内存释放 |

---

## 8. 附录 A：NWB 输出结构（完整版）

> 搬迁自 architecture.md Section 5（原 lines 912-982）

多 probe 数据在单个 NWB 文件中的组织方式：

```
NWBFile
├── .identifier               UUID（session 唯一标识）
├── .session_description      "pynpxpipe processed: {session_id.canonical()}"
├── .session_start_time       从 SpikeGLX meta 中的 fileCreateTime 字段读取
├── .timestamps_reference_time session_start_time（所有时间戳相对此时刻，单位秒）
│
├── .subject                  NWBSubject
│     .subject_id             "MaoDan"
│     .description            "good monkey"
│     .species                "Macaca mulatta"
│     .sex                    "M"
│     .age                    "P4Y"
│     .weight                 "12.8kg"
│
├── .electrode_groups         dict[str, ElectrodeGroup]（每个 probe 一个）
│     "imec0": ElectrodeGroup
│           .name             "imec0"
│           .description      "Neuropixels 1.0, SN: XXXXX"
│           .location         "Area_V1"（从 probe.target_area 读取，由 discover stage 从 probe_plan 注入）
│           .device           Device（"Neuropixels 1.0"）
│     "imec1": ElectrodeGroup
│           ...
│
├── .electrodes               DynamicTable（所有 probe 的电极合并）
│     列：x, y, z             float（探针坐标系中的位置，μm）
│         group               引用 electrode_groups 中的对象
│         group_name          str（"imec0" | "imec1"）
│         probe_id            str（冗余列，便于查询）
│         channel_id          int（probe 内通道编号）
│
├── .units                    Units DynamicTable（所有 probe 的 unit 合并）
│     必选列：
│         spike_times          VectorData[float]（每个 unit 的 spike 时间序列，秒）
│         spike_times_index    VectorIndex（CSC 格式索引）
│         probe_id             str（"imec0" | "imec1"）
│         electrode_group      引用对应的 ElectrodeGroup
│     quality metric 列：
│         isi_violation_ratio  float
│         amplitude_cutoff     float
│         presence_ratio       float
│         snr                  float
│         slay_score           float（SLAY 可靠性分数）
│         is_visual            bool（Mann-Whitney U 视觉响应标记）
│         unittype_string      str（"SUA"/"MUA"/"NON-SOMA"）
│     波形列：
│         waveform_mean        array，shape (n_samples × n_channels)，单位 μV
│         waveform_std         array，shape (n_samples × n_channels)
│         unit_location        array，shape (3,)，单位 μm（探针坐标系）
│
├── .trials                   TimeIntervals DynamicTable
│     start_time              float（trial onset，NIDQ 时钟秒）
│     stop_time               float（trial offset，NIDQ 时钟秒）
│     stim_onset_time         float（stimulus onset，NIDQ 时钟秒）
│     trial_id                int（BHV2 trial 编号）
│     condition_id            int（刺激条件编号）
│     trial_valid             bool（眼动验证通过）
│     onset_time_ms           float（刺激 ON 持续时间 ms，来自 BHV2）
│     offset_time_ms          float（ISI 时间 ms，来自 BHV2）
│     stim_name               str（刺激图像文件名）
│     stim_index              int（刺激序号，1-based）
│     dataset_name            str（BHV2 DatasetName）
│
├── .processing["behavior"]   ProcessingModule
│     └── "EyeTracking"       EyeTracking 容器
│           └── "right_eye_position"  SpatialSeries (n_timepoints, 2)，unit="degrees"
│
├── .processing["ecephys"]    ProcessingModule
│     ├── "kilosort4_imec0"   KS4 完整排序结果（spike_times, spike_templates, amplitudes）
│     ├── "kilosort4_imec1"   ...
│     └── "LFP"               LFP 对象（接口已预留，方法体为 NotImplementedError）
│
├── .acquisition（Phase 3 后台写入）
│     ├── "ElectricalSeriesAP" 原始 AP 数据（30kHz, int16, Blosc zstd 压缩）
│     └── "ElectricalSeriesLF" 原始 LF 数据（2.5kHz, int16, Blosc zstd 压缩）
└──
```
