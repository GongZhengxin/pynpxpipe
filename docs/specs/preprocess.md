# Spec: stages/preprocess.py

## 1. 目标

实现 pipeline 第二个 stage：**预处理（Preprocess）**。

对每个 IMEC probe 的 AP 数据流串行执行：坏通道检测 → 带通滤波 → 公共中值参考（CMR）→ 运动校正（可选）→ 保存为 Zarr 格式。每个 probe 处理完成后写 per-probe checkpoint 并释放内存（`del recording; gc.collect()`）。

内存安全是核心约束：AP bin 文件可达 400-500GB，禁止一次性加载，必须通过 SpikeInterface lazy recording 处理。

---

## 2. 输入

### `PreprocessStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `probes`（已由 discover 填充）、`output_dir`、`config` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调，CLI 为 None |

### `session.config` 中读取的配置键

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `config.pipeline.preprocess.freq_min` | `float` | `300.0` | 带通滤波低截止频率（Hz） |
| `config.pipeline.preprocess.freq_max` | `float` | `6000.0` | 带通滤波高截止频率（Hz） |
| `config.pipeline.preprocess.motion_correction.method` | `str \| None` | `None` | 运动校正方法，`None` 表示跳过；支持 `"dredge"` 等 SpikeInterface 内置方法 |
| `config.pipeline.n_jobs` | `int \| str` | `"auto"` | SpikeInterface 内部并行 job 数；`"auto"` 由 ResourceDetector 在 runner 层解析 |
| `config.pipeline.chunk_duration` | `str` | `"1s"` | SpikeInterface 分块处理时间窗（如 `"1s"`、`"30s"`） |

---

## 3. 输出

### 每个 probe 的输出

| 输出 | 路径 | 说明 |
|---|---|---|
| 预处理后 Zarr 录制 | `{output_dir}/preprocessed/{probe_id}/` | lazy SpikeInterface recording，可被 sort stage 直接读取 |
| per-probe checkpoint | `{output_dir}/checkpoints/preprocess_{probe_id}.json` | 含处理参数和通道数量 |

### per-probe checkpoint payload

```json
{
  "probe_id": "imec0",
  "n_channels_original": 384,
  "n_channels_after_bad_removal": 380,
  "n_bad_channels": 4,
  "freq_min": 300.0,
  "freq_max": 6000.0,
  "motion_correction_method": null,
  "zarr_path": "/output/preprocessed/imec0"
}
```

---

## 4. 处理步骤

### `run()`

1. 检查 stage 级 checkpoint（`_is_complete()`）；若完成 → 报告并 return（note：stage 级 checkpoint 记录"所有 probe 已处理"，per-probe checkpoint 控制单个 probe 跳过）
2. `_report_progress("Starting preprocess", 0.0)`
3. 对 `session.probes` 按顺序遍历（`enumerate`），对每个 probe 调用 `_preprocess_probe(probe_id)`
4. 每个 probe 完成后 `_report_progress(f"Preprocessed {probe_id}", (i+1)/n_probes)`
5. 所有 probe 完成后 `_write_checkpoint({"probe_ids": [...]})` （stage 级）
6. `_report_progress("Preprocess complete", 1.0)`

若某个 probe 的 `_preprocess_probe` raise `PreprocessError`：
- 调用 `_write_failed_checkpoint(error, probe_id=probe_id)`
- re-raise（pipeline 中断）

### `_preprocess_probe(probe_id)`

1. **检查 per-probe checkpoint**：`_is_complete(probe_id=probe_id)` → 若已完成则 skip 并 return
2. **懒加载 AP 录制**：`SpikeGLXLoader(session).load_ap(probe_id)` → 返回 lazy `si.BaseRecording`（不读取数据）
3. **Phase shift 校正**（Neuropixels 必须步骤，必须在任何滤波之前）：
   `recording = si.phase_shift(recording)`
   — 校正 Neuropixels 时分多路复用 ADC 的通道间采样时间偏移；若放在滤波后会导致 CMR 效果变差
4. **带通滤波**：`recording = si.bandpass_filter(recording, freq_min=..., freq_max=...)`（均从 config 读取，禁止硬编码）
5. **坏通道检测**（在滤波后检测，coherence+psd 更准确）：
   `bad_channel_ids, channel_labels = si.detect_bad_channels(recording, method="coherence+psd")`
6. **移除坏通道**：若有坏通道，`recording = recording.remove_channels(bad_channel_ids)`
7. **公共中值参考（CMR）**：`recording = si.common_reference(recording, reference="global", operator="median")`
   — 坏道已移除后再做 CMR，避免污染参考信号
8. **运动校正（可选）**：若 `config.pipeline.preprocess.motion_correction.method is not None` → 调用 `si.correct_motion(recording, preset=method)` （或对应 API）；若方法不支持则 raise `PreprocessError`
   — 注意：启用此步时 sort 阶段 Kilosort4 的 `nblocks` 必须设为 0，不能双重校正
9. **保存为 Zarr**：
   ```python
   zarr_path = output_dir / "preprocessed" / probe_id
   recording.save(folder=zarr_path, format="zarr", chunk_duration=..., n_jobs=...)
   ```
   若磁盘空间不足或权限失败 → raise `PreprocessError("Failed to save Zarr for {probe_id}: {e}")`
10. **写 per-probe checkpoint**：`_write_checkpoint(payload, probe_id=probe_id)`
11. **释放内存**：`del recording; import gc; gc.collect()`

---

## 5. 公开 API

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class PreprocessStage(BaseStage):
    """Applies preprocessing pipeline to each probe's AP recording.

    Processing order per probe (phase_shift MUST be first):
        phase_shift → bandpass_filter → detect_bad_channels →
        remove_bad_channels → CMR → motion_correction (optional) → Zarr save.

    Phase shift corrects Neuropixels time-division multiplexed ADC offsets;
    it must precede any filtering to avoid degrading CMR effectiveness.
    Each probe processed serially. Memory released between probes (del + gc.collect).
    AP recordings are never fully loaded into memory (SpikeInterface lazy).

    Raises:
        PreprocessError: If Zarr save fails (disk full, permissions) or
            motion correction method is unsupported.
    """

    STAGE_NAME = "preprocess"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None: ...

    def run(self) -> None:
        """Preprocess all probes serially.

        For each probe (skipping those with completed per-probe checkpoint):
        1. Load AP recording lazily via SpikeGLXLoader.
        2. Phase shift (Neuropixels ADC timing correction — FIRST step).
        3. Bandpass filter (freq_min, freq_max from config).
        4. Detect and remove bad channels (on filtered data).
        5. Common median reference.
        6. Motion correction if config.preprocess.motion_correction.method not None.
        7. Save to Zarr at {output_dir}/preprocessed/{probe_id}/.
        8. Write per-probe checkpoint; del recording + gc.collect().

        Raises:
            PreprocessError: If Zarr write fails or motion correction unsupported.
        """

    def _preprocess_probe(self, probe_id: str) -> None:
        """Run the full preprocessing pipeline for one probe.

        Args:
            probe_id: Probe identifier (e.g. "imec0").

        Raises:
            PreprocessError: On unrecoverable processing failure.
        """
```

### 可配参数

| 参数 | 配置键 | 默认值 | 说明 |
|---|---|---|---|
| `freq_min` | `config.pipeline.preprocess.freq_min` | `300.0` | 带通滤波低截止（Hz），**禁止硬编码** |
| `freq_max` | `config.pipeline.preprocess.freq_max` | `6000.0` | 带通滤波高截止（Hz），**禁止硬编码** |
| `motion_method` | `config.pipeline.preprocess.motion_correction.method` | `None` | `None` 跳过，`"dredge"` 启用 DREDge；启用时 sort 阶段 KS4 `nblocks` 必须为 0 |
| `n_jobs` | `config.pipeline.n_jobs` | `"auto"` | SpikeInterface job 数（runner 层已解析 "auto"） |
| `chunk_duration` | `config.pipeline.chunk_duration` | `"1s"` | 分块时间窗 |

注：`phase_shift` 无可配参数，始终执行（Neuropixels 硬件固定的 ADC 偏移特性决定此步不可跳过）。

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_preprocess.py`

测试策略：用 `unittest.mock.patch` mock `SpikeGLXLoader.load_ap` 返回一个合成 si.NumpyRecording（小数据，不写真实大文件）；mock `si.detect_bad_channels`、`si.bandpass_filter`、`si.common_reference`、`recording.save` 等 SpikeInterface API。用 `tmp_path` 作为 output_dir。

### 正常流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_processes_all_probes` | 2 probes，全部成功 | `_preprocess_probe` 对每个 probe 被调用一次 |
| `test_run_writes_stage_checkpoint` | 所有 probe 成功 | `checkpoints/preprocess.json` status=completed |
| `test_probe_checkpoint_written_per_probe` | 2 probes | `checkpoints/preprocess_imec0.json` 和 `_imec1.json` 均存在 |
| `test_zarr_saved_to_correct_path` | probe_id="imec0" | `recording.save` 调用路径含 `preprocessed/imec0` |
| `test_bad_channels_removed` | `detect_bad_channels` 返回 2 个坏通道 | `remove_channels` 被调用 |
| `test_no_bad_channels_skips_removal` | `detect_bad_channels` 返回空列表 | `remove_channels` 未被调用 |
| `test_phase_shift_called` | 任意 probe | `si.phase_shift` 被调用一次 |
| `test_phase_shift_before_bandpass` | 检查调用顺序 | `si.phase_shift` 的调用在 `si.bandpass_filter` 之前 |
| `test_motion_correction_called_when_configured` | `motion_method="dredge"` | `si.correct_motion` 被调用 |
| `test_motion_correction_skipped_when_none` | `motion_method=None` | `si.correct_motion` 未被调用 |
| `test_gc_collect_called_after_probe` | 任意 | `gc.collect` 在每个 probe 完成后被调用 |

### 断点续跑（per-probe checkpoint 跳过）

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_skips_already_preprocessed_probe` | imec0 checkpoint 已 complete | `load_ap` 对 imec0 未被调用 |
| `test_processes_remaining_probe_after_skip` | imec0 完成，imec1 未完成 | imec1 被正常处理 |
| `test_stage_skips_if_all_probes_complete` | stage 级 checkpoint 已 complete | 整个 run() 立即返回 |

### 错误处理

| 测试名 | 输入构造 | 预期异常 |
|---|---|---|
| `test_zarr_save_failure_raises_preprocess_error` | `recording.save` raise IOError | raise `PreprocessError` |
| `test_failed_probe_checkpoint_written` | save 失败 | `checkpoints/preprocess_imec0.json` status=failed |
| `test_preprocess_error_propagates` | 第一个 probe 失败 | run() re-raise `PreprocessError` |

### 配置参数

| 测试名 | 预期行为 |
|---|---|
| `test_bandpass_freq_from_config` | `si.bandpass_filter` 以 config 中 freq_min/freq_max 调用 |
| `test_n_jobs_passed_to_save` | `recording.save` 以 config 中 n_jobs 调用 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.PreprocessError` | 项目内部 | 预处理失败时抛出 |
| `pynpxpipe.io.spikeglx.SpikeGLXLoader` | 项目内部 | lazy AP 录制加载 |
| `spikeinterface.preprocessing` | 第三方 | `detect_bad_channels`、`bandpass_filter`、`common_reference`、`correct_motion` |
| `gc` | 标准库 | 显式 GC 释放内存 |
| `pathlib.Path` | 标准库 | 路径操作 |

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #13（AP 预处理 + KS4 启动） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #13 段落 |
| **ADR 关联** | ADR-002（phase_shift 必须在 bandpass 之前） |

### MATLAB 算法概要

MATLAB step #13 将预处理与 sorting 合并在同一步骤中执行。预处理链在 CatGT 或自定义脚本中完成，随后直接启动 KS4。

### 有意偏离

| 偏离 | 理由 |
|------|------|
| phase_shift 作为第一步执行（ADR-002） | 旧 Python 代码中 phase_shift 在 highpass_filter 之后（错误顺序），已修正；MATLAB 使用 CatGT 做时间对齐，不直接调用 SpikeInterface phase_shift |
| 预处理与 sorting 拆分为两个独立 stage | MATLAB 合并执行；Python 拆分后可独立断点续跑，且支持 import 模式导入外部 sorting |
| 坏通道检测使用 coherence+psd 方法 | MATLAB 手动指定坏通道列表；Python 自动检测更鲁棒 |
| CMR 在坏道移除后执行 | MATLAB 无明确的坏道移除步骤；Python 先移除坏道再做 CMR 避免污染参考信号 |
| 输出为 Zarr 格式 | MATLAB 输出 binary 文件；Zarr 支持 SpikeInterface lazy 加载，节省内存 |
