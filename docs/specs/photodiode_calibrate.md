# Spec: io/sync/photodiode_calibrate.py

## 1. 目标

实现同步三级架构中的**第三级：Photodiode 模拟信号校准**。

从 NIDQ 模拟通道读取光电二极管（photodiode）信号，精确检测每个 trial 中视觉刺激在显示器上的实际显示时刻，纠正数字事件码触发时间与真实显示时间之间的系统延迟差。输出每个 trial 精确的 stim onset 时间（NIDQ 时钟），以及逐 trial 的质量标志位。

本模块属于 IO 层，无 stage 逻辑、无 checkpoint、无 UI 依赖。所有配置参数均从调用方传入，无 magic number。

---

## 2. 输入

### `calibrate_photodiode` 函数参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `photodiode_signal` | `np.ndarray` (int16, 1D) | NIDQ 模拟通道的原始整数信号，按 `config.sync.photodiode_channel_index` 提取的单通道数据 |
| `sample_rate_hz` | `float` | NIDQ 模拟通道的采样率（Hz），从 nidq.meta `niSampRate` 字段读取，**禁止硬编码** |
| `voltage_range` | `float` | ADC 量程（伏特），从 nidq.meta `niAiRangeMax` 字段读取，**禁止硬编码** |
| `stim_onset_times_s` | `np.ndarray` (float64, 1D) | 数字事件码解码得到的 stim onset 时间序列（NIDQ 时钟秒），即 `trial_events_df.stim_onset_nidq_s`，可含 NaN |
| `monitor_delay_ms` | `float` | 显示器系统延迟校正量（ms），从 `config.sync.monitor_delay_ms` 读取，**禁止硬编码** |
| `pd_window_pre_ms` | `float` | photodiode 检测窗口的前置时长（ms），默认 `10.0`，从 `config.sync.pd_window_pre_ms` 读取 |
| `pd_window_post_ms` | `float` | photodiode 检测窗口的后置时长（ms），默认 `100.0`，从 `config.sync.pd_window_post_ms` 读取 |
| `min_signal_variance` | `float` | 信号方差下限，低于此值认为 photodiode 无信号（接头松动），默认 `1e-6`，从配置读取 |

约束：
- `photodiode_signal` 长度必须 > 0
- `stim_onset_times_s` 中的 NaN 条目会被标记为 `quality_flag=2`（out_of_bounds）
- `sample_rate_hz` 必须 > 0
- `pd_window_pre_ms` 和 `pd_window_post_ms` 必须 > 0

---

## 3. 输出

```python
@dataclass
class CalibratedOnsets:
    """Photodiode-calibrated stimulus onset times.

    Attributes:
        stim_onset_nidq_s: Refined stim onset times in NIDQ clock seconds.
            Shape (n_trials,). Trials with quality_flag != 0 retain the
            original digital event code time (not corrected).
        onset_latency_ms: Measured photodiode latency per trial (ms),
            defined as the delay from digital stim_onset_code to actual
            photodiode threshold crossing. Shape (n_trials,).
            NaN for trials where detection was skipped (quality_flag 2).
        quality_flags: Per-trial integer quality indicator. Shape (n_trials,).
            0 = good (photodiode detected, latency applied)
            1 = negative_latency (onset before trigger; warning issued,
                original time retained)
            2 = out_of_bounds (window extends beyond recording; trial skipped,
                original time retained)
            3 = low_signal (signal variance below threshold; original time
                retained, warning issued)
        n_suspicious: Count of trials where quality_flag != 0.
    """
    stim_onset_nidq_s: np.ndarray
    onset_latency_ms: np.ndarray
    quality_flags: np.ndarray
    n_suspicious: int
```

---

## 4. 处理步骤

### `calibrate_photodiode`

1. **整体信号质量检查**
   - 将 `photodiode_signal` (int16) 转换为电压：`voltage = signal.astype(float) * (voltage_range / 32768.0)`（32768 = 2^15 for int16 signed）
   - 计算全局信号方差 `np.var(voltage)`
   - 若方差 < `min_signal_variance` → raise `SyncError("Photodiode signal variance {variance:.2e} too low. Check photodiode connection.")`

2. **重采样到 1ms 分辨率**
   - 目标采样率为 1000 Hz（1ms/sample）
   - 计算重采样比率：`up = 1000`，`down = int(round(sample_rate_hz))`（精确使用整数比率）
   - 调用 `scipy.signal.resample_poly(voltage, up, down)` 得到 `pd_1ms`
   - `pd_1ms` 的时间轴：每个采样点对应 1ms，`pd_1ms[i]` 对应 NIDQ 时间 `i / 1000.0` 秒

3. **初始化输出数组**
   - `n_trials = len(stim_onset_times_s)`
   - `result_onsets = stim_onset_times_s.copy()`（初始值为原始数字触发时间）
   - `onset_latency_ms = np.full(n_trials, np.nan)`
   - `quality_flags = np.zeros(n_trials, dtype=int)`

4. **逐 trial 处理（循环 trial 索引 i）**

   a. **处理 NaN onset**：若 `stim_onset_times_s[i]` 为 NaN → `quality_flags[i] = 2`，continue

   b. **提取窗口样本索引**：
      - `t_onset_ms = stim_onset_times_s[i] * 1000.0`
      - `idx_start = int(round(t_onset_ms - pd_window_pre_ms))`
      - `idx_end = int(round(t_onset_ms + pd_window_post_ms))`
      - 越界检查：若 `idx_start < 0` 或 `idx_end > len(pd_1ms)` → `quality_flags[i] = 2`，continue

   c. **提取窗口信号**：`window = pd_1ms[idx_start:idx_end]`，长度 = `pd_window_pre_ms + pd_window_post_ms`

   d. **信号方差检查**：若 `np.var(window) < min_signal_variance` → `quality_flags[i] = 3`，记录警告，continue

   e. **逐 trial z-score 归一化**（独立归一化，不使用全局统计量）：
      - `mean_w = np.mean(window)`；`std_w = np.std(window)`
      - 若 `std_w == 0`：`quality_flags[i] = 3`，continue
      - `z_window = (window - mean_w) / std_w`

   f. **逐 trial 极性检测与校正**（cf. MATLAB step #10: polarity correction）：
      - 计算一阶差分的绝对值：`abs_diff = np.abs(np.diff(z_window))`
      - 找到最大变化点索引：`max_change_idx = np.argmax(abs_diff)`
      - 检测该点的原始差分符号：`raw_diff = np.diff(z_window)[max_change_idx]`
      - 若 `raw_diff < 0`（下降沿 → 暗刺激或反极性 photodiode）：`z_window = -z_window`
      - 这确保所有 trial 的 z-score 信号统一为上升沿极性，使全局阈值计算正确

5. **计算全局阈值**（先收集所有有效 trial z-score 窗口，再统一计算）：
   - 收集所有 `quality_flag == 0` 的 trial z-score 窗口
   - `baseline_values` = 每个有效 trial 窗口中前 `pd_window_pre_ms` 个样本的 z-score，拼接后取均值 `baseline_mean`
   - `stim_values` = 每个有效 trial 窗口中后 `pd_window_post_ms` 个样本的 z-score，拼接后取均值 `stim_period_mean`
   - `global_threshold = 0.1 * baseline_mean + 0.9 * stim_period_mean`

6. **逐 trial 阈值检测（第二次循环，使用 `global_threshold`）**

   a. 跳过 `quality_flags[i] != 0` 的 trial

   b. 在 z-score 窗口的刺激期（从第 `pd_window_pre_ms` 个样本开始）中找第一个超过 `global_threshold` 的样本索引 `first_above`

   c. 若无样本超过阈值：`quality_flags[i] = 3`，记录警告，continue

   d. 计算原始延迟：`latency_raw_ms = first_above`（从刺激期开始的 ms 偏移）

   e. 处理负延迟（信号在触发前超阈）：在刺激期之前（基线段）也找超阈点，若存在则 `latency_raw_ms` 为负 → `quality_flags[i] = 1`，记录警告，continue（不校正，保留原始数字触发时间）

   f. 应用显示器延迟校正：`corrected_latency_ms = latency_raw_ms - monitor_delay_ms`

   g. 更新输出：
      - `onset_latency_ms[i] = corrected_latency_ms`
      - `result_onsets[i] = stim_onset_times_s[i] + corrected_latency_ms / 1000.0`

7. **汇总统计**
   - `n_suspicious = int(np.sum(quality_flags != 0))`
   - 若 `n_suspicious > 0`：记录 warning 日志，列出各 quality_flag 类别的数量

8. **返回 `CalibratedOnsets`**

---

## 5. 公开 API 与可配参数

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pynpxpipe.core.errors import SyncError


@dataclass
class CalibratedOnsets:
    """Photodiode-calibrated stimulus onset times.

    Attributes:
        stim_onset_nidq_s: Refined stim onset times in NIDQ clock seconds.
            Shape (n_trials,). Trials flagged non-zero retain the original
            digital event code time without photodiode correction.
        onset_latency_ms: Measured photodiode onset latency per trial (ms).
            Shape (n_trials,). NaN for trials that were skipped (flag=2).
        quality_flags: Per-trial integer quality indicator. Shape (n_trials,).
            0 = good, 1 = negative_latency, 2 = out_of_bounds, 3 = low_signal.
        n_suspicious: Count of trials where quality_flag != 0.
    """

    stim_onset_nidq_s: np.ndarray
    onset_latency_ms: np.ndarray
    quality_flags: np.ndarray
    n_suspicious: int


def calibrate_photodiode(
    photodiode_signal: np.ndarray,
    sample_rate_hz: float,
    voltage_range: float,
    stim_onset_times_s: np.ndarray,
    monitor_delay_ms: float,
    pd_window_pre_ms: float = 10.0,
    pd_window_post_ms: float = 100.0,
    min_signal_variance: float = 1e-6,
) -> CalibratedOnsets:
    """Calibrate stimulus onset times using the photodiode analog signal.

    Converts the raw NIDQ int16 photodiode channel to voltage, resamples to
    1ms resolution, extracts per-trial windows around digital stim onset times,
    applies per-trial z-score normalization, and detects the first threshold
    crossing to determine actual display onset latency.

    The global detection threshold is computed once across all valid trials:
        threshold = 0.1 * baseline_mean + 0.9 * stim_period_mean
    where baseline is the pre-onset window and stim_period is the post-onset
    window, both in z-score units.

    Quality flags per trial:
        0 - good: photodiode onset detected and latency correction applied.
        1 - negative_latency: signal exceeded threshold before digital trigger;
            warning logged, original digital time retained.
        2 - out_of_bounds: trial window extends beyond recording boundaries or
            stim_onset_times_s[i] is NaN; trial skipped, original time retained.
        3 - low_signal: signal variance too low in this trial's window;
            warning logged, original digital time retained.

    Args:
        photodiode_signal: Raw int16 1D array from the NIDQ analog channel
            (photodiode_channel_index). Length = n_nidq_samples.
        sample_rate_hz: NIDQ analog sampling rate in Hz. Read from nidq.meta
            niSampRate field. Never hardcode.
        voltage_range: ADC full-scale range in volts (single-sided). Read
            from nidq.meta niAiRangeMax field. Never hardcode.
        stim_onset_times_s: 1D float64 array, shape (n_trials,). Digital
            stim onset times in NIDQ clock seconds. May contain NaN.
        monitor_delay_ms: Systematic display delay correction (ms). Read from
            config.sync.monitor_delay_ms. Subtract from onset_latency_ms.
            Typical value for 60Hz monitor is -5ms. Never hardcode.
        pd_window_pre_ms: Baseline window before stim onset (ms). Default 10.0.
            Read from config.sync.pd_window_pre_ms.
        pd_window_post_ms: Detection window after stim onset (ms). Default 100.0.
            Read from config.sync.pd_window_post_ms.
        min_signal_variance: Minimum acceptable signal variance after int16→voltage
            conversion. Default 1e-6.

    Returns:
        CalibratedOnsets with refined onset times, per-trial latencies,
        quality flags, and suspicious trial count.

    Raises:
        SyncError: If the overall photodiode signal variance is below
            min_signal_variance (indicates disconnected photodiode).
    """
```

### 可配参数

| 参数 | 对应配置键 | 说明 |
|---|---|---|
| `monitor_delay_ms` | `config.sync.monitor_delay_ms` | 显示器系统延迟（ms），60Hz 显示器通常为 `-5`，**禁止硬编码** |
| `pd_window_pre_ms` | `config.sync.pd_window_pre_ms` | 基线窗口时长（ms），默认 `10.0` |
| `pd_window_post_ms` | `config.sync.pd_window_post_ms` | 检测窗口时长（ms），默认 `100.0` |
| `voltage_range` | `nidq.meta["niAiRangeMax"]` | ADC 量程（伏特），从 nidq.meta 读取，**禁止硬编码** |
| `sample_rate_hz` | `nidq.meta["niSampRate"]` | 采样率（Hz），从 nidq.meta 读取，**禁止硬编码** |
| `min_signal_variance` | `config.sync.pd_min_signal_variance` | 无信号判定阈值，默认 `1e-6` |

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_io/test_photodiode_calibrate.py`

### 正常情况

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_returns_calibrated_onsets_dataclass` | 单 trial，正常阶跃信号 | 返回类型是 `CalibratedOnsets` |
| `test_good_trial_quality_flag_zero` | 干净阶跃信号，阶跃在 trigger 后 20ms | `quality_flags[0] == 0` |
| `test_onset_latency_detected_correctly` | 信号在 trigger 后 20ms 阶跃，monitor_delay_ms=0 | `onset_latency_ms[0] ≈ 20.0`（±1ms） |
| `test_monitor_delay_applied` | 阶跃在 20ms，`monitor_delay_ms=-5` | `onset_latency_ms[0] ≈ 25.0`（latency_raw - delay = 20 - (-5) = 25） |
| `test_stim_onset_nidq_updated` | trigger 在 1.0s，20ms 阶跃，monitor_delay=0 | `stim_onset_nidq_s[0] ≈ 1.020` |
| `test_multiple_trials_all_good` | 5 trials，各有干净阶跃，latency 10-50ms | 所有 `quality_flags == 0` |
| `test_n_suspicious_zero_when_all_good` | 5 trials 全部 good | `n_suspicious == 0` |
| `test_int16_to_voltage_conversion` | 已知 int16 值和 voltage_range | 转换结果与手动公式 `signal * (range/32768)` 一致 |

### 重采样

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_resample_to_1ms` | `sample_rate_hz=30000.0`，1 秒信号 | 重采样后长度 ≈ 1000 个样本 |
| `test_resample_preserves_step_location` | 已知采样率，已知阶跃样本位置 | 重采样后阶跃时刻误差 < 1ms |
| `test_resample_ratio_from_sample_rate` | `sample_rate_hz=25000.0` | `up=1000, down=25000` 的约分比率正确 |

### 质量标志位

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_negative_latency_flag` | 信号在 trigger 之前就超过阈值 | `quality_flags[0] == 1`，原始时间保留 |
| `test_out_of_bounds_flag_window_start` | `stim_onset_times_s[0]` 使 `idx_start < 0` | `quality_flags[0] == 2` |
| `test_out_of_bounds_flag_window_end` | `stim_onset_times_s[0]` 使 `idx_end > len(pd_1ms)` | `quality_flags[0] == 2` |
| `test_nan_onset_flag_out_of_bounds` | `stim_onset_times_s[0] = np.nan` | `quality_flags[0] == 2` |
| `test_low_signal_per_trial_flag` | 某 trial 窗口内信号方差接近零 | `quality_flags[i] == 3` |
| `test_suspicious_count_matches_flags` | 2 good，1 negative，1 out_of_bounds | `n_suspicious == 2` |
| `test_flagged_trials_retain_original_time` | quality_flag=1 的 trial | `stim_onset_nidq_s[i] == stim_onset_times_s[i]` |

### 阈值计算

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_global_threshold_formula` | 已知 baseline_mean 和 stim_period_mean | `threshold == 0.1 * baseline + 0.9 * stim` |
| `test_threshold_is_global_not_per_trial` | 两 trial 信号不同，但阈值应为全局 | 两 trial 使用相同 `global_threshold` |

### 全局信号质量

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_dead_signal_raises_sync_error` | 全零 int16 信号 | raise `SyncError`，消息含 "variance" |
| `test_near_zero_signal_raises_sync_error` | 信号方差 = 1e-10 < min_signal_variance | raise `SyncError` |
| `test_sync_error_is_pynpxpipe_error` | 死信号输入 | `SyncError` 是 `PynpxpipeError` 子类 |

### 边界情况

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_single_trial` | 只有 1 个 trial | 正常返回，输出数组长度为 1 |
| `test_all_trials_out_of_bounds` | 所有 trial 窗口越界 | 所有 `quality_flags == 2`，`n_suspicious == n_trials` |
| `test_no_threshold_crossing` | 信号平坦，无超阈点 | `quality_flags[i] == 3`，记录警告 |

### 极性校正

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_falling_edge_signal_corrected` | 构造 trial 信号为下降沿阶跃（高→低） | 极性翻转后仍能正确检测 onset，`quality_flags == 0` |
| `test_rising_edge_signal_unchanged` | 构造 trial 信号为上升沿阶跃（低→高） | 不翻转，正常检测，`quality_flags == 0` |
| `test_mixed_polarity_trials` | 3 trials：rising, falling, rising | 所有 trial 均 `quality_flags == 0`，latency 一致（±1ms） |
| `test_polarity_correction_before_threshold` | 全部 falling-edge trials | 全局阈值计算在翻转后的信号上，能正确检测 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `numpy` | 必选 | int16→float 转换、数组运算、z-score、NaN 处理 |
| `scipy.signal.resample_poly` | 必选 | 精确整数比率重采样到 1ms 分辨率 |
| `dataclasses.dataclass` | 标准库 | `CalibratedOnsets` 定义 |
| `pynpxpipe.core.errors.SyncError` | 项目内部 | 信号质量失败时抛出 |

无 matplotlib，无 pandas，无 spikeinterface，无文件 IO。

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #10（Photodiode onset 校准）+ step #11（Monitor delay 校正 -5ms） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #10, #11 段落 |

### MATLAB 算法概要

1. 粗定位：NIDQ bit 6 上升沿 → `onset_LOC`
2. 提取窗口：`before_onset_measure=10ms, after_onset_measure=50ms, after_onset_stats=100ms`
3. z-score 归一化：`zscore(AIN(start:end))`
4. **逐 trial 极性检测**：`max(abs(diff(po_dis)))` 找最大变化点，若 `diff < 0`（下降沿）则 `po_dis(tt,:) = -po_dis(tt,:)`
5. 阈值：`thres = 0.1*baseline + 0.9*highline`（baseline=前 10ms 均值，highline=60-80ms 均值）
6. 检测：`find(po_dis(tt,:)>thres, 1) - before_onset_measure` → latency（ms）
7. Monitor delay：`onset_time_ms = onset_time_ms - 5`（硬编码 60Hz）

### 有意偏离

| 偏离 | 理由 |
|------|------|
| Monitor delay 从 config 读取而非硬编码 | MATLAB 硬编码 -5ms（仅适用 60Hz）；Python 支持不同刷新率 |
| 阈值窗口可配 | MATLAB 硬编码 `before=10, after=50/100`；Python 从 config 读取 |
| Python 增加 `quality_flags` 系统 | MATLAB 无逐 trial 质量标记，失败 trial 静默跳过 |
| 重采样使用 `scipy.signal.resample_poly` | MATLAB 直接在 1kHz AIN 上操作（NIDQ 已是 1kHz 采样），Python 需处理不同采样率 |
| Python stim_onset_times_s 由调用方传入 | MATLAB 内部从 NIDQ bit 6 提取；Python 解耦，由 synchronize stage 组装传入 |
