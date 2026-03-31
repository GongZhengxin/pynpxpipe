# pynpxpipe 架构设计文档

> 版本：0.1.0  
> 日期：2026-03-31  
> 依据：CLAUDE.md + docs/legacy_analysis.md

---

## 1. Session 生命周期

Session 是贯穿整个 pipeline 的核心状态对象。从创建到写出 NWB 文件，经历以下状态流转：

```
Session.create(session_dir, bhv_file, subject, output_dir)
        │
        ▼
  [discover]          checkpoint: {n_probes, probe_ids, nidq_found}
        │
        ▼
  [preprocess]        checkpoint per probe: {preprocessed_recording_path}
        │
        ▼
  [sort]              checkpoint per probe: {sorting_result_path, n_units}
        │
        ▼
  [synchronize]       checkpoint: {sync_tables_path, behavior_events_path, n_trials}
        │
        ▼
  [curate]            checkpoint per probe: {curated_path, n_units_before, n_units_after}
        │
        ▼
  [postprocess]       checkpoint per probe: {analyzer_path, n_units}
        │
        ▼
  [export]            checkpoint: {nwb_path, file_size_gb}
        │
        ▼
  Session 完成（所有 stage checkpoint 均存在）
```

**checkpoint 存储位置**：`{output_dir}/checkpoints/{stage_name}[_{probe_id}].json`

Pipeline 启动时逐条检查 checkpoint 文件，已完成的 stage 自动跳过，实现断点续跑。

---

## 2. 每个 Stage 的详细设计

### 2.1 discover

**输入**：
- `session.session_dir` — SpikeGLX 录制数据根目录
- `session.bhv_file` — MonkeyLogic BHV2 文件路径

**处理逻辑**：
1. 扫描 `session_dir`，匹配 `imec{N}` 子目录（支持 SpikeGLX 标准输出结构）
2. 对每个 probe 目录：
   - 验证 `.ap.bin` + `.ap.meta` 文件存在
   - 读取 `.ap.meta` 提取采样率（`imSampRate`）、通道数（`nSavedChans`）、探针型号（`imProbeOpt`/`imProbeSN`）
   - 校验 bin 文件大小与 meta 中 `fileSizeBytes` 声明一致（防截断文件）
   - 验证 `.lf.bin` + `.lf.meta` 是否存在（记录但不强制要求）
3. 扫描 NIDQ 数据（`*.nidq.bin` + `*.nidq.meta`），验证存在
4. 验证 BHV2 文件可读（读取文件头部魔数）
5. 构建 `ProbeInfo` 列表，写入 `session.probes`
6. 将 session 元信息快照写入 `{output_dir}/session_info.json`

**输出**：
- `session.probes` — 填充完整的 `list[ProbeInfo]`
- `{output_dir}/session_info.json` — session 元信息快照（人类可读）

**checkpoint 内容**：
```json
{
  "stage": "discover",
  "completed_at": "2026-03-31T10:00:00",
  "n_probes": 2,
  "probe_ids": ["imec0", "imec1"],
  "nidq_found": true,
  "lf_found": {"imec0": true, "imec1": false}
}
```

**内存管理**：仅读取 meta 文件（纯文本，KB 级）。无内存风险。

---

### 2.2 preprocess

**输入**：
- `session.probes` — ProbeInfo 列表
- `{session_dir}/{probe_id}/*.ap.bin` — 原始 AP 数据（lazy loading，不读入内存）
- `config.pipeline.preprocess` — 滤波参数、坏道检测参数、CMR 参数、运动校正参数
- `config.pipeline.resources` — n_jobs, chunk_duration

**处理逻辑**（对每个 probe 串行）：
1. 用 `si.read_spikeglx()` 以 lazy 方式加载 AP recording（Recording 对象仅存指针）
2. 坏道检测：`si.detect_bad_channels(method="coherence+psd")`（基于 chunk 计算 PSD，不加载整体）
3. 剔除坏道：`recording.remove_channels(bad_channels)`
4. Bandpass filter：`si.bandpass_filter(freq_min=300, freq_max=6000)` — 参数从配置读取
5. Common median reference：`si.common_reference(reference="global", operator="median")`
6. 运动校正：`si.correct_motion(preset="nonrigid_accurate")` — 可在配置中关闭（`method: null`）
7. 将预处理后的 recording 保存为 Zarr 格式到 `{output_dir}/preprocessed/{probe_id}/`
8. 写 per-probe checkpoint；`del recording`；`gc.collect()`

**输出**：
- `{output_dir}/preprocessed/{probe_id}/` — Zarr 格式预处理 recording（lazy 可加载）

**checkpoint 内容**：
```json
{
  "stage": "preprocess",
  "probe_id": "imec0",
  "completed_at": "2026-03-31T11:30:00",
  "bad_channels": [32, 45, 67],
  "recording_path": "preprocessed/imec0",
  "n_channels_after": 381
}
```

**内存管理**：
- SpikeInterface lazy recording 机制：数据按 chunk 流式读取，chunk 大小由 `chunk_duration` 控制
- 坏道检测按 chunk 逐块计算 PSD，不加载全体数据
- Zarr 写入采用压缩格式，磁盘占用约为原始 bin 的 30-50%
- 每个 probe 处理完立即 `del recording` + `gc.collect()`

---

### 2.3 sort

**输入**：
- `{output_dir}/preprocessed/{probe_id}/` — Zarr 预处理 recording
- `config.sorting` — mode, sorter.name, sorter.params 或 import.path

**处理逻辑**（对每个 probe 串行，始终串行）：

**本地运行模式**（`mode: local`）：
1. 从 Zarr 加载预处理 recording
2. 调用 `si.run_sorter(sorter_name, recording, output_folder="{output_dir}/sorting/{probe_id}")`
3. 验证 sorting 结果：spike_times 非空，cluster 数合理（>0）
4. `del recording`；`gc.collect()`（GPU 内存由 Kilosort 自行管理，处理完探针后释放）

**导入外部结果模式**（`mode: import`）：
1. 读取 `config.sorting.import.path[probe_id]` 指定的 Kilosort 输出目录
2. 用 `si.read_sorter_folder()` 加载 sorting 结果
3. 验证结果完整性（spike_times.npy, spike_clusters.npy 等）
4. 保存到标准位置 `{output_dir}/sorting/{probe_id}/`

**输出**：
- `{output_dir}/sorting/{probe_id}/` — SpikeInterface Sorting 对象（文件夹格式）

**checkpoint 内容**：
```json
{
  "stage": "sort",
  "probe_id": "imec0",
  "completed_at": "2026-03-31T14:00:00",
  "sorter": "kilosort4",
  "mode": "local",
  "n_units": 142,
  "sorting_path": "sorting/imec0"
}
```

**内存管理**：
- GPU 内存由 Kilosort 管理，完成后自动释放
- 严格串行（不允许并行 sort），确保同一时刻只有一个 probe 占用 GPU
- Zarr recording 通过 lazy 加载，批次大小由 Kilosort 的 `batch_size` 控制

---

### 2.4 synchronize

**输入**：
- `{session_dir}/*.nidq.bin` + `*.nidq.meta` — NIDQ 数字通道（sync bit 和事件码）和模拟通道（photodiode）
- `{session_dir}/{probe_id}/{probe_id}.ap.bin` — 每个 probe 的 AP sync 脉冲（仅 sync 通道）
- `session.bhv_file` — BHV2 行为文件
- MATLAB Engine（BHV2 解析需要；通过 Python 调用 MATLAB 引擎读取 .bhv2）
- `config.pipeline.sync` — sync_bit, event_bits, max_time_error_ms, photodiode_channel_index,
  monitor_delay_ms, stim_onset_code, imec_sync_code, generate_plots

**处理逻辑**：

**步骤 1 — IMEC↔NIDQ 时钟对齐**（对每个 probe 循环）：
1. 从 AP 数据数字通道提取 sync 脉冲上升沿时间序列
2. 从 NIDQ 数字通道提取对应 sync 脉冲上升沿时间序列
3. 验证双方 sync 事件数量一致
4. 线性回归建立校正函数：`t_nidq = a × t_imec + b`，验证残差 < `max_time_error_ms`
5. 输出：每个 probe 的 `{a, b, residual_ms}`

**步骤 2 — BHV2↔NIDQ 事件匹配**：
1. 解析 BHV2 文件（通过 MATLAB 引擎），提取 trial 事件码序列和时间戳
2. 同时提取 BHV2 元信息：DatasetName、刺激参数等
3. 从 NIDQ 数字通道解码事件码序列及时间
4. 按 trial 数量和 onset 事件码匹配；自动修复 trial_start_bit 映射错误
5. 验证逐 trial onset 数量一致性；差异在 trial_count_tolerance 范围内则自动截断
6. 输出：trial 级事件对应表

**步骤 3 — Photodiode 校准**：
1. 从 NIDQ 模拟通道读取 photodiode 信号（通道索引由 `sync.photodiode_channel_index` 指定）
2. int16 → 电压转换（量程从 `nidq.meta` 的 `niAiRangeMax` 字段读取，不使用 fallback 常数）
3. 重采样到 1ms 分辨率（`resample_poly`，比率从采样率精确计算）
4. 以数字 stim onset 为参考提取 [-10ms, +100ms] 窗口，逐 trial z-score 归一化
5. 计算全局阈值（跨 trial 共享）：`0.1×baseline_mean + 0.9×stimulus_period_mean`
6. 逐 trial 首次超阈值检测，确定 `onset_latency`（相对数字触发的延迟 ms）
7. 加 `monitor_delay_ms` 校正（从配置读取，60Hz 约 -5ms）
8. `np.interp` 将校准后的 onset 时间从 NI 时钟转换到 IMEC 时钟（对每个 probe 各一个插值函数）
9. 边界情况：`onset_latency < 0` 记警告、信号方差过低 raise `SyncError`、窗口越界跳过该 trial
10. 输出：校准后的 stimulus onset 时间序列（IMEC 时钟，每 probe 一份）

**步骤 4 — 诊断图生成**（由 `sync.generate_plots` 控制，默认 true）：
- 调用 `io/sync_plots.py` 生成全部诊断图，保存到 `{output_dir}/sync/figures/`
- 诊断图列表：`sync_drift_{probe_id}.png`、`event_alignment.png`、
  `photodiode_heatmap.png`、`onset_latency_histogram.png`、
  `photodiode_mean_signal.png`、`sync_pulse_interval.png`
- matplotlib 为可选依赖；若缺失则跳过图表生成，记录警告

**输出**：
- `{output_dir}/sync/sync_tables.json` — 每个 probe 的时间校正参数 `{a, b, residual_ms}`
- `{output_dir}/sync/behavior_events.parquet` — 统一时间轴上的行为事件表
- `{output_dir}/sync/figures/` — 诊断图（若 `generate_plots=true`）

**behavior_events.parquet 列**：
| 列名 | 类型 | 说明 |
|------|------|------|
| trial_id | int | BHV2 trial 编号（1-indexed） |
| onset_nidq_s | float | trial onset 的 NIDQ 时间（秒） |
| stim_onset_nidq_s | float | stimulus onset 的 NIDQ 时间（秒） |
| stim_onset_imec_s | str→float | 各 probe 上的 IMEC 时钟精确 onset（JSON 字符串 `{probe_id: float}`） |
| trial_valid | bool | 眼动验证是否通过（预留，postprocess 阶段填写） |
| condition_id | int | 刺激条件编号 |
| dataset_name | str | BHV2 DatasetName 字段（实验名称） |

**checkpoint 内容**：
```json
{
  "stage": "synchronize",
  "completed_at": "2026-03-31T14:30:00",
  "sync_tables_path": "sync/sync_tables.json",
  "behavior_events_path": "sync/behavior_events.parquet",
  "n_trials": 480,
  "sync_residuals_ms": {"imec0": 0.8, "imec1": 1.2},
  "photodiode_calibrated": true,
  "monitor_delay_ms": -5,
  "dataset_name": "exp_20260101"
}
```

**内存管理**：
- NIDQ 数字通道仅提取 1-2 个 bit 通道（不全量加载模拟通道），内存极小
- Photodiode 模拟通道按 trial 窗口分块读取，不一次性加载全长信号
- BHV2 解析结果按 trial 存储，不预分配全量眼动矩阵
- sync 脉冲时间序列为稀疏数组（每秒约 1 个脉冲），内存可忽略

---

### 2.4a synchronize 子模块拆分

synchronize stage 内部模块划分（每个子模块可独立测试）：

- **`stages/synchronize.py`** — 主调度，按顺序调用下面的子模块，管理 checkpoint
- **`io/sync/imec_nidq_align.py`** — 第一级：IMEC↔NIDQ 时钟对齐
  - 输入：AP 数字通道数据、NIDQ 数字通道数据、各自采样率
  - 输出：`SyncResult(a: float, b: float, residual_ms: float)`
  - 可独立调用和测试，无外部依赖
- **`io/sync/bhv_nidq_align.py`** — 第二级：BHV2↔NIDQ 事件匹配
  - 输入：BHV2 文件路径、NIDQ 数字事件码序列及时间、config 事件码定义
  - 输出：`TrialAlignment(trial_events_df: pd.DataFrame, dataset_name: str, bhv_metadata: dict)`
  - 依赖 MATLAB 引擎（MATLAB Engine API for Python）
- **`io/sync/photodiode_calibrate.py`** — 第三级：Photodiode 校准
  - 输入：NIDQ 模拟信号（int16 array）、数字 stim onset 时间序列、sync 校正函数参数
  - 输出：`CalibratedOnsets(onset_times_imec_ms: np.ndarray, onset_latencies: np.ndarray, quality_flags: np.ndarray)`
  - `quality_flags` 含义：0=正常，1=latency 为负，2=窗口越界（跳过），3=信号方差异常
- **`io/sync_plots.py`** — 诊断图生成
  - 输入：以上三个子模块的输出 + 输出目录路径
  - 输出：PNG 文件到指定目录
  - matplotlib 为可选依赖（`try: import matplotlib; except ImportError: return`）

---

### 2.5 curate

**输入**：
- `{output_dir}/sorting/{probe_id}/` — Sorting 结果
- `{output_dir}/preprocessed/{probe_id}/` — 预处理 recording（quality metrics 需要波形）
- `config.pipeline.curation` — 各 quality metric 的阈值

**处理逻辑**（对每个 probe 串行）：
1. 加载 Sorting 结果
2. 创建轻量 `SortingAnalyzer`（仅注册 quality metrics 所需扩展）
3. 计算扩展序列：`random_spikes` → `waveforms`（小批量）→ `templates` → `noise_levels`
4. 计算 quality metrics：`si.compute_quality_metrics()`
   - `isi_violation_ratio`（ISI 违反比例）
   - `amplitude_cutoff`（振幅截断估计）
   - `presence_ratio`（存在比例）
   - `snr`（信噪比）
5. 按配置阈值筛选 good units，生成 `good_unit_ids` 列表
6. 保存 quality_metrics 表格和 curated sorting
7. `del analyzer`；`gc.collect()`

**输出**：
- `{output_dir}/curated/{probe_id}/` — Curated Sorting 对象
- `{output_dir}/curated/{probe_id}/quality_metrics.csv` — 所有 unit 的 quality metrics

**checkpoint 内容**：
```json
{
  "stage": "curate",
  "probe_id": "imec0",
  "completed_at": "2026-03-31T15:00:00",
  "n_units_before": 142,
  "n_units_after": 87,
  "curated_path": "curated/imec0"
}
```

**内存管理**：
- SortingAnalyzer 仅计算必要扩展（不计算完整 waveforms，仅用少量 random spikes）
- quality metrics 计算按 unit 迭代，不同时持有所有 unit 的波形

---

### 2.6 postprocess

**输入**：
- `{output_dir}/curated/{probe_id}/` — Curated sorting
- `{output_dir}/preprocessed/{probe_id}/` — 预处理 recording
- `{output_dir}/sync/behavior_events.parquet` — 行为事件（SLAY 所需）
- `config.sorting.analyzer` — waveform 提取参数

**处理逻辑**（对每个 probe 串行）：
1. 创建完整 `SortingAnalyzer`（绑定 curated sorting + preprocessed recording）
2. 按顺序计算扩展（每个扩展完成后可释放中间结果）：
   - `random_spikes`（均匀采样每个 unit 的 spike，限制数量）
   - `waveforms`（提取波形，ms_before/ms_after 从配置读取）
   - `templates`（计算平均/标准差模板）
   - `unit_locations`（空间位置估计，monopolar_triangulation 方法）
   - `template_similarity`（cosine similarity，用于后续合并参考）
3. SLAY 计算：
   - 加载 `behavior_events.parquet`，取 `stim_onset_nidq_s` 列
   - 对每个 good unit，以 stim onset 为参考点截取 spike，计算 SLAY 分数
   - 将 SLAY 分数写入 analyzer 的自定义扩展表
4. 眼动验证（由 `config.postprocess.eye_validation.enabled` 控制，默认 true）：
   - 加载 BHV2 眼动数据（`AnalogData.Eye`）和固视窗口参数（中心坐标、半径）
   - 逐 trial 分块处理（禁止预分配全量眼动矩阵）：
     - 以 stim onset 时间截取眼动信号窗口（-50ms 至 +200ms）
     - 计算窗口内眼位与固视中心的欧式距离
     - 若距离 ≤ 固视窗口半径（来自 BHV2 fixation window 参数），标记 `trial_valid=True`
     - 否则标记 `trial_valid=False`，记录偏离时刻
   - 将 `trial_valid` 列写入 `behavior_events.parquet`（原地更新）
5. 保存完整 analyzer 到磁盘；`del analyzer`；`gc.collect()`

**输出**：
- `{output_dir}/postprocessed/{probe_id}/` — 完整 SortingAnalyzer
  - 含：waveforms, templates, unit_locations, template_similarity, slay_scores

**checkpoint 内容**：
```json
{
  "stage": "postprocess",
  "probe_id": "imec0",
  "completed_at": "2026-03-31T17:00:00",
  "analyzer_path": "postprocessed/imec0",
  "n_units": 87,
  "slay_computed": true,
  "eye_validation_computed": true
}
```

**内存管理**：
- waveforms 计算时 SpikeInterface 按 chunk 流式提取（由 `chunk_duration` 控制）
- `random_spikes` 限制每 unit 最多 500 个 spike，控制总波形量
- SLAY 计算按 unit 迭代，不同时持有所有 unit 的 spike train
- 眼动验证按 trial 分块处理，不预分配 `(n_trials × max_dur × 2)` 的全量矩阵

---

### 2.7 export

**输入**：
- `{output_dir}/postprocessed/{probe_id}/` — 各 probe 的 SortingAnalyzer
- `{output_dir}/sync/behavior_events.parquet` — 行为事件
- `session.subject` — SubjectConfig
- `session.probes` — ProbeInfo 列表（含电极坐标等元数据）
- `session.session_dir` — 用于读取 SpikeGLX meta 的 session 信息

**处理逻辑**：
1. 创建 `NWBFile`（subject 字段来自 SubjectConfig，session_start_time 来自 SpikeGLX meta）
2. 对每个 probe（逐 probe 处理，不同时加载所有 analyzer）：
   - 创建 `ElectrodeGroup`（name=probe_id, location 从配置或 ProbeInfo 读取）
   - 构建电极表（x/y/z 坐标、group、channel_id）
   - 从 SortingAnalyzer 写 units table（spike_times, waveform_mean, waveform_std, quality_metrics 列, slay_score 列）
   - `del analyzer`；`gc.collect()`
3. 添加 trials 表（来自 behavior_events.parquet）
4. 添加 stimulus 信息（来自 BHV2，条件编号和描述）
5. 预留 LFP 接口（`add_lfp()` 方法体为 `raise NotImplementedError`）
6. 写入 NWB 文件（pynwb，Blosc/zstd 压缩）

**输出**：
- `{output_dir}/NWBFile_{session_id}.nwb`

**checkpoint 内容**：
```json
{
  "stage": "export",
  "completed_at": "2026-03-31T18:00:00",
  "nwb_path": "NWBFile_session_20260101.nwb",
  "file_size_gb": 2.3
}
```

**内存管理**：
- 逐 probe 加载 analyzer，写完立即释放
- NWB 写入采用流式方式（pynwb 内部缓冲），不一次性构建完整对象树
- waveforms 从 analyzer 按 unit 批次写入

---

## 3. synchronize 三级对齐流程图

```
【第一级：IMEC ↔ NIDQ 时钟对齐】

  imec0.ap 数字通道（sync bit 0）
        │
        │  np.diff → 上升沿采样点
        │  ÷ 采样率（从 meta 读取）
        ▼
  imec0 sync 脉冲时间序列
  [t0_ap, t1_ap, t2_ap, ...]        ←── 通常 1 Hz，整个 session
        │
        │  配对
        ▼
  nidq 数字通道（sync bit 0）
        │
        │  np.diff → 上升沿采样点
        │  ÷ 采样率（从 nidq.meta 读取）
        ▼
  nidq sync 脉冲时间序列
  [t0_ni, t1_ni, t2_ni, ...]
        │
        ▼
  线性回归：t_nidq = a × t_imec + b
        │
        ├── 验证残差 < max_time_error_ms（默认 17ms）
        │
        └── 输出：校正函数 {a, b}，写入 sync_tables.json
            对 imec1, imec2, ... 重复上述流程


【第二级：BHV2 ↔ NIDQ 行为对齐】

  BHV2 文件（MATLAB HDF5）
        │
        │  MATLAB Engine 解析 trial struct array
        │  提取 DatasetName 等元信息
        ▼
  BHV2 trial 序列
  [{trial_id, events:[{time_ms, code}, ...]}, ...]
        │
        │  匹配事件码序列（自动修复 trial_start_bit 映射错误）
        ▼
  nidq 数字通道（event_bits 1-7）
        │
        │  多 bit 解码 → (采样点, 事件码)
        │  ÷ 采样率 → 事件时间（NIDQ 时钟）
        ▼
  NIDQ 事件码序列
  [(t_ni_0, code_0), (t_ni_1, code_1), ...]
        │
        │  trial 对齐（onset 事件码序列匹配）
        ▼
  behavior_events 表（初版，trial_valid=NaN）
  trial_id | onset_nidq_s | stim_onset_nidq_s | condition_id | dataset_name | ...


【第三级：Photodiode 模拟信号校准】

  nidq 模拟通道（sync.photodiode_channel_index）
        │
        │  int16 → 电压（niAiRangeMax 从 meta 读取）
        │  resample_poly → 1ms 分辨率
        ▼
  photodiode 信号（1ms/sample）
        │
        │  以 stim_onset_nidq_s 为参考
        │  提取 [-10ms, +100ms] 窗口（逐 trial）
        ▼
  逐 trial z-score 归一化
        │
        │  全局阈值 = 0.1×baseline_mean + 0.9×stim_period_mean
        │  首次超阈 → onset_latency (ms)
        ▼
  onset_latency + monitor_delay_ms（来自配置）
        │
        │  np.interp（NI 时钟 → IMEC 时钟，用第一级校正函数）
        ▼
  stim_onset_imec_s（IMEC 时钟，每 probe 一份）
        │
        └── 写入 behavior_events.stim_onset_imec_s
```

---

## 4. 配置文件设计

### 4.1 config/pipeline.yaml — 完整字段定义

```yaml
# ============================================================
# pynpxpipe Pipeline 配置
# ============================================================

# 资源配置
resources:
  n_jobs: auto                   # "auto" 或整数（ResourceDetector 自动推算）
  chunk_duration: auto           # "auto" 或时长字符串（如 "0.5s", "2s"）
  max_memory: auto               # "auto" 或大小字符串（如 "32G"）— 仅警告用

# 多探针并行（实验性，谨慎开启）
parallel:
  enabled: false                 # 默认串行；资源充足时可开启
  max_workers: auto              # "auto" 或整数（ProcessPoolExecutor 最大工作进程数）
                                 # 注意：sort stage 忽略此选项，始终串行

# 预处理参数
preprocess:
  bandpass:
    freq_min: 300                # 高通截止频率（Hz）
    freq_max: 6000               # 低通截止频率（Hz）
  bad_channel_detection:
    method: "coherence+psd"      # 坏道检测方法
    dead_channel_threshold: 0.5  # coherence 低于此值认定为死道
  common_reference:
    reference: "global"          # "global" | "local"
    operator: "median"           # "median" | "average"
  motion_correction:
    method: "dredge"             # "dredge" | "kilosort" | null（跳过运动校正）
    preset: "nonrigid_accurate"  # dredge 预设（"rigid_fast" | "nonrigid_accurate"）

# 质控与筛选阈值（curate stage）
curation:
  isi_violation_ratio_max: 0.1   # ISI 违反比例上限（0~1）
  amplitude_cutoff_max: 0.1      # 振幅截断比例上限（0~1）
  presence_ratio_min: 0.9        # 存在比例下限（0~1，即 session 中出现时间的占比）
  snr_min: 0.5                   # 信噪比下限

# 同步参数（synchronize stage）
sync:
  sync_bit: 0                    # SpikeGLX sync 脉冲的 bit 位（AP 和 NIDQ 数字通道）
  event_bits: [1, 2, 3, 4, 5, 6, 7]  # MonkeyLogic 事件码占用的 bit 位
  max_time_error_ms: 17.0        # IMEC↔NIDQ 最大允许同步误差（ms），超限报错
  trial_count_tolerance: 2       # BHV2 trial 数与 NIDQ 事件数允许的最大差异（自动修复范围）
  photodiode_channel_index: 0    # NIDQ 模拟通道中 photodiode 信号的通道索引
  monitor_delay_ms: -5           # 显示器系统延迟校正量（ms），60Hz 通常为 -5
  stim_onset_code: 64            # NIDQ 数字通道中代表 stimulus onset 的事件码值
  imec_sync_code: 64             # IMEC 数字通道中的 sync 标记码值
  generate_plots: true           # 是否生成同步诊断图（保存到 sync/figures/）
```

### 4.2 config/sorting.yaml — 完整字段定义

```yaml
# ============================================================
# pynpxpipe Sorting 配置
# ============================================================

# Sorting 模式
mode: "local"                    # "local"（本地运行）| "import"（导入外部结果）

# 本地运行参数（mode: local 时生效）
sorter:
  name: "kilosort4"              # 使用的 spike sorter 名称
  params:
    nblocks: 15                  # 漂移校正块数（0 = 关闭漂移校正，适合短 session）
    Th_learned: 7.0              # 学习阈值（越小越灵敏，噪声也越多）
    do_CAR: false                # 是否在 KS 内部做 CAR（预处理已做 CMR，通常关闭）
    batch_size: auto             # "auto" 或采样点数（ResourceDetector 基于 VRAM 推算）
    n_jobs: 1                    # Kilosort 内部并行（通常设 1，依赖 GPU）

# 导入外部结果参数（mode: import 时生效）
import:
  format: "kilosort4"            # "kilosort4" | "phy"（phy 格式通用于多种 sorter 的手动修改结果）
  # probe 路径在 CLI 调用时通过 --import-path 参数传入，不固定在配置文件中
  # 若要在配置中固定，可用如下格式：
  # paths:
  #   imec0: "/path/to/kilosort_output/imec0"
  #   imec1: "/path/to/kilosort_output/imec1"

# SortingAnalyzer 后处理参数（postprocess stage 使用）
analyzer:
  random_spikes:
    max_spikes_per_unit: 500     # 每个 unit 最多采样的 spike 数（控制内存）
    method: "uniform"            # 采样方式
  waveforms:
    ms_before: 1.0               # spike 前提取时长（ms）
    ms_after: 2.0                # spike 后提取时长（ms）
  templates:
    operators: ["average", "std"]  # 计算模板的统计量
  unit_locations:
    method: "monopolar_triangulation"  # 空间定位方法
  template_similarity:
    method: "cosine_similarity"  # 模板相似度计算方法
```

---

## 5. NWB 输出结构

多 probe 数据在单个 NWB 文件中的组织方式如下：

```
NWBFile
├── .identifier               UUID（session 唯一标识）
├── .session_description      "pynpxpipe processed: {session_id}"
├── .session_start_time       从 SpikeGLX meta 中的 fileCreateTime 字段读取
├── .timestamps_reference_time session_start_time（所有时间戳相对此时刻，单位秒）
│
├── .subject                  NWBSubject
│     .subject_id             "MaoDan"
│     .description            "good monkey"
│     .species                "Macaca mulatta"
│     .sex                    "M"
│     .age                    "P4Y"
│     .weight                 "12.8kg"
│
├── .electrode_groups         dict[str, ElectrodeGroup]（每个 probe 一个）
│     "imec0": ElectrodeGroup
│           .name             "imec0"
│           .description      "Neuropixels 1.0, SN: XXXXX"
│           .location         "Area_V1"（从配置或探针信息读取）
│           .device           Device（"Neuropixels 1.0"）
│     "imec1": ElectrodeGroup
│           ...
│
├── .electrodes               DynamicTable（所有 probe 的电极合并）
│     列：x, y, z             float（探针坐标系中的位置，μm）
│         group               引用 electrode_groups 中的对象
│         group_name          str（"imec0" | "imec1"）
│         probe_id            str（冗余列，便于查询）
│         channel_id          int（probe 内通道编号）
│
├── .units                    Units DynamicTable（所有 probe 的 unit 合并）
│     必选列：
│         spike_times          VectorData[float]（每个 unit 的 spike 时间序列，秒）
│         spike_times_index    VectorIndex（CSC 格式索引）
│         probe_id             str（"imec0" | "imec1"）
│         electrode_group      引用对应的 ElectrodeGroup
│     quality metric 列：
│         isi_violation_ratio  float
│         amplitude_cutoff     float
│         presence_ratio       float
│         snr                  float
│         slay_score           float（SLAY 可靠性分数）
│     波形列：
│         waveform_mean        array，shape (n_samples × n_channels)，单位 μV
│         waveform_std         array，shape (n_samples × n_channels)
│         unit_location        array，shape (3,)，单位 μm（探针坐标系）
│
├── .trials                   TimeIntervals DynamicTable
│     start_time              float（trial onset，NIDQ 时钟秒）
│     stop_time               float（trial offset，NIDQ 时钟秒）
│     stim_onset_time         float（stimulus onset，NIDQ 时钟秒）
│     trial_id                int（BHV2 trial 编号）
│     condition_id            int（刺激条件编号）
│     trial_valid             bool（眼动验证通过，来自 BHV2 或后处理）
│
├── .processing["behavior"]   ProcessingModule
│     └── "BehavioralTimeSeries"  BehavioralTimeSeries（预留，可含眼动 SpatialSeries）
│
└── .processing["ecephys"]    ProcessingModule（预留 LFP）
      └── "LFP"               LFP 对象（接口已预留，方法体为 NotImplementedError）
```

**多 probe 数据的 units table 示例**：

| unit_id | probe_id | spike_times | isi_violation_ratio | slay_score | waveform_mean |
|---------|----------|-------------|--------------------:|----------:|---------------|
| 0 | imec0 | [0.12, 0.45, ...] | 0.02 | 0.85 | array(...) |
| 1 | imec0 | [0.08, 0.33, ...] | 0.05 | 0.72 | array(...) |
| ... | ... | ... | ... | ... | ... |
| 87 | imec1 | [0.15, 0.42, ...] | 0.01 | 0.91 | array(...) |

---

## 6. 错误处理策略

### 6.1 异常层次

```
PynpxpipeError（基类）
├── StageError(stage_name, probe_id, cause)   — stage 执行失败
│     ├── DiscoverError                       — 数据发现/验证失败
│     ├── PreprocessError                     — 预处理失败
│     ├── SortError                           — spike sorting 失败
│     ├── SyncError                           — 时间同步失败
│     ├── CurateError                         — 质控筛选失败
│     ├── PostprocessError                    — 后处理失败
│     └── ExportError                         — NWB 导出失败
├── ConfigError(field, value)                  — 配置文件错误
└── CheckpointError(stage, path)               — checkpoint 读写失败
```

### 6.2 各 Stage 失败场景与恢复方式

| Stage | 失败场景 | 严重程度 | 恢复方式 |
|-------|---------|---------|---------|
| discover | bin 文件大小与 meta 不匹配（数据截断） | 中 | 跳过该 probe，记录警告；若所有 probe 失败则 raise DiscoverError |
| discover | BHV2 文件不可读（魔数错误、损坏） | 高 | 立即 raise DiscoverError，pipeline 中止 |
| discover | NIDQ 数据缺失 | 高 | 立即 raise DiscoverError，pipeline 中止 |
| preprocess | 坏道比例超过阈值（>50%） | 中 | 记录警告，继续处理；可配置 `bad_channel_max_ratio` 控制中止阈值 |
| preprocess | 磁盘空间不足（Zarr 写入失败） | 高 | 捕获 OSError，清理已写文件，raise PreprocessError |
| sort | Kilosort CUDA/OOM 错误 | 高 | 写失败 checkpoint（含错误信息），建议用户修复后用 `import` 模式导入 |
| sort | 导入路径不存在（import mode） | 高 | 立即 raise SortError，提示检查配置中的 import.paths |
| sort | sorting 结果为空（0 units） | 中 | 记录警告，写 checkpoint，使用空 sorting 继续（后续 stage 会处理空情况） |
| synchronize | IMEC↔NIDQ 误差超限 | 高 | raise SyncError，提示数据可能有录制中断或 sync 脉冲丢失 |
| synchronize | BHV2 trial 数与 NIDQ 事件数相差超过容忍值 | 高 | raise SyncError，提示检查 BHV2 文件和 NIDQ 录制是否完整 |
| synchronize | BHV2 trial 数差异在容忍范围内 | 低 | 自动截断较长一侧（取较小值），记录警告和丢失的 trial 编号 |
| curate | 所有 unit 被筛掉（过于严格的阈值） | 低 | 记录警告，写 checkpoint（n_units_after=0），用空 sorting 继续；不 raise |
| postprocess | waveform 提取 OOM | 中 | 将 chunk_duration 减半后自动重试一次；失败则 raise PostprocessError |
| export | NWB 写入失败（磁盘满、权限问题） | 高 | 删除不完整 NWB 文件，raise ExportError；checkpoint 数据保留，可重跑 export |

### 6.3 通用错误处理模式

所有 stage 遵循以下模式：

```
try:
    stage.run()
    stage._write_checkpoint(status="completed")
except PynpxpipeError:
    stage._write_checkpoint(status="failed", error=str(e))
    logger.error(stage=..., probe_id=..., error=..., traceback=...)
    raise
except Exception as e:
    # 未预期的异常包装为 StageError
    stage._write_checkpoint(status="failed", error=str(e))
    raise StageError(stage_name, probe_id, e) from e
```

checkpoint 中的 `"failed"` 状态允许用户：
1. 修复问题（如补充数据、调整配置）
2. 删除对应 checkpoint 文件
3. 重新运行 pipeline，自动从失败点续跑
