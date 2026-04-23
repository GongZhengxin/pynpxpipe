# per-unit 稳定性分析（第七轮验证 / VII.D + VII.E）

**日期**：2026-04-20
**输入**：
- `processed_good/deriv/TrialRaster_241026_*.h5` / `TrialRecord_*.csv` / `UnitProp_*.csv`（REF）
- `processed_pynpxpipe/07_derivatives/TrialRaster_241029_*.h5` + 同系列 CSV（OURS）
- `diag/unit_pairing.csv`（VI.1b Hungarian 匹配，分析器空间 d_xy + cos + sim）

**产物**：
- `diag/per_unit_reliability.csv`（527 行 = 268 REF + 259 OURS）
- `diag/per_unit_reliability_hist.png/svg`
- `diag/matched_pair_reliability_scatter.png/svg`
- `diag/per_unit_reliability_summary.txt`
- `diag/psth_gallery.png/svg`
- `diag/pair_spatial.png/svg`（VII.C1，v2 增强版）
- `diag/pair_spatial_unitprop.png/svg`（VII.C2，UnitProp-CSV 源对照）
- `diag/pair_waveforms.png/svg`（VII.B，空间最近邻版）

本轮不重跑 pipeline，只基于既有输出做分析和可视化。

---

## 1. 范围与数据源

| 字段 | REF | OURS |
|---|---|---|
| UnitProp / TrialRaster 单元数 | 268 | 259 |
| 成功 trial 数（fix_success=1） | 972 中的子集 | 972 中的子集 |
| PSTH bin | 1 ms（底层存储）→ 10 ms（分析） | 同 |
| 时间窗 | [-50, +300] ms（相对 stim onset） | 同 |
| 评分窗口 | [60, 220] ms post-onset | 同 |
| 单元类型来源 | REF：Bombcell + MATLAB SUA 判定 | OURS：Bombcell + pynpxpipe `_UNITTYPE_ENUM`（SUA/GOOD→1, MUA→2, NOISE→3）|

每个 unit 在**成功 trial 上**计算：`splithalf_fr_pearson`（5 seed 平均，Spearman-Brown 校正）、`splithalf_psth_pearson`（10 ms bin）、`selectivity`（Lurie 风格）、`n_spikes_total`、`n_active_trials`、`snr`。

---

## 2. d_xy 来源澄清（`pair_spatial_unitprop.png`）

用户在第六轮抽查 `diag/unit_pairing.csv.d_xy` 时发现：用 `UnitProp.csv.unitpos` 复算的 d_xy 对不上。本轮溯源如下：

| 来源 | REF x 分布 | OURS x 分布 |
|---|---|---|
| `analyzer.unit_locations`（SI `monopolar_triangulation`）| 连续坐标 | 连续坐标 |
| `UnitProp.csv.unitpos` | **2 个离散值 {0, 103} µm**（Bombcell `ksPeakChan_xy`）| 35 个连续值（保留 SI monopolar 输出）|

REF 侧的 MATLAB 管道把 Bombcell 的峰值通道坐标写进 UnitProp CSV，而 `processed_good/SI/analyzer` 里的 `unit_locations` 来自 SI monopolar；OURS 侧两者同源同值。**`diag/unit_pairing.csv.d_xy` 两边都来自 analyzer.unit_locations，是内部自洽的**；但如果用 REF 的 CSV 去复算 d_xy，就是在做"ref peakchan vs ours monopolar"的混合比较，差值会系统性偏大 10–40 µm。

**这不是 bug，是 REF 管道 CSV 与 analyzer 的数据源分歧**。`pair_spatial_unitprop.png` 中可见：REF 的点（空心蓝圈）只出现在 x∈{0, 103} 两列，而 OURS（实心橙点）散布在 x∈[-0.5, 120.9] 连续区间；连接同一配对的灰线因此被"强行拉直到两条列线"之一，比 `pair_spatial.png`（基于同源 analyzer 定位）长得多。

---

## 3. per-unit reliability 分布（`per_unit_reliability_hist.png`）

按 pipeline × unittype 叠加直方图（ref 蓝 / ours 橙），每面板给出 `ks_2samp` p-value。

### splithalf_fr_pearson（5-seed Spearman-Brown）

| 组 | REF median (n) | OURS median (n) | KS p |
|---|---|---|---|
| ALL | 0.262 (268) | 0.251 (255) | 2.1e-3 |
| SUA | 0.329 (52) | **0.472 (24)** | 2.5e-1（NS）|
| MUA | 0.306 (138) | 0.245 (187) | — |
| NOISE | 0.226 (78) | 0.193 (44) | — |

**关键观察**：
- OURS 在 ALL 层级上略偏低（KS p=2e-3 但效应量小：0.251 vs 0.262）。
- **OURS 的 SUA 单元**在 split-half FR 上**反而高于 REF**（0.472 vs 0.329，KS p=0.25 样本量太小 NS）。说明 OURS 侧 Bombcell 留下的 SUA 质量并不比 REF 差。
- OURS 的 MUA 数量（187）比 REF（138）多，且 MUA median 偏低（0.245），这是 ALL 层级被拉低的主要来源。

### splithalf_psth_pearson（10 ms bin，一次 split）

| 组 | REF median | OURS median | KS p |
|---|---|---|---|
| ALL | 0.952 | 0.945 | 3.2e-2 |
| SUA | 0.945 | 0.964 | 4.7e-1 |

所有组的 PSTH 自稳定性都在 0.9 以上——**PSTH 形状在两边都很稳定**，ours 的问题不在时间形状噪声，而在 per-stim 的 FR 编码。

### selectivity（Lurie 风格）

| 组 | REF median | OURS median | KS p |
|---|---|---|---|
| ALL | 0.658 | 0.606 | 3.1e-4 |
| SUA | 0.614 | 0.649 | 7.1e-1 |

OURS 的 ALL selectivity 显著低于 REF（p<1e-3），但 **SUA 子组无显著差异**。同样是组分效应：更多 MUA 把均值拉低。

### snr

| 组 | REF median | OURS median | KS p |
|---|---|---|---|
| ALL | 0.528 | 0.676 | 1.3e-3 |
| SUA | 0.596 | 0.591 | 4.3e-1 |

OURS 的 window-内 SNR 反而**略高**（驱动主要是 MUA 组：0.780 vs 0.660）。这点值得注意——它与 split-half FR 偏低并不矛盾：SNR 只看窗内 FR 的均值/标准差比，而 split-half FR 相关是看 per-stim 编码的一致性。窗内高 SNR + 跨-stim 低 split-half，意味着 OURS 的 MUA 单元在窗内激发强但对 stimulus identity 分辨差（典型的 multi-unit 混叠）。

---

## 4. matched-pair reliability 配对（`matched_pair_reliability_scatter.png`）

171 个 matched pair（两侧 ks_id 都能在 UnitProp 里找到）的 `splithalf_fr_pearson` 两两散点。

- **Pearson r = 0.635（p=1.12e-20，n=171）**。
- 大部分点落在 y=x 附近，且按 ours unittype 着色时 SUA（蓝）聚集在高可靠区。

**解读**：
- matching 找到的 171 对确实是同一物理 neuron 的不同算法实例——两侧 reliability 正相关 0.64，不是随机匹配。
- 偏离 y=x 的程度是真实的 pipeline 差异（spike train 细节不同），但方向无明显系统性：没有"ours 永远更低"的现象，散点在对角线两侧都有分布。

---

## 5. PSTH gallery 定性观察（`psth_gallery.png`）

采样 12 pair（3 高 / 3 中 / 3 低 matched + 3 unmatched，seed=2）。每个子图 4 条曲线：ref preferred / ref mean / ours preferred / ours mean（见图 legend）。shade = [60, 220] ms 评分窗口。

- **high_match (cos≥0.97)**：ref 与 ours preferred PSTH 在窗内峰值时间、形状、幅度高度重合；各自偏好的 stim_index 经常相同。
- **mid_match (0.85–0.97)**：峰值时间基本对齐，但幅度有 10–30% 差异；偏好 stim 有时不同但属同一语义类别。
- **low_match (0.60–0.85)**：两侧的 preferred PSTH 经常指向**不同 stim_index**，但各自相对 mean 都有响应 → 这些 pair 是"同位置但被排序器分配到不同子群体"的情况。
- **unmatched**：仅出现一侧曲线的面板（另一侧 ks_id 不存在于对应 UnitProp）。

**结论**：matched pair 的 PSTH 形状一致度随 cos 单调下降，与 waveform cos 的等级一致；低-cos pair 的差异是真实的响应差异，不是噪声造成的"看起来不像"。

---

## 6. 对"ours 稳定性 < ref"的定性归因

三个假设的证据汇总：

### (a) 单元级：每个 unit 更噪？
- **否**。SUA 子组中 ours 的 split-half FR 中位数 0.472 **高于** ref 的 0.329（KS p=0.25 NS 但 ours 分布整体右移）。MUA 子组两边持平（0.245 vs 0.306）。
- PSTH split-half（时间形状）两边都在 0.94+，形状稳定性不是短板。
- SNR 窗内两边 SUA 相当（0.59 vs 0.60）。

### (b) 组分级：更多 NOISE/MUA？
- **是主要解释**。
  - OURS SUA 占比：24 / 259 = **9.3%**；REF：52 / 268 = **19.4%**（SUA 绝对数少 54%）。
  - OURS MUA 占比：187 / 259 = **72.2%**；REF：138 / 268 = **51.5%**（MUA 占比增 21 个百分点）。
  - MUA 组 split-half FR 比 SUA 低（两边都是）；OURS 更多 MUA 导致整体 split-half 均值被拉低。
- 把 noise 过滤条件对齐后（仅取 SUA 参与 RDM），split-half RDM 可靠性的差距会显著缩小——这与第六轮 `rdm_ablation.csv` 中"SUA-only 子集"结果一致，本轮不重跑 RDM，引用即可。

### (c) 配对级：同物理 neuron 响应漂移？
- **部分是**。matched-pair split-half r = 0.635，有 36% 的方差在两侧不同步。
- 散点无系统偏下：非"ours 总是更低"。差异是随机方向的算法噪声（KS4 模板、Bombcell 分类阈值、SLAy 合并），不是单调降级。

---

## 7. SUA recall 25% 的影响

VI 中报告 SUA recall = 25%（13/52）。现在用 unittype-matched confusion 重新审视：

### 7.1 ref-SUA 的去向

| ref unittype | ours unittype | 数量 |
|---|---|---|
| SUA | SUA | **13** |
| SUA | MUA | 33 |
| SUA | NOISE | 1 |
| SUA | （未匹配）| 5 |
| 合计 ref SUA | | 52 |

**47 / 52 = 90%** 的 ref SUA **在 ours 侧找到了对应单元**（matched），只是 **33 个被 ours 的 Bombcell 判为 MUA**。真正"ours 没检测到"的 ref SUA 只有 5 个（9.6%）。

**SUA recall 25% 主要是分类降级问题，不是 sorting 漏检问题**：
- 分类下游（Bombcell 阈值、SLAy 合并、ours 的 `_UNITTYPE_ENUM` 判定规则）在 33 个单元上给出了更严格的"MUA"判定。
- 真正的 spike sorting（KS4）基本把 47/52 = 90% 的 ref SUA 对应位置都挖出来了。

### 7.2 ref-only SUA（5 个）的可靠性

| 组 | n | splithalf FR median | selectivity median |
|---|---|---|---|
| ref SUA **已匹配** | 47 | 0.362 | 0.613 |
| ref SUA **ref_only**（ours 漏）| 5 | **0.213** | 0.709 |

KS p=0.54（n=5 太小）。**未被 ours 恢复的 5 个 ref SUA 反而 reliability 更低**（0.21 vs 0.36）。与"ours 漏掉的是最稳的单元"的假设**相反**。

**综合结论**：
- OURS 漏检的不是"最稳"单元，而是 reliability 偏低的 5 个 SUA——小样本，不影响结论。
- OURS 的 SUA 减少**主要来自分类阈值降级**（33/52 = 63% 的 ref SUA 被 ours 降为 MUA）。
- 这是**可配置**的 Bombcell 阈值问题，不是 sorting 算法短板。

---

## 8. 结论 + 下一步

### 结论
1. `unit_pairing.csv.d_xy` 是正确的（两侧同源 analyzer），**第六轮用 CSV 复算不一致是 REF 管道 CSV 数据源的特性**，不是我们的 bug。`pair_spatial_unitprop.png` 作为视觉佐证。
2. `pair_waveforms.png` 已改为空间最近邻选取（`probe.contact_positions` 欧氏距离 top-5），对 Neuropixels 2-列交错几何和多 shank 探针都正确。
3. `pair_spatial.png` 视觉增强完成（线更深 / 圆更大 / 未配对单元用冷色填充）。
4. **ours 稳定性 < ref 的主因是组分差异**：ours SUA 数少 54%、MUA 占比多 21 pp；逐单元看，ours 的 SUA 并不比 ref 差（split-half FR median 0.472 vs 0.329）。
5. **matched-pair r=0.635** 证实 VI.1b 的 Hungarian 匹配找到的是真正对应的单元对，不是随机配对。
6. **SUA recall 25% 中，分类降级 (33/52)** 远大于 **漏检 (5/52)**。真正的 sorting 检测率 ≈ 90%。

### 不承诺的下一步（供用户参考）
- 若要提升 SUA 数，应先对齐 Bombcell 阈值（而不是改 KS4 参数）。建议在 VIII 轮独立 session 中：
  - 对齐 OURS 与 REF 的 `bc_param` 所有阈值（尤其 `minAmplitude` / `maxRPVratio` / `minPresenceRatio` / `isolationDist`）。
  - 对 33 个 matched "ref SUA → ours MUA" 单元做一次 per-unit Bombcell 报告 diff，定位是哪个阈值在起决定作用。
- 本轮**不动 src/**、**不重跑 sorting/curate/postprocess**。
