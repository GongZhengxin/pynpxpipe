# NWB 文件创建和处理脚本

## 概述

`savenwb.py` 是一个完整的 NWB (Neurodata Without Borders) 文件创建和处理脚本，按照注释目标实现了以下功能：

1. **Step 1**: 创建原始数据转换器并转换为 NWB 文件
2. **Step 2**: 将 Kilosort 排序结果写入现有 NWB 文件作为处理模块
3. **Step 3**: 写入自定义单元属性到现有 NWB 文件
4. **Step 4**: 将刺激数据写入现有 NWB 文件
5. **Step 5**: 写入眼动追踪数据到现有 NWB 文件
6. **Step 6**: 写入试次事件到现有 NWB 文件
7. **Step 7**: 更新元数据和被试元数据到现有 NWB 文件

## 依赖包

运行此脚本需要以下 Python 包：

```bash
pip install pynwb neuroconv numpy scipy h5py dateutil
```

## 主要特性

### 1. 智能数据处理
- 自动检测真实数据的可用性
- 如果真实数据不可用，自动生成合理的模拟数据
- 错误处理和安全操作包装

### 2. 完整的 NWB 结构
- **采集数据**: SpikeGLX 原始神经信号
- **单元数据**: Kilosort 排序结果 + 自定义质量指标
- **行为数据**: 眼动追踪和瞳孔大小
- **刺激数据**: 视觉刺激序列
- **试次数据**: 完整的试次表格和行为事件
- **元数据**: 被试信息、实验描述、设备信息

### 3. 数据压缩优化
- 使用 Blosc-zstd 压缩算法
- 优化的 chunk 大小配置
- 针对不同数据类型的压缩设置

## 使用方法

### 基本使用

```python
# 直接运行脚本
python savenwb.py
```

### 自定义路径

修改脚本中的路径配置：

```python
# 修改数据路径
folder_path = Path(r"your/spikeglx/data/path")
kilosort_folder = Path(r"your/kilosort/output/path")

# 修改输出路径
output_folder = Path(r'your/output/path')
nwbfile_path = output_folder / "your_session.nwb"
```

## 输出结果

脚本会创建一个完整的 NWB 文件，包含：

- **原始电生理数据** (压缩存储)
- **排序单元** (50-数百个神经元)
- **单元质量指标** (SNR, 隔离距离, 污染率等)
- **眼动数据** (500Hz 采样的眼位和瞳孔大小)
- **刺激序列** (时间戳和刺激类型)
- **试次表格** (300个试次的完整信息)
- **完整元数据** (被试、实验、设备信息)

## 验证和检查

脚本会自动验证最终的 NWB 文件：

```
📊 NWB 文件内容验证:
✓ 会话描述: Visual word-form discrimination task with Neuropixels recording
✓ 被试ID: MD241029
✓ 电极数量: 384
✓ 单元数量: 50
✓ 试次数量: 300
✓ 处理模块: ['stimulus', 'behavior', 'events']
✓ 采集数据: ['ElectricalSeriesAP', 'ElectricalSeriesLF']

📈 文件大小: 1234.5 MB
```

## 高级功能

### 1. 真实数据集成

如果以下路径存在真实数据，脚本会自动使用：

```python
data_paths = {
    'kilosort_folder': Path(r"F:\ProcessPipeline\testdata\wordfob\kilosort_def_5block_97\sorter_output"),
    'stimulus_folder': Path(r"F:\ProcessPipeline\testdata\wordfob\stimulus_images"),
    'behavior_file': Path(r"F:\ProcessPipeline\testdata\wordfob\behavior_data.mat"),
    'eye_tracking_file': Path(r"F:\ProcessPipeline\testdata\wordfob\eye_tracking.csv")
}
```

### 2. 错误处理

所有关键操作都包装在安全函数中：

```python
def safe_nwb_operation(operation_name, operation_func):
    try:
        result = operation_func()
        print(f"✅ {operation_name}: 成功")
        return result
    except Exception as e:
        print(f"❌ {operation_name}: 失败 - {str(e)}")
        return None
```

### 3. 模块化设计

每个步骤都封装为独立函数，便于调试和修改：

- `add_kilosort_results()`: 添加排序结果
- `add_custom_unit_properties()`: 添加自定义单元属性
- `add_stimulus_data()`: 添加刺激数据
- `add_behavioral_and_metadata()`: 添加行为数据和元数据
- `validate_nwb_file()`: 验证最终文件

## 注意事项

1. **内存使用**: 大文件处理时注意内存使用
2. **磁盘空间**: NWB 文件可能很大，确保有足够磁盘空间
3. **数据路径**: 确保所有数据路径正确
4. **权限**: 确保对输出目录有写权限

## 故障排除

### 常见问题

1. **导入错误**: 确保安装了所有依赖包
2. **路径错误**: 检查数据文件路径是否正确
3. **内存不足**: 减少数据量或增加系统内存
4. **权限问题**: 确保对输出目录有写权限

### 调试模式

如需调试，可以单独运行各个步骤：

```python
# 只运行特定步骤
result = safe_nwb_operation("添加 Kilosort 结果", add_kilosort_results)
```

## 扩展功能

脚本设计为模块化，可以轻松添加新功能：

1. 添加更多质量指标
2. 集成其他数据类型
3. 自定义压缩设置
4. 添加数据验证检查

## 参考资料

- [PyNWB 文档](https://pynwb.readthedocs.io/)
- [NeuroConv 文档](https://neuroconv.readthedocs.io/)
- [NWB 标准](https://nwb-schema.readthedocs.io/)
- [SpikeInterface 文档](https://spikeinterface.readthedocs.io/)
