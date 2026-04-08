# Step 4：MATLAB 预处理流程逐步解析

> 分析日期：2026-04-04
> 信息来源：仅 MATLAB 源码直接阅读（行号引用），整合 Step 1-3 已有分析
> 步骤编号：对应 `step2_input_consumption.md` 统一消费点总表 #0-#20

---

## 前言

本文档以 `step1_entry_structure.md` 的调用树为骨架，将 `step2_input_consumption.md` 的所有消费点和 `step3_output_analysis.md` 的所有输出点整合为每步骤的完整三元组（输入→处理→输出）。

**Pipeline 实际执行顺序**：

1. `Analysis_Fast.ipynb`（Python/SpikeInterface）— AP 预处理 + Kilosort4（步骤 #13，独立运行）
2. `gen_globaL_par.m` — 定义全局参数（一次性，非 per-session）
3. `Process_pipeline_2504.m:11-14` — per session 循环（共 23 个 session）：
   - `Load_Data_function(path)` — 步骤 #0-#12
   - `PostProcess_function_raw(path)` — 步骤 #14-#17
   - `PostProcess_function(path)` — 步骤 #18-#20

**本批次覆盖**：步骤 #0 — #6（Load_Data_function 前半部分：数据发现 + 加载 + 时钟对齐）

---

## 步骤 0：SpikeGLX 文件夹发现与环境初始化

**所在函数**：`Load_Data_function.m:Load_Data_function:1-9`
**在流程中的位置**：第 1 个主函数 / 子步骤 1

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `data_path` | `Process_pipeline_2504.m:12` 循环传入 | string（文件系统路径） | 指向一个 session 的数据根目录 |
| `NPX*` 目录 | 文件系统 `dir('NPX*')` | SpikeGLX 录制文件夹 | 命名约定：`NPX_{subject}{date}_exp_g{N}` |

### 处理

1. `:2` — `cd(data_path)` — 切换工作目录到 session 数据根目录
2. `:3` — `clear` — 清空函数局部工作区（⚠️ `data_path` 参数也被清除，后续依赖 `pwd`）
3. `:4` — `mkdir processed` — 创建 `processed/` 输出子目录（写操作 #2）
4. `:7` — `SGLX_Folder = dir('NPX*')` — 扫描当前目录下所有以 `NPX` 开头的子目录
5. `:8` — `session_name = SGLX_Folder(1).name` — 取第一个匹配结果的名称
6. `:9` — `g_number = session_name(end)` — 取文件名最后一个字符作为 SpikeGLX g 编号

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `session_name` | 步骤 #1, #4, #5 路径构造 | string | 如 `NPX_MD250723_exp_g10` |
| `g_number` | 步骤 #12 META 文件保存 | char（单字符） | 如 `'0'`；⚠️ 仅取最后 1 字符，多位数 g 编号会截断 |
| `processed/` 目录 | 后续所有写操作 | 目录 | 写操作 #2 |

### 质检节点

无。

### 注意事项

- ⚠️ **硬编码 `NPX*` 前缀**：SpikeGLX 文件夹必须以 `NPX` 开头（`:7`）
- ⚠️ **仅取第一个匹配**：`SGLX_Folder(1)`（`:8`），若目录下有多个 NPX* 文件夹将忽略其余
- ⚠️ **g_number 单字符截取**：`session_name(end)`（`:9`），g 编号 ≥ 10 时仅取末位
- ⚠️ **`clear` 清除输入参数**：`:3` 的 `clear` 会清除 `data_path`，但 `:2` 已执行 `cd`，后续用相对路径和 `pwd` 工作
- ⚠️ **硬编码 `imec0`**：后续路径构造（`:28`, `:30`）写死 `imec0`，不支持多探针

---

## 步骤 1：NIDQ 数据加载

**所在函数**：`Load_Data_function.m:10-11` → `load_NI_data.m:load_NI_data:1-55`（含 `load_meta.m:1-37`）
**在流程中的位置**：第 1 个主函数 / 子步骤 2

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `.nidq.meta` 文件 | 文件系统 | SpikeGLX 文本格式（key=value） | 消费字段：`fileSizeBytes`, `nSavedChans`, `niSampRate`, `niAiRangeMax`, `snsMnMaXaDw` |
| `.nidq.bin` 文件 | 文件系统 | int16 二进制 [nChan × nFileSamp] | 通道 1 = photodiode AIN，通道 digCh = 数字字 |
| `session_name` | 步骤 #0 | string | 用于构造文件路径 |

### 处理

**路径构造**（`Load_Data_function.m`）：

1. `:10` — `NIFileName = fullfile(session_name, sprintf('%s_t0.nidq', session_name))` — 构造 NIDQ 文件路径（不含扩展名）

**Meta 解析**（`load_meta.m`，首次调用——后续步骤 #4, #5 复用同一函数）：

2. `load_meta.m:3` — `textData = fileread(meta_file_name)` — 读取整个 .meta 文件为文本
3. `load_meta.m:4` — `lines = strsplit(textData, '\n')` — 按行分割
4. `load_meta.m:5-36` — 逐行循环：按 `=` 分割 key/value，自动类型推断（含小数点→`str2double`，纯整数→`str2num`，布尔→logical）
5. `load_meta.m:32-33` — 遇到 `~` 开头的行停止解析（SpikeGLX meta 的 section 分隔符）
6. `load_meta.m:35` — `metaData.(key) = value` — 动态字段赋值，输出为 struct

**文件尺寸计算**（`load_NI_data.m`）：

7. `:4` — `nFileBytes = NI_META.fileSizeBytes`
8. `:5` — `nChan = NI_META.nSavedChans`
9. `:6` — `nFileSamp = nFileBytes / (2 * nChan)` — 每个采样点 2 字节（int16）

**二进制数据加载**：

10. `:9` — `m = memmapfile(sprintf('%s.bin',NIFileName), 'Format', {'int16', [nChan, nFileSamp], 'x'}, 'Writable', false)` — 内存映射 .nidq.bin
11. `:10` — `NI_rawData = m.Data.x` — ⚠️ 访问 `.Data.x` 会将整个文件加载到内存

**模拟通道提取（Photodiode AIN）**：

12. `:12` — `fI2V = NI_META.niAiRangeMax / 32768` — int16→电压转换因子
13. `:20` — `AIN = double(NI_rawData(1,:)) * fI2V` — 第 1 行 = 模拟输入（photodiode），转换为电压

**数字通道提取（事件码）**：

14. `:13-16` — 解析 `snsMnMaXaDw` 为 `MN`, `MA`, `XA`, `DW`（4 种通道类型计数）
15. `:18` — `digCh = MN + MA + XA + 1` — 计算数字通道索引（跳过所有模拟通道）
16. `:30` — `digital0 = NI_rawData(digCh,:)` — 提取数字字通道
17. `:31` — `CodeAll = diff(digital0)` — 计算一阶差分，检测所有变化点
18. `:32` — `DCode.CodeLoc = find(CodeAll~=0)` — 所有变化点位置（⚠️ 包含上升和下降沿）
19. `:33` — `digital0(1)=[]` — 删除第一个元素以对齐 diff 输出
20. `:34` — `DCode.CodeVal = digital0(DCode.CodeLoc)` — 变化后的**新数字字值**（不是变化量）
21. `:35-36` — 前置哨兵：`CodeLoc = [nan, CodeLoc]`，`CodeVal = [0, CodeVal]`（初始状态为 0）

**时间转换与重采样**：

22. `:50` — `DCode.CodeTime = 1000 * DCode.CodeLoc / NI_META.niSampRate` — 采样点→毫秒
23. `:52` — `[p, q] = rat(1000 / NI_META.niSampRate)` — 计算有理数近似（目标 1000 Hz）
24. `:53` — `AIN = resample(AIN, p, q)` — 将 AIN 从 niSampRate 重采样到 1000 Hz

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `NI_META` | 步骤 #12 META 保存 | struct（全部 meta 键值对） | 含 niSampRate, niAiRangeMax 等 |
| `AIN` | 步骤 #10 Photodiode 校准 + 步骤 #12 META 保存 | double [1 × T_1000Hz] | 已重采样到 1000 Hz，单位：电压（V） |
| `DCode_NI` | 步骤 #6 时钟对齐 + 步骤 #7 trial 验证 + 步骤 #10 onset 检测 + 步骤 #12 META 保存 | struct {CodeLoc, CodeVal, CodeTime} | CodeTime 单位 ms；CodeVal 是变化后的绝对值 |

### 质检节点

无直接图表。`:7-8` fprintf 输出录制时长（秒/分）。`:42-46` fprintf 输出所有事件码及其出现次数。

### 注意事项

- ⚠️ **整文件加载到内存**：`:10` `NI_rawData = m.Data.x` 实际触发全量读取。NIDQ 文件通常较小（~100-500 MB），但不是 lazy 加载
- ⚠️ **硬编码通道 1 为 AIN**：`:20` 假设第一个模拟通道为 photodiode，取决于硬件连线配置
- ⚠️ **数字通道定位方式**：`:18` 通过 `MN+MA+XA+1` 计算，而非硬编码通道号——这是正确的参数化方式
- 代码注释 `:37-41` 提到 sync 码与 onset 码可能同时出现（如 65=64+1, 63=64-1），但当前版本选择不处理
- `:22-28` 被注释掉的旧代码仅提取上升沿（`CodeAll>0`），现版本 `:32` 提取所有变化（`CodeAll~=0`）并记录变化后的绝对值

---

## 步骤 2：BHV2 行为数据发现与解析

**所在函数**：`Load_Data_function.m:14-25`（含 `mlread.m:1-32` → `mlfileopen.m:1-15` → `mlbhv2.m:1-399`）
**在流程中的位置**：第 1 个主函数 / 子步骤 3

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `*.bhv2` 文件 | 文件系统 `dir('*bhv2')` | MonkeyLogic 自定义二进制格式 | BHV2 magic：前 21 字节 = `\x0d\x00...\x00IndexPosition` |
| 缓存文件 `processed/ML_*.mat`（可选） | 步骤 #2 前次运行的产出 | .mat v7 | 含 `trial_ML` 变量 |

### 处理

1. `:14` — `ML_FILE = dir('*bhv2')` — 扫描当前目录下所有 .bhv2 文件
2. `:15` — `ml_name = ML_FILE(1).name` — 取第一个匹配的文件名
3. `:18` — `trial_ML_name = fullfile('processed', sprintf('ML_%s.mat', ml_name(1:end-5)))` — 构造缓存路径（去掉 `.bhv2` 共 5 个字符）
4. `:19` — `file_exist = length(dir(trial_ML_name))` — 检查缓存是否存在
5. `:20-21` — **若缓存存在**：`load(trial_ML_name)` — 直接加载缓存的 `trial_ML`
6. `:23` — **若缓存不存在**：`trial_ML = mlread(ml_name)` — 调用 mlread 解析 BHV2
   - `mlread.m:22` → `mlfileopen(filename, 'r')`
   - `mlfileopen.m:8` → `mlbhv2(filepath)` — 创建 mlbhv2 读取器对象
   - `mlbhv2.m` 内部：读取二进制 BHV2 文件，解析 IndexPosition 表，逐 trial 反序列化
   - 输出：struct array，每个元素含 `BehavioralCodes`, `AnalogData`, `UserVars` 等字段
7. `:24` — `save(trial_ML_name, "trial_ML")` — 保存 .mat 缓存（写操作 #3）

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `trial_ML` | 步骤 #7 trial 验证、#8 数据集提取、#9 眼动验证、#16 字段清理、#17/#20 最终保存 | struct array [1 × n_trials] | 每元素含 BehavioralCodes, AnalogData, UserVars 等 |
| `ml_name` | 步骤 #3 文件名解析 + 步骤 #12 META 保存 | string | BHV2 文件名 |
| `processed/ML_*.mat` | 缓存供下次运行 + 步骤 #14 PostProcess_function_raw:9 加载 | .mat v7 | 写操作 #3 |

### 质检节点

无。

### 注意事项

- ⚠️ **仅取第一个 .bhv2**：`:15` `ML_FILE(1).name`，若目录下有多个 .bhv2 文件将忽略其余
- 缓存机制（`:19-25`）避免重复调用慢速的 mlbhv2 解析器
- `mlbhv2.m` 是 MonkeyLogic 官方提供的 MATLAB 类（399 行），处理 BHV2 自定义二进制格式
- BHV2 **不是** HDF5 格式，不能用 h5py 读取

---

## 步骤 3：BHV2 文件名解析

**所在函数**：`Load_Data_function.m:16` → `parsing_ML_name.m:parsing_ML_name:1-5`
**在流程中的位置**：第 1 个主函数 / 子步骤 4

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `ml_name` | 步骤 #2 | string | BHV2 文件名，格式如 `250723_MaoDan_xxx.bhv2` |

### 处理

1. `parsing_ML_name.m:2` — `split = find(ml_name=='_')` — 找到所有下划线位置
2. `parsing_ML_name.m:3` — `a = ml_name(1:split(1)-1)` — 第一个下划线之前 = 日期
3. `parsing_ML_name.m:4` — `b = ml_name(split(1)+1:split(2)-1)` — 第一个和第二个下划线之间 = 动物名

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `exp_day` | 步骤 #12 META 文件名和内容 | string | 如 `'250723'` |
| `exp_subject` | 步骤 #12 META 文件名和内容 | string | 如 `'MaoDan'`（原始名，非代号） |

### 质检节点

无。

### 注意事项

- 文件名格式约定：`{YYMMDD}_{SubjectName}_{其余}.bhv2`
- ⚠️ 与 `parse_name.m` 不同：`parsing_ML_name` 解析 BHV2 文件名，`parse_name` 解析 SpikeGLX 路径（`parse_name` 不在主流程中）
- `parsing_ML_name` 返回原始动物名（如 `MaoDan`），不做代号映射（代号映射仅在未被调用的 `parse_name.m` 中）

---

## 步骤 4：IMEC LF 同步脉冲提取

**所在函数**：`Load_Data_function.m:28-29` → `load_IMEC_data.m:load_IMEC_data:1-22`（含 `load_meta.m`）
**在流程中的位置**：第 1 个主函数 / 子步骤 5

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `.lf.meta` 文件 | 文件系统 | SpikeGLX 文本格式 | 消费字段：`fileSizeBytes`, `nSavedChans`, `imSampRate` |
| `.lf.bin` 文件 | 文件系统 | int16 二进制 [nChan × nFileSamp] | 通道 385 = sync 数字通道 |
| `session_name` | 步骤 #0 | string | 用于构造路径 |

### 处理

**路径构造**（`Load_Data_function.m`）：

1. `:28` — `ImecFileName = fullfile(session_name, sprintf('%s_imec0',session_name), sprintf('%s_t0.imec0.lf',session_name))` — 构造 IMEC LF 路径（⚠️ 硬编码 `imec0`）

**Meta 解析**（`load_IMEC_data.m`）：

2. `:2` — `META_DATA = load_meta(sprintf('%s.meta', NIFileName))` — 解析 .lf.meta（同步骤 #1 的 load_meta 逻辑）
3. `:3-5` — 计算 `nFileBytes`, `nChan`, `nFileSamp`

**二进制数据加载与 sync 提取**：

4. `:8` — `m = memmapfile(sprintf('%s.bin',NIFileName), ...)` — 内存映射 .lf.bin
5. `:9` — `digital0 = m.Data.x(385,:)` — ⚠️ 硬编码通道 385（384 数据 + 1 sync）
6. `:11` — `CodeAll = diff(digital0)` — 一阶差分
7. `:12` — `DCode.CodeLoc = find(CodeAll>0)` — **仅提取上升沿**（与步骤 #1 NIDQ 的 `CodeAll~=0` 不同！）
8. `:13` — `DCode.CodeVal = CodeAll(DCode.CodeLoc)` — 值为**变化量**（diff 值，非绝对值——与步骤 #1 NIDQ 也不同）

**时间转换**：

9. `:21` — `DCode.CodeTime = 1000 * DCode.CodeLoc / META_DATA.imSampRate` — 采样点→毫秒

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `IMEC_META` | 步骤 #12 META 保存 | struct（LF meta 全部键值对） | 含 imSampRate（~2500 Hz） |
| `DCode_IMEC` | 步骤 #6 时钟对齐 + 步骤 #12 META 保存 | struct {CodeLoc, CodeVal, CodeTime} | 仅含上升沿；CodeVal 是变化量（非绝对值） |

### 质检节点

`:6-7` 和 `:14-18` 有 `fprintf` 输出录制时长和事件统计。

### 注意事项

- ⚠️ **读 LF 不读 AP**：有意为之——LF 文件远小于 AP（~1/10 大小），但同样含 sync 通道。AP 的 meta 单独在步骤 #5 加载
- ⚠️ **硬编码通道 385**：`:9` 直接用 `m.Data.x(385,:)`。对 Neuropixels 1.0 LF 流正确（384 数据 + 1 sync），不适用于其他探针型号
- ⚠️ **硬编码 `imec0`**：`Load_Data_function.m:28` 路径中写死 `imec0`，不支持多探针
- ⚠️ **NIDQ vs IMEC 数字事件提取逻辑差异**：
  - NIDQ（步骤 #1）：`find(CodeAll~=0)` 提取所有变化 + CodeVal = 变化后的**绝对值**
  - IMEC（步骤 #4）：`find(CodeAll>0)` 仅提取**上升沿** + CodeVal = **变化量**（diff 值）
  - 此差异是有意的：NIDQ 数字字包含多路信号需要全量解析，IMEC sync 只需上升沿

---

## 步骤 5：IMEC AP 元信息加载

**所在函数**：`Load_Data_function.m:30-31`（含 `load_meta.m`）
**在流程中的位置**：第 1 个主函数 / 子步骤 6

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `.ap.meta` 文件 | 文件系统 | SpikeGLX 文本格式 | 核心消费字段：`imSampRate`（~30000 Hz） |
| `session_name` | 步骤 #0 | string | 用于构造路径 |

### 处理

1. `:30` — `ImecFileName = fullfile(session_name, sprintf('%s_imec0',session_name), sprintf('%s_t0.imec0.ap',session_name))` — 构造 AP 文件路径（⚠️ 硬编码 `imec0`）
2. `:31` — `IMEC_AP_META = load_meta(sprintf('%s.meta', ImecFileName))` — 解析 .ap.meta（复用步骤 #1 的 load_meta）

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `IMEC_AP_META` | 步骤 #12 META 保存 → 步骤 #15 KS4 输出加载（`imSampRate` 用于 spike time 转换） | struct（AP meta 全部键值对） | 关键字段：`imSampRate`（~30000 Hz） |

### 质检节点

无图表。但紧接其后（`:34-35`）创建诊断 figure：

```matlab
figure;
set(gcf,'Position',[100 80 1800 950])
```

此 figure 设置 3×6 subplot 布局（1800×950 像素），步骤 #6 至 #12 的所有诊断图均绘入此 figure。

### 注意事项

- 此步骤**仅加载 .ap.meta，不读取 .ap.bin**——AP bin 文件（可达数百 GB）由 `Analysis_Fast.ipynb`（步骤 #13）通过 SpikeInterface 处理
- ⚠️ **硬编码 `imec0`**：`:30` 路径中写死 `imec0`

---

## 步骤 6：IMEC↔NIDQ 时钟对齐

**所在函数**：`Load_Data_function.m:37` → `examine_and_fix_sync.m:examine_and_fix_sync:1-66`
**在流程中的位置**：第 1 个主函数 / 子步骤 7

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `DCode_NI` | 步骤 #1 | struct {CodeLoc, CodeVal, CodeTime} | 使用 CodeVal 的 bit 0（sync 脉冲上升沿） |
| `DCode_IMEC` | 步骤 #4 | struct {CodeLoc, CodeVal, CodeTime} | 使用 CodeVal==64 的脉冲（sync 上升沿变化量） |

### 处理

**NI 端 sync 脉冲提取**：

1. `:4` — `se = find(diff(bitand(DCode_NI.CodeVal,1))>0)` — 在 NI 数字字中提取 bit 0 上升沿位置（bitand 提取 bit 0，diff>0 找上升沿）
2. `:5` — `SyncLine.NI_time = DCode_NI.CodeTime(1+se)` — 取上升沿后一个位置的时间戳（+1 补偿 diff 偏移）

**IMEC 端 sync 脉冲提取**：

3. `:6` — `SyncLine.imec_time = DCode_IMEC.CodeTime(DCode_IMEC.CodeVal==64)` — 取 IMEC 中变化量==64 的事件（sync 脉冲上升沿）

**脉冲间隔计算**：

4. `:11` — `d1 = diff(SyncLine.imec_time)` — IMEC 端脉冲间隔序列
5. `:12` — `d1 = d1(2:end)` — 去掉第一个间隔（可能不稳定）
6. `:13-14` — 同理计算 `d2`（NI 端脉冲间隔，同样去掉首个）

**脉冲数量校验与修复**：

7. `:26` — 检查 `length(SyncLine.NI_time) ~= length(SyncLine.imec_time)`
8. `:27-28` — **若不匹配**：`warning('Sync Fail! Fixing...')` + `keyboard`（⚠️ 暂停执行等待人工干预）
9. `:31` — `index = find(d2 > 1200)` — 找到 NI 端间隔 >1200ms 的位置（预期 ~1000ms）
10. `:34-38` — 修复逻辑：在异常间隔位置插入两个相邻脉冲的中间值 `(NI_time(idx) + NI_time(idx+1)) / 2`
11. `:40-51` — 重新计算修复后的间隔并绘图验证
12. `:53-55` — **若匹配**：`fprintf('Sync Success!\n')`

**时钟漂移计算**：

13. `:57-60` — `terr(ii) = SyncLine.NI_time(ii) - SyncLine.imec_time(ii)` — 逐脉冲计算 NI 与 IMEC 的时间差

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `SyncLine` | 步骤 #12 META 保存 → 步骤 #15 KS4 spike time 对齐（interp1 映射） | struct {NI_time [1×N double ms], imec_time [1×N double ms]} | 配对的 sync 脉冲时间序列 |

### 质检节点

| 图表 | subplot 位置 | 来源行号 | 内容 | 检查要点 |
|------|-------------|---------|------|---------|
| IMEC 脉冲间隔 | (3,6,13) | `:16-18` | `d1 = diff(SyncLine.imec_time)` 折线图，ylim [950, 2000] | 间隔应稳定 ~1000 ms，无异常跳变 |
| NI 脉冲间隔 | (3,6,14) | `:19-21` | `d2 = diff(SyncLine.NI_time)` 折线图，ylim [950, 2000] | 同上 |
| NI-IMEC 时钟漂移 | (3,6,15) | `:61-65` | `terr = NI_time - imec_time` 折线图，ylim [-10, 10] | 漂移应缓慢线性变化，在 ±10 秒内 |
| 修复后间隔（条件性） | nexttile ×2 | `:44-51` | 修复后的 d1, d2（仅 sync 失败时绘制） | 验证插值修复效果 |

### 注意事项

- ⚠️ **`keyboard` 命令**：`:28` 在 sync 失败时暂停执行，需要人工在 MATLAB 命令行干预。自动化 pipeline 必须替换为异常处理
- ⚠️ **NI bit 0 vs IMEC val==64**：两端提取 sync 的方式不对称——NI 用 `bitand(CodeVal,1)` 提取 bit 0 的上升沿（因为 NIDQ 数字字包含多路信号：bit 0=sync, bit 1=trial start, bit 6=onset），IMEC 用 `CodeVal==64` 过滤（因为 IMEC sync 通道只有单一 sync 信号，上升沿 diff 值固定为 64）
- ⚠️ **修复阈值硬编码**：`:31` 的 1200ms 阈值硬编码（预期 sync 间隔 ~1000ms，>1200 表示丢脉冲）
- **SyncLine 不做拟合**：输出的 SyncLine 是配对的时间戳序列（非线性回归系数），下游步骤 #15 通过 `interp1` 做逐点线性插值映射

---

## 步骤 7：ML↔NI Trial 数量一致性验证

**所在函数**：`Load_Data_function.m:Load_Data_function:43-74`
**在流程中的位置**：第 1 个主函数 / 子步骤 8（🔴 SpikeGLX×BHV2 交汇节点）

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `trial_ML` | 步骤 #2 | struct array [1 × n_trials] | 使用 `.BehavioralCodes.CodeNumbers`（事件码==64 表示 onset，==32 表示 offset） |
| `DCode_NI` | 步骤 #1 | struct {CodeVal, CodeLoc, CodeTime} | 使用 `CodeVal` 的 bit 1（trial start）和 bit 6（onset） |

### 处理

**ML 端统计**：

1. `:43` — `onset_times = 0; offset_times = 0` — 初始化全局 onset/offset 计数器
2. `:45` — `onset_times_by_trial_ML = zeros([1, length(trial_ML)])` — 预分配每 trial onset 数
3. `:46-50` — 循环每个 trial：
   - `:47` — `onset_times_by_trial_ML(tt) = sum(trial_ML(tt).BehavioralCodes.CodeNumbers==64)` — 计数事件码==64 的 onset
   - `:48` — 累加到全局 `onset_times`
   - `:49` — 累加 `offset_times`（事件码==32）
4. `:51` — `fprintf` 输出 trial 总数、onset 总数、offset 总数

**NI 端统计**：

5. `:54` — `LOCS = find(diff(bitand(DCode_NI.CodeVal,2))>0)+1` — 提取 bit 1（值=2）上升沿位置 = trial start 位置
6. `:55` — `onset_times_by_trial_SGLX = zeros([1, length(LOCS)])` — 预分配每 trial onset 数
7. `:56-65` — 循环每个 trial（由 LOCS 界定的 trial 边界）：
   - `:57` — `LOC1 = LOCS(tt)` — 当前 trial 起始索引
   - `:58-62` — `LOC2` = 下一个 trial 起始索引（或序列末尾）
   - `:63` — `all_code_this_trial = DCode_NI.CodeVal(LOC1:LOC2)` — 截取当前 trial 的所有事件码
   - `:64` — `onset_times_by_trial_SGLX(tt) = length(find(diff(bitand(all_code_this_trial,64))>0))` — 计数 bit 6（值=64）上升沿 = onset 数

**交叉验证**：

8. `:71-72` — `if(max(onset_times_by_trial_ML - onset_times_by_trial_SGLX) > 0)` → `warning('Inconsistant Trial Number')`

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `onset_times_by_trial_ML` | 仅用于绘图验证 | double [1 × n_trials] | 每 trial 的 ML 端 onset 计数 |
| `onset_times_by_trial_SGLX` | 仅用于绘图验证 | double [1 × n_trials_NI] | 每 trial 的 NI 端 onset 计数 |
| `onset_times` | 步骤 #9 眼动验证（`:90`）预分配 | int（标量） | onset 总数 |

### 质检节点

| 图表 | subplot 位置 | 来源行号 | 内容 | 检查要点 |
|------|-------------|---------|------|---------|
| ML vs SGLX onset 散点图 | (3,6,1) | `:68-74` | `scatter(onset_times_by_trial_SGLX, onset_times_by_trial_ML)`，title 显示 MaxErr | 所有点应在对角线上（两端一致），MaxErr 应为 0 |

### 注意事项

- ⚠️ **bit 含义**：bit 1（值 2）= trial start，bit 6（值 64）= onset。这是 MonkeyLogic 通过 SpikeGLX 数字端口发送的事件码约定
- ⚠️ **trial 数量可能不一致**：ML 端 trial 数 `length(trial_ML)` 可能与 NI 端 trial 数 `length(LOCS)` 不同（如 NI 录制比 ML 早/晚启停）。代码仅 warning，不中断
- 交叉验证仅比较 onset 数量的**最大误差**，不做逐 onset 时间比对

---

## 步骤 8：数据集名称提取

**所在函数**：`Load_Data_function.m:Load_Data_function:77-85`
**在流程中的位置**：第 1 个主函数 / 子步骤 9

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `trial_ML` | 步骤 #2 | struct array | 使用 `.UserVars.DatasetName` |

### 处理

1. `:77-80` — 循环所有 trial，收集 `trial_ML(trial_idx).UserVars.DatasetName` 到 cell array `dataset_pool`
2. `:81` — `dataset_pool = unique(dataset_pool)` — 去重
3. `:82` — `dataset_pool = dataset_pool{1}` — ⚠️ 仅取第一个唯一数据集
4. `:83` — `[kk] = find(dataset_pool=='\')` — 找路径中的反斜杠分隔符
5. `:85` — `img_set_name = dataset_pool(kk(end)+1:end-4)` — 取最后一个反斜杠之后、去掉末尾 4 字符（`.bmp` 或 `.png` 扩展名）= 图片集名

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `dataset_pool` | 步骤 #9 眼动验证（`:102`）数据集匹配 | string（或 cell） | `:82` 取唯一后变为 string |
| `img_set_name` | 步骤 #12 META 文件名构造 | string | 如 `'ImageSet_v1'` |

### 质检节点

无。

### 注意事项

- ⚠️ **仅支持单数据集**：`:82` 取 `dataset_pool{1}`，若 session 包含多个数据集将忽略其余
- ⚠️ **Windows 路径反斜杠**：`:83` 用 `=='\''` 查找路径分隔符，仅适用于 Windows 风格路径
- ⚠️ **硬编码扩展名长度**：`:85` 的 `end-4` 假设图片文件扩展名为 4 字符（含 `.`，如 `.bmp`）

---

## 步骤 9：眼动验证（Eye Validation）

**所在函数**：`Load_Data_function.m:Load_Data_function:87-142`
**在流程中的位置**：第 1 个主函数 / 子步骤 10（🔴 SpikeGLX×BHV2 交汇节点）

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `trial_ML` | 步骤 #2 | struct array | 使用：`.BehavioralCodes`（code 64=onset）、`.AnalogData.Eye`（眼位 [T×2]）、`.AnalogData.SampleInterval`、`.VariableChanges.onset_time`（刺激呈现时长）、`.VariableChanges.fixation_window`（注视窗半径）、`.UserVars.Current_Image_Train` |
| `onset_times` | 步骤 #7 | int（标量） | onset 总数，用于预分配 |
| `dataset_pool` | 步骤 #8 | string | 用于数据集索引匹配 |

### 处理

**初始化**：

1. `:87` — `eye_thres = 0.999` — ⚠️ 硬编码注视比例阈值（99.9%）
2. `:88-89` — `valid_eye = 0; onset_marker = 0` — 计数器
3. `:90` — `trial_valid_idx = zeros([1, onset_times])` — 预分配逐 onset 有效标记
4. `:91` — `dataset_valid_idx = zeros([1, onset_times])` — 预分配逐 onset 数据集索引
5. `:93` — `eye_matrix = []` — 眼动数据矩阵（延迟分配）

**逐 trial、逐 onset 验证循环**（`:94-125`）：

6. `:94` — `for trial_idx = 1:length(trial_ML)` — 外层循环：遍历所有 trial
7. `:95-98` — 提取当前 trial 数据：`onset_duration`、`beh_code`、`beh_time`
8. `:99` — `onset_beh_location = find(beh_code==64)` — 找到本 trial 中所有 onset 事件的位置
9. `:100` — `onset_times_this_trial = length(onset_beh_location)` — 本 trial 的 onset 数
10. `:101` — `img_idx_now = trial_data.UserVars.Current_Image_Train(1:onset_times_this_trial)` — 每个 onset 对应的图片编号
11. `:102` — `dataset_idx = find(strcmp(trial_ML(trial_idx).UserVars.DatasetName, dataset_pool))` — 当前 trial 所属数据集索引
12. `:103` — `for onset_idx = 1:onset_times_this_trial` — 内层循环：遍历本 trial 的每个 onset
13. `:104` — `onset_marker = onset_marker + 1` — 全局 onset 计数器递增

**单个 onset 的眼动提取与验证**（`:105-123`）：

14. `:105` — `onset_start_to_end = (beh_time(onset_beh_location(onset_idx)) : beh_time(onset_beh_location(onset_idx))+onset_duration) ./ trial_data.AnalogData.SampleInterval` — 计算 onset 时间窗的采样索引（从 onset 到 onset+duration，按 BHV2 的 SampleInterval 换算）
15. `:106` — `onset_start_to_end = floor(onset_start_to_end)` — 取整
16. `:108` — `eye_data = trial_data.AnalogData.Eye(onset_start_to_end,:)` — 截取眼位数据 [T × 2]（X, Y）
17. `:109-111` — **延迟分配 `eye_matrix`**：首次遇到时创建 `zeros([2, onset_times, length(onset_start_to_end)])` — shape 为 [2(XY) × n_onsets × T]
18. `:112-114` — 将 eye_data 填入 eye_matrix 的对应位置
19. `:115` — `eye_dist = sqrt(eye_data(:,1).^2 + eye_data(:,2).^2)` — 计算每个时间点到注视点的欧式距离
20. `:116` — `eye_ratio = sum(eye_dist < trial_data.VariableChanges.fixation_window) / (onset_duration+1)` — 注视窗内的时间比例
21. `:118-122` — `if(eye_ratio > eye_thres)` — 若注视比例 > 99.9%：
    - `:120` — `trial_valid_idx(onset_marker) = img_idx_now(onset_idx)` — 记录有效 onset 对应的图片编号
    - `:121` — `dataset_valid_idx(onset_marker) = dataset_idx` — 记录数据集索引

**眼位密度图计算**（`:127-142`）：

22. `:127-128` — `binx = -8:0.5:8; biny = -8:0.5:8` — ⚠️ 硬编码 bin 范围 ±8 度，步长 0.5 度
23. `:130` — `plot_eye = squeeze(mean(eye_matrix,3))` — 每个 onset 在整个呈现时间内的平均眼位 [2 × n_onsets]
24. `:131-138` — 双重循环构建 density_plot 二维直方图

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `trial_valid_idx` | 步骤 #12 META 保存 → 步骤 #18 Raster 构建 | double [1 × onset_times] | 有效 onset 处填图片编号，无效处为 0 |
| `dataset_valid_idx` | 步骤 #10 Photodiode 校准（排除无效 trial）+ 步骤 #12 META 保存 | double [1 × onset_times] | 有效 onset 处填数据集索引，无效处为 0 |
| `eye_matrix` | 步骤 #12 META 保存 | double [2 × onset_times × T] | 完整眼动矩阵（含无效 trial） |

### 质检节点

| 图表 | subplot 位置 | 来源行号 | 内容 | 检查要点 |
|------|-------------|---------|------|---------|
| 眼位密度热图 | (3,6,12) | `:139-142` | `imagesc(binx, biny, log10(density_plot))` | 应集中在中心（注视点），无系统性偏移 |

### 注意事项

- ⚠️ **硬编码 `eye_thres = 0.999`**：99.9% 的注视比例阈值非常严格
- ⚠️ **硬编码 bin 范围**：`:127-128` 的 ±8 度范围和 0.5 度步长
- ⚠️ **`try` 无 `catch`**：`:107-123` 用 `try...end` 包裹眼动提取（无 catch），若 `onset_start_to_end` 超出 `AnalogData.Eye` 范围则静默跳过该 onset
- ⚠️ **eye_matrix 延迟分配**：`:109-111` 首次分配时 `T` 维度固定为第一个有效 onset 的长度，若后续 onset 的 `onset_start_to_end` 长度不同会越界
- 眼位密度图使用 log10 刻度（`:140`），零计数 bin 将显示为 -Inf

---

## 步骤 10：Photodiode Onset 时间校准

**所在函数**：`Load_Data_function.m:Load_Data_function:144-258`
**在流程中的位置**：第 1 个主函数 / 子步骤 11（🔴 SpikeGLX×BHV2 交汇节点——间接）

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `DCode_NI` | 步骤 #1 | struct | 使用 `CodeVal` 的 bit 6（onset 事件位置）和 `CodeTime`（ms） |
| `AIN` | 步骤 #1 | double [1 × T_1000Hz] | Photodiode 模拟信号（1000 Hz） |
| `dataset_valid_idx` | 步骤 #9 | double [1 × onset_times] | 用于排除非注视 trial（`:232`, `:239`） |
| `sign_array` | 本步骤内部计算 | double [1 × onset_times] | 极性校正标记 |

### 处理

**粗定位——数字 onset 位置提取**：

1. `:145-147` — 硬编码参数：`before_onset_measure=10`（前10ms）、`after_onset_measure=50`（后50ms）、`after_onset_stats=100`（后100ms）
2. `:148` — `onset_LOC = find(diff(bitand(DCode_NI.CodeVal,64))>0)+1` — 提取 bit 6（值 64）上升沿 = 所有 onset 位置
3. `:149` — `onset_times = length(onset_LOC)` — onset 总数（⚠️ 覆盖步骤 #7 的同名变量）
4. `:150` — `po_dis = zeros([onset_times, 1+before_onset_measure+after_onset_stats])` — 预分配 photodiode 信号矩阵
5. `:151` — `onset_time_ms = zeros([1, onset_times])` — 预分配 onset 时间数组

**逐 onset 粗定位**（`:152-157`）：

6. `:153` — `onset_time_ms(tt) = floor(DCode_NI.CodeTime(onset_LOC(tt)))` — 数字事件码时间→ms（取整）
7. `:154-155` — 计算 AIN 截取窗口：`onset_time_ms(tt) ± [before, after_stats]`
8. `:156` — `po_dis(tt,:) = zscore(AIN(start_get_time:end_get_time))` — 截取并 z-score 归一化

**极性检测与校正**（`:166-192`）：

9. `:166` — `diff_abs_data = abs(diff(po_dis'))` — 信号一阶差分绝对值
10. `:167` — `diff_data = diff(po_dis')` — 信号一阶差分（保留符号）
11. `:184-192` — 循环每个 trial：
    - `:185` — `[val_array(tt), time_array(tt)] = max(diff_abs_data(:,tt))` — 找最大变化点
    - `:186-188` — `if(diff_data(time_array(tt),tt)<0)` → `po_dis(tt,:) = -po_dis(tt,:)` — 若变化为下降方向则反转信号
    - `:188-190` — 记录 `sign_array`：+1 或 -1

**阈值计算**（`:201-203`）：

12. `:201` — `baseline = mean(mean(po_dis(:,1:before_onset_measure)))` — onset 前 10ms 的平均值
13. `:202` — `hignline = mean(mean(po_dis(:, before_onset_measure+after_onset_measure+[1:20])))` — onset 后 60-80ms（10+50+[1:20]）的平均值
14. `:203` — `thres = 0.1*baseline + 0.9*hignline` — 加权阈值（90% 响应 + 10% 基线）

**精校准——逐 trial 阈值穿越检测**（`:210-214`）：

15. `:210` — `onset_latency = zeros([1, size(po_dis,1)])` — 预分配 onset 延迟
16. `:212` — `onset_latency(tt) = find(po_dis(tt,:)>thres, 1) - before_onset_measure` — 找 photodiode 信号首次超过阈值的时间点 - 基线长度 = 相对于数字 onset 的延迟（ms）
17. `:213` — `onset_time_ms(tt) = onset_time_ms(tt) + onset_latency(tt)` — 将延迟加入 onset 时间 = 校准后 onset

**校准验证**（`:219-241`）：

18. `:220-225` — 使用校准后的 `onset_time_ms` 重新截取 AIN 信号 → `po_dis`（重新 zscore + 极性校正）
19. `:229-241` — 排除非注视 trial（`dataset_valid_idx==0`）后重新截取

**每图片 trial 统计**（`:245-258`）：

20. `:245` — `dataset_idx = 1` — ⚠️ 硬编码仅统计第一个数据集
21. `:247` — `img_idx = dataset_valid_idx==dataset_idx` — 属于该数据集的 onset 掩码
22. `:248` — `valid_onset = trial_valid_idx(img_idx)` — 有效 onset 的图片编号
23. `:250` — `img_size = max(valid_onset)` — 图片总数（取最大图片编号）
24. `:251-253` — 统计每张图片的有效 trial 数 `onset_t(img)`

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `onset_time_ms` | 步骤 #11（-5ms 校正）→ 步骤 #12 META 保存 → 步骤 #18 Raster 构建 | double [1 × onset_times] | 校准后的 onset 时间（NI 时钟域，ms） |
| `img_size` | 步骤 #12 META 保存 → 步骤 #18-#19 | int（标量） | 图片集中的图片总数 |

### 质检节点

| 图表 | subplot 位置 | 来源行号 | 内容 | 检查要点 |
|------|-------------|---------|------|---------|
| 原始 photodiode 热图 | (3,6,2) | `:159-163` | `imagesc(po_dis)`，时间×trial | 所有 trial 应在 onset 附近有明显响应 |
| 差分信号热图 | (3,6,3) | `:169-173` | `diff(po_dis')` | 变化点应对齐 |
| 差分绝对值热图 | (3,6,4) | `:175-179` | `abs(diff(po_dis'))` | 极性无关的变化幅度 |
| 极性校正后热图 | (3,6,5) | `:194-198` | 校正后 `po_dis` | 所有 trial 应统一方向 |
| 校准前均值±std | (3,6,7) | `:205-208` | `shadedErrorBar` + `yline(thres)` | 阈值线位置合理 |
| 延迟分布直方图 | (3,6,10) | `:215-217` | `hist(onset_latency,20)` + min/max xline | 延迟分布应集中，范围合理（如 5-20ms） |
| 校准后均值±std | (3,6,8) | `:219-227` | `shadedErrorBar` | onset 应在 time=0 处更尖锐对齐 |
| 排除非注视后均值±std | (3,6,9) | `:229-241` | 仅含 valid trial | 质量应优于校准前 |
| 每图片 trial 数分布 | (3,6,11) | `:246-258` | `plot(1:img_size, onset_t)` | 各图片 trial 数应大致均匀 |

### 注意事项

- ⚠️ **硬编码参数**：`before_onset_measure=10`、`after_onset_measure=50`、`after_onset_stats=100`（`:145-147`）
- ⚠️ **`dataset_idx = 1` 硬编码**：`:245` 仅统计第一个数据集的每图片 trial 数
- ⚠️ **阈值算法**：`:203` 的 `0.1*baseline + 0.9*hignline` 是加权阈值，权重硬编码
- ⚠️ **`onset_times` 被覆盖**：`:149` 重新计算 onset_times = 从 NI 数字事件码提取的 onset 数量，可能与步骤 #7 的 ML 端计数不同
- `shadedErrorBar` 是第三方绘图函数（非 MATLAB 内置）
- 校准算法本质：数字 onset 给出粗定位（±0 ms），photodiode 阈值穿越给出精修（+latency ms）

---

## 步骤 11：显示器延迟校正（-5ms）

**所在函数**：`Load_Data_function.m:Load_Data_function:263`
**在流程中的位置**：第 1 个主函数 / 子步骤 12

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `onset_time_ms` | 步骤 #10 | double [1 × onset_times] | 校准后 onset 时间（ms） |

### 处理

1. `:263` — `onset_time_ms = onset_time_ms - 5;` — 减去 5ms 显示器延迟

代码注释：`% fix monitor time err in 60Hz`

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `onset_time_ms` | 步骤 #12 META 保存 | double [1 × onset_times] | 已含 -5ms 校正 |

### 质检节点

无。

### 注意事项

- ⚠️ **硬编码 -5ms**：针对 60Hz 显示器的延迟补偿。物理依据：60Hz 刷新周期 ~16.67ms，photodiode 检测到的 onset 可能比实际像素变化晚约半帧。注释称是"修正 60Hz 显示器时间误差"
- 此校正发生在 photodiode 校准之后、META 保存之前
- 对不同刷新率的显示器（如 120Hz），此硬编码值不正确

---

## 步骤 12：诊断图保存与 META 文件输出

**所在函数**：`Load_Data_function.m:Load_Data_function:260-265`
**在流程中的位置**：第 1 个主函数 / 子步骤 13（Load_Data_function 的最终输出）

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| 当前 figure 句柄 `gcf` | 步骤 #6-#10 累积绘制 | MATLAB figure（3×6 subplot） | 含 14 个 subplot |
| `exp_day` | 步骤 #3 | string | |
| `exp_subject` | 步骤 #3 | string | |
| `img_set_name` | 步骤 #8 | string | |
| `eye_matrix` | 步骤 #9 | double [2 × onset_times × T] | |
| `ml_name` | 步骤 #2 | string | |
| `trial_valid_idx` | 步骤 #9 | double [1 × onset_times] | |
| `dataset_valid_idx` | 步骤 #9 | double [1 × onset_times] | |
| `onset_time_ms` | 步骤 #11 | double [1 × onset_times] | 已含 -5ms 校正 |
| `NI_META` | 步骤 #1 | struct | |
| `AIN` | 步骤 #1 | double [1 × T_1000Hz] | |
| `DCode_NI` | 步骤 #1 | struct | |
| `IMEC_META` | 步骤 #4 | struct | |
| `DCode_IMEC` | 步骤 #4 | struct | |
| `SyncLine` | 步骤 #6 | struct | |
| `IMEC_AP_META` | 步骤 #5 | struct | |
| `img_size` | 步骤 #10 | int | |
| `g_number` | 步骤 #0 | char | |

### 处理

1. `:242` — `sgtitle(pwd)` — 设置 figure 全局标题为当前工作目录路径
2. `:260` — `saveas(gcf, 'processed\DataCheck')` — 保存为 .fig 格式（写操作 #4）
3. `:261` — `saveas(gcf, 'processed\DataCheck.png')` — 保存为 .png 格式（写操作 #5）
4. `:262` — `save_name = fullfile('processed', sprintf('META_%s_%s_%s.mat', exp_day, exp_subject, img_set_name))` — 构造 META 文件名
5. `:263` — `onset_time_ms = onset_time_ms - 5;` — -5ms 校正（步骤 #11，已列为独立步骤）
6. `:265` — `save(save_name, "eye_matrix", "ml_name", "trial_valid_idx", "dataset_valid_idx", "onset_time_ms", "NI_META", "AIN", "DCode_NI", "IMEC_META", "DCode_IMEC", "SyncLine", "IMEC_AP_META", "img_size", "g_number", "exp_subject", "exp_day")` — 保存 META 文件（写操作 #6）

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `processed/DataCheck.fig` | 人工查看 | .fig（MATLAB 可交互 figure） | 写操作 #4 |
| `processed/DataCheck.png` | 人工查看 | .png | 写操作 #5 |
| `processed/META_{exp_day}_{exp_subject}_{img_set_name}.mat` | `PostProcess_function_raw.m:6-7`（步骤 #14） | .mat v7 | 写操作 #6；包含 17 个变量 |

### 质检节点

`processed/DataCheck.fig` 和 `processed/DataCheck.png` 本身就是质检产物，包含步骤 #6-#10 的全部 14 个诊断 subplot。

**Figure 布局总表**（供参考）：

| subplot | 步骤 | 内容 |
|---------|------|------|
| (3,6,1) | #7 | ML vs SGLX onset 散点图 |
| (3,6,2) | #10 | 原始 photodiode 热图 |
| (3,6,3) | #10 | 差分信号热图 |
| (3,6,4) | #10 | 差分绝对值热图 |
| (3,6,5) | #10 | 极性校正后热图 |
| (3,6,6) | — | 未使用 |
| (3,6,7) | #10 | 校准前均值±std |
| (3,6,8) | #10 | 校准后均值±std |
| (3,6,9) | #10 | 排除非注视后均值±std |
| (3,6,10) | #10 | 延迟分布直方图 |
| (3,6,11) | #10 | 每图片 trial 数 |
| (3,6,12) | #9 | 眼位密度热图 |
| (3,6,13) | #6 | IMEC 脉冲间隔 |
| (3,6,14) | #6 | NI 脉冲间隔 |
| (3,6,15) | #6 | NI-IMEC 时钟漂移 |
| (3,6,16-18) | — | 未使用 |

### 注意事项

- META 文件是整个 `Load_Data_function` 到 `PostProcess_function_raw` 的核心中间产物
- META 文件名格式：`META_{日期}_{动物名}_{图片集名}.mat`
- `:265` 的 save 使用默认 .mat v7 格式（非 v7.3），因此单变量不能超过 2GB（`AIN` 和 `eye_matrix` 通常远小于此）
- 全局标题 `sgtitle(pwd)` 用于标识诊断图对应的 session

---

## 步骤 13：AP 预处理 + Kilosort4 Spike Sorting

**所在函数**：`Analysis_Fast.ipynb:cell-0` + `cell-1`（Python/SpikeInterface，独立于 MATLAB 主流程）
**在流程中的位置**：在 MATLAB 主流程之前单独运行（步骤 0 之前）

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `.ap.bin` + `.ap.meta` | 文件系统 | SpikeGLX AP 数据 | 全部 384 通道 |
| SpikeGLX 文件夹 | 硬编码路径 | 目录 | `cell-0`: `spikeglx_folder = 'NPX_MD250723_exp_g10'` |

### 处理

**预处理链**（`cell-0`）：

1. `cell-0` — `raw_rec = si.read_spikeglx(spikeglx_folder, stream_name='imec0.ap', load_sync_channel=False)` — 加载 AP 数据（⚠️ 硬编码 `imec0.ap`）
2. `cell-0` — `rec3 = si.highpass_filter(recording=raw_rec, freq_min=300.)` — 高通滤波 300 Hz
3. `cell-0` — `bad_channel_ids, channel_labels = si.detect_bad_channels(rec3)` — 坏道检测
4. `cell-0` — `rec3 = rec3.remove_channels(bad_channel_ids)` — 剔除坏道
5. `cell-0` — `rec3 = si.phase_shift(rec3)` — ADC 时序校正（⚠️ 在 highpass_filter 之后，非推荐顺序）
6. `cell-0` — `rec3 = si.common_reference(rec3, operator="median", reference="global")` — 全局中位数 CMR

**保存预处理结果**（`cell-1`）：

7. `cell-1` — `job_kwargs = dict(n_jobs=18, chunk_duration='4s', progress_bar=True)` — 并行参数
8. `cell-1` — `corrected_rec = rec3.save(folder='./KS_TEMP2', format='binary', **job_kwargs)` — 保存为 binary 格式（写操作 #12）

**Kilosort4 排序**（`cell-1`）：

9. `cell-1` — `sorting_KS4 = run_sorter(sorter_name="kilosort4", recording=corrected_rec, folder="./kilosort_def_5block_97", nblocks=5, Th_learned=7)` — 运行 KS4（写操作 #13）

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `./KS_TEMP2/` | KS4 内部读取（通过 `corrected_rec`） | binary 格式（traces_cached_seg0.raw + binary.json） | 写操作 #12；可达数百 GB |
| `./kilosort_def_5block_97/sorter_output/` | 步骤 #14 Bombcell（`run_bc.m:3`）+ 步骤 #15 KS4 加载（`load_KS4_output.m`） | .npy + .tsv | 写操作 #13；含 spike_times/spike_templates/templates/spike_positions/amplitudes.npy + cluster_KSLabel.tsv |

### 质检节点

无诊断图输出。`cell-1` 的 progress_bar 输出显示处理进度。

### 注意事项

- ⚠️ **预处理顺序问题**：`highpass_filter` 在 `phase_shift` 之前。推荐顺序是 phase_shift 应在滤波之前（CLAUDE.md 已标注）
- ⚠️ **无运动校正**：MATLAB 版未调用 DREDge（Python 旧代码 `NPX_session_process.ipynb` 有此步骤）
- ⚠️ **硬编码参数**：`nblocks=5`（Python 旧代码使用 `nblocks=20`）、`Th_learned=7`、`n_jobs=18`、`chunk_duration='4s'`
- ⚠️ **硬编码路径**：`spikeglx_folder`、`./KS_TEMP2`、`./kilosort_def_5block_97` 全部硬编码
- ⚠️ **硬编码 `imec0.ap`**：不支持多探针
- `KS_TEMP2` 目录在整个流程中无清理逻辑

---

## 步骤 14：Bombcell 质控

**所在函数**：`PostProcess_function_raw.m:PostProcess_function_raw:5-11` → `run_bc.m:run_bc:1-26`
**在流程中的位置**：第 2 个主函数 / 子步骤 1

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `processed/META_*.mat` | 步骤 #12 | .mat v7 | `:5-7` 加载全部变量到工作区 + `meta_data` struct |
| `processed/ML_*.mat` | 步骤 #2 | .mat v7 | `:8-9` 加载 `trial_ML` |
| KS4 输出目录 | 步骤 #13 | `./kilosort_def_5block_97/sorter_output/` | `run_bc.m:3` 硬编码路径 |
| `.ap.bin` + `.ap.meta` | 文件系统 | SpikeGLX AP 原始数据 | `run_bc.m:5-6` 通过 dir 扫描定位 |

### 处理

**META 与 BHV2 加载**（`PostProcess_function_raw.m`）：

1. `:5` — `meta_file = dir('processed/META*')` — 查找 META 文件
2. `:6` — `load(fullfile(pwd,'processed',meta_file(1).name))` — 加载 META 全部变量到工作区（SyncLine, IMEC_AP_META 等）
3. `:7` — `meta_data = load(...)` — 同一文件再次加载为 struct（用于后续保存）
4. `:8-9` — `trial_ML = load(fullfile('processed',ML_FILE(1).name)).trial_ML` — 加载 BHV2 缓存

**Bombcell 运行**（`run_bc.m`）：

5. `run_bc.m:2` — `npx_data = dir('NPX_*')` — 发现 SpikeGLX 文件夹
6. `run_bc.m:3` — `ephysKilosortPath = fullfile(data_path, 'kilosort_def_5block_97/sorter_output')` — ⚠️ 硬编码 KS4 输出路径
7. `run_bc.m:4` — `npx_probe_data = dir(fullfile(data_path, npx_data.name, "*imec0"))` — ⚠️ 硬编码 `imec0`
8. `run_bc.m:5-6` — 通过 dir 扫描定位 `*ap*.*bin` 和 `*ap*.*meta` 文件
9. `run_bc.m:7-8` — `savePath = fullfile(data_path, "processed", "BC"); mkdir(savePath)` — 创建 BC 输出目录（写操作 #7）
10. `run_bc.m:9-11` — 设置 Bombcell 参数：`decompressDataLocal=''`、`gain_to_uV=NaN`、`kilosortVersion=4`
11. `run_bc.m:15-16` — `bc.load.loadEphysData(ephysKilosortPath, savePath)` — 加载 KS4 输出到 Bombcell
12. `run_bc.m:19` — `bc.dcomp.manageDataCompression(ephysRawDir, decompressDataLocal)` — 处理数据压缩
13. `run_bc.m:21` — `param = bc.qm.qualityParamValues(ephysMetaDir, rawFile, ephysKilosortPath, gain_to_uV, kilosortVersion)` — 获取质量指标参数
14. `run_bc.m:24-25` — `[qMetric, unitType] = bc.qm.runAllQualityMetrics(param, spikeTimes_samples, spikeTemplates, templateWaveforms, templateAmplitudes, pcFeatures, pcFeatureIdx, channelPositions, savePath)` — 计算全部质量指标

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `qMetric` | 步骤 #17 GoodUnitRaw 保存 → 步骤 #19 统计筛选 | matrix [n_units × n_metrics] | Bombcell 质量指标矩阵 |
| `unitType` | 步骤 #17 GoodUnitRaw 保存 → 步骤 #19 统计筛选（`unitType~=0`） | vector [1 × n_units] | 0=noise，非 0=有效单元 |
| `processed/BC/` 目录 | 步骤 #19 波形模板读取 | .npy + Bombcell 内部文件 | 写操作 #7, #8；含 `templates._bc_rawWaveforms.npy` |
| Bombcell figure(8) | 步骤 #17 中保存为 BC.png | MATLAB figure 句柄 | Bombcell 库内部创建 |

### 质检节点

Bombcell 库内部生成 figure(8)（质控诊断图），在步骤 #17 中保存。

### 注意事项

- ⚠️ **硬编码路径**：`run_bc.m:3` 的 `kilosort_def_5block_97/sorter_output`
- ⚠️ **硬编码 `imec0`**：`run_bc.m:4`
- ⚠️ **`gain_to_uV = NaN`**：`run_bc.m:10`，由 Bombcell 内部从 meta 读取实际增益
- Bombcell 是外部 MATLAB 库，内部行为不受本代码控制

---

## 步骤 15：KS4 输出加载与 IMEC→NI 时钟对齐

**所在函数**：`PostProcess_function_raw.m:12` → `load_KS4_output.m:load_KS4_output:1-32`
**在流程中的位置**：第 2 个主函数 / 子步骤 2（🔴 关键时钟转换节点）

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| KS4 `.npy` 文件 | 步骤 #13 | NumPy binary | spike_times, spike_templates, templates, spike_positions, amplitudes |
| `cluster_KSLabel.tsv` | 步骤 #13 | TSV 文本 | 列：cluster_id, KSLabel, ... |
| `IMEC_AP_META` | 步骤 #14 加载的 META | struct | 使用 `imSampRate`（~30000 Hz） |
| `SyncLine` | 步骤 #14 加载的 META | struct {NI_time, imec_time} | 用于 interp1 时钟映射 |

### 处理

**加载 KS4 输出**：

1. `load_KS4_output.m:2` — `loading_data = {'spike_times','spike_templates','templates','spike_positions','amplitudes'}` — 待加载的 5 个 npy 文件列表
2. `:3-5` — 循环 `eval(sprintf(...readNPY...))` — 逐个用 `readNPY` 加载（⚠️ 使用 `eval` 动态赋值）

**spike time 时钟转换**：

3. `:7` — `spike_times = 1000 * double(spike_times) / IMEC_AP_META.imSampRate` — sample→ms（IMEC 时钟域）
4. `:8` — `sync_spike_times = interp1(SyncLine.imec_time, SyncLine.NI_time, spike_times, 'linear', 'extrap')` — 通过 SyncLine 配对时间戳做线性插值，将 spike time 从 IMEC 时钟域映射到 NI 时钟域

**加载 cluster 标签**：

5. `:10` — `spike_templates = spike_templates + 1` — 0-indexed → 1-indexed（MATLAB 约定）
6. `:12-15` — 读取 `cluster_KSLabel.tsv`（fopen → fgetl 跳过 header → textscan 解析）

**组装 UnitStrc**：

7. `:17-20` — 定义 `example_unit` 模板 struct：`{waveform, spiketime_ms, spikepos, amplitudes}`
8. `:21` — `strc_unit = repmat(example_unit, [1, max(spike_templates)])` — 预分配
9. `:23-30` — 循环每个 unit（`spike_idx = 1:max(spike_templates)`）：
   - `:24` — `waveform = squeeze(templates(spike_idx,:,:))` — 该 unit 的模板波形 [T × 384]
   - `:25` — `spiketime_ms = sync_spike_times(spike_templates==spike_idx)` — 该 unit 的 spike 时间（**已对齐到 NI 时钟**）
   - `:26` — `spikepos = mean(spike_positions(spike_templates==spike_idx,:))` — 该 unit 的平均空间位置
   - `:27` — `amplitudes = amplitudes(spike_templates==spike_idx)` — 该 unit 的振幅序列

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `UnitStrc` | 步骤 #17 GoodUnitRaw 保存 → 步骤 #18-#19 Raster/筛选 | struct array [1 × n_units] | 每元素：{waveform [T×384], spiketime_ms [1×N_spikes], spikepos [1×2], amplitudes [1×N_spikes]}；**spiketime_ms 已在 NI 时钟域** |

### 质检节点

无。`:29` fprintf 输出进度（当前 unit / 总 unit 数）。

### 注意事项

- ⚠️ **硬编码 KS4 路径**：`PostProcess_function_raw.m:12` 的 `'./kilosort_def_5block_97/sorter_output'`
- ⚠️ **`eval` 使用**：`:5` 用 eval 动态创建变量，不推荐但功能正确
- ⚠️ **`interp1` 外推**：`:8` 使用 `'extrap'` 选项，对超出 SyncLine 范围的 spike time 做线性外推（可能引入误差）
- **关键时钟转换**：这是 spike time 从 IMEC 采样域到 NI 毫秒域的唯一转换点。后续所有 spike time 均在 NI 时钟域，可直接与 `onset_time_ms`（也在 NI 时钟域）对齐

---

## 步骤 16：trial_ML 字段清理

**所在函数**：`PostProcess_function_raw.m:PostProcess_function_raw:14-17`
**在流程中的位置**：第 2 个主函数 / 子步骤 3

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `trial_ML` | 步骤 #14 加载的 ML_*.mat | struct array | 使用 `.AnalogData.Mouse` 和 `.AnalogData.KeyInput` |

### 处理

1. `:14-17` — 循环所有 trial：
   - `:15` — `trial_ML(trial_idx).AnalogData.Mouse = []` — 清空鼠标数据
   - `:16` — `trial_ML(trial_idx).AnalogData.KeyInput = []` — 清空键盘输入数据

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `trial_ML`（已清理） | 步骤 #17 GoodUnitRaw 保存 → 步骤 #20 GoodUnit 保存 | struct array | Mouse 和 KeyInput 字段已置空 |

### 质检节点

无。

### 注意事项

- 目的：减小保存文件体积，Mouse 和 KeyInput 数据在后续分析中不使用
- 不删除字段本身（仍存在但为空数组），保持 struct 结构一致性

---

## 步骤 17：Bombcell 诊断图保存 + GoodUnitRaw 文件输出

**所在函数**：`PostProcess_function_raw.m:PostProcess_function_raw:19-23`
**在流程中的位置**：第 2 个主函数 / 子步骤 4（PostProcess_function_raw 的最终输出）

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| Bombcell figure(8) | 步骤 #14 Bombcell 库内部创建 | MATLAB figure | 图表内容由 Bombcell 控制 |
| `UnitStrc` | 步骤 #15 | struct array [1 × n_units] | 含已对齐的 spiketime_ms |
| `trial_ML` | 步骤 #16（已清理） | struct array | Mouse/KeyInput 已清空 |
| `meta_data` | 步骤 #14 加载 | struct | META_*.mat 完整内容 |
| `qMetric` | 步骤 #14 | matrix | Bombcell 质量指标 |
| `unitType` | 步骤 #14 | vector | Bombcell 单元类型 |
| `meta_file` | 步骤 #14 `:5` | dir struct | 用于构造输出文件名 |

### 处理

1. `:19` — `drawnow` — 强制刷新所有 figure 渲染
2. `:20` — `figure(8)` — 切换到 Bombcell 创建的 figure 8（⚠️ 依赖 Bombcell 内部创建 figure 8）
3. `:21` — `saveas(gca, fullfile("processed/", 'BC.png'))` — 保存为 PNG（写操作 #9）
4. `:22` — `file_name_LOCAL = fullfile('processed', sprintf('GoodUnitRaw_%s_g%s.mat', meta_file(1).name(6:end-4), meta_data.g_number))` — 构造文件名（去掉 META_ 前缀的 5 个字符和 .mat 后缀的 4 个字符）
5. `:23` — `save(file_name_LOCAL, "UnitStrc", "trial_ML", 'meta_data', 'qMetric', 'unitType', '-v7.3')` — 保存为 .mat v7.3（HDF5 格式，支持 >2GB）（写操作 #10）

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `processed/BC.png` | 人工查看 | .png | 写操作 #9；Bombcell 诊断图 |
| `processed/GoodUnitRaw_{name}_g{N}.mat` | `PostProcess_function.m:6-7`（步骤 #18） | .mat v7.3 | 写操作 #10；含 UnitStrc, trial_ML, meta_data, qMetric, unitType |

### 质检节点

| 图表 | 保存位置 | 来源 | 内容 |
|------|---------|------|------|
| Bombcell 诊断图 | `processed/BC.png` | Bombcell 库内部 figure(8) | 质量指标可视化（具体内容由 Bombcell 版本决定） |

### 注意事项

- ⚠️ **figure(8) 硬编码**：`:20` 假设 Bombcell 创建的是 figure 8，可能因 Bombcell 版本变化而失效
- ⚠️ **文件名构造逻辑**：`:22` 使用 `meta_file(1).name(6:end-4)` — 假设 META 文件名格式为 `META_{rest}.mat`，取 `{rest}` 部分
- `-v7.3` 格式选择：因 UnitStrc 含大量 spike time 数据，文件可能超过 2GB
- GoodUnitRaw 是 `PostProcess_function_raw` → `PostProcess_function` 之间的核心中间产物

---

## 步骤 18：Raster + PSTH 构建

**所在函数**：`PostProcess_function.m:PostProcess_function:1-62`（含加载 + 主循环前半）
**在流程中的位置**：第 3 个主函数 / 子步骤 1（🔴 SpikeGLX×BHV2 最终交汇点）

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `processed/GoodUnitRaw_*.mat` | 步骤 #17 | .mat v7.3 | `:6-7` 加载：UnitStrc, trial_ML, meta_data, qMetric, unitType |
| `global_params.mat` | `gen_globaL_par.m` | .mat v7 | `:11` 加载：pre_onset(100), post_onset(700), psth_window_size_ms(30), base_line_time(-25:25), high_line_time1(50:250) |
| `processed/fscale.mat` | ⚠️ 来源不明 | .mat | `:27` 加载：`fscale`（波形缩放因子） |
| `processed/BC/templates._bc_rawWaveforms.npy` | 步骤 #14 Bombcell 产出 | .npy | `:29` 用 readNPY 加载 |

### 处理

**加载与初始化**（`:1-30`）：

1. `:6-7` — `load(fullfile('processed', meta_file(1).name))` — 加载 GoodUnitRaw 全部变量
2. `:11` — `load global_params.mat` — 加载全局参数
3. `:12-16` — 解包参数：`pre_onset=100`, `post_onset=700`, `psth_window_size_ms=30`, `base_line_time=-25:25`, `high_line_time1=50:250`
4. `:18-19` — `good_idx = 1; GoodUnitStrc = UnitStrc` — 初始化输出 struct（先复制全部，后裁剪）
5. `:20` — `GoodUnitStrc(good_idx).Raster = []` — 清空第一个元素的 Raster（预留写入）
6. `:21-23` — 从 `meta_data` 解包：`trial_valid_idx`, `onset_time_ms`, `img_size`
7. `:24` — `good_trial = find(trial_valid_idx)` — 有效 onset 的索引（trial_valid_idx > 0 的位置）
8. `:25` — `img_idx = trial_valid_idx(good_trial)` — 有效 onset 对应的图片编号
9. `:27` — `load("processed\fscale.mat")` — ⚠️ 来源不明的缩放因子
10. `:29` — `template_bc = fscale * readNPY(fullfile('processed/BC/templates._bc_rawWaveforms.npy'))` — 缩放后的 Bombcell 波形模板 [n_units × n_channels × T]

**逐 unit 主循环——Raster 构建**（`:31-43`）：

11. `:31` — `for spike_num = 1:length(UnitStrc)` — 循环所有 unit
12. `:32` — `spike_time = UnitStrc(spike_num).spiketime_ms` — 当前 unit 的 spike 时间（NI 时钟域）
13. `:33` — `psth_range = -pre_onset:post_onset` — 时间轴 [-100, +700] ms
14. `:34` — `raster_raw = zeros([length(good_trial), pre_onset+post_onset])` — 预分配 raster [n_good_trials × 800]
15. `:35-43` — 双层循环：
    - `:35` — 外层：循环每个有效 trial（`good_trial_idx`）
    - `:36-37` — 获取当前 trial 的 onset 时间：`onset_time_trial = onset_time_ms(loc_in_orig)`
    - `:38` — 截取该 onset 前后窗口内的 spike：`time_bound = spike_time(spike_time > onset_time_trial-pre_onset & spike_time < onset_time_trial+post_onset)`
    - `:39` — 转换为相对时间：`time_bound = 1 + time_bound - (onset_time_trial - pre_onset)`
    - `:40-42` — 内层：逐 spike 填入 raster（`floor(time_bound(time_bound_idx))` 位置 +1）

**PSTH 计算——滑动窗口平均**（`:44-58`）：

16. `:44-47` — 统计每张图片的有效 trial 数 `onset_t(img)`
17. `:48` — `psth_raw = zeros(size(raster_raw))` — 与 raster 同 shape
18. `:49-57` — 循环每个时间点：
    - `:50-55` — 确定滑动窗口边界（处理边界情况：窗口不足则左/右截断）
    - `:57` — `psth_raw(:,time_points) = 1000 * sum(raster_raw(:, time_window), 2) / length(time_window)` — spike count→firing rate (Hz)

**Response matrix 按图片平均**（`:59-62`）：

19. `:59` — `response_matrix_img = zeros([img_size, pre_onset+post_onset])` — [n_images × 800]
20. `:60-62` — 循环每张图片：`response_matrix_img(img,:) = sum(psth_raw(img_idx==img,:), 1) ./ onset_t(img)` — 按图片平均 PSTH

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `raster_raw` | 步骤 #19 统计筛选（baseline/highline 计算）+ 步骤 #19 GoodUnitStrc 组装 | double [n_good_trials × 800] | 逐 unit 计算，循环内变量 |
| `response_matrix_img` | 步骤 #19 GoodUnitStrc 组装 | double [img_size × 800] | 按图片平均的 PSTH |
| `template_bc` | 步骤 #19 波形裁剪 | double [n_units × n_channels × T] | fscale 缩放后的 Bombcell 波形模板 |

### 质检节点

无。`:86` fprintf 输出进度（`good_idx-1` good, `spike_num` in `length(UnitStrc)`）。

### 注意事项

- ⚠️ **`fscale.mat` 来源不明**：`:27` 加载但在所有已分析 MATLAB 代码中未找到生成逻辑
- ⚠️ **全局参数硬编码**：pre_onset=100ms, post_onset=700ms, psth_window_size_ms=30ms 均由 `gen_globaL_par.m` 硬编码
- ⚠️ **PSTH 窗口边界处理不精确**：`:50-55` 的滑动窗口在序列首尾固定为 `1:psth_window_size_ms` 或 `end-psth_window_size_ms:end`，导致边缘时间点的有效窗口大小不一致
- **🔴 最终交汇点**：这里是 SpikeGLX 链（spike_time，经 IMEC→NI 对齐）与 BHV2 链（onset_time_ms，经 photodiode 校准 -5ms）的最终交汇——所有上游处理步骤都在为此步骤准备数据

---

## 步骤 19：统计筛选 + 波形裁剪 + GoodUnitStrc 组装

**所在函数**：`PostProcess_function.m:PostProcess_function:63-88`（主循环后半）+ `prune_wf.m:prune_wf:1-10`
**在流程中的位置**：第 3 个主函数 / 子步骤 2

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `raster_raw` | 步骤 #18（循环内） | double [n_good_trials × 800] | 当前 unit 的 raster |
| `response_matrix_img` | 步骤 #18（循环内） | double [img_size × 800] | 当前 unit 的按图片平均 PSTH |
| `base_line_time` | `global_params` | -25:25（51 个时间点） | 基线窗 |
| `high_line_time1` | `global_params` | 50:250（201 个时间点） | 响应窗 |
| `unitType` | 步骤 #14 | vector [1 × n_units] | Bombcell 单元类型 |
| `template_bc` | 步骤 #18 | double [n_units × n_channels × T] | 缩放后波形模板 |
| `UnitStrc` | 步骤 #15 | struct array | 原始 unit 数据 |
| `qMetric` | 步骤 #14 | matrix | Bombcell 质量指标 |

### 处理

**统计检验**（`:63-68`）：

1. `:63` — `baseline = sum(raster_raw(:, (base_line_time)+pre_onset+1), 2)` — 基线窗 spike count per trial（`base_line_time+101` = 76:126）
2. `:64` — `highline1 = sum(raster_raw(:, (high_line_time1)+pre_onset+1), 2)` — 响应窗 spike count per trial（`high_line_time1+101` = 151:351）
3. `:66` — `[p1,~,~] = ranksum(highline1, baseline, method="approximate")` — Wilcoxon rank-sum 检验

**三重筛选条件**（`:68`）：

4. `:68` — `if(p1 < 0.001 && unitType(spike_num)~=0 && mean(highline1) > mean(baseline))` — 同时满足：
   - `p1 < 0.001`：响应窗与基线窗差异显著
   - `unitType(spike_num) ~= 0`：Bombcell 判定非噪声
   - `mean(highline1) > mean(baseline)`：响应窗均值高于基线（排除抑制性响应）

**波形裁剪**（`:69-70`，仅通过筛选的 unit）：

5. `:69` — `wf = squeeze(template_bc(spike_num,:,:))` — 取当前 unit 的全通道波形 [n_channels × T]
6. `:70` — `[cc, ww] = prune_wf(wf)` — 裁剪到 peak channel 附近
   - `prune_wf.m:4` — `amp = max(input_wf') - min(input_wf')` — 每通道振幅
   - `prune_wf.m:5` — `[~, peak_channel] = max(amp)` — 最大振幅通道
   - `prune_wf.m:6` — `steps = -6:2:6` — peak ± 6，步长 2（共 7 个通道）
   - `prune_wf.m:7` — `channels = peak_channel + steps` — 候选通道列表
   - `prune_wf.m:8` — `channels = intersect(channels, 1:384)` — 边界裁剪（⚠️ 硬编码 384）
   - `prune_wf.m:9` — `wf_near_site = input_wf(channels,:)` — 截取裁剪后的波形

**GoodUnitStrc 组装**（`:71-84`）：

7. `:71` — `GoodUnitStrc(good_idx).waveform = ww` — 裁剪后波形
8. `:72` — `GoodUnitStrc(good_idx).waveformchan = cc` — 裁剪的通道号
9. `:73` — `GoodUnitStrc(good_idx).KSidx = spike_num` — 原始 KS4 unit 编号
10. `:75` — `GoodUnitStrc(good_idx).spiketime_ms = UnitStrc(spike_num).spiketime_ms` — spike 时间序列
11. `:76` — `GoodUnitStrc(good_idx).spikepos = UnitStrc(spike_num).spikepos` — spike 位置
12. `:78` — `GoodUnitStrc(good_idx).Raster = uint8(raster_raw)` — raster 矩阵（转 uint8 省空间）
13. `:79` — `GoodUnitStrc(good_idx).response_matrix_img = single(response_matrix_img)` — PSTH（转 single 省空间）
14. `:81` — `GoodUnitStrc(good_idx).qm = qMetric(spike_num,:)` — 质量指标行
15. `:82` — `GoodUnitStrc(good_idx).unittype = unitType(spike_num)` — 单元类型
16. `:83` — `good_idx = good_idx + 1` — 递增 good 计数器

**循环结束后裁剪**：

17. `:88` — `GoodUnitStrc(good_idx:end) = []` — 删除未使用的预分配空间
18. `:89` — `global_params.PsthRange = psth_range(2:end)` — 将 PSTH 时间轴追加到 global_params（去掉第一个元素，使长度=800）

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `GoodUnitStrc` | 步骤 #20 最终保存 | struct array [1 × n_good_units] | 仅含通过三重筛选的 unit |
| `global_params`（含 PsthRange） | 步骤 #20 最终保存 | struct | 新增字段 `PsthRange` |

### 质检节点

无图表。`:86` fprintf 输出进度。

### 注意事项

- ⚠️ **ranksum 的 `method="approximate"`**：使用正态近似而非精确检验，对小样本可能不准确
- ⚠️ **p 值阈值硬编码 0.001**：`:68`
- ⚠️ **仅选择兴奋性响应**：`:68` 的 `mean(highline1) > mean(baseline)` 条件排除了所有抑制性神经元
- ⚠️ **prune_wf 硬编码 384 通道**：`prune_wf.m:8` 的 `intersect(channels, 1:384)`
- ⚠️ **prune_wf 步长 2**：`prune_wf.m:6` 取 peak ± 6 步长 2，即最多 7 个通道（不连续取样）
- Raster 转 `uint8`（`:78`）意味着单个 bin（1ms）内最多记录 255 个 spike
- response_matrix_img 转 `single`（`:79`）降低精度以节省空间

---

## 步骤 20：GoodUnit 最终文件输出

**所在函数**：`PostProcess_function.m:PostProcess_function:91-92`
**在流程中的位置**：第 3 个主函数 / 子步骤 3（★ Pipeline 最终输出）

### 输入

| 数据 | 来源 | 格式/类型 | 关键参数 |
|------|------|---------|---------|
| `GoodUnitStrc` | 步骤 #19 | struct array [1 × n_good_units] | 筛选后的 unit 数据 |
| `trial_ML` | 步骤 #16（已清理） | struct array | |
| `global_params` | 步骤 #19（含 PsthRange） | struct | |
| `meta_data` | 步骤 #14 加载 | struct | |
| `meta_file` | `:6` | dir struct | 用于文件名构造 |

### 处理

1. `:91` — `file_name_LOCAL = fullfile('processed', sprintf('GoodUnit_%s_g%s.mat', meta_file(1).name(13:end-7), meta_data.g_number))` — 构造文件名（从 `GoodUnitRaw_{name}_g{N}.mat` 中取 `{name}` 部分：跳过前 12 字符 `GoodUnitRaw_`，去掉末尾 7 字符 `_gN.mat`）
2. `:92` — `save(file_name_LOCAL, "GoodUnitStrc", "trial_ML", "global_params", 'meta_data', '-v7.3')` — 保存为 .mat v7.3（写操作 #11）

### 输出

| 数据 | 去向 | 格式/类型 | 备注 |
|------|------|---------|------|
| `processed/GoodUnit_{name}_g{N}.mat` | **无代码消费——★ Pipeline 最终产物** | .mat v7.3（HDF5） | 写操作 #11 |

**最终文件内容**：

| 变量 | 类型 | 内容 |
|------|------|------|
| `GoodUnitStrc` | struct array [1 × n_good] | 每元素含：waveform, waveformchan, KSidx, spiketime_ms, spikepos, Raster(uint8), response_matrix_img(single), qm, unittype |
| `trial_ML` | struct array | BHV2 trial 数据（Mouse/KeyInput 已清空） |
| `global_params` | struct | 含 pre_onset, post_onset, psth_window_size_ms, base_line_time, high_line_time1, PsthRange |
| `meta_data` | struct | 含 eye_matrix, onset_time_ms, trial_valid_idx, dataset_valid_idx, SyncLine, NI_META, IMEC_META, IMEC_AP_META, AIN, DCode_NI, DCode_IMEC, img_size, g_number, exp_subject, exp_day, ml_name |

### 质检节点

无。

### 注意事项

- **★ 这是整个 Pipeline 唯一的最终输出文件**，供后续分析脚本或手动加载使用
- `-v7.3` 格式（HDF5），支持 >2GB 文件
- 文件名格式：`GoodUnit_{日期}_{动物名}_{图片集名}_g{N}.mat`

---

## 流程总览表

| 步骤# | 步骤名 | 主要输入 | 主要输出 | 关键参数来源 | 质检图 |
|-------|--------|---------|---------|------------|--------|
| 0 | SpikeGLX 文件夹发现 | `NPX*` 目录 | session_name, g_number | 文件系统扫描 | 无 |
| 1 | NIDQ 数据加载 | `.nidq.meta` + `.nidq.bin` | NI_META, AIN(1kHz), DCode_NI | meta: niSampRate, niAiRangeMax, snsMnMaXaDw | 无 |
| 2 | BHV2 发现与解析 | `*.bhv2` | trial_ML, `ML_*.mat`(缓存) | 文件系统扫描 | 无 |
| 3 | BHV2 文件名解析 | ml_name | exp_day, exp_subject | 文件名下划线分割 | 无 |
| 4 | IMEC LF 同步脉冲提取 | `.lf.meta` + `.lf.bin` ch385 | IMEC_META, DCode_IMEC | meta: imSampRate; 硬编码 ch385 | 无 |
| 5 | IMEC AP 元信息加载 | `.ap.meta` | IMEC_AP_META | meta: imSampRate | 无 |
| 6 | IMEC↔NIDQ 时钟对齐 | DCode_NI(bit0), DCode_IMEC(val64) | SyncLine{NI_time, imec_time} | 硬编码阈值 1200ms | subplot(3,6,13-15) |
| 7 | ML↔NI trial 验证 | trial_ML(code64), DCode_NI(bit1,bit6) | onset_times | ML 事件码 64/32; NI bit 1/6 | subplot(3,6,1) |
| 8 | 数据集名称提取 | trial_ML.UserVars.DatasetName | dataset_pool, img_set_name | 路径反斜杠分割 | 无 |
| 9 | 眼动验证 | trial_ML.AnalogData.Eye + fixation_window | trial_valid_idx, dataset_valid_idx, eye_matrix | 硬编码 eye_thres=0.999 | subplot(3,6,12) |
| 10 | Photodiode onset 校准 | DCode_NI(bit6) + AIN | onset_time_ms, img_size | 硬编码 before=10, after=50/100ms, thres 权重 | subplot(3,6,2-5,7-11) |
| 11 | 显示器延迟校正 | onset_time_ms | onset_time_ms(-5ms) | 硬编码 -5ms | 无 |
| 12 | META 文件输出 | 步骤 0-11 全部变量 | `META_*.mat`, DataCheck.fig/.png | — | DataCheck.fig/png(14 subplot) |
| 13 | AP 预处理 + KS4 | `.ap.bin`(384ch, via SI) | `KS_TEMP2/`, `kilosort_def_5block_97/` | 硬编码 nblocks=5, Th_learned=7, freq_min=300 | 无 |
| 14 | Bombcell 质控 | KS4 输出 + `.ap.bin/.meta` | qMetric, unitType, `BC/` 目录 | Bombcell 默认参数 | BC.png(步骤17保存) |
| 15 | KS4 输出加载+时钟对齐 | KS4 .npy + IMEC_AP_META + SyncLine | UnitStrc(spiketime已对齐NI) | imSampRate; interp1 线性插值 | 无 |
| 16 | trial_ML 字段清理 | trial_ML | trial_ML(Mouse/KeyInput清空) | — | 无 |
| 17 | GoodUnitRaw 输出 | UnitStrc+trial_ML+meta_data+qMetric+unitType | `GoodUnitRaw_*.mat`, `BC.png` | -v7.3 格式 | BC.png |
| 18 | Raster + PSTH 构建 | UnitStrc.spiketime_ms + onset_time_ms + fscale + BC波形 | raster_raw, response_matrix_img | pre=100, post=700, psth_win=30ms | 无 |
| 19 | 统计筛选+波形裁剪 | raster_raw + unitType + template_bc | GoodUnitStrc | ranksum p<0.001; unitType≠0; 响应>基线 | 无 |
| 20 | ★ GoodUnit 最终输出 | GoodUnitStrc+trial_ML+global_params+meta_data | **`GoodUnit_*.mat`** | -v7.3 格式 | 无 |
