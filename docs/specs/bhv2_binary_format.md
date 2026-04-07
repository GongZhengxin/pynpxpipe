# BHV2 二进制格式规格

> 逆向来源：`legacy_reference/pyneuralpipe/Util/mlbhv2.m`（399 行）  
> 验证文件：`F:\#Datasets\demo_rawdata\241026_MaoDan_YJ_WordLOC.bhv2`（11,647,585 字节，11 trials）

---

## 1. 文件总体布局

```
Offset 0
┌────────────────────────────────────────────────────────┐
│  Variable: "IndexPosition"  (double scalar)            │  ← bytes 0–66
│    uint64 value = byte offset of FileIndex             │
├────────────────────────────────────────────────────────┤
│  Variable: "FileInfo"  (struct)                        │  ← bytes 67–...
│    fields: machinefmt (char), encoding (char)          │
├────────────────────────────────────────────────────────┤
│  Variable: "Trial1"  (struct)                          │
│  Variable: "Trial2"  (struct)                          │
│  ...                                                   │
│  Variable: "Trial11" (struct)                          │
│  Variable: "MLConfig"(struct)                          │
│  ...（其他变量，由 who() 枚举）                          │
├────────────────────────────────────────────────────────┤
│  Variable: "FileIndex"  (cell)                         │  ← offset 11,645,144
│    cell[N, 3]: name / start_byte / end_byte            │
└────────────────────────────────────────────────────────┘
EOF (11,647,585 bytes)
```

**已验证字节偏移（真实文件）：**

| 字节范围 | 内容 | 验证 |
|---------|------|------|
| 0–66 | IndexPosition 变量（完整） | ✅ hexdump 确认 |
| 67–... | FileInfo 变量开始 | ✅ name='FileInfo', type='struct', nfield=2 |
| 11,645,144 | FileIndex 变量开始 | ✅ IndexPosition 双精度值 |

---

## 2. Magic / IndexPosition 编码（逐字节）

```
Bytes  0– 7:  uint64 LE = 13          ← name_length
Bytes  8–20:  b'IndexPosition'        ← variable name (13 bytes, ASCII)
Bytes 21–28:  uint64 LE = 6           ← type_length
Bytes 29–34:  b'double'               ← type string
Bytes 35–42:  uint64 LE = 2           ← ndim = 2
Bytes 43–50:  uint64 LE = 1           ← sz[0] = 1
Bytes 51–58:  uint64 LE = 1           ← sz[1] = 1
Bytes 59–66:  float64 LE              ← payload: FileIndex offset (= 11645144.0)
```

**Hex dump（已验证）：**
```
0000: 0d 00 00 00 00 00 00 00  49 6e 64 65 78 50 6f 73  |........IndexPos|
0010: 69 74 69 6f 6e 06 00 00  00 00 00 00 00 64 6f 75  |ition........dou|
0020: 62 6c 65 02 00 00 00 00  00 00 00 01 00 00 00 00  |ble.............|
0030: 00 00 00 01 00 00 00 00  00 00 00 <8 bytes:double>|
```

---

## 3. 变量通用编码格式

每个变量（包括 IndexPosition 本身）的序列化格式：

```
┌──────────────────────────────────────────┐
│ uint64 LE: name_length                   │  8 bytes
│ char[name_length]: variable_name         │  name_length bytes
│ uint64 LE: type_length                   │  8 bytes
│ char[type_length]: type_string           │  type_length bytes
│ uint64 LE: ndim                          │  8 bytes
│ uint64 LE × ndim: size_array             │  ndim × 8 bytes
│ <type-specific payload>                  │  见第 4 节
└──────────────────────────────────────────┘
```

**FileInfo 变量（bytes 67–...）已验证：**
- name_len=8, name='FileInfo', type='struct', ndim=2, sz=[1,1], nfield=2
- 两个字段：`machinefmt`（char，通常 'ieee-le'）、`encoding`（char，通常 'UTF-8' 或 'windows-1252'）

---

## 4. Payload 规格（按 type_string）

### 4.1 数值类型（double / single / uint8/16/32/64 / int8/16/32/64 / logical）

```
fread(fid, prod(size), '*<type>')  → reshape(sz, 'Fortran order')
```

| type_string | 字节宽 | numpy dtype |
|------------|--------|------------|
| `double`   | 8      | float64     |
| `single`   | 4      | float32     |
| `uint8`    | 1      | uint8       |
| `uint16`   | 2      | uint16      |
| `uint32`   | 4      | uint32      |
| `uint64`   | 8      | uint64      |
| `int8`     | 1      | int8        |
| `int16`    | 2      | int16       |
| `int32`    | 4      | int32       |
| `int64`    | 8      | int64       |
| `logical`  | 1      | bool        |

**注意 Fortran order**：MATLAB 以列优先存储。Python 还原：
```python
np.frombuffer(data, dtype=dtype).reshape(sz, order='F')
```

### 4.2 char

```
fread(fid, prod(size), 'char*1=>char')
→ 直接解码为字符串（UTF-8 或 FileInfo.encoding）
```

### 4.3 struct

```
uint64 LE: nfield          ← 字段数量
对每个元素（prod(size) 个）× 每个字段（nfield 个）：
    递归读取一个变量（名称=字段名，内容=字段值）
```

**注意**：`struct` 数组时外层循环元素、内层循环字段（MATLAB 列优先展开）。

### 4.4 cell

```
对每个元素（prod(size) 个）：
    递归读取一个变量（名称为空字符串 ''）
```

**注意**：cell 没有 nfield。

### 4.5 containers.Map

```
递归读取变量 "keys"   → keySet  (cell of char)
递归读取变量 "values" → valueSet (cell of any)
→ dict(zip(keySet, valueSet))
```

### 4.6 ml* 前缀类型（旧版兼容）

```
if type.startswith('ml'):
    treat as 'struct'  ← mlbhv2.m line 304
```

### 4.7 其他特殊类型

| type_string | 处理方式 |
|------------|---------|
| `string` | 读为 cell，再转字符串 |
| `function_handle` | 读 char 变量，str2func |
| `datetime` | 读 struct 字段重构 |
| `table/timetable/timeseries` | 复杂，见 mlbhv2.m 对应分支 |

---

## 5. FileIndex 结构

FileIndex 是 `cell` 类型，shape `[N, 3]`（N 个变量）：

| 列 | 内容 | 类型 |
|----|------|------|
| `[i, 0]` | 变量名 | char |
| `[i, 1]` | 变量起始字节偏移 | double → int |
| `[i, 2]` | 变量结束字节偏移 | double → int |

**陷阱**：偏移以 `double` 存储，Python 读取后需 `int()` 转换才能用于 `seek()`。

---

## 6. Trial 结构体布局（真实文件验证）

```
Trial{N} (struct, 1×1)
├── Trial              : double scalar → trial_id (1-indexed)
├── Condition          : double scalar → condition_id
├── BehavioralCodes    : struct
│   ├── CodeNumbers    : uint16 [1, M]  → 事件码序列
│   └── CodeTimes      : double [1, M]  → 事件时间 ms（相对 trial 开始）
├── AnalogData         : struct
│   ├── Eye            : double [N, 2]  → [Eye_X, Eye_Y]，单位 degree
│   ├── SampleInterval : double scalar  → 4.0 ms（250 Hz）
│   ├── Mouse          : double array   → 鼠标输入（可清空）
│   ├── KeyInput       : double array   → 键盘输入（可清空）
│   └── PhotoDiode     : double array   → 光电管（可选）
├── UserVars           : struct
│   ├── DatasetName    : char           → Windows 路径字符串
│   └── Current_Image_Train : double [1, 1000] → 图片索引序列
└── VariableChanges    : struct
    ├── onset_time     : double scalar  → 刺激呈现时长 ms
    └── fixation_window: double scalar  → 注视窗口半径 degree
```

**已验证不变量（11 trials，真实文件）：**
- Eye shape 严格为 `(n_samples, 2)`，n_samples 范围 490–25560
- SampleInterval 固定 4.0 ms
- Current_Image_Train 长度固定 1000
- CodeTimes 从接近 0 开始（range 0.52–2.89 ms），单位 ms

---

## 7. 字节序与编码

- **字节序**：Little-Endian（`ieee-le`）
- **字符编码**：`FileInfo.encoding`（默认 `UTF-8`；旧版文件可能为 `windows-1252`）
- **浮点**：IEEE 754，与 Python `float` 完全相同，exact match 可行
