# Spec: io/nwb_writer.py

## 1. 目标

将 pynpxpipe 处理流程的最终结果写入 DANDI 兼容的 NWB 2.x 文件。一个 session 对应一个 NWB 文件，包含所有探针的电极、单元活动、波形特征、行为事件和 trial 信息。模块仅负责 NWB 格式组装与写盘，不执行任何电生理计算。LFP 接口预留但不实现（始终 raise `NotImplementedError`）。

## 2. 输入

- `NWBWriter.__init__`: `session: Session`（含 subject、session_dir、probes 等），`output_path: Path`（NWB 文件输出路径）
- `create_file()`: 从 session 对象和第一个 probe 的 ap.meta 的 `fileCreateTime` 字段获取录制开始时间
- `add_probe_data(probe: ProbeInfo, analyzer: si.SortingAnalyzer)`: probe 元信息 + 已计算好 waveforms/templates/unit_locations 扩展的 SortingAnalyzer
- `add_trials(behavior_events: pd.DataFrame)`: 列名为 `trial_id, onset_nidq_s, stim_onset_nidq_s, condition_id, trial_valid` 的 DataFrame
- `add_lfp(probe: ProbeInfo, lfp_data: np.ndarray)`: 接口参数（实现体直接 raise）
- `write()`: 无额外参数

## 3. 输出

- `create_file()` → `NWBFile` 实例（内存中），不写盘；同时存储为 `self._nwbfile`
- `add_probe_data()` → `None`；副作用：将 ElectrodeGroup、electrodes 行和 units 行追加到内部 NWBFile
- `add_trials()` → `None`；副作用：将 TimeIntervals（trials）追加到内部 NWBFile
- `add_lfp()` → 始终 raise `NotImplementedError`
- `write()` → `Path`（最终写入的 NWB 文件绝对路径）；副作用：在 `output_path` 写出压缩 HDF5 文件

## 4. 处理步骤

### NWBWriter.__init__
1. 存储 `session` 和 `output_path`
2. 初始化 `self._nwbfile: NWBFile | None = None`

### create_file
1. 验证 `session.subject` 中 DANDI 必填字段（`subject_id`, `species`, `sex`, `age`）均不为空字符串，否则 raise `ValueError("Missing required DANDI subject fields: {missing_fields}")`
2. 从 `session.probes[0].ap_meta` 解析 meta，提取 `fileCreateTime`（格式 `"YYYY-MM-DDThh:mm:ss"`），转换为 `datetime`（附加 UTC tzinfo）
3. 构造 `NWBSubject` 对象，映射所有 SubjectConfig 字段
4. 构造 `NWBFile`：
   - `identifier`: `str(uuid.uuid4())`
   - `session_description`: `f"pynpxpipe processed: {session.session_dir.name}"`
   - `session_start_time`: 步骤 2 中获取的 aware datetime
   - `subject`: 步骤 3 的 NWBSubject
5. 存入 `self._nwbfile`，返回 NWBFile 实例

### add_probe_data
1. 若 `self._nwbfile is None` 则 raise `RuntimeError("call create_file() before add_probe_data()")`
2. 验证 `analyzer` 已计算以下扩展：`waveforms`，`templates`，`unit_locations`；缺失则 raise `ValueError`
3. 构造 `ElectrodeGroup`（name=probe_id, description=probe_type+SN, device=NWBDevice）
4. 向 `self._nwbfile.electrodes` DynamicTable 追加每个通道的行：`x`、`y`（μm，来自 channel_positions）、`z=0.0`、`group`、`group_name`、`probe_id`、`channel_id`
5. 从 `analyzer` 提取每个 unit 的数据并调用 `self._nwbfile.add_unit()` 逐 unit 追加：
   - `spike_times`: `analyzer.sorting.get_unit_spike_train(unit_id, return_times=True)`
   - quality metrics: `isi_violation_ratio`, `amplitude_cutoff`, `presence_ratio`, `snr`（来自 quality_metrics extension）
   - `slay_score`: 从 quality_metrics 取（若列不存在则填 `np.nan`）
   - `waveform_mean`, `waveform_std`: 来自 templates/waveforms extension（shape: n_samples × n_channels, μV）
   - `unit_location`: 来自 unit_locations extension（shape: (3,) μm）
   - `probe_id`, `electrode_group`

### add_trials
1. 若 `self._nwbfile is None` 则 raise `RuntimeError`
2. 验证 DataFrame 包含必要列：`trial_id`, `onset_nidq_s`, `stim_onset_nidq_s`, `condition_id`, `trial_valid`；缺失则 raise `ValueError`
3. 构造 `TimeIntervals("trials")`，添加自定义列：`stim_onset_time`, `trial_id`, `condition_id`, `trial_valid`
4. 对 DataFrame 每行调用 `trials.add_interval()`（start_time=onset_nidq_s, stop_time=onset_nidq_s, 其余字段按列名映射）
5. 将 trials 追加到 `self._nwbfile`

### add_lfp
1. raise `NotImplementedError("LFP export is not yet implemented. Reserved for future lfp_process stage integration.")`

### write
1. 若 `self._nwbfile is None` 则 raise `RuntimeError("call create_file() before write()")`
2. 确保 `output_path.parent` 目录存在（`mkdir(parents=True, exist_ok=True)`）
3. 以 `pynwb.NWBHDF5IO(self.output_path, mode='w')` 打开，调用 `io.write(self._nwbfile)`
4. 返回 `self.output_path`

## 5. 公开 API 与可配参数

```python
class NWBWriter:
    """Assembles and writes a DANDI-compliant NWB 2.x file for one session.

    All probes are written into a single NWB file. LFP export is reserved
    for a future release and raises NotImplementedError.

    Args:
        session: Session object providing subject metadata, probe list,
                 and path information.
        output_path: Destination path for the output .nwb file.
    """

    def __init__(self, session: Session, output_path: Path) -> None: ...

    def create_file(self) -> pynwb.NWBFile:
        """Create an in-memory NWBFile with session and subject metadata.

        Reads session_start_time from the first probe's .ap.meta fileCreateTime.
        Must be called before add_probe_data(), add_trials(), or write().

        Raises:
            ValueError: If any DANDI-required subject field is empty.
        """

    def add_probe_data(
        self,
        probe: ProbeInfo,
        analyzer: si.SortingAnalyzer,
    ) -> None:
        """Add electrode group, electrodes, and units for one probe.

        Raises:
            RuntimeError: If create_file() has not been called.
            ValueError: If required analyzer extensions are missing.
        """

    def add_trials(self, behavior_events: pd.DataFrame) -> None:
        """Populate the NWB trials TimeIntervals from a behavior events DataFrame.

        Raises:
            RuntimeError: If create_file() has not been called.
            ValueError: If required DataFrame columns are missing.
        """

    def add_lfp(self, probe: ProbeInfo, lfp_data: np.ndarray) -> None:
        """Reserved interface for LFP export — not yet implemented.

        Raises:
            NotImplementedError: Always.
        """

    def write(self) -> Path:
        """Write the assembled NWBFile to disk.

        Returns:
            Absolute path of the written .nwb file.

        Raises:
            RuntimeError: If create_file() has not been called.
        """
```

## 6. 测试范围（TDD 用）

| 测试组 | 用例 | 预期行为 |
|---|---|---|
| `__init__` | 合法 session + output_path | 正常构造，_nwbfile 为 None |
| `create_file` 正常 | 合法 session，meta 含 fileCreateTime | 返回 NWBFile，identifier 为合法 UUID |
| `create_file` 正常 | session_description 包含 session 目录名 | 字段值格式正确 |
| `create_file` 正常 | NWBFile.subject.subject_id 匹配 SubjectConfig | 字段正确映射 |
| `create_file` 正常 | session_start_time 为 aware datetime | 不为 naive datetime |
| `create_file` 错误 | subject.subject_id 为空字符串 | raise `ValueError` 含字段名提示 |
| `create_file` 错误 | subject.species 为空字符串 | raise `ValueError` |
| `create_file` 错误 | subject.sex 为空字符串 | raise `ValueError` |
| `create_file` 错误 | subject.age 为空字符串 | raise `ValueError` |
| `add_probe_data` 正常 | 合法 probe + analyzer（含所有扩展） | NWBFile 含对应 ElectrodeGroup |
| `add_probe_data` 正常 | units table 含 spike_times, probe_id | 列存在且值类型正确 |
| `add_probe_data` 正常 | units table 含 waveform_mean（2D array） | shape 为 (n_samples, n_channels) |
| `add_probe_data` 正常 | slay_score 列不存在于 quality_metrics | slay_score 填 np.nan，不 raise |
| `add_probe_data` 正常 | 两个 probe 依次调用 | electrodes table 含两组 probe_id |
| `add_probe_data` 错误 | create_file 未调用 | raise `RuntimeError` |
| `add_probe_data` 错误 | analyzer 缺少 waveforms 扩展 | raise `ValueError` 含扩展名 |
| `add_probe_data` 错误 | analyzer 缺少 unit_locations 扩展 | raise `ValueError` |
| `add_trials` 正常 | 合法 DataFrame，3 条 trial | trials table 含 3 行，字段正确 |
| `add_trials` 错误 | create_file 未调用 | raise `RuntimeError` |
| `add_trials` 错误 | DataFrame 缺少 trial_id 列 | raise `ValueError` |
| `add_lfp` | 任何输入 | 始终 raise `NotImplementedError`，message 含 "LFP" |
| `write` 正常 | create_file 已调用，output_path 父目录不存在 | 自动创建父目录，写出文件，返回 output_path |
| `write` 正常 | 写出的文件可被 pynwb.NWBHDF5IO 打开 | 读取无异常 |
| `write` 错误 | create_file 未调用 | raise `RuntimeError` |
| 集成 | create_file → add_probe_data（2 probe）→ add_trials → write → 重新读取 | 电极组数为 2，units 含两组 probe_id |

## 7. 依赖

- `pynpxpipe.core.session` — `Session`, `SubjectConfig`
- `pynpxpipe.io.spikeglx` — `ProbeInfo`, `SpikeGLXDiscovery`（读取 meta 的 fileCreateTime）
- 标准库：`pathlib.Path`, `uuid`, `datetime`
- 第三方：`pynwb`（>= 2.8）, `spikeinterface`, `numpy`, `pandas`

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #20（GoodUnit 最终输出） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #20 段落 |

### 有意偏离

| 偏离 | 理由 |
|------|------|
| 输出 NWB 格式而非 .mat | MATLAB 输出 GoodUnit.mat；NWB 是 DANDI/Brain Initiative 标准，支持跨平台共享 |
| 一个 NWB 文件包含所有 probe | MATLAB 可能按 probe 分别输出；NWB 标准鼓励 session 级聚合 |
| 通过 pynwb 组装而非手写 HDF5 | MATLAB 直接操作 struct 序列化；pynwb 提供 schema 验证和 DANDI 兼容性检查 |
| spike times 在写入时才做时钟转换 | MATLAB step #15 提前将 spike times 从 IMEC 转换到 NIDQ 时钟；Python 在 export 阶段按需转换，保持 postprocess 阶段 spike times 在原始 IMEC 时钟 |
