# Spec: io/bhv.py

## 1. 目标

`BHV2Parser` 负责将 MonkeyLogic 的 BHV2 行为文件桥接到 Python 数据结构。BHV2（`.bhv2`）是 MonkeyLogic 专有的自定义二进制格式，**不是 HDF5 格式**，因此无法直接用 h5py 读取。读取 BHV2 的唯一方式是通过 MATLAB Python Engine（`matlab.engine`）调用 MATLAB 函数加载文件，将结果保存为 MATLAB v7.3 的 `.mat` 文件（该格式才是 HDF5），再由 Python 通过 h5py 读取中间 `.mat` 文件。本模块封装上述完整工作流，向上层（`synchronize` stage、`postprocess` stage）提供结构化的 `TrialData` 列表、session 元信息字典和逐 trial 的模拟信号数据。MATLAB Engine 实例延迟初始化（首次使用时启动）并缓存复用，避免重复启动开销。

## 2. 输入

- `BHV2Parser.__init__`: `bhv_file: Path` — BHV2 文件的绝对路径
- `BHV2Parser.parse`: 无额外参数；通过 MATLAB Engine 读取完整 TrialRecord
- `BHV2Parser.get_event_code_times`: `event_code: int`，可选 `trials: list[int] | None`（None 表示所有 trial）
- `BHV2Parser.get_session_metadata`: 无额外参数；通过 MATLAB Engine 读取 MLConfig
- `BHV2Parser.get_analog_data`: `channel_name: str`，可选 `trials: list[int] | None`（None 表示所有 trial）

## 3. 输出

- `__init__`: 无返回值；若文件不存在则 raise `FileNotFoundError`；若前 21 字节不匹配 `BHV2_MAGIC` 则 raise `IOError`
- `parse()` → `list[TrialData]`，按 `trial_id` 升序排列；结果缓存
- `get_event_code_times()` → `list[tuple[int, float]]`，每个元素为 `(trial_id, time_ms)`，按 trial_id 升序
- `get_session_metadata()` → `dict`，包含以下字段（均来自 BHV2 文件的 `MLConfig` 变量）：
  - `ExperimentName`：实验名称字符串（`MLConfig.ExperimentName`）
  - `MLVersion`：MonkeyLogic 版本字符串（`MLConfig.MLVersion`）
  - `SubjectName`：受试者名称字符串（`MLConfig.SubjectName`）
  - `TotalTrials`：int，由文件中 `TrialN` 变量数量统计得到
- `get_analog_data()` → `dict[int, np.ndarray]`，键为 `trial_id`，值为该 trial 的模拟信号数组（shape: `[n_samples, n_channels_for_that_analog]`）；不含目标通道的 trial 被跳过（记录警告日志）

## 4. 处理步骤

### BHV2Parser.__init__

1. 验证 `bhv_file` 存在，不存在则 raise `FileNotFoundError`
2. 以二进制模式打开文件，读取前 21 个字节，验证是否等于 `BHV2_MAGIC`（`b'\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition'`）；字节数不足或内容不匹配则 raise `IOError("Not a valid BHV2 file: {bhv_file}")`
   - Magic 结构说明：前 8 字节为 uint64 LE 值 13（即字符串 "IndexPosition" 的长度），后 13 字节为字符串 `b'IndexPosition'`，合计 21 字节
3. 将 `bhv_file` 存为 `self.bhv_file`
4. 设置 `self._engine = None`（延迟初始化，不在 `__init__` 中启动 MATLAB）
5. 设置 `self._cache = None`

### _get_engine

1. 若 `self._engine is None`，调用 `matlab.engine.start_matlab()` 启动 MATLAB Engine，赋值给 `self._engine`
2. 将 `mlbhv2.m` 所在目录（`legacy_reference/pyneuralpipe/Util/`，相对项目根目录）添加到 MATLAB path：`eng.addpath(...)`
3. 返回 `self._engine`

### parse

1. 若 `self._cache is not None`，直接返回缓存，不重复调用 MATLAB
2. 调用 `self._get_engine()` 获取 MATLAB Engine 实例
3. 在 MATLAB 中打开 BHV2 文件：`b = mlbhv2(bhv_file_path)`
4. 枚举文件中所有变量名（`b.who()`），过滤出名称匹配 `^Trial\d+$` 的变量（如 `Trial1`, `Trial2`, ...）
5. 对每个 `TrialN` 变量：
   a. `trial = b.read('TrialN')` 读取 trial struct
   b. 提取 `trial.Trial` → `trial_id: int`
   c. 提取 `trial.Condition` → `condition_id: int`
   d. 提取 `trial.BehavioralCodes.CodeTimes`（ms）和 `trial.BehavioralCodes.CodeNumbers`，zip 为 `list[tuple[float, int]]`（time_ms, code）
   e. 提取 `trial.UserVars`（MATLAB engine 返回 Python `dict`）；若为空则用空 dict
   f. 构造 `TrialData(trial_id=trial_id, condition_id=condition_id, events=events, user_vars=user_vars)`
6. 按 `trial_id` 升序排序
7. 将结果赋值给 `self._cache`，返回

### get_event_code_times

1. 调用 `self.parse()` 获取所有 trial 数据（缓存命中则不重复调用 MATLAB）
2. 若 `trials` 不为 None，过滤只保留指定 trial_id
3. 对每个 trial 的 events 列表，找出所有 `code == event_code` 的条目
4. 收集为 `[(trial_id, time_ms), ...]` 列表，按 trial_id 升序返回；未找到任何匹配则返回空列表

### get_session_metadata

1. 调用 `self._get_engine()` 获取 MATLAB Engine 实例
2. 在 MATLAB 中打开 BHV2 文件，读取 `MLConfig` 变量：`b = mlbhv2(path); cfg = b.read('MLConfig')`
3. 读取文件中所有 `TrialN` 变量的数量，得到 `TotalTrials`
4. 返回 dict：
   - `ExperimentName`: `str(cfg.ExperimentName)`
   - `MLVersion`: `str(cfg.MLVersion)`
   - `SubjectName`: `str(cfg.SubjectName)`
   - `TotalTrials`: `int`（TrialN 变量数量）

### get_analog_data

1. 调用 `self._get_engine()` 获取 MATLAB Engine 实例
2. 若 `trials` 为 None，通过 `parse()` 获取所有 trial_id 列表
3. **逐 trial 分块处理**（严禁预分配 3D 矩阵）：
   a. 对每个 trial_id，通过 MATLAB Engine 访问该 trial 的 `AnalogData[channel_name]`
   b. 若该 trial 不含目标 `channel_name`，记录 warning 日志，跳过该 trial（不 raise 异常）
   c. 将返回的数据转换为 `np.ndarray`，shape 为 `[n_samples, n_channels_for_that_analog]`
   d. 将 `trial_id → np.ndarray` 键值对写入结果 dict
4. 返回结果 dict

## 5. 公开 API 与可配参数

```python
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from pathlib import Path

# BHV2 文件魔数：uint64 LE 值 13（"IndexPosition" 的字符串长度）+ b'IndexPosition'
BHV2_MAGIC: bytes = b'\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition'


@dataclass
class TrialData:
    """单个 MonkeyLogic trial 的行为数据。

    Attributes:
        trial_id: BHV2 TrialRecord 中以 1 为起点的 trial 序号。
        condition_id: 该 trial 所属的条件编号。
        events: (time_ms, event_code) 元组列表，时间以行为时钟 ms 为单位。
        user_vars: 任务脚本中记录的用户自定义变量字典。
    """
    trial_id: int
    condition_id: int
    events: list[tuple[float, int]]
    user_vars: dict = field(default_factory=dict)


class BHV2Parser:
    """MonkeyLogic BHV2 文件解析器。

    BHV2 是 MonkeyLogic 专有的自定义二进制格式，读取必须依赖 MATLAB Python Engine。
    Engine 实例在首次调用时延迟启动，并在整个 parser 生命周期内缓存复用。

    Args:
        bhv_file: BHV2 文件的绝对路径（.bhv2 扩展名）。

    Raises:
        FileNotFoundError: 若 bhv_file 不存在。
        IOError: 若文件前 21 字节不匹配 BHV2_MAGIC，即不是合法的 BHV2 文件。
    """

    BHV2_MAGIC: bytes = b'\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition'

    def __init__(self, bhv_file: Path) -> None: ...

    def parse(self) -> list[TrialData]:
        """通过 MATLAB Engine 加载全部 trial 数据。

        首次调用时启动 MATLAB Engine（若尚未启动），结果缓存后续调用直接返回。

        Returns:
            按 trial_id 升序排列的 TrialData 列表。
        """

    def get_event_code_times(
        self,
        event_code: int,
        trials: list[int] | None = None,
    ) -> list[tuple[int, float]]:
        """返回指定事件码在各 trial 中出现的时间戳列表。

        Args:
            event_code: 要查询的整数事件码。
            trials: 可选，限制查询范围的 trial_id 列表；None 表示所有 trial。

        Returns:
            (trial_id, time_ms) 元组列表，按 trial_id 升序；未找到则返回空列表。
        """

    def get_session_metadata(self) -> dict:
        """通过 MATLAB Engine 提取 session 级别元信息（来自 MLConfig）。

        Returns:
            包含 ExperimentName、MLVersion、TotalTrials、DatasetName、
            DataFileBaseName 的字典。
        """

    def get_analog_data(
        self,
        channel_name: str,
        trials: list[int] | None = None,
    ) -> dict[int, np.ndarray]:
        """逐 trial 读取模拟信号数据（Eye、Joystick 等）。

        数据按 trial 分块读取，不预分配 3D 矩阵，确保内存安全。
        不含目标通道的 trial 被跳过并记录警告日志，不 raise 异常。

        Args:
            channel_name: 模拟通道名称，如 'Eye'、'Joystick'。
            trials: 可选，限制读取范围的 trial_id 列表；None 表示所有 trial。

        Returns:
            dict，键为 trial_id，值为 np.ndarray（shape: [n_samples, n_channels]）。
        """

    def _get_engine(self):
        """延迟初始化并返回 MATLAB Engine 实例。

        首次调用时调用 matlab.engine.start_matlab()，后续复用已有实例。

        Returns:
            已启动的 matlab.engine 实例。
        """
```

**可配参数**：本模块自身无配置项；调用方（`synchronize` stage、`postprocess` stage）通过 `config.sync` 和 `config.postprocess` 控制所需事件码、通道名等参数。

## 6. 测试范围（TDD 用）

**测试数据**：`F:\#Datasets\demo_rawdata\241026_MaoDan_YJ_WordLOC.bhv2`（真实 BHV2 文件，包含 11 个 trial，magic bytes 已验证匹配）

**测试策略**：
- **禁止使用任何 mock**，所有测试使用真实 MATLAB Engine 启动
- `conftest.py` 中配置 `MATLAB_RUNTIME` PATH（`C:/Program Files/MATLAB/R2024b/runtime/win64`），并提供 session 级别的 MATLAB engine fixture（避免重复启动）
- `_get_engine` 的 `matlab.engine.start_matlab()` 通过 `BHV2Parser` 真实调用，无 mock

**已知真实文件结构**（探测自 `241026_MaoDan_YJ_WordLOC.bhv2`）：
- 变量：`IndexPosition`, `FileInfo`, `MLConfig`, `Trial1`…`Trial11`, `TrialRecord`, `FileIndex`
- 每个 trial 字段：`Trial`（trial_id）, `Condition`（condition_id）, `BehavioralCodes.CodeTimes/CodeNumbers`, `AnalogData`, `UserVars`
- MLConfig 实际存在的字段：`ExperimentName`（="PV"）, `MLVersion`（="2.2.42 (Dec 15, 2023)"）, `SubjectName`
- AnalogData 通道：`Eye`, `Eye2`, `Joystick`, `PhotoDiode` 等

| 测试组 | 用例 | 预期行为 |
|---|---|---|
| `__init__` 正常 | 真实 BHV2 文件 | 正常构造，无异常 |
| `__init__` 错误 | 文件不存在 | raise `FileNotFoundError` |
| `__init__` 错误 | 文件存在但前 21 字节不匹配 BHV2_MAGIC | raise `IOError` |
| `__init__` 错误 | 文件不足 21 字节（过短） | raise `IOError` |
| `__init__` 延迟 | 构造后检查 `_engine` 属性 | `_engine` 为 None（Engine 未启动） |
| `_get_engine` | 首次调用 | 返回可用 MATLAB engine 实例（真实启动） |
| `_get_engine` | 连续调用两次 | 返回同一 engine 实例（不重复启动） |
| `parse` | 真实文件，11 trials | 返回长度为 11 的列表 |
| `parse` | 检查第一个 trial | trial_id=1, condition_id 为 int, events 非空 |
| `parse` | 检查 events 结构 | 每个 event 为 (float, int) 元组 |
| `parse` | 检查排序 | 返回列表按 trial_id 升序 |
| `parse` | 连续调用两次 | 第二次返回同一列表对象（缓存命中） |
| `get_event_code_times` | event_code 存在于多个 trial | 返回 (trial_id, time_ms) 列表，长度 >= 1 |
| `get_event_code_times` | `trials` 参数限定子集 | 仅返回指定 trial 的事件 |
| `get_event_code_times` | event_code 不存在 | 返回空列表 |
| `get_session_metadata` | 真实文件 | 返回 dict 含 ExperimentName="PV" |
| `get_session_metadata` | 真实文件 | TotalTrials=11 |
| `get_analog_data` | channel_name='Eye' | 返回 `dict[int, np.ndarray]`，所有 11 个 trial |
| `get_analog_data` | `trials=[1, 2]` | 只返回 trial 1 和 2 |
| `get_analog_data` | channel_name 不存在 | 返回空 dict，记录 warning |
| `_get_engine` | 首次调用 | `matlab.engine.start_matlab` 被调用一次 |
| `_get_engine` | 连续调用两次 | `start_matlab` 仅调用一次（复用缓存） |
| `parse` | 含 3 个 trial 的合成数据（mocked engine） | 返回长度为 3 的列表，trial_id 按序 |
| `parse` | trial 含多个 events | events 列表长度与 codes 数组长度一致 |
| `parse` | trial 含 user_vars | user_vars dict 含对应 key |
| `parse` | trial 无 user_vars 字段 | user_vars 为空 dict |
| `parse` | 连续调用两次 | 第二次返回同一对象（不重复调用 MATLAB Engine） |
| `parse` | trial_id 在原始数据中无序排列 | 返回列表已按 trial_id 升序排序 |
| `get_event_code_times` | event_code 在多个 trial 中出现 | 返回所有 (trial_id, time_ms) 元组 |
| `get_event_code_times` | `trials` 参数限定子集 | 仅返回指定 trial 中的事件 |
| `get_event_code_times` | event_code 不存在于任何 trial | 返回空列表 |
| `get_session_metadata` | MLConfig 含 ExperimentName、TotalTrials | 返回 dict 含对应 key-value |
| `get_session_metadata` | MLConfig 含 DatasetName、DataFileBaseName | dict 含这两个字段 |
| `get_analog_data` | 指定 channel 存在于所有 trial | 返回 `dict[int, np.ndarray]`，键为 trial_id |
| `get_analog_data` | `trials=None` | 处理全部 trial |
| `get_analog_data` | 部分 trial 不含目标 channel | 缺失 trial 被跳过，记录 warning，不 raise |
| `get_analog_data` | 检查内存模式 | 不预分配 3D 矩阵（验证 mock 调用模式为逐 trial） |

## 7. 依赖

- 标准库：`pathlib.Path`，`dataclasses.dataclass, field`，`tempfile`，`logging`
- 第三方（必选）：
  - `matlab.engine`：MATLAB Python Engine，读取 BHV2 的唯一途径；**要求本机安装 MATLAB**
  - `h5py`：读取 MATLAB Engine 输出的中间 `.mat`（v7.3 = HDF5）文件
  - `numpy`：数组类型转换与操作
- 注意：BHV2 文件本身是 MonkeyLogic 专有二进制格式，**不是 HDF5**，h5py 无法直接读取，必须经由 MATLAB Engine 转换。

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #2（BHV2 发现与解析）, #3（BHV2 文件名解析） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #2, #3; `docs/ground_truth/step5_matlab_vs_python.md` step #2, #3 |

### 有意偏离

| 偏离 | 理由 |
|------|------|
| MATLAB Engine 桥接而非原生 Python 解析 | BHV2 是 MonkeyLogic 专有格式，有公开文档和源码 mlbhv2.m，MATLAB Engine 是唯一可靠解析途径；feature 分支将开发 pure-Python parser |
| 输出 TrialData list 而非 struct array | MATLAB 直接操作 struct array；Python 转换为 dataclass list 更类型安全 |
| h5py 作为中间格式 | MATLAB Engine 返回的 cell/struct 需要通过 .mat v7.3 (HDF5) 序列化到 Python 侧；step5 指出此处有 170+ 行解析复杂度 |
| DatasetName 直接从 metadata 提取 | MATLAB step #3 解析 Windows 路径字符串（`find(=='\')`, 截取 -4 字符）；Python 通过 `get_session_metadata()` 结构化提取 |
| 文件名格式假设不同 | step5 指出 MATLAB 的 split index 假设（截取文件名特定位置字符）与 Python 不同，可能在某些命名规范下出错 |
