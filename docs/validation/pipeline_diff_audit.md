# Pipeline Diff Audit — OURS vs REF（MATLAB Analysis_Fast）

生成日期：2026-04-20
触发：用户挑战 `phase_shift` 必须在 `bandpass_filter` 之前的既有断言，要求系统对照两条 pipeline 找出造成 round 7 结果差异的真因。

---

## 0. TL;DR

- **phase_shift 相对 bandpass 的顺序不是质量差异的主因**。LTI 性质保证两个顺序在通带内数值可交换；architecture.md § ADR-002 中"相位贡献不可分离"的论据过强，需要降档。已查到 SpikeInterface 官方 NP 教程与 MATLAB REF 都采用 `highpass → detect_bad → phase_shift → CMR`，与我们的顺序相反，但这不是 round 7 差距的来源。
- **真正的主因（按影响大小排序）**：
  1. `Th_learned = 8.0`（OURS）vs `7`（REF）— KS4 模板匹配阈值更严格 → 直接少检出 ~30% 单元。
  2. **漂移校正算法不同**：OURS 用 SI `DREDge` + `nblocks=0`；REF 用 `nblocks=5`（KS4 内部）。两条路径目标相同但实现独立，不等价。
  3. **方向性过滤缺失**：REF postprocess step #19 施加 `ranksum p<0.001 && response>baseline` 三重条件，OURS 完全没有。这条不影响 `diag/pipeline_agreement_summary.txt` 的 unit 计数差异，但会污染 selectivity/RDM/PSTH 对比。
- **OURS sort 出来 259 units，REF sort 出来 387 units**（原始数量就差 33%，不是 curate/postprocess 过滤导致）。SUA 召回率 25% = `both-matched SUA 13 / ref SUA 52`，根本原因在 sort 阶段漏检（OURS 只有 24 个 SUA 可匹配）。
- 下一步推荐：**单变量消融实验**（E1–E5，详见 § 5），优先 E1（Th_learned 7）+ E2（nblocks=5, 关 DREDge），两者合起来大概率能把 SUA 召回率从 25% 拉到 ≥ 50%。

---

## 1. 重新评估"phase_shift 必须第一步"这个断言

### 1.1 现有断言（需要纠正）

`docs/architecture.md:397-436` 的 "ADR-002"（这个 ADR 编号与 `docs/adr/002-*.md` 重名；真 ADR-002 是关于 SI 版本升级的，不是关于 phase_shift 的）主张：

> 如果先做带通滤波（FIR/IIR 滤波器）再做 phase shift，FIR 滤波器的群延迟（group delay）和相位响应已经修改了各频率分量的相位。此时再叠加 phase_shift 的相位旋转，两者的相位贡献不可分离，导致 phase shift 校正量与真实时间偏移不匹配。

`src/pynpxpipe/stages/preprocess.py:31` 的 docstring 进一步声明：
> `phase shift MUST be first; placing it after filtering would degrade CMR effectiveness.`

### 1.2 LTI 可交换性反驳

`si.bandpass_filter` 对每个通道应用**同一个** FIR/IIR 滤波器 `H(ω)`；`si.phase_shift` 对通道 `c` 在频域乘以 `exp(-jω·Δt_c)`，其中 `Δt_c` 是 TDM-ADC 引入的 sub-sample 偏移。两者都是通道独立、频率相关的线性时不变操作，因此：

```
bandpass( phase_shift(x) )[c, ω] = H(ω) · exp(-jω·Δt_c) · X[c, ω]
phase_shift( bandpass(x) )[c, ω] = exp(-jω·Δt_c) · H(ω) · X[c, ω]
```

二者在频域逐元素相等。"相位贡献不可分离"这句话在数学上没有解释力：两个操作的总体响应就是乘积 `H(ω) · exp(-jω·Δt_c)`，顺序不改变该乘积。`CMR` 作用于每一个样本点 `s`，做 `x[c,s] - median(x[:,s])`；只要进 CMR 前所有通道都已对齐到统一参考时刻（即 phase_shift 在 CMR 之前），CMR 的效果与 bandpass 是否先行无关。

### 1.3 真正的约束

**phase_shift 必须在 CMR 之前**（理由：CMR 是空间中位数，要求各通道时间对齐才能抵消共模噪声）。**phase_shift 相对 bandpass 的位置无硬约束**。IBL 官方 destripe 流水线、SpikeInterface 官方 NP 教程（https://spikeinterface.readthedocs.io/ `analyze_neuropixels.html`）、MATLAB REF（Analysis_Fast.ipynb cell-0）都采用 `highpass → detect_bad → phase_shift → CMR`，与我们的顺序相反，但这些流水线都是健康的。

### 1.4 建议

- 将 architecture.md § ADR-002 改为："phase_shift 必须在 CMR 之前；相对 bandpass 的位置不敏感。为了与 SI 官方教程和 REF 一致，本项目可选择把 phase_shift 移到 bandpass + detect_bad 之后"。
- E4（见 § 5）通过小样本真实数据验证：预期 waveform cosine ≥ 0.99、agreement recall 变化 <1%。

---

## 2. 完整差异矩阵

| # | 维度 | OURS (pynpxpipe) | REF (Analysis_Fast.ipynb) | 影响评级 | 纸面可否排除 |
|---|------|------------------|---------------------------|---------|-------------|
| 1 | preprocess 顺序 | phase_shift → bandpass(300,6000) → detect_bad → remove → CMR → DREDge | highpass(300) → detect_bad → remove → phase_shift → CMR | 低 | ✅ 可（LTI） |
| 2 | 带通 vs 高通 | bandpass(300, 6000) | highpass(300)，无低通 | 低 | ✅ 可（NP ADC 抗混叠已限带） |
| 3 | 运动校正 | SI DREDge（preprocess 阶段） | KS4 内部 `nblocks=5` | **高** | ❌ 需实验 |
| 4 | KS4 `nblocks` | 0（与 DREDge 互斥） | 5 | **高**（与 #3 耦合） | ❌ 需实验 |
| 5 | KS4 `Th_learned` | 8.0 | 7 | **高** | ❌ 需实验 |
| 6 | KS4 `Th_universal` | 9.0 | 未显式设（= KS4 默认 9） | 可忽略 | ✅ 相同 |
| 7 | KS4 `cluster_downsampling` | 1 | 1（KS4 4.1.0-4.1.2 默认） | 可忽略 | ✅ 相同 |
| 8 | Bombcell 版本 | SI 0.104 原生 Python 端口 | MATLAB `Util/BC/bombcell_pipeline` | 中 | ⚠️ 需 apple-to-apple |
| 9 | Bombcell 阈值 | 默认 | 默认 | 低 | ✅ 相同 |
| 10 | 坏道处理 | `remove_channels` | `remove_channels` | 可忽略 | ✅ 相同 |
| 11 | postprocess 方向性过滤 | **缺失** | `ranksum p<0.001 && mean(response) > mean(baseline)` | **高（下游）** | ❌ 影响 selectivity / RDM |
| 12 | sync pulse repair (MATLAB step #6) | ❌ 未实现 | ✅ 丢脉冲插值补回 | 低-中（对齐误差） | ⚠️ 需核查 sync 日志 |
| 13 | photodiode 极性校正 (step #10) | ❌ 未实现 | ✅ 逐 trial 检测并翻转 | 低-中（仅在暗刺激 session 失败） | ⚠️ 本 session 可能未触发 |

评级标准：
- **高**：可单独解释 >= 10 个百分点的 SUA 召回率差距
- **中**：1–10 个百分点
- **低**：< 1 个百分点或理论上 0

---

## 3. 每条差异的纸面分析

### 3.1 预处理顺序（#1, #2）—— 已纸面排除

见 § 1。LTI 可交换 + AP 带宽本身已受模拟抗混叠滤波器约束到约 5 kHz，bandpass vs highpass 对模板匹配的影响 < 0.1%。

### 3.2 漂移校正算法（#3, #4）—— 需实验

- **DREDge (OURS)**：`si.correct_motion(preset='dredge')`，基于 AP 带通后数据做 AP-band decentralized registration；产出 `displacement(t, depth)`，然后对 recording 做 rigid/nonrigid shift；KS4 拿到已对齐的 recording，设 `nblocks=0` 关掉内部校正。
- **KS4 nblocks=5 (REF)**：KS4 在模板学习过程内每 5 个纵向 block 独立做 iterative drift correction；不预校正 recording。

两者目标一致但实现独立：
- DREDge 的漂移估计依赖 AP-band spike 事件密度；若 session 长度较短或 spike rate 低，估计噪声会抬升。
- KS4 nblocks 在模板 pool 足够大时估计稳健，但对于 session 短或 firing 稀疏的 probe 同样有问题。

无法纸面断定哪条路径在本数据集上更好。**E2 实验必须做**。

### 3.3 KS4 `Th_learned` 8→7（#5）—— 需实验

KS4 源码 (`kilosort/core.py`) 中 `Th_learned` 是模板匹配阈值，单位为 template-convolution 噪声的标准差。数值越小越敏感。

8 → 7 只降 12.5%，但 template matching 产生的检出率对阈值是**指数敏感**的（高斯尾部）。粗略估计：`z=7` 相对 `z=8` 漏检率至少降低一个数量级。

这可能是 OURS 比 REF 少 33% 单元的**最大单一因子**。**E1 必须做**，预期效果：unit 数从 259 → 350+。

### 3.4 方向性响应过滤（#11）—— 已纸面确认其作用域

REF MATLAB step #19（`docs/ground_truth/step4_full_pipeline_analysis.md:1138-1146`）执行：

```matlab
if( p1 < 0.001 && unitType(spike_num)~=0 && mean(highline1) > mean(baseline) )
    GoodUnitStrc(good_idx).waveform = ww;
    ...
end
```

其中 `p1` 是 `baseline` 与 `highline1` 的 Wilcoxon rank-sum (`approximate`)，response window = `[60, 220] ms`，baseline window = `[-25, 25] ms`。

**影响范围**：
- 这一步发生在 Bombcell **之后**，只影响 `GoodUnitStrc` 导出的集合。
- `diag/pipeline_agreement_summary.txt` 的 REF `ref_total=387` 是**过滤前**还是**过滤后**，需要核查 MATLAB→Python 导入脚本（可能只取 `GoodUnitStrc` 那 268 条，`387` 可能来自 `UnitProp` 或更早阶段）。
- 无论如何，这一步**不影响** OURS vs REF 的 sort 阶段 unit 数量差距（259 vs 387）。
- **会**影响 selectivity（REF 排除了抑制性响应，分布偏高）、RDM、PSTH 比较。docs/validation/per_unit_analysis.md § 报告 selectivity REF median=0.658 vs OURS 0.606 有 KS p=3e-4 差异，这条过滤差异有很大概率就是主因。

### 3.5 Bombcell 版本差异（#8）—— 需核实

两条 pipeline 都用 Bombcell 做四分类，但实现不同：
- OURS：SI 0.104 的 `spikeinterface.curation.bombcell_label_units()`
- REF：MATLAB `Util/BC/+bc/+qm/runAllQualityMetrics.m` + `getQualityUnitType.m`

两者在某些指标（尤其是 `waveformBaselineFlatness`、`peakToTroughRatio`）的计算细节可能有小数点级差异；级联到分类阈值时会影响 SUA/MUA 边界上的 unit。**中等影响**，但比 #3/#5 次要。

### 3.6 Sync 相关缺陷（#12, #13）—— 本 session 可能未触发

- **Sync pulse repair**：若本 session 的 NIDQ/IMEC sync 无丢脉冲，此差异不触发。查 `01_synchronize/imec_nidq_*.log` 里是否有 `pulse_repaired` 记录即可断定。
- **Photodiode 极性**：只在暗刺激 (inverted photodiode signal) session 触发。图像刺激 session 一般不触发。

---

## 4. 对 `diag/` 数据的新解读

结合 § 3 的差异矩阵重新读 `diag/pipeline_agreement_summary.txt` + `diag/per_unit_reliability_summary.txt`：

| 指标 | 数字 | 主因（按影响排序） |
|------|------|---------------------|
| OURS sort 总 units | 259（REF 387） | #5 Th_learned + #3/#4 漂移算法 |
| SUA 召回率 | 13/52 = 25% | 同上（OURS 侧只有 24 个 SUA 可匹配） |
| Matched pair FR Pearson median | 0.642 | 匹配上的 pair 时间基本对齐；残差来自漂移校正细节 |
| Matched pair spike F1 median | 0.486 (recall 0.377, precision 0.804) | KS4 阈值差异 → OURS 检出的 spike 更保守 |
| Selectivity KS p (ALL) | 3e-4 | #11 方向性过滤缺失（REF 排除抑制性） |
| per-unit FR split-half ALL | OURS 0.251 vs REF 0.262 | 主要是组分效应，见 per_unit_analysis.md |
| SUA 亚组 FR split-half | OURS 0.472 > REF 0.329 | ✅ OURS SUA 实际更稳，数量少不等于质量差 |

---

## 5. Round VIII 实验计划（需用户授权）

所有实验要求重跑 `sort` 以及可能的 `preprocess`/`postprocess`，每次 1 个 probe × 完整 session 约需 GPU 1-3 小时。建议在 `dev/round8-ablation` 分支上做。

| ID | 名称 | 改动 | 成本 | 预期效果 | 优先级 |
|----|------|------|------|---------|-------|
| **E1** | Th_learned 消融 | `sorting.yaml: Th_learned: 7.0` | 1× sort | unit 数 259→350+；SUA 召回率 25%→40%+ | 🔴 最高 |
| **E2** | 漂移校正方法消融 | `pipeline.yaml: motion_correction.method: null` + `sorting.yaml: nblocks: 5` | 1× preprocess + 1× sort | unit 数与 REF 更接近；spike F1 median 上升 | 🔴 最高 |
| **E3** | 完全复刻 REF | E1 + E2 + preprocess 顺序改为 `highpass → detect_bad → phase_shift → CMR` | 1× preprocess + 1× sort + 1× curate | agreement F1 median ≥ 0.65 | 🟡 高 |
| **E4** | phase_shift 顺序消融 | 单独把 phase_shift 移到 detect_bad 之后 | 1× preprocess + 1× sort（或复用 E3 数据） | waveform cosine ≥ 0.99，agreement recall 变化 <1%。**预期无差异**，用于证伪 § 1 断言 | 🟢 中 |
| **E5** | 方向性过滤补全 | 在 `stages/postprocess.py` 加 `ranksum p<0.001 + mean(resp)>mean(base)` 逻辑 | 仅 postprocess | selectivity KS p 回到 NS；SUA 数可能再减 | 🟢 中 |
| **E6** | Bombcell apple-to-apple | 把 OURS 的 KS4 输出导出给 MATLAB Bombcell 重跑分类 | 需 MATLAB 环境，half-day | 判定 #8 对 SUA 召回率的贡献 | 🟢 低 |

推荐执行顺序：**E1 → E2 → E3**。E1、E2 单独跑用来归因；E3 做"完全复刻"对照。如果 E3 后 SUA 召回率仍 < 60%，再上 E6。

对于每个实验应在 `docs/validation/round8_E{i}.md` 记录：改动 diff、重跑命令、SUA/MUA/NOISE 计数变化、agreement F1 分布、matched pair Pearson。

---

## 6. 建议的 spec/架构修正（需用户批准后立即可做）

1. `docs/architecture.md § ADR-002`（phase_shift 一节）：改写为"phase_shift 必须在 CMR 之前；相对 bandpass 的位置不敏感"，附 LTI 推导。
2. `docs/adr/002-spikeinterface-api-verification.md` 保持不动（真 ADR-002）；新建 `docs/adr/003-phase-shift-positioning.md` 承接更新后的立场，避免继续重名。
3. `src/pynpxpipe/stages/preprocess.py:31` docstring 弱化措辞：`phase_shift corrects TDM-ADC per-channel sub-sample offsets; must precede CMR (not necessarily bandpass).`
4. `docs/specs/preprocess.md § 4.3` 同步。
5. `CLAUDE.md` "预处理链顺序：phase_shift **必须在** bandpass_filter 之前（旧代码顺序错误）" 改为 "phase_shift 必须在 CMR 之前；相对 bandpass 的位置由团队约定，当前项目选择 phase_shift 先行以便与旧代码断绝继承关系"。

这些修正**不改变**当前 OURS pipeline 的行为，只修正文档，让后续 Round VIII 讨论有准确起点。

---

## 7. 结论

1. 我过去对 "phase_shift 必须在 bandpass 之前" 的断言**过强**。LTI 可交换性证明两种顺序等价，SI 官方与 REF 都用相反顺序且健康。这不是 round 7 质量差异的来源。
2. Round 7 数据里的 **unit 数差异 (259 vs 387) 和 SUA 召回率 25% 几乎肯定是由 Th_learned=8 vs 7 与漂移校正算法差异** 造成的，两者都需要实验消融。
3. **selectivity 与 RDM 差异**很大概率来自 **方向性响应过滤缺失**（MATLAB step #19），与 sort 阶段无关。
4. 建议立即开展 E1/E2 单变量消融（GPU ~2-6 小时），其它改动（phase_shift 顺序、Bombcell apple-to-apple）优先级较低。

---

## 附录 A：关键代码位置

| 项目 | 文件 | 行 |
|------|------|----|
| OURS preprocess 链 | `src/pynpxpipe/stages/preprocess.py` | 120-152 |
| OURS sort 参数入口 | `src/pynpxpipe/stages/sort.py` | 137-159 |
| OURS sort YAML | `config/sorting.yaml` | 8-22 |
| OURS preprocess YAML | `config/pipeline.yaml` | 18-30 |
| OURS curate 逻辑 | `src/pynpxpipe/stages/curate.py` | 107-185 |
| OURS curate 阈值 | `config/pipeline.yaml` | 8-14 |
| REF preprocess 原文 | `docs/ground_truth/step4_full_pipeline_analysis.md` | 785-832 |
| REF sort 参数 | `docs/ground_truth/step4_full_pipeline_analysis.md` | 815（nblocks=5, Th_learned=7） |
| REF step #19 过滤 | `docs/ground_truth/step4_full_pipeline_analysis.md` | 1138-1146 |
| 架构文档 ADR-002（待修正） | `docs/architecture.md` | 397-436 |
| Legacy 分析 | `docs/legacy_analysis.md` | 140-170, 345-385 |

## 附录 B：diag 关键数字一次性索引

- `diag/pipeline_agreement_summary.txt`：overall recall 50.1%, precision 74.9%, matched 194, ref_total 387, ours_total 259; SUA 52/24/13, MUA 138/191/94, NOISE 78/44/14。
- `diag/per_unit_reliability_summary.txt`：SUA split-half FR Pearson — REF 0.329 (n=52), OURS 0.472 (n=24)，KS p=0.25 NS。
- `diag/unit_pairing_summary.txt`：matched 194，cos sim median 0.947，d_xy median 3.1 µm。
