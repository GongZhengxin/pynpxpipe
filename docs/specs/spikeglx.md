# Spec: io/spikeglx.py

## 1. 目标

负责发现、验证和懒加载 SpikeGLX 录制数据。`SpikeGLXDiscovery` 扫描 session 目录，枚举所有 IMEC 探针目录并解析元信息，验证数据完整性。`SpikeGLXLoader` 提供零内存拷贝的懒加载接口（AP bin 可达 400-500GB，严禁整体读入内存），提供从录制对象提取同步脉冲边沿的工具函数，并提供从 `.ap.meta` 的 `fileCreateTime` 抽取规范化录制日期的工具方法（供上层构造 `SessionID.date`）。

## 2. 输入

- `SpikeGLXDiscovery.__init__`: `session_dir: Path` — SpikeGLX 录制根目录（必须存在，否则 `FileNotFoundError`）
- `SpikeGLXDiscovery.discover_probes`: 无额外参数，扫描 `session_dir` 下所有 `*_imec{N}/` 子目录
- `SpikeGLXDiscovery.validate_probe`: `probe: ProbeInfo`
- `SpikeGLXDiscovery.discover_nidq`: 无额外参数，在 `session_dir` 下查找 `*.nidq.bin` + `*.nidq.meta`
- `SpikeGLXDiscovery.parse_meta`: `meta_path: Path` — `.ap.meta` 或 `.nidq.meta` 文件路径
- `SpikeGLXLoader.load_ap`: `probe: ProbeInfo`
- `SpikeGLXLoader.load_nidq`: `nidq_bin: Path, nidq_meta: Path`
- `SpikeGLXLoader.load_preprocessed`: `recording_path: Path` — Zarr 格式已处理录制的目录
- `SpikeGLXLoader.extract_sync_edges`: `recording: si.BaseRecording, sync_bit: int, sample_rate: float`
- `SpikeGLXLoader.read_recording_date`: `ap_meta_path: Path` — 某 probe 的 `.ap.meta` 文件路径

## 3. 输出

- `discover_probes()` → `list[ProbeInfo]`，按 probe 编号升序排列；若无 imec 目录则 raise `DiscoverError`
- `validate_probe()` → `list[str]`，每条警告说明具体问题；空列表表示无问题
- `discover_nidq()` → `tuple[Path, Path]`（nidq_bin, nidq_meta）；找不到则 raise `DiscoverError`
- `parse_meta()` → `dict[str, str]`，键值均为字符串（调用方负责类型转换）
- `load_ap()` → `si.BaseRecording`（懒加载，未读取任何 AP 数据）
- `load_nidq()` → `si.BaseRecording`（懒加载）
- `load_preprocessed()` → `si.BaseRecording`（Zarr 后端懒加载）
- `extract_sync_edges()` → `list[float]`，单位秒，即同步脉冲上升沿时刻列表
- `read_recording_date()` → `str`，6 字符 YYMMDD 格式（如 `"251024"`）

## 4. 处理步骤

### SpikeGLXDiscovery.__init__
1. 验证 `session_dir` 存在，不存在则 raise `FileNotFoundError`
2. 将 `session_dir` 存为 `self.session_dir`

### discover_probes
1. 在 `session_dir` 下用 glob 模式 `*_imec*/` 枚举所有子目录
2. 用正则 `_imec(\d+)` 提取 probe 编号 N
3. 对每个 imec 目录，在其下查找 `*.ap.meta` 文件（取第一个匹配）
4. 若找到 meta 文件，调用 `parse_meta()` 提取字段，构造 `ProbeInfo`
5. 将所有 ProbeInfo 按 probe 编号整数升序排列
6. 若列表为空则 raise `DiscoverError("No imec probe directories found in {session_dir}")`

### validate_probe
1. 初始化空 `warnings: list[str]`
2. 检查 `probe.ap_bin` 是否存在，不存在则追加警告
3. 检查 `probe.ap_meta` 是否存在，不存在则追加警告
4. 若 bin 和 meta 均存在：取 `probe.ap_bin` 实际文件大小，与 meta 中 `fileSizeBytes` 比较；若不匹配则追加警告
5. 检查 meta 中必要字段（`imSampRate`, `nSavedChans`）是否存在，缺失则逐一追加警告
6. 返回 `warnings`（不 raise，不副作用）

### discover_nidq
1. 在 `session_dir` 下 glob `*.nidq.bin`，取第一个匹配；无则 raise `DiscoverError`
2. 由同名规则推断 meta 路径
3. 验证 meta 文件存在，不存在则 raise `DiscoverError`
4. 返回 `(nidq_bin, nidq_meta)`

### parse_meta
1. 以 `encoding='utf-8'` 打开文件，逐行读取
2. 跳过空行和以 `#` 开头的注释行
3. 按首个 `=` 分割，左侧为 key，右侧为 value（均 strip 空白）
4. 返回 dict

### SpikeGLXLoader.load_ap
1. 从 `probe.probe_id` 构造 stream_name：`f"{probe.probe_id}.ap"`（如 `"imec0.ap"`）
2. 调用 `si.read_spikeglx(probe.ap_bin.parent, stream_name=stream_name, load_sync_channel=True)`
3. 返回 recording 对象（懒加载，不触发任何 bin 文件读取）

### SpikeGLXLoader.load_nidq
1. 调用 `si.read_spikeglx(nidq_bin.parent, stream_name="nidq")`
2. 返回 recording 对象（懒加载）

### SpikeGLXLoader.load_preprocessed
1. 调用 `si.load(recording_path)` 加载 Zarr 格式录制
2. 返回 recording 对象

### SpikeGLXLoader.extract_sync_edges
1. 从 recording 获取数字同步通道原始数据
2. 用位掩码 `(data >> sync_bit) & 1` 提取指定 bit 的二值信号
3. 用 `np.diff` 找到值为 1 的索引（上升沿的样本位置）
4. 样本位置除以 `sample_rate` 转换为秒
5. 返回 `list[float]`

### SpikeGLXLoader.read_recording_date
1. 若 `ap_meta_path` 不存在 → raise `FileNotFoundError`（不包装，保持与 `parse_meta` 一致）
2. 按 `parse_meta` 同逻辑读取 meta 为 dict（建议抽取模块级私有 `_parse_meta_file(path)` 复用于两处，避免 `SpikeGLXLoader` ↔ `SpikeGLXDiscovery` 耦合）
3. 若 dict 中缺少 `fileCreateTime` 键 → raise `ValueError(f"Meta file missing required field 'fileCreateTime': {ap_meta_path}")`
4. 取 `raw = meta['fileCreateTime'].strip()`
5. 显式校验格式：`raw` 必须同时含日期段和时间段。判定规则：若 `raw` 既不含 `T`、也不含空格分隔的时间段，raise `ValueError(f"Unparseable fileCreateTime value {raw!r} in {ap_meta_path}")`
6. 标准化分隔符：若 `raw` 含空格且不含 `T`，将首个空格替换为 `T`
7. 严格解析：`dt = datetime.fromisoformat(normalized)`；任何 `ValueError` 捕获后重新 raise `ValueError(f"Unparseable fileCreateTime value {raw!r} in {ap_meta_path}")`
8. 返回 `dt.strftime("%y%m%d")`（如 2025-10-24T14:32:11 → `"251024"`）

**拒绝**的退化格式：纯数字串（`"20251024"`、`"251024"`）、欧美日期格式（`"10/24/2025"`）、仅日期无时间（`"2025-10-24"`）。由步骤 5 的显式校验兜底，不依赖 `fromisoformat` 对 date-only 输入的宽松行为。

## 5. 公开 API 与可配参数

```python
class SpikeGLXDiscovery:
    """Scans a SpikeGLX session directory and validates its contents.

    Args:
        session_dir: Root directory of a SpikeGLX recording session.

    Raises:
        FileNotFoundError: If session_dir does not exist.
    """

    def __init__(self, session_dir: Path) -> None: ...
    def discover_probes(self) -> list[ProbeInfo]: ...
    def validate_probe(self, probe: ProbeInfo) -> list[str]: ...
    def discover_nidq(self) -> tuple[Path, Path]: ...
    def parse_meta(self, meta_path: Path) -> dict[str, str]: ...


class SpikeGLXLoader:
    """Static factory methods for lazy SpikeInterface recordings."""

    @staticmethod
    def load_ap(probe: ProbeInfo, *, load_sync_channel: bool = False) -> si.BaseRecording: ...

    @staticmethod
    def load_lf(probe: ProbeInfo) -> si.BaseRecording: ...

    @staticmethod
    def load_nidq(nidq_bin: Path, nidq_meta: Path) -> si.BaseRecording: ...

    @staticmethod
    def load_preprocessed(recording_path: Path) -> si.BaseRecording: ...

    @staticmethod
    def extract_sync_edges(
        recording: si.BaseRecording, sync_bit: int, sample_rate: float
    ) -> list[float]: ...

    @staticmethod
    def read_recording_date(ap_meta_path: Path) -> str:
        """Extract the recording date from a probe's .ap.meta ``fileCreateTime``.

        This is the single source of truth for ``SessionID.date``. Upper layers
        (UI form, CLI, SessionManager caller) call this helper BEFORE constructing
        a Session so that ``core/session.py`` does not need to import
        ``io/spikeglx.py`` (preserving the core ↛ io layering rule).

        Args:
            ap_meta_path: Absolute path to a ``.ap.meta`` file (any probe works;
                in practice callers use the first probe's meta).

        Returns:
            6-character ``YYMMDD`` string, e.g. ``"251024"``.

        Raises:
            FileNotFoundError: If ap_meta_path does not exist.
            ValueError: If the meta file lacks ``fileCreateTime`` (message includes
                meta path and field name), or if ``fileCreateTime`` cannot be parsed
                as a full ISO-ish datetime (message includes the raw string).
                Degenerate formats (pure digits, date-only, MM/DD/YYYY) are
                rejected — SpikeGLX always writes ISO-ish ``YYYY-MM-DDThh:mm:ss``
                (optionally with a space separator).
        """
```

**上层调用契约（重要）**

- `SpikeGLXLoader.read_recording_date` 是 `SessionID.date` 的**唯一**生产者
- 调用方：UI 的 session form、CLI 的 `run` 子命令、任何构造 `Session` 的工厂代码
- `core/session.py` 的 `SessionManager.create()` 签名接收 `date: str`，**不**内部调用本方法（保持分层：core 不依赖 io）
- 典型调用链：
  ```python
  from pynpxpipe.io.spikeglx import SpikeGLXDiscovery, SpikeGLXLoader
  discovery = SpikeGLXDiscovery(session_dir)
  probes = discovery.discover_probes()
  date = SpikeGLXLoader.read_recording_date(probes[0].ap_meta)
  session = SessionManager.create(..., date=date, experiment=..., probe_plan=..., ...)
  ```

## 6. 测试范围（TDD 用）

既有测试（保留）：`__init__`、`discover_probes`、`validate_probe`、`discover_nidq`、`parse_meta`、`extract_sync_edges` 覆盖面不变。

### 新增：`read_recording_date`

| 测试名 | 输入 | 预期行为 |
|---|---|---|
| `test_read_recording_date_normal` | meta 含 `fileCreateTime=2025-10-24T14:32:11` | 返回 `"251024"` |
| `test_read_recording_date_space_separator` | meta 含 `fileCreateTime=2025-10-24 14:32:11`（SpikeGLX 实际写出格式） | 返回 `"251024"` |
| `test_read_recording_date_missing_field_raises` | meta 存在但无 `fileCreateTime` | raise `ValueError`，消息含 `fileCreateTime` 字段名和 meta path |
| `test_read_recording_date_malformed_raises` | `fileCreateTime=not-a-date`、`20251024`、`10/24/2025`、`2025-10-24`（仅日期） | raise `ValueError`，消息含原始值字符串 |
| `test_read_recording_date_file_not_found_raises` | 传入不存在的 meta 路径 | raise `FileNotFoundError`（不包装） |

## 7. 依赖

- `pynpxpipe.core.errors` — `DiscoverError`
- `pynpxpipe.core.session` — `ProbeInfo` dataclass
- 标准库：`pathlib.Path`, `re`, `datetime.datetime`（供 `read_recording_date` 使用 `fromisoformat` / `strftime`）
- 第三方：`spikeinterface`（`read_spikeglx`, `load`）、`numpy`（仅 `extract_sync_edges`）

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #0（文件夹发现）、#1（NIDQ 加载）、#5（IMEC AP metadata） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #0, #1, #5 |

### 有意偏离

| 偏离 | 理由 |
|------|------|
| 使用 SpikeInterface `read_spikeglx` 而非手动解析 | SI 提供经过验证的标准化读取器 |
| 自动检测多 probe | MATLAB 硬编码 `imec0`，不支持多探针 |
| sync 脉冲从 AP digital channel 提取 | AP 采样率 30 kHz vs LF 2.5 kHz，时间精度更高 |
| 新增 `read_recording_date` 作为 `SessionID.date` 唯一生产者 | MATLAB 从目录名切片或手输获得日期；pynpxpipe 从 `.ap.meta.fileCreateTime` 抽取，保证与实际录制时刻一致且零人为输入 |
