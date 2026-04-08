# 输入端消费点完整分析（SpikeGLX + BHV2）

> 分析日期：2026-04-03
> 信息来源：仅 MATLAB 源码直接阅读
> 已有材料：`bhv2_consumption_analysis.md`（BHV2 部分）、`step1_entry_structure.md`（调用树）

---

## 第一部分：SpikeGLX 消费点记录

### 消费点 #S1
- **文件**：`.nidq.meta`
- **位置**：`load_NI_data.m:3` → 调用 `load_meta.m`
- **读取方式**：文本逐行解析 `key=value`（`load_meta.m:3-36`）
- **读取的具体内容**：所有 `~` 之前的键值对，解析为 struct 字段
- **用途**：获取 NIDQ 录制参数（采样率、通道数、文件大小、增益等）
- **依赖的 meta 字段**：
  - `fileSizeBytes`（`load_NI_data.m:4`）— 计算总采样点数
  - `nSavedChans`（`load_NI_data.m:5`）— 通道数，用于 memmap reshape
  - `niSampRate`（`load_NI_data.m:8,50,52`）— 采样率，时间转换 + AIN 重采样
  - `niAiRangeMax`（`load_NI_data.m:12`）— 模拟输入量程，int16→电压转换
  - `snsMnMaXaDw`（`load_NI_data.m:13-16`）— 通道类型计数 [MN,MA,XA,DW]，定位数字通道
- **是否有对应的 Python 旧代码实现**：有。`data_loader.py:206` 通过 `nidq_rec.neo_reader.signals_info_dict[(0, 'nidq')]['meta']` 获取 meta dict。`synchronizer.py:165` 读 `niSampRate`，`:469` 读 `niAiRangeMax`。差异：Python 不手动解析 .meta 文本，依赖 SpikeInterface 内部 API（含私有属性 `neo_reader.signals_info_dict`）；`fileSizeBytes`、`nSavedChans`、`snsMnMaXaDw` 在 Python 中不需要（SpikeInterface 内部处理通道映射）。

---

### 消费点 #S2
- **文件**：`.nidq.bin`
- **位置**：`load_NI_data.m:9`
- **读取方式**：`memmapfile` 直接二进制读取，格式 `int16 [nChan × nFileSamp]`
- **读取的具体内容**：
  - **通道 1**（第一行）：模拟输入 AIN（`load_NI_data.m:20`）
    - 转换：`double(NI_rawData(1,:)) * niAiRangeMax/32768`
    - 后续重采样到 1000 Hz（`load_NI_data.m:52-53`）
  - **通道 digCh = MN+MA+XA+1**（最后一个数据通道）：数字字（`load_NI_data.m:30`）
    - 通过 `diff()` 提取事件码变化点
    - 输出 DCode struct：`{CodeLoc, CodeVal, CodeTime}`
- **用途**：
  - AIN = photodiode 模拟信号，用于 onset 时间校准
  - 数字字 = MonkeyLogic 发送的行为事件码 + 同步脉冲
- **依赖的 meta 字段**：fileSizeBytes, nSavedChans, niSampRate, niAiRangeMax, snsMnMaXaDw
- **是否有对应的 Python 旧代码实现**：有。
  - AIN：`data_loader.py:198` 用 `nidq_rec.get_traces(channel_ids=['nidq#XA0'])` 读取模拟通道。`synchronizer.py:469-479` 做 `AIN * fI2V` 电压转换 + `signal.resample_poly(AIN, p, q)` 重采样到 1000 Hz。与 MATLAB 功能对等。
  - 数字字：`data_loader.py:202` 用 `nidq_rec.get_traces(channel_ids=['nidq#XD0'])` 读取数字通道。`synchronizer.py:166-176` 用 `np.diff` 提取事件码，逻辑与 MATLAB `load_NI_data.m:30-36` 对应。差异：Python 用 SpikeInterface 通道 ID 定位，MATLAB 用 `snsMnMaXaDw` 计算通道索引。

---

### 消费点 #S3
- **文件**：`.lf.meta`
- **位置**：`load_IMEC_data.m:2` → 调用 `load_meta.m`
- **读取方式**：文本逐行解析 `key=value`
- **读取的具体内容**：IMEC LF 流元信息
- **用途**：获取 LF 采样率、通道数、文件大小
- **依赖的 meta 字段**：
  - `fileSizeBytes`（`load_IMEC_data.m:3`）— 计算总采样点数
  - `nSavedChans`（`load_IMEC_data.m:4`）— 通道数
  - `imSampRate`（`load_IMEC_data.m:7,21`）— LF 采样率，sync 脉冲时间转换
- **是否有对应的 Python 旧代码实现**：有。`data_loader.py:230` 通过 `imec_rec.neo_reader.signals_info_dict[(0, 'imec0.lf')]['meta']` 获取 meta dict。`synchronizer.py:150` 读 `imSampRate`。差异：Python 不手动解析 .meta 文本，通过 SpikeInterface 私有 API 获取；`fileSizeBytes` 和 `nSavedChans` 在 Python 中不需要。

---

### 消费点 #S4
- **文件**：`.lf.bin`
- **位置**：`load_IMEC_data.m:8-9`
- **读取方式**：`memmapfile` 直接二进制读取，格式 `int16 [nChan × nFileSamp]`
- **读取的具体内容**：
  - **通道 385**（硬编码）：同步数字通道（`load_IMEC_data.m:9`）
    - 通过 `diff()` 提取上升沿（`CodeAll>0`）
    - 输出 DCode struct：`{CodeLoc, CodeVal, CodeTime}`
- **用途**：提取 IMEC 端同步脉冲，与 NIDQ 对齐
- **依赖的 meta 字段**：fileSizeBytes, nSavedChans, imSampRate
- **⚠️ 注意**：读的是 LF 流（不是 AP），因为 LF 文件远小于 AP（~1/10），但同样含 sync 通道。通道号 385 = 384 数据通道 + 1 sync 通道，对 Neuropixels 1.0 LF 流是正确的。
- **是否有对应的 Python 旧代码实现**：有。`data_loader.py:223-226` 用 `si.read_spikeglx(..., stream_name='imec0.lf-SYNC')` + `get_traces(channel_ids=['imec0.lf#SY0'])`。`synchronizer.py:151-156` 用 `np.diff` + `>0` 提取上升沿，与 MATLAB `load_IMEC_data.m:11-13` 逻辑一致。差异：Python 用 SpikeInterface 的 SYNC stream 而非硬编码通道 385。

---

### 消费点 #S5
- **文件**：`.ap.meta`
- **位置**：`Load_Data_function.m:31` → 调用 `load_meta.m`
- **读取方式**：文本逐行解析 `key=value`
- **读取的具体内容**：IMEC AP 流元信息
- **用途**：获取 AP 采样率，传递给 `load_KS4_output` 用于 spike time 转换
- **依赖的 meta 字段**：
  - `imSampRate`（`load_KS4_output.m:7`）— AP 采样率，sample→ms 转换
- **是否有对应的 Python 旧代码实现**：间接有。`data_loader.py:152` 用 `si.read_spikeglx(spikeglx_folder, stream_name='imec0.ap')` 加载 AP 数据，SpikeInterface 内部自动解析 .ap.meta。AP 采样率可通过 `recording.get_sampling_frequency()` 获取（`data_loader.py:243`）。`NPX_session_process.ipynb:cell-8452ac5d` 中 KS4 运行后，通过 `si.load(sorting_path)` 加载 sorting 结果，采样率信息由 SpikeInterface 自动从 AP recording 传递到 sorting 对象。Python 旧代码中没有单独加载 .ap.meta 仅为获取 `imSampRate` 的逻辑——spike time 的采样率转换由 SpikeInterface sorting 对象内部处理，不需要手动读取 `imSampRate` 字段。

---

### 消费点 #S6
- **文件**：`.ap.bin`
- **位置**：`Analysis_Fast.ipynb` cell-0
- **读取方式**：SpikeInterface `si.read_spikeglx(folder, stream_name='imec0.ap', load_sync_channel=False)`
- **读取的具体内容**：全部 384 通道 AP 数据
- **用途**：预处理（highpass → bad channel detection → phase_shift → CMR）→ 保存 binary → Kilosort4
- **依赖的 meta 字段**：SpikeInterface 内部自动解析 .ap.meta
- **是否有对应的 Python 旧代码实现**：有。`data_loader.py:152` 完全相同地使用 `si.read_spikeglx(spikeglx_folder, stream_name='imec0.ap')`。`NPX_session_process.ipynb:cell-f6e0eb8b` 展示了完整的 Python 预处理链：`si.read_spikeglx` → `highpass_filter(freq_min=300)` → `detect_bad_channels` → `remove_channels` → `phase_shift` → `common_reference(operator="median", reference="global")`，与 `Analysis_Fast.ipynb` cell-0 逻辑一致。此外，Python 版本新增了 DREDge 运动校正（`si.correct_motion(recording=rec3, preset='dredge')`，`cell-6a2379c6`），MATLAB 版无此步骤。KS4 调用参数差异：Python 使用 `nblocks=20`（`cell-8452ac5d`），MATLAB `Analysis_Fast.ipynb` 使用 `nblocks=5`。预处理结果保存为 Zarr 格式（`cell-0c5986aa`），MATLAB 保存为 binary。

---

### 消费点 #S7
- **文件**：`.ap.bin` + `.ap.meta`
- **位置**：`run_bc.m:5-6`
- **读取方式**：Bombcell 库内部读取（`bc.load.loadEphysData`, `bc.dcomp.manageDataCompression`, `bc.qm.qualityParamValues`）
- **读取的具体内容**：原始 AP 波形，用于质量指标计算
- **用途**：Bombcell 质控（waveform 特征提取、噪声检测等）
- **依赖的 meta 字段**：由 Bombcell 内部 `bc.dependencies.SGLX_readMeta` 解析
- **是否有对应的 Python 旧代码实现**：有。`NPX_session_process.ipynb:cell-668d73c6` 中调用 `QualityController(kilosort_output_path=ks_output_path, imec_data_path=imec_path)` + `quality_controller.run_quality_control()`，确认 Python 旧代码有 Bombcell 集成。`QualityController` 类（`core/quality_controller.py`）通过 MATLAB engine 调用 Bombcell 库，输入为 KS4 输出目录 + IMEC AP 数据路径。与 MATLAB `run_bc.m` 功能对等，但封装为 Python 类并通过 `matlab.engine` 桥接调用。pynpxpipe 新架构中 Bombcell 功能由 SpikeInterface 0.104+ 原生 `spikeinterface.curation.bombcell_label_units` 替代。

---

### 消费点 #S8（不在主流程中）
- **文件**：SpikeInterface 预处理后的 LFP 输出（非原始 `.lf.bin`）
- **位置**：`load_LFP_data.m:29-38`
- **读取方式**：读 `LFPprep/binary.json`（采样率）、`LFPprep/probe.json`（探针元数据）、`LFPprep/traces_cached_seg0.raw`（memmapfile int16）
- **读取的具体内容**：SpikeInterface 保存的预处理 LFP 二进制 + channel_labels.mat（坏道标记）
- **用途**：加载预处理后的 LFP 数据，按深度合并通道
- **⚠️ 注意**：此函数不在 Process_pipeline_2504.m 主流程中
- **是否有对应的 Python 旧代码实现**：无。Python 旧代码（`data_loader.py`、`synchronizer.py`）中没有 LFP 加载逻辑。

---

## 第二部分：汇总表

### 表一：meta 文件字段消费清单

| meta 文件 | 字段名 | 值类型 | 用途 | 消费位置 |
|-----------|--------|--------|------|---------|
| `.nidq.meta` | `fileSizeBytes` | int | 计算总采样点数 | `load_NI_data.m:4` |
| `.nidq.meta` | `nSavedChans` | int | 通道数 → memmap reshape | `load_NI_data.m:5` |
| `.nidq.meta` | `niSampRate` | float | NIDQ 采样率（~25 kHz） | `load_NI_data.m:8,50,52` |
| `.nidq.meta` | `niAiRangeMax` | float | 模拟输入量程最大值 | `load_NI_data.m:12` |
| `.nidq.meta` | `snsMnMaXaDw` | int[4] | 通道类型计数 [MN,MA,XA,DW] | `load_NI_data.m:13-16` |
| `.lf.meta` | `fileSizeBytes` | int | 计算总采样点数 | `load_IMEC_data.m:3` |
| `.lf.meta` | `nSavedChans` | int | 通道数 → memmap reshape | `load_IMEC_data.m:4` |
| `.lf.meta` | `imSampRate` | float | LF 采样率（~2500 Hz） | `load_IMEC_data.m:7,21` |
| `.ap.meta` | `imSampRate` | float | AP 采样率（~30000 Hz） | `load_KS4_output.m:7` |

### 表二：bin 文件通道消费清单

| bin 文件 | 通道标识 | 信号类型 | 读取范围 | 用途 | 消费位置 |
|---------|---------|---------|---------|------|---------|
| `.nidq.bin` | 行 1（第一通道） | 模拟 — Photodiode (AIN) | 全时段 | Onset 时间校准 | `load_NI_data.m:20` |
| `.nidq.bin` | 行 MN+MA+XA+1 | 数字 — 事件字 | 全时段 | ML 行为事件码 + 同步脉冲 | `load_NI_data.m:30` |
| `.lf.bin` | 行 385（硬编码） | 数字 — Sync 脉冲 | 全时段 | IMEC↔NIDQ 时钟对齐 | `load_IMEC_data.m:9` |
| `.ap.bin` | 全部 384 通道 | 模拟 — AP 宽频 | 全时段 | 预处理 + Kilosort4 | `Analysis_Fast.ipynb:cell-0` |
| `.ap.bin` | 全部 384 通道 | 模拟 — AP 宽频 | 全时段 | Bombcell 质控 | `run_bc.m:5`（内部读取） |

### 表三：SpikeGLX 数据与 BHV2 数据的交汇点

| 交汇步骤 | SpikeGLX 数据 | BHV2 数据 | 交汇函数 | 交汇行号 | 交汇方式 |
|---------|--------------|----------|---------|---------|---------|
| ML↔NI trial 数量一致性验证 | `DCode_NI.CodeVal`（NIDQ 数字事件码） | `trial_ML.BehavioralCodes.CodeNumbers` | `Load_Data_function.m` | :46-74 | 按 onset 事件（code=64）逐 trial 计数对比 |
| 眼动验证 | `DCode_NI`（间接：通过 onset 计数确定 trial 边界） | `trial_ML.AnalogData.Eye` + `VariableChanges` | `Load_Data_function.m` | :87-125 | BHV2 眼动数据按 NIDQ trial 结构逐 onset 验证 |
| Photodiode onset 校准 | `AIN`（photodiode 模拟信号） + `DCode_NI.CodeVal`（onset 事件 bit 64） | （无直接 BHV2 参与，但结果 `onset_time_ms` 后续与 BHV2 trial_valid_idx 关联） | `Load_Data_function.m` | :144-258 | NIDQ 数字 onset 时间 + photodiode 模拟信号校准 |
| IMEC↔NIDQ 时钟对齐 | `DCode_NI`（NIDQ sync 脉冲） + `DCode_IMEC`（IMEC sync 脉冲） | （无 BHV2 参与） | `examine_and_fix_sync.m` | :4-6 | sync 脉冲上升沿配对，产出 SyncLine 映射表 |
| Spike time→NI 时钟转换 | `IMEC_AP_META.imSampRate` + `SyncLine` | （无直接 BHV2 参与） | `load_KS4_output.m` | :7-8 | sample→ms→interp1 映射到 NI 时间域 |
| Raster 构建（spike × onset 对齐） | spike time（已转到 NI 时钟，来自 KS4） | `onset_time_ms`（来自 NIDQ photodiode 校准）+ `trial_valid_idx`（来自 BHV2 眼动验证） | `PostProcess_function.m` | :31-42 | 对每个 valid trial 的每个 onset，在 spike time 序列中搜索 pre/post 窗口内的 spike |

---

## 第三部分：统一输入端消费点总表（按处理步骤排序）

| # | 处理步骤 | 消费的 SpikeGLX 数据 | 消费的 BHV2 数据 | 交汇方式 | 所在函数:行号 |
|---|---------|-------------------|----------------|---------|-------------|
| 0 | SpikeGLX 文件夹发现 | NPX* 目录扫描 → session_name, g_number | — | 无（仅 SpikeGLX） | `Load_Data_function.m:7-9` |
| 1 | NIDQ 数据加载 | `.nidq.meta`（5 个字段）+ `.nidq.bin`（AIN + 数字通道） | — | 无（仅 SpikeGLX） | `load_NI_data.m:1-55` |
| 2 | BHV2 文件发现 + 解析 | — | `*.bhv2` → `mlread()` → trial_ML struct array | 无（仅 BHV2） | `Load_Data_function.m:14-25` |
| 3 | BHV2 文件名解析 | — | BHV2 文件名 → exp_day, exp_subject | 无（仅 BHV2） | `parsing_ML_name.m:1-5` |
| 4 | IMEC LF 同步脉冲提取 | `.lf.meta`（3 个字段）+ `.lf.bin`（通道 385 sync） | — | 无（仅 SpikeGLX） | `load_IMEC_data.m:1-22` |
| 5 | IMEC AP meta 加载 | `.ap.meta` → imSampRate | — | 无（仅 SpikeGLX） | `Load_Data_function.m:30-31` |
| 6 | **IMEC↔NIDQ 时钟对齐** | DCode_NI（NIDQ sync 脉冲 bit 0）+ DCode_IMEC（IMEC sync 脉冲 val=64） | — | 无（两路 SpikeGLX 互对齐） | `examine_and_fix_sync.m:1-66` |
| 7 | **🔴 ML↔NI trial 数量一致性验证** | DCode_NI.CodeVal（bit 1 = trial start, bit 6 = onset） | trial_ML.BehavioralCodes.CodeNumbers（code=64 onset, code=32 offset） | **交汇**：逐 trial 对比 onset 计数，SGLX 用 bit 操作提取，ML 用事件码==64 计数 | `Load_Data_function.m:43-74` |
| 8 | 数据集名称提取 | — | trial_ML.UserVars.DatasetName → 解析图片集名 | 无（仅 BHV2） | `Load_Data_function.m:77-85` |
| 9 | **🔴 眼动验证** | （间接：依赖步骤 7 的 trial 对应关系） | trial_ML.BehavioralCodes + AnalogData.Eye + VariableChanges.onset_time + fixation_window + UserVars.Current_Image_Train | **交汇**：BHV2 的眼动数据按 NIDQ 确认的 trial 结构逐 onset 验证 | `Load_Data_function.m:87-125` |
| 10 | **🔴 Photodiode onset 时间校准** | DCode_NI.CodeVal（bit 6 = onset）+ AIN（photodiode 模拟信号） | （间接：`dataset_valid_idx` 来自步骤 9 的眼动验证） | **交汇**：NIDQ 数字 onset 粗定位 → photodiode 精校准 → 与眼动验证结果关联 | `Load_Data_function.m:144-258` |
| 11 | -5ms 显示器延迟校正 | onset_time_ms（来自步骤 10） | — | 无（硬编码校正） | `Load_Data_function.m:263` |
| 12 | META 文件保存 | NI_META, AIN, DCode_NI, IMEC_META, DCode_IMEC, SyncLine, IMEC_AP_META, g_number | eye_matrix, ml_name, trial_valid_idx, dataset_valid_idx, onset_time_ms, img_size, exp_subject, exp_day | 合并保存到 processed/META_*.mat | `Load_Data_function.m:265` |
| 13 | AP 预处理 + Kilosort4 | `.ap.bin` 全 384 通道（via SpikeInterface） | — | 无（仅 SpikeGLX）| `Analysis_Fast.ipynb:cell-0,1` |
| 14 | Bombcell 质控 | `.ap.bin` + `.ap.meta`（via Bombcell 内部读取）+ KS4 输出 | — | 无（仅 SpikeGLX + KS4） | `run_bc.m:1-26` |
| 15 | **🔴 KS4 输出加载 + 时钟对齐** | IMEC_AP_META.imSampRate + SyncLine（IMEC→NI 映射） | — | 无（KS4 spike time → NI 时钟域） | `load_KS4_output.m:1-32` |
| 16 | trial_ML 字段清理 | — | trial_ML.AnalogData.Mouse/KeyInput 清空 | 无（仅 BHV2） | `PostProcess_function_raw.m:14-17` |
| 17 | GoodUnitRaw 保存 | UnitStrc（含同步后的 spike time） | trial_ML, meta_data | 合并保存到 processed/GoodUnitRaw_*.mat | `PostProcess_function_raw.m:22-23` |
| 18 | **🔴 Raster + PSTH 构建** | UnitStrc.spiketime_ms（已在 NI 时钟域） | onset_time_ms（NIDQ 校准后）+ trial_valid_idx（BHV2 眼动验证后） | **交汇**：每个 valid trial 的每个 onset 前后窗口内搜索 spike | `PostProcess_function.m:31-42` |
| 19 | 统计筛选 + 波形裁剪 | template_bc（Bombcell 波形模板）+ fscale.mat | qMetric, unitType（Bombcell 输出） | 合并判定条件：ranksum + unitType ≠ 0 | `PostProcess_function.m:63-84` |
| 20 | GoodUnit 最终保存 | GoodUnitStrc（筛选后的 unit 数据） | trial_ML, global_params, meta_data | 合并保存到 processed/GoodUnit_*.mat | `PostProcess_function.m:91-92` |

**🔴 = 两种输入数据交汇的关键节点**

---

## 交汇节点时序分析

### 节点 7（ML↔NI trial 验证）：
- **先**：NIDQ 数字码已全量加载到内存（步骤 1）
- **先**：BHV2 trial_ML 已全量解析（步骤 2）
- **时序关系**：两者独立加载后做逐 trial 对比，无先后依赖

### 节点 9（眼动验证）：
- **先**：步骤 7 的 trial 对应关系已确立
- **后**：使用 BHV2 的眼动数据（AnalogData.Eye），按步骤 7 确定的 trial 顺序逐 onset 处理
- **时序关系**：BHV2 数据依赖 NIDQ 的 trial 边界

### 节点 10（Photodiode 校准）：
- **先**：NIDQ 数字 onset 位置已知（DCode_NI.CodeVal bit 64）
- **后**：NIDQ 模拟 AIN（photodiode）在 onset 前后窗口内搜索真实亮度变化
- **间接**：校准后的 onset_time_ms 与步骤 9 的 dataset_valid_idx 关联
- **时序关系**：纯 NIDQ 内部操作，BHV2 间接参与

### 节点 15（KS4 spike time 转换）：
- **先**：SyncLine（步骤 6 产出）+ IMEC_AP_META.imSampRate（步骤 5 产出）
- **后**：spike_times(sample) → ms → interp1 映射到 NI 时钟域
- **时序关系**：纯 SpikeGLX 数据链，无 BHV2 参与

### 节点 18（Raster 构建）— 最终交汇点：
- **来自 SpikeGLX 链**：UnitStrc.spiketime_ms（AP→KS4→SyncLine→NI 时钟域）
- **来自 BHV2 链**：trial_valid_idx（眼动验证）+ onset_time_ms（NIDQ photodiode 校准 - 5ms）
- **时序关系**：此处是整个流程中 SpikeGLX 和 BHV2 两条数据链的最终交汇，所有上游处理都在为这一步做准备

---

## ⚠️ 不确定项

- [ ] **NIDQ 数字通道位含义**：`load_NI_data.m:31-36` 中 `diff(digital0)` 提取变化点，`CodeVal` 是变化后的新值（完整数字字）。`Load_Data_function.m:54` 中 `bitand(DCode_NI.CodeVal,2)` 提取 bit 1，`bitand(DCode_NI.CodeVal,64)` 提取 bit 6，`bitand(DCode_NI.CodeVal,1)` 提取 bit 0。各 bit 的确切含义：bit 0 = sync 脉冲，bit 1 = trial start，bit 6 = onset。需要数据验证确认。
- [ ] **NIDQ 模拟通道 1 是否始终是 photodiode**：`load_NI_data.m:20` 直接取第一行。这取决于硬件连线配置，是否对所有实验 session 成立需确认。
- [ ] **LF 流 sync 通道号 385 是否对多探针配置也成立**：目前代码硬编码 `imec0`，如有 `imec1` 需确认其 LF sync 通道号。
- [ ] **fscale.mat 来源**：`PostProcess_function.m:27` 加载但未在任何已分析代码中找到生成逻辑。

---

## ❌ 与 Python 旧代码的差异

| 差异描述 | MATLAB 行为 | Python 旧代码行为 | 严重程度 |
|---------|------------|-----------------|---------|
| NIDQ 数据读取方式 | `memmapfile` 直接二进制读取，手动解析通道 | `si.read_spikeglx` + `get_traces(channel_ids=['nidq#XA0'])` | 实现差异 |
| NIDQ meta 解析 | 自写 `load_meta.m` 逐行 key=value 解析 | SpikeInterface 内部解析 + `neo_reader.signals_info_dict` 私有 API | 实现差异 |
| 数字通道定位 | 通过 `snsMnMaXaDw` 计算 `digCh = MN+MA+XA+1` | `get_traces(channel_ids=['nidq#XD0'])` | 实现差异 |
| IMEC sync 读取 | 从 `.lf.bin` 硬编码通道 385 读取 | `si.read_spikeglx(..., stream_name='imec0.lf-SYNC')` + `channel_ids=['imec0.lf#SY0']` | 实现差异 |
| IMEC sync 事件提取 | `diff>0`（仅上升沿）（`load_IMEC_data.m:11-13`） | `synchronizer.py:151` 用 `np.diff(imec_sync)` 提取变化点，`:199` 用 `np.diff(...) > 0` 提取上升沿。`data_loader.py:223-226` 负责加载原始 sync trace。功能对等。 | 实现差异 |
| AIN 重采样 | `resample(AIN, p, q)` → 1000 Hz（`load_NI_data.m:52-53`） | `synchronizer.py:479` 用 `signal.resample_poly(AIN, p, q)` 重采样到 1000 Hz，功能对等。 | 实现差异 |
| NIDQ 事件码提取逻辑 | `diff(digital0)` 取全量变化点 + 新值（`load_NI_data.m:31-36`） | `synchronizer.py:166` 用 `np.diff(nidq_digital)` 提取全量变化点；`:183,:199,:277,:302` 通过 `np.diff(CodeVal & bit_mask) > 0` 按 bit 提取事件。功能对等，但 Python 在 synchronizer 层直接做 bit 操作，而非像 MATLAB 先产出完整 DCode 再在 Load_Data_function 中按 bit 提取。 | 实现差异 |
| 预处理参数差异 | KS4 `nblocks=5`（`Analysis_Fast.ipynb`），无运动校正 | KS4 `nblocks=20`（`NPX_session_process.ipynb:cell-8452ac5d`），有 DREDge 运动校正（`cell-6a2379c6`） | ⚠️ 参数差异 |
| Bombcell 调用方式 | 直接调用 MATLAB Bombcell 库（`run_bc.m`） | 通过 `QualityController` 类经 `matlab.engine` 桥接调用（`NPX_session_process.ipynb:cell-668d73c6`） | 实现差异 |
| 预处理保存格式 | 保存为 binary（`Analysis_Fast.ipynb`） | 保存为 Zarr 格式（`NPX_session_process.ipynb:cell-0c5986aa`） | 实现差异 |
