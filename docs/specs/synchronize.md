# Spec: stages/synchronize.py

## 1. 目标

实现 pipeline 第四个 stage：**同步（Synchronize）**。

执行三级时间对齐：
1. **第一级**：每个 IMEC probe 的 AP 时钟 ↔ NIDQ 时钟线性对齐
2. **第二级**：BHV2 行为事件 ↔ NIDQ 事件码对齐，提取 trial 级事件表
3. **第三级**：Photodiode 模拟信号校准，精确检测 stimulus onset 延迟

本 stage 属于 stages 层编排层，实际对齐逻辑在 `io/sync/` 子模块中。输出 `sync_tables.json` 和 `behavior_events.parquet`，供 postprocess（SLAY）和 export 阶段使用。

本 stage 使用**单一 stage 级 checkpoint**（非 per-probe），因为三级对齐高度耦合。

---

## 2. 输入

### `SynchronizeStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `probes`、`bhv_file`、`output_dir`、`config` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调 |

### `session.config` 中读取的配置键

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `config.sync.sync_bit` | `int` | `6` | AP/NIDQ 数字通道中 sync 脉冲的 bit 位，**禁止硬编码** |
| `config.sync.event_bits` | `list[int]` | `[0,1,2,3,4,5,6,7]` | NIDQ 数字通道中用于事件码解码的 bit 列表 |
| `config.sync.max_time_error_ms` | `float` | `17.0` | 对齐误差上限（ms） |
| `config.sync.trial_count_tolerance` | `int` | `2` | BHV2/NIDQ trial 数量允许差异 |
| `config.sync.stim_onset_code` | `int` | — | Stimulus onset 事件码值，**禁止硬编码** |
| `config.sync.trial_start_bit` | `int \| None` | `None` | trial start 的 NIDQ bit；None 时自动检测 |
| `config.sync.photodiode_channel_index` | `int` | — | NIDQ 模拟通道中 photodiode 的通道索引，**禁止硬编码** |
| `config.sync.monitor_delay_ms` | `float` | `0.0` | 显示器延迟校正量（ms），**禁止硬编码** |
| `config.sync.gap_threshold_ms` | `float \| None` | `1200.0` | 丢脉冲检测阈值（ms），传递给 `align_imec_to_nidq`。`None` 禁用修复。 |
| `config.sync.pd_window_pre_ms` | `float` | `10.0` | Photodiode 基线窗口（ms） |
| `config.sync.pd_window_post_ms` | `float` | `100.0` | Photodiode 检测窗口（ms） |
| `config.sync.generate_plots` | `bool` | `True` | 是否生成诊断图 |

---

## 3. 输出

### 文件输出

| 输出 | 路径 | 说明 |
|---|---|---|
| 同步参数表 | `{output_dir}/sync/sync_tables.json` | 每个 probe 的线性对齐参数 |
| 行为事件表 | `{output_dir}/sync/behavior_events.parquet` | 统一 NIDQ 时钟的逐 trial 事件 |
| 诊断图（可选） | `{output_dir}/sync/figures/` | 6 张 PNG，由 `io/sync_plots.py` 生成 |
| stage checkpoint | `{output_dir}/checkpoints/synchronize.json` | 单一 stage 级 |

### `sync_tables.json` 结构

```json
{
  "probes": {
    "imec0": {"a": 1.0000001, "b": 0.0023, "residual_ms": 0.042, "n_repaired": 0},
    "imec1": {"a": 0.9999998, "b": -0.0015, "residual_ms": 0.037, "n_repaired": 1}
  },
  "dataset_name": "exp_20260101",
  "n_trials": 120,
  "bhv_metadata": {"TotalTrials": 120, "DatasetName": "exp_20260101"}
}
```

### `behavior_events.parquet` 列

| 列名 | 类型 | 说明 |
|---|---|---|
| `trial_id` | `int` | BHV2 trial 编号（1-indexed） |
| `onset_nidq_s` | `float` | trial onset，NIDQ 时钟秒 |
| `stim_onset_nidq_s` | `float` | stimulus onset（数字码），NIDQ 时钟秒 |
| `stim_onset_imec_s` | `str` (JSON) | 每个 probe 的 IMEC 时钟 onset，格式 `{"imec0": 1.023, "imec1": 1.021}` |
| `condition_id` | `int` | 刺激条件编号 |
| `trial_valid` | `float` | NaN（占位，postprocess 阶段填写） |
| `onset_latency_ms` | `float` | Photodiode 检测到的延迟（ms），NaN 表示跳过 |
| `quality_flag` | `int` | Photodiode 质量标志（0=good, 1=negative, 2=bounds, 3=low_signal） |
| `dataset_name` | `str` | BHV2 DatasetName（每行相同） |

### stage checkpoint payload

```json
{
  "n_probes": 2,
  "probe_ids": ["imec0", "imec1"],
  "n_trials": 120,
  "n_suspicious_pd": 3,
  "dataset_name": "exp_20260101"
}
```

---

## 4. 处理步骤

### `run()`

1. 检查 stage 级 checkpoint；若完成 → return
2. `_report_progress("Starting synchronize", 0.0)`
3. **提取 NIDQ sync 脉冲时间**：`SpikeGLXLoader.load_nidq(session)` → lazy NIDQ recording；从 NIDQ 数字通道按 `config.sync.sync_bit` 提取上升沿时间 → `nidq_sync_times`
4. **第一级：逐 probe 对齐**：对每个 probe 调用 `_align_probe_to_nidq(probe_id, nidq_sync_times)` → 收集 `sync_results` dict；`_report_progress("Level 1 complete", 0.33)`
5. **解码 NIDQ 事件码**：调用 `_decode_nidq_events(nidq_recording, event_bits, sample_rate)` → `(nidq_event_times, nidq_event_codes)`
6. **第二级：BHV2↔NIDQ 对齐**：调用 `_align_bhv2_to_nidq(nidq_event_times, nidq_event_codes)` → `TrialAlignment`；`_report_progress("Level 2 complete", 0.55)`
7. **第三级：Photodiode 校准**：
   - 从 NIDQ 模拟通道按 `config.sync.photodiode_channel_index` 提取信号（`int16` lazy，逐块读取避免大内存）
   - 从 nidq.meta 读取 `sample_rate_hz`（`niSampRate`）和 `voltage_range`（`niAiRangeMax`），**禁止硬编码**
   - 调用 `calibrate_photodiode(...)` → `CalibratedOnsets`
   - `_report_progress("Level 3 complete", 0.75)`
8. **将 IMEC 时钟 onset 写入 stim_onset_imec_s**：对每个 probe，用 `sync_result.a, sync_result.b` 将 `stim_onset_nidq_s` 转换为 IMEC 时钟；序列化为 JSON 字符串（每个 trial 一行）
9. **构建 behavior_events DataFrame**：合并 trial 表 + photodiode 校准结果
10. **写 `sync_tables.json`**：JSON dump，`mkdir(parents=True, exist_ok=True)`
11. **写 `behavior_events.parquet`**：`df.to_parquet(..., engine="pyarrow")`
12. **生成诊断图（可选）**：若 `config.sync.generate_plots`，调用 `generate_all_plots(...)` 传入各级结果；函数内 matplotlib 缺失时静默返回
13. **写 stage checkpoint**
14. `_report_progress("Synchronize complete", 1.0)`

若任何步骤 raise `SyncError`：`_write_failed_checkpoint(error)` 后 re-raise。

### `_align_probe_to_nidq(probe_id, nidq_sync_times)`

1. 从 `{output_dir}/preprocessed/{probe_id}/` 加载 Zarr recording（或直接从原始 AP 文件）
2. 从 AP 数字通道按 `config.sync.sync_bit` 提取上升沿 → `ap_sync_times`（用 `SpikeGLXLoader.extract_sync_edges` 或 `np.diff` 方法）
3. 调用 `align_imec_to_nidq(probe_id, ap_sync_times, nidq_sync_times, max_time_error_ms=config.sync.max_time_error_ms, gap_threshold_ms=config.sync.gap_threshold_ms)` → `SyncResult`
4. 返回 `(ap_sync_times, SyncResult)`（ap_sync_times 供诊断图使用）

### `_align_bhv2_to_nidq(nidq_event_times, nidq_event_codes)`

1. 构建 `BHV2Parser(session.bhv_file)` 实例
2. 调用 `align_bhv2_to_nidq(bhv_parser, nidq_event_times, nidq_event_codes, stim_onset_code=..., trial_start_bit=..., max_time_error_ms=..., trial_count_tolerance=...)` → `TrialAlignment`
3. 返回 `TrialAlignment`

### `_decode_nidq_events(nidq_recording, event_bits, sample_rate)`

从 NIDQ digital channel 解码 MonkeyLogic 多 bit 事件码：
1. 读取指定 bit 列表对应的 NIDQ 数字通道数据（lazy 分块读取，避免 OOM）
2. 在每个样本点，将各 bit 值组合为整数（`sum(bit_val << i for i, bit_val in enumerate(bits))`）
3. 找出值变化的样本点（`np.where(np.diff(code_values) != 0)`）→ transition 事件
4. 转换为时间（秒）：`event_times = transition_samples / sample_rate`
5. 返回 `(event_times_s, event_codes)` 两个 1D numpy 数组

---

## 5. 公开 API

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd

    from pynpxpipe.core.session import Session


class SynchronizeStage(BaseStage):
    """Aligns all data streams to NIDQ clock and extracts behavioral events.

    Three-level alignment:
    1. IMEC ↔ NIDQ: linear regression per probe (t_nidq = a*t_imec + b).
    2. BHV2 ↔ NIDQ: MonkeyLogic event codes matched to BHV2 trials.
    3. Photodiode: calibrates stim onset times from analog photodiode signal.

    Outputs: sync_tables.json, behavior_events.parquet, optional figures/.
    Uses single stage-level checkpoint (not per-probe).

    Raises:
        SyncError: If any alignment error exceeds max_time_error_ms, trial count
            mismatch exceeds tolerance, or photodiode signal is dead.
    """

    STAGE_NAME = "synchronize"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None: ...

    def run(self) -> None: ...

    def _align_probe_to_nidq(
        self,
        probe_id: str,
        nidq_sync_times: np.ndarray,
    ) -> tuple[np.ndarray, object]:
        """Fit linear time correction for one probe.

        Returns:
            (ap_sync_times, SyncResult) tuple.
        """

    def _align_bhv2_to_nidq(
        self,
        nidq_event_times: np.ndarray,
        nidq_event_codes: np.ndarray,
    ) -> object:
        """Align BHV2 events to NIDQ clock.

        Returns:
            TrialAlignment dataclass.
        """

    def _decode_nidq_events(
        self,
        nidq_recording,
        event_bits: list[int],
        sample_rate: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Decode MonkeyLogic event codes from NIDQ digital bits.

        Returns:
            (event_times_s, event_codes) numpy arrays.
        """
```

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_synchronize.py`

测试策略：mock IO 层子模块（`align_imec_to_nidq`、`align_bhv2_to_nidq`、`calibrate_photodiode`、`generate_all_plots`、`SpikeGLXLoader`）；使用小型合成数组。

### 正常流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_writes_sync_tables_json` | 2 probes，全部成功 | `sync/sync_tables.json` 存在，含两个 probe 的 a/b/residual |
| `test_run_writes_behavior_events_parquet` | 有效 trial 对齐 | `sync/behavior_events.parquet` 存在，可被 pandas 读取 |
| `test_behavior_events_columns` | 正常 | parquet 含所有必须列 |
| `test_stim_onset_imec_s_computed_per_probe` | 2 probes，a=1.0, b=0.0 | `stim_onset_imec_s` 列包含每个 probe 的值 |
| `test_run_writes_checkpoint` | 成功 | `checkpoints/synchronize.json` status=completed |
| `test_generate_plots_called_when_configured` | `generate_plots=True` | `generate_all_plots` 被调用 |
| `test_generate_plots_skipped_when_disabled` | `generate_plots=False` | `generate_all_plots` 未被调用 |

### `_decode_nidq_events`

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_decode_single_bit_events` | bit=1 只有一位，3 次跳变 | 返回 3 个事件时间和编码 |
| `test_decode_multi_bit_events` | 3 bits，组合值 1-7 | 返回正确的整数编码序列 |
| `test_decode_times_from_sample_rate` | `sample_rate=30000`，跳变在第 30000 样本 | 事件时间 ≈ 1.0s |
| `test_decode_returns_numpy_arrays` | 任意输入 | 返回类型为 numpy 数组 |

### `_align_probe_to_nidq`

| 测试名 | 预期行为 |
|---|---|
| `test_align_probe_calls_align_imec_to_nidq` | `align_imec_to_nidq` 以正确 probe_id 被调用 |
| `test_align_probe_returns_sync_result` | 返回含 `SyncResult` 的 tuple |

### 断点续跑

| 测试名 | 预期行为 |
|---|---|
| `test_skips_if_checkpoint_complete` | stage checkpoint complete → run() 立即返回 |

### 错误处理

| 测试名 | 预期行为 |
|---|---|
| `test_sync_error_propagates` | `align_imec_to_nidq` raise SyncError → re-raise |
| `test_failed_checkpoint_written_on_error` | 任意 SyncError | `checkpoints/synchronize.json` status=failed |
| `test_photodiode_dead_signal_raises` | `calibrate_photodiode` raise SyncError → re-raise |

### Parquet 内容

| 测试名 | 预期行为 |
|---|---|
| `test_trial_valid_column_is_nan` | `trial_valid` 列全部为 NaN |
| `test_dataset_name_in_every_row` | `dataset_name` 列每行相同 |
| `test_quality_flag_from_calibration` | `quality_flag` 列来自 CalibratedOnsets.quality_flags |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.SyncError` | 项目内部 | 同步失败时抛出 |
| `pynpxpipe.io.sync.imec_nidq_align.align_imec_to_nidq` | 项目内部 | 第一级对齐 |
| `pynpxpipe.io.sync.bhv_nidq_align.align_bhv2_to_nidq` | 项目内部 | 第二级对齐 |
| `pynpxpipe.io.sync.photodiode_calibrate.calibrate_photodiode` | 项目内部 | 第三级校准 |
| `pynpxpipe.io.sync_plots.generate_all_plots` | 项目内部 | 诊断图生成（可选 matplotlib） |
| `pynpxpipe.io.spikeglx.SpikeGLXLoader` | 项目内部 | NIDQ lazy 录制加载 |
| `pynpxpipe.io.bhv.BHV2Parser` | 项目内部 | BHV2 文件解析 |
| `numpy` | 必选 | 数组运算 |
| `pandas` | 必选 | behavior_events DataFrame |
| `pyarrow` | 必选 | parquet 写入 |
| `json` | 标准库 | sync_tables.json 写出 |

---

## 8. 附录 A：三级对齐流程图

> 搬迁自 architecture.md Section 3（原 lines 710-790）

```
【第一级：IMEC ↔ NIDQ 时钟对齐】

  imec0.ap 数字通道（sync bit 0）
        │
        │  np.diff → 上升沿采样点
        │  ÷ 采样率（从 meta 读取）
        ▼
  imec0 sync 脉冲时间序列
  [t0_ap, t1_ap, t2_ap, ...]        ←── 通常 1 Hz，整个 session
        │
        │  配对
        ▼
  nidq 数字通道（sync bit 0）
        │
        │  np.diff → 上升沿采样点
        │  ÷ 采样率（从 nidq.meta 读取）
        ▼
  nidq sync 脉冲时间序列
  [t0_ni, t1_ni, t2_ni, ...]
        │
        ▼
  线性回归：t_nidq = a × t_imec + b
        │
        ├── 丢脉冲修复：检测 >gap_threshold_ms 间隔，等间距插值（cf. MATLAB step #6）
        ├── 验证残差 < max_time_error_ms（默认 17ms）
        │
        └── 输出：校正函数 {a, b}，写入 sync_tables.json
            对 imec1, imec2, ... 重复上述流程


【第二级：BHV2 ↔ NIDQ 行为对齐】

  BHV2 文件（MATLAB HDF5）
        │
        │  MATLAB Engine 解析 trial struct array
        │  提取 DatasetName 等元信息
        ▼
  BHV2 trial 序列
  [{trial_id, events:[{time_ms, code}, ...]}, ...]
        │
        │  匹配事件码序列（自动修复 trial_start_bit 映射错误）
        ▼
  nidq 数字通道（event_bits 1-7）
        │
        │  多 bit 解码 → (采样点, 事件码)
        │  ÷ 采样率 → 事件时间（NIDQ 时钟）
        ▼
  NIDQ 事件码序列
  [(t_ni_0, code_0), (t_ni_1, code_1), ...]
        │
        │  trial 对齐（onset 事件码序列匹配）
        ▼
  behavior_events 表（初版，trial_valid=NaN）
  trial_id | onset_nidq_s | stim_onset_nidq_s | condition_id | dataset_name | ...


【第三级：Photodiode 模拟信号校准】

  nidq 模拟通道（sync.photodiode_channel_index）
        │
        │  int16 → 电压（niAiRangeMax 从 meta 读取）
        │  resample_poly → 1ms 分辨率
        ▼
  photodiode 信号（1ms/sample）
        │
        │  以 stim_onset_nidq_s 为参考
        │  提取 [-10ms, +100ms] 窗口（逐 trial）
        ▼
  逐 trial z-score 归一化
        │
        │  逐 trial 极性校正：检测下降沿 → 翻转信号（cf. MATLAB step #10）
        │  全局阈值 = 0.1×baseline_mean + 0.9×stim_period_mean
        │  首次超阈 → onset_latency (ms)
        ▼
  onset_latency + monitor_delay_ms（来自配置）
        │
        │  np.interp（NI 时钟 → IMEC 时钟，用第一级校正函数）
        ▼
  stim_onset_imec_s（IMEC 时钟，每 probe 一份）
        │
        └── 写入 behavior_events.stim_onset_imec_s
```

---

## 9. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #6-#12（`examine_and_fix_sync.m` + `Load_Data_function.m` 前半部分） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #6-#12 段落 |

本 stage 编排三个 IO 子模块，各子模块的 MATLAB 对照详见其各自 spec。

### 编排级差异

| 偏离 | 理由 |
|------|------|
| 三级对齐拆分为 3 个独立 IO 模块 + 1 个编排 stage | MATLAB 在单一函数 `Load_Data_function.m` 中串行完成所有步骤；Python 拆分后可独立测试和复用 |
| 输出为 JSON + Parquet 而非 .mat | Python 生态标准格式，更利于下游工具消费 |
| 诊断图生成独立于核心同步逻辑 | MATLAB 图表散落在各步骤中；Python 集中在 `sync_plots.py`，matplotlib 为可选依赖 |
| 使用 stage 级 checkpoint 而非无 checkpoint | MATLAB 无断点续跑；Python 支持失败后恢复 |
| NIDQ 事件码解码使用配置化 bit 列表 | MATLAB 硬编码 `bitand(CodeVal, 2)` (bit 1) 和 `bitand(CodeVal, 64)` (bit 6) |
