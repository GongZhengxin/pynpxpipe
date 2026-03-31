# Spec: core/session.py

## 1. 目标

`core/session.py` 提供 pipeline 执行的核心上下文容器和生命周期管理：

- **Session dataclass** — 持有 pipeline 所有 stage 共享的状态（路径、subject 信息、probes 列表、checkpoint 摘要、日志路径）
- **SubjectConfig dataclass** — DANDI 兼容的动物元信息（由 `config.load_subject_config()` 构造并注入）
- **ProbeInfo dataclass** — 单个 IMEC 探针的元信息（由 `discover` stage 填充后写回 session）
- **SessionManager** — 工厂与持久化：创建新 Session（含目录初始化）、从磁盘恢复 Session、持久化状态到 `{output_dir}/session.json`

无 UI 依赖：不 import click、不 print、不 sys.exit。`Session` 对象在所有 stage 之间传递，是 pipeline 的唯一共享状态载体。

---

## 2. 输入

### 2.1 典型目录布局（SpikeGLX 约定）

```
xxx/                       ← data_dir（用户传入这个根目录）
  xxx_g0/                  ← SpikeGLX gate 录制文件夹（session_dir，自动发现）
    xxx_g0_imec0/          ← probe 0 数据子目录
    xxx_g0_imec1/          ← probe 1 数据子目录（多探针时）
    xxx_g0_t0.nidq.bin     ← NIDQ 数据
    xxx_g0_t0.nidq.meta
  xxx.bhv2                 ← BHV2 行为文件（与 xxx_g0/ 同级，自动发现）
```

### 2.2 SessionManager.from_data_dir()（主入口）

| 参数 | 类型 | 说明 |
|------|------|------|
| `data_dir` | `Path` | 包含 `*_g0/` 子目录和 `*.bhv2` 的根目录（必须已存在） |
| `subject` | `SubjectConfig` | 由 `config.load_subject_config()` 预先加载 |
| `output_dir` | `Path` | 处理输出目录（不存在则自动创建） |

### 2.3 SessionManager.create()（底层接口，显式路径控制）

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_dir` | `Path` | SpikeGLX gate 录制文件夹（必须已存在） |
| `bhv_file` | `Path` | MonkeyLogic BHV2 文件路径（必须已存在） |
| `subject` | `SubjectConfig` | 由 `config.load_subject_config()` 预先加载 |
| `output_dir` | `Path` | 处理输出目录（不存在则自动创建） |

适用于多 gate（`*_g0`, `*_g1`）或 BHV2 文件在非标准位置的场景。

### 2.4 SessionManager.load()

| 参数 | 类型 | 说明 |
|------|------|------|
| `output_dir` | `Path` | 之前 pipeline 运行的输出目录（必须含 `session.json`） |

---

## 3. 输出

### 3.1 SessionManager.from_data_dir() / create()

返回完整初始化的 `Session` 对象，并在 `output_dir` 下创建目录结构：

```
{output_dir}/
  session.json         # Session 状态序列化（含 subject、路径；probes 初始为空）
  checkpoints/         # CheckpointManager 工作目录（初始为空）
  logs/                # 结构化日志存放目录
```

`Session.probes` 初始为空列表，由后续 `discover` stage 填充后调用 `SessionManager.save()` 更新。

### 3.2 SessionManager.load()

返回从 `session.json` 反序列化的 `Session`，subject、probes、checkpoint、log_path 全部恢复。

### 3.3 SessionManager.save()

将 Session 状态写入 `{output_dir}/session.json`（幂等，覆盖写入）。无返回值。

---

## 4. 处理步骤

### 4.1 from_data_dir() 自动发现规则

1. 对 `data_dir` 做 glob，收集所有匹配 `*_g[0-9]*/` 的子目录（按名称升序排序）
2. 若无匹配 → raise `FileNotFoundError(f"No *_g[0-9] directory found in {data_dir}")`
3. 若多个匹配 → 取第一个（字母序最小），并通过标准 logging 发出 WARNING
4. 对 `data_dir` 做 glob，收集所有匹配 `*.bhv2` 的文件
5. 若无匹配 → raise `FileNotFoundError(f"No *.bhv2 file found in {data_dir}")`
6. 若多个匹配 → 取第一个，并通过标准 logging 发出 WARNING
7. 调用 `create(session_dir, bhv_file, subject, output_dir)`

### 4.2 create() 流程

1. 验证 `session_dir` 是已存在的目录（`FileNotFoundError` if not）
2. 验证 `bhv_file` 是已存在的文件（`FileNotFoundError` if not）
3. `output_dir.mkdir(parents=True, exist_ok=True)`
4. `(output_dir / "checkpoints").mkdir(exist_ok=True)`
5. `(output_dir / "logs").mkdir(exist_ok=True)`
6. 构造 `Session(session_dir, output_dir, subject, bhv_file)`  
   → `__post_init__` 自动设置 `log_path`
7. 调用 `save(session)` 写入 `session.json`
8. 返回 `session`

### 4.3 Session.__post_init__

```python
self.log_path = self.output_dir / "logs" / f"pynpxpipe_{self.session_dir.name}.log"
```

`log_path` 是 `field(init=False)`，调用方无需（也不能）传入。

### 4.4 save() 序列化规则

写入 UTF-8 编码的 JSON，indent=2，格式如下：

```json
{
  "session_dir": "/path/to/xxx_g0",
  "output_dir": "/path/to/output",
  "bhv_file": "/path/to/xxx.bhv2",
  "subject": {
    "subject_id": "MaoDan",
    "description": "good monkey",
    "species": "Macaca mulatta",
    "sex": "M",
    "age": "P4Y",
    "weight": "12.8kg"
  },
  "probes": [
    {
      "probe_id": "imec0",
      "ap_bin": "/path/to/xxx_g0_imec0/xxx.ap.bin",
      "ap_meta": "/path/to/xxx_g0_imec0/xxx.ap.meta",
      "lf_bin": null,
      "lf_meta": null,
      "sample_rate": 30000.0,
      "n_channels": 384,
      "probe_type": "NP1010",
      "serial_number": "123456",
      "channel_positions": [[0.0, 0.0], [16.0, 0.0]]
    }
  ],
  "checkpoint": {}
}
```

序列化规则：
- `Path` → `str(path)` 或 `None`（若为 None）
- `ProbeInfo.channel_positions` → `list[list[float]]` 或 `null`
- `log_path` 不序列化（`__post_init__` 在 load 时重新计算）

### 4.5 load() 反序列化规则

1. `session_json = output_dir / "session.json"`
2. 若文件不存在 → `FileNotFoundError`
3. JSON 解析失败 → `ValueError(f"Corrupt session.json: {e}")`
4. 必填顶层键缺失（session_dir, output_dir, bhv_file, subject, probes, checkpoint）→ `ValueError`
5. `str → Path` 重建所有路径字段
6. `dict → SubjectConfig(**d)`
7. `list[dict] → list[ProbeInfo]`，每个 dict 的路径字段重建为 `Path`，`channel_positions` 重建为 `list[tuple[float, float]]` 或 `None`
8. 构造 `Session(...)` → `__post_init__` 自动重建 `log_path`
9. 返回 Session

---

## 5. 公开 API 与可配参数

### 5.1 SubjectConfig

```python
@dataclass
class SubjectConfig:
    """动物 subject 元信息，遵循 DANDI 归档标准。
    
    所有字段 required，无默认值，由 config.load_subject_config() 从 monkeys/*.yaml 加载。
    export 到 NWB 时直接映射到 NWBFile.subject。
    """
    subject_id: str   # required by DANDI
    description: str  # 自由描述
    species: str      # required by DANDI, e.g. "Macaca mulatta"
    sex: str          # "M" | "F" | "U" | "O"
    age: str          # ISO 8601 duration, e.g. "P4Y"
    weight: str       # 含单位, e.g. "12.8kg"
```

**设计决策**：`SubjectConfig` 定义在 `core/session.py`（domain model 的归属地）。
`core/config.py` 的 `load_subject_config()` 从 `core.session` 导入此类，
并删除 `config.py` 中原有的重复定义（有 empty-string defaults 的版本）。

### 5.2 ProbeInfo

```python
@dataclass
class ProbeInfo:
    """单个 IMEC 探针的元信息，由 discover stage 填充。"""
    probe_id: str                                      # e.g. "imec0", "imec1"
    ap_bin: Path                                       # AP .bin 文件路径
    ap_meta: Path                                      # AP .meta 文件路径
    lf_bin: Path | None                                # LF .bin，无则 None
    lf_meta: Path | None                               # LF .meta，无则 None
    sample_rate: float                                 # AP 采样率 Hz（从 meta 读取）
    n_channels: int                                    # 保存的通道数（从 meta 读取）
    probe_type: str                                    # 探针型号，e.g. "NP1010"
    serial_number: str                                 # 探针序列号
    channel_positions: list[tuple[float, float]] | None = None  # (x, y) µm，discover 后填充
```

### 5.3 Session

```python
@dataclass
class Session:
    """Pipeline 执行的核心上下文，在所有 stage 之间传递。"""
    session_dir: Path          # SpikeGLX gate 录制文件夹
    output_dir: Path           # 所有处理输出的根目录
    subject: SubjectConfig     # 动物元信息
    bhv_file: Path             # MonkeyLogic BHV2 文件路径
    probes: list[ProbeInfo] = field(default_factory=list)   # discover 后填充
    checkpoint: dict = field(default_factory=dict)          # stage 完成状态摘要
    log_path: Path = field(init=False)                      # 由 __post_init__ 设置
    
    def __post_init__(self) -> None:
        self.log_path = self.output_dir / "logs" / f"pynpxpipe_{self.session_dir.name}.log"
```

`checkpoint` 字段是轻量摘要（如 `{"discover": true, "sort_imec0": true}`），
实际的 checkpoint 文件由 `CheckpointManager` 独立管理；各 stage 在更新
checkpoint 后调用 `SessionManager.save()` 同步摘要。

### 5.4 SessionManager

```python
class SessionManager:
    """Session 对象的工厂与持久化管理器。"""
    
    @staticmethod
    def from_data_dir(
        data_dir: Path,
        subject: SubjectConfig,
        output_dir: Path,
    ) -> Session:
        """从 data_dir 自动发现 session_dir 和 bhv_file，调用 create()。
        
        自动发现规则：session_dir = 第一个 *_g[0-9]/ 子目录，
        bhv_file = 第一个 *.bhv2 文件。多个匹配时取字母序第一个并记录 WARNING。
        
        Raises:
            FileNotFoundError: 若 data_dir 不存在，或找不到 *_g[0-9]/ 或 *.bhv2。
        """
    
    @staticmethod
    def create(
        session_dir: Path,
        bhv_file: Path,
        subject: SubjectConfig,
        output_dir: Path,
    ) -> Session:
        """创建新 Session，初始化 output_dir 目录结构，写入 session.json。
        
        Raises:
            FileNotFoundError: 若 session_dir 或 bhv_file 不存在。
            OSError: 若 output_dir 无法创建。
        """
    
    @staticmethod
    def load(output_dir: Path) -> Session:
        """从 output_dir/session.json 恢复 Session。
        
        Raises:
            FileNotFoundError: 若 session.json 不存在。
            ValueError: 若 JSON 损坏或缺少必填字段。
        """
    
    @staticmethod
    def save(session: Session) -> None:
        """将 Session 序列化写入 {session.output_dir}/session.json。
        
        Raises:
            OSError: 若文件无法写入。
        """
```

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_core/test_session.py`

| 组 | 测试点 |
|----|-------|
| A. Dataclasses | SubjectConfig 所有字段 required；ProbeInfo channel_positions 默认 None；Session log_path 由 __post_init__ 正确设置 |
| B. from_data_dir() | 正常发现；data_dir 不存在；无 *_g[0-9]/ 目录；无 *.bhv2 文件；多 gate 取第一个并发出 WARNING |
| C. create() | 正常流程 + 目录创建 + session.json 写入；session_dir 不存在；bhv_file 不存在；output_dir 不存在时自动创建 |
| D. save() | Path 序列化为 str；None lf_bin → null；channel_positions 序列化；log_path 不写入 JSON |
| E. load() | 所有字段正确反序列化；session.json 不存在；JSON 语法错误；缺少必填键 |
| F. Roundtrip | create → save → load 得到等价 Session（含 ProbeInfo 列表和 checkpoint dict） |

---

## 7. 依赖

- `core/errors.py` — 无（session.py 仅 raise 标准库异常，FileNotFoundError / ValueError / OSError）
- `core/config.py` — `config.load_subject_config()` 导入 `SubjectConfig` from `core.session`（反向依赖，session.py 本身不导入 config）
- `core/checkpoint.py` — 不直接依赖；CheckpointManager 由 stage 层独立持有
- 标准库：`dataclasses`, `pathlib`, `json`, `logging`
