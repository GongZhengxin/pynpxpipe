# mlbhv2.m 逐函数分析

> 源文件：`legacy_reference/pyneuralpipe/Util/mlbhv2.m`（399 行）  
> 角色：BHV2 二进制格式的 MATLAB 参考实现，Python BHV2Reader 的对照基准

---

## 1. 文件概览

```matlab
classdef mlbhv2 < handle
```

- `handle` 子类：按引用传递，`close()` 只需调用一次
- 受保护属性：`filename`, `fid`, `var_pos`, `readonly`, `indexed`, `update_index`, `fileinfo`
- `var_pos`：变量位置缓存，cell array `{name, start_byte, end_byte}`（在首次访问时懒加载）

---

## 2. `open(filename, mode)` — 打开文件

三种模式：

| 模式 | 行为 |
|------|------|
| `'r'` | 只读，调用 `read_index()` 加载 FileIndex 和 FileInfo |
| `'w'` | 新建写，先写 `IndexPosition=-1`，再写 `FileInfo` |
| `'a'` | 追加，若文件存在则读 FileIndex 定位追加点；否则同 `'w'` |

**关键**：读模式下 `read_index()` 在 `open()` 时立即执行，`var_pos` 会被预填（若 FileIndex 存在）。

---

## 3. `read_index()` — 识别 magic，定位 FileIndex

```
1. seek(0)
2. 读 name_len（uint64）
3. 读 name（char[name_len]）
4. 若 name == 'IndexPosition'：
     a. indexed = true
     b. 重新 seek(0)，read_variable() 读 IndexPosition 值 → pos（FileIndex 字节偏移）
     c. 继续读下一个变量：若 name == 'FileInfo' → 读 FileInfo（编码信息）
     d. 若 pos > 0：seek(pos)，read_variable() 读 FileIndex cell array → var_pos
5. 若无 FileInfo → 使用默认编码（windows-1252 或系统默认）
```

**陷阱 A（Python 实现必读）**：FileInfo 可能不存在于旧版 BHV2 文件。Python 需 fallback：
```python
encoding = file_info.get('encoding', 'windows-1252')
```

---

## 4. 三种读取入口对比

| 方法 | 行为 | 适用场景 |
|------|------|---------|
| `read(name)` | 按名称读取单个变量；若 var_pos 有缓存直接 seek；否则顺序扫描并缓存所有路过的变量 | 读指定变量 |
| `read()` (无参数) | 清空 var_pos 缓存，从头顺序读取所有变量，返回 struct | 读取全部变量 |
| `read_trial()` | 先用 var_pos 中 `^Trial\d+$` 的偏移读已知 trial；再顺序扫描剩余 | 批量读取 trial 数组 |
| `who()` | 扫描文件填充 var_pos，返回所有变量名列表 | 枚举变量 |

**实现注意**：`read(name)` 当 var_pos 为空时从 offset=0 开始扫描；有缓存时从 `var_pos{end,3}`（最后已知变量的结束位置）继续扫描。Python 实现应先读 FileIndex（即在 open 时调用 read_index），然后 `read(name)` 可直接按 FileIndex 中的 start_byte 定位。

---

## 5. `read_variable()` — 核心解析函数（逐 case 注释）

### 5.1 读取 header（所有变量共用）

```matlab
lname = fread(fid, 1, 'uint64=>double')   % 变量名长度
name  = fread(fid, [1 lname], 'char*1=>char')  % 变量名
ltype = fread(fid, 1, 'uint64=>double')   % 类型字符串长度
type  = fread(fid, [1 ltype], 'char*1=>char')   % 类型字符串
dim   = fread(fid, 1, 'uint64=>double')   % 维度数
sz    = fread(fid, [1 dim], 'uint64=>double')   % 各维度大小
```

**陷阱 B**：`uint64=>double` 转换——MATLAB `fread` 将 uint64 读为 double。对于文件偏移，当偏移 > 2^53 时会丢精度（约 9 PB），实际无影响。**Python 读 uint64 时直接用 `struct.unpack('<Q', ...)` 即可，不需要转 double。**

### 5.2 ml* 前缀兼容（行 304）

```matlab
if strncmp(type, 'ml', 2)
    type = 'struct';
end
```

Python 对应：
```python
if type_str.startswith('ml'):
    type_str = 'struct'
```

### 5.3 struct（行 308–309）

```matlab
val = repmat(struct, sz);
nfield = fread(fid, 1, 'uint64=>double');
for m = 1:prod(sz)
    for n = 1:nfield
        [a, b] = read_variable(obj);
        val(m).(b) = a;
    end
end
```

**注意**：先读 nfield（uint64），然后 `prod(sz) × nfield` 次递归。  
**陷阱 C**：`sz=[1,1]` 时 `prod(sz)=1`，不代表"标量"——shape 仍是 `[1,1]`。

Python：
```python
nfield = read_uint64()
result = {}  # or list of dicts for sz != [1,1]
for _ in range(prod(sz)):
    for _ in range(nfield):
        val, name = read_variable()
        result[name] = val
```

### 5.4 cell（行 311）

```matlab
val = cell(sz);
for m = 1:prod(sz)
    val{m} = read_variable(obj);
end
```

**注意**：cell 没有 nfield，直接读 `prod(sz)` 个元素。  
**注意**：每次 `read_variable()` 返回 `(val, name)`，cell 元素的 name 是空字符串。

### 5.5 数值类型（行 373）

```matlab
val = reshape(fread(fid, prod(sz), ['*' type]), sz);
```

- `fread` 读取 `prod(sz)` 个元素，结果为列向量（Fortran order）
- `reshape(v, sz)` 等价于 `reshape(v, sz, 'F')` — MATLAB 默认 Fortran order
- Python 等价：
  ```python
  raw = f.read(prod(sz) * dtype_size)
  arr = np.frombuffer(raw, dtype=dtype).reshape(sz, order='F')
  ```

### 5.6 containers.Map（行 345–348）

```matlab
keySet   = read_variable(obj);   % 读 "keys" 变量
valueSet = read_variable(obj);   % 读 "values" 变量
val = containers.Map(keySet, valueSet);
```

两次递归 `read_variable()`，分别读取 keys（cell of char）和 values（cell of any）。Python 等价：
```python
keys_val, _ = read_variable()
vals_val, _ = read_variable()
result = dict(zip(keys_val, vals_val))
```

### 5.7 EOF 处理

```matlab
catch err
    if ~strcmp(err.identifier, 'mlbhv2:eof')
        fprintf(2, '%s\n\n', err.message);
    end
    break;
```

EOF 通过 `feof(obj.fid)` 在 `read_variable` 开头检测，抛出 `mlbhv2:eof` identifier。顺序扫描时以此为结束信号。

Python 等价：在 read_variable 入口检查 `f.read(8)` 是否为空字节。

---

## 6. 陷阱清单（Python 实现必读）

| # | 陷阱 | 正确处理 |
|---|------|---------|
| A | FileInfo 在旧版 BHV2 可能不存在 | fallback 到 `encoding='windows-1252'` |
| B | `uint64=>double` 精度损失 | Python 直接 `struct.unpack('<Q', ...)` |
| C | `sz=[1,1]` 不等于 scalar | 保留 shape，不要 squeeze |
| D | FileIndex 偏移存为 double | `int(float_val)` 再 seek |
| E | cell 无 nfield，struct 有 nfield | 严格区分两个分支 |
| F | Fortran order reshape | `np.frombuffer().reshape(sz, order='F')` |
| G | struct 数组：外层循环元素，内层循环字段 | 顺序不能颠倒 |
| H | char 编码：FileInfo.encoding 优先 | 非 UTF-8 文件会出现解码错误 |

---

## 7. `write_recursively()` — 写入（参考用）

仅用于理解二进制格式，Python Reader 不需要实现写入。关键点：
- `function_handle`：`func2str()` 转 char 写入
- `table/timetable`：复杂的 Properties struct + CustomProperties 布尔标志
- `ml*` 对象：尝试转 struct；若无效转 char

---

## 8. 与 Python BHV2Reader 的对应关系

| mlbhv2 方法 | Python BHV2Reader 对应 |
|------------|----------------------|
| `mlbhv2(file, 'r')` | `BHV2Reader.__init__(path)` |
| `read_index()` | `_read_file_index()` |
| `read(name)` | `read(var_name)` |
| `read_trial()` | 内部批量读 Trial1...N |
| `who()` | `list_variables()` |
| `close()` | `close()` / `__exit__` |
| `read_variable()` | `_read_variable()` |
