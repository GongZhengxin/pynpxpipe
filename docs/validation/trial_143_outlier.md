# V.2.1 — Trial 143 离群诊断

**日期**：2026-04-20
**范围**：单 trial 离群分析，无代码改动

## 观测

TrialRecord.csv 中 `start_time` 差值 `ours - ref`（毫秒）在 972 个 trials 上的分布：

| 统计 | 值 (ms) |
|------|---------|
| median | +12.9 |
| std | 2.1 |
| min | **−12.6** (trial 143) |
| max | +17.6 |

除 trial 143 外的其他 trials：`|residual|` 相对局部中位数 ≤ 1.4 ms。**只有 trial 143 偏离 24 ms**。

局部数据：

| trial | ref_t0 (s) | ours_t0 (s) | dt (ms) |
|-------|------------|-------------|---------|
| 141 | 86.201677 | 86.212977 | +11.30 |
| 142 | 86.501682 | 86.513073 | +11.39 |
| **143** | **86.800686** | **86.788075** | **−12.61** |
| 144 | 88.935656 | 88.946790 | +11.13 |
| 145 | 89.236632 | 89.246792 | +10.16 |

## 根因

`processed_pynpxpipe/04_sync/behavior_events.parquet` 中 trial 143 是 **972 个 trials 里唯一 `onset_latency_ms=NaN`、`quality_flag=1` 的一行**：

| 列 | trial 143 | 其他 971 trials |
|----|-----------|------------------|
| onset_latency_ms | NaN | median 27.0 ms（std < 1） |
| quality_flag | 1 ("negative latency") | 0 |
| trial_valid | 0 (fix 失败) | 多数 1 |

`quality_flag=1` 对应 `src/pynpxpipe/io/sync/photodiode_calibrate.py:231-236`：
> "negative latency — threshold crossed before digital trigger"

即**在 digital trigger 上升沿之前**，photodiode 信号已高于阈值。典型场景是"前一 trial 的 PD bright 还未回到 baseline，就收到了下一 trial 的 trigger"（尤其在 fix-break-abort 导致 ITI 被截断时）。trial 143 的 `trial_valid=0` / `fix_success=0` 与这个典型场景吻合。

**关键代码行为**（photodiode_calibrate.py:128-241）：

```python
result_onsets = stim_onset_times_s.copy()       # 初始化为 trigger 原始时间
...
if quality_flags[i] != 0:                        # PD 检测失败
    continue                                     # result_onsets[i] 保持 trigger 时间
...
result_onsets[i] = stim_onset_times_s[i] + corrected_latency_ms / 1000.0  # 正常 trial 加监视器延迟
```

**即：PD 校准失败的 trial，`stim_onset_nidq_s` 使用未校正的 trigger 时间；正常 trial 则加上 `corrected_latency_ms ≈ 25 ms` 的监视器延迟。** trial 143 少了这 25 ms，所以看起来比邻居早 ~24 ms。

**数值验证**：
- BHV2 timestamp delta (142→143) = **300.042 ms**
- NIDQ stim_onset_nidq_s delta (142→143) = **275.003 ms**
- 差 = **25.039 ms** ≈ 1 帧 @ 60 Hz 监视器刷新率 ≈ `onset_latency_ms` 全 session 中位数 27 ms

## 结论

这 **不是 BHV2↔NIDQ 事件码匹配错位**（原 V.2.1 假设），而是 **PD 校准失败时的 fallback 行为**：

1. Pipeline 把 `stim_onset_nidq_s` 保留为未校正的 trigger 时间
2. `quality_flag=1` 正确标记了这个异常
3. Trial 本就 `trial_valid=0`（fix 失败），所有 `fix_success only` 分析已经丢弃它
4. 仅 `all trials` 分析会看到它 `start_time` 偏早 ~25 ms

## 是否修复

**不修**（按 V.2.1 标注 "可跳过，影响单 trial"），理由：

- 影响范围：972 trials 中 1 个（0.1%），且这个 trial 本身就是 invalid
- 定量化分析（RSM、PSTH 等）已经用 `fix_success only` 过滤掉
- 若下游需要 all-trials 一致时间，可在消费端对 `quality_flag != 0` 的行用中位数 latency 补齐

## 可选的未来修复（不属于本轮）

`photodiode_calibrate.py` 在 step 7 摘要后，增加一个"补齐 pass"：

```python
# For trials with quality_flag != 0, impute corrected latency from valid-trial median
if n_suspicious > 0:
    valid_mask = quality_flags == 0
    median_lat_ms = float(np.nanmedian(onset_latency_ms[valid_mask]))
    for i in np.where(quality_flags != 0)[0]:
        if not np.isnan(stim_onset_times_s[i]):
            result_onsets[i] = stim_onset_times_s[i] + median_lat_ms / 1000.0
            # onset_latency_ms[i] 保持 NaN（区别于真实测量）
```

同时在 NWB `trials` 列 description 里明确 "latency-imputed trials are flagged via quality_flag"。此改动需要：
- 1 个 regression test（mock trial with negative-latency flag → verify result_onsets gets imputed）
- 更新 `docs/specs/photodiode_calibrate.md` 描述
- 重跑 sync stage

不在 V.2.1 范围内，留到未来决定是否采纳。

---

**产物**：本文件 + `diag/unit_pairing.csv` / `diag/unit_pairing_summary.txt` （V.8）+ `docs/validation/rsm_report.md` （V.3/V.7/V.8）
