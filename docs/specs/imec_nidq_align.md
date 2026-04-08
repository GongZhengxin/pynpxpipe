# Spec: io/sync/imec_nidq_align.py

## 1. 目标

对单个 IMEC probe 的 AP 时钟与 NIDQ 时钟进行线性对齐。从两侧的同步脉冲上升沿时间序列出发，通过最小二乘线性回归建立校正函数 `t_nidq = a × t_imec + b`，验证残差在容忍阈值内，返回结构化的对齐结果。

本模块属于 IO 层，无任何 stage 逻辑、无 checkpoint、无 UI 依赖。输入输出均为 numpy 数组或 Python dataclass。可独立调用和独立测试。

---

## 2. 输入

| 参数 | 类型 | 说明 |
|---|---|---|
| `probe_id` | `str` | 探针标识符，如 `"imec0"`，仅用于结果标注和错误消息 |
| `ap_sync_times` | `np.ndarray` (float64, 1D) | 从 AP 数据流提取的同步脉冲上升沿时间，单位：秒（AP 时钟） |
| `nidq_sync_times` | `np.ndarray` (float64, 1D) | 从 NIDQ 数据流提取的同步脉冲上升沿时间，单位：秒（NIDQ 时钟） |
| `max_time_error_ms` | `float` | 允许的最大 RMS 残差（毫秒），默认 `17.0` |
| `gap_threshold_ms` | `float \| None` | 丢脉冲检测阈值（毫秒）。正常脉冲间隔约 1000ms，超过此阈值的间隔视为丢脉冲并尝试插值修复。`None` 禁用修复（要求两数组等长）。默认 `1200.0`，从 `config.sync.gap_threshold_ms` 读取。 |

约束：
- 若 `gap_threshold_ms` 为 `None`：两数组长度必须相同
- 若 `gap_threshold_ms` 不为 `None`：允许长度不同，修复后仍不等 → raise SyncError
- 两数组长度必须 >= 2（少于 2 个脉冲无法拟合）
- 两数组均不得含 NaN 或 Inf

---

## 3. 输出

```python
@dataclass
class SyncResult:
    probe_id: str       # 探针标识符，来自输入
    a: float            # 线性系数（斜率）：t_nidq = a * t_imec + b
    b: float            # 线性系数（截距），单位：秒
    residual_ms: float  # RMS 对齐误差，单位：毫秒
    n_repaired: int     # 修复的丢脉冲总数（AP 侧 + NIDQ 侧），未启用修复时为 0
```

使用方式：对任意 IMEC 时刻 `t_imec`，计算对应 NIDQ 时刻：
```python
t_nidq = sync_result.a * t_imec + sync_result.b
```

---

## 4. 处理步骤

1. **输入验证**
   - 检查两数组均不含 NaN/Inf → raise `SyncError("Sync times contain NaN or Inf for probe {probe_id}")`
   - 检查每侧长度 >= 2；不足 → raise `SyncError("Insufficient sync pulses: need >= 2, got {n} for probe {probe_id}")`

2. **丢脉冲检测与修复**（仅当 `gap_threshold_ms` 不为 `None` 时执行）

   MATLAB 参考：step #6 检测 NI 侧 >1200ms 间隔并插值修复。Python 实现对称地处理双侧。

   a. 对 `ap_sync_times` 和 `nidq_sync_times` 各自计算相邻脉冲间隔：`intervals = np.diff(times)`
   b. 计算中位间隔 `median_interval = np.median(intervals)`
   c. 检测异常间隔：`gap_mask = intervals > gap_threshold_ms / 1000.0`
   d. 对每个异常间隔，估算丢失脉冲数 `n_missing = round(interval / median_interval) - 1`
   e. 在异常间隔处插入 `n_missing` 个等间距插值点：`inserted = np.linspace(t_start, t_end, n_missing + 2)[1:-1]`
   f. 将插入点合并回原数组，保持排序
   g. 记录各侧修复数量 `n_repaired = n_repaired_ap + n_repaired_nidq`
   h. 修复后检查 `len(ap_sync_times) == len(nidq_sync_times)`；仍不等 → raise `SyncError("Sync pulse count mismatch after repair: AP={n_ap}, NIDQ={n_nidq} for probe {probe_id}. gap_threshold_ms={gap_threshold_ms}.")`
   i. 若 `n_repaired > 0`：记录 WARNING 日志，含各侧修复数量

   若 `gap_threshold_ms` 为 `None`：
   - 直接检查 `len(ap_sync_times) == len(nidq_sync_times)`；不匹配 → raise `SyncError("Sync pulse count mismatch: AP={n_ap}, NIDQ={n_nidq} for probe {probe_id}")`
   - `n_repaired = 0`

3. **线性回归**
   - 调用 `np.polyfit(ap_sync_times, nidq_sync_times, 1)` → 返回 `[a, b]`
   - `a` 为斜率（接近 1.0 说明两时钟速率匹配），`b` 为截距

4. **残差计算**
   - `predicted = a * ap_sync_times + b`
   - `residuals_ms = (nidq_sync_times - predicted) * 1000`
   - `residual_ms = np.sqrt(np.mean(residuals_ms ** 2))` （RMS，单位毫秒）

5. **残差验证**
   - 若 `residual_ms > max_time_error_ms` → raise `SyncError("Alignment residual {residual_ms:.3f} ms exceeds threshold {max_time_error_ms} ms for probe {probe_id}")`

6. **返回结果**
   - 构造并返回 `SyncResult(probe_id=probe_id, a=a, b=b, residual_ms=residual_ms, n_repaired=n_repaired)`

---

## 5. 公开 API 与可配参数

```python
@dataclass
class SyncResult:
    probe_id: str
    a: float
    b: float
    residual_ms: float
    n_repaired: int


def align_imec_to_nidq(
    probe_id: str,
    ap_sync_times: np.ndarray,
    nidq_sync_times: np.ndarray,
    max_time_error_ms: float = 17.0,
    gap_threshold_ms: float | None = 1200.0,
) -> SyncResult:
    """Fit a linear time correction from IMEC AP clock to NIDQ clock.

    Uses sync pulse rising-edge times from both streams to perform
    least-squares linear regression: t_nidq = a * t_imec + b.

    When gap_threshold_ms is not None, missing pulses are detected
    (intervals exceeding the threshold) and repaired by interpolation
    before regression. This handles the common case where one side
    drops sync pulses during recording.

    Args:
        probe_id: Probe identifier string (e.g. "imec0"), used for labeling.
        ap_sync_times: Rising-edge times from AP digital sync channel, in
            AP clock seconds. Must be 1D float64.
        nidq_sync_times: Rising-edge times from NIDQ digital sync channel, in
            NIDQ clock seconds. Must be 1D float64.
        max_time_error_ms: Maximum allowed RMS residual in milliseconds.
            Default 17.0 ms. Raise SyncError if exceeded.
        gap_threshold_ms: Missing-pulse detection threshold in ms. Intervals
            exceeding this value are treated as dropped pulses and repaired
            by interpolation. None disables repair (arrays must be same
            length). Default 1200.0. Read from config.sync.gap_threshold_ms.

    Returns:
        SyncResult with slope a, intercept b, RMS residual, and repair count.

    Raises:
        SyncError: If arrays contain NaN/Inf, insufficient pulses,
            pulse counts mismatch (after repair if enabled), or
            RMS residual exceeds max_time_error_ms.
    """
```

可配参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `max_time_error_ms` | `17.0` | RMS 残差上限（毫秒）。17ms 约等于 60Hz 显示器一帧，是典型的可接受误差上限。**必须从 config 传入，禁止硬编码。** |
| `gap_threshold_ms` | `1200.0` | 丢脉冲检测阈值（毫秒）。正常脉冲间隔约 1000ms。设为 `None` 可禁用修复。**必须从 config 传入。** |

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_io/test_imec_nidq_align.py`

### 正常情况

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_perfect_alignment` | `nidq = ap + 0.5`（纯平移，1000 个脉冲，间隔 1.0s） | `a ≈ 1.0`，`b ≈ 0.5`，`residual_ms ≈ 0.0` |
| `test_clock_drift` | `nidq = 1.0000001 * ap + 0.1`（轻微时钟漂移） | `a ≈ 1.0000001`，`b ≈ 0.1`，`residual_ms < 0.1` |
| `test_minimum_pulses` | 恰好 2 个脉冲 | 不 raise，返回有效 SyncResult |
| `test_residual_within_threshold` | 加入随机噪声 < 1ms | 不 raise，`residual_ms < max_time_error_ms` |
| `test_result_probe_id_preserved` | `probe_id="imec1"` | 返回的 `SyncResult.probe_id == "imec1"` |
| `test_returns_syncresult_dataclass` | 任意有效输入 | 返回类型是 `SyncResult` |
| `test_conversion_correctness` | 已知 `a=1.0, b=0.5`，验证校正公式 | `a * t + b` 与 nidq 时间吻合 |

### 边界情况

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_residual_exactly_at_threshold` | 构造 residual 恰好等于 `max_time_error_ms` | 不 raise（`>` 不包含等于） |
| `test_residual_just_above_threshold` | 构造 residual 略大于 `max_time_error_ms` | raise `SyncError` |
| `test_custom_max_time_error` | 传入 `max_time_error_ms=5.0`，residual 在 6ms | raise `SyncError` |
| `test_large_pulse_count` | 10000 个脉冲（模拟长 session） | 正常返回，不超时 |

### 错误情况

| 测试名 | 输入构造 | 预期异常 |
|---|---|---|
| `test_mismatched_lengths` | `ap` 长度 100，`nidq` 长度 99 | raise `SyncError`，消息含 "mismatch" |
| `test_empty_arrays` | 两者均为空数组 | raise `SyncError` |
| `test_single_pulse` | 各 1 个脉冲 | raise `SyncError`（需要 >= 2） |
| `test_nan_in_ap` | `ap_sync_times` 含 NaN | raise `SyncError` |
| `test_nan_in_nidq` | `nidq_sync_times` 含 NaN | raise `SyncError` |
| `test_inf_in_ap` | `ap_sync_times` 含 Inf | raise `SyncError` |
| `test_high_residual` | `nidq` 相对 `ap` 加入 50ms 随机噪声 | raise `SyncError`，消息含 "residual" 和 "ms" |
| `test_sync_error_message_contains_probe_id` | `probe_id="imec2"`, mismatched lengths | raise `SyncError` 消息含 `"imec2"` |

### 数值正确性

| 测试名 | 验证内容 |
|---|---|
| `test_polyfit_consistency` | `a, b` 与直接调用 `np.polyfit` 结果一致 |
| `test_rms_residual_formula` | 手动计算 `residual_ms` 与函数返回值一致（数值精度 1e-10） |

### 丢脉冲修复

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_repair_single_missing_nidq_pulse` | AP 有 100 脉冲间隔 1.0s；NIDQ 有 99 脉冲，第 50 个后有 2.0s gap | `n_repaired == 1`，修复后回归成功 |
| `test_repair_single_missing_ap_pulse` | NIDQ 有 100 脉冲；AP 有 99 脉冲，第 30 个后有 2.0s gap | `n_repaired == 1`，修复后回归成功 |
| `test_repair_multiple_gaps` | NIDQ 丢 2 个脉冲（两处 gap），AP 完整 | `n_repaired == 2` |
| `test_repair_both_sides` | AP 丢 1 个，NIDQ 丢 1 个 | `n_repaired == 2` |
| `test_repair_disabled_with_none` | `gap_threshold_ms=None`，长度不同 | raise `SyncError` |
| `test_repair_not_needed_same_length` | 两侧等长无 gap | `n_repaired == 0` |
| `test_repair_fails_large_mismatch` | AP 100 脉冲，NIDQ 90 脉冲，无对应 gap | raise `SyncError`，含 "after repair" |
| `test_repair_preserves_regression_accuracy` | 修复 1 个脉冲后，`residual_ms` 仍 < 1.0ms | 回归精度不受修复影响 |
| `test_n_repaired_in_result` | 有修复的场景 | `SyncResult.n_repaired > 0` |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `numpy` | 必选 | `polyfit`，数组运算 |
| `dataclasses.dataclass` | 标准库 | `SyncResult` 定义 |
| `core/errors.py` 中的 `SyncError` | 项目内部 | 同步失败时抛出 |

无 IO 操作，无文件读写，无 matplotlib，无 pandas，无 spikeinterface。

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #6（`examine_and_fix_sync.m`） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #6 段落 |

### MATLAB 算法概要

1. NI 侧：`find(diff(bitand(DCode_NI.CodeVal,1))>0)` 提取 bit 0 上升沿
2. IMEC 侧：`DCode_IMEC.CodeVal==64` 过滤 sync 上升沿
3. 丢脉冲检测：`diff(NI_time) > 1200` ms 为异常间隔
4. 修复：`(NI_time(idx) + NI_time(idx+1)) / 2` 中值插值
5. 时钟漂移：`terr(ii) = NI_time(ii) - imec_time(ii)` 逐脉冲误差

### 有意偏离

| 偏离 | 理由 |
|------|------|
| Python 对 AP 和 NIDQ 双侧对称修复 | MATLAB 仅修复 NI 侧；Python 通用化处理，AP 侧同样可能丢脉冲 |
| 使用最小二乘线性回归而非逐点差值 | MATLAB 也做了 `terr` 逐点差值但用于诊断图；回归更鲁棒且输出可直接用于时间校正 |
| 中值插值改为等间距多点插值 | MATLAB 仅插入 1 个中值点（假设只丢 1 个脉冲）；Python 根据间隔估算丢失数量，插入多点 |
| gap 阈值可配 | MATLAB 硬编码 1200ms；Python 从 config 读取，默认值相同 |
