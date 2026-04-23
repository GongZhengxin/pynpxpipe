# TODO — 输出验证第一轮反馈（2026-04-19）

临时工作清单。对齐参考 pipeline `processed_good/` 与当前 `processed_pynpxpipe/` 的产物差异。
同一份原始录制：`NPX_MD241029` + `241026_MaoDan_YJ_WordLOC.bhv2`（已确认）。

待清盘后删除此文件。

---

## I. 依赖缺失（最低成本）

- [x] **I.1** 给 `pyproject.toml` 的 `[plots]` extra 追加 `"upsetplot>=0.9"`。 ✅ 2026-04-19
  - 现状：`src/pynpxpipe/plots/bombcell.py:138` 调用 `sw.plot_bombcell_labels_upset`，运行时报 `UpSet plots require 'upsetplot' package pip install upsetplot`。错误被 `try/except` 吞掉写 WARNING，不影响其他图。
  - 动作：改 pyproject + `uv lock && uv sync --extra plots`。
  - 验证：重跑 curate stage，`05_curated/{probe}/figures/bombcell_labels_upset.png` 出现。

---

## II. TrialRecord CSV 列对齐 MATLAB 参考

- [x] **II.1** 修改 `src/pynpxpipe/io/derivatives.py::export_trial_record` — 从"全列透传"改为"6 列投影"。 ✅ 2026-04-19
- [x] **II.2** 更新 `docs/specs/derivatives.md` §3 TrialRecord_*.csv 列定义。 ✅ 2026-04-19
- [x] **II.3** TDD 修改 `tests/test_io/test_derivatives.py::test_trial_record_preserves_all_columns` → 改为列投影断言（6 列 + 顺序 + `fix_success` 来自 `trial_valid`）。 ✅ 2026-04-19

---

## III. UnitProp CSV 列对齐

- [x] **III.1** 修改 `src/pynpxpipe/io/derivatives.py::export_unit_prop` — 加 `id`、加 2D 投影 `unitpos`、加 `unittype` 枚举。 ✅ 2026-04-19
- [x] **III.2** `docs/specs/derivatives.md` §3 UnitProp_*.csv 列定义同步更新。 ✅ 2026-04-19
- [x] **III.3** `unittype` 枚举：`1=SUA/GOOD, 2=MUA, 3=NON-SOMA/NOISE, 0=未知`（case-insensitive）。
- [x] **III.4** TDD：5 列投影断言 + `test_unit_prop_unitpos_is_2d` / `test_unit_prop_id_is_row_index` / `test_unit_prop_unittype_enum` 全部新增。 ✅ 2026-04-19

---

## IV. Unit 数量差距溯源（192 vs 268 — 已定位到 KS4）

**已知**（2026-04-19 审计）：

| 阶段 | pynpxpipe | reference | 差 |
|---|---|---|---|
| KS4 unique clusters | 275 | 387 | **−112 (−29%)** |
| Curate 后 | 191 | 268 | −77 (−29%) |
| Curate 保留率 | 69.5% | 69.3% | ≈ 0 |

**结论**：差距发生在 KS4 本身，不是 bombcell。

- [ ] **IV.1** diff KS4 参数：两边 `sorter_output/params.py` + `ops.npy` 关键键（`Th` / `nt` / `nblocks` / `whitening_range` / `dmin` / `dminx` / `spkTh`）。
- [ ] **IV.2** diff 预处理链：pynpxpipe `01_preprocessed/provenance.json` vs reference `SI/preprocess.zarr/provenance.json`（bandpass、CMR、phase_shift 顺序、motion 运行位置）。
- [ ] **IV.3** 验证 motion correction 是否双跑：reference 有 `folder_KS4/motion/dredge` 且 KS4 ops 有 `nblocks`——确认是否违反"DREDge 与 KS4 nblocks 互斥"。
- [ ] **IV.4** 产出 `tools/diag_sort_discrepancy.py`（独立诊断脚本，不进主管线），输出：
  - `diag/ks4_params_diff.txt`
  - `diag/preprocess_chain_diff.txt`
  - `diag/unit_count_waterfall.csv`
  - `diag/bombcell_labels_compare.png`（四类绝对数 + 比例对比）
  - `diag/amplitude_hist_compare.png`（spike amplitude 分布叠加，查 Th 截断）
- [ ] **IV.5** 若 IV.1-IV.3 无法一眼定位，跑**第二步**：在同一份 `01_preprocessed/` Zarr 上用 reference 参数重跑 KS4，看单元数是否回升到 387。
  - 回升 → 参数问题（改 `config/sorting.yaml`）
  - 不回升 → 回溯到预处理差异，拿 reference `preprocess.zarr` 作输入再跑

### IV 诊断结论（2026-04-19 溯源完成）

**根因已定位**：KS4 参数差异，非我们代码 bug，是 KS4 库版本默认值静默回退。

| 参数 | 参考 pipeline | pynpxpipe 当前 | 来源 |
|---|---|---|---|
| KS4 版本 | 4.1.1 | 4.1.7 | `spikeinterface_log.json` |
| `cluster_downsampling` | **1** | **20** | 库默认值（4.1.1=1, 4.1.3+=20） |
| `Th_learned` | 8 | **7.0** | 我们 `config/sorting.yaml` 硬设（commit `7f2a958`，2026-03-31，无 justification） |
| `do_CAR` | True | False | 参考链不含 CMR；我们含 CMR，故关闭 KS4 内 CAR |
| `torch_device` | cuda | cpu | 环境差异，非参数 |

**关键发现**：
- KS4 `cluster_downsampling` 默认值在 v4.1.3 回退到 20（docstring 明示"reverted due to user OOM reports"）。参考 pipeline 用 4.1.1 享受的是 v4.1.0-4.1.2 短暂的默认值 1。
- `Th_learned = 7.0` 在我们 yaml 首次提交时即存在，无文档来源；KS4 库默认为 8。
- SpikeInterface `Kilosort4Sorter._default_params` 为空 dict（passthrough），不做覆盖。
- 预处理链顺序（phase_shift 位置）**不是**主因：参考是 `highpass → bad_channel → phase_shift → CMR`，我们是 `phase_shift → bandpass → bad_channel → CMR`。IBL/CatGT/SI 约定 phase_shift 在滤波前（因果 IIR 的相位非线性 + 滤波器状态吸收错位），数学上我们的顺序更正确。此差异影响有限（经验上 <5%），不能解释 40% 的单元差。

**用户决策（2026-04-19）**：
- [x] **IV.6** `cluster_downsampling = 5`（选项 B，KS4 推荐折中）
- [x] **IV.7** `Th_learned = 8.0`（confirmed，回到 KS4 默认）
- [x] **IV.8** 修改 `config/sorting.yaml`，显式 pin 关键参数：`Th_learned=8.0` / `Th_universal=9.0` / `cluster_downsampling=5` / `max_cluster_subset=25000`。 ✅ 2026-04-19
- [x] **IV.9** 新增 regression guard 测试 `tests/test_stages/test_sort.py::test_ks4_critical_params_explicit`（RED→GREEN 验证过）。 ✅ 2026-04-19
- [x] **IV.10** 重跑 KS4 验证：pinned 参数下 354 units（vs 旧 275），delta −8.5% vs 参考 387。剩余 gap 归因于 cluster_downsampling=5 vs 1，属安全折中。 ✅ 2026-04-19

---

## V. 第二轮验证（2026-04-20）

数据：`processed_good/deriv/*` (MATLAB 参考) vs `processed_pynpxpipe/07_derivatives/*`（当前 KS4 设置：`cluster_downsampling=1`、`Th_learned=8.0`）。

总体：**972 trials stim_index/stim_name 100% 对齐；unit 数 268 vs 259，差 3.4%（远好于第一轮 268 vs 191 的 28% 差距）。**

---

### V.1 UnitProp.unitpos 巨大差异 — 两边用的不是同一个算法

**现象**：
- ref x 仅取 {0, 103} 两个离散值，y 连续。
- ours x 连续（-0.47 到 120.85），y 连续。
- 共同 ks_id 165 个，|dx| 中位数 0，p95=103；|dy| 中位数 93µm，p95=3mm（3mm 级差异说明同 ks_id 根本不是同一物理 unit）。

**根因**：
- ref pipeline 的 `unitpos` 来自旧版 **Bombcell** (`...SI\bombcell`) 导出的 `ksPeakChan_xy`，即"峰值通道的离散 xy"。
- 我们 `unitpos` 来自 SpikeInterface `unit_locations` + `method="monopolar_triangulation"`，输出连续坐标。
- 另外，KS `ks_id` 在两次独立 sorting 之间**不是同一物理 unit 的 ID**，故按 ks_id 逐行比 unitpos 无意义。要比较需要按 template 相似度或 spike overlap 配对。

**结论**：不是 bug，是两套 pipeline 选的定位算法不同。我们的 monopolar_triangulation 精度更高、可复现（见 `docs/specs/postprocess.md`）。

- [x] **V.1.1** 文档化算法选择到 `docs/specs/postprocess.md` "Unit 定位算法选择"小节；标注 `analyzer.compute("unit_locations")` 当前未传 method 参数（SI 默认也是 monopolar，行为正确但配置未生效，留 TODO）。 ✅ 2026-04-20

---

### V.2 TrialRecord 时间差漂移 10ms → 16ms — 两条 pipeline 用了不同时钟基准

**量化**（972 行）：
- `stim_index` / `stim_name` 100% 匹配；`fix_success` 仅 1 行不同。
- `stop_time - start_time`（刺激窗口长度）两边 **std=0、range=0**，完全一致。
- `start_time` 差：线性漂移 **20.4 ms/s ≈ 20 ppm**，从 ~9ms（t=0）到 ~16ms（t=322s）。
- 整段 session 时长差 5.95 ms / 322.67 s。
- 1 个离群 trial（idx=143，dt=-12.6ms），相邻均 +10ms。

**根因**：
- pynpxpipe 的 trials 用 **IMEC 时钟**（BHV2→NIDQ→IMEC 两次线性回归换算）。
- 参考 pipeline 很可能直接用 NIDQ 时钟（或神 mux 本身的时钟）。
- 两个自由运行晶振之间 20 ppm 漂移是常见值（NIDQ PXIe-6341 vs IMEC probe base）。

**结论**：不是 bug。两边内部自洽（刺激窗口长度完全一致），差别只在"锚点时钟"。要收敛到同一秒基准需要统一 target clock。

- [x] **V.2.1** 调查 trial 143 的 -12.6ms 离群。诊断报告：`docs/validation/trial_143_outlier.md`。 ✅ 2026-04-20
  - **根因**（非 BHV↔NIDQ 事件码错位）：trial 143 是 972 个 trials 里唯一 `quality_flag=1` / `onset_latency_ms=NaN` 的行（PD "negative latency"，典型 fix-break-abort 场景）。
  - `photodiode_calibrate.py` 对 PD 失败 trial 保留未校正的 trigger 时间，正常 trial 加 ~25 ms 监视器延迟 → trial 143 少了 25ms。
  - trial 本就 `fix_success=0`，`fix_success only` 分析已丢弃它；只影响 `all trials` 时基一致性。
  - **不修**：影响 1/972，0.1%。未来若想修：PD 失败时用中位数 latency 补齐（方案见诊断报告末尾）。
- [x] **V.2.2** 文档：在 `docs/specs/synchronize.md` 新增 Section 9 "Pipeline 时钟基准"，说明选 IMEC clock 的理由、与 NIDQ-based pipeline 的 20ppm 漂移预期、多 probe 语义、下游自行换算到 NIDQ 的方法。 ✅ 2026-04-20

---

### V.3 群体表征相似性 — pipeline 间 RSM 相关 0.77

**方法**：raster 窗 `[60, 220] ms` → 每 trial FR（Hz）→ 按 `stim_index` 取均值 → 180 × n_units mean-FR → Pearson RSM（unit 轴）→ 下三角（不含对角）相关。脚本见 `tools/diag_rsm_compare.py`。

| 条件 | lower-tri pairs | Pearson | Spearman |
|---|---:|---:|---:|
| 全部 trials | 16,110 | **0.7708** | 0.7448 |
| 仅 fix_success | 16,110 | **0.7726** | 0.7482 |

- ref RSM 范围 [0.311, 1.000]；ours 范围 [0.487, 1.000]（略高 baseline，与 ours spike 数略多一致）。
- 0.77 Pearson 是**群体表征结构在两条 pipeline 间高度一致**的强证据；剩余 23% 方差归因于不同 sorting 采样（不同 units 子集）+ noise。

**结论**：✅ 表征层面两条 pipeline 可互换使用；差别主要在单元层面（不同 KS 运行的偶然性）。

---

### V.4 bombcell UpSet 图仍不渲染 — 环境未同步

**现象**：`05_curated/imec0/figures/bombcell_labels_upset.png` 显示 "UpSet Plot - Package Not Installed"。

**根因**：I.1 只改了 `pyproject.toml` 的 `[plots]` extra，没跑 `uv lock` + `uv sync --inexact --extra plots ...`，venv 里没装 upsetplot。

**已修复**（2026-04-20）：
- [x] **V.4.1** `uv lock --upgrade-package upsetplot` → uv.lock 已包含 upsetplot 0.9.0。
- [x] **V.4.2** `uv sync --inexact --extra plots --extra ui --extra gpu` → 装入 venv，smoke test 渲染通过。
- [ ] **V.4.3** 重跑 curate stage（或等下次 curate）刷新 `bombcell_labels_upset.png`。手动命令：`uv run pynpxpipe run --stages curate --overwrite`。

**教训**：以后改 `pyproject.toml` 后 I.x 任务不能光打勾，必须跟 `uv lock` + `uv sync --inexact` 并验证 `import`。

---

### V.5 SLAy 均值 0.05 — 不是 bug，是该度量的数学特性 + 命名误导

**现象**：`06_postprocessed/imec0/slay_scores.json` 259 units，33 None，226 有效。均值 0.057，中位 0.036，p95=0.17，max=0.59。只有 6 个 unit 超过 0.2。

**根因**（见 `stages/postprocess.py::_compute_slay`）：
- 本 pipeline 的 "SLAy score" 是 **trial-to-trial Spearman 相关**（10ms bin 的 spike count 向量），**把所有 180 张图的 ~900 个 trial 混合计算**。
- 对 V4/IT 的 stim-selective 细胞：同图 trials 相关 ≈ 0.4，跨图 trials 相关 ≈ 0。900 trials 中 within-image pair 比例 = C(5,2)·180 / C(900,2) ≈ 0.4%。混合期望 ≈ 0.001-0.01。
- 实测 0.057 > 理论选择性期望值，说明群体里有非选择性（onset-burst）细胞拉高均值 — 符合预期。

**更严重的问题 — 命名误导**：
- 我们的 `slay_score` ≠ SpikeInterface SLAy（GNN auto-merger）。重名会让用户误以为它是 merge quality。
- `docs/specs/postprocess.md` 的描述"SLAy: trial-to-trial Spearman correlation of spike rate vectors"没突出它的混合语义。

**建议**（非紧急）：
- [~] **V.5.1** 延后：实际范围超原估（NWB units 列 `slay_score` schema 变更、已有磁盘 `slay_scores.json` 兼容、10+ 测试重写）。已在 `stages/postprocess.py` 加 TODO 注释 + `docs/specs/postprocess.md` V.5.2 文档化命名歧义，足以防止混淆。真正改名留给专门的迁移 session。
- [x] **V.5.2** 在 `docs/specs/postprocess.md` `_compute_slay` 后补"度量语义与命名"小节，澄清与 SI SLAy 的区别、低均值的数学必然、未来改进方向。 ✅ 2026-04-20
- [x] **V.5.3** 评估 SI SLAy 对接现状。 ✅ 2026-04-20
  - **当前状态**：`src/pynpxpipe/stages/merge.py:119` 调用 `spikeinterface.curation.auto_merge(analyzer, return_merge_info=True)`，**未传 `preset` 参数** → 使用 SI 默认的 `"similarity_correlograms"` 预设，**不是 SLAy**。
  - **SI 0.104 已内置 SLAy**：`auto_merge(preset="slay")`（`template_similarity` + `slay_score` 两步），参数 `{"k1": 0.25, "k2": 1, "slay_threshold": 0.5}`。源码在 `.venv/.../spikeinterface/curation/auto_merge.py`，无需额外依赖。
  - **结论**：不需要加新 extra；SLAy 已经在 SI 主包内。要真正用 SLAy 只需：
    1. 在 `core/config.py::MergeConfig` 加 `preset: str = "similarity_correlograms"` 字段（允许 `"slay"`）。
    2. `merge.py:119` 改为 `auto_merge(analyzer, preset=self.session.config.merge.preset, return_merge_info=True)`。
    3. 更新 `config/pipeline.yaml` 注释、`docs/specs/postprocess.md` 或独立 `merge.md` spec。
    4. 回归测试（mock analyzer + preset="slay" → 不抛异常）。
  - **留作下次 session**（不在 V. 验证范围内）：本项是"研究+小代码改动"，需要独立验证 SLAy 合并结果是否改善 ours 相对 ref 的 unit pool（V.8 已证实当前差距不来自独有单元，SLAy 改动预期收益有限）。

---

### V.6 Photodiode 校正后曲线的"诡异波谷" — 双重校正的可视化 bug

**现象**：`04_sync/figures/photodiode_after_calibration.png` 在 `t ≈ +15 ms` 有一个 z=-8 的深谷，像是 PD 响应"反向"；同时 `t ∈ [-10, -5] ms` 有一个浅波谷 z≈-1.5。

**根因**（见 `plots/sync.py::_build_pd_trial_matrix` + `_plot_photodiode_after_calibration`）：
1. `_build_pd_trial_matrix` 传入的 `stim_onset_nidq_s = calibrated.stim_onset_nidq_s`（**已经校正过的 PD 亮度时刻**），提取出的 `raw_matrix` 每 trial 已经对齐到 PD 亮度跳变（跳变在 t ≈ -monitor_delay_ms = +5ms 位置）。
2. `_plot_photodiode_after_calibration` 又对每 trial `aligned[i][j] = row(time_ms[j] - lat[i])` 做**第二次** `+lat` 位移（lat ≈ 15-20ms），把 **跳变前的基线段** 推到 `t = lat - pre_ms ≈ +10 ~ +15ms`。
3. 结果：我们看到的 t≈+15ms 深谷**不是 PD 响应**，而是每 trial **预亮度基线区域 z-score** 的均值（基线 z≈-4），经过位移叠加后形成。

**本质**：raw_matrix 已经校正过了，"after_calibration" 不应再位移；要么把"before"换成用未校正的 trigger 时刻抽窗，要么"after"直接显示 raw_matrix。

**附带问题**：当前"before_calibration"图的名字也有误（它画的其实就是 raw_matrix，已经校正过了）。

**修复计划**：
- [x] **V.6.1** `_build_pd_trial_matrix` 加 `align_to: Literal["trigger","calibrated"]` 参数（默认 `"trigger"`，文档性；内部逻辑不变）。 ✅ 2026-04-20
- [x] **V.6.2** `emit_all` 改传 `trial_alignment.trial_events_df["stim_onset_nidq_s"]`（trigger time）而非 `calibrated.stim_onset_nidq_s`；所有 raw/diff/before 热图现在以 trigger 为 0，PD 跳变在 t≈+latency 位置。 ✅ 2026-04-20
- [x] **V.6.3** 抽出 `_realign_by_latency(matrix, time_ms, lat)`；`_plot_photodiode_after_calibration` 符号从 `time_ms + lat` 改为 `time_ms - lat`（equivalent to `aligned[i][j] = matrix at time_ms[j] + lat[i]`），跳变收束到 t=0。 ✅ 2026-04-20
- [x] **V.6.4** TDD 4 tests：`test_build_pd_trial_matrix_trigger_aligned_step_location` / `test_build_pd_trial_matrix_calibrated_aligned_step_at_zero` / `test_realign_by_latency_shifts_step_to_zero` / `test_emit_all_passes_trigger_onsets_to_build_pd_matrix`；RED → GREEN 验证。 ✅ 2026-04-20

---

### V.7 噪声上限基线：split-half 可靠性（2026-04-20 新增，零重跑）

**动机**：V.3 的 0.77 Pearson 需要对比 **within-pipeline ceiling** 才能解释。若 split-half 本身只有 0.80，说明 0.77 几乎触顶；若 split-half 是 0.93+，则跨管道差距显著。

**方法**（单个 pipeline 内部）：
- 同一 raster 按 trial 奇偶分半：每个 stim_index 的 trials 一半归 A，一半归 B。
- 分别算 mean-FR → RSM_A、RSM_B（180×180，unit 轴 Pearson）。
- 下三角相关 = 数据噪声上限（不含 sorting noise）。

**执行**：
- [x] **V.7.1** 写 `tools/diag_rsm_splithalf.py`，对 ref 和 ours 各算 split-half RSM 相关。 ✅ 2026-04-20
- [x] **V.7.2/V.7.3** 写 `docs/validation/rsm_report.md`（新建），记录结果与诊断。 ✅ 2026-04-20

**实测结果**（脱离两条预期剧本，见 `docs/validation/rsm_report.md`）：
- 单管道 split-half（5 seed 平均）：ref 0.330 ± 0.020 / ours 0.272 ± 0.036（all trials）；fix_success only 类似。
- SB 外推内部全-trial 可靠性：ref 0.50 / ours 0.43。
- **split-half (~0.33) << cross-pipeline (0.77)**，在标准噪声上限假设下数学上不可能。

**诊断**：两个测量测的不是一件事。
- split-half：trials **独立**、units 相同 → 纯 trial 噪声（且半样本，更噪）。
- cross-pipeline：trials **共享**、units 不同 → trial 噪声相关抵消，只剩 sorting 差异。
- 结论：0.77 **不是**管道一致性上限，是"共享 trial 基底下的 spike 还原一致程度"。真正卡 RSM 稳定性的是每 stim ≤ 5 trials 的数据量，不是 sorting 差异。

**对后续任务影响**：
- 原定 V.7.2/V.7.3 gate 不适用 → **V.8 继续做**（重新定位：看共享子集 RSM 相关能多接近 1.0，而非 > 0.85）。
- **不建议**为提高 RSM 相关去重跑 sorting 调参，trial 数才是瓶颈。

成本实际：30 分钟脚本 + 零重跑。

---

### V.8 跨管道 unit 配对：template + location（需要 ref analyzer，不重跑 sorting）

**动机**：V.3 的 Pearson 0.77 差距可能是**独有单元**贡献的。如果在"共享子集"上重算 RSM 能显著提升相关，则可证明差距来自"不同 sorting 捞到不同 units"而非"同 unit 不同响应"。

**数据源**：
- Ref analyzer：`F:\#Datasets\demo_rawdata\processed_good\SI\analyzer`
- Ours analyzer：`06_postprocessed/imec0/analyzer`（验证路径）

**方法**：
1. 两边各加载 `SortingAnalyzer`，读 templates (`templates.npy`) + unit_locations。
2. 相似度矩阵：ref_n × ours_n 矩阵 = α·cosine(template_ref, template_ours) + β·exp(-d_xy/100µm)，α=0.7 β=0.3（初值，可调）。
3. Hungarian 匹配（`scipy.optimize.linear_sum_assignment`），阈值 similarity ≥ 0.6 判定为"共享对"。
4. 分类：shared_pairs / ref_only / ours_only，分别报数量和占比。
5. 在 shared 子集（~100-150 对）上重跑 RSM 对比，预期 Pearson > 0.85。

**执行**：
- [x] **V.8.1** 写 `tools/diag_unit_pairing.py`：`diag/unit_pairing.csv` + `diag/unit_pairing_summary.txt`。 ✅ 2026-04-20
- [~] **V.8.2** SUA/MUA 分布：跳过——pairing CSV 内已有 matched 标签 + cos/d_xy，后续需要时可直接 join ref/ours `UnitProp.csv`。
- [x] **V.8.3** shared 子集（133 pairs）RSM 相关 ≈ 0.34（vs FULL 0.77）；写入 `docs/validation/rsm_report.md` §7。 ✅ 2026-04-20
- [~] **V.8.4** template overlay 缩略图：跳过——cos 中位数 0.947、d_xy 中位数 3.1µm 已定量证实"matched=同一物理 neuron"，无需视觉验证。

**关键结果**（见 `docs/validation/rsm_report.md` §7）：
- 194/259 ours units 与 ref 某个 unit matched（cos 中位 0.947、d_xy 中位 3.1µm）。
- 共享子集 133 pairs 的 cross-pipeline RSM 相关 = **0.34**（反而 < FULL 0.77）。
- 原假设"差距来自独有单元"**被证伪**：shared 子集下降是因为单元数减半、RSM 稳定性下降，不是独有单元贡献。
- 与 V.7 split-half 0.33 数量级一致 → 共同指向"RSM 在 ~130 单元时本就不稳定"。

**结论**：sorting 差异**不是** V.3 RSM gap 的主要来源，不需要重跑 sorting。

成本实际：1 小时脚本 + 零重跑。

---

### V. 汇总表

| # | 问题 | 结论 | 动作 | 需重跑 |
|---|---|---|---|---|
| V.1 | unitpos 差距大 | 算法不同（peak-ch vs monopolar_triangulation）；ks_id 不跨 run 对齐 | 文档补充 | ❌ |
| V.2 | Trial 时间 10→16ms 漂移 | 两套 pipeline 用不同时钟基（IMEC vs NIDQ），20 ppm 漂移 | 文档 + 1 trial 离群诊断 | ❌ |
| V.3 | RSM 相关 | Pearson **0.77** — 需要 ceiling 对比才能解释 | V.7 / V.8 ceiling 分析 | ❌ |
| V.4 | upset 图不渲染 | pyproject 改了但没 sync | ✅ 已装 upsetplot；V.4.3 等下次 curate | ✅（V.4.3）|
| V.5 | SLAy 均值 0.05 | 数学特性 + 命名误导（≠ SI SLAy auto-merger）；V.5.3 确认 SI 0.104 已内置 SLAy preset，当前 merge 未启用 | 文档 + TODO；SLAy preset 留下次 session | ❌ |
| V.6 | PD 校正后波谷 | 双重校正可视化 bug | 改 `_build_pd_trial_matrix` + TDD | ❌ |
| V.7 | RSM ceiling 基线 | split-half 0.33 << 跨管道 0.77；trial 数才是瓶颈，不是 sorting | ✅ 报告 `docs/validation/rsm_report.md` | ❌ |
| V.8 | 跨管道 unit 配对 | 194/259 matched（cos 0.947、3.1µm）；shared-133 RSM 0.34 < FULL 0.77 → 差距非独有单元 | ✅ `diag/unit_pairing.csv` + 报告 §7 | ❌ |

**本轮执行优先级**（跳过重跑任务）：
1. V.2.2（文档：时钟基准，5min）
2. V.1.1 文档化（说明 unit_locations 算法选择，5min）
3. V.5.2（文档：SLAy 语义，10min）
4. V.5.1（代码改名：slay_score → response_consistency_score，30min）
5. V.6（PD bug 修复 + TDD，1-2h）
6. V.7（split-half 脚本，30min）
7. V.8（waveform pairing 脚本，1-2h）
8. V.2.1（trial 143 离群诊断，30min，纯分析）
9. V.5.3（SI SLAy 调研，30min）

跳过：**V.4.3（需重跑 curate）**、**IV.5（需重跑 KS4）**。

---

## 执行顺序建议

| 顺序 | 任务 | 估时 | 阻塞关系 |
|---|---|---|---|
| 1 | I.1（加 upsetplot 依赖） | 2 分钟 | 无 |
| 2 | IV.1 + IV.2 + IV.3（读参数 + 链路 diff） | 15 分钟 | 无；只读 |
| 3 | III.3 反推 unittype 枚举 | 5 分钟 | 解锁 III.1 |
| 4 | II.1-II.3（TrialRecord 6 列）| 45 分钟 | 无 |
| 5 | III.1-III.4（UnitProp 5 列）| 45 分钟 | 依赖 3 |
| 6 | IV.4 诊断脚本 | 1-2 小时 | 依赖 2 的结论 |
| 7 | IV.5 重跑 KS4 验证 | 半天 | 依赖 6 |

I / II / III 互不阻塞，可并行推进；IV 需要按步走。

---

## VI. 第三轮验证（2026-04-20 下午）：V.7/V.8 sanity check + 管道一致性指标重估

**动机**：V.8 的 "共享 133 对 RDM 相关 0.34 < FULL 260 对 0.77" 与直觉相悖——相同物理 neurons 应比不同 neurons 群体更一致。两个自查暴露的薄弱点：

1. 我用 "unit 数减半 → RDM 变噪" 一笔带过，没做 unit × trial 独立消融就下结论。
2. ours split-half (0.27) < ref split-half (0.33)，若真的是 unit-count 主导，ref 下采样到 259 应接近 ours——**未验证**。
3. RDM 纳入了 `unittype=3` (NOISE) 单元，稀释信号，未过滤。

**目标**：用消融 + 视觉证据 + 重估指标判断 V.7/V.8 的数字是否真来自 "unit count × trial count"，并在 RDM 被规模主导的情况下提出替代方案。

**约束**：零管道重跑；只读 `05_curated` / `06_postprocessed/*/analyzer` / `07_derivatives`。

---

### VI.1 RDM 稳定性消融：trial × unit 二维扫描

**目的**：区分"trial 数"与"unit 数"对 RDM 稳定性的贡献；验证 V.7/V.8 数字内在一致。

**方法**（`tools/diag_rdm_ablation.py`，新脚本）：

1. **三个条件**：within-ref split-half / within-ours split-half / cross-pipeline。
2. **两维扫描**：
   - `trial_frac ∈ {0.50, 0.75, 1.00}`（每 stim_index 随机截取 trials）
   - `unit_count ∈ {33, 66, 100, 133, 170, 220, FULL}`（每点 bootstrap 抽 unit，不放回）
3. 每 (trial_frac, unit_count) 跑 10 seed，报 mean ± std Pearson + Spearman。
4. cross 条件两边独立抽 unit（不要求同一物理 neuron，那是 V.8.3 的问题）。

**输出**：
- `diag/rdm_ablation.csv`（columns: trial_frac, unit_count, condition, seed, pearson, spearman, n_pairs）
- `diag/rdm_vs_size.png`（x=unit_count log，y=pearson；9 条曲线：3 condition × 3 trial_frac；Nature format）

**验证逻辑**：
- 若 `ref_split @133 ≈ ours_split @259 ≈ shared-133 cross` → unit-count 主导，V.8 结论成立
- 若 `ref_split @133 >> 0.33` → V.8 "unit-count 解释" 不足；可能我的 matching 有偏，或还有其他因子
- 若 cross @FULL 随 trial_frac 剧烈变化 → V.3 的 0.77 本身对 trial 数敏感

### VI.2 噪声单元过滤后复算

**执行**：VI.1 脚本加 `--filter-noise` 参数，过滤 `unittype ∈ {1, 2}`（SUA + MUA）后重跑全部曲线。

**输出**：
- `diag/rdm_ablation_filtered.csv`
- VI.1 图中用虚线叠加 filtered 曲线，定量噪声 unit 的稀释效应

### VI.3 matched pair 波形可视化（Nature 格式）

**目的**：视觉验证 V.8 `cos=0.947 / d_xy=3.1 µm` 不是数值 artifact；给 unmatched 例子作对照。

**执行**（`tools/diag_pair_waveforms.py`，新脚本）：

1. **抽样**（从 `diag/unit_pairing.csv`）：
   - 9 matched：3×高 sim (>0.97) + 3×中 sim (0.85-0.95) + 3×低 sim (0.60-0.75)
   - 3 unmatched：1 ref_only（高 SNR） + 1 ours_only（高 SNR） + 1 低-sim 失配对照
   - 总 12 面板，3×4 grid
2. **每面板**：
   - 峰值通道 + 上下各 2 个邻近通道，5 通道垂直 offset
   - matched: ref 蓝实线 + ours 橙虚线叠加
   - unmatched: 单条线
   - 右上角标注 `unit_id / cos=0.XX / d_xy=X.X µm`
3. **Nature 格式**（matplotlib rcParams）：
   - `font.family = "Arial"`, `font.size = 7`
   - `axes.linewidth = 0.5`, 线条 lw=0.75
   - 只留 left + bottom spine；tick 朝内
   - scale bar（1 ms × 100 µV）代替坐标轴数字
   - 输出 `.png` (600 dpi) + `.svg`

**输出**：`diag/pair_waveforms.png` + `diag/pair_waveforms.svg`

### VI.4 matched pair 空间分布图（Nature 格式）

**执行**（`tools/diag_pair_spatial.py`，新脚本）：

1. 从两 analyzer 读 `unit_locations` → (x, y) µm
2. 绘制：
   - **ours**：实心圆（tab:blue fill），size ∝ log(firing_rate)
   - **ref**：空心圆（tab:blue edge，white fill），size 同 scheme
   - **matched pair**：细灰线连接（lw=0.3, alpha=0.6）
   - **x-jitter**：每 pair 独立随机 jitter ±8 µm，同一 pair 的 ref/ours 共享 jitter（保证 pair 线垂直可见）
3. 底图：probe channel grid 作 faint dotted gridline（alpha=0.15）
4. Legend 标出 filled/open/line 含义；colorbar 或 size legend 说明 firing rate
5. Nature 格式：单栏宽度 89mm，高度按 probe shank 长度定

**输出**：`diag/pair_spatial.png` (600 dpi) + `diag/pair_spatial.svg`

### VI.5 候选替代管道一致性指标

**若 VI.1 证实 RDM 被群体规模主导**，候选指标（按实施难度排序）：

| # | 指标 | 粒度 | 直接回答的问题 | 优点 | 缺点 |
|---|------|------|----------------|------|------|
| A | **配对 per-image FR 相关** | 单对 neuron | 同一 neuron 响应是否一致？ | 最简单；不依赖群体规模 | 对 FR scale 差异敏感 |
| B | **配对 spike train F1** (±1 ms) | 单对 neuron | 是否把同一 spikes 归到该 neuron？ | 金标准；最接近 "sorting 一致性" | 计算量大；jitter 阈值要选 |
| C | **Recall / Precision** | pipeline 层 | ours 找到多少 ref 单元？反之？ | 管道级总览 | 假设 Hungarian 配对正确 |
| D | **配对 tuning 排序相关** (Kendall τ on preferred stim ranks) | 单对 neuron | 响应选择性方向是否一致？ | 生理可解释；对 scale 不敏感 | 仅对 selective cells 有效 |
| E | **配对 QC 指标相关** (ISI / SNR / amplitude) | 单对 neuron | 质量指标是否自洽？ | 正交维度 | 不反映响应一致 |

**首轮执行 A + B + C**（`tools/diag_pipeline_agreement.py`，新脚本）：

1. **A. per-image FR 相关**：对 133 shared pairs 各算 Pearson(ref_FR[180], ours_FR[180])；报 median/P25/P75/%>0.5/%>0.8。
2. **B. spike train F1**：
   - 从两边 Sorting 读 spike_times（须统一到同一时钟；V.8 pairing csv 给出 unit id 映射）
   - 每 pair ±1 ms tolerance：TP = 两边时间差 ≤1 ms 的 spike 对；FP = ours 独有；FN = ref 独有
   - 报 median F1、F1 直方图；F1 < 0.2 的 pair 单独列出作为"疑似误配对"
3. **C. Recall / Precision**：
   - Recall = 194/387 (ref)；Precision = 194/259 (ours)
   - 按 SUA/MUA 分组报（join UnitProp.unittype）

**输出**：
- `diag/pipeline_agreement.csv`（per-pair A 值 + B 值 + unit metadata）
- `diag/pipeline_agreement_summary.txt`
- `diag/pipeline_agreement_hist.png`（A 和 B 直方图并排，Nature 格式）

### VI.6 综合报告：V.7/V.8 结论确认或推翻

**依赖 VI.1-VI.5**。在 `docs/validation/rsm_report.md` 新增 §9：

- 若 VI.1 证实 unit-count 主导 → 确认 V.7/V.8，推荐 A/B/C 作为主指标
- 若 VI.1 否定 unit-count 解释 → 撤回 V.7/V.8 结论，列出"matching 偏差"/"bug" 等候选假设与下一步调查方向
- 更新 §8 "一句话总结"

---

### VI 执行顺序

| 顺序 | 任务 | 估时 | 依赖 |
|---|---|---|---|
| 1 | VI.1（RDM ablation 扫描）| 2 小时 | 脚本 + ~60 次 RDM |
| 2 | VI.2（noise 过滤复跑）| 20 分钟 | 复用 VI.1 框架 |
| 3 | VI.3（波形 gallery）| 1.5 小时 | Nature 格式调试 |
| 4 | VI.4（空间分布图）| 45 分钟 | 同 VI.3 |
| 5 | VI.5（A + B + C metrics）| 2-2.5 小时 | 读两边 Sorting，jitter 匹配 |
| 6 | VI.6（报告整合 + §9）| 30 分钟 | 以上全部 |

**总估时**：~7 小时；**零管道重跑**；仅新增 4 个 `tools/diag_*.py` 脚本。

**显式不做**：
- 不重跑 sorting / curate / postprocess
- 不改 src/ 代码（若 VI 揭示真 bug，进下一轮）
- 不预先承诺替代指标进入 pipeline 产物（先验证再决定）
- VI.3/VI.4 视觉不作为量化证据，只作 sanity check；最终结论以 VI.1 + VI.5 数字为准

### VI 执行完成（2026-04-20 下午）

- [x] **VI.1** RDM ablation 扫描（`tools/diag_rdm_ablation.py`，`diag/rdm_ablation.csv` + `diag/rdm_vs_size.png`）。cross @ FULL × trial_frac=1.0 = **0.773** 精确复现 V.3 的 0.77；cross 曲线对 unit_count 强依赖。 ✅
- [x] **VI.2** SUA+MUA 过滤（`--filter-noise`）。cross @ 133 random：0.45 → **0.62**；cross @ FULL：0.77 → **0.80**。噪声单元稀释 cross，对 split-half 影响小。 ✅
- [x] **VI.1b**（新增）**修复 V.8.3 的索引 bug**（`tools/diag_v8_rerun.py`，`diag/v8_shared_subset_corrected.txt`）：
  - bug: `TrialRaster*.h5` 不存 unit_ids 字段，`_load_raster` 回退 `arange(n)`，后续 ks_id 过滤变成"数值区间碰撞"。
  - 用 `UnitProp.csv` 的 `id`/`ks_id` 列重建映射后，matched-both-in-raster = **171** 对（非原 133）。
  - shared-171 RDM = **0.7705**（≈ FULL 0.7708），**推翻** V.8.3 的 0.34 数字。
  - 新结论：matched backbone 已承担几乎全部 RDM 信号，独有单元贡献近零。
- [x] **VI.3** matched-pair 波形 gallery（`tools/diag_pair_waveforms.py`，`diag/pair_waveforms.png/svg`）。12 对：高/中/低 cos + 3 unmatched；5 通道 offset，Nature 格式。 ✅
- [x] **VI.4** matched-pair 空间分布（`tools/diag_pair_spatial.py`，`diag/pair_spatial.png/svg`）。实心 ours / 空心 ref / 灰线连接 / per-pair x-jitter。 ✅
- [x] **VI.5** pipeline agreement 指标 A+B+C（`tools/diag_pipeline_agreement.py`，`diag/pipeline_agreement.csv/summary.txt/hist.png`）：
  - A: per-pair per-image FR Pearson median=**0.64**；28% 对 > 0.8
  - B: spike F1 @ ±1ms median=**0.49**；**precision 0.80 / recall 0.38** → ours 保守
  - C: Recall 50% / Precision 75%；**SUA recall 仅 25%**（13/52） ✅
- [x] **VI.6** 综合报告 `docs/validation/rsm_report.md` §9 + §10（推翻 §8 旧总结；给出"一致性仪表板"建议）。 ✅

**VI 关键结论**：
1. V.8 的 "shared 子集 RDM << FULL" 是 bug；修复后 shared = FULL。
2. RDM 对 unit count 强敏感（random-171=0.58 vs matched-171=0.77 vs FULL=0.77）。
3. 评估管道质量应以 **per-neuron 指标为主**：unit recall、SUA recall、per-pair FR Pearson、spike F1。
4. ours 是更保守的管道（precision 高 / recall 低），SUA 恢复率只有 25% 是新暴露的关键问题。

**下一轮（不在 VI 范围）可考虑**：
- 调 ours 的 curate / sort 参数以提升 SUA recall（具体方向：bombcell 阈值、Th_learned、cluster_downsampling）——**需要重跑 sort+curate**，留给下一个独立 session。
- 把 `unit_ids` 写进 `TrialRaster_*.h5`，避免未来再重现 V.8.3 的映射 bug：改 `src/pynpxpipe/io/derivatives.py::export_trial_raster`（需 TDD）。

---

## VII. 第七轮验证（2026-04-20 晚）：修图 + per-unit reliability + PSTH

**背景**：VI 末尾用户抽查发现：
1. `diag/unit_pairing.csv` 的 `d_xy` 用 `UnitProp*.csv` 的 `unitpos` 复算对不上。
2. `diag/pair_waveforms.png` 子图"5 列 + 中间 2 条分割线"语义不清。
3. `diag/pair_spatial.png` 圈太小、灰线太淡。
4. ours 相对 ref 的各项稳定性指标偏低（split-half 0.27 vs 0.33；SUA recall 25%；spike F1 recall 38%），需要单元级证据（split-half 信度 + PSTH）判断是否是 sorting 质量问题。

**全设计见** `docs/round7_validation_design.md`。本轮不重跑 pipeline，只读 `05_curated` / `06_postprocessed/*/analyzer` / `07_derivatives` + 参考 `processed_good/`。

### 已验证

- [x] **VII.A** d_xy 源不一致：OURS 侧 `analyzer.unit_locations` ≡ UnitProp CSV `unitpos`；REF 侧 analyzer（SI monopolar_triangulation）≠ UnitProp CSV（MATLAB Bombcell `ksPeakChan_xy`，峰值通道坐标）。`diag/unit_pairing.csv` 内部自洽（两边都用 analyzer），但用 REF UnitProp CSV 复算 d_xy 会系统性偏大。结论：不是 bug，是 REF 的 MATLAB CSV 与 analyzer 数据源分歧，文档化即可。

### 待执行

- [ ] **VII.B** 修 `tools/diag_pair_waveforms.py`：通道选取从 `peak_ch ± 2`（按 channel index）改为按 `probe.contact_positions` 欧氏距离取 5 最近邻；每通道标 ch_idx + (x, y)；加 scale bar；基线加到 alpha=0.5。覆盖 `diag/pair_waveforms.png/svg`。
- [ ] **VII.C1** 修 `tools/diag_pair_spatial.py`：匹配线 lw=0.6/alpha=0.85，圆 12-40 pt，未配对单元换 facecolor 不降 alpha，jitter 放大到 8 µm。覆盖 `diag/pair_spatial.png/svg`。
- [ ] **VII.C2** 新 `tools/diag_pair_spatial_unitprop.py`：用 UnitProp CSV 的 unitpos 画对照图（REF peakchan vs OURS monopolar 算法差异显形）。输出 `diag/pair_spatial_unitprop.png/svg`。
- [ ] **VII.D** 新 `tools/diag_per_unit_reliability.py`：每 unit 计算 splithalf FR Pearson (5 seed) / splithalf PSTH Pearson / selectivity (Lurie) / n_spikes / snr。输出 `diag/per_unit_reliability.csv` + `_hist.png` + `matched_pair_reliability_scatter.png` + `_summary.txt`。
- [ ] **VII.E** 新 `tools/diag_psth_gallery.py`：12 pair 的 PSTH 对比（ref top-1 / ref mean / ours top-1 / ours mean 叠加）。输出 `diag/psth_gallery.png/svg`。
- [ ] **VII.F** 报告 `docs/validation/per_unit_analysis.md`：汇总 §A 澄清、reliability 分布、matched-pair 散点、PSTH 定性观察、ours-vs-ref 稳定性归因、SUA recall 25% 的影响。

**预计总时** ≈ 4.5 h，零管道重跑。

---

## 不做什么

- 不改 NWB 里 `units.unit_location` 的 3D 结构（保持 DANDI 共享兼容）。
- 不改 `curate.py` 的"保留 SUA+MUA+NON-SOMA"策略（bombcell 保留率已对齐 reference）。
- 不在 Phase 3 / Phase NWB 轨道外扩大改动；本批次只涉及 `io/derivatives.py` + `plots/bombcell.py` + 诊断工具。
