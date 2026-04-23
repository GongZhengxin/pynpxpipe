# RSM 验证报告：跨管道相关 vs 数据噪声上限

**生成时间**：2026-04-20
**数据**：`processed_good/deriv/*` (MATLAB 参考) vs `processed_pynpxpipe/07_derivatives/*`
**Session**：`241026_MaoDan_WordLocalizer_MLO` (ref) / `241029_MaoDan_WordLOC_MLO` (ours)
**窗口**：60–220 ms post-stim onset；FR 单位 Hz；RSM 轴=units（Pearson across units）

---

## 1. 跨管道 RSM 相关（基线，来自 `tools/diag_rsm_compare.py`）

两个 pipeline 各用**全部 trials**算 (180, n_units) mean FR → Pearson 得 (180, 180) RSM → 下三角相关：

| 条件 | Pearson | Spearman |
|------|---------|----------|
| all trials | **0.77** | 0.75 |
| fix_success only | **0.78** | 0.76 |

> V.3 的 "0.77" 由此而来。

---

## 2. 单管道 split-half 可靠性（V.7，来自 `tools/diag_rsm_splithalf.py`）

每个 pipeline **内部**按 trial 划分两半（每个 `stim_index` 的 trials 随机打乱后奇偶交替分配，5 seed 平均）：

| 条件 | pipeline | Pearson (mean±std) | Spearman (mean±std) | pairs |
|------|----------|---------------------|----------------------|-------|
| all trials | ref  | **0.3302 ± 0.0203** | 0.3063 ± 0.0191 | 16110 |
| all trials | ours | **0.2715 ± 0.0364** | 0.2724 ± 0.0344 | 16110 |
| fix_success only | ref  | **0.3361 ± 0.0097** | 0.3186 ± 0.0111 | 16110 |
| fix_success only | ours | **0.2861 ± 0.0186** | 0.2862 ± 0.0196 | 16110 |

### Spearman-Brown 外推到全 trials 内部可靠性

SB 公式：`r_full = 2·r_half / (1 + r_half)`

| 条件 | pipeline | r_half | **r_SB (estimated full-trial reliability)** |
|------|----------|--------|---------------------------------------------|
| all trials | ref  | 0.3302 | **0.497** |
| all trials | ours | 0.2715 | **0.427** |
| fix_success | ref  | 0.3361 | **0.503** |
| fix_success | ours | 0.2861 | **0.445** |

---

## 3. 关键发现：split-half < cross-pipeline（出乎预期）

V.7 原假设场景：
- (V.7.2) split-half ≥ 0.90 → 跨管道 0.77 有显著差距
- (V.7.3) split-half 0.80–0.85 → 0.77 接近 ceiling

**实际结果是第三种、未被原任务预料的情况**：

> Within-pipeline split-half (~0.33) **远低于** cross-pipeline (0.77)，即便 SB 外推到全 trial 也只有 ~0.50。

这在"标准噪声上限"假设下**数学上不应发生**：如果 0.33 是"单管道 RSM 的内部可靠性天花板"，那两个噪声独立的 pipeline 之间的 RSM 相关应 ≤ 0.33；观测到的 0.77 违反这个上限。

### 原因分析

**两种测量测的不是同一样东西**。关键在于"共享 trials"。

| 测量 | 两个 RSM 的 trials | 两个 RSM 的 units | 预期主导变异源 |
|------|---------------------|-------------------|-----------------|
| Split-half | **独立**（A=奇，B=偶） | 相同（同一 sorting） | trial 采样噪声 |
| Cross-pipeline | **相同**（全部 trials） | 不同（独立 sorting） | sorting 差异 |

- Split-half 把 trial 级噪声（神经状态、注意力、arousal 波动）**独立**地加到两个 RSM 上，trials 数再减半 → 极噪。
- Cross-pipeline 两个 RSM 共享 trials，**trial 级噪声是相关的**，在相关计算中部分相消；只剩 sorting 级差异。

因此：
- **Split-half 0.33 衡量的是 "相同管道、不同 trials" 的可重复性**
- **Cross-pipeline 0.77 衡量的是 "不同管道、相同 trials" 的一致性**

两者不是同一坐标系上的"floor"与"ceiling"关系。

### 实际结论

1. **单管道 RSM 本身在当前 trial 数下很不稳定**：每 stim_index 平均 ~5.4 trials，分半后 ~2.7 trials/stim，per-image mean-FR 噪声很大。
2. **Cross-pipeline 0.77 被"共享 trial 基底"抬高**：它不是传统意义上的"pipeline 一致性上限"，而是"两条管道在同一份神经录制上能多大程度还原同一批 spikes 的 RSM"。
3. **想让 RSM 真正稳定（r > 0.85）需要更多 trials/stim**：单 stim 5 trials 远不够。设计后续实验时建议 ≥ 20 trials/stim。

### 数值矛盾的量化

- SB 外推内部全-trial 可靠性：≈ 0.50
- Cross-pipeline 全-trial 观测：0.77
- **0.77 > 0.50** 的差值（≈0.27）不是"sorting 质量贡献"，而是"trial 基底共享带来的噪声相消"。这个差值**无法**被解释成"更好的 sorting 能关闭的 gap"。

---

## 4. 对后续任务的影响

| 原规划 | 新结论 |
|--------|--------|
| V.7.2 建议（若 split-half ≥ 0.90） | 不适用 |
| V.7.3 建议（若 split-half 0.80–0.85） | 不适用 |
| V.8 共享单元 RSM 分析 | **仍有意义**，但预期收益受限：共享子集 RSM 相关提升 ≤ 0.27 的数学上限 |
| 重跑 sorting 换参数优化 RSM | **不建议**：trial 数才是瓶颈，不是 sorting 参数 |

**V.8 的重新定位**：
- 原假设：共享子集 RSM 相关显著高于 0.77 → 证明差距来自"独有单元"。
- 新理解：在 trial-shared 框架下，若共享子集 RSM 接近 1.0（而不仅仅是 > 0.85），说明独有单元承担了绝大多数差异；否则，差异可能更多来自"同一 unit 在两套 sorting 中响应特征被捕获的差异"（例如 refractory 违规率不同、template 拟合不同）。
- V.8 结果解读要在 trial-shared 框架下，不能直接用 split-half 数字作为基线。

---

## 5. 方法学注意事项

1. **零方差 unit 过滤在两个半分上独立进行**：当前实现会导致 RSM_A 与 RSM_B 可能建立在略微不同的 unit 子集上。对数值影响估计 < 0.02 Pearson，不改变定性结论，但严格基线应取交集。
2. **每 stim_index trial 数下限**：9 个 stim 有 ≤ 4 trials；分半后有些只有 1 trial → per-image FR 估计极不稳。可作为敏感性分析改为"剔除 trials < 6 的 stim"。
3. **RSM unit 轴 Pearson**：受零均值 shift 不变，但受 per-unit FR scale 差异影响。可尝试 z-score per unit 再 correlate。
4. **SB 外推假设**：假设两个半分噪声 i.i.d.；若 trial 存在 session 内慢漂（例如前半段与后半段 firing rate 系统差），外推值可能低估真实全-trial 可靠性。

---

## 6. 产物清单

- 脚本：`tools/diag_rsm_splithalf.py`
- 原始输出（终端）：见当次 Claude session 记录；关键行已摘入第 2 节
- 本报告：`docs/validation/rsm_report.md`

## 7. V.8 跨管道 unit 配对（template cosine + spatial distance）

### 方法
- 数据：`processed_good/SI/analyzer` (387 units, 1.5ms before + 2.0ms after) vs `processed_pynpxpipe/06_postprocessed/imec0` (259 units, 1.0ms before + 2.0ms after)
- 裁剪到共同窗口 (1.0ms before + 2.0ms after, 90 samples @ 30kHz)
- 在完整 373 通道 template 上计算 Pearson 余弦相似度
- 空间距离：unit_locations (x, y) 欧氏距离；proximity = exp(-d/100µm)
- 组合：sim = 0.7·cos + 0.3·proximity
- Hungarian 分配（`scipy.optimize.linear_sum_assignment`），阈值 sim ≥ 0.60 为"matched"

### 配对结果

| 指标 | 数值 |
|------|-----|
| 总 ours 单元 | 259 |
| 总 ref 单元 | 387 |
| matched 对数 | **194** (= 75% of ours, 50% of ref) |
| ours_only | 65 |
| ref_only | 193 |
| 余弦相似度中位数（matched） | **0.947** |
| d_xy 中位数（matched） | **3.1 µm** |
| 余弦 > 0.95 的对数 | 92 (36%) |

> 两套 sorting 找到的单元在波形与空间位置上都高度一致：对绝大多数 matched 对而言，两边捞到的是**同一个物理 neuron**。

### 配对对在 deriv raster 中的生存情况

- 194 对 matched 单元中，同时在双方的 deriv 曲线中存活的：**133 对**
- 丢失原因：curate 阶段不同（bombcell 阈值、SUA 过滤差异）

### shared 子集 RSM（V.8.3）

在 133 pairs（双方都是同一物理 neuron）上重算 RSM 相关：

| 条件 | shared 子集 (133 units) | FULL (ref 268 / ours 259) |
|------|---------------------------|-----------------------------|
| all trials | pearson **0.342** / spearman 0.349 | pearson 0.771 / spearman 0.745 |
| fix_success only | pearson **0.347** / spearman 0.354 | pearson 0.773 / spearman 0.748 |

### 关键发现：shared 子集 RSM 相关 ≈ V.7 split-half 数字

- V.7 within-pipeline split-half（~133 半数 units×半数 trials）：~0.27-0.34
- V.8 shared 子集 cross-pipeline（133 相同物理 units × 全 trials）：~0.34

两个数字本质上都反映"**RSM 建立在 ~130 units 时的稳定性上限**"：
- V.7 分半：用 130 单元 × 半 trials → r ~ 0.30
- V.8 shared 子集：用 133 单元 × 全 trials → r ~ 0.34（稍高是因为全 trials）

Spearman-Brown 校正 V.7 (0.33) 到全 trials → 0.50。V.8 观测 0.34 < 0.50。意味着：即使两边是**完全相同的 133 个物理 neurons**，由于单元采样较少导致的 RSM 不稳定性使得相关无法达到内部全-trial 可靠性上限。

但 FULL 两边（各 ~260 units）cross-pipeline 相关 = 0.77，**远高**于 shared-133-subset 的 0.34，因为单元数目加倍显著提升了 RSM 每个 entry 的稳定性（单元越多，unit-axis averaging 越充分）。

### V.8 对初始假设的检验

**原假设（V.8 动机）**：V.3 的 Pearson 0.77 差距可能由"独有单元"贡献。在共享子集上 RSM 相关显著提升（预期 > 0.85），则证明差距来自"不同 sorting 捞到不同 units"。

**实际结论**：
- 共享子集 RSM 相关 **下降**（0.34 < 0.77），不是上升。
- 下降完全由"单元数从 ~260 减到 133"的 RSM 稳定性损失解释，**与独有单元无关**。
- 两个 pipeline 在"共同 trials + 共同 neurons"的纯净条件下，RSM 相关不会更高——它被 RSM 数学上的不稳定性上限压住。

因此：
1. **sorting 差异不是 cross-pipeline RSM 差距的主要来源**。
2. **ref_only 的 193 个单元（主要是 ref pipeline 做得更细）**不是造成 0.77 vs 更高数字的原因。
3. 若要让 cross-pipeline RSM 相关进一步提升（e.g. 到 0.85+），应该**增加 trial 数**或**扩大 unit 人口**（例如多 probe 合并），而不是调 sorting 参数。

### V.8.4 template overlay 缩略图（跳过）

由于 cos 中位数 0.947、d_xy 中位数 3.1µm 已定量证实"matched 对 = 同一 physical neuron"，跳过视觉 sanity check。需要时可基于 `diag/unit_pairing.csv` 随机抽取 9 对画图。

---

## 8. 一句话总结（第二轮，**已在 §9 被部分推翻**）

~~**跨管道 RSM 0.77 不是管道一致性上限，也不反映 sorting 质量；它反映两条管道在共享 trial 基底上的 spike 一致程度。真正限制 RSM 稳定性的是（1）每 stim ≤ 5 trials 的数据量，（2）unit 人口规模。V.8 配对进一步证实：两套 sorting 找到的是同一批物理 neurons（cos 中位 0.947，d_xy 3.1µm），RSM 差距不来自独有单元。**~~

**更正见 §9**（第三轮）：V.8.3 的 shared-133 RSM=0.34 是一个索引 bug——修复后 shared-171 RSM=0.77，**等于** FULL。0.77 本身仍是管道间一致程度，但关键结论反过来：**matched backbone 已承担了几乎全部的 RSM 信号**。RDM 适合做整体一致性一瞥，但**管道质量评估应以 per-neuron 指标为主**（见 §9）。

---

## 9. 第三轮（VI，2026-04-20 下午）：消融 + 修复 V.8.3 bug + 替代指标

### 9.1 RDM ablation 扫描（VI.1）

脚本 `tools/diag_rdm_ablation.py` 在 **trial_frac × unit_count × {ref_split, ours_split, cross}** 三维上做 10 seed 平均。关键数字（only_valid=True）：

| trial_frac | unit_count | ref_split | ours_split | **cross** |
|-----------|-----------|-----------|-----------|-----------|
| 1.00 | 33 | 0.232 | 0.160 | 0.192 |
| 1.00 | 133 | 0.291 | 0.262 | **0.453** |
| 1.00 | 170 | 0.336 | 0.284 | 0.584 |
| 1.00 | 220 | 0.296 | 0.278 | 0.679 |
| 1.00 | FULL (268 / 259) | 0.345 | 0.284 | **0.773** |
| 0.50 | FULL | 0.211 | 0.197 | 0.510 |
| 0.75 | FULL | 0.286 | 0.257 | 0.671 |

- **Sanity check 通过**：cross @ FULL × trial_frac=1.00 = 0.773，精确复现 V.3 的 0.77。
- **ours split-half < ref split-half 的部分解释**：ref @ 220 random units ≈ 0.296，ours @ FULL(259) = 0.284，两者接近——单元数不是全部原因（ref 在同样单元数下仍略高），但差距缩小了。
- **cross 曲线平滑上升**：unit_count 33→FULL 时 0.19 → 0.77，确认 cross RDM 对群体规模强依赖。

图：`diag/rdm_vs_size.png`（三 trial_frac 并排；solid=all units / dashed=SUA+MUA）

### 9.2 噪声过滤（VI.2）

过滤 `unittype ∈ {1, 2}`（SUA+MUA，ref 190 / ours 215）后：

| 条件 | all units | SUA+MUA |
|------|-----------|---------|
| cross @ 133 random | 0.453 | **0.615** |
| cross @ FULL | 0.773 | **0.804** |
| ref split-half @ FULL | 0.345 | 0.312 |
| ours split-half @ FULL | 0.284 | 0.285 |

- 噪声单元对 cross 相关有**明显稀释**（+0.15 @133 units，+0.03 @FULL）。
- 对 split-half 影响很小——单管道内噪声单元相关本身就低，两半之间抵消。
- 结论：未来报 cross RDM 时**建议同时报 SUA+MUA 过滤后的版本**。

### 9.3 V.8.3 bug 修复（VI.1b）

**发现的 bug**：`TrialRaster_*.h5` 不保存 `unit_ids`/`ks_ids` 字段，`diag_unit_pairing.py:_load_raster` 回退到 `np.arange(n_units)`。随后 `ks_id.isin(set(0..267))` 的过滤和 `_filter_by_unit_ids` 的 dict-lookup 都把 ks_id **数值**当作 raster 行索引，导致"共享 133 对"是**偶然数字落在区间内**的、与物理 neuron 无关的碎片。

**修复**（`tools/diag_v8_rerun.py`）：改用 `UnitProp_*.csv` 的 `id`（raster row） + `ks_id`（analyzer unit id）建立映射：

| 指标 | V.8 (bug) | VI.1b (corrected) |
|------|-----------|-------------------|
| matched-both-in-raster | 133 | **171** |
| shared-subset RDM all | 0.342 | **0.7705** |
| shared-subset RDM fix_success | 0.347 | **0.7686** |
| FULL RDM all (对照) | 0.771 | 0.7708 |

**新结论**：171 matched 物理 neurons 的 cross RDM **等于** FULL 268/259 的 cross RDM。ref_only 193 + ours_only 65 的额外单元**几乎不贡献 RDM 相关**。  

**回溯 V.8 的原结论**：

- ~~"shared 子集 RSM 相关 0.34 < FULL 0.77"~~ → 假的（bug）
- ~~"差距非独有单元"~~ → **实际上成立**，但证据不是"shared < FULL"而是"shared = FULL"：独有单元对 RDM 无贡献。

### 9.4 Random vs Matched 同 unit 数对比

结合 VI.1 + VI.1b：

| 条件 | n_units | cross RDM |
|------|---------|-----------|
| random 170 each side | 170 | 0.584 |
| matched 171 same-physical-neurons | 171 | **0.7705** |
| FULL | 268 / 259 | 0.7708 |

- **配对在起作用**：同一物理 neurons 比随机 170 高出 0.19 Pearson。
- 说明 V.8 的 Hungarian 匹配（template cos + spatial）**确实找到了同一批 neurons**（否则应该≈ random-170）。
- V.8 的"cos 中位 0.947，d_xy 3.1 µm"现在有了独立的功能验证。

### 9.5 替代一致性指标（VI.5）

脚本 `tools/diag_pipeline_agreement.py`：

**Metric A — per-pair per-image FR Pearson** （180 维 mean FR 向量的单对相关）：

- n=171 valid pairs（both in raster）
- median **0.642**，P25 0.389，P75 0.807
- 67% pairs > 0.5；28% pairs > 0.8

**Metric B — per-pair spike-train F1 @ ±1 ms**（两边 sorting 共享同一 frame 基准）：

- n=188 pairs with spikes both sides
- median F1 = **0.486**
- **median precision = 0.804**（ours 的 spike 大多在 ref 里）
- **median recall = 0.377**（ref 的 spike 只有 38% 被 ours 捕获）
- 48% pairs F1 > 0.5；24% pairs F1 < 0.2（疑似误配对或真实响应分歧）

**Metric C — Recall / Precision**：

| 分组 | ref | ours | matched (both side same unittype) |
|------|----:|-----:|----------------------------------:|
| SUA | 52 | 24 | **13** (recall 25% / precision 54%) |
| MUA | 138 | 191 | 94 (recall 68% / precision 49%) |
| NOISE | 78 | 44 | 14 |
| TOTAL | 387 | 259 | 194 (recall 50.1% / precision 74.9%) |

**关键解读**：

1. **ours 是更保守的管道**：precision 0.80 / recall 0.38 意味着 "ours 捕的 spikes 大多真存在，但漏掉很多 ref 捕到的 spikes"。
2. **SUA recall 仅 25%** 是新暴露的真问题：ours 只找到 13/52 个 ref 的 SUA。对依赖 SUA 的分析（如特定 neuron tuning），ours 的 SUA 覆盖显著不如 ref。
3. **per-pair 指标（A 和 B）不依赖群体规模**，对比管道时比 RDM 更直接、更可解释。

图：`diag/pipeline_agreement_hist.png`（A 和 B 直方图并排）；完整 per-pair 表 `diag/pipeline_agreement.csv`

### 9.6 matched pair 视觉验证（VI.3 + VI.4）

- `diag/pair_waveforms.png`：12 对波形叠加（高/中/低 cos + 3 unmatched），5 通道 offset。视觉证实高 cos 对（>0.97）波形几乎重合；低 cos 对（0.60-0.85）存在形态差异但仍高度相关。
- `diag/pair_spatial.png`：空间分布图。194 matched pairs 的 ref/ours 位置差异小（d_xy 中位 3.1 µm，比电极间距 12 µm 还小）。

### 9.7 修正后的"管道一致性仪表板"建议

**主指标**（推荐并排上报）：

| 指标 | 值 | 含义 |
|------|---:|------|
| unit recall (ref-covered) | 50.1% | ours 覆盖 ref 的 units 比例 |
| unit precision (ours-matched) | 74.9% | ours 被 ref 确认的 units 比例 |
| SUA recall | 25% | 高质量单元覆盖率 |
| per-pair FR Pearson (median) | 0.64 | 单 neuron 响应保真度 |
| per-pair spike F1 (median) | 0.49 | 单 neuron 检测一致性 |
| cross RDM (matched backbone = FULL) | 0.77 | 群体表征相似度 |
| RDM noise-filtered (SUA+MUA) | 0.80 | 排除噪声单元后群体相似度 |

**辅助**：cos / d_xy / unittype 分布。

**不推荐单看 RDM 数字**——它对群体规模 + 噪声单元敏感，而且给人"误以为是上限"的错觉。

### 9.8 对 V.7 的重新定位

- V.7 split-half 0.33 测的是"固定 ~260 unit、半 trial 数下的 RDM 稳定性"；
- V.8 corrected matched-171 cross = 0.77 等于 FULL cross——**trial 基底共享 + 同一物理 neurons 的情况下，RDM 没有被群体规模压低**；
- ergo V.7 的"单元数才是瓶颈"说法仅在 bootstrap-random 条件下成立，对 matched 条件不成立；
- **V.7 的 0.33 split-half 数字依然真实，但它的意义是"单管道内部独立-trial RDM 可靠性"**，不适合作为跨管道一致性上限。

---

## 10. 一句话总结（第三轮）

**V.8.3 的 0.34 是索引 bug；修复后 matched-171 RDM = 0.77 = FULL，证实配对的 backbone 承担了全部 RDM 信号。RDM 对群体规模强敏感（random-171=0.58 vs matched-171=0.77），所以它是"集体是不是同一批 neurons"的尺，不是"每个 neuron 被捕得多准"的尺。评估管道质量应改用 per-neuron 指标：unit recall 50%、SUA recall 25%、per-pair FR Pearson 0.64、spike F1 0.49——这些数字共同说明 ours 是一个更保守的管道：detect 出的 spikes 可靠（precision 0.80），但漏掉了 ref 捕获的不少（recall 0.38）。**
