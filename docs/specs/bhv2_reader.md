# Spec: io/bhv2_reader.py — Pure-Python BHV2 解析器

## 1. 目标

实现纯 Python 的 MonkeyLogic BHV2 二进制格式解析器，去除对 MATLAB Engine 的运行时依赖。

BHV2 是 MonkeyLogic v2 的专有二进制格式，**不是 HDF5**。当前实现 (`io/bhv.py`) 通过 MATLAB Engine 调用 `mlbhv2.m` 读取。本模块直接用 Python `struct` 模块解析二进制数据，产出与现有 `TrialData` / `BHV2Parser` 完全兼容的接口。

**约束**：
- 公开 API（`BHV2Parser.parse()`, `get_event_code_times()`, `get_session_metadata()`, `get_analog_data()`）签名和返回值不变
- 上层消费者（`synchronize` / `postprocess` stage）的现有测试全部通过
- 无 MATLAB 依赖；`matlabengine` 仅作为 optional 对比验证后端

---

## 2. BHV2 二进制格式（逆向自 mlbhv2.m）

### 2.1 文件总体结构

```
┌─────────────────────────────────────────────┐
│ Variable 0: "IndexPosition"                 │  ← 文件头 / Magic
│   uint64 LE: 13 (name length)               │
│   char[13]: "IndexPosition"                 │
│   <variable body: uint64 offset value>      │
├─────────────────────────────────────────────┤
│ Variable 1 ... Variable N                   │  ← 顺序存储的变量
│   (Trial1, Trial2, ..., MLConfig, etc.)     │
├─────────────────────────────────────────────┤
│ FileIndex (at offset from IndexPosition)    │  ← 变量索引表
│   cell array: {name, start_byte, end_byte}  │
└─────────────────────────────────────────────┘
```

### 2.2 Magic / 文件头

前 21 字节：
```
Bytes 0-7:    uint64 LE = 13 (字符串长度)
Bytes 8-20:   b'IndexPosition' (ASCII)
```

之后紧跟 IndexPosition 变量的 body（包含一个 uint64，指向 FileIndex 的字节偏移）。

### 2.3 变量编码格式

每个变量的序列化格式（对应 mlbhv2.m `read_variable` 方法）：

```
┌────────────────────────────────────────────┐
│ uint64: name_length                        │
│ char[name_length]: variable_name           │
│ uint64: type_length                        │
│ char[type_length]: type_string             │
│ uint64: ndim (维度数)                       │
│ uint64[ndim]: size_array (各维度大小)        │
│ <type-specific payload>                     │
└────────────────────────────────────────────┘
```

### 2.4 类型反序列化规则

| type_string | 反序列化逻辑 |
|------------|-------------|
| `double` | 直接读取 `prod(size) * 8` 字节，解析为 float64 LE，reshape 为 size (Fortran order) |
| `single` | 直接读取 `prod(size) * 4` 字节，解析为 float32 LE，reshape |
| `char` | 直接读取 `prod(size)` 字节，解码为 UTF-8 字符串 |
| `logical` | 直接读取 `prod(size)` 字节，每字节一个 bool |
| `uint8` | 直接读取 `prod(size) * 1` 字节 |
| `uint16` | 直接读取 `prod(size) * 2` 字节 |
| `uint32` | 直接读取 `prod(size) * 4` 字节 |
| `uint64` | 直接读取 `prod(size) * 8` 字节 |
| `int8/16/32/64` | 同上，有符号版本 |
| `struct` | 读取 `uint64 nfield`，然后对 `prod(size)` 个元素依次递归读取 nfield 个字段 |
| `cell` | 对 `prod(size)` 个元素依次递归读取（每个元素是独立变量） |
| `ml*` 前缀 | 视为 `struct`（MonkeyLogic 自定义类的向后兼容） |
| `string` | 读取为 cell array，取内部 char |
| `containers.Map` | 读取 keys 变量 + values 变量，组装为 dict |

**Fortran order 注意**：MATLAB 存储为列优先；Python numpy `reshape(size, order='F')` 可对齐。

### 2.5 FileIndex 结构

FileIndex 本身是一个 cell array（类型 `cell`，size `[N, 3]`），每行：
- `[0]`: 变量名 (char)
- `[1]`: 起始字节偏移 (double → int)
- `[2]`: 结束字节偏移 (double → int)

---

## 3. Trial 结构体布局

从消费分析 (`docs/ground_truth/bhv2_consumption_analysis.md`) 和真实数据验证得知：

```
Trial{N} (struct)
├── Trial: double scalar → int (trial_id, 1-indexed)
├── Condition: double scalar → int (condition_id)
├── BehavioralCodes (struct)
│   ├── CodeNumbers: uint16 array (事件码序列)
│   └── CodeTimes: double array (事件时间，ms，相对于 trial 开始)
├── AnalogData (struct)
│   ├── Eye: double [n_samples, 2] (Eye_X, Eye_Y, 单位 degree)
│   ├── SampleInterval: double scalar (采样间隔，ms；250 Hz → 4.0)
│   ├── Joystick: double [n_samples, 2] (可选)
│   ├── PhotoDiode: double [n_samples, 1] (可选)
│   ├── Mouse: double array (可选，postprocess 会清空)
│   └── KeyInput: double array (可选，postprocess 会清空)
├── UserVars (struct)
│   ├── DatasetName: char (Windows 路径字符串)
│   ├── Current_Image_Train: double [1000] (图片索引，取前 N 个)
│   └── (其他实验特定变量)
└── VariableChanges (struct)
    ├── onset_time: double scalar (刺激呈现时长，ms)
    └── fixation_window: double scalar (注视窗口半径，degree)
```

已验证的不变量（来自真实数据 `241026_MaoDan_YJ_WordLOC.bhv2`, 11 trials）：
- Eye shape 严格为 `(n_samples, 2)`
- Current_Image_Train 长度固定 1000
- SampleInterval 固定 4.0 ms
- CodeTimes 从 ~0 ms 开始（相对 trial 起始）

---

## 4. 公开 API

### 4.1 BHV2Reader（底层）

```python
class BHV2Reader:
    """底层 BHV2 二进制解析器。"""

    def __init__(self, bhv_file: Path) -> None:
        """打开文件，读取并缓存 FileIndex。"""

    def list_variables(self) -> list[str]:
        """返回文件中所有变量名列表。"""

    def read(self, var_name: str) -> Any:
        """读取指定变量，返回 Python 原生类型。

        类型映射：
          double/single → np.ndarray (float64/float32)
          char → str
          logical → np.ndarray (bool)
          uint*/int* → np.ndarray (对应 dtype)
          struct → dict[str, Any]  (嵌套)
          cell → list[Any]
        """

    def close(self) -> None:
        """关闭文件句柄。"""

    def __enter__(self) / __exit__(...):
        """上下文管理器支持。"""
```

### 4.2 BHV2Parser（高层，替换现有实现）

签名与现有 `io/bhv.py` 完全一致：

```python
class BHV2Parser:
    def __init__(self, bhv_file: Path) -> None: ...
    def parse(self) -> list[TrialData]: ...
    def get_event_code_times(self, event_code: int, trials: list[int] | None = None) -> list[tuple[int, float]]: ...
    def get_session_metadata(self) -> dict: ...
    def get_analog_data(self, channel_name: str, trials: list[int] | None = None) -> dict[int, np.ndarray]: ...
```

内部改为使用 `BHV2Reader` 而非 MATLAB Engine。

---

## 5. 测试策略

### 5.1 单元测试 — BHV2Reader

| 测试 | 方法 |
|------|------|
| magic 验证 | 构造非法 header → `IOError` |
| FileIndex 解析 | 用 MATLAB 导出已知文件的 index → 对比 Python 解析结果 |
| 基本类型反序列化 | 用 MATLAB 写入已知值的变量 → Python 逐个读取验证 |
| struct 递归解析 | 读取 Trial1 → 验证嵌套 dict 结构 |
| 大端/小端 | 所有 BHV2 文件为 LE，验证 BE 机器上也能正确读取 |

### 5.2 Ground-truth 验证

1. **MATLAB 导出基准**（B1.3 任务）：
   - 对测试文件的每个 Trial，用 MATLAB 导出完整字段为 JSON
   - 存放于 `tests/fixtures/bhv2_ground_truth/trial_{N}.json`

2. **逐字段对比**：
   ```python
   def test_trial_1_behavioral_codes():
       gt = json.load(open("tests/fixtures/bhv2_ground_truth/trial_1.json"))
       with BHV2Reader(TEST_BHV2_FILE) as reader:
           trial = reader.read("Trial1")
       np.testing.assert_array_equal(
           trial["BehavioralCodes"]["CodeNumbers"],
           gt["BehavioralCodes"]["CodeNumbers"]
       )
   ```

3. **数值精度**：
   - CodeTimes: float64, 误差 < 1e-10
   - Eye data: float64, exact match (二进制相同)

### 5.3 回归测试

- 运行现有 `tests/test_io/test_bhv.py`（27 tests）— 需要 mock 调整
- 运行 `tests/test_stages/test_synchronize.py`（20 tests）— BHV2Parser 被 mock，应无影响
- 运行 `tests/test_stages/test_postprocess.py`（26 tests）— BHV2Parser 被 mock，应无影响
- 全量 pytest 通过

---

## 6. 兼容性开关

```python
# io/bhv.py 顶部
import os

_BHV2_BACKEND = os.environ.get("BHV2_BACKEND", "python")

if _BHV2_BACKEND == "matlab":
    from pynpxpipe.io._bhv_matlab import BHV2Parser  # 旧实现移到此文件
else:
    from pynpxpipe.io.bhv2_reader import BHV2Parser  # 新 Pure-Python 实现
```

旧实现不删除，移到 `io/_bhv_matlab.py`，用于对比验证。

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|------|------|------|
| `struct` | 标准库 | 二进制解析 |
| `numpy` | 已有 | 数组存储 |
| `pathlib` | 标准库 | 路径操作 |
| `matlabengine` | optional `[matlab]` | 仅旧后端需要 |

---

## 8. 实施阶段对应关系

| 阶段 | Session 数 | 内容 | 前置条件 |
|------|-----------|------|---------|
| **B1** | 1-2 | 逆向工程：二进制格式文档 + mlbhv2.m 分析 + ground-truth 导出 | MATLAB 可用 |
| **B2** | 2-3 | BHV2Reader (TDD) + BHV2Parser 替换 + ground-truth 验证 + 回归测试 | B1 完成 |
| **B3** | 1 | 依赖清理 + 兼容性开关 + PR merge | B2 完成 |

---

## 9. 风险

| 风险 | 影响 | 缓解 |
|------|------|------|
| BHV2 格式有未文档化的类型（如 `timetable`, `categorical`） | 解析器 crash | 未知类型 → raise + 日志，不默默跳过 |
| 不同 MonkeyLogic 版本的 BHV2 格式有差异 | 解析错误 | 收集多个版本的测试文件；解析器报告文件版本 |
| struct 字段顺序不固定 | 字段名匹配失败 | 按名称匹配而非位置 |
| 浮点精度：Python double vs MATLAB double | 数值微小差异 | 二进制层面 exact match（相同 IEEE 754） |
