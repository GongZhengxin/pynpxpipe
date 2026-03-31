# 神经数据处理流程Python应用开发计划 (更新版本)

## 1. 项目概述

本项目旨在开发一个基于Python的神经数据处理流程应用，整合SpikeInterface、Kilosort4、Bombcell、PyNWB等工具包，实现从原始数据读取、尖峰排序、质量控制到神经元响应分析的全过程。通过Streamlit框架提供交互式界面，允许用户调整参数、查看处理报告及中间结果，并最终生成符合NWB标准的神经数据文件。

### 项目当前状态
- ✅ **数据加载模块** (data_loader.py) - 已完成SpikeGLX和MonkeyLogic数据加载
- ✅ **同步校验模块** (synchronizer.py) - 已完成神经-行为数据同步和光敏二极管校准
- ✅ **尖峰排序模块** (spike_sorter.py) - 已完成Kilosort4集成
- 🔄 **质量控制模块** (quality_controller.py) - 需要重构，集成Bombcell Python API
- 🔄 **数据整合模块** (data_integrator.py) - 需要重构，优化响应分析和输出结构
- ❌ **NWB导出模块** - 需要新建实现
- ❌ **MAT导出模块** - 需要新建MATLAB引擎集成
- 🔄 **Streamlit界面** - 需要完善功能和用户体验

## 2. 架构设计

### 2.1 系统架构
```
├── Frontend (Streamlit UI)
│   ├── 目录选择与检查模块
│   ├── 参数配置界面
│   ├── 处理进度可视化
│   └── 结果报告展示
├── Processing Core (数据处理核心)
│   ├── 数据加载与验证模块
│   ├── 尖峰排序模块
│   ├── 同步与校验模块
│   ├── 质量控制模块
│   └── 数据整合模块
├── Output Handlers (输出处理器)
│   ├── NWB导出模块
│   ├── MAT导出模块(传统兼容)
│   └── 云备份模块
└── Utilities (工具类)
    ├── 日志系统
    ├── 配置管理
    └── 错误处理
```

### 2.2 数据流程
1. 用户选择数据目录
2. 系统验证目录结构并确定处理阶段
3. 加载和验证SpikeGLX与MonkeyLogic数据
4. 执行尖峰排序(Kilosort4)
5. 同步神经数据与行为数据
6. 质量控制(Bombcell等价功能)
7. "Good Unit"筛选与响应分析
8. 生成输出文件(NWB和MAT格式)
9. 可选云备份

## 3. 模块详细设计 (基于当前实现)

### 3.1 质量控制模块 (重构 - 集成Bombcell)
```python
class QualityController:
    def __init__(self, kilosort_output_path, raw_data_path=None):
        """
        初始化质量控制器，集成Bombcell Python API
        
        Args:
            kilosort_output_path: Kilosort输出目录
            raw_data_path: 原始数据路径(可选)
        """
        self.ks_output_path = kilosort_output_path
        self.raw_data_path = raw_data_path
        self.bombcell_params = None
        self.quality_metrics = None
        self.unit_types = None
        
    def setup_bombcell_params(self, custom_params=None):
        """设置Bombcell参数"""
        import bombcell as bc
        self.bombcell_params = bc.get_default_parameters(
            self.ks_output_path,
            raw_file=self.raw_data_path,
            kilosort_version=4
        )
        if custom_params:
            self.bombcell_params.update(custom_params)
    
    def run_quality_control(self):
        """运行Bombcell质量控制"""
        import bombcell as bc
        save_path = Path(self.ks_output_path) / "bombcell"
        
        (self.quality_metrics, 
         self.bombcell_params, 
         self.unit_types, 
         unit_type_strings, 
         figures) = bc.run_bombcell(
            self.ks_output_path, 
            save_path, 
            self.bombcell_params,
            return_figures=True
        )
        
        return {
            'qMetric': self.quality_metrics,
            'unitType': self.unit_types,
            'figures': figures
        }
```

### 3.2 数据整合模块 (重构 - 优化响应分析)
```python
class DataIntegrator:
    def __init__(self, kilosort_data, quality_results, sync_data, behavior_data):
        """
        数据整合器，基于质量控制结果和同步数据进行最终整合
        
        Args:
            kilosort_data: Kilosort排序结果
            quality_results: Bombcell质量控制结果
            sync_data: 同步校验数据
            behavior_data: 行为数据
        """
        self.kilosort_data = kilosort_data
        self.qMetric = quality_results['qMetric']
        self.unitType = quality_results['unitType']
        self.sync_data = sync_data
        self.behavior_data = behavior_data
        self.good_units = []
        
    def filter_good_units(self, custom_criteria=None):
        """根据Bombcell分类和自定义标准筛选优质神经元"""
        # 使用unitType == 1 (good) 作为基础筛选
        good_indices = np.where(self.unitType == 1)[0]
        
        # 应用额外的质量标准
        if custom_criteria:
            good_indices = self._apply_quality_filters(good_indices, custom_criteria)
        
        self.good_units = good_indices
        return len(self.good_units)
    
    def calculate_responses_with_sync(self):
        """基于同步数据计算神经元响应"""
        # 使用sync_data中的校准后onset时间
        onset_times = self.sync_data['calibrated_onset_ms']
        trial_valid_idx = self.sync_data['trial_valid_idx']
        
        # 为每个good unit计算raster和PSTH
        responses = {}
        for unit_idx in self.good_units:
            unit_response = self._calculate_unit_response_aligned(
                unit_idx, onset_times, trial_valid_idx
            )
            responses[unit_idx] = unit_response
        
        return responses
```

### 3.3 NWB导出模块 (新建)
```python
class NWBExporter:
    def __init__(self, integrated_data, session_metadata):
        """
        NWB数据导出器
        
        Args:
            integrated_data: 整合后的数据结构
            session_metadata: 会话元数据
        """
        self.data = integrated_data
        self.metadata = session_metadata
        self.nwbfile = None
        
    def create_full_nwb(self, output_path):
        """创建完整版NWB文件(本地保存)"""
        from pynwb import NWBFile, NWBHDF5IO
        from pynwb.ecephys import ElectricalSeries, LFP
        from pynwb.behavior import EyeTracking
        
        # 创建NWB文件对象
        self.nwbfile = NWBFile(
            session_description=self.metadata['session_description'],
            identifier=self.metadata['identifier'],
            session_start_time=self.metadata['session_start_time'],
            experimenter=self.metadata['experimenter'],
            lab=self.metadata['lab'],
            institution=self.metadata['institution']
        )
        
        # 添加原始电生理数据
        self._add_raw_ephys_data()
        
        # 添加排序结果
        self._add_spike_sorting_results()
        
        # 添加行为数据
        self._add_behavior_data()
        
        # 添加质量控制结果
        self._add_quality_metrics()
        
        # 保存文件
        with NWBHDF5IO(output_path, 'w') as io:
            io.write(self.nwbfile)
    
    def create_analysis_nwb(self, output_path):
        """创建分析版NWB文件(云端备份)"""
        # 只包含分析结果，不包含原始数据
        pass
```

### 3.4 MAT导出模块 (新建 - MATLAB兼容性)
```python
class MATExporter:
    def __init__(self, integrated_data, matlab_util_path):
        """
        MAT格式导出器，兼容现有MATLAB流程
        
        Args:
            integrated_data: 整合后的数据
            matlab_util_path: MATLAB工具函数路径
        """
        self.data = integrated_data
        self.matlab_util_path = matlab_util_path
        self.matlab_engine = None
        
    def setup_matlab_engine(self):
        """初始化MATLAB引擎"""
        import matlab.engine
        self.matlab_engine = matlab.engine.start_matlab()
        self.matlab_engine.addpath(self.matlab_util_path, nargout=0)
    
    def export_intermediate_files(self, data_path):
        """导出中间文件，兼容现有MATLAB流程"""
        # 生成META_*.mat文件，包含同步数据
        meta_data = {
            'trial_valid_idx': self.data['sync_data']['trial_valid_idx'],
            'onset_time_ms': self.data['sync_data']['calibrated_onset_ms'],
            'img_size': self.data['sync_data']['img_size'],
            'g_number': self.data['metadata']['g_number'],
            'exp_subject': self.data['metadata']['exp_subject'],
            'exp_day': self.data['metadata']['exp_day']
        }
        
        # 保存为MATLAB可读格式
        from scipy.io import savemat
        meta_file = data_path / 'processed' / f"META_{meta_data['exp_day']}_{meta_data['exp_subject']}.mat"
        savemat(meta_file, meta_data)
    
    def run_matlab_postprocess(self, data_path):
        """运行MATLAB后处理函数"""
        if self.matlab_engine:
            # 调用PostProcess_function_raw.m
            self.matlab_engine.cd(str(data_path), nargout=0)
            self.matlab_engine.PostProcess_function_raw(str(data_path), nargout=0)
            
            # 调用PostProcess_function.m
            self.matlab_engine.PostProcess_function(str(data_path), nargout=0)
```

## 4. NWB Schema设计

### 4.1 完整版NWB结构
```
/ (root)
│-- session_description
│-- identifier
│-- session_start_time
│-- timestamps_reference_time
│-- experimenter
│-- experiment_description
│-- institution
│-- intervals
│   └-- trials (Table)
│       ├-- start_time
│       ├-- stop_time
│       └-- various trial conditions
│-- processing
│   └-- neural_data
│       ├-- ElectricalSeries (raw data)
│       ├-- spike_times (Units table)
│       ├-- waveforms
│       ├-- quality_metrics
│       └-- PSTH_responses
│-- acquisition
│   └-- behavior_data
│       ├-- eye_tracking
│       └-- task_events
│-- scratch (various analysis results)
```

### 4.2 简化版NWB结构(用于云备份)
```
/ (root)
│-- session_description
│-- identifier
│-- session_start_time
│-- experimenter
│-- intervals
│   └-- trials (Table)
│       ├-- start_time
│       ├-- stop_time
│       └-- various trial conditions
│-- processing
│   └-- analysis_data
│       ├-- Units (table)
│       │   ├-- spike_times
│       │   ├-- quality_metrics
│       │   └-- waveform_characteristics
│       ├-- PSTH_responses
│       └-- stimulus_response_profiles
```

## 5. Streamlit界面设计

### 5.1 主界面布局
```
侧边栏
├── 数据目录选择
├── 处理阶段显示
├── 参数配置区域
└── 操作按钮(开始处理、导出、备份)

主区域
├── 目录检查结果展示
├── 处理进度可视化
├── 中间结果预览(波形、Raster、PSTH等)
└── 最终报告生成
```

### 5.2 界面组件
```python
# 目录选择组件
data_dir = st.sidebar.text_input("数据目录", value="F:/data/raw/")
browse_btn = st.sidebar.button("浏览...")

# 处理阶段显示
if 'processing_stage' in st.session_state:
    st.sidebar.markdown(f"**当前阶段:** {st.session_state.processing_stage}")

# 参数配置
with st.sidebar.expander("处理参数"):
    n_jobs = st.slider("并行任务数", 1, 16, 12)
    chunk_duration = st.selectbox("分块时长", ['1s', '2s', '4s'], index=2)

# 操作按钮
col1, col2, col3 = st.sidebar.columns(3)
start_btn = col1.button("开始处理")
export_btn = col2.button("导出结果")
backup_btn = col3.button("云备份")
```

## 6. 更新开发路线图 (基于当前进度)

### 阶段1: 已完成 ✅
- ✅ 基础框架搭建和项目结构
- ✅ 数据加载与验证功能 (DataLoader)
- ✅ 尖峰排序模块 (SpikeSorter + Kilosort4)
- ✅ 同步与校验功能 (DataSynchronizer)
- ✅ 基本Streamlit界面框架

### 阶段2: 当前重点 🔄 (需要立即实施)
**优先级1: 质量控制重构**
- 🔄 重构QualityController，集成Bombcell Python API
- 🔄 实现qMetric和unitType获取功能
- 🔄 添加Bombcell参数配置和结果可视化

**优先级2: 数据整合优化**
- 🔄 重构DataIntegrator，基于Bombcell结果筛选good units
- 🔄 优化响应计算，使用同步校准后的onset时间
- 🔄 实现规范化的输出数据结构

### 阶段3: 输出模块开发 ❌ (紧接着实施)
**优先级3: NWB导出实现**
- ❌ 创建NWBExporter类，支持PyNWB格式
- ❌ 实现完整版NWB (本地保存，包含原始数据)
- ❌ 实现简化版NWB (云端备份，仅分析结果)

**优先级4: MATLAB兼容性**
- ❌ 创建MATExporter类，支持MATLAB引擎调用
- ❌ 实现中间文件导出 (META_*.mat等， 需增量改进 dataloader 与 synchronizer 确保元数据的完整)
- ❌ 集成现有MATLAB后处理函数

### 阶段4: 界面完善与集成 🔄 (并行进行)
**优先级5: Streamlit界面增强**
- 🔄 添加Bombcell参数配置界面
- 🔄 实现质量控制结果展示
- 🔄 添加NWB/MAT导出选项和进度监控
- 🔄 完善错误处理和用户反馈

### 阶段5: 测试与优化 ❌ (最后阶段)
- ❌ 端到端流程测试
- ❌ 性能优化和内存管理
- ❌ 用户文档和示例数据
- ❌ 部署和分发准备

## 7. 立即行动计划

### 第一步: 重构质量控制模块 (当前任务)
1. **安装和测试Bombcell环境**
   ```bash
   conda activate spikesort
   pip install bombcell
   ```

2. **重写quality_controller.py**
   - 集成Bombcell Python API
   - 实现run_bc.m等效功能
   - 添加参数配置和结果处理

3. **更新配置管理**
   - 在app_config.yaml中添加Bombcell参数配置
   - 支持自定义质量控制阈值

### 第二步: 重构数据整合模块
1. **更新data_integrator.py**
   - 基于Bombcell unitType进行神经元筛选
   - 使用同步数据的校准onset时间
   - 优化响应计算算法

2. **实现输出数据结构标准化**
   - 定义NWB兼容的数据结构
   - 支持多种导出格式的统一接口

### 第三步: 创建导出模块
1. **创建output目录和NWB导出器**
   ```
   output/
   ├── __init__.py
   ├── nwb_exporter.py
   ├── mat_exporter.py
   └── cloud_backup.py
   ```

2. **实现PyNWB集成**
   - 完整版NWB文件结构
   - 简化版分析数据结构
   - 元数据管理和验证

### 第四步: MATLAB兼容性集成
1. **实现MATLAB引擎接口**
   - 中间文件生成和管理
   - 现有.m函数调用封装
   - 错误处理和日志记录

2. **用户选择机制**
   - Streamlit界面中的导出格式选择
   - NWB vs MAT格式的优缺点说明
   - 混合导出支持 (本地NWB + 云端简化版)

## 8. 技术要求和依赖更新

### 新增Python依赖
```txt
# 质量控制
bombcell>=1.0.0

# NWB支持  
pynwb>=2.5.0
hdmf>=3.8.0

# MATLAB兼容性
matlab.engine  # 需要MATLAB安装

# 云存储支持 (可选)
boto3  # AWS S3
google-cloud-storage  # Google Cloud
```

### 环境配置要求
1. **spikesort conda环境** - 已有Bombcell安装
2. **MATLAB R2020b+** - 支持Python引擎 (可选)
3. **足够存储空间** - NWB文件可能很大
4. **网络连接** - 云端备份功能 (可选)

## 9. 关键技术挑战与解决方案

### 挑战1: Bombcell Python API集成
**问题**: 需要从MATLAB版本迁移到Python版本，保持功能一致性
**解决方案**: 
- 使用BC_demo.ipynb作为参考实现
- 确保qMetric和unitType输出格式与MATLAB版本兼容
- 添加参数验证和错误处理

### 挑战2: NWB格式复杂性
**问题**: NWB标准复杂，需要正确映射所有数据类型
**解决方案**:
- 分步实现：先基础结构，后完整功能
- 参考现有NWB示例和最佳实践
- 实现数据验证和完整性检查

### 挑战3: MATLAB引擎性能
**问题**: MATLAB引擎调用可能影响性能和稳定性
**解决方案**:
- 提供Python原生实现作为主要方案
- MATLAB引擎作为兼容性选项
- 实现异步调用和超时处理

### 挑战4: 大数据文件处理
**问题**: NWB文件可能非常大，影响I/O性能
**解决方案**:
- 实现分块写入和流式处理
- 提供压缩选项
- 分离完整版和简化版导出

## 10. 质量保证和测试策略

### 单元测试
- 每个核心模块的独立测试
- Bombcell集成的功能测试
- NWB文件格式验证测试

### 集成测试  
- 端到端流程测试
- 不同数据集的兼容性测试
- 性能基准测试

### 用户验收测试
- 现有MATLAB用户的迁移测试
- 新用户的易用性测试
- 错误场景的处理测试

## 11. 部署和维护

### 环境管理
- 提供完整的conda环境配置文件
- 依赖版本锁定和兼容性矩阵
- 自动化安装脚本

### 文档和培训
- 用户手册和API文档
- 视频教程和示例数据
- 迁移指南 (从MATLAB到Python)

### 持续维护
- 定期更新依赖包版本
- 新功能开发和bug修复
- 社区反馈收集和处理

---

## 📋 总结

此更新的开发计划基于当前项目的实际进度，明确了下一步的开发重点：

1. **立即任务**: 重构质量控制模块，集成Bombcell Python API
2. **核心目标**: 实现完整的NWB导出功能和MATLAB兼容性
3. **用户体验**: 完善Streamlit界面，提供直观的参数配置和结果展示
4. **技术债务**: 重构现有模块，提高代码质量和可维护性

该计划确保了项目的技术先进性（使用最新的Python生态工具）和实用性（保持与现有MATLAB流程的兼容），为神经科学研究提供了一个现代化、高效的数据处理解决方案。