# Spec: docs/specs/best_practices.md（LLM 助手的项目常识库）

## 1. 目标

为 UI 内置的 LLM chat 助手提供一份**可被直接注入 system prompt** 的"项目常识"文档。内容覆盖：

- 易错配置组合（互斥选项、默认值陷阱）
- 运行时资源约束（多探针 lazy load、内存、磁盘）
- 常见报错 → 定位思路的对应表
- 上游数据格式的隐式契约（SpikeGLX、BHV2、photodiode）
- 本项目相对于 MATLAB 旧管线的关键差异

**定位**：它是"浓缩版的架构 + 踩坑记录"，不是教程、不是 API 参考。token 预算 ~1K（~1500 字中文 / 800 词英文以内）。

**使用方式**：`llm_client.build_system_prompt()` 把 `best_practices.md` 全文注入 system prompt，与 `graphify-out/GRAPH_REPORT.md` 并列作为静态上下文。用户提问时，这份文档已经在 LLM 的 context 里，不需要二次检索。

---

## 2. 输入

无运行时输入 —— 这是一份 **静态 markdown**，由人类维护。

---

## 3. 输出

一份 markdown 文件 `docs/specs/best_practices.md`（本文件），按下述结构组织。构造 system prompt 时整个文件被 `Path.read_text()` 读取后以 fenced block 形式拼接。

---

## 4. 内容大纲（本文件本身的结构）

下列每一节的具体条目需要经用户审阅确认后再写入正文。本 Section 只定义大纲骨架，正文在 Section 5 中给出首版。

1. **配置互斥 / 陷阱（Configuration Pitfalls）**
   - DREDge 运动校正与 KS4 `nblocks` 互斥
   - `sync.imec_sync_bit` 只作用于 IMEC 流，不是 NIDQ 通道
   - `curate.isi_violation_ratio_max` 的量纲是 ratio，不是百分比
   - `n_jobs="auto"` 在 Windows 上的实际并发度受 `pool_engine="thread"` 影响

2. **资源与性能（Resource Constraints）**
   - AP bin 文件最大 400–500 GB，禁止 `load_all_data`
   - 多探针 session 的内存推算公式
   - Zarr 中间产物的磁盘占用
   - 每个 stage 末尾的 `del + gc.collect()` 纪律

3. **数据格式隐式契约（Data Contract）**
   - SpikeGLX meta 字段读取优先级（`imSampRate` > `niSampRate`）
   - BHV2 `trial_count_tolerance` 的语义：允许的 trial 数差异
   - Photodiode 极性校正的必要性（MATLAB 有，旧 Python 缺）
   - NIDQ sync bit 与 event bits 的通道布局

4. **常见报错对照表（Error → Solution）**
   - `ConfigError: motion.enabled and nblocks>0`
   - `SyncError: sync pulse count mismatch`
   - `FileNotFoundError: session.json`
   - `ImportError: No module named 'matplotlib'`
   - `KilosortError: CUDA out of memory`

5. **相对 MATLAB 旧管线的差异（Legacy Delta）**
   - 预处理链顺序修正（phase_shift 必须最先）
   - DREDge 运动校正替换 KS4 内部 nblocks
   - photodiode 极性校正补回
   - IMEC↔NIDQ 丢脉冲修复逻辑补回
   - Bombcell 从独立包改为 SpikeInterface 内置

---

## 5. 正文首版（待用户审阅）

> **视角**：这一节是写给 **最终用户**（实验者 / 数据分析师）的，不是给 CC 或开发者的。LLM 助手收到用户提问时，应该能从这里查到"做什么、怎么点、为什么报错"。语言朴素，避免架构术语。

### 5.1 pynpxpipe 是什么，什么时候用

pynpxpipe 是一个**自动化 Neuropixels 电生理管线**。它把一次实验录制产生的原始数据（SpikeGLX AP/NIDQ bin + MonkeyLogic BHV2）转换成标准 NWB 文件。一次运行对应一个 session，session 内可以有任意数量（N ≥ 1）的 IMEC 探针。

适合你：
- 用 SpikeGLX 录了 Neuropixels + NIDQ + MonkeyLogic 行为数据
- 想得到带 trial 事件、同步时间、质量标记的 NWB，可以直接进分析管线
- 不想手动跑 Kilosort、不想写同步脚本、不想每次自己调 QC 阈值

**不适合**：手动筛 Kilosort 的 cluster（本管线是全自动 curation）、只想跑 spike sorting（直接用 SpikeInterface）。

### 5.2 七个 stage 都在做什么

管线按顺序跑七个 stage。失败一个停一个，已完成的 stage 会写 checkpoint，下次从断点继续。

1. **discover** — 扫 session 目录，识别有几个 probe、每个 probe 的 AP/LF/NIDQ 文件齐不齐、meta 有没有损坏。**跑多久**：秒级。
2. **preprocess** — 对每个 probe 的 AP 数据：phase shift → 带通（300–6000 Hz）→ 坏道检测 → 公共参考去除（CMR）→ 可选运动校正 → 存成 zarr。**跑多久**：每个 probe 每 GB 约 1–2 分钟。
3. **sort** — 用 Kilosort4 做 spike sorting；或者如果你已经在别处跑过 KS，用 `sort.mode="import"` 把外部结果导入。**跑多久**：GPU 下每个 probe 约 10–30 分钟。
4. **synchronize** — 三级时钟对齐：IMEC↔NIDQ sync 脉冲回归 → BHV2↔NIDQ 事件码匹配 → photodiode 延迟校准。产出逐 trial 事件表。**跑多久**：秒级到分钟级。
5. **curate** — 计算质量指标（ISI、SNR、amplitude cutoff 等）+ Bombcell 分类，给每个 unit 打 good / mua / noise 标签。**跑多久**：每个 probe 约 2–5 分钟。
6. **postprocess** — 基于 SortingAnalyzer 算模板波形、unit 位置、相似度；可选 SLAy 自动合并重复 unit；可选眼动数据验证。**跑多久**：每个 probe 约 3–10 分钟。
7. **export** — 把所有结果打包写成 NWB 文件。**跑多久**：分钟级。

---

### 5.3 配置 `pipeline.yaml` 的关键项

下面按 **"改什么 → 为什么改"** 组织，而不是穷举所有字段。完整字段见 `docs/specs/config.md`。

**运行资源（`resources`）**
- `n_jobs: "auto"` —— 自动用一半 CPU 核。手动指定时 **别给太满**，preprocess 每个 worker 要占一块 chunk 的内存。
- `chunk_duration: "1s"` —— 每个 worker 一次处理的时长。RAM 小的机器把它设成 `"0.5s"`。

**预处理（`preprocess`）**
- `bandpass.freq_min: 300`, `freq_max: 6000` —— 标准 Neuropixels 值，一般不动。
- `bad_channel_detection.method: "coherence+psd"` —— 用 SpikeInterface 内置的坏道检测。
- `common_reference.reference: "global"`, `operator: "median"` —— 全局中值 CMR，抗共模噪声。
- `motion_correction.enabled: true`, `method: "dredge"` —— **默认开着**。DREDge 比 KS4 内部的 drift 校正更稳定。

**排序（`sorting.yaml`）**
- `sorter.name: "kilosort4"` —— 默认用 KS4。
- `sorter.params.nblocks: 0` —— **默认 0**。因为 preprocess 已经开了 DREDge 运动校正，这里再开 KS4 的内部 drift 会产生双重校正。**同时开两个是最常见的错误配置**。
- 想改用 KS4 自己的 drift 校正时：关掉 `preprocess.motion_correction.enabled`，把 `nblocks` 设成 5 或 15。

**同步（`sync`）**
- `sync_bit_nidq: 1`, `imec_sync_bit: 6` —— 两个是不同硬件通道，不要混淆。NIDQ 上记录的是 NIDQ sync bit，IMEC AP 流里记录的是 IMEC sync bit（标准值 6，Neuropixels 硬件固定）。
- `event_bits: [1,2,3,4,5,6,7]` —— NIDQ 数字通道上的事件码位。
- `stim_onset_code: 64` —— MonkeyLogic 在 stim 开始时发的事件码（2^6=64）。
- `trial_count_tolerance: 2` —— 允许 BHV2 trial 数和 NIDQ 检出 trial 数差 2 个。差得更多说明中间漏了 trial，会 raise `SyncError`。

**质量控制（`curation`）**
- `isi_violation_ratio_max: 2.0` —— ISI 违规率上限，单位是 **ratio 不是百分比**。默认 2.0 含义是允许 200% ISI 违规（Hill 经典阈值）。要严格可以改成 `0.5` 或 `0.1`。
- `firing_rate_min: 0.1` —— 每秒低于 0.1 spike 的 unit 归为噪声。

---

### 5.4 典型操作流程（用户视角）

**首次跑一个 session**
1. UI 里 **Configure** 分区：填 Session Directory（指向包含 `imec0/`, `nidq` 的文件夹）、Output Directory（空的新目录）、BHV File（`.bhv2` 路径）、Subject（动物 ID + 物种 + 年龄）。
2. 右侧填 Pipeline / Sorting 表单（大部分字段用默认即可）。
3. 点侧栏 **Execute** → Run。日志窗口会滚动显示每个 stage 的进度。
4. 跑完后点 **Review** → Load Session，可以看到每个 stage 的状态 + 生成的诊断图。

**中途失败了想从断点继续**
- 直接重新点 Run，已完成的 stage 会被跳过。
- 如果想强制重跑某个 stage：Review 分区找到对应 stage 点 **Reset**，把 checkpoint 清掉，再 Run。

**换配置重跑**
- 改完配置重启 pipeline，**不会**自动失效下游已有 checkpoint。手动 Reset 需要重跑的 stage。

---

### 5.5 常见报错 → 你该做什么

| 报错 | 意思 | 怎么解决 |
|---|---|---|
| `ConfigError: motion_correction.enabled and nblocks>0 are mutually exclusive` | 运动校正和 KS4 内部 drift 同时开了 | **保持 DREDge，把 `sorting.yaml` 里的 `nblocks` 改回 0**（推荐）；或者关掉 `preprocess.motion_correction.enabled` |
| `SyncError: sync pulse count mismatch (imec=N, nidq=M)` | IMEC 和 NIDQ 上的 sync 脉冲数对不上 | 检查录制时 sync cable 是否松动；差 ≤5 个脉冲会被自动修复，差更多说明 sync 线丢了 |
| `SyncError: trial count mismatch bhv=X nidq=Y` | BHV2 报告的 trial 数和 NIDQ 检出的 stim onset 数差太多 | 看 `sync/figures/event_alignment.png` 图，确认中间是否漏了 trial；或者把 `sync.trial_count_tolerance` 调大（谨慎） |
| `FileNotFoundError: session.json` | Review → Load Session 时指错了目录 | 指向一个已经跑过至少一次的 output 目录，里面必须有 `session.json` |
| `Kilosort CUDA out of memory` | GPU 显存不够 | 把 `sorting.yaml` 里的 `sorter.params.batch_size` 减小（从 60000 降到 30000 或 "auto"），或者换更小显存友好的 `chunk_duration` |
| `BHV2 parse error / magic mismatch` | `.bhv2` 文件头不是标准 MonkeyLogic 格式 | 确认文件不是 `.h5`（BHV2 早期命名误导），需要是真正的二进制 bhv2 |
| `ImportError: No module named 'matplotlib'` | 没装诊断图依赖 | `uv pip install -e ".[ui]"`；或关掉 `sync.generate_plots` |
| pipeline 一直停在 preprocess，内存爆了 | `n_jobs` 太大 | 把 `resources.n_jobs` 从 "auto" 改成具体小数字（比如 4），或把 `chunk_duration` 缩短到 `"0.5s"` |

---

### 5.6 常见困惑澄清

- **我要自己跑 Kilosort 吗？** 不用。管线里 `sort` stage 会自动跑 KS4。如果你已经跑过想导入，设 `sort.mode="import"` 并指定 KS 结果路径。
- **能不能跳过某个 stage？** 可以。UI 的 Stage Selector 里勾选想跑的 stage。注意依赖关系：sort 依赖 preprocess，synchronize 依赖 discover，etc。
- **生成的 NWB 文件在哪？** `{output_dir}/nwb/{session_name}.nwb`。
- **想看同步质量？** Review 分区的 Figures 面板会显示 `sync/figures/` 下的所有 PNG（IMEC-NIDQ 散点图、残差直方图、事件对齐图、photodiode 热图等）。
- **多 probe 怎么处理？** 自动的。discover 扫出来几个 probe，后面每个 stage 都会对每个 probe 独立处理，共享同一份 session.json 和同一个 NWB 输出。

---

## 6. 与其它文档的关系

- **CLAUDE.md**：总纲与工具链，面向项目协作者。本文档面向 LLM 运行时注入，粒度更细、更聚焦"避坑"。
- **docs/architecture.md**：架构总纲，~500 行，给人读。本文档是它的"踩坑节选"。
- **docs/ground_truth/\***：MATLAB 参考实现逐行对照，给人写代码时查。本文档只复述结论。
- **graphify-out/GRAPH_REPORT.md**：知识图谱，粒度=节点+边；本文档粒度=条目+原因。两者互补，都注入 LLM 上下文。

---

## 7. 维护规则

- 每次修一个与上述条目相关的 bug，顺手更新对应条目（加一行"历史：{commit hash} 修复 X"）。
- 新增条目必须 ≤50 词，严禁长篇。
- 严禁在本文件放代码片段（代码会快速过时）。只放配置项名、函数名、报错字符串。
- 文件总长度**硬上限 2000 字**。超过就合并条目或移到 architecture.md。
