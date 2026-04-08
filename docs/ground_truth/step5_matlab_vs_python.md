# Step 5: MATLAB vs Python 版本差异系统对比

> 分析日期：2026-04-04
> MATLAB 版本：Step 4 产出 `step4_full_pipeline_analysis.md` 中的 21 个步骤
> Python 版本：`legacy_reference/pyneuralpipe/NPX_session_process.ipynb` + `core/` 目录
> 对比方法：逐步骤检查 6 个维度（实现位置/输入格式/处理逻辑/关键参数/输出格式/质检节点）

---

## 步骤 0 对比：SpikeGLX 文件夹发现与环境初始化

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Load_Data_function.m:1-9` | `data_loader.py:171-186` `_find_spikeglx_folder()` | ✅ 等价 |
| 输入数据格式 | `data_path` 字符串 → `cd` + `dir('NPX*')` | `Path.glob("NPX*")` | ✅ 等价 |
| 处理逻辑 | 仅匹配 `NPX*` 前缀，取第一个 | 先匹配 `NPX*`，若无则扫描含 `.bin`+`.meta` 的子目录 | ➕ 新增 |
| 关键参数值 | 硬编码 `NPX*`、`g_number = session_name(end)` | 硬编码 `NPX*`，无 `g_number` 提取 | ⚠️ 存疑 |
| 输出格式 | `session_name`(string)、`g_number`(char)、`processed/` 目录 | 返回 `Path` 对象；`processed/` 在后续步骤创建 | ✅ 等价 |
| 质检节点 | 无 | 无 | ✅ 等价 |

**差异说明**：
- ➕ Python 增加了 fallback 逻辑（扫描含 bin+meta 的子目录），更鲁棒
- ⚠️ Python 未提取 `g_number`（SpikeGLX g 编号），该值在 MATLAB 中用于 META 文件名。Python 的 NWB 输出不需要此字段

---

## 步骤 1 对比：NIDQ 数据加载

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `load_NI_data.m:1-55` + `load_meta.m` | `data_loader.py:188-217` `_load_nidq_sync_data()` | ✅ 等价 |
| 输入数据格式 | `.nidq.meta`(文本) + `.nidq.bin`(int16 memmap) | `si.read_spikeglx(stream_name='nidq')` → SpikeInterface Recording | ⚠️ 存疑 |
| 处理逻辑 — meta 解析 | 手写 key=value 解析器 (`load_meta.m`) | SpikeInterface 内部解析，通过 `neo_reader.signals_info_dict` 私有属性读取 | ⚠️ 存疑 |
| 处理逻辑 — AIN 提取 | `NI_rawData(1,:) * fI2V`（第 1 行=模拟输入，硬编码通道索引） | `nidq_rec.get_traces(channel_ids=['nidq#XA0'])`（按 SpikeInterface 通道名） | ✅ 等价 |
| 处理逻辑 — 数字通道 | 手工解析 `snsMnMaXaDw` → `digCh = MN+MA+XA+1` → 提取数字字 | `nidq_rec.get_traces(channel_ids=['nidq#XD0'])`（按 SI 通道名） | ✅ 等价 |
| 处理逻辑 — AIN 重采样 | `resample(AIN, p, q)` 到 1000 Hz（在 load_NI_data.m 内） | 延迟到 synchronizer.py:477-479 `resample_poly` 到 1000 Hz | ✅ 等价 |
| 关键参数值 | `niSampRate`, `niAiRangeMax` 从 meta 读取；通道 1 = AIN 硬编码 | `niSampRate`, `niAiRangeMax` 从 meta 读取；通道名 `nidq#XA0` | ✅ 等价 |
| 输出格式 | `NI_META`(struct), `AIN`(double 1×T_1kHz), `DCode_NI`(struct) | `sync_data['nidq_analog']`(ndarray), `sync_data['nidq_digital']`(ndarray), `sync_data['nidq_meta']`(dict) | ✅ 等价 |
| 质检节点 | fprintf 输出录制时长和事件码统计 | 无 | ➖ 缺失 |

**差异说明**：
- ⚠️ **私有 API 使用**：`data_loader.py:206` 访问 `nidq_rec.neo_reader.signals_info_dict[(0, 'nidq')]['meta']`。这是 SpikeInterface 的私有属性，可能随版本更新而破坏。`docs/legacy_analysis.md` 已标注此问题。
- ⚠️ **AIN 电压转换潜在双重缩放**：`data_loader.py:198` 的 `get_traces()` 默认返回原始 int16（`return_scaled=False`），synchronizer.py:472 再乘以 `fI2V` 转电压。但若 SpikeInterface 版本变更了默认行为（`return_scaled=True`），则会双重缩放。不过由于后续使用 z-score 归一化，功能上无影响。
- ➖ Python 缺少 NIDQ 录制时长和事件码统计的日志输出

---

## 步骤 2 对比：BHV2 行为数据发现与解析

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Load_Data_function.m:14-25` → `mlread.m` → `mlbhv2.m:1-399` | `data_loader.py:251-324` `load_monkeylogic()` → MATLAB engine → h5py/.mat | ✅ 等价 |
| 输入数据格式 | `.bhv2` 二进制文件（MATLAB 原生 mlbhv2 类直接读取） | `.bhv2` → MATLAB engine 转 `.mat` v7.3 → h5py 读取 | ✅ 等价 |
| 处理逻辑 — 缓存 | 检查 `processed/ML_*.mat` 是否存在 | 检查 `.mat` + `.pkl` 缓存，含 hash 校验和版本号 | ➕ 新增 |
| 处理逻辑 — 解析 | `mlbhv2.m` 原生解析 BHV2 二进制 → struct array | MATLAB engine `mlread()` → `save -v7.3` → h5py 递归解析 → dict list | ⚠️ 存疑 |
| 关键参数值 | 无配置参数 | 文件扩展名可配置 `.bhv2` | ➕ 新增 |
| 输出格式 | `trial_ML`(struct array) — 字段直接访问 | `monkeylogic_data`(dict) — 按字段名组织为 list | ⚠️ 存疑 |
| 质检节点 | 无 | 无 | ✅ 等价 |

**差异说明**：
- ⚠️ **数据结构差异**：MATLAB 输出 `trial_ML` 是 struct array（`trial_ML(i).BehavioralCodes.CodeNumbers`），Python 输出是按字段组织的 dict（`behavior_data['BehavioralCodes']['CodeNumbers'][i]`）。访问模式不同但语义等价。
- ⚠️ **h5py 解析复杂度**：`data_loader.py:475-646` 用了 170+ 行递归解析 h5py 格式，包含大量边界情况处理。数据类型转换（如浮点整数化 `_normalize_scalar`）可能引入微妙差异。
- ➕ Python 的缓存机制更完善（hash 校验 + 版本号），避免了 MATLAB 简单文件存在检查的局限性

---

## 步骤 3 对比：BHV2 文件名解析

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `parsing_ML_name.m:1-5` | `synchronizer.py:692` 在 `_prepare_export_data()` 中 | ✅ 等价 |
| 处理逻辑 | 按 `_` 分割文件名：`日期_动物名_其余.bhv2` | `self.data_loader.metadata['monkeylogic']['file_path'].name.split('_')[1:3]` | ⚠️ 存疑 |
| 输出格式 | `exp_day`(string), `exp_subject`(string) | `exp_day`(string), `exp_subject`(string) | ✅ 等价 |

**差异说明**：
- ⚠️ **文件名格式假设不同**：MATLAB 假设 `{date}_{subject}_{rest}.bhv2`，取第 1、2 个 `_` 分段。Python 取 `split('_')[1:3]`，即跳过第 0 个分段。这意味着 Python 假设文件名前缀有一个额外的前导分段（如 `ML_{date}_{subject}_{rest}.mat`）。若文件名格式为 `260302_JianJian_xxx.bhv2`，MATLAB 取 `260302` 和 `JianJian`，Python 的 `[1:3]` 取 `JianJian` 和第三段——可能错位。
- ⚠️ 实际上 Python 的 `file_path` 是 `ML_{stem}.mat` 而非原始 `.bhv2`，路径格式不同导致 split 索引不同。需要验证实际文件名格式。

---

## 步骤 4 对比：IMEC LF 同步脉冲提取

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `load_IMEC_data.m:1-22` + `load_meta.m` | `data_loader.py:219-236` `_load_imec_sync_data()` | ✅ 等价 |
| 输入数据格式 | `.lf.meta` + `.lf.bin`（int16 memmap，通道 385 硬编码） | `si.read_spikeglx(stream_name='imec0.lf-SYNC')` → `get_traces(channel_ids=['imec0.lf#SY0'])` | ✅ 等价 |
| 处理逻辑 — sync 提取 | `digital0 = m.Data.x(385,:)` → `diff` → `find(CodeAll>0)` 仅上升沿 | SpikeInterface 的 `-SYNC` stream 直接提取 sync 通道 | ✅ 等价 |
| 处理逻辑 — CodeVal | `CodeVal = CodeAll(DCode.CodeLoc)` — diff 值（变化量） | synchronizer.py:155 — `Dcode_imec_all[np.where(...)]` — diff 值（变化量） | ✅ 等价 |
| 关键参数值 | `imSampRate` 从 meta 读取；通道 385 硬编码 | `imSampRate` 从 meta 读取；通道名由 SI 管理 | ✅ 等价 |
| 输出格式 | `IMEC_META`(struct), `DCode_IMEC`(struct) | `sync_data['imec_sync']`(ndarray), `sync_data['imec_meta']`(dict) | ✅ 等价 |
| 质检节点 | fprintf 录制时长和事件统计 | synchronizer.py:160-162 log IMEC 事件统计 | ✅ 等价 |

**差异说明**：
- Python 使用 SpikeInterface 的 `imec0.lf-SYNC` stream 直接读取 sync 通道，无需硬编码通道 385，更适配不同探针型号。➕ 改进
- ⚠️ **私有 API**：`data_loader.py:230` 访问 `imec_rec.neo_reader.signals_info_dict` 获取 meta，同步骤 1

---

## 步骤 5 对比：IMEC AP 元信息加载

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Load_Data_function.m:30-31` + `load_meta.m` | 隐式在 notebook `si.read_spikeglx(stream_name='imec0.ap')` 中 | ✅ 等价 |
| 处理逻辑 | 单独加载 `.ap.meta`，不读 AP bin | SpikeInterface 加载 AP Recording 对象（lazy，不读全量 bin） | ✅ 等价 |
| 关键参数值 | `imSampRate` ~30000 Hz | `recording.get_sampling_frequency()` | ✅ 等价 |
| 输出格式 | `IMEC_AP_META`(struct) | Recording 对象内含 meta | ✅ 等价 |

**差异说明**：
- 无重大差异。Python 更优雅——AP meta 信息内嵌在 Recording 对象中，无需单独提取

---

## 步骤 6 对比：IMEC↔NIDQ 时钟对齐

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `examine_and_fix_sync.m:1-66` | `synchronizer.py:142-235` `_prepare_sync_data()` | ⚠️ 存疑 |
| 处理逻辑 — NI sync 提取 | `bitand(DCode_NI.CodeVal, 1)` → diff > 0 → 上升沿 | `np.diff(Dcode_ni['CodeVal'] & 1) > 0` | ✅ 等价 |
| 处理逻辑 — IMEC sync 提取 | `DCode_IMEC.CodeVal == 64` | `Dcode_imec['CodeVal'] == 64` | ✅ 等价 |
| 处理逻辑 — 脉冲数量校验 | 不匹配时 `keyboard`（暂停等待人工干预）+ 自动插值修复（找 >1200ms 间隔，插入中间值） | 不匹配时只 log warning + 设置 status='failed'，**无修复逻辑** | ❌ 错误 |
| 处理逻辑 — 时钟漂移 | 逐脉冲计算 `terr = NI_time - imec_time`，输出配对时间序列 | 同样计算 `time_err = ni_sync_time - imec_sync_time` | ✅ 等价 |
| 关键参数值 | 硬编码阈值 1200ms（修复间隔判定） | 无修复，`max_time_error=17ms`（质量警告阈值） | ⚠️ 存疑 |
| 输出格式 | `SyncLine{NI_time, imec_time}` — 配对时间序列 | `sync_line{ni_sync_time, imec_sync_time, time_errors, ...}` | ✅ 等价 |
| 质检节点 | subplot(3,6,13-15)：IMEC/NI 脉冲间隔 + NI-IMEC 漂移图 | synchronizer.py:668-681 生成 sync error 图 | ⚠️ 存疑 |

**差异说明**：
- ❌ **缺少 sync 修复逻辑**：MATLAB 在脉冲数量不匹配时有自动修复机制（间隔 >1200ms 的位置插入插值脉冲）。Python 版本直接报 failed，不尝试修复。在实际数据中偶尔会出现丢脉冲，MATLAB 的修复机制是必要的。
- ⚠️ Python 的质检图只有 sync error 一幅图，缺少 MATLAB 的脉冲间隔图（用于诊断丢脉冲位置）

---

## 步骤 7 对比：ML↔NI Trial 数量一致性验证

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Load_Data_function.m:43-74` | `synchronizer.py:237-331` `_check_ml_ni_alignment()` | ✅ 等价 |
| 处理逻辑 — ML 端 | 逐 trial 循环，计数 `CodeNumbers==64` | 逐 trial 循环，计数 `codes == stim_onset_code`（可配置，默认 64） | ✅ 等价 |
| 处理逻辑 — NI 端 | `bitand(CodeVal, 2) > 0` 提取 bit 1（trial start），逐 trial 计数 bit 6 onset | `diff(CodeVal & (1 << trial_start_bit)) > 0`，可配置 bit 位 | ✅ 等价 |
| 处理逻辑 — 不一致处理 | `warning` + 继续（仅比较 max error） | `warning` + **自动修复 trial start bit**（遍历 bit 0-7 寻找匹配数量） | ➕ 新增 |
| 关键参数值 | bit 1 = trial start, bit 6 = onset（硬编码） | `trial_start_bit`, `stim_onset_bit` 从配置读取（默认 1, 6） | ➕ 新增 |
| 输出格式 | `onset_times_by_trial_ML/SGLX`(向量), `onset_times`(标量) | `onset_comparison`(dict)，含 `ml_by_trial`, `sglx_by_trial`, `max_error` | ✅ 等价 |
| 质检节点 | subplot(3,6,1)：ML vs SGLX onset 散点图 | synchronizer.py:566-575 生成散点图 | ✅ 等价 |

**差异说明**：
- ➕ **trial start code 自动修复**：Python 在 trial 数不匹配时会自动搜索正确的 bit 编号（synchronizer.py:285-298）。MATLAB 仅 warning 不修复。
- ➕ **参数化事件码**：Python 的 onset/offset code 和 bit 位从配置文件读取，MATLAB 全部硬编码

---

## 步骤 8 对比：数据集名称提取

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Load_Data_function.m:77-85` | `synchronizer.py:333-351` `_extract_dataset_info()` | ✅ 等价 |
| 处理逻辑 | 收集 `UserVars.DatasetName` → unique → 取第一个 → 按反斜杠分割提取图片集名 → `img_set_name` | 收集 `DatasetName` → unique → `Path(datasets[0]).name.split('.')[0]` | ✅ 等价 |
| 关键参数值 | 硬编码反斜杠 `\` 分割 + `end-4`（假设 4 字符扩展名） | 使用 `Path.name`（跨平台） + `split('.')[0]`（任意扩展名） | ➕ 新增 |

**差异说明**：
- ➕ Python 使用 `pathlib.Path` 处理路径，不依赖 Windows 反斜杠，更跨平台

---

## 步骤 9 对比：眼动验证（Eye Validation）

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Load_Data_function.m:87-142` | `synchronizer.py:353-463` `_validate_eye_tracking()` | ⚠️ 存疑 |
| 处理逻辑 — 时间索引 | `onset_start_to_end = (beh_time(loc) : beh_time(loc)+duration) ./ SampleInterval` → floor | `np.arange(start, end) / SampleInterval` → floor → `astype(int16)` | ✅ 等价 |
| 处理逻辑 — 眼动距离 | `sqrt(eye_data(:,1).^2 + eye_data(:,2).^2)` | `np.linalg.norm(eye_data, axis=1)` | ✅ 等价 |
| 处理逻辑 — 注视比例 | `sum(dist < fixation_window) / (onset_duration+1)` | `sum(dist < fixation_window) / stim_ondur` | ⚠️ 存疑 |
| 处理逻辑 — 有效标记 | `trial_valid_idx` 仅在 `eye_ratio > threshold` 时赋值图片编号，否则保持 0 | `valid_stim_idx` 对**所有** onset 赋值图片编号，`valid_dataset_idx` 仅在 valid 时赋值 | ❌ 错误 |
| 处理逻辑 — eye_matrix | 3D 延迟分配 `[2 × n_onsets × T]`，首次 onset 确定 T 维度 | 预分配 `[n_onsets × max_dur × 2]`，使用 NaN 填充 | ➕ 新增 |
| 处理逻辑 — try/catch | `try...end` 无 catch，溢出静默跳过 | try/except IndexError → 截断越界索引 | ➕ 新增 |
| 关键参数值 | `eye_thres = 0.999` 硬编码 | `ratio_threshold` 从配置读取（默认 0.999） | ➕ 新增 |
| 输出格式 | `trial_valid_idx`(仅 valid 有值), `dataset_valid_idx`, `eye_matrix[2×N×T]` | `valid_stim_idx`(所有 onset 有值), `valid_dataset_idx`, `eye_matrix[N×T×2]` | ❌ 错误 |
| 质检节点 | subplot(3,6,12)：眼位密度热图 | synchronizer.py:629-651 生成密度热图 | ✅ 等价 |

**差异说明**：
- ❌ **`trial_valid_idx` 语义不同**：
  - MATLAB：`trial_valid_idx(i) > 0` 同时表示"眼动有效"和"图片编号"。值为 0 = 无效
  - Python：`valid_stim_idx(i)` 对所有 onset 都赋值图片编号（无论眼动是否有效），仅 `valid_dataset_idx(i) > 0` 表示眼动有效
  - **影响**：Python 的 `valid_eye_count = sum(valid_stim_idx > 0)` (synchronizer.py:453) 会计入所有 onset（因为图片编号始终 > 0），而非仅眼动有效的 onset。这使得 `valid_eye_count` 日志值偏高。
  - **下游影响有限**：DataIntegrator 使用 `dataset_valid_idx != 0` 判断 `fix_success`，不依赖 `trial_valid_idx` 的零值语义。NWB 中 `stim_index` 记录所有 onset 的图片编号（即使 fixation 失败），这实际上**更有信息量**。
- ⚠️ **注视比例分母差异**：MATLAB 用 `onset_duration+1`，Python 用 `stim_ondur`。差 1 个样本点，对 200ms+ 的 onset 影响极小（<0.5%），但是一个差异。
- ➕ Python 的 eye_matrix 使用 NaN 预分配 + 预先确定 T 维度，避免了 MATLAB 的延迟分配和潜在的维度不一致问题
- ➕ Python 处理 IndexError 时截断越界索引，比 MATLAB 的静默跳过更可靠

---

## 步骤 10 对比：Photodiode Onset 时间校准

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Load_Data_function.m:144-258` | `synchronizer.py:465-557` `_calibrate_photodiode_timing()` | ❌ 错误 |
| 处理逻辑 — onset 定位 | `diff(bitand(CodeVal, 64)) > 0` → 提取 bit 6 上升沿 | `diff(CodeVal & (1 << stim_onset_bit)) > 0`，bit 可配置 | ✅ 等价 |
| 处理逻辑 — 信号截取 | 逐 onset 截取 AIN 信号 → z-score 归一化 | 逐 onset 截取 AIN 信号 → z-score 归一化 | ✅ 等价 |
| 处理逻辑 — **极性校正** | **有**：逐 trial 检测 diff 方向，若下降则翻转信号 + 记录 sign_array | **无**：不做极性检测/校正 | ❌ 错误 |
| 处理逻辑 — 阈值计算 | `0.1*baseline + 0.9*highline`（baseline=前 10ms 均值, highline=60-80ms 均值） | `baseline_weight * baseline + peak_weight * highline`（参数化，默认相同） | ✅ 等价 |
| 处理逻辑 — latency 检测 | `find(po_dis(tt,:) > thres, 1) - before_onset_measure` | `np.where(photodoide[_,:] > threshold)[0].min() - before_onset_measure` | ✅ 等价 |
| 处理逻辑 — 校准后验证 | 重新截取 + 重新 zscore + 极性校正 + 排除非注视 trial + 绘图 | 重新截取 + 重新 zscore + 排除非注视 trial（无极性校正） | ⚠️ 存疑 |
| 关键参数值 | `before=10, after_measure=50, after_stats=100` 硬编码 | 从配置读取（默认相同值） | ➕ 新增 |
| 输出格式 | `onset_time_ms`(ms, NI 时钟域) | `onset_time_ms`(ms, NI 时钟域 → 后续映射到 IMEC 时钟域) | ⚠️ 存疑 |
| 质检节点 | 8 个 subplot（热图/均值/直方图） | 3 个 subplot（校准后信号/排除非注视/延迟分布缺失） | ➖ 缺失 |

**差异说明**：
- ❌ **缺少极性校正**：这是最严重的功能差异。MATLAB 的 photodiode 校准包含完整的极性检测和校正（`Load_Data_function.m:184-192`），处理 photodiode 信号可能为正跳或负跳的情况。Python 完全缺少此步骤。若刺激使 photodiode 信号下降（如暗色图片替换亮色背景），Python 的阈值穿越检测会失败并抛出异常（synchronizer.py:524）。
- ➖ Python 缺少 5 个诊断图：原始 photodiode 热图、diff 热图、|diff| 热图、极性校正后热图、延迟分布直方图
- ⚠️ **时钟域转换差异**：Python 在此步骤之后将 `onset_time_ms` 从 NI 域映射到 IMEC 域（synchronizer.py:548），MATLAB 保持在 NI 域。方向不同但一致性正确——见步骤 15 分析。

---

## 步骤 11 对比：显示器延迟校正（-5ms）

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Load_Data_function.m:263` | `synchronizer.py:530` | ✅ 等价 |
| 处理逻辑 | `onset_time_ms = onset_time_ms - 5` | `stim_onset_ms = stim_onset_ms + self.params['monitor_delay_correction']` | ✅ 等价 |
| 关键参数值 | -5ms 硬编码 | 配置参数 `monitor_delay_correction`（默认 -5） | ➕ 新增 |

**差异说明**：
- ➕ Python 将 -5ms 参数化，可根据显示器刷新率调整

---

## 步骤 12 对比：诊断图保存与 META 文件输出

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Load_Data_function.m:260-265` | `synchronizer.py:559-687`(viz) + `689-976`(export) | ✅ 等价 |
| 输出格式 — 诊断图 | `DataCheck.fig` + `DataCheck.png`（3×6=18 subplot） | base64 PNG（部分 subplot） + 保存为文件 | ➖ 缺失 |
| 输出格式 — META | `.mat v7`，含 17 个变量 | `.h5`（HDF5），含嵌套 dict 结构 | ⚠️ 存疑 |
| 输出格式 — 数据内容 | eye_matrix, onset_time_ms, trial/dataset_valid_idx, SyncLine, META×3, AIN, DCode×2, img_size, g_number, exp_subject, exp_day | sync_info, trial_validation, eye_data, session_info, processing_params | ✅ 等价 |

**差异说明**：
- ➖ Python 的诊断图缺少多个 MATLAB 中有的 subplot（见步骤 10）
- ⚠️ 输出格式从 .mat 变为 .h5，字段组织方式不同但内容等价
- Python 新增了 `processing_params` 和 `processing_timestamp` 等元数据 ➕

---

## 步骤 13 对比：AP 预处理 + Kilosort4 Spike Sorting

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `Analysis_Fast.ipynb`（2 个 cell） | `NPX_session_process.ipynb` cells + `spike_sorter.py` | ✅ 等价 |
| 处理逻辑 — 预处理链 | highpass(300) → detect_bad → remove_bad → **phase_shift** → CMR | highpass(300) → detect_bad → remove_bad → **phase_shift** → CMR（相同错误顺序） | ❌ 错误 |
| 处理逻辑 — 运动校正 | **无** | **有**：`si.correct_motion(preset='dredge')` + 可选开关 | ➕ 新增 |
| 处理逻辑 — 保存格式 | `format='binary'`（→ `KS_TEMP2/`） | `format='zarr'`（→ `preprocess.zarr`） | ✅ 等价 |
| 关键参数值 — nblocks | 5（硬编码） | 20（notebook）/ 15（spike_sorter.py 默认） | ⚠️ 存疑 |
| 关键参数值 — Th_learned | 7（硬编码） | 未设置（默认值） | ⚠️ 存疑 |
| 关键参数值 — n_jobs | 18 | 12-20（可配置） | ✅ 等价 |
| 关键参数值 — chunk_duration | '4s' | '3s'-'4s'（可配置） | ✅ 等价 |
| 输出格式 | `KS_TEMP2/` + `kilosort_def_5block_97/sorter_output/` | `SI/preprocess.zarr` + `SI/KS4/sorter_output/` | ✅ 等价 |
| 质检节点 | 无 | 无 | ✅ 等价 |

**差异说明**：
- ❌ **预处理顺序错误**：MATLAB 和 Python 旧代码**都**将 `phase_shift` 放在 `highpass_filter` 之后。正确顺序应为 phase_shift 在最前面（CLAUDE.md 已标注）。两个版本犯了相同的错误。
- ➕ **运动校正**：Python 版本新增 DREDge 运动校正步骤（`use_motion_correction=True`），MATLAB 版本没有。这是一个重要改进。
- ⚠️ **nblocks 差异**：MATLAB 用 5，Python notebook 用 20，spike_sorter.py 默认 15。nblocks 控制 KS4 的漂移校正分块数，值越大校正越精细但越慢。若使用了外部 DREDge 运动校正，nblocks 应与之互斥（CLAUDE.md 约束）。
- ⚠️ **Th_learned**：MATLAB 设为 7，Python 未显式设置（使用 KS4 默认值，通常为 8 或 9）。此参数影响 spike 检测灵敏度。
- Python spike_sorter.py 支持 "protocol pipeline" 模式（通过配置文件定义预处理链）和传统手动模式 ➕

---

## 步骤 14 对比：Bombcell 质控

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `run_bc.m:1-26`（MATLAB Bombcell 库） | `quality_controller.py:149-211`（Python bombcell 包） | ✅ 等价 |
| 处理逻辑 | MATLAB 原生 Bombcell：`bc.load.loadEphysData` → `bc.qm.qualityParamValues` → `bc.qm.runAllQualityMetrics` | Python bombcell 包：`bc.get_default_parameters()` → `bc.run_bombcell()` | ✅ 等价 |
| 关键参数值 | `gain_to_uV=NaN`(自动), `kilosortVersion=4` | `kilosort_version=4`, 自定义 `tauR` 参数 | ⚠️ 存疑 |
| 输出格式 | `qMetric`(matrix), `unitType`(vector: 0=noise) | `qMetric`(dict), `unitType`(array: 0=noise,1=good,2=mua,3=no-somatic) | ⚠️ 存疑 |
| 质检节点 | figure(8)（Bombcell 内部创建） | `return_figures=True` 参数控制 | ✅ 等价 |

**差异说明**：
- ⚠️ **unitType 编码差异**：MATLAB Bombcell 输出 `unitType` 为 0（noise）和非 0（有效）。Python Bombcell 输出更细粒度：0=noise, 1=good, 2=mua, 3=no-somatic。MATLAB 代码用 `unitType~=0` 筛选，Python 代码在 DataIntegrator 中用 `unitType == 0` 排除。逻辑等价。
- ⚠️ Python 额外自定义了 `tauR` 参数（quality_controller.py:138-140），MATLAB 使用默认值
- Python 将结果保存为 JSON + CSV，便于后续处理 ➕

---

## 步骤 15 对比：KS4 输出加载与 IMEC→NI 时钟对齐

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `load_KS4_output.m:1-32` | `data_integrator.py:497-565` `step4_add_custom_units()` | ⚠️ 存疑 |
| 处理逻辑 — spike time 时钟转换 | `interp1(SyncLine.imec_time, SyncLine.NI_time, spike_times)` — IMEC→NI 映射 | **不转换 spike times**；onset 时间在步骤 10 中 NI→IMEC 映射 | ⚠️ 存疑 |
| 处理逻辑 — 时钟域 | 所有数据对齐到 **NI 时钟域** | 所有数据对齐到 **IMEC 时钟域** | ✅ 等价 |
| 处理逻辑 — UnitStrc 组装 | 循环逐 unit：提取 waveform, spiketime_ms, spikepos, amplitudes | 在 `_add_units()` 中逐 unit：从 NWB 读取 spike_times, 计算 unit 响应 | ✅ 等价 |
| 关键参数值 | `imSampRate` 用于 sample→ms 转换 | neuroconv 自动处理 sample→seconds 转换 | ✅ 等价 |
| 输出格式 | `UnitStrc`(struct array: {waveform, spiketime_ms, spikepos, amplitudes}) | NWB units table（spike_times in seconds） | ✅ 等价 |

**差异说明**：
- ⚠️ **时钟域对齐方向相反**：
  - MATLAB：spike times 从 IMEC 域映射到 NI 域（`interp1(imec→NI)`），onset 时间保持在 NI 域。所有比对在 **NI 时钟域**。
  - Python：onset 时间从 NI 域映射到 IMEC 域（synchronizer.py:548 `np.interp(onset, ni→imec)`），spike times 保持在 IMEC 域。所有比对在 **IMEC 时钟域**。
  - **两种方式等价**，因为映射是双向线性插值，精度相同。但设计哲学不同。
- Python 不手工加载 KS4 .npy 文件——使用 neuroconv 的 `KiloSortSortingInterface` 自动处理 ➕
- Python 不手工组装 UnitStrc——数据直接写入 NWB ➕

---

## 步骤 16 对比：trial_ML 字段清理

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `PostProcess_function_raw.m:14-17` | 无对应实现 | ➖ 缺失 |
| 处理逻辑 | 清空 `trial_ML(i).AnalogData.Mouse` 和 `.KeyInput` | Python 数据不需要此步骤 | ✅ 等价 |

**差异说明**：
- 此步骤的目的是减小 `.mat` 文件体积。Python 输出 NWB 格式，不保存 Mouse/KeyInput 数据到 NWB，因此不需要显式清理。功能等价。

---

## 步骤 17 对比：Bombcell 诊断图保存 + GoodUnitRaw 文件输出

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `PostProcess_function_raw.m:19-23` | 无直接对应——Bombcell 图由 `quality_controller.py` 处理；数据直接流入 NWB | ✅ 等价 |
| 输出格式 | `GoodUnitRaw_*.mat`（.mat v7.3，含 UnitStrc+trial_ML+meta_data+qMetric+unitType） | Bombcell 结果保存为 JSON + CSV；数据在 `data_integrator.py` 中直接写入 NWB | ✅ 等价 |

**差异说明**：
- Python 不产生中间 `GoodUnitRaw` 文件——数据直接从 KS 输出 + Bombcell 结果流入 NWB。减少了一个中间产物。➕ 改进

---

## 步骤 18 对比：Raster + PSTH 构建

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `PostProcess_function.m:31-62` | `data_integrator.py:661-707` `_compute_unit_response()` | ⚠️ 存疑 |
| 处理逻辑 — Raster | 双层循环：逐 good_trial → 截取 spike → `floor(relative_time)` 位置 +1 | `np.histogram(aligned_spikes, bins)` | ⚠️ 存疑 |
| 处理逻辑 — PSTH | 滑动窗口平均（窗口大小 30ms）→ spike count / 窗口长度 × 1000 = Hz | **不计算 PSTH**——仅存储 raster，PSTH 在下游分析中计算 | ➖ 缺失 |
| 处理逻辑 — Response matrix | 按图片平均 PSTH → `response_matrix_img [img_size × 800]` | **不计算**——直接存储 raster，按需分析 | ➖ 缺失 |
| 处理逻辑 — trial 选择 | 仅 `trial_valid_idx > 0`（眼动有效）的 onset | 仅 `trial['fix_success']` 为 True 的 trial | ✅ 等价 |
| 关键参数值 | pre=100ms, post=700ms, psth_window=30ms（`gen_globaL_par.m` 硬编码） | pre/post/bin_size 从配置读取 | ➕ 新增 |
| 输出格式 | `raster_raw`(double [trials × 800]), `response_matrix_img`(double [imgs × 800]) | `epoch_raster`(uint8 [trials × bins]), baseline/response spike counts | ⚠️ 存疑 |

**差异说明**：
- ⚠️ **Raster 构建方法不同**：MATLAB 逐 spike 手动填入 raster 矩阵（1ms bin），Python 使用 `np.histogram`。若 bin_size = 1ms，结果等价。Python 的 bin_size 可配置。
- ➖ **缺少 PSTH 和 Response Matrix**：MATLAB 在 pipeline 内计算滑动窗口 PSTH 和按图片平均的 response matrix。Python 仅存储 raster 到 NWB，PSTH 在后续分析脚本中（如 notebook 的 `spike_times_to_raster` 函数）计算。设计哲学不同——Python 将分析从 pipeline 中分离。
- ⚠️ **fscale 问题**：MATLAB 加载 `processed/fscale.mat` 用于 Bombcell 波形缩放。Python 不使用 fscale——直接使用 Bombcell 原始波形。`fscale` 的来源和用途在 MATLAB 代码中不明。

---

## 步骤 19 对比：统计筛选 + 波形裁剪 + GoodUnitStrc 组装

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `PostProcess_function.m:63-88` + `prune_wf.m` | `data_integrator.py:609-660` `_add_units()` + `_statistical_test()` + `_prepare_waveforms()` | ⚠️ 存疑 |
| 处理逻辑 — 统计检验 | `ranksum(highline, baseline, method="approximate")` — Wilcoxon 秩和检验 | `mannwhitneyu(baseline, response, alternative=..., method='auto')` — Mann-Whitney U | ⚠️ 存疑 |
| 处理逻辑 — 筛选条件 | **三重条件**：p<0.001 AND unitType≠0 AND mean(response)>mean(baseline) | **二重条件**：statistical test AND optionally unitType≠0 | ❌ 错误 |
| 处理逻辑 — 波形裁剪 | `prune_wf.m`：peak channel ± 6，步长 2（7 个非连续通道），硬编码 384 | `_prepare_waveforms()`：peak channel ± n_channels_around（可配置），连续通道 | ⚠️ 存疑 |
| 关键参数值 | p < 0.001, baseline=-25:25, highline=50:250（硬编码） | p_threshold 可配置, baseline/response window 可配置 | ➕ 新增 |
| 输出格式 | `GoodUnitStrc`(struct array) — 仅含通过筛选的 unit | NWB units table — 仅含通过筛选的 unit | ✅ 等价 |

**差异说明**：
- ❌ **缺少方向性条件**：MATLAB 的第三个条件 `mean(highline1) > mean(baseline)` 排除了抑制性响应的神经元（response < baseline）。Python 版本**不包含此条件**。这意味着 Python 可能会保留 MATLAB 会排除的抑制性神经元。若 `mannwhitneyu` 的 `alternative` 设为 `'greater'`（单侧检验），则等效于方向性条件，但需要验证配置。
- ⚠️ **统计检验方法**：ranksum（MATLAB）和 mannwhitneyu（Python）是数学等价的检验。但参数顺序不同（MATLAB: response, baseline; Python: baseline, response），若使用单侧检验，方向需要反转。
- ⚠️ **波形裁剪通道选择不同**：MATLAB 取 peak ± 6 步长 2（非连续，7 个通道），Python 取 peak ± n_channels_around（连续通道）。波形形态会不同。

---

## 步骤 20 对比：GoodUnit 最终文件输出

| 维度 | MATLAB 版本 | Python 版本 | 差异类别 |
|------|------------|------------|---------|
| 实现位置 | `PostProcess_function.m:91-92` | `data_integrator.py:755-787` `run_full_pipeline()` | ✅ 等价 |
| 输出格式 | `GoodUnit_*.mat`（.mat v7.3）：GoodUnitStrc + trial_ML + global_params + meta_data | `NWBFile_*.nwb`（NWB/HDF5）：units + trials + eye tracking + raw data | ➕ 新增 |
| 输出内容 | 仅含筛选后 unit 的 raster/PSTH/waveform + 行为数据 + meta | 含原始电生理数据 + KS 全部 units + 筛选后 units + 行为数据 + 眼动 + 刺激 | ➕ 新增 |

**差异说明**：
- ➕ **NWB 格式**：Python 输出 NWB 标准格式，包含更完整的数据（原始电生理、LFP、完整 KS 输出、行为数据），符合 DANDI 归档标准。MATLAB 输出的 .mat 仅包含分析结果子集。
- ➕ Python 在 NWB 中保留了所有 KS units（通过 KiloSortSortingInterface），筛选后的 units 作为额外的 units table，保留了更多信息供后续分析。

---

## 差异汇总

### 必须修复（❌ 错误类）

| 步骤 | 差异描述 | 正确行为（MATLAB） | 当前错误行为（Python） | 影响范围 |
|------|---------|---------|------------|---------|
| #6 | 缺少 sync 修复逻辑 | 脉冲数不匹配时：找 >1200ms 间隔 → 插入插值脉冲 | 直接报 failed，无修复 | 偶发丢脉冲的 session 无法处理 |
| #9 | `trial_valid_idx` 语义不同 | 仅眼动有效的 onset 赋值图片编号（无效=0） | 所有 onset 都赋值图片编号（valid 由 dataset_valid_idx 控制） | `valid_eye_count` 日志值错误（偏高）；下游 NWB 不受影响 |
| #10 | 缺少 photodiode 极性校正 | 逐 trial 检测极性方向，若下降则翻转信号 | 不做极性检测/校正 | 暗色刺激的 session 校准失败 |
| #13 | 预处理顺序错误（与 MATLAB 相同） | phase_shift 应在 highpass_filter **之前** | phase_shift 在 highpass_filter 之后 | spike 检测精度下降（两版本同样的错误） |
| #19 | 缺少方向性筛选条件 | p<0.001 AND unitType≠0 AND mean(response)>mean(baseline) | p<threshold AND unitType≠0（无方向性条件） | 可能保留抑制性神经元（MATLAB 会排除） |

### 需要验证（⚠️ 存疑类）

| 步骤 | 差异描述 | 验证方法 |
|------|---------|---------|
| #1 | `neo_reader.signals_info_dict` 私有 API 稳定性 | 检查 SpikeInterface 0.104+ 文档确认是否提供公开 API 替代 |
| #1 | AIN `get_traces()` 是否返回原始 int16 | 打印 `nidq_rec.get_traces(channel_ids=['nidq#XA0']).dtype` 验证 |
| #3 | 文件名 split 索引是否匹配实际格式 | 检查实际 `file_path.name` 的格式（是 `ML_260302_JianJian_xxx.mat` 还是 `260302_JianJian_xxx.bhv2`） |
| #9 | 注视比例分母：`onset_duration+1` vs `stim_ondur` | 对比两种计算结果差异（预期 <0.5%，影响极小） |
| #13 | nblocks=5(MATLAB) vs 20(Python) 结果差异 | 用相同数据对比两种 nblocks 的 sorting 输出 |
| #13 | Th_learned=7(MATLAB) vs 默认值(Python) | 确认 KS4 默认 Th_learned 值 |
| #15 | 时钟域选择（NI vs IMEC）一致性 | 确认 Python 中 onset_time 和 spike_time 都在 IMEC 域 |
| #18 | fscale.mat 的来源和作用 | 在实际数据中检查 fscale.mat 内容和波形缩放效果 |
| #19 | mannwhitneyu `alternative` 参数配置 | 检查配置文件中的 `alternative` 值；若为 `'greater'` 则等效于 MATLAB 方向性条件 |
| #19 | 波形裁剪通道选择模式差异 | 对比两种选择方式的波形质量 |

### 可以保留（➕ 新增类）

| 步骤 | 新增内容 | 保留理由 |
|------|---------|---------|
| #0 | Fallback 扫描含 bin+meta 的子目录 | 更鲁棒的文件发现 |
| #2 | 缓存 hash 校验 + 版本号 | 避免陈旧缓存 |
| #7 | 自动修复 trial start bit code | 减少人工干预 |
| #7 | 事件码参数化（从配置读取） | 消除硬编码 |
| #8 | 使用 pathlib 处理路径 | 跨平台兼容 |
| #9 | NaN 预分配 eye_matrix + IndexError 处理 | 更可靠的边界处理 |
| #10 | Photodiode 参数可配置 | 灵活性 |
| #11 | 显示器延迟可配置 | 适配不同显示器 |
| #13 | DREDge 运动校正 | 重要的信号质量改进 |
| #13 | Protocol pipeline 模式 | 可配置预处理链 |
| #17 | 无中间 GoodUnitRaw 文件 | 减少中间产物 |
| #18 | Raster bin_size 可配置 | 灵活性 |
| #19 | 统计检验参数可配置 | 灵活性 |
| #20 | NWB 标准格式输出 | DANDI 兼容，数据更完整 |

### 缺失但不影响功能（➖ 缺失类）

| 步骤 | 缺失内容 | 影响评估 |
|------|---------|---------|
| #1 | 录制时长/事件码统计日志 | 仅影响调试便利性 |
| #10 | 5 个诊断图（原始/diff/极性/延迟分布） | 影响 QC 可视化完整性 |
| #18 | PSTH / response_matrix_img | 设计选择——分析从 pipeline 分离到下游 |
