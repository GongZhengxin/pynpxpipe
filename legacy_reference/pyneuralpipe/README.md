# 神经数据处理流程应用 (PyNeuralPipe)

一个基于Python的神经数据处理流程应用，整合SpikeInterface、Kilosort4、PyNWB等工具包，提供完整的神经数据分析流水线。

## 🎯 主要特性

- 🔄 **完整流水线**: 从原始数据到最终分析结果的一站式处理
- 🧠 **Kilosort4集成**: 使用最新的Kilosort4进行高质量尖峰排序
- 🧩 **SpikeInterface Protocol Pipeline**: 标准化、模块化的预处理/排序/后处理
- 🔬 **Bombcell质量控制**: 集成Bombcell进行自动化单元质量评估
- 📊 **NWB标准格式**: 完整的NWB文件生成，包含电生理、行为和质量指标
- 🎯 **智能单元筛选**: 基于统计检验和质量指标的自动化单元筛选
- 🔗 **灵活数据源**: SpikeSorter支持多种数据源，兼容Recording对象和文件夹路径
- 📈 **可视化界面**: 基于Streamlit的交互式用户界面
- ⚙️ **配置管理**: 灵活的配置系统，支持实时调整参数
- 📝 **实时监控**: 处理进度可视化和日志记录
- 🔄 **向后兼容**: 保持原有API兼容性，支持渐进式升级

## 📁 项目结构

```
pyneuralpipe/
├── app.py                      # Streamlit主应用
├── requirements.txt            # 依赖管理
├── config/                     # 配置文件
│   └── app_config.yaml        # 主配置文件
├── core/                       # 核心处理模块
│   ├── data_loader.py         # 数据加载与验证
│   ├── spike_sorter.py        # 尖峰排序模块(Kilosort4,支持多种数据源)
│   ├── synchronizer.py        # 同步与校验模块
│   ├── quality_controller.py  # 质量控制模块(Bombcell集成)
│   └── data_integrator.py     # 数据整合模块(NWB导出)
├── output/                     # 输出处理器
│   ├── nwb_exporter.py        # NWB导出模块
│   └── mat_exporter.py        # MAT格式导出
├── ui/                         # 用户界面组件
│   ├── components.py          # UI组件(含配置管理)
│   └── layouts.py             # 界面布局
├── utils/                      # 工具类
│   ├── directory_checker.py   # 目录检查
│   ├── logger.py              # 日志系统
│   ├── config_manager.py      # 配置管理
│   └── error_handler.py       # 错误处理
├── logs/                       # 日志文件
├── output/                     # 输出目录
├── temp/                       # 临时文件
└── Util/                       # MATLAB工具函数
```

## 安装运行

### 方法一：使用启动脚本（推荐）

1. 激活conda环境：
```bash
conda activate spikesort
```

2. 运行启动脚本：
```bash
python run_app.py
```

启动脚本会自动检查环境和依赖项，并启动应用。

### 方法二：手动启动

1. 激活conda环境：
```bash
conda activate spikesort
```

2. 安装依赖：
```bash
pip install -r requirements.txt
```

3. 创建必要目录：
```bash
mkdir -p logs output temp config
```

4. 运行应用：
```bash
streamlit run app.py
```

## 🚀 使用说明

### 🖥️ GUI 配置编辑器（推荐）

**快速启动：**

Windows:
```bash
cd pyneuralpipe
run_config_editor.bat
```

Linux/Mac:
```bash
cd pyneuralpipe
./run_config_editor.sh
```

**功能特点：**
- 📝 可视化编辑所有配置文件
- 🗂️ 便捷选择 session 文件夹
- ▶️ 一键运行完整处理流程
- 📊 实时查看处理输出和进度
- 💾 自动保存配置到正确位置

详细说明请查看 [GUI_README.md](GUI_README.md)

### 📓 Jupyter Notebook 方式

使用 `NPX_session_process.ipynb` 进行交互式处理：
- 逐步执行每个处理阶段
- 灵活调整参数
- 查看中间结果

### 🌐 Streamlit Web 应用

基本工作流程：

1. **🗂️ 选择数据目录**: 在侧边栏输入包含SpikeGLX和MonkeyLogic数据的目录路径
2. **⚙️ 配置参数**: 使用配置管理界面调整Kilosort、同步和质量控制参数
3. **▶️ 开始处理**: 点击"开始处理"按钮启动完整的分析流程
4. **📊 查看结果**: 在不同标签页中查看处理进度、可视化结果和统计信息
5. **💾 导出数据**: 将结果导出为NWB或MAT格式

### 📂 数据目录要求

应用期望的数据目录结构：
```
数据目录/
├── *.ap.bin, *.ap.meta     # SpikeGLX神经数据(必需)
├── *.lf.bin, *.lf.meta     # SpikeGLX LFP数据(可选)
├── *.nidq.bin, *.nidq.meta # NI-DAQ同步数据(推荐)
└── *.bhv2                  # MonkeyLogic行为数据(可选)
```

### 🔄 处理阶段

1. **📋 Data Check**: 验证数据文件完整性和格式
2. **🧠 Spike Sorting**: 使用Kilosort4进行尖峰排序
3. **🔗 Synchronization**: 神经数据与行为数据同步校准
4. **🔍 Quality Control**: 单元质量评估和筛选
5. **📊 Post Process**: 响应分析和统计处理
6. **✅ Completed**: 所有处理完成，可以导出结果

### ⚙️ 配置管理

应用提供了完整的配置管理系统，基于 `app_config.yaml` 文件，实现了模块间的统一配置管理：

#### 🔧 配置系统特性

- **🎯 统一配置**: 所有模块参数集中在 `config/app_config.yaml` 中管理
- **📊 分层结构**: 配置按模块分类，支持嵌套配置结构
- **🔄 自动加载**: 各模块自动从配置文件加载对应参数
- **⚡ 实时调整**: 支持通过界面实时调整参数设置
- **🔒 类型安全**: 配置管理器提供类型检查和默认值回退
- **📝 向后兼容**: 保持原有API兼容，支持渐进式配置迁移

#### 📋 主要配置模块

**数据加载配置** (`data_loader`)
- **SpikeGLX配置**: 数据流名称、数字通道映射、采样率设置
- **MonkeyLogic配置**: 文件扩展名、必需字段、行为代码映射
- **同步数据配置**: 通道映射、采样率默认值

**同步器配置** (`synchronizer`) 
- **眼动验证**: 固视阈值、固视窗口参数
- **光敏二极管校准**: 测量窗口、延迟校正、阈值计算参数
- **同步验证**: 时间误差阈值、最小同步事件数

**Kilosort配置** (`kilosort`)
- **基础参数**: 并行数、数据块大小、进度条设置
- **算法参数**: 阈值、lambda参数、分割标准
- **预处理**: 滤波频率、坏道检测、参考设置

**质量控制配置** (`quality_control`)
- **单元质量标准**: 发放率、污染率、振幅、信噪比阈值
- **通道质量**: 噪声水平、信号范围、伪影检测
- **统计参数**: 显著性阈值、置信水平、bootstrap参数

**界面配置** (`ui`)
- **主题设置**: 颜色主题、页面布局、图表样式
- **组件配置**: 文件上传、进度条、数据编辑器设置
- **可视化**: matplotlib和plotly图表参数

#### 🔗 配置集成示例

```python
# DataLoader自动从配置获取参数
loader = DataLoader(data_path)
# 自动使用config中的stream_name、digital_channel_map等

# Synchronizer继承配置管理器
synchronizer = DataSynchronizer(loader)
# 自动加载eye_threshold、photodiode参数等

# 也支持显式传入配置管理器
config_manager = ConfigManager()
loader = DataLoader(data_path, config_manager=config_manager)
synchronizer = DataSynchronizer(loader, config_manager=config_manager)
```

#### 📁 配置文件结构

```yaml
# config/app_config.yaml
data_loader:
  spikeglx:
    stream_name: 'imec0.ap'
    digital_channel_map:
      sync: 0
      trial_start: 3
      stim_onset: 6
  monkeylogic:
    file_extension: '.bhv2'
    code_mappings:
      stim_onset: 64
      stim_offset: 32

synchronizer:
  eye_tracking:
    threshold: 0.999
  photodiode:
    before_onset_measure: 10
    monitor_delay_correction: -5
```

### 🔧 SpikeSorter数据源配置

SpikeSorter类支持灵活的数据源配置，满足不同的使用场景：

#### 数据源类型

**方式1: 集成模式（推荐）**
```python
# 与DataLoader配合使用，适用于完整流水线
from core.data_loader import DataLoader

loader = DataLoader(data_path)
loader.load_spikeglx()
neural_data = loader.get_spikeglx_data()  # 获取Recording对象

# 直接传入Recording对象
spike_sorter = SpikeSorter(neural_data)
# 或使用类方法
spike_sorter = SpikeSorter.from_recording(neural_data)
```

**方式2: 独立模式**
```python
# 直接从SpikeGLX数据文件夹加载
spike_sorter = SpikeSorter("/path/to/spikeglx/data")
# 或使用类方法
spike_sorter = SpikeSorter.from_folder("/path/to/spikeglx/data")
```

#### 主要优势

- **🔗 无缝集成**: Recording对象可直接传入，避免重复加载
- **🚀 提高效率**: 减少数据加载时间，避免内存浪费
- **🔄 向后兼容**: 原有文件夹路径方式完全保持兼容
- **🎯 智能识别**: 自动检测数据源类型并应用对应处理流程
- **🎨 优化显示**: 可视化标题根据数据源自动调整

#### 兼容性说明

- ✅ **完全向后兼容**: 原有的文件夹路径初始化方式不受影响
- ✅ **流程一致性**: 无论使用哪种数据源，后续处理流程完全一致
- ✅ **输出兼容性**: 排序结果和导出格式保持完全一致

## DataIntegrator - NWB 数据整合模块

### 📋 概述

`DataIntegrator` 是一个强大的数据整合工具，负责将电生理数据、Kilosort 排序结果、Bombcell 质量控制和行为数据整合到标准的 NWB 文件中。

### 🎯 主要功能

- **原始数据转换**: 将 SpikeGLX 记录转换为 NWB 格式
- **排序结果整合**: 添加 Kilosort4 的 spike sorting 结果
- **行为数据**: 整合 trials、眼动追踪和刺激信息
- **质量控制**: 包含 Bombcell 质量指标
- **响应分析**: 计算神经元对刺激的响应（PSTH/Raster）
- **智能筛选**: 基于统计检验和质量指标自动筛选高质量 units

### 🚀 快速开始

#### 方法一：使用便捷函数

```python
from pyneuralpipe.core.data_integrator import integrate_data

# 一行代码完成整合
output_file = integrate_data(
    data_path="F:/ProcessPipeline/testdata/wordfob",
    subject_config="MaoDan.yaml",
    electrode_location="MLO"
)
```

#### 方法二：使用命令行

```bash
python pyneuralpipe/scripts/run_data_integrator.py \
    --data_path "F:/ProcessPipeline/testdata/wordfob" \
    --subject_config "MaoDan.yaml" \
    --electrode_location "MLO"
```

#### 方法三：批量处理

```bash
# 编辑批处理配置文件
cp pyneuralpipe/config/batch_config_example.yaml my_batch.yaml

# 运行批处理
python pyneuralpipe/scripts/batch_integrate.py --config my_batch.yaml
```

### 📊 输出的 NWB 文件结构

```
NWB File
├── acquisition/
│   ├── ElectricalSeriesAP    # AP band 原始数据
│   └── ElectricalSeriesLF    # LF band 原始数据
├── processing/
│   ├── ecephys/kilosort4_unit  # Kilosort 排序结果
│   └── behavior/EyeTracking    # 眼动追踪数据
├── stimulus/presentation/
│   ├── ImageSeries           # 刺激图片
│   └── IndexSeries           # 刺激索引
├── trials                    # Trial 信息
│   ├── start_time, stop_time
│   ├── stim_index, stim_name
│   └── fix_success
└── units                     # 自定义 units 表
    ├── spike_times           # 放电时间
    ├── unittype              # Bombcell 类型 (1=good, 2=mua, 3=non-soma)
    ├── Raster                # 刺激对齐的 raster
    └── [质量指标...]         # Bombcell 质量指标列
```

### ⚙️ 配置说明

主配置文件：`config/data_integrator.yaml`

**Units 筛选配置**:
```yaml
units:
  filtering:
    enable_statistical_test: true  # 启用统计检验
    p_value_threshold: 0.001       # p 值阈值
    statistical_test: "mannwhitneyu"
    exclude_bombcell_zero: true    # 排除低质量 units

  raster:
    pre_onset_ms: 50               # 刺激前时间窗口（毫秒）
    post_onset_ms: 300             # 刺激后时间窗口（毫秒）
    baseline_window_ms: [-25, 25] # 基线窗口
    response_window_ms: [60, 220]  # 响应窗口
```

### 📖 详细文档

- **快速入门**: `README_DataIntegrator.md`
- **完整指南**: `pyneuralpipe/docs/data_integrator_guide.md`
- **测试示例**: `pyneuralpipe/tests/test_data_integrator.py`

### 💡 Units 筛选逻辑

1. **统计检验**（可选）:
   - 比较 baseline 和 response 窗口的放电率
   - 使用 Mann-Whitney U 检验
   - 只保留显著响应的单元（p < 0.001）

2. **质量控制**（可选）:
   - 排除 Bombcell `unittype == 0` 的单元
   - `unittype == 1`: good units
   - `unittype == 2`: multi-unit activity (MUA)
   - `unittype == 3`: non-somatic spikes

## SpikeInterface Protocol Pipeline 集成

本文档整合了项目中新增的 SpikeInterface Protocol Pipeline 能力，提供标准化、模块化的神经尖峰排序流程。

### 📋 概述

基于官方规范的字典式 pipeline，我们将手动预处理替换为标准化协议，包含：

- 预处理协议（preprocessing）
- 排序协议（sorting）
- 后处理协议（postprocessing）

### 🔧 配置结构（`config/app_config.yaml`）

```yaml
spike_sorting_pipeline:
  preprocessing:
    highpass_filter:
      freq_min: 300.0
    detect_and_remove_bad_channels:
      method: 'mad'
      std_mad_threshold: 5
    phase_shift: {}
    common_reference:
      operator: 'median'
      reference: 'global'

  sorting:
    sorter_name: 'kilosort4'
    nblocks: 15
    Th_learned: 7.0
    n_jobs: 12
    chunk_duration: '4s'

  postprocessing:
    waveforms:
      ms_before: 1.0
      ms_after: 2.0
      max_spikes_per_unit: 500
    spike_amplitudes:
      peak_sign: 'neg'
    spike_locations:
      method: 'center_of_mass'
    unit_locations:
      method: 'center_of_mass'
    quality_metrics:
      metric_names: ['firing_rate', 'snr', 'isi_violation']
```

### 🚀 使用方法

```python
from core.spike_sorter import SpikeSorter

# 方式1：从 Recording 对象
sorter = SpikeSorter.from_recording(recording_obj)
success = sorter.run_full_pipeline()

# 方式2：从数据文件夹
sorter = SpikeSorter.from_folder('/path/to/spikeglx/data')
success = sorter.run_full_pipeline()
```

### 访问后处理结果

```python
waveforms = sorter.get_waveforms()
spike_amplitudes = sorter.get_spike_amplitudes()
spike_locations = sorter.get_spike_locations()
unit_locations = sorter.get_unit_locations()
spike_times_ms = sorter.get_spike_times_ms()
summary = sorter.get_postprocessing_summary()
```

### 自定义协议配置（运行时更新）

```python
from utils.config_manager import get_config_manager

config_manager = get_config_manager()

# 更新预处理
config_manager.update_config('preprocessing_protocol', highpass_filter={'freq_min': 400.0})

# 更新后处理
config_manager.update_config('postprocessing_protocol', waveforms={'ms_before': 2.0, 'ms_after': 3.0})
```

### 📊 Pipeline 标准流程

```python
# 1) 预处理
preprocessed = si.apply_pipeline(recording, preprocessing_protocol)

# 2) 排序
sorting = si.run_sorter(recording=preprocessed, **sorting_protocol)

# 3) 创建分析器
analyzer = si.create_sorting_analyzer(recording=preprocessed, sorting=sorting)

# 4) 后处理
analyzer.compute(postprocessing_protocol)
```

### 🎯 配置管理辅助

- 获取完整 pipeline 配置：`config_manager.get_spike_sorting_pipeline_config()`
- 获取具体协议：`get_preprocessing_protocol()` / `get_sorting_protocol()` / `get_postprocessing_protocol()`
- 批量更新：`update_section_config('spike_sorting_pipeline', new_config)`

### 📈 优势

- 标准化：遵循 SpikeInterface 标准 API
- 模块化：三段式协议独立配置与更新
- 可扩展：支持 SpikeInterface 各类扩展计算
- 高效：利用官方实现的并行与内存优化

### 🔍 示例与参考

- 使用示例：`pyneuralpipe/examples/protocol_pipeline_example.py`
- 测试样例：`pyneuralpipe/tests/pipeline_test.ipynb`
- 参考文档：[SpikeInterface Protocol Pipeline 文档](https://spikeinterface.readthedocs.io/en/0.103.0/how_to/build_pipeline_with_dicts.html)

### ⚠️ 注意事项

- 建议使用较新的 SpikeInterface 版本
- 大型数据的后处理（如 waveforms、locations）内存占用较高，请按需配置

## ⚠️ 重要说明

### 🔧 技术要求

- **Python版本**: 3.8+
- **内存要求**: 建议16GB以上RAM用于大型数据集
- **存储空间**: 预留足够空间用于临时文件(约为原始数据的2-3倍)
- **GPU支持**: Kilosort4可选择使用GPU加速

### 📦 依赖环境

主要依赖包：
- `spikeinterface>=0.98.0` - 神经数据处理接口
- `kilosort>=4.0` - 尖峰排序算法
- `streamlit>=1.28.0` - Web界面框架
- `pynwb>=2.5.0` - NWB格式支持
- `scipy`, `numpy`, `pandas` - 科学计算
- `matplotlib`, `plotly` - 数据可视化

### 🚀 性能优化

- **并行处理**: 自动利用多核CPU进行数据处理
- **内存管理**: 智能数据分块，避免内存溢出
- **临时文件**: 使用SSD存储可显著提升处理速度
- **GPU加速**: 支持CUDA加速Kilosort排序过程
- **数据复用**: SpikeSorter支持Recording对象传入，避免重复数据加载
- **类型安全**: 自动识别数据源类型，减少运行时错误
- **智能缓存**: 预加载的数据可在多个处理步骤间复用
- **配置优化**: 统一配置管理避免重复参数解析，提升模块初始化速度
- **参数验证**: 配置管理器提供参数验证，减少运行时配置错误

### 🔄 数据处理流程

#### 完整流水线包括：

1. **数据加载阶段**
   - SpikeGLX数据验证和加载
   - MonkeyLogic行为数据解析
   - 同步信号提取和验证

2. **预处理阶段**
   - 高通滤波(默认300Hz)
   - 坏道检测和移除
   - 相位偏移校正
   - 共同参考去噪

3. **尖峰排序阶段**
   - Kilosort4自动聚类
   - 模板匹配和精化
   - 漂移校正
   - 污染率评估

4. **同步校准阶段**
   - 设备间时钟同步
   - 光敏二极管时间校准
   - 眼动数据验证
   - 试次对齐

5. **质量控制阶段**
   - 单元发放率筛选
   - 波形质量评估
   - ISI违规检测
   - 隔离质量计算

6. **数据整合阶段**
   - 多模态数据对齐
   - 刺激响应分析
   - 统计显著性检验
   - 结果可视化

### 🎨 可视化功能

- **实时进度监控**: 处理进度条和状态显示
- **数据质量报告**: 同步误差、单元质量统计
- **排序结果可视化**: 漂移图、发放率分布、污染率统计
- **响应分析图表**: PSTH、光栅图、眼动轨迹
- **交互式参数调整**: 实时配置修改和预览

### 💾 数据导出格式

#### NWB格式 (推荐)
- 符合BRAIN Initiative标准
- 包含完整元数据
- 支持时间序列和事件数据
- 兼容多种分析工具

#### MAT格式
- MATLAB兼容
- 结构化数据组织
- 包含处理参数
- 便于后续分析

### 🐛 故障排除

常见问题及解决方案：

1. **内存不足错误**
   - 减少`chunk_duration`参数
   - 降低`n_jobs`并行数
   - 增加系统虚拟内存

2. **Kilosort安装问题**
   - 确保CUDA版本兼容
   - 检查GPU驱动程序
   - 使用conda环境管理

3. **数据格式错误**
   - 验证SpikeGLX文件完整性
   - 检查.meta文件是否存在
   - 确认文件路径正确

4. **同步失败**
   - 检查数字通道连接
   - 验证同步信号质量
   - 调整同步检测参数

5. **SpikeSorter数据源问题**
   - **Recording对象无效**: 确保Recording对象具有必要的方法(`get_sampling_frequency`, `get_num_channels`, `get_traces`)
   - **数据源识别失败**: 检查传入的参数类型，确保是有效的Recording对象或文件夹路径字符串
   - **路径访问权限**: 对于文件夹路径，确保有读取权限且包含必要的SpikeGLX文件(.ap.bin, .ap.meta)
   - **兼容性问题**: 使用类方法`SpikeSorter.from_recording()`或`SpikeSorter.from_folder()`以获得更好的类型安全

6. **配置管理问题**
   - **配置文件缺失**: 确保 `config/app_config.yaml` 文件存在且格式正确
   - **参数类型错误**: 检查配置文件中的参数类型是否符合预期（数字、字符串、布尔值等）
   - **必需参数缺失**: 关键参数如 `digital_channel_map`、`code_mappings` 等应在配置文件中正确设置
   - **配置加载失败**: 检查YAML文件语法，确保缩进和格式正确
   - **模块配置冲突**: 不同模块间的配置参数应保持一致，特别是通道映射和代码映射

7. **Protocol Pipeline 配置问题**
   - 确认 `spike_sorting_pipeline` 下的 `preprocessing`/`sorting`/`postprocessing` 键存在且缩进正确
   - `sorting` 中需包含 `sorter_name`（如 `kilosort4`）以及资源参数（`n_jobs`, `chunk_duration`）
   - 后处理计算可能占用大量内存，按需关闭或降低 `max_spikes_per_unit`
