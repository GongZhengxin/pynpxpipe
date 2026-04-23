# 第七轮验证设计（2026-04-20）

**上下文**：第六轮 VI 完成后，用户抽查 `diag/unit_pairing.csv` 与 `UnitProp*.csv` 的 `unitpos`，发现 `d_xy` 对不上；同时对 `pair_waveforms.png` 的通道选取、`pair_spatial.png` 的可读性、以及 ours 相对 ref 在各种稳定性指标上均偏低的现象提出深层检查要求。本轮不重跑任何 pipeline，只读 `05_curated/` / `06_postprocessed/*/analyzer` / `07_derivatives/` + 参考 `processed_good/`。

---

## 任务清单

| # | 类型 | 产物 | 估时 |
|---|---|---|---|
| A | 澄清（无代码） | 本文档 §A（d_xy 源不一致的机理） | 0 |
| B | 改图 | `diag/pair_waveforms.png/svg`（v2） | 45 min |
| C1 | 改图 | `diag/pair_spatial.png/svg`（v2） | 20 min |
| C2 | 新图 | `diag/pair_spatial_unitprop.png/svg`（CSV 源对照） | 30 min |
| D | 新脚本 | `tools/diag_per_unit_reliability.py` | 1.5 h |
| E | 新脚本 | `tools/diag_psth_gallery.py` | 1 h |
| F | 报告 | `docs/validation/per_unit_analysis.md` | 45 min |

**总估时** ≈ 4.5 h，零管道重跑。

---

## A. d_xy 源不一致的机理（已验证）

| ks_id | REF analyzer.unit_locations | REF UnitProp.csv.unitpos | OURS analyzer | OURS UnitProp |
|---|---|---|---|---|
| 0 | (0, **-10.92**) | (0, **31.75**) | (0, 4.20) | (0, 4.20) ✓ |
| 1 | (0, **56.44**) | (0, **67.61**) | (0, 54.79) | (0, 54.79) ✓ |
| 2 | (0, **112.55**) | (0, **123.96**) | (0, 78.33) | (0, 78.33) ✓ |

- **OURS 侧**：`analyzer.unit_locations` ≡ `UnitProp.csv.unitpos`（pynpxpipe 的 NWB 写入链保持一致）。
- **REF 侧**：两者不等（10–40 µm 偏差）。REF 的 MATLAB pipeline 把 **Bombcell 的 `ksPeakChan_xy`**（峰值通道坐标）写入 UnitProp CSV，而 `processed_good/SI/analyzer` 里的 `unit_locations` 来自 SI 的 `monopolar_triangulation`。

**结论**：`diag/unit_pairing.csv` 的 `d_xy` 两边都来自 `analyzer.unit_locations`（同源同算法），是内部自洽的。但如果用 REF 的 `UnitProp.csv.unitpos` 去复算 d_xy，实际上是在做 "ref peakchan vs ours monopolar" 的混合比较，数值会系统性偏大。**这不是 bug，是 REF 管道 CSV 与 analyzer 的数据源分歧**。本轮文档化这一点（见 §F 报告 + `pair_spatial_unitprop.png` 作视觉佐证）。

---

## B. pair_waveforms.png v2

### 已识别的 bug

当前 `_plot_waveform_pair` 取 `channels = range(peak_ch-2, peak_ch+3)`，按 **channel index** 选邻近通道。但 Neuropixels 1.0 探针的 2 列交错几何（x ∈ {0, 103} µm）意味着：channel index ±1 在 X 方向跳列、Y 方向跳一个 pitch，**不是空间上的最近邻**。多 shank 探针（NPX 2.0 4-shank）问题更严重。

### 修复方案

1. 通道选取改为**空间欧氏距离**：
   ```python
   probe = analyzer.get_probe()
   contacts = probe.contact_positions  # (n_channels, 2) µm
   peak_ch = _peak_channel(template)
   dists = np.linalg.norm(contacts - contacts[peak_ch], axis=1)
   neighbor_chs = np.argsort(dists)[:5]  # 5 closest, includes peak
   ```

2. 选出的 5 通道**按 Y 深度排序**后绘制；X 位置用 `ax.annotate` 在每条 trace 右端标 `ch{idx} (x={x:.0f}, y={y:.0f})`。

3. 可视化改进：
   - 加大通道 offset（`sep = max(p2p_list) * 1.5`）
   - `axhline` 基线：`color="grey", lw=0.3, alpha=0.5`（当前 alpha=0.2 几乎看不见）
   - 每个面板左下角加 **scale bar**：1 ms（水平，黑色）× 100 µV（垂直，黑色），lw=1.0
   - 去掉误导性的 legend 专用空子图，直接在 `fig.legend(...)` 画在图外

4. 布局：继续 4×3 网格（高/中/低 matched + unmatched），Nature 格式。

### 验收

- 肉眼检查：5 条 trace 在**同一 shank 同一列**（或至多跨列但相邻），Y 方向递增，不会出现"中间隔着远通道"的情况。
- 复查：peak channel 的 p2p 必须是 5 条里最大的。

---

## C1. pair_spatial.png v2

### 现状问题

- 匹配线 `lw=0.3 alpha=0.6` 过淡
- 圆点 `size = 3 + 10*log1p(fr)` 最小 3pt、最大 13pt，分辨率不足
- 未配对单元的 alpha=0.35 太淡，和背景混淆

### 修复

- 匹配线：`color="#555555", lw=0.6, alpha=0.85, zorder=1`
- 匹配圆：min 12pt，max 40pt（`size = 12 + 28 * norm_log1p_fr`）
- 未配对：不再降 alpha，改用更冷的 facecolor（`#aaccee` for ref_only, `#ffcc99` for ours_only），同尺寸
- 保留 x-jitter，但提高到 `JITTER_UM = 8`

### 产物

- 覆盖 `diag/pair_spatial.png` + `.svg`（Nature 格式，单栏 89mm × 高度按 shank 长度）。

---

## C2. pair_spatial_unitprop.png（新）

**目的**：让 §A 的"REF CSV 用 peakchan，OURS CSV 用 monopolar"在视觉上显形。

**数据源**：直接读两边的 `UnitProp_*.csv`，用 `ast.literal_eval` 解析 `unitpos` 列。

**可视化**：与 C1 同布局（实心 ours / 空心 ref / 灰线连接），但位置来自 CSV，**不是** analyzer：
- REF 侧将呈现 X 只在 {0, 103} 的离散分布（Bombcell peakchan）
- OURS 侧呈现连续 monopolar 位置
- 匹配线从"OURS 连续位置"拉到"REF 离散 peakchan"，会比 C1 长得多，让算法差异一目了然

**配对来源**：仍用 `diag/unit_pairing.csv` 的 matched 列（基于 analyzer 的 Hungarian 匹配，不受 CSV 源影响）。

**产物**：`diag/pair_spatial_unitprop.png` + `.svg`。

---

## D. tools/diag_per_unit_reliability.py

### 目的

判断 ours 的 split-half RDM 可靠性 (0.27) < ref (0.33) 是否源自：
- (a) **单元级**：ours 每个 unit 的 trial-to-trial 响应更噪
- (b) **组分级**：ours 的 NOISE 单元更多
- (c) **配对级**：同一物理 neuron 两边 reliability 是否正相关（验证 matching 质量）

### 输入

- `processed_good/deriv/TrialRaster_{REF_STEM}.h5` + `TrialRecord_*.csv` + `UnitProp_*.csv`
- `processed_pynpxpipe/07_derivatives/TrialRaster_{OURS_STEM}.h5` + 同系列 CSV
- `diag/unit_pairing.csv`

### 每 unit 计算的指标

1. **splithalf_fr_pearson**：对该 unit 的 (n_trials, 180) per-trial per-image FR 矩阵
   - 按 `stim_index` 分组，每组 trials 奇偶分两半 → A / B
   - per-image mean FR vector（180 维）on A 和 B → Pearson
   - 5 seed 平均（随机打乱 trial 顺序后奇偶划分）
2. **splithalf_psth_pearson**：全 trial PSTH（10 ms bin, window [0, 300] ms）split-half 相关
3. **selectivity_index**：`(max_stim_FR − mean_FR) / (max_stim_FR + mean_FR)`（Lurie 风格），范围 0-1
4. **n_spikes_total**、**n_active_trials**（≥1 spike 的 trial 数）
5. **snr**：window [60, 220] ms 内 per-trial FR 的 mean / std（across trials）

### 输出

1. `diag/per_unit_reliability.csv`
   - columns: `pipeline, ks_id, unittype, unittype_string, n_spikes_total, n_active_trials, splithalf_fr_pearson, splithalf_psth_pearson, selectivity, snr`
2. `diag/per_unit_reliability_hist.png/svg`（Nature 格式）
   - 2 行 × 3 列：行 = `splithalf_fr_pearson` / `selectivity` / `snr`（或 `splithalf_psth_pearson`）
   - 列 = SUA / MUA / ALL
   - 每面板叠加 ref（蓝）vs ours（橙）直方图，加 KS 检验 p-value
3. `diag/matched_pair_reliability_scatter.png/svg`（Nature 格式）
   - 171 matched pair 的 (ref_splithalf_fr, ours_splithalf_fr) 散点
   - 对角线参考线 + Pearson r 标注
   - 点大小 = cos 相似度，颜色 = unittype
4. `diag/per_unit_reliability_summary.txt`
   - 各 pipeline 各 unittype 的 median/P25/P75 表格
   - 关键 KS 检验 p-value
   - matched-pair ρ

### 验收标准

- hist 图能看出 ours 与 ref 在 SUA 组的 splithalf 分布是否有显著偏移
- scatter 的 Pearson r 回答"matched pair 的 reliability 是否正相关"——若 r > 0.5，matching 有信；若接近 0，matching 找到的是同位置但响应已偏离的单元

---

## E. tools/diag_psth_gallery.py

### 目的

定性判断：matched pair 是否呈现相似的 tuning 形状；低-cos pair 的响应差异是否真实。

### 选 pair 方法

复用 `diag_pair_waveforms.py::_select_samples` 逻辑（3 高 / 3 中 / 3 低 matched + 3 unmatched），但 rng seed=2（与波形 gallery 不同单元，避免重复）。

### 每面板内容

- X：time（−100 到 +300 ms relative to stim onset，10 ms bin）
- Y：FR（Hz）
- **4 条曲线叠加**：
  - ref top-1 preferred stim：蓝实线
  - ref mean across all stims：蓝虚线
  - ours top-1 preferred stim：橙实线
  - ours mean across all stims：橙虚线
- 阴影带：window [60, 220] ms，alpha=0.08 灰
- Title：`ks_id ref=X ours=Y\ncos=.. dxy=..`
- unmatched 面板：只画可用一侧的 4 条（或 2 条）

**注**：preferred stim 可能两边不同——故意保留该差异，比较 "ref 的 top-1 在 ours 对应位置的响应形态" 与 "ours 自己的 top-1 响应"，帮用户感觉 tuning 一致度。

### 产物

- `diag/psth_gallery.png/svg`（600 dpi，Nature 格式，4×3 布局）

---

## F. docs/validation/per_unit_analysis.md

### 目录

1. **范围与数据源**（上面 §D/§E 的 repeat）
2. **d_xy 源澄清**（§A 内容 + `pair_spatial_unitprop.png` 引用）
3. **per-unit reliability 分布**（hist 图 + 数字）
4. **matched-pair reliability 配对**（scatter 图 + 解读）
5. **PSTH gallery 定性观察**（12 pair 逐项一句话）
6. **对 "ours 稳定性 < ref" 的定性归因**
   - (a) 单元级证据：对比 SUA 组 splithalf 分布偏移量
   - (b) 组分级证据：NOISE/MUA 比例 + 把它们去掉后的 RDM split-half 变化（引用 VI.2 已有数据，不重跑）
   - (c) 配对级证据：matched-pair splithalf 相关、matched-pair selectivity 差
7. **SUA recall 25% 的影响**：ref 独有的 SUA 比 matched SUA 是否 reliability 更高？（验证"ours 漏掉的是否就是最稳的单元"）
8. **结论 + 下一步**（不承诺 pipeline 改动）

---

## 不做（显式声明）

- 不重跑 sorting / curate / postprocess / export
- 不改 `src/` 的任何代码（本轮只产出 `tools/diag_*.py` + `diag/*` + `docs/validation/*.md`）
- 不对 `TrialRaster_*.h5` 加 `unit_ids` 字段（VI 末尾提到，留给下次独立 session）
- PSTH 不做 trial-to-trial 对齐/bootstrap CI（10 ms bin + 平均足以定性判断）
- 不重画 `rdm_vs_size.png` / `pipeline_agreement_hist.png`（VI 已定稿）
- 不计算 Kendall τ 或 information theoretic selectivity（当前 Lurie 指数够用）

---

## 执行顺序

```
A（已完成，本文档 §A）
↓
B（waveform 修复，空间邻居）→ 验证 5 通道合理
↓
C1 + C2 (spatial 两图可并行)
↓
D（per-unit reliability 脚本，有分布和 scatter）
↓
E（PSTH gallery）
↓
F（报告，汇总所有产物）
```

B/C1/C2 与 D/E 互不依赖，可并行。报告 F 必须最后写。

---

## 验收（整体）

- 所有 `diag/` 新文件生成无 warning
- `per_unit_reliability.csv` 行数 = ref_units + ours_units = 387 + 259 = 646
- `matched_pair_reliability_scatter.png` 上 n=171（与 VI.1b 一致）
- 报告 §6 能给出 ours SUA 可靠性是否显著 < ref SUA 的 KS p-value
- 所有新脚本能用 `uv run python tools/diag_*.py` 独立跑通
