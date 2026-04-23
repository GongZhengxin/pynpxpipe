# Spec: io/sync/bhv_nidq_align.py

## 1. 目标

实现同步三级架构中的**第二级：BHV2↔NIDQ 行为事件对齐**。

从 NIDQ 数字通道解码 MonkeyLogic 事件码序列，与 BHV2 文件中按 trial 组织的行为事件时间戳对齐，输出统一在 NIDQ 时钟下的**逐 stimulus onset** 事件表。同时提取 BHV2 会话元信息（`dataset_name` 等）供后续 export 阶段写入 NWB。

本模块属于 IO 层，无任何 stage 逻辑、无 checkpoint、无 UI 依赖。输入为 `BHV2Parser` 实例、NIDQ 事件时间/编码数组以及同步配置参数，输出为结构化的 `TrialAlignment` dataclass。

### 核心原则：stim_onset_nidq_s 由 NIDQ rising 直接提供

`stim_onset_nidq_s` 必须来自 NIDQ stim_onset bit 的实际 rising 时间（与 MATLAB `find(diff(bitand(CodeVal,64))>0)+1` 一致），**不得**用 `trial_anchor + bhv_offset` 公式计算。原因：BHV2 的"trial 零点"是 ML trial 函数被调用的时刻，而 NIDQ 上 trial_start 上升沿是 ML 初始化若干毫秒后才发出的；两者的 gap 逐 trial 随机（实测 58–121ms），导致用偏移公式得到的 stim_onset 误差可达 ±120ms，远超 photodiode 校准窗 [-10,+100]ms，造成大量 flag=3（no transition）。

`onset_nidq_s`（trial anchor）仍来自 NIDQ trial_start bit 上升沿，语义不变。

---

## 2. 输入

### `align_bhv2_to_nidq` 函数参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `bhv_parser` | `BHV2Parser` | 已初始化的 BHV2 解析器实例（指向 .bhv2 文件） |
| `nidq_event_times` | `np.ndarray` (float64, 1D) | NIDQ 数字通道解码后的事件时间序列，单位：秒（NIDQ 时钟） |
| `nidq_event_codes` | `np.ndarray` (int, 1D) | 与 `nidq_event_times` 一一对应的事件码整数数组 |
| `stim_onset_code` | `int` | **BHV2 侧** stimulus onset 的原始事件码值（MonkeyLogic 语义，例如 64 = bit 6），从 `config.sync.stim_onset_code` 传入，**禁止硬编码** |
| `trial_start_bit` | `int \| None` | **解码域**中 trial start 信号对应的输出 bit 索引（注意：不是 NIDQ 原始 bit 号，是 decoder 压缩后的位置）。若为 `None`，则自动检测 |
| `stim_onset_bit` | `int \| None` | **解码域**中 stim onset 信号对应的输出 bit 索引。若为 `None`，则自动检测（选总 rising 次数最接近 BHV2 stim onset 总数的 bit） |
| `max_time_error_ms` | `float` | 对齐质量验证阈值（毫秒），从 `config.sync.max_time_error_ms` 传入 |
| `trial_count_tolerance` | `int` | BHV2 trial 数与 NIDQ 事件数允许的最大差异，从 `config.sync.trial_count_tolerance` 传入，默认 `2` |
| `stim_count_tolerance` | `int` | 单个 trial 内 BHV2 stim 数与 NIDQ 窗口内 stim rising 数允许的差异，默认 `0`（严格匹配；不匹配的 trial 内 stim 置 NaN 并记 warning） |

约束：
- `nidq_event_times` 与 `nidq_event_codes` 长度必须相同
- `stim_onset_code` 必须在 0-255 范围内（单字节事件码）
- `trial_count_tolerance` 必须 >= 0
- `stim_count_tolerance` 必须 >= 0

### 命名术语说明（重要）

本模块中有两套 bit 概念，易混淆：
- **原始 NIDQ bit**（MonkeyLogic 语义，0-7）：数字通道字中的物理位，例如 bit 6（= code 64）= stim_onset。`stim_onset_code` 参数用这套。
- **解码域 bit**（decoder 压缩后，0-6）：`SynchronizeStage._decode_nidq_events` 把 `event_bits=[1..7]` 压缩成连续的 output bit `[0..6]`。所以原始 bit 6 在解码输出中对应的"事件码值"是 `1 << event_bits.index(6) = 32`（而非 64）。`trial_start_bit` / `stim_onset_bit` 参数以及 `nidq_event_codes` 数组用的是这套。

两者是不同坐标，必须明确区分。MATLAB 参考直接读原始数字字（不做 bit 压缩），所以 MATLAB 的 `bitand(CodeVal,64)` 对应 Python 的"解码域 bit 5 的 rising"。

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
    detected_stim_onset_bit: int
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

6. **提取 stimulus onset 时间序列（MATLAB-style 直接匹配）**

   6a. **确定 `stim_onset_bit`**
     - 若 `stim_onset_bit` 非 `None`：直接使用
     - 否则调用 `_auto_detect_stim_onset_bit(nidq_event_codes, n_bhv_stim_total)`：遍历解码域 bit 0-7，选计数最接近 BHV2 stim_onset_code 事件总数的 bit
     - 记录到 `detected_stim_onset_bit`

   6b. **提取 NIDQ stim rising 时间序列**
     - `stim_code_val = 1 << detected_stim_onset_bit`
     - `nidq_stim_rising = nidq_event_times[nidq_event_codes == stim_code_val]`
     - 这是**所有** stim onset rising 的全局时间序列，与 BHV2 stim 事件总数应 1:1 对应

   6c. **BHV2 按 trial 组织 stim 事件**
     - 调用 `bhv_parser.get_event_code_times(stim_onset_code, trials=[t.trial_id for t in trials])` → `[(trial_id, time_ms_bhv), ...]`
     - 按 `trial_id` 分组，保留 trial 内的原始顺序

   6d. **逐 trial 匹配**
     - 对每个 trial `i`：
       - `window_start = nidq_trial_onset_times[i]`
       - `window_end = nidq_trial_onset_times[i+1]` （最后一个 trial 用 `+∞`）
       - `nidq_stims_in_window = nidq_stim_rising[(nidq_stim_rising >= window_start) & (nidq_stim_rising < window_end)]`
       - `bhv_stims_in_trial = stim_times_by_trial.get(trial.trial_id, [])`
       - **若数量匹配**（差值 ≤ `stim_count_tolerance`）：逐元素取 `nidq_stims_in_window[k]` 作为该 stim 的 `stim_onset_nidq_s`
       - **若不匹配**：为该 trial 内所有 stim 的 `stim_onset_nidq_s` 置 `np.nan`，记录 warning 含 trial_id / n_bhv / n_nidq
       - **若 `bhv_stims_in_trial` 为空**：仍写入一行占位（`stim_onset_nidq_s=NaN`, `stim_index=0`），保留 trial 信息以便 postprocess 引用 `onset_nidq_s`
     - `stim_onset_bhv_ms` 列继续保留 BHV2 原生 stim 时间（眼动验证需要）
     - `onset_nidq_s` 列仍为 NIDQ trial anchor 时间（每个 trial 内所有 stim row 共享同一值）

7. **对齐质量验证**
   - 校验 `nidq_trial_onset_times` 严格单调递增；否则 raise `SyncError`
   - 校验 `stim_onset_nidq_s`（过滤 NaN 后）严格单调递增；若存在反转仅 warning（数据质量问题，不中止流程）
   - 汇总：计算 `n_nan = np.isnan(stim_onset_nidq_s).sum()`；若 `n_nan > 0`，记录 info 日志列出 trial_id

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
        detected_trial_start_bit: Decoded-domain bit index used for trial
            onsets (either as given or auto-detected).
        detected_stim_onset_bit: Decoded-domain bit index used for stim
            onsets (either as given or auto-detected).
    """

    trial_events_df: pd.DataFrame
    dataset_name: str
    bhv_metadata: dict
    detected_trial_start_bit: int
    detected_stim_onset_bit: int


def align_bhv2_to_nidq(
    bhv_parser: BHV2Parser,
    nidq_event_times: np.ndarray,
    nidq_event_codes: np.ndarray,
    stim_onset_code: int,
    trial_start_bit: int | None = None,
    stim_onset_bit: int | None = None,
    max_time_error_ms: float = 17.0,
    trial_count_tolerance: int = 2,
    stim_count_tolerance: int = 0,
) -> TrialAlignment:
    """Align BHV2 behavioral events to the NIDQ clock.

    Decodes trial onset times from NIDQ digital event codes, matches them
    1:1 with BHV2 trials, and resolves each stimulus onset in NIDQ clock by
    directly matching it to a NIDQ stim-onset rising edge within the trial
    window (MATLAB-style: bit-6 rising, cf. ground_truth step #10). Never
    uses trial_anchor + bhv_offset, which accumulates up to ±120ms drift.

    Auto-detection: when trial_start_bit / stim_onset_bit is None, iterates
    decoded-domain bits 0-7 and picks the bit whose rising-edge count best
    matches BHV2 trial / stim total.

    Args:
        bhv_parser: Initialized BHV2Parser pointing to the .bhv2 file.
        nidq_event_times: 1D float64 array of event times in NIDQ seconds.
            Must have the same length as nidq_event_codes.
        nidq_event_codes: 1D int array of decoded integer event codes from
            the NIDQ digital channel. Same length as nidq_event_times.
        stim_onset_code: Integer event code value that marks stimulus onset
            in the BHV2 event list. Read from config.sync.stim_onset_code.
            Must be in range 0-255. Never hardcode.
        trial_start_bit: Decoded-domain bit index (0-7) for trial_start.
            If None, auto-detection is performed.
        stim_onset_bit: Decoded-domain bit index (0-7) for stim_onset.
            If None, auto-detection is performed (picks bit whose count
            best matches BHV2 stim_onset_code event total).
        max_time_error_ms: Maximum allowed alignment error in milliseconds.
            Read from config.sync.max_time_error_ms. Default 17.0.
        trial_count_tolerance: Maximum allowed difference between BHV2 trial
            count and NIDQ decoded trial count before raising SyncError.
            Read from config.sync.trial_count_tolerance. Default 2.
        stim_count_tolerance: Maximum allowed per-trial difference between
            BHV2 stim count and NIDQ stim-rising count inside the trial
            window; mismatched trials get NaN stim_onset_nidq_s + warning.
            Default 0 (strict equality).

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
    """Find the decoded-domain bit whose rising count best matches BHV2 trial count."""


def _auto_detect_stim_onset_bit(
    nidq_event_codes: np.ndarray,
    n_bhv_stims: int,
    *,
    exclude_bit: int | None = None,
    tolerance: int = 0,
) -> int:
    """Find the decoded-domain bit whose rising count best matches BHV2 stim count.

    Args:
        nidq_event_codes: Decoded event codes (post compression).
        n_bhv_stims: Total BHV2 stim_onset_code events across all trials.
        exclude_bit: Optionally skip a bit already claimed by trial_start,
            so a probe whose trial/stim counts happen to coincide doesn't
            collapse onto the same bit.
        tolerance: Max allowed |count - n_bhv_stims|.

    Returns:
        Best-matching decoded bit index.

    Raises:
        SyncError: If no bit is within tolerance.
    """
```

### 可配参数

| 参数 | 对应配置键 | 说明 |
|---|---|---|
| `stim_onset_code` | `config.sync.stim_onset_code` | BHV2 侧 stim onset 事件码值（ML 语义），**禁止硬编码** |
| `trial_start_bit` | `config.sync.trial_start_bit` | 解码域 trial_start bit；`None` 时自动检测 |
| `stim_onset_bit` | `config.sync.stim_onset_bit` | 解码域 stim_onset bit；`None` 时自动检测 |
| `max_time_error_ms` | `config.sync.max_time_error_ms` | 对齐误差上限（毫秒） |
| `trial_count_tolerance` | `config.sync.trial_count_tolerance` | trial 数量允许差异（自动截断范围） |
| `stim_count_tolerance` | `config.sync.stim_count_tolerance` | 单 trial 内 stim 数量允许差异 |

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_io/test_bhv_nidq_align.py`

### 正常对齐流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_perfect_alignment_returns_dataframe` | 3 trial BHV2，每 trial 1 stim，NIDQ 提供匹配 rising | 返回 `TrialAlignment`，`trial_events_df` 有 3 行 |
| `test_onset_nidq_s_column_values` | 已知 trial anchor [1.0, 2.0, 3.0] | `onset_nidq_s` 与输入一致 |
| `test_stim_onset_from_nidq_rising_not_offset` | BHV2 offset=200ms，NIDQ stim rising @ trial_anchor+0.230s | `stim_onset_nidq_s` 必须等于 NIDQ rising（0.230 偏移），**不是** anchor+0.200 |
| `test_condition_id_preserved` | BHV2 trial condition_id=[5, 7, 3] | 列值一致 |
| `test_trial_valid_column_is_nan` | 任意有效输入 | `trial_valid` 列全部为 `np.nan` |
| `test_dataset_name_extracted` | MLConfig DatasetName="exp_20260101" | `dataset_name == "exp_20260101"` |
| `test_bhv_metadata_populated` | MLConfig 含 TotalTrials | metadata 有值 |
| `test_detected_trial_start_bit_matches_input` | `trial_start_bit=3` | `detected_trial_start_bit == 3` |
| `test_detected_stim_onset_bit_matches_input` | `stim_onset_bit=5` | `detected_stim_onset_bit == 5` |
| `test_trial_id_column_1indexed` | 3 trial BHV2 | `trial_id.tolist() == [1, 2, 3]` |

### 逐 trial 多 stim 匹配（RSVP / 多刺激范式）

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_rsvp_multiple_stims_per_trial` | trial 1 含 3 个 stim，NIDQ 在 trial 窗口内提供 3 个 stim rising | 每个 stim row 的 `stim_onset_nidq_s` 等于对应 NIDQ rising |
| `test_nidq_stim_count_mismatch_gives_nan` | trial 1 BHV 有 3 stim，NIDQ 窗口内只有 2 rising，tolerance=0 | 该 trial 全部 stim row 置 NaN，warning |
| `test_nidq_stim_count_within_tolerance` | 同上但 tolerance=1 | 不置 NaN，取前 min(n_bhv, n_nidq) 个 rising |
| `test_last_trial_window_uses_plus_inf` | 最后一个 trial 的 stim rising 在 anchor 之后没有下一个 anchor | 仍被匹配到最后 trial |
| `test_trial_with_no_bhv_stim_keeps_placeholder_row` | 某 trial BHV 无 stim | 保留一个占位 row，`stim_onset_nidq_s=NaN`，`stim_index=0` |

### 自动检测 trial_start_bit

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_auto_detect_selects_correct_bit` | bit=2 计数与 BHV2 trial 数相同，`trial_start_bit=None` | `detected_trial_start_bit == 2` |
| `test_auto_detect_picks_closest_count` | bit=1 → 5，bit=2 → 10，n_bhv=10 | 选 bit=2 |
| `test_auto_detect_fails_no_matching_bit` | 所有 bit 差值 > tolerance | raise `SyncError` |
| `test_explicit_bit_skips_auto_detect` | `trial_start_bit=5` | 使用 bit=5，不报错 |

### 自动检测 stim_onset_bit

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_auto_detect_stim_bit_selects_matching_count` | bit=5 rising 数 = n_bhv_stims | `detected_stim_onset_bit == 5` |
| `test_auto_detect_stim_bit_excludes_trial_start_bit` | trial_start_bit=0，stim count = trial count | 不选 bit=0（排除冲突） |
| `test_auto_detect_stim_bit_fails_no_match` | 所有 bit 差值 > tolerance | raise `SyncError` |
| `test_explicit_stim_bit_skips_auto_detect` | `stim_onset_bit=5` | 使用 bit=5 |

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
| `test_stim_onset_precision_matches_nidq_rising` | NIDQ rising @ 1.2345，输出 `stim_onset_nidq_s` 与之差值 < 1e-12 |
| `test_multiple_probes_independent` | 两次独立调用结果互不影响 |
| `test_no_offset_drift_across_trials` | 构造 trial-gap 递增的场景（模拟 58–121ms 漂移），bit-6-direct 输出 = NIDQ rising，与 anchor+offset 公式的结果**不相等** |

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
| trial_start_bit 自动检测而非硬编码 bit 1 | MATLAB 硬编码 `bitand(CodeVal,2)`；Python 支持 auto-detect 或从 config 指定 |
| stim_onset_code 从 config 读取而非硬编码 64 | MATLAB 硬编码 event code 64；Python 参数化 |
| NIDQ 侧同时使用"解码域 bit index"而非原始 NIDQ bit | Python decoder 会把 `event_bits` 压缩成连续 output bit（ML 原始 bit 6 → 解码域 bit 5）；参数层面保留这一差异，避免两次解码 |
| dataset_name 从 BHV2 metadata 提取，不做路径解析 | MATLAB 解析 Windows 路径字符串；Python 通过 `BHV2Parser.get_session_metadata()` 直接获取 |
| trial 数量不匹配时自动截断（tolerance 范围内） | MATLAB 仅 warning + keyboard；Python 自动处理并记录 |
| 逐 trial stim 数量不匹配时整 trial 置 NaN | MATLAB 硬编码 1 stim/trial，本 codebase 支持 RSVP；保留 trial 占位方便下游 postprocess 引用 |
| Python 无逐 trial onset 计数交叉验证 | MATLAB 做逐 trial onset 次数比对；Python 在 sync_plots 模块中实现诊断图 |

### 先前版本的错误实现（本轮已修复）

旧版本 step 6 使用 `stim_onset_nidq_s = nidq_trial_onset_times[idx] + bhv_offset_ms/1000`。实测该公式会引入 ±120ms 漂移（BHV2 trial 零点 vs NIDQ trial_start rising 的 gap 逐 trial 随机 58–121ms），导致 photodiode 校准窗 [-10,+100]ms 接不到信号、大面积 flag=3。当前 spec 采用 MATLAB 的 bit-6-direct 方式消除该漂移。
