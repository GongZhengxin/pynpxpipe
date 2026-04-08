# BHV2 数据消费点分析

## 分析来源
- **MATLAB 主流程**：`legacy_reference/pyneuralpipe/Util/Load_Data_function.m`
- **MATLAB 后处理**：`legacy_reference/pyneuralpipe/Util/PostProcess_function_raw.m`
- **Python 对照**：`legacy_reference/pyneuralpipe/core/synchronizer.py`, `data_loader.py`

---

## 消费点记录

### 消费点 #1
- **位置**：Load_Data_function.m:47
- **访问路径**：`trial_ML(tt).BehavioralCodes.CodeNumbers`
- **用途**：统计每个 trial 中 onset 事件（code=64）的数量
- **数据特征**：数值数组，元素为事件码（整数），包含 64（onset）、32（offset）等
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:195-203

---

### 消费点 #2
- **位置**：Load_Data_function.m:49
- **访问路径**：`trial_ML(tt).BehavioralCodes.CodeNumbers`
- **用途**：统计每个 trial 中 offset 事件（code=32）的数量
- **数据特征**：同消费点 #1
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:195-203

---

### 消费点 #3
- **位置**：Load_Data_function.m:79
- **访问路径**：`trial_ML(trial_idx).UserVars.DatasetName`
- **用途**：提取数据集名称（图片集路径），用于后续解析图片集名称
- **数据特征**：字符串，Windows 路径格式（包含反斜杠），例如 `'C:\path\to\dataset.tsv'`
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:244-252

---

### 消费点 #4
- **位置**：Load_Data_function.m:96
- **访问路径**：`trial_ML(trial_idx).VariableChanges.onset_time`
- **用途**：获取刺激呈现持续时间（onset duration），单位 ms
- **数据特征**：标量数值，表示刺激呈现时长
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:268

---

### 消费点 #5
- **位置**：Load_Data_function.m:97
- **访问路径**：`trial_ML(trial_idx).BehavioralCodes.CodeNumbers`
- **用途**：获取行为事件码序列，用于定位 onset 事件位置
- **数据特征**：数值数组，事件码序列
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:269

---

### 消费点 #6
- **位置**：Load_Data_function.m:98
- **访问路径**：`trial_ML(trial_idx).BehavioralCodes.CodeTimes`
- **用途**：获取行为事件时间戳序列，与 CodeNumbers 一一对应
- **数据特征**：数值数组，时间戳（单位 ms），与 CodeNumbers 长度相同
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:270

---

### 消费点 #7
- **位置**：Load_Data_function.m:101
- **访问路径**：`trial_ML(trial_idx).UserVars.Current_Image_Train`
- **用途**：获取当前 trial 呈现的图片索引序列（每个 onset 对应一个图片 ID）
- **数据特征**：数值数组，图片索引（整数），长度 >= onset_times_this_trial
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:273

---

### 消费点 #8
- **位置**：Load_Data_function.m:102
- **访问路径**：`trial_ML(trial_idx).UserVars.DatasetName`
- **用途**：获取数据集名称，用于匹配 dataset_pool 中的索引
- **数据特征**：字符串，数据集路径
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:274

---

### 消费点 #9
- **位置**：Load_Data_function.m:105
- **访问路径**：`trial_ML(trial_idx).AnalogData.SampleInterval`
- **用途**：获取模拟数据采样间隔（ms），用于将时间戳转换为采样点索引
- **数据特征**：标量数值，采样间隔（ms）
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:278

---

### 消费点 #10
- **位置**：Load_Data_function.m:108
- **访问路径**：`trial_ML(trial_idx).AnalogData.Eye`
- **用途**：获取眼动数据矩阵，用于眼动验证
- **数据特征**：2D 数组，shape=(n_samples, 2)，列分别为 Eye_X 和 Eye_Y，单位为度（degree）
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:281-285

---

### 消费点 #11
- **位置**：Load_Data_function.m:116
- **访问路径**：`trial_ML(trial_idx).VariableChanges.fixation_window`
- **用途**：获取注视窗口半径阈值，用于判断眼动是否在有效范围内
- **数据特征**：标量数值，注视窗口半径（度）
- **是否有对应的 Python 旧代码实现**：有，synchronizer.py:289

---

### 消费点 #12
- **位置**：PostProcess_function_raw.m:9
- **访问路径**：`trial_ML` (整体)
- **用途**：加载完整的 trial_ML 结构体，用于后续处理
- **数据特征**：结构体数组，每个元素是一个 trial 的完整数据
- **是否有对应的 Python 旧代码实现**：有，data_loader.py:300-400（mlread 调用）

---

### 消费点 #13
- **位置**：PostProcess_function_raw.m:15-16
- **访问路径**：`trial_ML(trial_idx).AnalogData.Mouse`, `trial_ML(trial_idx).AnalogData.KeyInput`
- **用途**：清空 Mouse 和 KeyInput 数据（减小文件大小）
- **数据特征**：数组（被清空前可能包含鼠标/键盘输入数据）
- **是否有对应的 Python 旧代码实现**：无

---

### 消费点 #14
- **位置**：PostProcess_function.m:92
- **访问路径**：`trial_ML` (整体)
- **用途**：保存到最终输出的 MAT 文件中
- **数据特征**：完整的 trial_ML 结构体数组
- **是否有对应的 Python 旧代码实现**：无（Python 版本导出到 HDF5）

---

## 汇总表

### 表一：BHV2 字段需求清单

| 字段路径 | 数据类型 | 用途 | 消费方 | 备注 |
|---------|---------|------|--------|------|
| `BehavioralCodes.CodeNumbers` | int array | 事件码序列，用于识别 onset/offset 事件 | Load_Data_function.m:47,49,97 | 关键事件码：64=onset, 32=offset |
| `BehavioralCodes.CodeTimes` | float array | 事件时间戳（ms），与 CodeNumbers 对应 | Load_Data_function.m:98 | 用于时间对齐 |
| `UserVars.DatasetName` | string | 数据集路径（图片集文件路径） | Load_Data_function.m:79,102 | Windows 路径格式，含反斜杠 |
| `UserVars.Current_Image_Train` | int array | 当前 trial 呈现的图片索引序列 | Load_Data_function.m:101 | 长度 >= onset 数量 |
| `VariableChanges.onset_time` | scalar | 刺激呈现持续时间（ms） | Load_Data_function.m:96 | 用于计算眼动验证窗口 |
| `VariableChanges.fixation_window` | scalar | 注视窗口半径（度） | Load_Data_function.m:116 | 眼动验证阈值 |
| `AnalogData.Eye` | float array (n×2) | 眼动数据矩阵 [Eye_X, Eye_Y] | Load_Data_function.m:108 | 单位：度，列0=X, 列1=Y |
| `AnalogData.SampleInterval` | scalar | 模拟数据采样间隔（ms） | Load_Data_function.m:105 | 用于时间戳→采样点转换 |
| `AnalogData.Mouse` | array | 鼠标输入数据（被清空） | PostProcess_function_raw.m:15 | 仅用于清空，不实际使用 |
| `AnalogData.KeyInput` | array | 键盘输入数据（被清空） | PostProcess_function_raw.m:16 | 仅用于清空，不实际使用 |

---

### 表二：BHV2 字段访问路径（按层级）

```
trial_ML (array of structs)
└── trial_ML(i) (single trial)
    ├── BehavioralCodes
    │   ├── CodeNumbers      [消费点 #1, #2, #5]
    │   └── CodeTimes        [消费点 #6]
    ├── AnalogData
    │   ├── Eye              [消费点 #10]
    │   ├── SampleInterval   [消费点 #9]
    │   ├── Mouse            [消费点 #13, 仅清空]
    │   └── KeyInput         [消费点 #13, 仅清空]
    ├── UserVars
    │   ├── DatasetName      [消费点 #3, #8]
    │   └── Current_Image_Train [消费点 #7]
    └── VariableChanges
        ├── onset_time       [消费点 #4]
        └── fixation_window  [消费点 #11]
```

---

## ✅ 验证结果（已用真实数据验证）

**验证数据**: `F:\#Datasets\demo_rawdata\241026_MaoDan_YJ_WordLOC.bhv2` (11 trials)

### 验证项 1: AnalogData.Eye 的 shape
- **结论**: ✅ 严格为 `(n_samples, 2)`
- **证据**: 所有 11 个 trial 的 Eye 数据第二维度均为 2
- **样本**: Trial 1: [490, 2], Trial 2: [10785, 2], Trial 4: [25560, 2]

### 验证项 2: Current_Image_Train 长度 vs onset 数量
- **结论**: ✅ 长度固定为 1000，远大于实际 onset 数量
- **证据**: 所有 trial 的 `Current_Image_Train` 长度均为 1000，而 onset_count 范围 3-338
- **代码行为**: `Load_Data_function.m:101` 使用 `Current_Image_Train(1:onset_times_this_trial)` 截取前 N 个元素

### 验证项 3: SampleInterval 单位
- **结论**: ✅ 单位为毫秒（ms）
- **证据**: 所有 trial 的 `SampleInterval = 4.0`
- **推断依据**: 250 Hz 采样率 = 1000/250 = 4 ms

### 验证项 4: CodeTimes 的时间基准
- **结论**: ✅ 相对于 trial 开始时刻，单位 ms
- **证据**: 各 trial 的 `min(CodeTimes)` 接近 0（范围 0.52-2.89 ms）
- **样本**: Trial 2: [0.59, 43135.64] ms, Trial 4: [0.53, 102239.08] ms

---

## ❌ 与 Python 旧代码的差异

| 差异描述 | MATLAB 行为 | Python 旧代码行为 | 严重程度 |
|---------|------------|-----------------|---------|
| Mouse/KeyInput 清空 | 显式清空（PostProcess_function_raw.m:15-16） | 未实现清空逻辑 | 实现差异 |
| 数据集名称解析 | 使用反斜杠分割 Windows 路径（Load_Data_function.m:83） | 使用 Path 对象处理（synchronizer.py:250） | 实现差异 |
| 眼动矩阵预分配 | 动态预分配 3D 矩阵（Load_Data_function.m:110） | 按 trial 分块处理（synchronizer.py:281-285） | 实现差异 |
| trial_ML 保存格式 | 保存到 MAT v7.3（PostProcess_function.m:92） | 导出到 HDF5（synchronizer.py:900+） | 实现差异 |

---

## 补充说明

### 关键事件码定义（从代码推断）
- **64**：onset 事件（刺激呈现开始）
- **32**：offset 事件（刺激呈现结束）

### 数据流向
1. **Load_Data_function.m** 读取 BHV2 → 提取同步信息、眼动验证 → 保存到 `META_*.mat`
2. **PostProcess_function_raw.m** 加载 `ML_*.mat`（包含 trial_ML）→ 清空冗余字段 → 保存到 `GoodUnitRaw_*.mat`
3. **PostProcess_function.m** 加载 `GoodUnitRaw_*.mat` → 使用 trial_ML 进行 PSTH 计算 → 保存到 `GoodUnit_*.mat`

### Python 旧代码的主要问题
- 未实现 Mouse/KeyInput 清空（可能导致文件过大）
- 眼动矩阵处理方式不同（MATLAB 预分配 3D，Python 分块处理）
- 输出格式不同（MATLAB 用 MAT v7.3，Python 用 HDF5）
