# 预处理流程知识萃取 — 分析任务清单

> 目标：从 MATLAB 原版代码萃取完整预处理流程事实，产出结构化探针记录。
> 状态图例：⬜ 待开始 | 🔵 进行中 | ✅ 完成

---

## Step 1 ✅ 摸清 MATLAB 版本的入口结构（文件调用树）

**产出文档**：`docs/ground_truth/step1_entry_structure.md`

**完成内容**：
- [x] 全局参数表（5 个参数，全部硬编码）
- [x] 完整调用树（含 Analysis_Fast.ipynb 前置步骤）
- [x] Load_Data_function 调用树（6 个子函数 + 内联逻辑）
- [x] PostProcess_function_raw 调用树（2 个子函数）
- [x] PostProcess_function 调用树（1 个子函数 + 内联逻辑）
- [x] 确认 PostProcess_function_LFP / rm_template / parse_name 均不在主流程中
- [x] 跨阶段状态传递表（文件传递链）
- [x] 8 个不确定项标记（含 fscale.mat 来源、预处理顺序、-5ms 校正等）
- [x] 叶子函数快速参考表（13 个函数）

---

## Step 2 ✅ SpikeGLX 输入消费点分析 + 统一输入端总表

**产出文档**：`docs/ground_truth/step2_input_consumption.md`

**完成内容**：
- [x] 8 个 SpikeGLX 消费点详细记录（S1-S8）
- [x] 表一：meta 文件字段消费清单（9 个字段 × 3 种 meta）
- [x] 表二：bin 文件通道消费清单（5 项）
- [x] 表三：SpikeGLX 与 BHV2 交汇点（6 个交汇步骤）
- [x] 统一输入端消费点总表（21 个步骤，按处理顺序排列）
- [x] 5 个交汇节点时序分析
- [x] 4 个不确定项
- [x] 7 个 MATLAB vs Python 差异（含 3 个功能缺失）

**目标**：找出 MATLAB 代码中所有读取 SpikeGLX 文件（.meta, .ap.bin, .lf.bin, .nidq.bin）的位置，记录每个消费点的：
- 读取哪个文件 / 哪些字段
- 如何解析（memmap? fread? 第三方库?）
- 数据被转换成什么格式/变量

**待完成**：
- [ ] 分析 `load_meta.m`：解析 .meta 文件的逻辑，提取哪些字段
- [ ] 分析 `load_IMEC_data.m`：如何读取 .ap.bin，memmap 方式，通道映射
- [ ] 分析 `load_NI_data.m`：如何读取 .nidq.bin，通道含义
- [ ] 分析 `load_LFP_data.m`：如何读取 .lf.bin
- [ ] 分析 `parse_name.m`：从文件名/路径中提取什么信息
- [ ] 汇总所有 .meta 字段消费表（哪个函数用了哪个 meta 字段）

---

## Step 3 ✅ 输出端分析（临时文件 + 诊断图）

**产出文档**：`docs/ground_truth/step3_output_analysis.md`

**完成内容**：
- [x] 14 个写文件操作完整记录（含 Analysis_Fast.ipynb 的 2 个 + rm_template.m 的 1 个）
- [x] 16 个绘图操作完整记录（含 Bombcell 内部 figure）
- [x] 3×6 subplot 布局映射
- [x] 文件输出依赖图（生产-消费关系树）
- [x] 质检图清单（按流程顺序排列）
- [x] 输出文件汇总表（按类型分类）
- [x] 5 个不确定项（fscale.mat 来源、Bombcell 内部文件列表、KS_TEMP2 清理等）

---

## Step 4 ✅ 综合：完整流程解析（输入→处理→输出 per step）

**产出文档**：`docs/ground_truth/step4_full_pipeline_analysis.md`

**完成内容**：
- [x] 21 个处理步骤的完整三元组（输入/处理/输出），严格按代码行号引用
- [x] 步骤 #0-#12：Load_Data_function 全部（发现→加载→同步→验证→校准→META 输出）
- [x] 步骤 #13：Analysis_Fast.ipynb（AP 预处理 + KS4）
- [x] 步骤 #14-#17：PostProcess_function_raw 全部（Bombcell→KS4 加载→清理→GoodUnitRaw 输出）
- [x] 步骤 #18-#20：PostProcess_function 全部（Raster/PSTH→统计筛选→★GoodUnit 最终输出）
- [x] 每步骤含质检节点、注意事项（硬编码值、边界情况）
- [x] 流程总览表（21 行，含步骤名/主要输入/主要输出/关键参数来源/质检图）

**预计探针记录列表**（待 Step 1 完成后修正）：
- [x] 探针记录：数据发现与元信息加载（parse_name + load_meta）
- [x] 探针记录：IMEC AP 数据加载（load_IMEC_data）
- [x] 探针记录：NIDQ 数据加载与同步信号提取（load_NI_data）
- [x] 探针记录：BHV2 行为数据解析（bhv_read + mlbhv2）
- [x] 探针记录：时间同步与事件对齐（examine_and_fix_sync）
- [x] 探针记录：Kilosort4 输出加载（load_KS4_output）
- [x] 探针记录：后处理 — 原始数据版（PostProcess_function_raw）
- [x] 探针记录：后处理 — 标准版（PostProcess_function）
- [x] 探针记录：质控 — Bombcell（run_bc）
- [x] ~~探针记录：LFP 处理（load_LFP_data + PostProcess_function_LFP）~~ — 用户确认跳过

---

## Step 5 ✅ MATLAB vs Python 差异对比

**产出文档**：`docs/ground_truth/step5_matlab_vs_python.md`

**完成内容**：
- [x] 21 个步骤的逐步对比（6 维度 × 每步骤：实现位置/输入格式/处理逻辑/关键参数/输出格式/质检节点）
- [x] Python 旧代码模块映射（data_loader / synchronizer / spike_sorter / quality_controller / data_integrator）
- [x] 差异分类标注（5 个 ❌ 错误 / 10 个 ⚠️ 存疑 / 14 个 ➕ 新增 / 3 个 ➖ 缺失）
- [x] 必须修复表（5 项：sync 修复逻辑、trial_valid_idx 语义、photodiode 极性、预处理顺序、方向性筛选）
- [x] 需要验证表（10 项）
- [x] 可保留新增表（14 项）
- [x] 非关键缺失表（3 项）

---

## Step 6 ⬜ 汇总成预处理完全解析文档

**目标**：将所有探针记录整合为一份完整的 `docs/ground_truth/preprocessing_full_analysis.md`。

**待完成**：
- [ ] 整合所有探针记录
- [ ] 补充调用树总览图
- [ ] 补充输入/输出文件总览表
- [ ] 补充与 pynpxpipe 新架构的映射关系建议（仅在用户确认后）

---

## MATLAB 文件阅读进度

| 文件 | 状态 | 行数 | 备注 |
|------|------|------|------|
| `process_pipeline_matlab/Process_pipeline_2504.m` | ✅ 已读 | 15 | 顶层入口 |
| `process_pipeline_matlab/gen_globaL_par.m` | ✅ 已读 | 7 | 全局参数 |
| `process_pipeline_matlab/rm_template.m` | ✅ 已读 | 17 | 清理脚本，不在主流程中 |
| `process_pipeline_matlab/Analysis_Fast.ipynb` | ✅ 已读 | 2 cells | SpikeInterface 预处理 + KS4 |
| `Util/Load_Data_function.m` | ✅ 已读 | 266 | 主函数1 |
| `Util/PostProcess_function_raw.m` | ✅ 已读 | 24 | 主函数2 |
| `Util/PostProcess_function.m` | ✅ 已读 | 93 | 主函数3 |
| `Util/load_NI_data.m` | ✅ 已读 | 56 | NIDQ 加载 |
| `Util/load_IMEC_data.m` | ✅ 已读 | 24 | IMEC LF 同步提取 |
| `Util/load_meta.m` | ✅ 已读 | 37 | .meta 解析 |
| `Util/load_KS4_output.m` | ✅ 已读 | 33 | KS4 结果加载 |
| `Util/load_LFP_data.m` | ✅ 已读 | 73 | LFP 加载（不在主流程中） |
| `Util/examine_and_fix_sync.m` | ✅ 已读 | 66 | 同步对齐 |
| `Util/parse_name.m` | ✅ 已读 | 19 | 文件名解析（不在主流程中） |
| `Util/parsing_ML_name.m` | ✅ 已读 | 5 | ML 文件名解析 |
| `Util/bhv_read.m` | ✅ 已读 | 584 | 旧 .bhv 格式读取器 |
| `Util/mlbhv2.m` | ✅ 已读 | 399 | .bhv2 格式读写类 |
| `Util/mlfileopen.m` | ✅ 已读 | 15 | 文件格式分派器 |
| `Util/mlread.m` | ✅ 已读 | 32 | 统一读取入口 |
| `Util/prune_wf.m` | ✅ 已读 | 10 | 波形裁剪 |
| `Util/run_bc.m` | ✅ 已读 | 27 | Bombcell 运行 |
