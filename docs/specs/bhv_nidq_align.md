# Spec: io/sync/bhv_nidq_align.py

## 1. 目标

实现同步三级架构中的**第二级：BHV2↔NIDQ 行为事件对齐**。

从 NIDQ 数字通道解码 MonkeyLogic 事件码序列，与 BHV2 文件中按 trial 组织的行为事件时间戳对齐，输出统一在 NIDQ 时钟下的 trial 级事件表。同时提取 BHV2 会话元信息（`dataset_name` 等）供后续 export 阶段写入 NWB。

本模块属于 IO 层，无任何 stage 逻辑、无 checkpoint、无 UI 依赖。输入为 `BHV2Parser` 实例、NIDQ 事件时间/编码数组以及同步配置参数，输出为结构化的 `TrialAlignment` dataclass。

---

## 2. 输入

### `align_bhv2_to_nidq` 函数参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `bhv_parser` | `BHV2Parser` | 已初始化的 BHV2 解析器实例（指向 .bhv2 文件） |
| `nidq_event_times` | `np.ndarray` (float64, 1D) | NIDQ 数字通道解码后的事件时间序列，单位：秒（NIDQ 时钟） |
| `nidq_event_codes` | `np.ndarray` (int, 1D) | 与 `nidq_event_times` 一一对应的事件码整数数组 |
| `stim_onset_code` | `int` | 代表 stimulus onset 的事件码值，从 `config.sync.stim_onset_code` 传入，**禁止硬编码** |
| `trial_start_bit` | `int \| None` | NIDQ 数字通道中 trial start 信号的 bit 位。若为 `None`，则自动检测（遍历 bit 0-7 寻找最佳匹配） |
| `max_time_error_ms` | `float` | 对齐质量验证阈值（毫秒），从 `config.sync.max_time_error_ms` 传入 |
| `trial_count_tolerance` | `int` | BHV2 trial 数与 NIDQ 事件数允许的最大差异，从 `config.sync.trial_count_tolerance` 传入，默认 `2` |

约束：
- `nidq_event_times` 与 `nidq_event_codes` 长度必须相同
- `stim_onset_code` 必须在 0-255 范围内（单字节事件码）
- `trial_count_tolerance` 必须 >= 0

---

## 3. 输出

```python
@dataclass
class TrialAlignment:
    """BHV2 到 NIDQ 对齐结果。

    Attributes:
        trial_events_df: 逐 trial 对齐事件表，时间均为 NIDQ 时钟秒。
            列定义：
              trial_id         (int)   — BHV2 trial 编号（1-indexed）
              onset_nidq_s     (float) — trial onset 在 NIDQ 时钟的时间（秒）
              stim_onset_nidq_s(float) — stimulus onset 在 NIDQ 时钟的时间（秒）
              condition_id     (int)   — 刺激条件编号
              trial_valid      (object, NaN) — 眼动验证占位列，postprocess 阶段填写
        dataset_name: BHV2 MLConfig 中的 DatasetName 字段值。
        bhv_metadata: BHV2 get_session_metadata() 返回的完整 session 元信息 dict。
        detected_trial_start_bit: 实际使用的 trial_start_bit（自动检测时有用）。
    """
    trial_events_df: pd.DataFrame
    dataset_name: str
    bhv_metadata: dict
    detected_trial_start_bit: int
```

`trial_events_df` 列说明：

| 列名 | 类型 | 说明 |
|---|---|---|
| `trial_id` | `int` | BHV2 trial 编号，1-indexed |
| `onset_nidq_s` | `float` | trial onset 的 NIDQ 时钟时间（秒） |
| `stim_onset_nidq_s` | `float` | stimulus onset 的 NIDQ 时钟时间（秒） |
| `condition_id` | `int` | 该 trial 的刺激条件编号（来自 BHV2 TrialData.condition_id） |
| `trial_valid` | `float` (NaN) | 预留列，初始值均为 `np.nan`，由 postprocess 阶段填写 |

---

## 4. 处理步骤

### `align_bhv2_to_nidq`

1. **输入验证**
   - 检查 `len(nidq_event_times) == len(nidq_event_codes)`；不匹配 → raise `SyncError("NIDQ event_times and event_codes length mismatch: {n_times} vs {n_codes}")`
   - 检查 `stim_onset_code` 在 0-255 范围内；超出 → raise `SyncError("stim_onset_code {code} out of range 0-255")`

2. **解析 BHV2**
   - 调用 `bhv_parser.parse()` 获取 `list[TrialData]`（缓存命中则不重复读盘）
   - 获取 BHV2 trial 数量 `n_bhv = len(trials)`
   - 调用 `bhv_parser.get_session_metadata()` 获取 `bhv_metadata` dict
   - 提取 `dataset_name = bhv_metadata.get("DatasetName", "")`

3. **确定 `trial_start_bit`**
   - 若 `trial_start_bit` 参数不为 `None`：直接使用，跳过自动检测
   - 若 `trial_start_bit` 为 `None`：调用内部函数 `_auto_detect_trial_start_bit(nidq_event_times, nidq_event_codes, n_bhv)` 自动检测
   - 将确定的 bit 记录为 `detected_trial_start_bit`

4. **提取 trial onset 时间序列**
   - 从 `nidq_event_codes` 中找出所有等于 `2 ** trial_start_bit`（trial start 信号对应的编码值）的事件索引
   - 取对应 `nidq_event_times`，得到 `nidq_trial_onset_times`（NIDQ 时钟秒数组）
   - 获取 NIDQ 侧 trial 数量 `n_nidq = len(nidq_trial_onset_times)`

5. **trial 数量校验与自动对齐截断**
   - 计算差值 `diff = abs(n_bhv - n_nidq)`
   - 若 `diff > trial_count_tolerance` → raise `SyncError("Trial count mismatch: BHV2={n_bhv}, NIDQ={n_nidq}, tolerance={trial_count_tolerance}. Check BHV2 file and NIDQ recording completeness.")`
   - 若 `diff > 0`（在容忍范围内）：
     - 取较小值 `n_trials = min(n_bhv, n_nidq)`
     - 截断较长一侧：`trials = trials[:n_trials]`，`nidq_trial_onset_times = nidq_trial_onset_times[:n_trials]`
     - 记录警告日志，含被丢弃的 trial 编号信息
   - 否则 `n_trials = n_bhv`

6. **提取 stimulus onset 时间序列**
   - 调用 `bhv_parser.get_event_code_times(stim_onset_code, trials=[t.trial_id for t in trials])` → 得到 `[(trial_id, time_ms_bhv), ...]`
   - 对每个 trial：BHV2 中的 stim_onset 相对于 trial onset 的偏移量（ms） = `stim_time_ms - trial_onset_time_ms_bhv`
   - 将该偏移量加到 `onset_nidq_s[trial_idx]` 上（ms 转秒），得到 `stim_onset_nidq_s`
   - 若某 trial 在 BHV2 中没有 `stim_onset_code` 事件，则该 trial 的 `stim_onset_nidq_s` 设为 `np.nan`，记录警告

7. **对齐质量验证**
   - 计算逐 trial 的 onset 时间间隔（BHV2 侧 vs NIDQ 侧），验证 inter-trial interval 的差值均值 < `max_time_error_ms / 1000`
   - 若验证失败 → raise `SyncError("BHV2-NIDQ alignment error exceeds {max_time_error_ms} ms. Check event code definitions.")`

8. **构建 `trial_events_df`**
   - 构造 pandas DataFrame，列如第 3 节所述
   - `trial_valid` 列全部初始化为 `np.nan`

9. **返回 `TrialAlignment`**
   - 返回 `TrialAlignment(trial_events_df=df, dataset_name=dataset_name, bhv_metadata=bhv_metadata, detected_trial_start_bit=detected_trial_start_bit)`

---

### `_auto_detect_trial_start_bit`（内部辅助函数）

```
_auto_detect_trial_start_bit(
    nidq_event_times: np.ndarray,
    nidq_event_codes: np.ndarray,
    n_bhv_trials: int,
) -> int
```

1. 对 bit 位 0 到 7 逐一尝试：
   a. 提取该 bit 对应编码值 `code_val = 2 ** bit`
   b. 计数 `nidq_event_codes` 中等于 `code_val` 的事件数 `count`
   c. 计算与 `n_bhv_trials` 的接近程度 `abs(count - n_bhv_trials)`
2. 选择接近程度最小的 bit 作为 `trial_start_bit`
3. 若所有 bit 对应的计数与 `n_bhv_trials` 差值均 > `trial_count_tolerance`（外部传入）：raise `SyncError("Cannot auto-detect trial_start_bit: no NIDQ bit matches BHV2 trial count {n_bhv_trials}. Check config.sync.trial_start_bit.")`
4. 记录 info 日志：自动检测结果 bit 编号和对应 trial count

---

## 5. 公开 API 与可配参数

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from pynpxpipe.core.errors import SyncError
from pynpxpipe.io.bhv import BHV2Parser


@dataclass
class TrialAlignment:
    """Result of BHV2-to-NIDQ behavioral event alignment.

    Attributes:
        trial_events_df: Per-trial aligned event table in NIDQ clock.
            Columns: trial_id (int), onset_nidq_s (float),
            stim_onset_nidq_s (float), condition_id (int),
            trial_valid (float, NaN placeholder for postprocess stage).
        dataset_name: Value of DatasetName field from BHV2 MLConfig.
        bhv_metadata: Full session metadata dict from BHV2Parser.get_session_metadata().
        detected_trial_start_bit: The NIDQ digital bit used to identify trial
            onsets (either as given or auto-detected).
    """

    trial_events_df: pd.DataFrame
    dataset_name: str
    bhv_metadata: dict
    detected_trial_start_bit: int


def align_bhv2_to_nidq(
    bhv_parser: BHV2Parser,
    nidq_event_times: np.ndarray,
    nidq_event_codes: np.ndarray,
    stim_onset_code: int,
    trial_start_bit: int | None = None,
    max_time_error_ms: float = 17.0,
    trial_count_tolerance: int = 2,
) -> TrialAlignment:
    """Align BHV2 behavioral events to the NIDQ clock.

    Decodes trial onset times from NIDQ digital event codes, matches them
    1:1 with BHV2 trials, and computes stimulus onset times in NIDQ clock
    by adding per-trial BHV2 relative offsets to the aligned trial onset times.

    Auto-detection of trial_start_bit: if trial_start_bit is None, iterates
    bits 0-7 to find the NIDQ bit whose event count best matches n_bhv_trials.

    Args:
        bhv_parser: Initialized BHV2Parser pointing to the .bhv2 file.
        nidq_event_times: 1D float64 array of event times in NIDQ seconds.
            Must have the same length as nidq_event_codes.
        nidq_event_codes: 1D int array of decoded integer event codes from
            the NIDQ digital channel. Same length as nidq_event_times.
        stim_onset_code: Integer event code value that marks stimulus onset
            in the BHV2 event list. Read from config.sync.stim_onset_code.
            Must be in range 0-255. Never hardcode.
        trial_start_bit: NIDQ digital bit position (0-7) for trial start signal.
            If None, auto-detection is performed.
        max_time_error_ms: Maximum allowed alignment error in milliseconds.
            Read from config.sync.max_time_error_ms. Default 17.0.
        trial_count_tolerance: Maximum allowed difference between BHV2 trial
            count and NIDQ decoded trial count before raising SyncError.
            Read from config.sync.trial_count_tolerance. Default 2.

    Returns:
        TrialAlignment with per-trial DataFrame, dataset_name, bhv_metadata,
        and the trial_start_bit actually used.

    Raises:
        SyncError: If event array lengths mismatch, stim_onset_code out of
            range, trial count mismatch exceeds tolerance, auto-detection
            fails, or alignment error exceeds max_time_error_ms.
    """


def _auto_detect_trial_start_bit(
    nidq_event_times: np.ndarray,
    nidq_event_codes: np.ndarray,
    n_bhv_trials: int,
    trial_count_tolerance: int = 2,
) -> int:
    """Find the NIDQ digital bit whose onset count best matches BHV2 trial count.

    Iterates bits 0-7 and selects the bit whose decoded event count is
    closest to n_bhv_trials.

    Args:
        nidq_event_times: 1D float64 array of NIDQ event times (seconds).
        nidq_event_codes: 1D int array of decoded event codes.
        n_bhv_trials: Number of trials from BHV2 file.
        trial_count_tolerance: Maximum allowed mismatch before raising SyncError.

    Returns:
        Best-matching bit index (0-7).

    Raises:
        SyncError: If no bit produces a count within trial_count_tolerance
            of n_bhv_trials.
    """
```

### 可配参数

| 参数 | 对应配置键 | 说明 |
|---|---|---|
| `stim_onset_code` | `config.sync.stim_onset_code` | stimulus onset 事件码值，**禁止硬编码** |
| `trial_start_bit` | `config.sync.trial_start_bit` | trial start 的 NIDQ bit 位；`None` 时自动检测 |
| `max_time_error_ms` | `config.sync.max_time_error_ms` | 对齐误差上限（毫秒） |
| `trial_count_tolerance` | `config.sync.trial_count_tolerance` | trial 数量允许差异（自动截断范围） |

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_io/test_bhv_nidq_align.py`

### 正常对齐流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_perfect_alignment_returns_dataframe` | 3 trial BHV2 mock + 对应 NIDQ 事件，`trial_start_bit=1` | 返回 `TrialAlignment`，`trial_events_df` 有 3 行 |
| `test_onset_nidq_s_column_values` | 已知 NIDQ onset 时间 [1.0, 2.0, 3.0] | `trial_events_df.onset_nidq_s` 值与 NIDQ 输入一致 |
| `test_stim_onset_nidq_s_offset_correct` | BHV2 中 stim onset 相对 trial onset 偏移 200ms | `stim_onset_nidq_s ≈ onset_nidq_s + 0.2` |
| `test_condition_id_preserved` | BHV2 trial condition_id=[5, 7, 3] | `trial_events_df.condition_id` 与 BHV2 一致 |
| `test_trial_valid_column_is_nan` | 任意有效输入 | `trial_valid` 列全部为 `np.nan` |
| `test_dataset_name_extracted` | BHV2 MLConfig DatasetName="exp_20260101" | `result.dataset_name == "exp_20260101"` |
| `test_bhv_metadata_populated` | BHV2 MLConfig 含 TotalTrials 字段 | `result.bhv_metadata["TotalTrials"]` 有值 |
| `test_detected_trial_start_bit_matches_input` | `trial_start_bit=3` | `result.detected_trial_start_bit == 3` |
| `test_trial_id_column_1indexed` | 3 trial BHV2 | `trial_events_df.trial_id.tolist() == [1, 2, 3]` |

### 自动检测 trial_start_bit

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_auto_detect_selects_correct_bit` | NIDQ 中 bit=2 的事件数与 BHV2 trial 数相同，`trial_start_bit=None` | `detected_trial_start_bit == 2` |
| `test_auto_detect_picks_closest_count` | bit=1 → 5 次，bit=2 → 10 次，n_bhv=10 | 选择 bit=2 |
| `test_auto_detect_fails_no_matching_bit` | 所有 bit 的计数均与 n_bhv 差值 > tolerance | raise `SyncError` |
| `test_explicit_bit_skips_auto_detect` | `trial_start_bit=5`，即使另一个 bit 更匹配 | 使用 bit=5，不报错 |

### trial 数量不匹配处理

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_trial_count_within_tolerance_truncates` | n_bhv=10，n_nidq=11，tolerance=2 | 不 raise，`trial_events_df` 有 10 行 |
| `test_trial_count_exceeds_tolerance_raises` | n_bhv=10，n_nidq=15，tolerance=2 | raise `SyncError`，消息含 "mismatch" |
| `test_trial_count_exact_match` | n_bhv=n_nidq=20 | 不 raise，`trial_events_df` 有 20 行 |
| `test_bhv2_longer_truncated` | n_bhv=12，n_nidq=11，tolerance=2 | `trial_events_df` 有 11 行（截断 BHV2 侧） |

### stim onset 缺失处理

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_missing_stim_onset_gives_nan` | 某 trial 在 BHV2 中无 `stim_onset_code` 事件 | 该 trial 的 `stim_onset_nidq_s` 为 `np.nan` |
| `test_stim_onset_multiple_occurrences` | 某 trial 在 BHV2 中有 2 次 `stim_onset_code` | 取第一次出现的时间 |

### 错误处理

| 测试名 | 输入构造 | 预期异常 |
|---|---|---|
| `test_event_arrays_length_mismatch` | `len(nidq_event_times) != len(nidq_event_codes)` | raise `SyncError`，消息含 "mismatch" |
| `test_stim_onset_code_out_of_range` | `stim_onset_code=300` | raise `SyncError`，消息含 "0-255" |
| `test_stim_onset_code_negative` | `stim_onset_code=-1` | raise `SyncError` |
| `test_sync_error_is_pynpxpipe_error` | 任意触发 `SyncError` 的场景 | `SyncError` 是 `PynpxpipeError` 子类 |

### 数值正确性

| 测试名 | 验证内容 |
|---|---|
| `test_stim_onset_offset_precision` | BHV2 偏移 500ms，结果与 `onset + 0.5` 差值 < 1e-9 秒 |
| `test_multiple_probes_independent` | 两次独立调用（模拟两个 probe 的同步）结果互不影响 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `numpy` | 必选 | 数组运算，`np.nan`，布尔索引 |
| `pandas` | 必选 | 构建 `trial_events_df` DataFrame |
| `dataclasses.dataclass` | 标准库 | `TrialAlignment` 定义 |
| `pynpxpipe.io.bhv.BHV2Parser` | 项目内部 | 解析 BHV2 文件 |
| `pynpxpipe.io.bhv.TrialData` | 项目内部 | BHV2 逐 trial 数据结构 |
| `pynpxpipe.core.errors.SyncError` | 项目内部 | 对齐失败时抛出 |

无 matplotlib，无 spikeinterface，无文件 IO（文件读写由 `BHV2Parser` 封装）。

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #7（ML↔NI trial 数量验证）+ step #8（Dataset 名提取） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #7, #8 段落 |

### MATLAB 算法概要

**Step #7 — Trial 数量交叉验证：**
1. ML 侧：逐 trial 统计 `BehavioralCodes.CodeNumbers==64`（onset 事件码）的出现次数
2. NI 侧：`find(diff(bitand(DCode_NI.CodeVal,2))>0)+1` 提取 trial start（bit 1），再在 trial 窗口内统计 bit 6 上升沿次数
3. 交叉验证：`max(onset_times_by_trial_ML - onset_times_by_trial_SGLX) > 0` → warning
4. 诊断图：scatter plot（ML vs SGLX onset count），MaxErr 显示在标题

**Step #8 — Dataset 名提取：**
1. 从 `trial_ML.UserVars.DatasetName` 提取唯一 dataset 名列表
2. 硬编码取第一个 dataset：`dataset_pool = dataset_pool{1}`
3. 解析 Windows 路径：取最后一个 `\` 后的内容，去掉末尾 4 字符（扩展名）

### 有意偏离

| 偏离 | 理由 |
|------|------|
| trial_start_bit 自动检测而非硬编码 bit 1 | MATLAB 硬编码 `bitand(CodeVal,2)`（bit 1）；Python 支持 auto-detect 或从 config 指定 |
| stim_onset_code 从 config 读取而非硬编码 64 | MATLAB 硬编码 event code 64；Python 参数化 |
| dataset_name 从 BHV2 metadata 提取，不做路径解析 | MATLAB 解析 Windows 路径字符串；Python 通过 `BHV2Parser.get_session_metadata()` 直接获取 |
| trial 数量不匹配时自动截断（tolerance 范围内） | MATLAB 仅 warning + keyboard 暂停；Python 自动处理并记录 |
| Python 无逐 trial onset 计数交叉验证 | MATLAB 做逐 trial onset 次数比对（scatter plot）；Python 在 sync_plots 模块中实现诊断图 |
