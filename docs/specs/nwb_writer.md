# Spec: io/nwb_writer.py

## 1. 目标

将 pynpxpipe 处理流程的最终结果写入 DANDI 兼容的 NWB 2.x 文件。一个 session 对应一个 NWB 文件，包含所有探针的电极、单元活动、波形特征、行为事件和 trial 信息。模块仅负责 NWB 格式组装与写盘，不执行任何电生理计算。LFP 接口预留但不实现（始终 raise `NotImplementedError`）。

**文件命名与身份元数据的唯一真源**：NWB 输出文件名由 `session.session_id.canonical()` 决定，NWBFile 内部的 `session_id` 字段同步使用该 canonical 字符串。电极组脑区（`ElectrodeGroup.location`）与 electrodes 行的 `location` 字段来自 `probe.target_area`（由 `discover` stage 从 `session.probe_plan` 注入），是多 probe 场景下每个探针独立的脑区标识。

## 2. 输入

- `NWBWriter.__init__`: `session: Session`（必含 `session_id: SessionID`、`subject`、`session_dir`、`probes` 等），`output_path: Path`（NWB 文件输出路径，上游 runner 构造时应使用 `{session.session_id.canonical()}.nwb` 作为文件名）
- `create_file()`: 从 session 对象读取 `session_id`、`subject` 元信息；从第一个 probe 的 `ap.meta` 的 `fileCreateTime` 字段获取录制开始时间
- `add_probe_data(probe: ProbeInfo, analyzer: si.SortingAnalyzer)`: probe 元信息 + 已计算好 waveforms/templates/unit_locations 扩展的 SortingAnalyzer。**要求 `probe.target_area` 为非空且 `!= "unknown"`**（该不变量由 discover stage 保证，上游若违反则不应进入 export）
- `add_trials(behavior_events: pd.DataFrame)`: 列名至少包含 `trial_id, onset_nidq_s, stim_onset_nidq_s, stim_onset_imec_s, condition_id, trial_valid` 的 DataFrame。`stim_onset_imec_s` 是逐 trial 的 JSON 字符串，映射 `{probe_id: t_imec_seconds}`，**必须包含 reference probe `imec0`**（模块常量 `_REFERENCE_PROBE`，不配置化）
- `add_lfp(probe: ProbeInfo, lfp_data: np.ndarray)`: 接口参数（实现体直接 raise）
- `write()`: 无额外参数

### 2.1 session 必需字段（硬前置条件）

| 字段 | 约束 | 失败后果 |
|------|------|----------|
| `session.session_id` | `SessionID` 实例，4 字段均非空字符串 | `create_file()` 访问 `.canonical()` 时 AttributeError / ValueError |
| `session.subject.{subject_id,species,sex,age}` | 均非空字符串 | `create_file()` raise `ValueError` |
| `session.probes[*].target_area` | 非空字符串，且 `!= "unknown"` | `add_probe_data()` 会把该值写入 `ElectrodeGroup.location`；上游 discover 已保证，此模块不再重复校验 |

## 3. 输出

- `create_file()` → `NWBFile` 实例（内存中），不写盘；同时存储为 `self._nwbfile`
- `add_probe_data()` → `None`；副作用：将 ElectrodeGroup（`location=probe.target_area`）、electrodes 行（每行 `location=probe.target_area`）和 units 行追加到内部 NWBFile
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
4. 计算 `canonical = session.session_id.canonical()`（例："251024_MaoDan_nsd1w_MSB-V4"）
5. 构造 `NWBFile`：
   - `identifier`: `str(uuid.uuid4())`
   - `session_id`: `canonical`（直接使用 SessionID.canonical() 字符串，**禁止**再从 `session.session_dir.name` 或其他 derived 字符串推导）
   - `session_description`: 以 canonical 开头，格式 `f"{canonical} | pynpxpipe processed"`（canonical 必须出现在开头，便于 DANDI 检索和人工扫读）
   - `session_start_time`: 步骤 2 中获取的 aware datetime
   - `subject`: 步骤 3 的 NWBSubject
6. 存入 `self._nwbfile`，返回 NWBFile 实例

### add_probe_data
1. 若 `self._nwbfile is None` 则 raise `RuntimeError("call create_file() before add_probe_data()")`
2. 验证 `analyzer` 已计算以下扩展：`waveforms`，`templates`，`unit_locations`；缺失则 raise `ValueError`
3. 构造 `ElectrodeGroup`：
   - `name=probe.probe_id`
   - `description=f"Probe {probe.probe_id}: {probe.probe_type} SN:{probe.serial_number}"`
   - `device=NWBDevice`
   - **`location=probe.target_area`** — 此值由 discover stage 从 `session.probe_plan` 注入，是 probe_plan 的最终归宿。断言前提：`probe.target_area` 既非空也非 `"unknown"`（discover 已保证，上游契约错误时此处写入的值即为错误标签，但此模块不再二次校验，避免重复门卫）
   - 多 probe 场景下每次调用 `add_probe_data(probe, ...)` 都创建独立的 ElectrodeGroup，其 location 各自取自对应 `probe.target_area`
4. 向 `self._nwbfile.electrodes` DynamicTable 追加每个通道的行：`x`、`y`（μm，来自 channel_positions）、`z=0.0`、`group`、`group_name`、`probe_id`、`channel_id`、**`location=probe.target_area`**（与 ElectrodeGroup.location 一致）
5. 从 `analyzer` 提取每个 unit 的数据并调用 `self._nwbfile.add_unit()` 逐 unit 追加：
   - `spike_times`: `analyzer.sorting.get_unit_spike_train(unit_id, return_times=True)` — **IMEC 时钟秒，不做 NIDQ 转换**
   - `ks_id`: Kilosort cluster ID（`int(unit_id)` 或 fallback index）
   - `unittype_string`: 单元分类（"SUA"/"MUA"/"NON-SOMA"/"unknown"），来自 sorting property
   - quality metrics: `isi_violation_ratio`, `amplitude_cutoff`, `presence_ratio`, `snr`（来自 quality_metrics extension）
   - `slay_score`: 从 slay_scores.json 读取（若不存在则填 `np.nan`）
   - `is_visual`: 从 slay_scores.json 读取（bool，若不存在则填 `False`）
   - `waveform_mean`, `waveform_std`: 来自 templates/waveforms extension（shape: n_samples × n_channels, μV）
   - `unit_location`: 来自 unit_locations extension（shape: (3,) μm）
   - `probe_id`, `electrode_group`
   - `Raster`（可选）：若 `rasters` 参数提供且含该 unit_id，写入 `(n_valid_trials, n_bins) uint8` 数组；否则空数组

### add_trials

> **Reference probe is hardcoded `imec0`** (module constant `_REFERENCE_PROBE`). The trials table anchors `start_time` / `stop_time` / `stim_onset_time` to IMEC seconds so `units.spike_times` and `trials.start_time` share a single clock. NIDQ seconds survive as the diagnostic column `stim_onset_nidq_s_diag`.

Required DataFrame columns (缺失任一则 raise `ValueError`):

- `trial_id`, `onset_nidq_s`, `stim_onset_nidq_s`, `condition_id`, `trial_valid`
- `stim_onset_imec_s` — JSON string mapping `{probe_id: t_imec_seconds}`, must include key `imec0`

Trials-table columns written (全部由本方法创建):

| 列名 | 类型 | 说明 |
|------|------|------|
| `start_time` | float64 | `stim_onset_imec_s["imec0"]` (IMEC seconds) |
| `stop_time` | float64 | `start_time + onset_time_ms / 1000.0` (IMEC seconds) |
| `stim_onset_time` | float64 | 同 `start_time`，明确语义："Stimulus onset time in IMEC seconds (reference probe imec0)" |
| `stim_onset_nidq_s_diag` | float64 | `stim_onset_nidq_s` 原始值，保留用于审计与反算 |
| `stim_onset_imec_{probe_id}` | float64 | 每个 probe_id 一列，从 JSON 的同名 key 读取（多 probe 场景） |
| `trial_id`, `condition_id`, `trial_valid` | int / int / bool | 直接映射 |
| `stim_index`, `onset_time_ms`, `offset_time_ms` | 按 DataFrame 列存在时写入 | VariableChanges 来源 |

处理步骤:

1. 若 `self._nwbfile is None` 则 raise `RuntimeError`
2. 校验 required columns；缺失则 raise `ValueError`
3. 逐行解析 `stim_onset_imec_s` JSON；若任意行无 `imec0` key 则 raise `ValueError`
4. 从第一行 JSON 抽取 probe_id 集合，在首次调用时声明 `stim_onset_imec_{probe_id}` 等 per-probe 列（pynwb 要求 `add_trial_column` 必须在首次 `add_trial` 前完成）
5. 逐行 `add_trial()`，所有时间列用 IMEC 秒；`stim_onset_nidq_s_diag = row["stim_onset_nidq_s"]`
6. 若某行 JSON 缺失任一声明过的 probe_id，raise `ValueError`（所有 trial 必须列出同一组 probe）

### add_sync_tables

**Purpose.** 把 `sync/` 目录里的时钟对齐表（IMEC↔NIDQ 线性拟合 + 光电二极管校准 + 事件码三元组）序列化进 `nwbfile.scratch["sync_tables"]`，让下游消费者在原始 SpikeGLX bin 被删除之后依然能复算或审计同步（E1.3）。

**Signature.**

```python
def add_sync_tables(
    self,
    nwbfile: NWBFile,
    sync_dir: Path,
    *,
    behavior_events: pd.DataFrame | None = None,
) -> dict[str, int | bool]: ...
```

**Scratch 条目.**

- name: `"sync_tables"`
- data: `json.dumps(payload, indent=2, default=str)`
- description: `"Clock alignment and photodiode calibration tables for reproducing sync without raw bins. JSON payload with keys: imec_nidq (per-probe linear fit t_nidq = a*t_imec + b), photodiode (per-trial PD-detected stim onsets in NIDQ seconds), event_codes (per-trial event-code triples used for BHV<->NIDQ matching). All times in NIDQ seconds unless noted."`

**JSON payload shape.**

```json
{
  "imec_nidq": {
    "imec0": {"a": 1.000001, "b": -0.003, "residual_ms": 0.012, "n_repaired": 0},
    "imec1": {...}
  },
  "photodiode": [
    {"trial_index": 0, "pd_onset_nidq_s": 12.345, "ec_onset_nidq_s": 12.320, "latency_s": -0.025},
    ...
  ],
  "event_codes": [
    {"trial_index": 0, "start_nidq_s": 10.0, "stim_onset_nidq_s": 12.32, "reward_nidq_s": null},
    ...
  ]
}
```

**数据来源.**

- `imec_nidq`: `Path.glob("*_imec_nidq.json")`，probe_id 从文件 stem 截断 `_imec_nidq` 得到，内容原样透传。
- `photodiode`: `behavior_events[["pd_onset_nidq_s", "ec_onset_nidq_s"]]`；只收录两列都非空的 trial，`latency_s = ec - pd`。
- `event_codes`: `behavior_events[["onset_nidq_s", "stim_onset_nidq_s", "reward_nidq_s"]]`；缺列或 NaN 写成 `null`。

**幂等性.** 若 `nwbfile.scratch` 已存在 `"sync_tables"` key，直接返回 `{idempotent_skipped: True}`，不覆写。

**失败处理.** 三个来源任一缺失时，对应 section 写成 `{"_missing": true}` 哨兵，不 raise；写 WARNING 日志。目的是让 export Phase 1 在部分同步失败时仍能产出可用的 NWB。

### Reference probe rationale（设计锁定）

- Reference probe 硬编码为 `imec0` —— 模块常量 `_REFERENCE_PROBE = "imec0"`，**不暴露为配置键**。
- 理由：多 probe session 中的 `stim_onset_imec_s` 已逐 probe 分别记录；reference 只是挑一个 anchor 让 `start_time` 与 `spike_times` 同一时钟。选择 `imec0` 确保单源且零歧义。
- 下游若需用其他 probe 的时间，读 `stim_onset_imec_{probe_id}` 列，禁止重定义 reference。

### add_lfp
1. raise `NotImplementedError("LFP export is not yet implemented. Reserved for future lfp_process stage integration.")`

### add_eye_tracking
1. 若 `self._nwbfile is None` 则 raise `RuntimeError`
2. 通过 `BHV2Parser(session.bhv_file).get_analog_data("Eye")` 逐 trial 读取眼位数据
3. 对每个 trial，在 stim onset 窗口内提取 (x, y) 眼位序列
4. 拼接为连续时间序列 `eye_track: np.ndarray`（shape: n_timepoints × 2）和对应 `timestamps`
5. 创建 `SpatialSeries(name="right_eye_position", data=eye_track, timestamps=timestamps, unit="degrees", reference_frame="center of screen")`
6. 创建 `EyeTracking` 容器，添加到 `processing["behavior"]`

### add_ks4_sorting
1. 若 `self._nwbfile is None` 则 raise `RuntimeError`
2. 从 `sorter_output_path` 加载 KS4 完整结果：`spike_times.npy`, `spike_templates.npy`, `amplitudes.npy`, `params.py`
3. 写入 `processing/ecephys/kilosort4_{probe_id}`：spike_times、spike_templates、amplitudes、KS4 参数元数据
4. 使用 NeuroConv `KiloSortSortingInterface` 或手动 pynwb 写入

### append_raw_data
1. 以 `NWBHDF5IO(nwb_path, 'r+')` 打开已有 NWB 文件
2. 使用 NeuroConv `SpikeGLXConverterPipe` 追加 AP + LF + NIDQ 原始数据
3. 压缩参数：Blosc zstd clevel=6，chunk_shape=[40000, 64]，buffer_shape=[200000, 384]
4. 流式写入（chunk_size 控制），不一次性加载整个 AP 数据到内存
5. **progress_callback**（可选 `Callable[[str, float], None]`）：每写完一个 chunk 调用一次，`fraction = bytes_written_so_far / total_bytes_to_write`（跨 AP/LF/NIDQ 全局归一化），`message = f"append_{stream}_{probe_id} chunk {i}/{n}"`。`None` 时完全不调。
6. **verify 内联**：`verify_policy="full"` 时 `append_raw_data` 在写完后自动调 `verify_nwb(nwb_path, progress_callback=...)`；verify 阶段的 fraction 接续 append（append 占 0-0.7，verify 占 0.7-1.0）。

#### NIDQ stream (session-level, single TimeSeries)

NIDQ 独立于每个 probe，以**单个 session 级 `TimeSeries`** 形式写入 `nwbfile.acquisition["NIDQ_raw"]`。该 TimeSeries 保留所有通道的原始 int16 数据（不解码数字字），并在 `description` 中携带下游 reader 解码所需的元数据。

**约定**：

| 字段 | 值 | 来源 |
|------|----|------|
| `name` | `"NIDQ_raw"` | 固定 |
| `data` | 原始 `int16`，全部通道，shape `(n_samples, n_channels)` | `SpikeGLXLoader.load_nidq()` |
| `rate` | `float(niSampRate)` | `.nidq.meta` |
| `starting_time` | `0.0` | 固定（NIDQ 作为同步参考系的 t=0） |
| `unit` | `"V"` | 固定 |
| `conversion` | `float(niAiRangeMax) / 32768.0` | `.nidq.meta` |
| `description` | `" \| "`-拼接的 key=value 字符串 | 见下方 |

**Description 格式**（必须**字面包含**以下 4 个 key 前缀，便于下游 reader 用子串匹配定位）：

- `niAiRangeMax=<value>` — 模拟增益最大值（V）
- `niSampRate=<value>` — NIDQ 采样率（Hz）
- `event_bits=<list>` — 事件码占用的 digital bit 索引（从 `session.config.sync.event_bits`；默认 `[1,2,3,4,5,6,7]`）
- `sync_bit=<int>` — 同步脉冲 bit 索引（从 `session.config.sync.nidq_sync_bit`；默认 `0`）

可选字段（meta 存在时追加）：`snsMnMaXaDw`、`niMNGain`、`niMAGain`。

**行为约定**：

1. **可选**：若 session 目录无 `*.nidq.bin` / `*.nidq.meta`（`SpikeGLXDiscovery.discover_nidq()` 抛 `DiscoverError`），**仅发 WARNING 日志并跳过**，不 raise。返回值中 `stream_names` 不含 `"NIDQ_raw"`。
2. **幂等**：若 `nwbfile.acquisition` 已含 `"NIDQ_raw"`，直接跳过（不重写、不抛错），返回值中 `stream_names` 也不含它。
3. **加载失败**：若 `load_nidq` 本身抛异常（如 meta 缺 `niSampRate` / `niAiRangeMax`），同样发 WARNING 跳过，保证整体 append 过程不被 NIDQ 问题阻断 AP/LF 写入。
4. **通道完整**：NIDQ TimeSeries 写入所有保存通道（不抽取 sync bit，不展开 event bits）。下游 reader 负责用 `description` 中的 `sync_bit` / `event_bits` 在读取时按需解码。
5. **流式写入**：使用与 AP 相同的 `SpikeGLXDataChunkIterator` + `H5DataIO`，chunk_shape 自动裁剪到 `(min(40000, n_samples), n_channels)`。

**与 AP/LF 的关系**：NIDQ 块位于 per-probe 循环之后、`io.write(nwbfile)` 之前，**不影响** AP/LF 路径的写入逻辑。即使 NIDQ 完全缺失，AP/LF 仍应正常写入。

### verify_nwb
1. 以 `NWBHDF5IO(nwb_path, 'r')` 打开
2. **Phase 1 验证**（轻量数据）：检查 units 表行数、trials 表行数、eye tracking 存在性、KS4 sorting 存在性
3. **Phase 3 验证**（原始数据，仅在 append_raw_data 完成后）：逐 chunk 比较 AP/LF 数据与原始 .bin 文件
4. 返回验证报告 dict（含 checksum、n_samples、通过/失败状态）
5. **progress_callback**（可选 `Callable[[str, float], None]`）：每比较完一个 chunk 调用一次，`message = f"verify_{stream}_{probe_id} chunk {i}/{n}"`，`fraction` 单调递增到 1.0。在 `append_raw_data` 内联调用时，fraction 由调用方按 0.7-1.0 线性映射。

### write
1. 若 `self._nwbfile is None` 则 raise `RuntimeError("call create_file() before write()")`
2. 确保 `output_path.parent` 目录存在（`mkdir(parents=True, exist_ok=True)`）
3. 以 `pynwb.NWBHDF5IO(self.output_path, mode='w')` 打开，调用 `io.write(self._nwbfile)`
4. 返回 `self.output_path`

## 5. 公开 API 与可配参数

```python
class NWBWriter:
    """Assembles and writes a DANDI-compliant NWB 2.x file for one session.

    All probes are written into a single NWB file. The output filename is
    expected to be {session.session_id.canonical()}.nwb (constructed by the
    caller / runner). Internally, NWBFile.session_id is also populated with
    this canonical string. LFP export is reserved for a future release and
    raises NotImplementedError.

    Args:
        session: Session object providing subject metadata, session_id,
                 probe list (with target_area populated), and path information.
        output_path: Destination path for the output .nwb file. Callers
                     SHOULD construct this as
                     ``output_dir / f"{session.session_id.canonical()}.nwb"``.
    """

    def __init__(self, session: Session, output_path: Path) -> None: ...

    def create_file(self) -> pynwb.NWBFile:
        """Create an in-memory NWBFile with session and subject metadata.

        Sets NWBFile.session_id = session.session_id.canonical() and
        prepends the canonical string to NWBFile.session_description so
        the identifier is discoverable via DANDI search.
        Reads session_start_time from the first probe's .ap.meta fileCreateTime.
        Must be called before add_probe_data(), add_trials(), or write().

        Raises:
            ValueError: If any DANDI-required subject field is empty.
        """

    def add_probe_data(
        self,
        probe: ProbeInfo,
        analyzer: si.SortingAnalyzer,
        rasters: dict | None = None,
    ) -> None:
        """Add electrode group, electrodes, and units for one probe.

        The ElectrodeGroup's ``location`` and every electrode row's
        ``location`` column are set to ``probe.target_area``, which is
        injected by the discover stage from ``session.probe_plan``. In
        multi-probe sessions each ElectrodeGroup therefore carries its
        own independent brain region label.

        Args:
            probe: ProbeInfo with channel_positions and target_area populated
                   (target_area must be a non-empty, non-"unknown" string;
                   this invariant is enforced by the discover stage).
            analyzer: SortingAnalyzer with waveforms, templates, unit_locations computed.
            rasters: Optional dict mapping unit_id → np.ndarray (n_valid_trials, n_bins).

        Raises:
            RuntimeError: If create_file() has not been called.
            ValueError: If required analyzer extensions are missing.
        """

    def add_trials(self, behavior_events: pd.DataFrame) -> None:
        """Populate the NWB trials table from a behavior events DataFrame.

        Anchors start_time / stop_time / stim_onset_time to IMEC seconds using
        the hardcoded reference probe ``imec0`` (module constant
        ``_REFERENCE_PROBE``). Multi-probe sessions gain per-probe columns
        ``stim_onset_imec_{probe_id}`` and retain the original NIDQ value as
        the diagnostic column ``stim_onset_nidq_s_diag``.

        Raises:
            RuntimeError: If create_file() has not been called.
            ValueError: If required DataFrame columns are missing, if the
                ``stim_onset_imec_s`` JSON cannot be parsed, or if any row
                lacks the reference probe ``imec0``.
        """

    def add_lfp(self, probe: ProbeInfo, lfp_data: np.ndarray) -> None:
        """Reserved interface for LFP export — not yet implemented.

        Raises:
            NotImplementedError: Always.
        """

    def add_eye_tracking(
        self,
        bhv_parser: BHV2Parser,
        behavior_events: pd.DataFrame,
    ) -> None:
        """Add eye tracking SpatialSeries to processing/behavior/EyeTracking.

        Args:
            bhv_parser: BHV2Parser instance for reading analog eye data.
            behavior_events: Trial events DataFrame with stim onset times.

        Raises:
            RuntimeError: If create_file() has not been called.
        """

    def add_ks4_sorting(
        self,
        probe_id: str,
        sorter_output_path: Path,
    ) -> None:
        """Write KS4 complete sorting results to processing/ecephys.

        Writes spike_times, spike_templates, amplitudes, and KS4 params.

        Args:
            probe_id: Probe identifier.
            sorter_output_path: Path to KS4 sorter_output/ directory.

        Raises:
            RuntimeError: If create_file() has not been called.
        """

    def append_raw_data(
        self,
        session: Session,
        nwb_path: Path,
    ) -> None:
        """Append raw AP+LF+NIDQ data to existing NWB via r+ mode (Phase 3).

        Uses NeuroConv SpikeGLXConverterPipe with Blosc zstd compression.
        Streaming write — does not load entire AP into memory.

        Args:
            session: Session with probe paths.
            nwb_path: Path to existing NWB file to append to.
        """

    def verify_nwb(self, nwb_path: Path) -> dict:
        """Verify NWB file contains all expected data.

        Returns:
            Dict with verification results (passed/failed per section).
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
| `create_file` 正常 | `test_nwbfile_session_id_is_canonical` — 写盘后用 NWBHDF5IO 读回 | `nwbfile.session_id == session.session_id.canonical()` |
| `create_file` 正常 | `test_nwbfile_session_description_contains_canonical` | `session.session_id.canonical()` 作为子串出现在 `nwbfile.session_description` 中（实现约定为开头） |
| `create_file` 正常 | NWBFile.subject.subject_id 匹配 SubjectConfig | 字段正确映射 |
| `create_file` 正常 | session_start_time 为 aware datetime | 不为 naive datetime |
| `create_file` 错误 | subject.subject_id 为空字符串 | raise `ValueError` 含字段名提示 |
| `create_file` 错误 | subject.species 为空字符串 | raise `ValueError` |
| `create_file` 错误 | subject.sex 为空字符串 | raise `ValueError` |
| `create_file` 错误 | subject.age 为空字符串 | raise `ValueError` |
| `add_probe_data` 正常 | 合法 probe + analyzer（含所有扩展） | NWBFile 含对应 ElectrodeGroup |
| `add_probe_data` 正常 | units table 含 spike_times, probe_id | 列存在且值类型正确 |
| `add_probe_data` 正常 | units table 含 waveform_mean（2D array） | shape 为 (n_samples, n_channels) |
| `add_probe_data` 正常 | `test_electrode_group_location_from_target_area` — probe.target_area="MSB" | 对应 `ElectrodeGroup.location == "MSB"` 且 electrodes 行 `location == "MSB"` |
| `add_probe_data` 正常 | `test_multi_probe_electrode_groups_independent_locations` — probe0.target_area="MSB"、probe1.target_area="V4" | 两个 ElectrodeGroup 的 location 分别为 "MSB" 与 "V4"，electrodes 表按 probe_id 分组后 location 列值一致 |
| `add_probe_data` 正常 | units table 含 is_visual 列 | bool 类型 |
| `add_probe_data` 正常 | slay_score 从 slay_scores.json 读取 | slay_score 填 np.nan 若 JSON 不存在 |
| `add_probe_data` 正常 | 两个 probe 依次调用 | electrodes table 含两组 probe_id |
| `add_probe_data` 错误 | create_file 未调用 | raise `RuntimeError` |
| `add_probe_data` 错误 | analyzer 缺少 waveforms 扩展 | raise `ValueError` 含扩展名 |
| `add_probe_data` 错误 | analyzer 缺少 unit_locations 扩展 | raise `ValueError` |
| `add_trials` 正常 | 合法 DataFrame，3 条 trial | trials table 含 3 行，字段正确 |
| `add_trials` 正常 | trials 含 stim_name、onset_time_ms、offset_time_ms、dataset_name | 扩展列存在 |
| `add_trials` 错误 | create_file 未调用 | raise `RuntimeError` |
| `add_trials` 错误 | DataFrame 缺少 trial_id 列 | raise `ValueError` |
| `add_eye_tracking` 正常 | 合法 bhv_parser + behavior_events | processing/behavior/EyeTracking 存在 |
| `add_eye_tracking` 正常 | SpatialSeries shape 为 (n, 2) | data 维度正确 |
| `add_eye_tracking` 错误 | create_file 未调用 | raise `RuntimeError` |
| `add_ks4_sorting` 正常 | 合法 sorter_output_path | processing/ecephys/kilosort4_{probe_id} 存在 |
| `add_ks4_sorting` 正常 | 含 spike_templates 和 amplitudes | 数据完整 |
| `verify_nwb` 正常 | 完整 NWB | 返回全部 passed |
| `verify_nwb` 正常 | 缺少 eye tracking | 返回 eye_tracking: failed |
| `add_lfp` | 任何输入 | 始终 raise `NotImplementedError`，message 含 "LFP" |
| `write` 正常 | create_file 已调用，output_path 父目录不存在 | 自动创建父目录，写出文件，返回 output_path |
| `write` 正常 | 写出的文件可被 pynwb.NWBHDF5IO 打开 | 读取无异常 |
| `write` 错误 | create_file 未调用 | raise `RuntimeError` |
| 集成 | create_file → add_probe_data（2 probe，各自 target_area）→ add_trials → write → 重新读取 | 电极组数为 2，两个 ElectrodeGroup 的 location 分别匹配对应 target_area；units 含两组 probe_id；顶层 `session_id` 为 canonical |

## 7. 依赖

- `pynpxpipe.core.session` — `Session`, `SubjectConfig`, `SessionID`, `ProbeInfo`
- `pynpxpipe.io.spikeglx` — `SpikeGLXDiscovery`（读取 meta 的 fileCreateTime）, `SpikeGLXLoader`
- `pynpxpipe.io.bhv` — `BHV2Parser`（眼动数据读取）
- 标准库：`pathlib.Path`, `uuid`, `datetime`
- 第三方：`pynwb`（>= 2.8）, `spikeinterface`, `numpy`, `pandas`, `neuroconv`（SpikeGLXConverterPipe, KiloSortSortingInterface）

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
| 文件名与 `NWBFile.session_id` 统一由 `SessionID.canonical()` 驱动 | MATLAB 以 gate 目录名作为隐含标识；Python 引入 `{date}_{subject}_{experiment}_{region}` 规范化 ID，作为 DANDI 归档与多 session 比对的单一真源 |
| `ElectrodeGroup.location` 取自 `probe.target_area`（probe_plan 注入） | MATLAB 无 target_area 概念；Python 要求用户在 UI 预声明 `probe_plan`，discover 时注入 ProbeInfo，export 时作为 NWB 电极组脑区的唯一来源，多 probe 场景下每组独立 |
