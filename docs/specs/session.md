# Spec: core/session.py

## 1. 目标

`core/session.py` 提供 pipeline 执行的核心上下文容器和生命周期管理：

- **Session dataclass** — 持有 pipeline 所有 stage 共享的状态（路径、subject 信息、SessionID、probe_plan、probes 列表、checkpoint 摘要、日志路径）
- **SessionID dataclass** — 规范化会话标识（`{date}_{subject}_{experiment}_{region}`），作为输出文件名与 NWB 元数据的权威来源
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
| `experiment` | `str` | 实验名（如 `"nsd1w"`）— 用户在 UI 表单现填，不校验正则 |
| `probe_plan` | `dict[str, str]` | 用户声明的 `{probe_id: target_area}` 映射（如 `{"imec0": "MSB", "imec1": "V4"}`）；不得为空 |
| `date` | `str` | 记录日期，YYMMDD 格式。由调用方通过 `io.spikeglx.read_recording_date()` 从 `.ap.meta` 的 `fileCreateTime` 预先抽出并传入 |

### 2.3 SessionManager.create()（底层接口，显式路径控制）

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_dir` | `Path` | SpikeGLX gate 录制文件夹（必须已存在） |
| `bhv_file` | `Path` | MonkeyLogic BHV2 文件路径（必须已存在） |
| `subject` | `SubjectConfig` | 由 `config.load_subject_config()` 预先加载 |
| `output_dir` | `Path` | 处理输出目录（不存在则自动创建） |
| `experiment` | `str` | 同上 |
| `probe_plan` | `dict[str, str]` | 同上 |
| `date` | `str` | 同上 |

适用于多 gate（`*_g0`, `*_g1`）或 BHV2 文件在非标准位置的场景。

**注**：`date` 参数而非 `create()` 内部计算，是为避免 `core.session` 依赖 `io.spikeglx`。UI / CLI 层在调用 `create()` 前自行调用 `io.spikeglx.read_recording_date()` 抽取日期。

### 2.4 SessionManager.load()

| 参数 | 类型 | 说明 |
|------|------|------|
| `output_dir` | `Path` | 之前 pipeline 运行的输出目录（必须含 `session.json`） |

---

## 3. 输出

### 3.1 SessionManager.from_data_dir() / create()

返回完整初始化的 `Session` 对象（含已计算好的 `session_id`、`probe_plan`），并在 `output_dir` 下创建目录结构：

```
{output_dir}/
  session.json         # Session 状态序列化（含 subject、路径、session_id、probe_plan；probes 初始为空）
  checkpoints/         # CheckpointManager 工作目录（初始为空）
  logs/                # 结构化日志存放目录
```

`Session.probes` 初始为空列表，由后续 `discover` stage 填充后调用 `SessionManager.save()` 更新。
`Session.session_id` 在 create() 阶段已完整构造（4 字段全部就绪）。

### 3.2 SessionManager.load()

返回从 `session.json` 反序列化的 `Session`，subject、session_id、probe_plan、probes、checkpoint、log_path 全部恢复。

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
7. 调用 `create(session_dir, bhv_file, subject, output_dir, experiment=..., probe_plan=..., date=...)`，原样透传后三个参数

### 4.2 create() 流程

1. 验证 `session_dir` 是已存在的目录（`FileNotFoundError` if not）
2. 验证 `bhv_file` 是已存在的文件（`FileNotFoundError` if not）
3. 验证 `probe_plan` 非空 → 否则 `ValueError("probe_plan must declare at least one probe")`
4. 验证 `probe_plan` 所有 key 匹配正则 `^imec\d+$` → 否则 `ValueError`
5. 验证 `experiment` 非空 → 否则 `ValueError`
6. 验证 `date` 为 6 位数字 → 否则 `ValueError`
7. 构造 `SessionID`：
   ```python
   region = SessionID.derive_region(probe_plan)   # 见 5.5 静态方法
   session_id = SessionID(
       date=date,
       subject=subject.subject_id,
       experiment=experiment,
       region=region,
   )
   ```
8. `output_dir.mkdir(parents=True, exist_ok=True)`
9. `(output_dir / "checkpoints").mkdir(exist_ok=True)`
10. `(output_dir / "logs").mkdir(exist_ok=True)`
11. 构造 `Session(session_dir, output_dir, subject, bhv_file, session_id, probe_plan, config=...)`  
    → `__post_init__` 自动设置 `log_path`
12. 调用 `save(session)` 写入 `session.json`
13. 返回 `session`

### 4.3 Session.__post_init__

```python
self.log_path = self.output_dir / "logs" / f"pynpxpipe_{self.session_dir.name}.log"
```

`log_path` 是 `field(init=False)`，调用方无需（也不能）传入。

**注**：`log_path` 仍然基于 `session_dir.name`（磁盘目录名），**不** 基于 `session_id.canonical()`。
日志是运行时诊断产物，保持与物理目录一致便于排查；NWB 导出名才走 session_id 规范。

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
  "session_id": {
    "date": "251024",
    "subject": "MaoDan",
    "experiment": "nsd1w",
    "region": "MSB-V4"
  },
  "probe_plan": {
    "imec0": "MSB",
    "imec1": "V4"
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
      "channel_positions": [[0.0, 0.0], [16.0, 0.0]],
      "target_area": "MSB"
    }
  ],
  "checkpoint": {}
}
```

序列化规则：
- `Path` → `str(path)` 或 `None`（若为 None）
- `ProbeInfo.channel_positions` → `list[list[float]]` 或 `null`
- `ProbeInfo.target_area` → 字符串，**必填**（无默认值）
- `SessionID` → 4 个字段的 dict
- `probe_plan` → 普通 `dict[str, str]`
- `log_path` 不序列化（`__post_init__` 在 load 时重新计算）

### 4.5 load() 反序列化规则

1. `session_json = output_dir / "session.json"`
2. 若文件不存在 → `FileNotFoundError`
3. JSON 解析失败 → `ValueError(f"Corrupt session.json: {e}")`
4. 必填顶层键缺失（`session_dir`, `output_dir`, `bhv_file`, `subject`, `session_id`, `probe_plan`, `probes`, `checkpoint`）→ `ValueError`
5. `str → Path` 重建所有路径字段
6. `dict → SubjectConfig(**d)`
7. `dict → SessionID(**d)`（严格 4 字段）
8. `dict → probe_plan`（保持 `dict[str, str]` 类型）
9. `list[dict] → list[ProbeInfo]`，每个 dict 的路径字段重建为 `Path`，`channel_positions` 重建为 `list[tuple[float, float]]` 或 `None`，`target_area` 必填
10. 构造 `Session(...)` → `__post_init__` 自动重建 `log_path`
11. 返回 Session

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
    target_area: str                                   # 脑区代号（必填，无默认）
    channel_positions: list[tuple[float, float]] | None = None  # (x, y) µm，discover 后填充
```

**重要变化**：`target_area` 不再有默认值 `"unknown"`。`discover` stage 从 `session.probe_plan`
查表填充；若某 probe 磁盘存在但 probe_plan 未声明（或反之），raise `ProbeDeclarationMismatchError`。

### 5.3 Session

```python
@dataclass
class Session:
    """Pipeline 执行的核心上下文，在所有 stage 之间传递。"""
    session_dir: Path                 # SpikeGLX gate 录制文件夹
    output_dir: Path                  # 所有处理输出的根目录
    subject: SubjectConfig            # 动物元信息
    bhv_file: Path                    # MonkeyLogic BHV2 文件路径
    session_id: SessionID             # 规范化会话标识（create 时构造完整）
    probe_plan: dict[str, str]        # 用户声明的 probe_id → target_area 映射
    config: object                    # PipelineConfig 实例（含 sorting/sync/preprocess 等），由 SessionManager 注入
    probes: list[ProbeInfo] = field(default_factory=list)   # discover 后填充
    checkpoint: dict = field(default_factory=dict)          # stage 完成状态摘要
    log_path: Path = field(init=False)                      # 由 __post_init__ 设置
    
    def __post_init__(self) -> None:
        self.log_path = self.output_dir / "logs" / f"pynpxpipe_{self.session_dir.name}.log"
```

`checkpoint` 字段是轻量摘要（如 `{"discover": true, "sort_imec0": true}`），
实际的 checkpoint 文件由 `CheckpointManager` 独立管理。

**probe_plan 与 probes 的关系**：
- `probe_plan` = **运行前意图**（UI 填入，create 时固定）
- `probes` = **发现后事实**（discover stage 填充）
- 两者通过 probe_id 关联。discover 做 set 比较，mismatch 时 raise `ProbeDeclarationMismatchError`

### 5.4 SessionManager

```python
class SessionManager:
    """Session 对象的工厂与持久化管理器。"""
    
    @staticmethod
    def from_data_dir(
        data_dir: Path,
        subject: SubjectConfig,
        output_dir: Path,
        *,
        experiment: str,
        probe_plan: dict[str, str],
        date: str,
    ) -> Session:
        """从 data_dir 自动发现 session_dir 和 bhv_file，调用 create()。
        
        自动发现规则：session_dir = 第一个 *_g[0-9]/ 子目录，
        bhv_file = 第一个 *.bhv2 文件。多个匹配时取字母序第一个并记录 WARNING。
        
        Raises:
            FileNotFoundError: 若 data_dir 不存在，或找不到 *_g[0-9]/ 或 *.bhv2。
            ValueError: 若 experiment 为空、probe_plan 为空、date 格式错误。
        """
    
    @staticmethod
    def create(
        session_dir: Path,
        bhv_file: Path,
        subject: SubjectConfig,
        output_dir: Path,
        *,
        experiment: str,
        probe_plan: dict[str, str],
        date: str,
    ) -> Session:
        """创建新 Session，初始化 output_dir 目录结构，写入 session.json。
        
        Raises:
            FileNotFoundError: 若 session_dir 或 bhv_file 不存在。
            OSError: 若 output_dir 无法创建。
            ValueError: 若 experiment 为空、probe_plan 为空、probe_plan key 不匹配 ^imec\\d+$、date 非 6 位数字。
        """
    
    @staticmethod
    def load(output_dir: Path) -> Session:
        """从 output_dir/session.json 恢复 Session。
        
        Raises:
            FileNotFoundError: 若 session.json 不存在。
            ValueError: 若 JSON 损坏或缺少必填字段（含 session_id, probe_plan）。
        """
    
    @staticmethod
    def save(session: Session) -> None:
        """将 Session 序列化写入 {session.output_dir}/session.json。
        
        Raises:
            OSError: 若文件无法写入。
        """
```

### 5.5 SessionID

```python
@dataclass(frozen=True)
class SessionID:
    """规范化会话标识：{date}_{subject}_{experiment}_{region}
    
    权威来源：NWB 文件名、NWBFile.session_id 元数据。
    
    字段约束：4 个字段均为非空字符串；不做正则校验（用户自维护）。
    """
    date: str        # YYMMDD，由 io.spikeglx.read_recording_date() 预抽取
    subject: str     # 来自 SubjectConfig.subject_id
    experiment: str  # 用户现填，如 "nsd1w"
    region: str      # 由 probe_plan.values() 按 probe_id 升序连接，分隔符 "-"
    
    def canonical(self) -> str:
        """返回规范化字符串，如 '251024_FanFan_nsd1w_MSB-V4'。"""
        return f"{self.date}_{self.subject}_{self.experiment}_{self.region}"
    
    @staticmethod
    def derive_region(probe_plan: dict[str, str]) -> str:
        """从 probe_plan 推导 region：按 probe_id 升序，用 '-' 连接 target_area。
        
        多 probe 同 target_area 时不去重（保持与 probe_id 一一对应）。
        probe_plan 为空时 raise ValueError。
        
        例：
          {"imec0": "MSB"}                → "MSB"
          {"imec1": "V4", "imec0": "MSB"} → "MSB-V4"
          {"imec0": "V1", "imec1": "V1"}  → "V1-V1"
        """
        if not probe_plan:
            raise ValueError("probe_plan must declare at least one probe")
        sorted_items = sorted(probe_plan.items(), key=lambda kv: kv[0])
        return "-".join(v for _, v in sorted_items)
    
    def to_dict(self) -> dict[str, str]:
        return {"date": self.date, "subject": self.subject,
                "experiment": self.experiment, "region": self.region}
```

**不做什么**：
- 不校验 region/experiment/subject/date 的字符集（用户自维护）
- 不支持 "参数化" 模板或替换变量
- region 分隔符固定为 `-`，不可配置

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_core/test_session.py`

| 组 | 测试点 |
|----|-------|
| A. Dataclasses | `SubjectConfig` 所有字段 required；`ProbeInfo.target_area` 必填（无默认，缺失 raise TypeError）；`Session.log_path` 由 `__post_init__` 正确设置 |
| B. SessionID | `canonical()` 输出正确；`derive_region()` 按 probe_id 升序；多 probe 同 region 不去重；空 probe_plan raise ValueError；dict 双向转换保留字段 |
| C. from_data_dir() | 正常发现；data_dir 不存在；无 `*_g[0-9]/`；无 `*.bhv2`；多 gate 取第一个并发出 WARNING；experiment/probe_plan/date 透传给 create |
| D. create() | 正常流程 + 目录创建 + session.json 写入；session_dir/bhv_file 不存在；empty probe_plan raise；probe_plan key 格式错误 raise；experiment 空串 raise；date 非 6 位数字 raise；正常构造出 session_id 可 canonical |
| E. save() | Path 序列化为 str；None lf_bin → null；channel_positions 序列化；session_id 序列化为 4 字段 dict；probe_plan 序列化为 dict；log_path 不写入 JSON |
| F. load() | 所有字段正确反序列化（含 session_id、probe_plan）；session.json 不存在；JSON 语法错误；缺少必填键（含 session_id、probe_plan）；`ProbeInfo.target_area` 缺失时 raise |
| G. Roundtrip | create → save → load 得到等价 Session（session_id、probe_plan、probes、checkpoint 全部一致） |

---

## 7. 依赖

- `core/errors.py` — 无（session.py 仅 raise 标准库异常，FileNotFoundError / ValueError / OSError）
- `core/config.py` — `config.load_subject_config()` 导入 `SubjectConfig` from `core.session`（反向依赖，session.py 本身不导入 config）
- `core/checkpoint.py` — 不直接依赖；CheckpointManager 由 stage 层独立持有
- **不依赖** `io/spikeglx.py`：`date` 参数由 create() 调用方预抽取后传入，避免分层反转
- 标准库：`dataclasses`, `pathlib`, `json`, `logging`
