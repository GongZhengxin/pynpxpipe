# Spec: io/spikeglx.py

## 1. 目标

负责发现、验证和懒加载 SpikeGLX 录制数据。`SpikeGLXDiscovery` 扫描 session 目录，枚举所有 IMEC 探针目录并解析元信息，验证数据完整性。`SpikeGLXLoader` 提供零内存拷贝的懒加载接口（AP bin 可达 400-500GB，严禁整体读入内存），并提供从录制对象提取同步脉冲边沿的工具函数。

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

## 3. 输出

- `discover_probes()` → `list[ProbeInfo]`，按 probe 编号升序排列；若无 imec 目录则 raise `DiscoverError`
- `validate_probe()` → `list[str]`，每条警告说明具体问题；空列表表示无问题
- `discover_nidq()` → `tuple[Path, Path]`（nidq_bin, nidq_meta）；找不到则 raise `DiscoverError`
- `parse_meta()` → `dict[str, str]`，键值均为字符串（调用方负责类型转换）
- `load_ap()` → `si.BaseRecording`（懒加载，未读取任何 AP 数据）
- `load_nidq()` → `si.BaseRecording`（懒加载）
- `load_preprocessed()` → `si.BaseRecording`（Zarr 后端懒加载）
- `extract_sync_edges()` → `list[float]`，单位秒，即同步脉冲上升沿时刻列表

## 4. 处理步骤

### SpikeGLXDiscovery.__init__
1. 验证 `session_dir` 存在，不存在则 raise `FileNotFoundError`
2. 将 `session_dir` 存为 `self.session_dir`

### discover_probes
1. 在 `session_dir` 下用 glob 模式 `*_imec*/` 枚举所有子目录
2. 用正则 `_imec(\d+)` 提取 probe 编号 N
3. 对每个 imec 目录，在其下查找 `*.ap.meta` 文件（取第一个匹配）
4. 若找到 meta 文件，调用 `parse_meta()` 提取字段，构造 `ProbeInfo`：
   - `probe_id = f"imec{N}"`
   - `ap_bin` 从 meta 文件名推断（将 `.ap.meta` 后缀替换为 `.ap.bin`）
   - `ap_meta = meta_path`
   - `sample_rate = float(meta['imSampRate'])`
   - `n_channels = int(meta['nSavedChans'])`
   - `serial_number = meta.get('imProbeSN', 'unknown')`
   - `probe_type = meta.get('imProbeOpt', meta.get('imProbeType', 'unknown'))`
   - `lf_bin`, `lf_meta` 若存在则填充，否则 `None`
5. 将所有 ProbeInfo 按 probe 编号整数升序排列
6. 若列表为空则 raise `DiscoverError("No imec probe directories found in {session_dir}")`
7. 返回列表

### validate_probe
1. 初始化空 `warnings: list[str]`
2. 检查 `probe.ap_bin` 是否存在，不存在则追加警告
3. 检查 `probe.ap_meta` 是否存在，不存在则追加警告
4. 若 bin 和 meta 均存在：取 `probe.ap_bin` 实际文件大小，与 meta 中 `fileSizeBytes` 比较；若不匹配则追加警告
5. 检查 meta 中必要字段（`imSampRate`, `nSavedChans`）是否存在，缺失则逐一追加警告
6. 返回 `warnings`（不 raise，不副作用）

### discover_nidq
1. 在 `session_dir` 下 glob `*.nidq.bin`，取第一个匹配；无则 raise `DiscoverError`
2. 由同名规则推断 meta 路径：将 `.nidq.bin` 后缀替换为 `.nidq.meta`
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
1. 调用 `si.load_extractor(recording_path)` 加载 Zarr 格式录制
2. 返回 recording 对象

### SpikeGLXLoader.extract_sync_edges
1. 从 recording 获取数字同步通道原始数据
2. 用位掩码 `(data >> sync_bit) & 1` 提取指定 bit 的二值信号，flatten 为一维数组
3. 用 `np.diff` 计算差分，找到值为 1 的索引（即 0→1 上升沿的样本位置）
4. 将样本位置除以 `sample_rate` 转换为秒
5. 返回 `list[float]`

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

    def discover_probes(self) -> list[ProbeInfo]:
        """Scan for all imec{N} probe directories and build ProbeInfo list.

        Returns:
            List of ProbeInfo sorted ascending by probe index.

        Raises:
            DiscoverError: If no imec directories are found.
        """

    def validate_probe(self, probe: ProbeInfo) -> list[str]:
        """Check a single probe for data completeness issues.

        Returns:
            List of warning message strings. Empty list means no issues found.
        """

    def discover_nidq(self) -> tuple[Path, Path]:
        """Locate the NIDQ .bin and .meta files in the session directory.

        Returns:
            Tuple of (nidq_bin_path, nidq_meta_path).

        Raises:
            DiscoverError: If nidq.bin or nidq.meta cannot be found.
        """

    def parse_meta(self, meta_path: Path) -> dict[str, str]:
        """Parse a SpikeGLX INI-like .meta file into a key-value dict.

        Both keys and values are returned as raw strings.

        Args:
            meta_path: Absolute path to a .ap.meta or .nidq.meta file.
        """


class SpikeGLXLoader:
    """Static factory methods for lazy SpikeInterface recordings."""

    @staticmethod
    def load_ap(probe: ProbeInfo) -> si.BaseRecording:
        """Return a lazy SpikeInterface recording for one probe's AP stream.

        No data is read from disk. The .ap.bin can be 400-500 GB.
        """

    @staticmethod
    def load_nidq(nidq_bin: Path, nidq_meta: Path) -> si.BaseRecording:
        """Return a lazy SpikeInterface recording for the NIDQ stream."""

    @staticmethod
    def load_preprocessed(recording_path: Path) -> si.BaseRecording:
        """Load a previously saved preprocessed recording from Zarr format."""

    @staticmethod
    def extract_sync_edges(
        recording: si.BaseRecording,
        sync_bit: int,
        sample_rate: float,
    ) -> list[float]:
        """Extract rising-edge timestamps of a sync pulse from a digital channel.

        Args:
            recording: Lazy BaseRecording that includes the digital sync channel.
            sync_bit: Bit index (0-based) within the sync word to extract.
            sample_rate: Sampling rate in Hz. Read from meta, NOT hardcoded.

        Returns:
            List of rising-edge times in seconds.
        """
```

## 6. 测试范围（TDD 用）

| 测试组 | 用例 | 预期行为 |
|---|---|---|
| `__init__` 正常 | session_dir 存在 | 正常构造，无异常 |
| `__init__` 错误 | session_dir 不存在 | raise `FileNotFoundError` |
| `discover_probes` 正常 | 目录含 `_imec0/` 和 `_imec1/`，各有合法 meta | 返回长度为 2 的列表，按 probe_id 升序 |
| `discover_probes` 正常 | 单 probe `_imec0/` | 返回长度为 1 的列表 |
| `discover_probes` 正常 | meta 含 imSampRate, nSavedChans, imProbeSN | ProbeInfo 字段正确映射 |
| `discover_probes` 正常 | meta 缺少 imProbeSN 字段 | `serial_number == "unknown"` |
| `discover_probes` 错误 | 目录下无 imec 子目录 | raise `DiscoverError` |
| `discover_probes` 边界 | imec 目录存在但无 .ap.meta 文件 | 该 probe 被跳过；若跳后列表为空则 raise `DiscoverError` |
| `discover_probes` 边界 | imec 目录编号不连续（0, 2） | 仍正确枚举，按编号升序 |
| `validate_probe` 正常 | bin + meta 均存在，大小匹配 | 返回空列表 |
| `validate_probe` 警告 | .ap.bin 不存在 | 返回含 bin-missing 警告的列表 |
| `validate_probe` 警告 | .ap.meta 不存在 | 返回含 meta-missing 警告的列表 |
| `validate_probe` 警告 | bin 实际大小与 fileSizeBytes 不符 | 返回含 size-mismatch 警告的列表 |
| `validate_probe` 警告 | fileSizeBytes 字段缺失 | 不追加大小警告，返回空列表 |
| `validate_probe` 警告 | meta 缺少 imSampRate | 返回含字段缺失警告的列表 |
| `validate_probe` 行为 | 存在多个问题 | 所有警告均在列表中，不 raise |
| `discover_nidq` 正常 | 目录含 .nidq.bin + .nidq.meta | 返回 (bin_path, meta_path) 元组 |
| `discover_nidq` 错误 | 无 .nidq.bin | raise `DiscoverError` |
| `discover_nidq` 错误 | .nidq.bin 存在但 .nidq.meta 缺失 | raise `DiscoverError` |
| `parse_meta` 正常 | 标准 key=value 格式 | 返回正确 dict |
| `parse_meta` 正常 | 含空行和注释行（# 开头） | 空行和注释被跳过 |
| `parse_meta` 正常 | value 含 = 号（如路径） | 仅以首个 = 分割，value 完整保留 |
| `parse_meta` 边界 | 空文件 | 返回空 dict |
| `parse_meta` 边界 | key 或 value 含前后空格 | strip 后正确存储 |
| `extract_sync_edges` 正常 | 已知上升沿位置的合成二进制信号 | 返回与期望时刻一致的列表 |
| `extract_sync_edges` 正常 | sync_bit=0 vs sync_bit=1 提取不同脉冲 | 各自只返回对应 bit 的边沿 |
| `extract_sync_edges` 边界 | 全零信号（无脉冲） | 返回空列表 |
| `extract_sync_edges` 边界 | 单个上升沿 | 返回长度为 1 的列表 |

## 7. 依赖

- `pynpxpipe.core.errors` — `DiscoverError`
- `pynpxpipe.core.session` — `ProbeInfo` dataclass
- 标准库：`pathlib.Path`, `re`
- 第三方：`spikeinterface`（`read_spikeglx`, `load_extractor`）, `numpy`（仅 `extract_sync_edges`）

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #0（SpikeGLX 文件夹发现）, #1（NIDQ 数据加载）, #5（IMEC AP metadata 加载） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #0, #1, #5; `docs/ground_truth/step5_matlab_vs_python.md` step #0, #1, #5 |

### 有意偏离

| 偏离 | 理由 |
|------|------|
| 使用 SpikeInterface `read_spikeglx` 而非手动解析 | MATLAB 手动用 `dir()` + 字符串匹配发现文件；SI 提供经过验证的标准化读取器 |
| 自动检测多 probe（不硬编码 imec0） | MATLAB 硬编码 `imec0`，不支持多探针；Python 扫描所有 `imec*` 目录 |
| meta 解析委托给 SI（不手动解析 .meta 文件） | MATLAB 使用 `SpikeGLX_Datafile_Tools` 手动解析；SI 封装了相同逻辑 |
| sync 脉冲提取从 AP digital channel 而非 LF channel | MATLAB step #4 从 LF 提取 sync；Python 从 AP digital channel 提取（更精确，AP 采样率 30kHz vs LF 2.5kHz） |
| Python 使用 `⚠️ signals_info_dict` 私有 API 存疑 | step5 指出旧代码使用 SI 私有属性；spec 要求使用公开 API `read_spikeglx` |
