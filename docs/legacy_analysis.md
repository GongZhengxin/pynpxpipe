# PyNeuralPipe Legacy Codebase 分析报告

> 分析对象：`legacy_reference/pyneuralpipe/`  
> 分析日期：2026-03-31  
> 分析目的：为新项目 pynpxpipe 提供迁移参考

---

## 1. Pipeline 总览

### 完整处理流程

```
原始数据（.bin/.meta + .bhv2）
       │
       ▼
[Step 1] DataLoader.load_spikeglx() + load_monkeylogic()
   输入：SpikeGLX 数据文件夹（NPX_*）、MonkeyLogic .bhv2 文件
   输出：spikeglx_data (Recording对象)、monkeylogic_data (dict)、sync_data (dict)
       │
       ▼
[Step 2] DataLoader.validate_data()
   输入：已加载的数据
   输出：验证通过/失败，issues 列表
       │
       ▼
[Step 3] SpikeSorter.run_full_pipeline()（可选，若已有 KS 结果可跳过）
   输入：Recording 对象或 SpikeGLX 文件夹路径
   子步骤：
     - load_recording()：获取 Recording 对象
     - preprocess()：高通滤波 → 坏道检测 → 相位校正 → 共同参考 → 保存 Zarr 临时文件
     - run_kilosort()：调用 Kilosort4 → 创建 SortingAnalyzer → 后处理扩展
   输出：kilosort_output/ 目录（spike_times.npy、spike_clusters.npy 等）
       │
       ▼
[Step 4] DataSynchronizer.process_full_synchronization()
   输入：DataLoader 实例（包含 sync_data、behavior_data）
   子步骤：
     - _prepare_sync_data()：解析 IMEC/NI 数字事件流
     - _check_ml_ni_alignment()：ML 与 NI 试次/onset 数量核对
     - _extract_dataset_info()：从 UserVars 提取数据集名称
     - _validate_eye_tracking()：逐 onset 检查固视比例 > 0.999
     - _calibrate_photodiode_timing()：zscore 标准化 → 峰值检测 → 时间对齐到 IMEC 时钟
     - _generate_visualizations()：生成数据质检图（base64 PNG）
     - _export_data_to_hdf5()：保存 META_*.h5
   输出：processed/META_<session>.h5（含 onset_time_ms、trial_valid_idx、eye_matrix 等）
       │
       ▼
[Step 5] QualityController.setup_bombcell_params() + run_quality_control()
   输入：kilosort_output_path、imec_data_path（可选）
   输出：qMetric (dict)、unitType (array: 0=noise, 1=good, 2=mua, 3=no-somatic)
         bombcell/ 目录（.csv、.npy 文件）
       │
       ▼
[Step 6] DataIntegrator.run_full_pipeline()
   输入：data_path（包含 SpikeGLX、processed/、bombcell/ 的 session 根目录）
   子步骤：
     - step1_convert_raw_data()：neuroconv SpikeGLXConverterPipe → NWB 原始数据
     - step2_add_kilosort_results()：KiloSortSortingInterface → NWB processing/ecephys
     - step3_add_behavioral_data()：读 META h5 → 写 trials + EyeTracking + Stimulus
     - step4_add_custom_units()：Raster 计算 + Mann-Whitney 筛选 + Bombcell 指标 → NWB units
   输出：NWBFile_<session_id>.nwb
```

### 处理流程要点

- **同步校准先于 NWB 整合**：Synchronizer 输出的 HDF5 文件（META_*.h5）是 DataIntegrator 的输入源
- **KS 输出路径约定**：`processed/SI/KS4/sorter_output/`；Bombcell：`processed/SI/bombcell/`
- **可独立运行各步骤**：DataIntegrator 通过检查文件是否存在来决定跳过已完成步骤

---

## 2. 模块职责

### 2.1 `core/data_loader.py` — DataLoader（约 1280 行）

**核心功能**：加载 SpikeGLX 神经数据和 MonkeyLogic 行为数据

| 方法 | 功能 |
|------|------|
| `load_spikeglx()` | 调用 `si.read_spikeglx()` 加载 AP 数据；另加载 nidq 模拟/数字信号和 imec 同步信号 |
| `_find_spikeglx_folder()` | 搜索以 `NPX` 开头或含 .bin/.meta 文件的子文件夹 |
| `_load_nidq_sync_data()` | 加载 `nidq#XA0`（光敏二极管）和 `nidq#XD0`（数字信号） |
| `_load_imec_sync_data()` | 加载 `imec0.lf-SYNC` 流的 `imec0.lf#SY0` 同步信号 |
| `load_monkeylogic()` | MATLAB 引擎调用 mlread → 保存 .mat → h5py/scipy.io 加载 → 缓存 |
| `_convert_bhv2_to_mat()` | matlab.engine 调用 `mlread()` 函数，保存 v7.3 格式 |
| `_load_h5py_recursive()` | 递归解析 HDF5 格式 MAT 文件（含 struct array → list 转换） |
| `_normalize_scalar/array()` | 浮点整数值转 Python int，统一数组类型（消除 h5py/scipy 差异） |
| `validate_data()` | 检查采样率（10kHz-100kHz）、通道数、试次数、行为代码字段完整性 |

**关键依赖**：`spikeinterface.full`、`scipy.io`、`h5py`、`matlab.engine`（可选）、`pickle`（缓存）

**缓存机制**：MD5 hash（文件前 1MB + 大小 + mtime）+ 版本字符串 `"v2.2_eye_no_double_transpose"` 验证，缓存保存为 `.pkl`

---

### 2.2 `core/synchronizer.py` — DataSynchronizer（约 1050 行）

**核心功能**：精确对齐神经数据与行为数据时间轴，复现 MATLAB `Load_Data_function.m`

| 方法 | 功能 |
|------|------|
| `_prepare_sync_data()` | 解析 IMEC 和 NI 数字事件（np.diff），计算事件时间（ms），验证 NI↔IMEC 同步误差 |
| `_check_ml_ni_alignment()` | 统计 ML 和 NI 的 onset/trial 数量，自动修复 trial bit 映射不匹配 |
| `_validate_eye_tracking()` | 逐 onset 提取眼动数据段，计算注视比例（vs 固视窗口），阈值 0.999 |
| `_calibrate_photodiode_timing()` | 重采样 NI 模拟信号至 1ms → zscore → 峰值检测延迟 → 插值对齐到 IMEC 时钟 |
| `_prepare_export_data()` | 打包 onset_time_ms、trial_valid_idx、eye_matrix 等 |
| `_export_data_to_hdf5()` | 保存 META_<session>.h5 |

**光敏二极管校准原理**：
1. NI 模拟信号重采样至 1ms/sample
2. 每个 onset 前后截取窗口（-10ms 到 +100ms）
3. zscore 标准化后计算阈值（基线×0.1 + 峰值×0.9）
4. 找到超阈值的第一个样本点，计算延迟
5. 加上 `monitor_delay_correction = -5ms`（60Hz 显示器补偿）
6. `np.interp()` 将 NI 时间轴插值到 IMEC 时间轴

**关键依赖**：`scipy.signal.resample_poly`、`scipy.stats.zscore`、`scipy.interpolate`（通过 np.interp）、`h5py`

---

### 2.3 `core/spike_sorter.py` — SpikeSorter（约 832 行）

**核心功能**：调用 Kilosort4 进行尖峰排序，支持两种数据源

| 方法 | 功能 |
|------|------|
| `from_recording(recording)` | 类方法：从预加载 Recording 对象初始化 |
| `from_folder(folder_path)` | 类方法：从 SpikeGLX 文件夹路径初始化 |
| `load_recording()` | 验证 Recording 对象或从文件夹加载 `imec0.ap` 流 |
| `preprocess()` | Protocol Pipeline 或传统手动预处理，输出 Zarr 格式到 `KS_TEMP/` |
| `run_kilosort()` | 调用 `si.run_sorter('kilosort4')` → 创建 SortingAnalyzer → 后处理扩展 |
| `_load_kilosort_outputs()` | 加载 `sorter_output/` 下的 .npy/.tsv 文件，计算发放率 |
| `_cleanup_temp_folder()` | 删除 Zarr 临时文件夹 |

**两种运行模式**：
- **Protocol Pipeline**（推荐）：`si.apply_preprocessing_pipeline()` → `si.run_sorter()` → `si.create_sorting_analyzer()` → `analyzer.compute(postprocessing_protocol)`
- **传统模式**：手动调用 `si.highpass_filter` → `si.detect_bad_channels` → `si.phase_shift` → `si.common_reference`

#### 预处理链详细分析

**Protocol Pipeline 实际执行顺序**（由 `spike_sorter.yaml` 的 `preprocessing` 字典顺序决定）：

| 步骤 | SI 函数 | 参数 | 说明 |
|------|---------|------|------|
| 1 | `si.highpass_filter` | `freq_min=300.0` | 仅高通，无上限截止频率 |
| 2 | `si.detect_bad_channels` + `.remove_channels` | （默认参数）| 组合为单步 `detect_and_remove_bad_channels` |
| 3 | `si.phase_shift` | — | **位置错误**：应在滤波之前执行 |
| 4 | `si.common_reference` | `operator='median'`, `reference='global'` | 全局中位数共同参考 |

**传统手动模式执行顺序**（`spike_sorter.py` 行 310–331）：

| 步骤 | SI 函数 | 备注 |
|------|---------|------|
| 1 | `si.highpass_filter(freq_min=300.0)` | 同 Protocol Pipeline，仅高通 |
| 2 | `si.detect_bad_channels` | 检测坏道 |
| 3 | `recording.remove_channels(bad_channel_ids)` | 移除坏道 |
| 4 | `si.phase_shift` | **同样位置错误** |
| 5 | `si.common_reference(operator='median', reference='global')` | |

**关键问题**：

1. **phase_shift 位置错误**：相位校正应在高通滤波之前执行（先校正因 IMEC ADC 多路转换引入的采样时间偏移，再滤波），legacy 两种模式均将 phase_shift 置于高通滤波之后，属次优顺序。pynpxpipe 新设计：`phase_shift` → `bandpass_filter` → `bad_channel_detection` → `common_reference`。

2. **仅高通滤波，无上限截止频率**：legacy 只设 `freq_min=300 Hz`，不设 `freq_max`。神经尖峰信号有效频段约 300–6000 Hz，缺少低通滤波会保留高频噪声，对 Kilosort4 的模板匹配质量有影响。pynpxpipe 新设计改用带通滤波器（300–6000 Hz）。

3. **运动校正完全缺失**：legacy 预处理链中没有任何运动校正（drift correction）步骤。pynpxpipe 新设计在 CMR 之前加入 DREDge 运动校正（`si.correct_motion`），与 Kilosort4 内置的 `nblocks` 运动估计互斥——二者不同时开启。

4. **单元位置估计方法**：`postprocessing_protocol` 中 `unit_locations` 使用 `method='center_of_mass'`（legacy），该方法对深层探针精度较低。pynpxpipe 新设计改用 `monopolar_triangulation`，对线性探针精度更高。

**发放率计算**（行 600，硬编码）：
```python
self.firing_rates = counts * 30000 / self.spike_times.max()
```

**关键依赖**：`spikeinterface.full`、`spikeinterface.sorters`、`kilosort.io.load_ops`、`zarr`（隐式）

---

### 2.4 `core/quality_controller.py` — QualityController（约 486 行）

**核心功能**：调用 Bombcell Python API 进行单元质量控制

| 方法 | 功能 |
|------|------|
| `setup_bombcell_params()` | `bc.get_default_parameters()` + 覆盖 tauR 参数（1.5-2.4ms ISI 不应期窗口） |
| `run_quality_control()` | `bc.run_bombcell()` → 返回 qMetric、unitType、figures |
| `get_good_units()` | 返回 `unitType >= 1` 的索引（包括 good + mua + no-somatic） |
| `filter_units_by_criteria()` | 在 Bombcell 结果上叠加自定义阈值过滤 |
| `get_quality_metrics_df()` | 转换为 DataFrame，含 unitType 和 unit_type_strings 列 |

**单元分类**：
- `1` = good（单个孤立单元）
- `2` = mua（多单元活动）
- `3` = no-somatic（非胞体尖峰，如轴突）
- `0` = noise（噪声，丢弃）

**关键依赖**：`bombcell`（Python 版）、`numpy`、`pandas`

---

### 2.5 质控与分类（bombcell）

**核心文件**：
- `Util/BC/bombcell_pipeline.m` — MATLAB 主入口
- `Util/BC/+bc/+qm/runAllQualityMetrics.m` — 计算 28+ 质量指标
- `Util/BC/+bc/+qm/getQualityUnitType.m` — 单元分类逻辑
- `Util/BC/+bc/+clsfy/classifyCells.m` — 细胞分类（体细胞 vs 非体细胞）
- `core/quality_controller.py` — Python 包装器（调用 MATLAB 引擎）
- `utils/nwb_bombcell_helper.py` — 将 bombcell 结果写入 NWB

**Bombcell 功能**：计算 28+ 质量指标，将单元分类为 NOISE / MUA / GOOD / NON-SOMATIC 四类。

**计算的质量指标**（三大类）：

1. **污染指标**：
   - `percentageSpikesMissing_gaussian` — 基于高斯拟合估计的漏检尖峰比例
   - `percentageSpikesMissing_symmetric` — 对称分布拟合的漏检比例
   - `fractionRPVs_estimatedTauR` — 不应期违规比例（自适应 tauR 估计，1.5-2.5ms）
   - `presenceRatio` — 单元在记录时长中的存在比例（60s bin）

2. **波形指标**：
   - `nPeaks` / `nTroughs` — 波形峰/谷数量
   - `waveformDuration_peakTrough` — 峰到谷持续时间（μs）
   - `spatialDecaySlope` — 空间衰减斜率（线性/指数拟合）
   - `waveformBaselineFlatness` — 基线平坦度（基线噪声 / 峰值幅度）
   - `scndPeakToTroughRatio` — 第二峰与谷的比值
   - `mainPeakToTroughRatio` — 主峰与谷的比值
   - `peak1ToPeak2Ratio` / `troughToPeak2Ratio` — 用于非体细胞检测

3. **幅度与漂移**：
   - `rawAmplitude` — 原始幅度（μV）
   - `signalToNoiseRatio` — 信噪比
   - `maxDriftEstimate` — 最大漂移（μm，60s bin）
   - `cumDriftEstimate` — 累积漂移（μm）
   - 可选隔离度指标：`isolationDistance`、`Lratio`、`silhouetteScore`（需 PCA 特征）

**分类逻辑**（unitType 值，来自 `getQualityUnitType.m`）：

- **unitType = 0 (NOISE)**：满足任一条件即判定为噪声
  - `nPeaks > 2` 或 `nTroughs > 1`
  - `waveformDuration < 100μs` 或 `> 1150μs`
  - `waveformBaselineFlatness > 0.3`
  - `spatialDecaySlope` 超出合理范围（线性 < -0.008 或指数 < 0.01 / > 0.1）
  - `mainPeakToTroughRatio > 0.8`

- **unitType = 2 (MUA)**：通过噪声过滤但未达到 GOOD 标准
  - 未满足以下任一条件：
    - `percentageSpikesMissing < 20%`
    - `nSpikes > 300`
    - `fractionRPVs < 10%`
    - `presenceRatio > 80%`
    - `rawAmplitude > 20μV`
    - `signalToNoiseRatio > 1`
    - `maxDriftEstimate < 100μm`（可选）
  - 可选隔离度条件：`isolationDistance > 20`、`Lratio < 0.1`

- **unitType = 1 (GOOD)**：通过所有 MUA 标准

- **unitType = 3 (NON-SOMATIC)**：GOOD 或 MUA 单元，但波形特征表明非体细胞记录
  - `troughToPeak2Ratio < 5` 且 `mainPeak_before_width < 4` 且 `mainTrough_width < 5` 且 `peak1ToPeak2Ratio > 3`
  - 或 `mainPeakToTroughRatio > 0.8`

**硬编码阈值**（来自 `qualityParamValues.m`）：

| 参数 | 值 | 说明 |
|------|-----|------|
| `tauR_valuesMin` | 1.5 ms | 不应期估计下限 |
| `tauR_valuesMax` | 2.5 ms | 不应期估计上限 |
| `tauC` | 0.1 ms | 重复尖峰剔除窗口 |
| `nRawSpikesToExtract` | 100 | 每单元提取波形数 |
| `presenceRatioBinSize` | 60 s | 存在比例时间窗 |
| `driftBinSize` | 60 s | 漂移估计时间窗 |
| `maxRPVviolations` | 0.1 (10%) | MUA vs GOOD 阈值 |
| `minPresenceRatio` | 0.8 (80%) | MUA vs GOOD 阈值 |
| `minAmplitude` | 20 μV | MUA vs GOOD 阈值 |
| `minSNR` | 1 | MUA vs GOOD 阈值 |
| `maxDrift` | 100 μm | MUA vs GOOD 阈值（可选） |

**新版本迁移**：pynpxpipe 使用 SpikeInterface `quality_metrics` 替代 MATLAB bombcell，覆盖大部分相同指标（除 `waveformBaselineFlatness` 需自定义实现）。分类逻辑改为配置文件驱动，阈值可调。

---

### 2.6 `core/data_integrator.py` — DataIntegrator（约 1150 行）
- `nRawSpikesToExtract`：100（用于波形提取）
- `presenceRatioBinSize`：60s
- `maxRPVviolations`：0.1（10% 不应期违规上限）
- `minPresenceRatio`：0.8（80% 存在比例下限）
- `minAmplitude`：20μV
- `minSNR`：1
- `maxDrift`：100μm

**新版本改进**：pynpxpipe 使用 SpikeInterface 内置 `quality_metrics` 模块替代 MATLAB bombcell，覆盖大部分相同指标（ISI violations、presence ratio、amplitude cutoff、SNR、drift 等），无需 MATLAB 依赖，计算效率更高。

---

### 2.6 `core/data_integrator.py` — DataIntegrator（约 818 行）

**核心功能**：将所有处理结果整合为标准 NWB 文件

| 方法 | 功能 |
|------|------|
| `step1_convert_raw_data()` | neuroconv `SpikeGLXConverterPipe` → 写入 AP+LF 原始数据（Blosc/zstd 压缩） |
| `step2_add_kilosort_results()` | `KiloSortSortingInterface` → `processing/ecephys/kilosort4_unit` |
| `step3_add_behavioral_data()` | 读 META h5 → 添加 trials 表 + EyeTracking（SpatialSeries）+ 刺激图片 |
| `step4_add_custom_units()` | 计算 Raster（-50~300ms bins）→ Mann-Whitney U 检验 → 写入 NWB units 表 |
| `_compute_unit_response()` | 逐 trial 截取尖峰，对齐到 onset，计算直方图 |
| `_statistical_test()` | Mann-Whitney U，baseline[-25,25ms] vs response[60,220ms]，p < 0.001 |
| `_prepare_waveforms()` | 提取 Bombcell 原始波形，保存峰值通道周围 ±6 通道 |

**关键依赖**：`pynwb`、`neuroconv`、`h5py`、`scipy.stats.mannwhitneyu`、`tqdm`

---

### 2.7 `utils/` — 工具模块

| 文件 | 功能 |
|------|------|
| `config_manager.py` | 分布式 YAML 配置加载，单例模式，各模块独立配置文件 |
| `logger.py` | ProcessLogger：步骤跟踪（start_step/complete_step）、性能计时、日志文件 |
| `error_handler.py` | `@error_boundary` 装饰器、DataLoadError/ProcessingError/ValidationError |
| `directory_checker.py` | 检查 session 目录结构，确定当前处理阶段 |
| `nwb_stim_helper.py` | 管理刺激图片，添加到 NWB |
| `nwb_bombcell_helper.py` | 将 Bombcell qMetric DataFrame 列映射到 NWB units 表 |

---

## 3. 配置体系

### 3.1 配置文件架构

ConfigManager 采用**分布式独立文件**设计（非单一 app_config.yaml），文件位于 `config/`：

| 配置文件 | 对应模块 | 核心参数 |
|---------|---------|---------|
| `data_loader.yaml` | DataLoader | SpikeGLX 流名、数字通道位映射、ML 代码映射 |
| `synchronizer.yaml` | DataSynchronizer | 眼动阈值、光敏二极管窗口、最大同步误差 |
| `spike_sorter.yaml` | SpikeSorter | Protocol Pipeline 三段配置 |
| `quality_controller.yaml` | QualityController | Bombcell 质量阈值、分类标准 |
| `data_integrator.yaml` | DataIntegrator | 文件夹结构、NWB 压缩、Raster 时间窗口、筛选参数 |

### 3.2 关键配置值

```yaml
# data_loader.yaml
spikeglx:
  stream_name: 'imec0.ap'
  digital_channel_map:
    sync: 0        # bit 0：同步脉冲
    trial_start: 3 # bit 3：试次开始
    stim_onset: 6  # bit 6：刺激 onset（=64）

monkeylogic:
  code_mappings:
    stim_onset: 64   # ML behavioral code
    stim_offset: 32

# synchronizer.yaml
eye_tracking:
  threshold: 0.999           # 固视合格比例
photodiode:
  monitor_delay_correction: -5  # 显示器延迟校正 ms
sync_validation:
  max_time_error: 17.0        # 同步最大误差 ms

# spike_sorter.yaml
spike_sorting_pipeline:
  sorting:
    sorter_name: 'kilosort4'
    nblocks: 15
    Th_learned: 7.0
    n_jobs: 12

# data_integrator.yaml
units:
  raster:
    pre_onset_ms: 50
    post_onset_ms: 300
    baseline_window_ms: [-25, 25]
    response_window_ms: [60, 220]
  filtering:
    p_value_threshold: 0.001
    statistical_test: "mannwhitneyu"
    exclude_bombcell_zero: true
```

### 3.3 monkeys/ subject 配置

每个 subject 一个 YAML 文件，符合 DANDI 标准：

```yaml
# MaoDan.yaml / JianJian.yaml
Subject:
  subject_id: "MaoDan"
  description: "good monkey"
  species: "Macaca mulatta"   # DANDI required
  sex: "M"                    # DANDI required
  age: "P4Y"                  # ISO 8601 duration
  weight: "12.8kg"
```

当前有 `MaoDan.yaml`（12.8kg）和 `JianJian.yaml`（6.4kg）两个受试猴配置。

---

## 4. 已知问题清单

### 4.1 硬编码路径与参数

| 位置 | 硬编码内容 | 风险 |
|------|-----------|------|
| `synchronizer.py:397` | `stim_onset_loc = np.where(trial_codes == 64)[0]` | 无视配置中的 `stim_onset_code`，固定为 64 |
| `spike_sorter.py:600` | `counts * 30000 / self.spike_times.max()` | 采样率硬编码为 30000 Hz，其他采样率结果错误 |
| `data_integrator.py:204` | `ap_config.chunk_shape = (1, 64)` | chunk_shape 先被硬编码为 (1,64) 后再从配置覆盖，逻辑混乱 |
| `data_integrator.py:214` | `lf_config.chunk_shape = (1, 64)` | 同上 |
| `data_integrator.py:139` | `self.info_yaml = Path(__file__).parent.parent / "config" / info_yaml` | subject yaml 路径固定在代码内的 config 目录 |
| `data_loader.py:198-203` | `channel_ids=['nidq#XA0']`, `['nidq#XD0']` | 通道 ID 硬编码，多路采集时不适用 |
| `data_loader.py:224` | `stream_name='imec0.lf-SYNC'` | 探针编号硬编码为 imec0 |
| `synchronizer.py:201` | `np.where(self.Dcode_imec['CodeVal'] == 64)[0]` | 同步事件值 64 硬编码 |
| `spike_sorter.py:~340` | `'chunk_duration': '4s'` | job_kwargs 中 chunk_duration 硬编码为 4s，在 Protocol Pipeline 路径和传统路径均如此（两处 fallback 值均为 `'4s'`） |
| `spike_sorter.py:~339` | `'n_jobs': 12` | job_kwargs 中 n_jobs 硬编码为 12，未从系统资源自动探测 |
| `synchronizer.py` | `monitor_delay_correction = -5` | 显示器延迟校正值 -5ms 在代码内直接赋值，虽然 synchronizer.yaml 中有对应配置项，但代码读取路径不明确 |
| `spike_sorter.yaml` | `unit_locations.method: 'center_of_mass'` | 单元位置估计方法硬编码在配置文件中，用户若不手动修改配置将始终使用精度较低的 center_of_mass |
| `spike_sorter.yaml` | Protocol Pipeline 预处理顺序固定 | YAML 字典顺序决定预处理链执行顺序，Python 3.7+ 保证插入顺序；用户若调整 YAML 中条目顺序，将改变预处理步骤顺序，但无任何文档说明此依赖 |

### 4.2 内存管理风险

| 位置 | 问题 | 严重程度 |
|------|------|---------|
| `spike_sorter.py:363-367` | Zarr 临时文件（KS_TEMP）保存整个预处理后的 Recording，大数据集可能占用数十 GB | 高 |
| `spike_sorter.py:440` | `analyzer.compute(postprocessing_protocol)` 一次性计算所有后处理，unit 数多时 OOM | 高 |
| `synchronizer.py:379` | `eye_matrix = np.nan * np.zeros((onset_times, max_dur, 2))` 预分配全量眼动矩阵，大 session 时 GB 级 | 中 |
| `data_integrator.py:376` | `f['eye_data']['eye_matrix'][:]` 一次性加载全量眼动矩阵到内存 | 中 |
| `data_loader.py:508-525` | h5py 递归解析时，cell array 全部展开为 Python list，大型 bhv2 文件内存翻倍 | 中 |
| `data_integrator.py:570` | 逐 unit 遍历计算 Raster 时，`spike_times_list` 中每个 unit 的所有 spike times 保存为 list，大 session 累计内存大 | 低 |

### 4.3 单探针设计，需改为多探针

**根本问题**：整个 Pipeline 假定只有一个 IMEC 探针（`imec0`），无多探针支持：

| 位置 | 问题 |
|------|------|
| `data_loader.py:139` | `stream_name = 'imec0.ap'`，固定 imec0 |
| `data_loader.py:222-224` | `stream_name='imec0.lf-SYNC'`，`channel_ids=['imec0.lf#SY0']` |
| `data_integrator.py:204` | `chunk_shape=(1, 64)`，隐含 64 通道/探针假设 |
| `quality_controller.py:119-126` | `glob("*.ap.bin")` 期望只有一个文件，多探针时 raise error |
| `spike_sorter.py:258` | `stream_name='imec0.ap'`，固定 imec0 |
| 整个 Synchronizer | 只处理一个 IMEC 同步信号，无法处理多探针时间对齐 |

**改造策略**：需要将探针标识（probe_id）参数化，DataLoader 返回探针列表，下游各模块迭代处理。

### 4.4 SpikeInterface API 使用问题

以下用法可能在新版 SpikeInterface（>= 0.100）中已过时或发生变化：

| 位置 | 问题 |
|------|------|
| `data_loader.py:206` | `nidq_rec.neo_reader.signals_info_dict[(0, 'nidq')]['meta']` — 访问私有属性，版本不兼容 |
| `data_loader.py:232` | `imec_rec.neo_reader.signals_info_dict[(0, 'imec0.lf')]['meta']` — 同上 |
| `spike_sorter.py:301` | `si.apply_preprocessing_pipeline()` — 该函数在某些版本中名称不同 |
| `spike_sorter.py:531` | `self.sorting_result.get_all_spike_trains()` — 此 API 在新版中已变更 |
| `synchronizer.py:12` | `matplotlib.use('Agg')` — Streamlit 后端下有副作用 |
| `data_loader.py:198` | `channel_ids=['nidq#XA0']` — 旧版 SpikeGLX 通道命名格式 |

### 4.5 数据验证缺陷

- `validate_data()` 只检查文件是否存在，不验证数据完整性（截断文件、损坏 meta）
- MonkeyLogic 验证只检查字段存在性，不验证字段类型或值域
- 眼动质量检查只统计注视比例，不检测眼漂移、眼跳（saccade）等伪影
- Bombcell 版本兼容性无检查（不同版本 qMetric 字段集不同）
- **缓存版本字符串脆弱**：`data_loader.py` 的 pickle 缓存用版本字符串 `"v2.2_eye_no_double_transpose"` 作为失效标志。任何代码逻辑修改必须手动更新此字符串，否则旧缓存不会失效，导致使用过时数据而不报错。版本字符串与代码变更没有自动绑定关系，极易被遗漏。
- **`si.apply_preprocessing_pipeline()` API 兼容性**：`spike_sorter.py:301` 调用此函数，但该函数在 SpikeInterface 0.101+ 中可能已被移除或重命名（SI 0.101 将预处理接口大幅重构）。新项目在 SI >= 0.101 环境下直接复用此调用会静默失败或 ImportError。

---

## 5. 可复用资产评估

### 5.1 可直接迁移（★★★★★）

**`utils/config_manager.py`** — ConfigManager
- 分布式 YAML、单例模式、模块隔离，设计干净
- 新项目直接复用，只需调整配置文件路径和模块名映射

**`utils/logger.py`** — ProcessLogger
- `start_step/complete_step` + 计时 + 日志文件，用法统一
- 新项目直接复用

**`utils/error_handler.py`** — `@error_boundary` 装饰器 + 异常类
- 统一错误捕获模式，适合流水线处理
- 直接复用

### 5.2 核心算法可复用（★★★★）

**`synchronizer.py`** — 光敏二极管校准算法
```python
# 可复用的核心算法（约 60 行）：
# 1. NI 模拟信号重采样到 1ms（resample_poly）
# 2. 按 onset 截取窗口 + zscore 标准化
# 3. 自适应阈值（baseline×0.1 + peak×0.9）
# 4. 找超阈值第一个点 → onset 延迟
# 5. np.interp 时钟对齐
```
需要：将硬编码 code=64 参数化，移除 Streamlit 依赖

**`synchronizer.py`** — 眼动验证逻辑
```python
# 核心：eye_distance = norm(eye_data, axis=1)
#       eye_valid_ratio = sum(distance < fixation_window) / stim_duration
#       valid if ratio > threshold
```
可直接提取为独立函数

**`data_loader.py`** — bhv2 解析（h5py + scipy.io 双通道）
- `_load_h5py_recursive`、`_load_h5py_struct`、`_normalize_scalar/array` 约 200 行
- 解决了 MATLAB struct array 转 Python list 的诸多边界情况
- 直接复用，但注意缓存版本字符串需更新

### 5.3 需要适配的代码（★★★）

**`spike_sorter.py`** — SpikeSorter 框架
- Protocol Pipeline 三段式设计良好，但需要：
  1. 参数化 `imec0` → 支持多探针
  2. 修复发放率计算的硬编码采样率
  3. 后处理按需计算（非全量），避免 OOM

**`quality_controller.py`** — QualityController
- Bombcell API 调用逻辑完整，基本可复用
- 需要：添加版本检查、支持多探针多组 KS 输出

**`data_loader.py`** — SpikeGLX 加载部分
- `load_spikeglx` 框架可复用，但需：
  1. 参数化探针 ID（不固定 imec0）
  2. 通道 ID 从配置读取（非硬编码字符串）
  3. 避免访问 `neo_reader` 私有属性

### 5.4 需要重写（★★）

**`data_integrator.py`** — DataIntegrator
- neuroconv 版本绑定，接口变化大
- chunk_shape 硬编码问题
- 建议：使用原生 pynwb API 重写，更稳定
- 可复用：`_compute_unit_response`、`_statistical_test` 算法逻辑

**`data_loader.py`** — nidq 元数据读取
- `neo_reader.signals_info_dict` 是私有属性，已知在不同版本下路径不同
- 建议用 `si.read_spikeglx` + probe metadata 替代

### 5.5 可复用的 MATLAB 参考（Util/）

| 文件 | 作用 | 新项目意义 |
|------|------|-----------|
| `mlread.m` | 读取 bhv2/bhvz/h5 文件，返回 trial struct array | Python 端的 bhv2 解析已复现其逻辑 |
| `mlbhv2.m` | bhv2 格式底层读取器（classdef） | 理解 bhv2 二进制格式 |
| `bhv_read.m` | 旧版 .bhv 格式读取器 | 仅用于向后兼容旧数据 |
| `Load_Data_function.m` | synchronizer.py 的原型，含完整同步逻辑 | 新 synchronizer 的算法参考 |
| `PostProcess_function.m` | MATLAB 后处理（已由 data_integrator 替代） | 了解历史处理逻辑 |

---

## 6. 新旧对比与迁移建议

| 特性 | Legacy (pyneuralpipe) | pynpxpipe 新设计 | 迁移理由 |
|------|-----------------------|------------------|----------|
| **Phase shift 位置** | highpass_filter 之后执行 | bandpass_filter 之前执行 | ADC 采样时间偏移应在任何滤波前校正，否则滤波会引入额外相位失真 |
| **滤波类型** | 仅高通 300 Hz，无上限截止 | 带通 300–6000 Hz | 神经尖峰有效频段为 300–6000 Hz；保留高频噪声降低 KS4 模板匹配质量 |
| **运动校正** | 完全缺失 | DREDge via `si.correct_motion`（与 KS4 `nblocks` 互斥） | 长时程录制中电极漂移可达数十微米，运动校正显著提升 spike sorting 质量 |
| **单元位置估计** | `center_of_mass` | `monopolar_triangulation` | 对线性多通道探针，monopolar_triangulation 空间精度更高，对深层单元误差更小 |
| **探针支持** | 单探针（硬编码 imec0） | 多探针（probe_id 参数化，支持 N 个 IMEC 探针） | 实验室 Neuropixels 2.0 录制常用多探针同步采集 |
| **质量控制框架** | Bombcell Python API | SpikeInterface 原生 `quality_metrics` + `curation` | Bombcell 版本兼容性差，与 SI 生态解耦；SI 0.101 内置 QC 指标更丰富且持续维护 |
| **NWB 写入方式** | neuroconv `SpikeGLXConverterPipe` + `KiloSortSortingInterface` | 原生 pynwb API | neuroconv 接口版本绑定强，升级频繁；原生 pynwb 更稳定，控制粒度更细 |
| **眼动矩阵处理** | `np.zeros((onset_times, max_dur, 2))` 预分配全量 3D 矩阵，大 session 达 GB 级 | 按 trial 分块处理，移至 postprocess 阶段 | 全量预分配在大 session（>1000 trials）下导致 OOM；分块处理内存峰值可控 |
| **BHV2 解析缓存** | pickle 缓存 + MD5 hash + 版本字符串 `"v2.2_eye_no_double_transpose"` | 无缓存，每次通过 MATLAB engine 重新解析 | 版本字符串脆弱，代码改动后若忘记更新字符串则使用过时缓存；BHV2 解析耗时可接受（< 30s），缓存收益不足以抵消风险 |
| **checkpoint 系统** | `directory_checker.py` 通过检查特定目录/文件是否存在来判断阶段完成状态，粒度粗 | 每个 stage × probe 独立写 JSON checkpoint 文件到 `output_dir/` | 目录检查无法区分"处理中断"和"处理完成"；JSON checkpoint 含时间戳、参数哈希，支持精确断点续跑 |

---

## 7. 依赖清单

### 7.1 requirements.txt 声明的依赖

```
# Web 界面
streamlit>=1.28.0

# 科学计算核心
numpy>=1.24.0
pandas>=2.0.0
scipy>=1.10.0
matplotlib>=3.7.0
seaborn>=0.12.0

# 配置
PyYAML>=6.0.0
PyQt5>=5.15.0

# 神经数据处理
spikeinterface>=0.100.0
kilosort>=4.0.0
pynwb>=2.5.0

# 数据 I/O
h5py>=3.8.0
mat73>=0.59
probeinterface>=0.2.0

# 可视化（可选）
plotly>=5.15.0
bokeh>=3.0.0
ipywidgets>=8.0.0

# 开发测试
pytest>=7.0.0
black>=23.0.0
flake8>=6.0.0
```

### 7.2 代码中实际 import 的库（requirements 未列出）

| 库 | 用途 | 来源模块 |
|----|------|---------|
| `neuroconv` | SpikeGLXConverterPipe、KiloSortSortingInterface | data_integrator |
| `bombcell` | bc.run_bombcell、bc.get_default_parameters | quality_controller |
| `matlab.engine` | bhv2 → mat 转换 | data_loader（可选）|
| `tqdm` | 进度条 | data_integrator |
| `dateutil` | tz.tzlocal() | data_integrator |
| `fractions.Fraction` | 精确有理数重采样比率 | synchronizer |

### 7.3 完整依赖清单（建议新 requirements.txt）

```
numpy>=1.24.0
pandas>=2.0.0
scipy>=1.10.0
matplotlib>=3.7.0
PyYAML>=6.0.0
h5py>=3.8.0
spikeinterface>=0.100.0
kilosort>=4.0.0
pynwb>=2.5.0
neuroconv>=0.5.0
probeinterface>=0.2.0
bombcell>=1.0.0
python-dateutil>=2.8.0
tqdm>=4.65.0
# 可选
mat73>=0.59
streamlit>=1.28.0
```

### 7.4 运行环境要求

- **Python**：3.9 - 3.11（SpikeInterface 官方支持范围）
- **操作系统**：Windows 11（当前开发环境）
- **conda 环境**：`spikesort`（含 Kilosort4 + CUDA 支持）
- **MATLAB**：R2020b+（可选，仅用于 bhv2 转换）
- **内存**：建议 ≥ 32GB RAM（大 session 的 eye_matrix + zarr 临时文件）
- **存储**：SSD，预留原始数据 2-3× 空间（zarr 临时文件 + NWB 输出）

---

## 附录：文件树（已分析部分）

```
pyneuralpipe/
├── core/
│   ├── data_loader.py       ✅ 已分析
│   ├── synchronizer.py      ✅ 已分析
│   ├── spike_sorter.py      ✅ 已分析
│   ├── quality_controller.py ✅ 已分析
│   └── data_integrator.py   ✅ 已分析
├── config/
│   ├── data_loader.yaml     ✅ 已分析
│   ├── synchronizer.yaml    ✅ 已分析
│   ├── spike_sorter.yaml    ✅ 已分析
│   ├── quality_controller.yaml ✅ 已分析
│   ├── data_integrator.yaml ✅ 已分析
│   └── nwbsession_template.yaml （NWB session 元数据模板）
├── utils/
│   ├── config_manager.py    ✅ 已分析
│   ├── logger.py            ✅ 已分析
│   ├── error_handler.py     ✅ 已分析
│   ├── directory_checker.py ✅ 已分析
│   ├── nwb_stim_helper.py   ✅ 已分析
│   └── nwb_bombcell_helper.py ✅ 已分析
├── monkeys/
│   ├── JianJian.yaml        ✅ 已分析（雄性恒河猴，4岁，6.4kg）
│   └── MaoDan.yaml          ✅ 已分析（雄性恒河猴，4岁，12.8kg）
├── Util/
│   ├── mlread.m             ✅ 已分析（MonkeyLogic 官方读取器）
│   ├── mlbhv2.m             ✅ 已分析（bhv2 底层 classdef）
│   ├── bhv_read.m           ✅ 已分析（旧版 .bhv 格式读取器）
│   ├── Load_Data_function.m  （synchronizer 的 MATLAB 原型）
│   └── PostProcess_function*.m （MATLAB 后处理函数）
├── NPX_session_process.ipynb （主处理 Notebook）
├── process_session.py        （命令行批处理脚本）
├── requirements.txt          ✅ 已分析
├── README.md                 ✅ 已分析
└── PyNeuralPipeline_developplan.md ✅ 已分析
```
