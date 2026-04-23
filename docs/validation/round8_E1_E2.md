# Round VIII 消融实验 — E1 / E2 / E3 联合报告

生成日期：2026-04-21（E1/E2 首轮），2026-04-21 E3 追加
输入依据：`docs/validation/pipeline_diff_audit.md` § 5 Round VIII 实验设计。
目的：单独改动 **Th_learned (E1)** 和 **漂移校正路径 (E2)**，再验证 **合并 (E3 = E1 + E2)** 是否存在正向交互。

---

## 0. TL;DR

- **E2（漂移校正改为 KS4 `nblocks=5`，关闭 SI DREDge）是全局赢家**：vs baseline，匹配 REF 的单元 +35（194 → 229，+18%），全种群 RSM Pearson +0.018（0.771 → 0.789），matched-pair reliability r 从 0.635 → 0.681，SUA 数从 24 → 32。把对 REF 的 recall 从 50.1% 抬到 59.2%。
- **E1（`Th_learned` 从 8 → 7）在几乎所有指标上退步**：matched 194 → 175，RSM full 0.771 → 0.642，单元总数 259 → 237。预期中"降低检出阈值 → 检出更多单元"的结论被数据否掉——KS4 下游聚类在更低阈值下合并更激进，反而收回单元。
- **E3（E1+E2 合并：Th=7 + nblocks=5）并没有正向交互**：matched 201（vs E2 229），RSM full 0.667（vs E2 0.789），SUA 20（vs E2 32，甚至低于 baseline 24）。**`Th_learned=7` 在任何漂移路径下都是有害的**，E1 的退步并非源自与 DREDge 的相互作用。最终推荐配置 = **E2**（`nblocks=5` + `Th_learned=8`，关 DREDge）。
- **残余差距（REF 387 vs E2 311）**仍然有 158 个 REF-only 单元未召回。audit § 2 给出的剩余因子（MATLAB step #19 方向性过滤、极性校正、ML 特异聚类）均不能通过 pipeline 参数调节关闭，需要单独实现。

---

## 1. 实验配置

| | Preprocess 漂移 | KS4 `nblocks` | KS4 `Th_learned` | 其他 |
|---|---|---|---|---|
| **round 7 baseline**（`processed_pynpxpipe/`） | DREDge preset | 0 | 8.0 | curate 阈值 & 其它参数统一（`config/pipeline.yaml` + `config/sorting.yaml`） |
| **E1**（`processed_pynpxpipe_E1/`） | DREDge preset | 0 | **7.0** ← | 其余与 baseline 完全一致（`config/sorting_E1.yaml`） |
| **E2**（`processed_pynpxpipe_E2/`） | **null** ← | **5** ← | 8.0 | 其余一致（`config/pipeline_E2.yaml` + `config/sorting_E2.yaml`） |
| **E3**（`processed_pynpxpipe_E3/`） | **null** | **5** | **7.0** ← | E1 + E2 合并（`config/pipeline_E2.yaml` + `config/sorting_E3.yaml`） |

- E1 通过 NTFS junction 复用 baseline 的 `01_preprocessed/`（16 GB Zarr）与 `04_sync/`，只重跑 sort→curate→postprocess→export。GPU 耗时 ~13 分钟。
- E2 因为漂移关掉，Zarr 必须重写（最终 3.9 GB，vs baseline 16 GB），所以 preprocess→sort→sync→curate→postprocess→export 全跑。GPU 耗时 ~13 分钟（preprocess 本身因为 CMR+filter 不产生中间漂移校正产物，比 baseline 快）。
- E3 通过 junction 复用 **E2** 的 `01_preprocessed/` + `04_sync/`（nblocks=5 需要 motion_correction=null，与 E2 一致），只重跑 sort→curate→postprocess→export。GPU 耗时 ~10 分钟。
- 三个输出目录都使用独立 checkpoint 体系，未污染 `processed_pynpxpipe/`。

注：CLI 入口 `pynpxpipe run` 目前调用 `SessionManager.create()` 时缺少 `experiment`/`probe_plan`/`date` 三个必需关键字参数（UI 层 `ui/app.py:182` 完整传入），会立即报错。本次消融用 `tools/run_ablation.py` 直接走 `SessionManager.load()` 绕开。CLI 这个 bug 单独记账，暂不处理。

---

## 2. 主结果

### 2.1 unit 计数

| 阶段 | baseline | E1 | E2 | **E3** | REF |
|---|---:|---:|---:|---:|---:|
| KS4 raw 输出 | 459 | 409 | **525** | 444 | 387 |
| curate 通过 (SI thresholds) | 259 | 237 | **311** | 267 | — |
| UnitProp.csv (postprocess) | 259 | 237 | 311 | 267 | 268 |
| SUA (Bombcell 分类) | 24 | 22 | **32** | **20** | 52 |
| MUA | 191 | 182 | 210 | 195 | 138 |
| NOISE | 44 | 33 | 69 | 45 | 78 |

**观察**：
- E1 从 baseline 的 459 raw 降到 409（−50）。预期"更低阈值应该检出更多单元"不成立。KS4 的模板学习在 Th_learned=7 下更积极地合并/丢弃边缘模板，净效应是收回而不是扩展。
- E2 从 459 raw 升到 525（+66），SUA 从 24 → 32（+33%）。nblocks=5 的跨区段漂移跟踪似乎允许 KS4 保留更多在时间上移动的单元。
- E2 的 NOISE 计数（69）是 baseline（44）的 1.6 倍——更多候选也意味着更多低质量假单元，curate 通过率（311/525 = 59%）低于 baseline 的 259/459 = 56%，但绝对数量仍然更高。
- **E3 (267) 远低于 E2 (311)**。把 Th_learned=7 叠加到 nblocks=5 上，raw 从 525 砍到 444（−81），再 curate 到 267——和 baseline 的 259 几乎打平。最令人意外的是 **E3 SUA 只有 20**，不仅低于 E2 的 32，还低于 baseline 的 24——Th_learned=7 在好的漂移基础上仍然把合理单元合并掉了。

### 2.2 与 REF 的匹配 (`diag_unit_pairing`)

| 指标 | baseline | E1 | E2 | **E3** |
|---|---:|---:|---:|---:|
| matched | 194 | 175 | **229** | 201 |
| ref_only (漏检) | 193 | 212 | 158 | 186 |
| ours_only (假阳) | 65 | 62 | 82 | 66 |
| recall = matched / 387 | 50.1% | 45.2% | **59.2%** | 51.9% |
| precision = matched / ours_total | 74.9% | 73.8% | 73.6% | **75.3%** |
| cos sim median | 0.947 | 0.934 | 0.938 | 0.931 |
| d_xy median (µm) | 3.1 | 4.2 | 3.3 | 3.7 |
| matched & both-in-raster | 133 | 109 | 154 | 133 |

**观察**：
- recall：E2 ≫ E3 ≈ baseline ≫ E1。E3 的 51.9% 仅比 baseline 略好（+1.8 pp），但比 E2 低 7.3 pp——合并没有产生协同效应。
- precision 三者齐平（73–75%）；E3 的 precision 最高（75.3%）是因为分子分母同减。
- E3 的 d_xy（3.7 µm）介于 E1（4.2）和 E2（3.3）之间，说明 Th_learned=7 对位置估计的抖动贡献与 drift path 解耦。
- E2 的 matched-and-in-raster（154）仍是最高，E3（133）退回与 baseline 齐平。

### 2.3 RSM（pairwise 种群相似度）

| Pearson | baseline | E1 | E2 | **E3** |
|---|---:|---:|---:|---:|
| 匹配子集（对齐到 REF 的仅共同单元） | 0.342 | 0.338 | **0.455** | 0.390 |
| 全集（各自 pipeline 的全体单元） | 0.771 | 0.642 | **0.789** | 0.667 |

**观察**：
- 全集 RSM：E1 退步 0.129，E2 进步 0.018，**E3 退步 0.104**。E3 全集 RSM (0.667) 几乎退回到 E1 (0.642) 的水平，说明 Th_learned=7 导致的"种群结构噪声"在叠加 nblocks=5 后**没有被抵消**。
- 匹配子集 RSM：E3 (0.390) 介于 baseline (0.342) 和 E2 (0.455) 之间。E2 仍是唯一显著跳升项（vs baseline +33%）。

### 2.4 每单元 split-half reliability (`diag_per_unit_reliability`)

FR Pearson median（数字越高，单元响应在 trial 间越一致）：

| 分组 | REF | baseline | E1 | E2 | **E3** |
|---|---:|---:|---:|---:|---:|
| ALL | 0.262 | 0.251 | 0.263 | 0.218 | 0.250 |
| SUA | 0.329 | 0.472 | 0.418 | **0.489** | 0.459 |
| MUA | 0.306 | 0.245 | 0.235 | 0.184 | 0.233 |
| NOISE | 0.226 | 0.193 | 0.240 | 0.181 | 0.225 |

matched-pair reliability 相关（REF 单元的 FR Pearson vs 我们配对单元的 FR Pearson，越高越说明我们复刻了 REF 的"信息含量"）：

| | baseline | E1 | E2 | **E3** |
|---|---:|---:|---:|---:|
| n 对 | 171 | 145 | **195** | 168 |
| Pearson r | 0.635 | 0.643 | **0.681** | 0.649 |

**观察**：
- SUA 的 split-half median：E2 (0.489) > baseline (0.472) > E3 (0.459) > E1 (0.418) > REF (0.329)。E3 的 SUA 本身响应还行，但**只有 20 个**——数量太少抵消了单元质量优势。
- matched-pair r：E2 (0.681, n=195) > E3 (0.649, n=168) > E1 (0.643, n=145) > baseline (0.635, n=171)。E3 的 matched-pair 样本数比 baseline 少（168 vs 171），质量也没有显著超过 E2。
- 结论：单元**数量**和**匹配 r** 两个维度 E2 都占优，E3 没有带来 E2 之外的增益。

---

## 3. 因子归因

结合 audit § 2 的"13 行差异矩阵"与本次 E1/E2/E3 结果，可以重新给因子贡献排序：

| 因子 | 方向 | 幅度证据 | 下一步 |
|---|---|---|---|
| **漂移校正算法** (DREDge vs KS4 nblocks) | E2 改动 → matched +35, SUA +8, RSM full +0.018 | 强，已经解释一半的 REF gap | **锁定 nblocks=5 做默认** |
| **Th_learned 8 → 7** | E1 单独 → matched −19, RSM full −0.129；**E3（叠 nblocks=5）→ matched −28 相对 E2**，RSM full −0.122 | **持续负向**，在两种漂移路径下都有害 | **拒绝**；`Th_learned=8` 保持不动 |
| 方向性过滤 (step #19) | 未测试 | audit § 4 argued this affects selectivity/RDM，不影响 unit 数 | 纳入 postprocess 以后的单独 ticket |
| phase_shift 位置 | 等价（LTI） | 0 | 非因子，关掉 |
| Bombcell 细则 | 未测 | 可能影响 SUA/MUA/NOISE 比例 | E5 验证 |

**主结论**：
1. **Th_learned=7 在任何漂移路径下都有害**——E1（叠 DREDge）和 E3（叠 nblocks=5）都比对应的 Th=8 基准退步。audit 原本的假设是"E1 负向是因为和 DREDge 打架，换 nblocks=5 后会翻正"，E3 数据直接否定这一假设。
2. **E2 (Th=8 + nblocks=5 + 无 DREDge) 是本轮唯一的最优组合**。应该作为新的 default pipeline。
3. Round 7 → REF 的 gap（259 → 387 = +128），E2 覆盖了约 +52（259 → 311），剩余 +76 主要依赖 MATLAB step #19 方向性过滤 + Bombcell 细则对齐。

---

## 4. 建议的后续实验

E3 已完成（见上文），下一步按优先级：

1. **更新默认配置为 E2**：把 `config/pipeline.yaml` 的 `motion_correction.method` 改为 `null`，`config/sorting.yaml` 的 `nblocks` 改为 5，`Th_learned` 保持 8.0。这是 E1/E2/E3 三组对比的明确结论——E2 在 matched、recall、RSM、matched-pair r 四个维度全部领先。

2. **MATLAB step #19 方向性过滤**：纳入 `docs/specs/postprocess.md` 的"ranksum p<0.001 & mean(60-220ms) > mean(baseline) & unitType≠0"规则。这是 selectivity/RDM 对比差异的主因，与 sort 阶段独立，预计能覆盖 REF gap 中剩余的约 +76 单元中的一部分。

3. **完善 Bombcell 阈值** (E5)：对齐 MATLAB 的 Bombcell 默认项（具体参数见 audit § 5 E5 行）。E3 SUA 数量（20）异常偏低，暗示 Th_learned=7 路径下的 Bombcell 分类也受影响；先拿 E2 作为 Bombcell 调参的稳定基线。

4. **E4 微调探索**（可选）：在 E2 基础上进一步扫描 `nblocks∈{3,5,7}` 与 `cluster_downsampling∈{1,2}`，确认 nblocks=5 不是 local optimum。优先级低，仅在 step #19 实现后仍有 REF gap 时再做。

---

## 5. 数据与代码复现

- 输出目录：
  - baseline `F:\#Datasets\demo_rawdata\processed_pynpxpipe\`
  - E1 `F:\#Datasets\demo_rawdata\processed_pynpxpipe_E1\`（`01_preprocessed` / `04_sync` 通过 NTFS junction 从 baseline 共享）
  - E2 `F:\#Datasets\demo_rawdata\processed_pynpxpipe_E2\`（独立 Zarr，3.9 GB）
  - E3 `F:\#Datasets\demo_rawdata\processed_pynpxpipe_E3\`（`01_preprocessed` / `04_sync` 通过 NTFS junction 从 E2 共享）
- 配置文件：`config/pipeline.yaml`, `config/pipeline_E2.yaml`, `config/sorting.yaml`, `config/sorting_E1.yaml`, `config/sorting_E2.yaml`, `config/sorting_E3.yaml`
- 运行器：`tools/run_ablation.py`（绕过 CLI 的 create() bug 走 load() 路径）
- diag 参数化：6 个 diag 脚本读 `PYNPX_OURS_ROOT` + `PYNPX_DIAG_OUT` 环境变量。默认值保持原 round 7 指向。复现命令（以 E3 为例）：
  ```bash
  PYNPX_OURS_ROOT='F:/#Datasets/demo_rawdata/processed_pynpxpipe_E3' \
  PYNPX_DIAG_OUT='diag/E3' \
  uv run python tools/diag_unit_pairing.py
  # 依赖 diag/E3/unit_pairing.csv → 再跑其余 diag 脚本
  ```
- E3 pipeline 运行命令：
  ```bash
  uv run python tools/run_ablation.py \
    'F:/#Datasets/demo_rawdata/processed_pynpxpipe_E3' \
    config/pipeline_E2.yaml config/sorting_E3.yaml \
    sort curate postprocess export
  ```
- diag 输出：`diag/E1/*`（E1）、`diag/E2/*`（E2）、`diag/E3/*`（E3）、`diag/*`（round 7 baseline，保留）

---

## 附录 A：原始数字一次性索引

**baseline：**
- `processed_pynpxpipe/checkpoints/sort_imec0.json` — 459
- `processed_pynpxpipe/checkpoints/curate_imec0.json` — 459 → 259
- `diag/unit_pairing_summary.txt` — matched=194, cos_sim=0.947, d_xy=3.1
- `diag/per_unit_reliability_summary.txt` — SUA FR Pearson median 0.472 (n=24), matched-pair r=0.635 (n=171)

**E1：**
- `processed_pynpxpipe_E1/checkpoints/sort_imec0.json` — 409
- `processed_pynpxpipe_E1/checkpoints/curate_imec0.json` — 409 → 237
- `diag/E1/unit_pairing_summary.txt` — matched=175, cos_sim=0.934, d_xy=4.2
- `diag/E1/per_unit_reliability_summary.txt` — SUA FR Pearson median 0.418 (n=22), matched-pair r=0.643 (n=145)

**E2：**
- `processed_pynpxpipe_E2/checkpoints/sort_imec0.json` — 525
- `processed_pynpxpipe_E2/checkpoints/curate_imec0.json` — 525 → 311
- `diag/E2/unit_pairing_summary.txt` — matched=229, cos_sim=0.938, d_xy=3.3
- `diag/E2/per_unit_reliability_summary.txt` — SUA FR Pearson median 0.489 (n=32), matched-pair r=0.681 (n=195)

**E3：**
- `processed_pynpxpipe_E3/checkpoints/sort_imec0.json` — 444
- `processed_pynpxpipe_E3/checkpoints/curate_imec0.json` — 444 → 267
- `processed_pynpxpipe_E3/checkpoints/postprocess_imec0.json` — n_units=267, slay_mean=0.0595
- `diag/E3/unit_pairing_summary.txt` — matched=201, cos_sim=0.931, d_xy=3.7
- `diag/E3/per_unit_reliability_summary.txt` — SUA FR Pearson median 0.459 (n=20), matched-pair r=0.649 (n=168)

**REF（固定）：**
- `processed_good/SI/analyzer` — 387 units
- `processed_good/deriv/UnitProp_...csv` — 52 SUA / 138 MUA / 78 NOISE / 268 总
