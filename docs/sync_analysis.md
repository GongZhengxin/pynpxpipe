# 同步模块深度分析报告

> 分析对象：`legacy_reference/pyneuralpipe/core/synchronizer.py`  
> 分析日期：2026-03-31  
> 分析目的：为 pynpxpipe 新架构的 synchronize stage 提供精确的迁移依据

---

## 1. `process_full_synchronization` 执行步骤

### 步骤 1 — `_prepare_sync_data()`（行 142–235）
**做了什么**：解析 IMEC 和 NIDQ 的数字事件流，提取各自的事件码时间序列，然后以 sync 脉冲作为参照，验证两设备的时钟对齐质量。

| 项目 | 内容 |
|------|------|
| **输入** | `sync_data['imec_sync']`（IMEC 数字通道，预加载数组）；`sync_data['nidq_digital']`（NIDQ 数字通道）；`sync_data['imec_meta']['imSampRate']`；`sync_data['nidq_meta']['niSampRate']`；config 中的 `digital_channel_map.sync` |
| **输出** | `self.Dcode_imec`：`{CodeLoc, CodeVal, CodeTime}` for IMEC 事件；`self.Dcode_ni`：`{CodeLoc, CodeVal, CodeTime}` for NIDQ 事件；`self.sync_line`：`{ni_sync_time, imec_sync_time, time_errors, mean_error, max_error, status}` |
| **验证** | 对比 NI/IMEC sync 事件数量是否一致；计算逐点时间误差；若 max_error > 17ms（可配置）则记录 warning（但不 raise！） |
| **可视化** | 无（在步骤 6 生成 sync 误差折线图） |

**关键实现细节**：
- IMEC 事件码提取：`np.diff(imec_sync)` → 取正值位置，CodeVal 是 diff 值（不是原始信号值）
- NIDQ 事件时间：取 diff 不为 0 的位置 +1（即变化后的采样点），CodeVal 是原始数字通道值（不是 diff 值）
- **硬编码 bug（行 201）**：IMEC sync 脉冲提取用 `CodeVal == 64`，而 NIDQ 侧用配置中的 `sync_bit`，两侧提取逻辑不对称，IMEC 侧完全绕过了配置

---

### 步骤 2 — `_check_ml_ni_alignment()`（行 237–331）
**做了什么**：统计 BHV2 和 NIDQ 中的 stimulus onset 总数及逐试次数量，核验一致性；若 trial start bit 映射错误则自动尝试修复。

| 项目 | 内容 |
|------|------|
| **输入** | `behavior_data['BehavioralCodes']['CodeNumbers']`（每个 trial 的 ML 事件码列表）；`self.Dcode_ni['CodeVal']`；config 中的 `stim_onset_code`（默认 64）、`trial_start_bit`（默认 1）、`stim_onset_bit`（默认 6） |
| **输出** | `self.onset_times_ml`（BHV2 onset 总数）；`self.onset_times_sglx`（NIDQ onset 总数）；`self.onset_comparison`（逐 trial 对比数据）；trial_start_bit 可能被自动修改 |
| **验证** | 逐 trial 对比 onset 数量，报告不一致的 trial 编号 |
| **自动修复** | 遍历 bit 0–7，找到与 ML trial 数一致的 bit 替换 `trial_start_bit`；bit 16 除外（硬排除） |
| **失败条件** | 自动修复失败时 raise `ProcessingError`（pipeline 中止）；onset 数量不一致时只记录 warning（不中止！） |
| **可视化** | 无（供步骤 6 的散点图使用） |

---

### 步骤 3 — `_extract_dataset_info()`（行 333–351）
**做了什么**：从 BHV2 的 `UserVars.DatasetName` 字段提取刺激集名称，用于后续文件命名和分组。

| 项目 | 内容 |
|------|------|
| **输入** | `behavior_data['UserVars']['DatasetName']`（每个 trial 的刺激集路径字符串） |
| **输出** | `self.dataset_name`（字符串）；`self.dataset_path`（Path 对象） |
| **边界处理** | DatasetName 为空时设为 `"unknown_dataset"`，不 raise |

---

### 步骤 4 — `_validate_eye_tracking()`（行 353–463）
**做了什么**：逐 trial、逐 stimulus 检查猴子的注视情况：若刺激呈现期间眼睛在固视窗口内的时间占比 > threshold，则标记为有效。同时把每个 stimulus 期间的眼动数据存入 eye_matrix。

| 项目 | 内容 |
|------|------|
| **输入** | `behavior_data['VariableChanges']['onset_time']`（刺激持续时间 ms）；`behavior_data['BehavioralCodes']['CodeNumbers/CodeTimes']`；`behavior_data['AnalogData']['Eye']`（眼动 x/y 数据）；`behavior_data['AnalogData']['SampleInterval']`；`behavior_data['VariableChanges']['fixation_window']`（固视窗口半径） |
| **输出** | `self.trial_valid_idx`（图片索引，0=无效）；`self.dataset_valid_idx`（数据集索引，0=无固视）；`self.eye_matrix`（形状 `(n_onsets, max_stim_dur, 2)`）；`self.valid_eye_count`；`self.imgset_size` |
| **验证** | 每个 onset 计算 `eye_valid_ratio = sum(eye_distance < fixwindow) / stim_dur`，与 threshold（默认 0.999）比较 |
| **可视化** | 无（数据供步骤 6 使用） |

**重要：**
- eye_distance 用 `np.linalg.norm(eye_data, axis=1)` 计算，是欧氏距离（2D），单位与 `fixation_window` 相同（视角度）
- 有 IndexError 边界处理：eye 数据索引超界时截断到最大有效索引

---

### 步骤 5 — `_calibrate_photodiode_timing()`（行 465–557）
**做了什么**：用 NIDQ 模拟通道的光敏二极管信号精确检测每个 stimulus 的实际显示时刻，校正数字事件码与实际显示的延迟差（帧级精度 → 亚毫秒精度），并将校准后的时间轴从 NI 时钟转换到 IMEC 时钟。

（详见第 2 节）

---

### 步骤 6 — `_generate_visualizations()`（行 559–683）
**做了什么**：生成 6 幅质检图（嵌入一个 3×6 subplot）和 1 幅独立同步误差图，全部以 base64 PNG 字符串存入 `self.visualizations`，供 Streamlit 显示。

（详见第 4 节）

---

### 步骤 7 — `_prepare_export_data()`（行 689–747）
**做了什么**：将所有中间结果打包为嵌套字典，准备写入 HDF5。

| 项目 | 内容 |
|------|------|
| **输入** | `self.onset_time_ms`、`self.stim_end_times`、`self.trial_valid_idx`、`self.dataset_valid_idx`、`self.eye_matrix`、`self.sync_line`、`self.params`、BHV2 文件路径 |
| **输出** | `self.export_data`（嵌套 dict，含 session_info、sync_info、trial_validation、eye_data、data_references、processing_params 六个子块） |
| **硬编码** | BHV2 文件名格式 `prefix_DATE_SUBJECT.bhv2`，用 `.split('_')[1:3]` 提取日期和动物名 |

---

### 步骤 8 — `_export_data_to_hdf5()`（行 970–976）
**做了什么**：将 `export_data` 写入 `{data_path}/processed/META_{session_name}.h5`。

| 项目 | 内容 |
|------|------|
| **输入** | `self.export_data`（嵌套 dict）；输出路径由 `__init__` 中硬编码为 `data_path / 'processed' / f'META_{data_path.name}.h5'` |
| **输出** | `META_*.h5` 文件（h5py，gzip 压缩数组，属性存标量） |

---

## 2. 光敏二极管 (Photodiode) 深度分析

### 2.1 信号来源

| 问题 | 答案 |
|------|------|
| **哪个通道** | NIDQ **模拟**通道，即 `nidq#XA0`（XA = Auxiliary Analog，通道 0）。这是 DataLoader 中的 `sync_data['nidq_analog']`，原始类型为 int16 |
| **模拟还是数字** | **模拟通道**。与数字事件码在不同通道（`nidq#XD0` 是数字通道） |
| **物理含义** | 光敏电阻贴在显示器角落，在刺激呈现时感应到亮度变化，通过 NI 模拟输入采集 |

### 2.2 Stimulus Onset 检测算法（逐步还原）

```
原始 int16 值
    │
    │ × (niAiRangeMax / 32768)    [int16 → 电压，niAiRangeMax 默认 5V]
    ▼
AIN  [单位：伏特，采样率 30000 Hz]
    │
    │ resample_poly(p=1, q=30)    [重采样到 1ms 分辨率]
    ▼
AIN_1ms  [每毫秒一个采样点]
    │
    │ 以数字触发时间为参考：
    │ 对每个 digital stim onset（bit 6 上升沿），提取窗口：
    │ [-10ms, +100ms]（共 110 个点）
    ▼
windows  [形状 (n_onsets, 110)]
    │
    │ zscore(每个窗口独立归一化)
    ▼
photodoide  [每行均值≈0，方差≈1]
    │
    │ 计算全局阈值（跨所有 trial）：
    │ baseline = mean(photodoide[:, 0:10])    # [-10, 0]ms，数字触发前
    │ peak_mean = mean(photodoide[:, 60:80])  # [60, 80]ms，刺激展示期
    │ threshold = 0.1 × baseline + 0.9 × peak_mean
    ▼
threshold  [单个标量，作用于所有 trial]
    │
    │ 对每个 trial：
    │ onset_latency[i] = (first index > threshold) - 10
    │ 若无超阈样本 → NaN → raise ProcessingError
    ▼
onset_latency  [每 trial 的光敏二极管延迟，单位 ms，相对数字触发]
    │
    │ stim_onset_ms += onset_latency      [校正到实际显示时刻]
    │ stim_onset_ms += (-5)               [monitor_delay_correction，60Hz 补偿]
    ▼
stim_onset_ms  [在 NI 时钟上的实际刺激时刻，ms]
    │
    │ np.interp(stim_onset_ms, ni_sync_time, imec_sync_time)
    │ [NI 时钟 → IMEC 时钟，分段线性插值]
    ▼
self.onset_time_ms  [在 IMEC 时钟上的刺激时刻，ms]
```

### 2.3 阈值检测方法的本质

这是**自适应首次超阈值检测**（Adaptive First-Crossing Threshold），不是峰值检测：

- **不是**找最大值，而是找第一个超过阈值的样本点
- threshold 是**全局标量**（跨所有 trial 共享），由所有 trial 的 z-score 归一化信号统计计算
  - 因为每个 trial 独立 z-score 后：baseline 均值 ≈ 0，stimulus 期均值 > 0（信号抬升）
  - threshold = 0.1 × 0 + 0.9 × (刺激期均值) ≈ 0.9 × 刺激期均值
- 优点：对信号幅度变化鲁棒（z-score 使幅度归一化）
- 缺点：若某个 trial 的信号质量差（低 SNR），z-score 会放大噪声，导致假阳性超阈

### 2.4 精度提升量

| 方案 | 时间精度 | 误差来源 |
|------|---------|---------|
| 纯数字事件码（bit 触发时刻） | ~0.033ms（采样率精度） | **测量的是 ML 发送触发的时刻，不是显示器实际显示的时刻** |
| 加 photodiode 校准 | ~1ms（受重采样分辨率限制） | 测量的是实际光子发出的时刻 |

**精度提升的核心不是时钟分辨率，而是消除显示延迟**：

对于 60Hz 显示器：
- 数字触发 → 实际显示：系统延迟 + 帧同步等待 = 0–16.7ms（一帧内的随机相位 + 系统延迟）
- 帧间抖动的标准差：≈ 16.7/√12 ≈ 4.8ms（均匀分布假设）
- 加上 monitor_delay_correction (-5ms) 修正系统偏移后，残余抖动 ≈ 1ms

**实际收益**：stimulus onset 时间精度从 ±~5ms 提升至 ±~1ms，对于分析短潜伏期神经响应（如 V1 的 ~50ms 响应）意义重大。

### 2.5 边界情况处理

| 场景 | 处理方式 | 是否足够 |
|------|---------|---------|
| 某 trial 无样本超阈（信号未上升） | 检测 NaN，raise `ProcessingError`，报告具体 trial 编号 | ✅ |
| 信号在触发前就超阈（噪声/伪信号） | **未处理**：会返回一个极小的负 onset_latency | ❌ |
| 多次超阈（振荡/反射） | **未处理**：`first` 超阈即采用，后续振荡被忽略 | ⚠️ 可接受 |
| 窗口越界（第一个 onset 在录制开始后 <10ms） | **未处理**：`start_time = stim_onset_ms - 10` 可能为负，数组索引出错 | ❌ |
| 光敏二极管接头松动（信号接近 0） | **未处理**：z-score 会放大噪声至正常量级，可能通过阈值但时间不准 | ❌ |
| 信号饱和（贴得太近，截幅） | **未处理**：影响 threshold 计算，可能高估 onset | ❌ |

---

## 3. 硬编码值完整清单

### 3.1 直接硬编码（magic number）

| 位置 | 代码 | 硬编码值 | 语义 | 新架构放置位置 |
|------|------|---------|------|--------------|
| `_prepare_sync_data()` L201 | `self.Dcode_imec['CodeVal'] == 64` | **64** | IMEC 数字通道上的 sync 脉冲事件码 | `config/pipeline.yaml: sync.imec_sync_code`（或从信号自动检测：选频率约 1Hz 的码值） |
| `_validate_eye_tracking()` L397 | `trial_codes == 64` | **64** | BHV2 中的 stim onset 事件码 | `config/pipeline.yaml: sync.stim_onset_code`（已存在于 config 但本函数未读取！） |
| `_calibrate_photodiode_timing()` L469 | `niAiRangeMax` default `5` | **5 V** | NI 模拟输入量程 | 应从 `nidq_meta['niAiRangeMax']` 读取（已实现，仅是 fallback 硬编码，可接受） |
| `_generate_visualizations()` L634-635 | `binx = np.arange(-8, 8.5, 0.5)` | **±8°** | 眼动密度图的坐标范围 | `config/pipeline.yaml: visualization.eye_position_range_deg` |
| `_prepare_export_data()` L693 | `.name.split('_')[1:3]` | **`_` 分隔符，位置 1 和 2** | BHV2 文件名格式假设（`prefix_DATE_SUBJECT.bhv2`） | 改为从 BHV2 内容读取 session info，或在 Session 对象中显式存储 |
| `_prepare_sync_data()` L165 | `niSampRate` fallback `30000` | **30000 Hz** | NI 采样率默认值 | 应强制从 meta 读取，不提供 fallback（meta 缺失应直接报错） |
| `_prepare_sync_data()` L150 | `imec_default` fallback `30000` | **30000 Hz** | IMEC 采样率默认值 | 同上 |

### 3.2 隐式硬编码（结构性假设）

| 位置 | 假设内容 | 风险 | 新架构处理方式 |
|------|---------|------|--------------|
| `__init__` L53 | `data_loader.get_spikeglx_data()` 返回单个 Recording | 不支持多 probe | 改为接收 `session.probes: list[ProbeInfo]`，循环处理 |
| `__init__` L56 | `data_loader.get_sync_data()` 返回包含 `imec_sync` 的单 dict | 假设只有 imec0 的 sync | 改为 `sync_data: dict[str, array]`，key 为 probe_id |
| `_calibrate_photodiode_timing()` L472–473 | `sync_data['nidq_analog']` 是单列（`np.squeeze`） | 如果有多路模拟输入，会错误地挤压维度 | 明确指定 photodiode 通道索引：`config/pipeline.yaml: sync.photodiode_channel_index` |
| `_calibrate_photodiode_timing()` L548 | `np.interp(stim_onset_ms, ni_sync_time, imec_sync_time)` | 假设 sync 是 imec0 | 对每个 probe 各有一个 `interp` 函数 |
| `_validate_eye_tracking()` L378–379 | `max_dur` 用第一个或最大 `stim_ondur` | 假设所有刺激等时长 | 对每个 onset 单独处理，不预分配全局矩阵 |
| `_generate_visualizations()` L12 | `matplotlib.use('Agg')` | 在 Streamlit 之外（如 Jupyter）有副作用 | 不在业务逻辑中调用 matplotlib，改为返回数据，由 CLI/GUI 层负责渲染 |
| `__init__` L69 | `self.h5_file = data_path / 'processed' / f'META_{data_path.name}.h5'` | 输出目录结构硬绑定 | 新架构改为 `session.output_dir / 'sync' / 'behavior_events.parquet'` |

### 3.3 从配置读取但 fallback 值有问题的参数

| 参数 | 配置路径 | 默认值 | 问题 |
|------|---------|------|------|
| `stim_onset_code` | `code_mappings.stim_onset` | 64 | `_check_ml_ni_alignment` 正确读取；`_validate_eye_tracking` **忽略**，用 magic 64 |
| `trial_start_bit` | `digital_channel_map.trial_start` | 1 | 自动修复逻辑中跳过 bit 4（值=16），但注释说 `new_code != 16`，应为 bit 4（16 = 1 << 4） |
| `stim_onset_bit` | `digital_channel_map.stim_onset` | 6 | 正确读取，但 `_prepare_sync_data` 中的 IMEC 侧不用此值 |

---

## 4. 可视化与验证步骤

### 4.1 现有可视化（步骤 6）

`_generate_visualizations` 生成以下图表，以 base64 PNG 字符串存入 `self.visualizations`：

| 图编号 | subplot 位置 | 内容 | 用途 | 注意事项 |
|--------|------------|------|------|---------|
| 1 | (1,1) 第1格 | SGLX 逐 trial onset 数 vs ML 逐 trial onset 数（散点图），标题显示 MaxErr | 发现哪些 trial 的 onset 数不一致 | 理想情况所有点在对角线上 |
| 2 | (1,2) 第2格 | 校准后 photodiode 信号热力图（imshow），x 轴为时间 [-10ms, +100ms]，y 轴为 trial | 总览所有 trial 的光敏二极管对齐质量 | 应看到明显的横向亮带在 t=0 右侧 |
| 3 | (2,1) 第7格 | 所有 trial 的校准后平均 photodiode 信号（mean ± std） | 验证 onset 对齐是否一致 | 若不对齐，onset 处的陡升会被抹平 |
| 4 | (2,3) 第9格 | 排除非注视 trial 后的平均 photodiode 信号 | 验证注视筛选对信号质量的影响 | 与图3对比，理想情况变化不大 |
| 5 | (2,5) 第11格 | 各图片索引的呈现次数（折线图） | 验证刺激均匀采样 | 若某图片次数为 0 说明有数据丢失 |
| 6 | (2,6) 第12格 | 眼动平均位置的 2D 密度图（log scale，直方图） | 验证注视位置是否集中在中心 | 应呈现以 (0,0) 为中心的热点 |
| 7 | 独立图 | NI↔IMEC sync 误差折线图（每个 sync 事件一个点） | 验证全 session 时钟稳定性 | 若有跳变说明录制中有中断 |

**局限性**：
- 图 1–6 嵌在同一个 3×6 figure 中，但代码只填充了 6 个 subplot 中的 6 个位置（位置编号非连续），其余 12 个 subplot 位置为空
- 所有图以 base64 字符串存储，与 Streamlit 强耦合（不能在 CLI 模式下保存为文件）

### 4.2 缺失的关键诊断图（新架构建议补充）

| 建议图 | 所在节点 | 内容 | 重要性 |
|--------|---------|------|--------|
| **Sync pulse 时间误差 vs 时间**（已有）| `_prepare_sync_data` 后 | 横轴为录制时间（min），纵轴为 NI-IMEC 误差（ms） | 高（检测录制中断） |
| **Pre-校准 vs Post-校准 photodiode 均值对比** | `_calibrate_photodiode_timing` 后 | 两条曲线叠加：数字触发对齐 vs photodiode 对齐 | **高**（直观展示校准收益） |
| **onset_latency 分布直方图** | `_calibrate_photodiode_timing` 后 | 每个 trial 的光敏二极管延迟值直方图 | 高（发现离群 trial，诊断显示器抖动） |
| **IMEC 同步脉冲频率漂移** | `_prepare_sync_data` 后 | 相邻 sync 脉冲间隔 vs 期望间隔（应为 1s） | 中（检测 IMEC 时钟不稳定） |
| **眼动轨迹时序图**（按 trial 排列） | `_validate_eye_tracking` 后 | 每个 trial 的眼动 x/y 时序，标注 onset | 中（诊断系统性眼漂移） |
| **BHV2 vs NIDQ 事件码时间差分布** | `_check_ml_ni_alignment` 后 | BHV2 trial onset ms 与 NIDQ 推算的 trial onset ms 之差 | 中（独立验证两侧对齐） |

---

## 5. 新架构迁移注意事项

### 5.1 必须修复的 bug

1. **行 201 硬编码 `== 64`**：IMEC sync 脉冲检测应从配置读取，或通过信号分析自动检测（找到近似 1Hz 的码值）
2. **行 397 硬编码 `== 64`**：`_validate_eye_tracking` 必须使用 `config.sync.stim_onset_code`（与 `_check_ml_ni_alignment` 保持一致）
3. **行 379 预分配全量矩阵**：`eye_matrix = np.nan * np.zeros((onset_times, max_dur, 2))` 改为按 trial 分块处理，返回 DataFrame 而不是 3D 矩阵

### 5.2 架构重构要点

| 旧设计 | 新架构 |
|--------|--------|
| `DataSynchronizer` 单类包含所有逻辑 | 拆分为 `SynchronizeStage` + `io/spikeglx.py` 的 sync edge 提取 + `io/bhv.py` 的 BHV2 解析 |
| 输出为 HDF5 + base64 PNG（Streamlit 格式） | 输出为 `sync_tables.json` + `behavior_events.parquet`；图像由 CLI/GUI 层按需生成 |
| 假设单 probe（imec0） | 对每个 probe 循环调用 `_align_probe_to_nidq()`，产生每 probe 独立的校正函数 |
| 内嵌 matplotlib（`matplotlib.use('Agg')`）| 诊断图生成函数独立出来，Stage 层不 import matplotlib |
| 方法内直接 raise `ProcessingError`（自定义类） | raise `SyncError`（继承自 `StageError`，不依赖旧的 `error_handler` 模块） |
| eye_matrix 写入 HDF5 export | eye_matrix 不在 synchronize stage 处理（眼动校验可独立为 postprocess 的可选步骤） |

### 5.3 photodiode 校准的精确复现要求

新架构 `_calibrate_photodiode_timing()` 必须满足：
1. 模拟通道索引必须可配置（`config.pipeline.sync.photodiode_channel_index: 0`）
2. 重采样比率必须用 `Fraction` 精确计算（不能用 `round`），与旧代码一致
3. z-score 归一化必须**逐 trial 独立**进行（现有代码已是逐 trial，正确）
4. threshold 是**全局标量**（跨 trial 共享），这是算法设计，不是 bug，需保留
5. onset_latency < 0（超阈在触发前）需检测并记录警告（旧代码未处理）
6. 最终 `np.interp` 的插值方向确认：`interp(ni_time, ni_sync_time, imec_sync_time)` → IMEC 时钟（与 spike times 的时钟一致）
