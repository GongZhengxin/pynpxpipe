# Spec: stages/export.py

## 1. 目标

实现 pipeline 第七个（最后一个）stage：**导出（Export）**。

将所有 probe 的处理结果、行为事件和 session 元信息整合写入单一 DANDI 兼容的 NWB 2.x 文件。调用 `io/nwb_writer.py` 中的 `NWBWriter` 完成实际格式组装，本 stage 仅负责编排（加载各 probe 的 SortingAnalyzer、调用 NWBWriter 接口、内存管理）。

**错误处理**：若写出 NWB 过程中发生异常，删除不完整的部分文件（`unlink(missing_ok=True)`），再 re-raise `ExportError`。

---

## 2. 输入

### `ExportStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `probes`、`output_dir`、`subject`、`config` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调 |

### 外部数据依赖

| 文件/目录 | 路径 | 说明 |
|---|---|---|
| SortingAnalyzer（每个 probe） | `{output_dir}/postprocessed/{probe_id}/` | 含 waveforms/templates/unit_locations 扩展 |
| SLAY 分数 | `{output_dir}/postprocessed/{probe_id}/slay_scores.json` | 由 postprocess stage 写出 |
| behavior_events.parquet | `{output_dir}/sync/behavior_events.parquet` | 含 trial 事件表 |

---

## 3. 输出

| 输出 | 路径 | 说明 |
|---|---|---|
| NWB 文件 | `{output_dir}/{session_dir.name}.nwb` | DANDI 兼容 NWB 2.x |
| stage checkpoint | `{output_dir}/checkpoints/export.json` | 含文件路径和统计数量 |

### stage checkpoint payload

```json
{
  "nwb_path": "/output/exp_20260101.nwb",
  "n_probes": 2,
  "n_units_total": 174,
  "n_trials": 120
}
```

---

## 4. 处理步骤

### `run()`

1. 检查 stage 级 checkpoint；若完成 → return
2. `_report_progress("Starting export", 0.0)`
3. 计算输出 NWB 路径：`nwb_path = _get_output_path()`
4. **初始化 NWBWriter**：`writer = NWBWriter(session, nwb_path)`
5. **创建 NWBFile**：`writer.create_file()`（读取 ap.meta 的 fileCreateTime，验证 subject 字段）
6. **逐 probe 写入**（串行，含内存释放）：
   ```
   for probe in session.probes:
       analyzer = si.load_extractor(postprocessed/{probe_id}/)
       # 注入 SLAY 分数到 analyzer（自定义 extension 或直接读 JSON 后挂载）
       writer.add_probe_data(probe, analyzer)
       del analyzer; gc.collect()
       _report_progress(f"Exported {probe_id}", ...)
   ```
7. **写入 trials 表**：
   - 读取 `behavior_events.parquet`
   - 提取 `trial_id, onset_nidq_s, stim_onset_nidq_s, condition_id, trial_valid` 列
   - `writer.add_trials(behavior_events_df[...])`
8. **写出 NWB 文件**：`nwb_path_written = writer.write()`
9. **验证文件可读**：`pynwb.NWBHDF5IO(nwb_path_written, "r")` 打开再关闭（验证 HDF5 格式完整）；若失败 → raise `ExportError`
10. **统计并写 checkpoint**：`n_units_total = sum(n_units per probe)`、`n_trials = len(behavior_events_df)`
11. `_report_progress("Export complete", 1.0)`

若步骤 5-9 中任何一步 raise：
- `nwb_path.unlink(missing_ok=True)`（删除不完整文件）
- `_write_failed_checkpoint(error)`
- re-raise 为 `ExportError`

### `_get_output_path() -> Path`

```python
return session.output_dir / f"{session.session_dir.name}.nwb"
```

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
    """Writes all pipeline outputs to a single NWB 2.x file.

    Processes probes one at a time to control memory:
    load analyzer → write to NWB → del + gc.collect.

    On write failure: deletes partial NWB file before raising ExportError.
    NWB file is verified readable (NWBHDF5IO round-trip) before checkpoint.

    Raises:
        ExportError: If NWBWriter raises, or if the written file cannot be read.
    """

    STAGE_NAME = "export"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None: ...

    def run(self) -> None:
        """Write all data to the output NWB file.

        Raises:
            ExportError: On write failure or file verification failure.
        """

    def _get_output_path(self) -> Path:
        """Compute the output NWB path: {output_dir}/{session_dir.name}.nwb."""
```

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_export.py`

测试策略：mock `NWBWriter`（避免真实 pynwb 写盘）；mock `si.load_extractor`；用 `tmp_path`；mock `pynwb.NWBHDF5IO` 的打开验证。

### 正常流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_creates_nwb_file` | 1 probe，有效 session | `NWBWriter.write()` 被调用 |
| `test_run_writes_checkpoint` | 成功 | `checkpoints/export.json` status=completed |
| `test_checkpoint_contains_nwb_path` | 成功 | checkpoint 含 `nwb_path` 字段 |
| `test_add_probe_data_called_per_probe` | 2 probes | `add_probe_data` 被调用 2 次 |
| `test_add_trials_called_once` | 正常 | `add_trials` 被调用 1 次 |
| `test_gc_called_after_each_probe` | 2 probes | `gc.collect` 被调用 2 次 |
| `test_get_output_path` | `session_dir.name="exp_20260101"` | 返回 `output_dir/exp_20260101.nwb` |

### 断点续跑

| 测试名 | 预期行为 |
|---|---|
| `test_skips_if_checkpoint_complete` | stage checkpoint complete → run() 立即返回，不调用 NWBWriter |

### 错误处理（部分文件清理）

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_partial_nwb_deleted_on_write_failure` | `writer.write()` raise | `nwb_path.unlink(missing_ok=True)` 被调用 |
| `test_export_error_raised_on_write_failure` | `writer.write()` raise | raise `ExportError` |
| `test_failed_checkpoint_written_on_error` | 任意失败 | `checkpoints/export.json` status=failed |
| `test_nwb_verification_failure_raises` | `NWBHDF5IO` 打开 raise | raise `ExportError`，文件被删除 |

### NWBWriter 调用顺序

| 测试名 | 预期行为 |
|---|---|
| `test_create_file_called_before_add_probe_data` | `create_file()` 先于 `add_probe_data()` 被调用 |
| `test_write_called_after_add_trials` | `write()` 在 `add_trials()` 之后调用 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.ExportError` | 项目内部 | 导出失败时抛出 |
| `pynpxpipe.io.nwb_writer.NWBWriter` | 项目内部 | NWB 文件组装与写盘 |
| `spikeinterface.core` | 第三方 | `load_extractor`（加载 SortingAnalyzer） |
| `pynwb` | 第三方 | `NWBHDF5IO`（验证可读） |
| `pandas` | 第三方 | 读取 behavior_events.parquet |
| `gc` | 标准库 | 显式内存释放 |
| `json` | 标准库 | 读取 slay_scores.json |
| `pathlib.Path` | 标准库 | 路径操作 |

---

## 8. 附录 A：NWB 输出结构（完整版）

> 搬迁自 architecture.md Section 5（原 lines 912-982）

多 probe 数据在单个 NWB 文件中的组织方式：

```
NWBFile
├── .identifier               UUID（session 唯一标识）
├── .session_description      "pynpxpipe processed: {session_id}"
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
│           .location         "Area_V1"（从配置或探针信息读取）
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
│     trial_valid             bool（眼动验证通过，来自 BHV2 或后处理）
│
├── .processing["behavior"]   ProcessingModule
│     └── "BehavioralTimeSeries"  BehavioralTimeSeries（预留，可含眼动 SpatialSeries）
│
└── .processing["ecephys"]    ProcessingModule（预留 LFP）
      └── "LFP"               LFP 对象（接口已预留，方法体为 NotImplementedError）
```

**多 probe 数据的 units table 示例**：

| unit_id | probe_id | spike_times | isi_violation_ratio | slay_score | waveform_mean |
|---------|----------|-------------|--------------------:|----------:|---------------|
| 0 | imec0 | [0.12, 0.45, ...] | 0.02 | 0.85 | array(...) |
| 1 | imec0 | [0.08, 0.33, ...] | 0.05 | 0.72 | array(...) |
| ... | ... | ... | ... | ... | ... |
| 87 | imec1 | [0.15, 0.42, ...] | 0.01 | 0.91 | array(...) |
