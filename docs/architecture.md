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
- `config.pipeline.preprocess` — 各步骤参数（详见第 4.1 节配置定义）
- `config.pipeline.resources` — n_jobs, chunk_duration

**预处理链（处理顺序严格不可调换）**：

```python
from spikeinterface.preprocessing import (
    phase_shift,
    bandpass_filter,
    detect_bad_channels,
    common_reference,
    correct_motion,
)

# 原始 AP recording（lazy，未进内存）

# 步骤 1：Phase Shift（相位校正）
# 必须第一步；校正 Neuropixels 多路复用 ADC 的通道采样时间偏移
recording = phase_shift(recording)

# 步骤 2：Bandpass Filter（带通滤波）
# 保留 AP 频段（300-6000 Hz）；在坏道检测之前滤波提高检测可靠性
recording = bandpass_filter(recording, freq_min=300, freq_max=6000)

# 步骤 3：Bad Channel Detection（坏道检测与剔除）
# 在已滤波数据上检测；避免坏道污染后续 CMR
bad_ids, labels = detect_bad_channels(recording, method="coherence+psd")
recording = recording.remove_channels(bad_ids)

# 步骤 4：Common Median Reference（公共中位参考）
# 全局中位参考去除共模噪声；坏道已剔除，不污染参考
recording = common_reference(recording, reference="global", operator="median")

# 步骤 5：Motion Correction（运动校正，可选）
# 仅在 motion_correction.method="dredge" 时执行；
# 与 KS4 内部漂移校正互斥（见"运动校正策略"说明）
recording = correct_motion(recording, preset="nonrigid_accurate")

recording.save(
    folder=output_dir / "preprocessed" / probe_id,
    format="zarr",
    n_jobs=n_jobs,
    chunk_duration=chunk_duration,
)
```

**处理逻辑**（对每个 probe 串行）：
1. 用 `si.read_spikeglx()` 以 lazy 方式加载 AP recording（Recording 对象仅存指针）
2. **Phase shift**：`spre.phase_shift(recording)` — Neuropixels 特有步骤，必须在任何滤波之前执行（原理见下方说明）
3. **Bandpass filter**：`spre.bandpass_filter(freq_min=300, freq_max=6000)` — 参数从配置读取；在坏道检测前滤波，使 coherence+psd 方法工作在 AP 频段
4. **坏道检测**：`spre.detect_bad_channels(method="coherence+psd", dead_channel_threshold=0.5, noisy_channel_threshold=1.0)` — 在已滤波数据上运行，检测结果更可靠
5. **剔除坏道**：`recording.remove_channels(bad_ids)` — 在 CMR 之前剔除，防止坏道污染全局中位参考
6. **CMR**：`spre.common_reference(reference="global", operator="median")` — 去除共模噪声（电极贴合不稳、运动伪迹）
7. **运动校正**（可选）：`spre.correct_motion(preset="nonrigid_accurate")` — 由配置 `motion_correction.method` 控制；与 KS4 `nblocks` 参数互斥
8. 将预处理后的 recording 保存为 Zarr 格式到 `{output_dir}/preprocessed/{probe_id}/`
9. 写 per-probe checkpoint；`del recording`；`gc.collect()`

**各步骤参数表**：

| 步骤 | SI 函数 | 关键参数 | 配置路径 | 备注 |
|------|---------|---------|---------|------|
| Phase shift | `spre.phase_shift()` | 无需参数（从 meta 自动读取） | — | Neuropixels 特有，非 Neuropixels 探针跳过 |
| Bandpass filter | `spre.bandpass_filter()` | `freq_min=300`, `freq_max=6000` | `preprocess.bandpass.*` | Hz 单位，从配置读取 |
| Bad channel detection | `spre.detect_bad_channels()` | `method`, `dead_channel_threshold`, `noisy_channel_threshold` | `preprocess.bad_channel_detection.*` | 返回 bad_ids 和 channel_labels |
| CMR | `spre.common_reference()` | `reference="global"`, `operator="median"` | `preprocess.common_reference.*` | 全局中位参考 |
| Motion correction | `spre.correct_motion()` | `preset="nonrigid_accurate"` | `preprocess.motion_correction.*` | `method: null` 时跳过 |
| 保存 | `recording.save()` | `format="zarr"`, `n_jobs`, `chunk_duration` | `resources.*` | Zarr 格式，支持 lazy 重新加载 |

**为什么 phase shift 必须在带通滤波之前**：

Neuropixels 探针使用时分多路复用 ADC（Time-Division Multiplexed ADC）。同一硬件时刻，各通道并非同时采样，而是以 `dt = 1/fs/nADCs` 的固定偏移依次采样（nADCs 通常为 12 或 24，对应每通道约 0.3-0.8 μs 偏移）。

`si.phase_shift()` 通过频域相位旋转将所有通道插值到同一时间点，消除这一系统性偏移。

若先做带通滤波再做 phase shift，相位旋转作用于已被滤波器改变了相位响应的数据，校正量与真实时间偏移不匹配，引入系统性误差。**phase shift 必须作用于原始未滤波数据。**

**为什么在滤波后检测坏道**：

坏道检测方法 `coherence+psd` 通过比较相邻通道的 coherence（低则为死道）和 PSD 异常（高则为噪声道）来识别坏道。原始数据中含有 LFP 频段（0-300 Hz）的共模信号，会干扰 coherence 计算，导致好道被误判为坏道。在带通滤波（300-6000 Hz）后检测，仅在 AP 频段工作，判别精度更高。

**为什么在 CMR 之前剔除坏道**：

若坏道（死道振幅接近零，噪声道振幅异常高）参与全局中位值计算，会拉偏中位参考信号，使 CMR 校正效果下降。先剔除坏道再计算全局中位，保证参考信号质量。

**运动校正策略（DREDge vs KS4 内部漂移校正）**：

KS4 的 `nblocks > 0` 参数会在内部执行基于模板匹配的漂移校正；`si.correct_motion()` 使用的 DREDge 算法则在预处理阶段独立完成漂移校正。**两者不可同时启用**，否则会对同一信号做两次漂移校正（"双重校正"），引入伪迹并降低 sorting 质量。

| 场景 | 推荐配置 | 说明 |
|------|---------|------|
| 长 session（>30 分钟） | `motion_correction.method: "dredge"` + KS4 `nblocks: 0` | DREDge 对长时漂移精度更高 |
| 短 session（≤30 分钟） | `motion_correction.method: null` + KS4 `nblocks: 15` | KS4 内部校正更轻量，足够应对短 session 漂移 |
| 导入外部 sorting 结果 | 取决于外部结果是否已做漂移校正 | 若外部结果来自已启用 `nblocks` 的 KS4，则 `method: null` |

**与旧代码的对比**：

| 步骤 | 旧代码顺序（错误） | 新架构顺序（正确） | 变更说明 |
|------|-----------|-----------|---------|
| — | （无 phase shift） | **步骤 1: phase_shift** | 新增；Neuropixels 必须步骤 |
| 1 | highpass_filter | **步骤 2: bandpass_filter** | 改为带通；改为在坏道检测之前 |
| 2 | detect_bad_channels（在原始数据上） | **步骤 3: detect_bad_channels**（在滤波后数据上） | 顺序后移，精度更高 |
| 3 | phase_shift（错误位置） | （已移至步骤 1） | 从滤波后移到滤波前 |
| 4 | CMR | **步骤 4: CMR** | 不变；但坏道已在之前剔除 |
| — | （无运动校正） | **步骤 5: motion_correction（可选）** | 新增 DREDge 集成 |

**输出**：
- `{output_dir}/preprocessed/{probe_id}/` — Zarr 格式预处理 recording（lazy 可加载）

**checkpoint 内容**：
```json
{
  "stage": "preprocess",
  "probe_id": "imec0",
  "completed_at": "2026-03-31T11:30:00",
  "bad_channels": [32, 45, 67],
  "bad_channel_labels": {"32": "dead", "45": "noisy", "67": "dead"},
  "n_channels_after": 381,
  "motion_correction_method": "dredge",
  "recording_path": "preprocessed/imec0"
}
```

**内存管理**：
- SpikeInterface lazy recording 机制：所有步骤（phase_shift / bandpass_filter / common_reference / correct_motion）均返回新的 lazy Recording 对象，数据按 chunk 流式读取，不写入内存
- 坏道检测按 chunk 逐块计算 PSD，不加载全体数据；chunk 大小由 `chunk_duration` 控制
- 运动校正（DREDge）内部分块估计漂移向量，不一次性加载全段数据
- Zarr 写入采用压缩格式，磁盘占用约为原始 bin 的 30-50%；写入时数据才真正被读取（唯一一次 I/O 密集操作）
- 每个 probe 处理完立即 `del recording` + `gc.collect()`

---

### 2.3 sort

**输入**：
- `{output_dir}/preprocessed/{probe_id}/` — Zarr 预处理 recording
- `config.sorting` — mode, sorter.name, sorter.params 或 import.path

**KS4 关键参数说明（与 preprocess 联动）**：

preprocess stage 已完成 CMR（公共中位参考）和可选的 DREDge 运动校正，KS4 的对应参数必须与 preprocess 配置保持一致：

| preprocess 配置 | 对应 KS4 参数设置 | 说明 |
|----------------|-----------------|------|
| CMR 已执行（始终） | `do_CAR: false` | 禁止 KS4 内部再做 CAR，避免双重参考 |
| `motion_correction.method: "dredge"` | `nblocks: 0` | DREDge 已校正漂移，KS4 不再重复 |
| `motion_correction.method: null` | `nblocks: 15`（推荐） | KS4 内部处理漂移，适合短 session |

> **注意**：`do_CAR: false` 对所有 session 均应设置（无论是否做了运动校正），因为 preprocess 始终执行 CMR。`nblocks` 则根据是否使用 DREDge 动态调整。

**处理逻辑**（对每个 probe 串行，始终串行）：

**本地运行模式**（`mode: local`）：
1. 从 Zarr 加载预处理 recording
2. 根据 preprocess 配置动态构造 KS4 参数（`do_CAR: false`；`nblocks` 由 `motion_correction.method` 决定）
3. 调用 spike sorter：
   ```python
   from spikeinterface.sorters import run_sorter

   sorting = run_sorter(
       sorter_name="kilosort4",
       recording=recording,
       folder=output_folder,
       **sorter_params
   )
   ```
4. 验证 sorting 结果：spike_times 非空，cluster 数合理（>0）
5. `del recording`；`gc.collect()`（GPU 内存由 Kilosort 自行管理，处理完探针后释放）

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
2. 创建 `SortingAnalyzer`（绑定 sorting + preprocessed recording）：
   ```python
   from spikeinterface.core import create_sorting_analyzer

   analyzer = create_sorting_analyzer(
       sorting=sorting,
       recording=recording,
       format="memory",
       sparse=True,
   )
   ```
3. 计算扩展序列：`random_spikes` → `waveforms` → `templates` → `noise_levels` → `spike_amplitudes`
4. **计算 quality metrics**：`analyzer.compute("quality_metrics")`
5. **Bombcell 分类**（基于已有 quality metrics）：
   ```python
   from spikeinterface.curation import bombcell_label_units

   # Compute quality metrics first (required before bombcell)
   analyzer.compute("quality_metrics")

   # Apply Bombcell labeling
   labels = bombcell_label_units(analyzer=analyzer, thresholds=thresholds)
   ```
   - 输出：DataFrame with `bombcell_label` 列（值："noise" / "mua" / "good" / "non_soma_mua"）
6. 根据 `bombcell_label` 筛选 units，保存 curated sorting
7. `del analyzer`；`gc.collect()`

**Bombcell 集成**（SpikeInterface 0.104+）：

Bombcell 是 `spikeinterface.curation` 模块的阈值分类工具，基于已计算的 quality metrics 进行二次分类。

**调用流程**：
```python
from spikeinterface.core import create_sorting_analyzer
from spikeinterface.curation import bombcell_label_units, bombcell_get_default_thresholds

# Step 0: 创建 SortingAnalyzer
analyzer = create_sorting_analyzer(
    sorting=sorting,
    recording=recording,
    format="memory",
    sparse=True,
)

# Step 1: 计算 quality metrics
analyzer.compute("quality_metrics")

# Step 2: 获取默认阈值（或从 config 加载自定义阈值）
thresholds = bombcell_get_default_thresholds()

# Step 3: Bombcell 分类
labels = bombcell_label_units(
    analyzer=analyzer,
    thresholds=thresholds,
    label_non_somatic=True,
    split_non_somatic_good_mua=True
)
```

**默认阈值结构**（`bombcell_get_default_thresholds()`）：

```python
{
  'noise': {
    'num_positive_peaks': {'greater': None, 'less': 2},
    'num_negative_peaks': {'greater': None, 'less': 1},
    'peak_to_trough_duration': {'greater': 0.0001, 'less': 0.00115},
    'waveform_baseline_flatness': {'greater': None, 'less': 0.5},
    'exp_decay': {'greater': 0.01, 'less': 0.1},
    'peak_after_to_trough_ratio': {'greater': None, 'less': 0.8}
  },
  'mua': {
    'amplitude_cutoff': {'greater': None, 'less': 0.2},
    'num_spikes': {'greater': 300, 'less': None},
    'rp_contamination': {'greater': None, 'less': 0.1},
    'presence_ratio': {'greater': 0.7, 'less': None},
    'amplitude_median': {'greater': 30, 'less': None, 'abs': True},
    'snr': {'greater': 5, 'less': None},
    'drift_ptp': {'greater': None, 'less': 100}
  },
  'non-somatic': {
    'main_peak_to_trough_ratio': {'greater': None, 'less': 0.8},
    'peak_before_to_peak_after_ratio': {'greater': None, 'less': 3},
    'peak_before_to_trough_ratio': {'greater': None, 'less': 3},
    'peak_before_width': {'greater': 0.00015, 'less': None},
    'trough_width': {'greater': 0.0002, 'less': None}
  }
}
```

**分类逻辑**：
1. 先检查 `noise` 阈值 → 标记为 "noise"
2. 未通过 `mua` 阈值 → 标记为 "mua"
3. 通过 `mua` 阈值 → 标记为 "good"
4. 若 `label_non_somatic=True`，检查 `non-somatic` 阈值 → 标记为 "non_soma_mua" 或 "non_soma_good"

**配置参数**（覆盖默认阈值）：

```yaml
curation:
  bombcell:
    label_non_somatic: true
    split_non_somatic_good_mua: true
    thresholds:  # 可选，覆盖默认值
      mua:
        presence_ratio: {greater: 0.8, less: null}
        snr: {greater: 3, less: null}
```

**输出**：
- `{output_dir}/curated/{probe_id}/` — Curated Sorting 对象
- `{output_dir}/curated/{probe_id}/quality_metrics.csv` — 所有 unit 的 quality metrics
- `{output_dir}/curated/{probe_id}/bombcell_labels.csv` — Bombcell 分类结果（列：unit_id, bombcell_label）

**checkpoint 内容**：
```json
{
  "stage": "curate",
  "probe_id": "imec0",
  "completed_at": "2026-03-31T15:00:00",
  "n_units_before": 142,
  "n_units_after": 87,
  "n_good": 21,
  "n_mua": 70,
  "n_noise": 50,
  "n_non_soma": 1,
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
   - `template_similarity`（cosine similarity）
   - `correlograms`（自相关和互相关）
3. **自动合并过分割单元**（可选，由 `config.postprocess.auto_merge.enabled` 控制）：
   - **SpikeInterface 0.104+ 集成 SLAy**：作为 merge preset 使用
   - **目的**：检测并合并被 sorter 过度分割的同一神经元
   - **调用方式**：
     ```python
     from spikeinterface.curation import compute_merge_unit_groups
     
     merge_groups = compute_merge_unit_groups(
         sorting_analyzer=analyzer,
         preset="slay",
         resolve_graph=True
     )
     analyzer_merged = analyzer.merge_units(merge_unit_groups=merge_groups)
     ```
   - **其他可用 presets**：`similarity_correlograms`, `temporal_splits`, `x_contaminations`, `feature_neighbors`
   - **注意**：合并操作不可逆，需保存原始 analyzer 副本
4. 眼动验证（由 `config.postprocess.eye_validation.enabled` 控制，默认 true）：
   - 加载 BHV2 眼动数据（`AnalogData.Eye`）和固视窗口参数（中心坐标、半径）
   - 逐 trial 分块处理（禁止预分配全量眼动矩阵）：
     - 以 stim onset 时间截取眼动信号窗口（-50ms 至 +200ms）
     - 计算窗口内眼位与固视中心的欧式距离
     - 若距离 ≤ 固视窗口半径（来自 BHV2 fixation window 参数），标记 `trial_valid=True`
     - 否则标记 `trial_valid=False`，记录偏离时刻
   - 将 `trial_valid` 列写入 `behavior_events.parquet`（原地更新）
5. 保存完整 analyzer 到磁盘；`del analyzer`；`gc.collect()`

**SLAY 计算（Stimulus-Locked Activity Yield）**

SLAY 衡量神经元响应的 trial-to-trial 可靠性（response reliability）。

**算法**：
1. 将 `[onset - pre_s, onset + post_s]` 窗口分成 10ms bins
2. 对每个 trial，计算每个 bin 的 spike count，形成向量
3. 计算所有 trial 对之间的 Spearman 相关系数（对低发放率更稳健）
4. SLAY = 所有 trial 对相关系数的平均值（范围 [0, 1]）

**参数**：
- `pre_s`：stimulus onset 前的窗口长度（秒），默认 0.05
- `post_s`：stimulus onset 后的窗口长度（秒），默认 0.30
- `bin_size_ms`：bin 大小（ms），固定 10ms

**返回值**：
- `float`：0-1，1 表示所有 trial 响应完全一致
- `np.nan`：有效 trial 数 < 5

**为什么用 Spearman 而非 Pearson**：低发放率时 spike count 分布非正态，Spearman 更稳健，不受极端值影响。

**参考实现**：
```python
from scipy.stats import spearmanr
import numpy as np

def compute_slay(spike_times, stim_onset_times, pre_s=0.05, post_s=0.30, bin_size_ms=10):
    valid_onsets = stim_onset_times[~np.isnan(stim_onset_times)]
    if len(valid_onsets) < 5:
        return np.nan
    bin_size_s = bin_size_ms / 1000.0
    window_duration = pre_s + post_s
    n_bins = int(window_duration / bin_size_s)
    trial_vectors = []
    for onset in valid_onsets:
        spikes_in_window = spike_times[
            (spike_times >= onset - pre_s) & (spike_times < onset + post_s)
        ]
        counts, _ = np.histogram(
            spikes_in_window - (onset - pre_s),
            bins=n_bins,
            range=(0, window_duration)
        )
        trial_vectors.append(counts)
    trial_vectors = np.array(trial_vectors)
    correlations = []
    for i in range(len(trial_vectors)):
        for j in range(i + 1, len(trial_vectors)):
            corr, _ = spearmanr(trial_vectors[i], trial_vectors[j])
            if not np.isnan(corr):
                correlations.append(corr)
    return float(np.mean(correlations)) if correlations else np.nan
```

**输出**：
- `{output_dir}/postprocessed/{probe_id}/` — 完整 SortingAnalyzer
  - 含：waveforms, templates, unit_locations, template_similarity, correlograms
- `{output_dir}/postprocessed/{probe_id}/merge_log.json` — 合并操作记录（如果执行了 auto_merge）

**checkpoint 内容**：
```json
{
  "stage": "postprocess",
  "probe_id": "imec0",
  "completed_at": "2026-03-31T17:00:00",
  "analyzer_path": "postprocessed/imec0",
  "n_units": 87,
  "auto_merge_applied": true,
  "n_units_before_merge": 95,
  "eye_validation_computed": true
}
```

**内存管理**：
- waveforms 计算时 SpikeInterface 按 chunk 流式提取（由 `chunk_duration` 控制）
- `random_spikes` 限制每 unit 最多 500 个 spike，控制总波形量
- 眼动验证按 trial 分块处理，不预分配 `(n_trials × max_dur × 2)` 的全量矩阵
- 自动合并操作在内存中完成，合并后立即保存并释放原 analyzer

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
  phase_shift:
    enabled: true                  # Neuropixels 专用相位校正（非 Neuropixels 探针设 false）
                                   # 必须第一步，在任何滤波之前执行
  bandpass:
    freq_min: 300                # 高通截止频率（Hz）
    freq_max: 6000               # 低通截止频率（Hz）
  bad_channel_detection:
    method: "coherence+psd"      # 坏道检测方法（在 bandpass 之后运行）
    dead_channel_threshold: 0.5  # coherence 低于此值认定为死道
    noisy_channel_threshold: 1.0 # PSD 异常系数高于此值认定为噪声道
  common_reference:
    reference: "global"          # "global" | "local"
    operator: "median"           # "median" | "average"
  motion_correction:
    method: "dredge"             # "dredge" | null（跳过运动校正）
                                 # 注意：method="dredge" 时，sorting.yaml 中
                                 # 必须设置 sorter.params.nblocks: 0
                                 # method=null 时，建议 nblocks: 15（KS4 处理漂移）
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
    nblocks: 0                   # 漂移校正块数：
                                 #   0  = 关闭 KS4 内部漂移校正（preprocess 用 DREDge 时必须设为 0）
                                 #   15 = 开启 KS4 内部漂移校正（preprocess.motion_correction.method=null 时推荐）
                                 # 与 preprocess.motion_correction.method 互斥，二者只能启用其一
    Th_learned: 7.0              # 学习阈值（越小越灵敏，噪声也越多）
    do_CAR: false                # 是否在 KS4 内部做 CAR（preprocess 已做 CMR，必须关闭，避免双重参考）
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

---

## 7. 关键架构决策（ADR）

架构决策记录（Architecture Decision Records）。每条 ADR 记录一个不可逆或代价高昂的设计选择，说明背景、方案比较和最终决策，供未来维护者理解为什么这样设计。

---

### ADR-001：运动校正策略选择（DREDge vs Kilosort4 内部校正）

**状态**：已采纳

**背景**：

Neuropixels 长时录制（>30 分钟）中探针相对脑组织会发生轴向漂移（drift），导致同一 unit 的波形在不同时间出现在不同通道上。有两种主流解决方案：

1. **SpikeInterface `si.correct_motion()`（DREDge 算法）**：在 preprocess 阶段独立运行，将 recording 重新插值到统一空间坐标，输出校正后的 recording，再交给 sorter。
2. **Kilosort4 内部漂移校正（`nblocks > 0`）**：KS4 在 sorting 过程中通过滑动模板匹配估计漂移并在内部迭代校正。

**问题**：

两种方案均可独立工作，但**不可叠加使用**。若同时启用，KS4 会对已被 DREDge 校正的数据再次做漂移估计，产生"过度校正"，引入错误的空间对齐，导致 spike 分配错误和 unit 质量下降。

**方案比较**：

| 维度 | DREDge（preprocess） | KS4 内部（nblocks） |
|------|---------------------|-------------------|
| 精度 | 非刚体（non-rigid）校正，处理局部漂移 | 刚体/分块，全局估计 |
| 适用场景 | 长 session（>30 min），漂移显著 | 短 session（≤30 min），漂移较小 |
| 计算代价 | 中（preprocess 阶段，CPU） | 低（sorting 内部，GPU 加速） |
| 互斥要求 | 启用时 KS4 `nblocks` 必须设为 0 | 启用时 preprocess `method` 必须设为 null |
| 可检查性 | 生成漂移估计图（diagnostics） | KS4 内部，难以独立验证 |

**决策**：

采用**互斥配置联动**机制：

- `preprocess.motion_correction.method: "dredge"` → pipeline 自动将 KS4 `nblocks` 覆盖为 `0`（即使 sorting.yaml 中写了其他值，也以 preprocess 配置为准，并记录 WARNING 日志）
- `preprocess.motion_correction.method: null` → KS4 使用 sorting.yaml 中的 `nblocks` 值（默认 `15`）
- 推荐默认值：长 session 用 DREDge，短 session 用 KS4 nblocks（由用户根据 session 时长判断）

**执行约束**：

`pipelines/runner.py` 在构造 sort stage 参数时，检查 preprocess checkpoint 中的 `motion_correction_method` 字段，自动注入正确的 `nblocks` 值。不依赖用户手动保持两个 yaml 文件的一致性。

---

### ADR-002：Phase shift 必须在带通滤波之前执行

**状态**：已采纳

**背景**：

Neuropixels 探针采用时分多路复用 ADC（TDM-ADC）架构。以 Neuropixels 1.0 为例，384 个记录通道通过 32 个 ADC 采集，每个 ADC 依次对 12 个通道采样。这意味着即使在名义上的同一采样点，各通道的实际物理采样时刻存在细微偏差：

```
通道 0 的实际采样时刻：t
通道 1 的实际采样时刻：t + 1/fs/nADCs  ≈ t + 0.83 μs（fs=30kHz, nADCs=12）
...
通道 11 的实际采样时刻：t + 11/fs/nADCs ≈ t + 9.2 μs
```

`si.phase_shift()` 通过在频域对每个通道施加与其时间偏移对应的相位旋转，将所有通道插值到统一的参考时刻，消除这一系统性偏差。

**问题**：

如果先做带通滤波（FIR/IIR 滤波器）再做 phase shift，FIR 滤波器的群延迟（group delay）和相位响应已经修改了各频率分量的相位。此时再叠加 phase_shift 的相位旋转，两者的相位贡献不可分离，导致 phase shift 校正量与真实时间偏移不匹配。对于高频 AP 信号（300-6000 Hz），相位误差可达数十微秒量级，超过峰值检测的精度要求。

**方案比较**：

| 顺序 | 结果 | 结论 |
|------|------|------|
| phase_shift → bandpass_filter | 在原始数据上做相位校正，物理含义明确 | **正确** |
| bandpass_filter → phase_shift | 相位旋转叠加在滤波器相位响应之上，引入系统误差 | 错误 |
| bandpass_filter → phase_shift → CMR | 同上，错误顺序 | 错误 |

**决策**：

`si.phase_shift()` 必须是 preprocess 链中的**第一个操作**，在任何滤波（包括 bandpass、notch、high-pass）之前执行。代码层面通过函数调用顺序硬性保证，不提供配置项改变此顺序。

这也是 SpikeInterface 官方推荐的 Neuropixels 预处理顺序（参见 SI 文档 "Preprocessing for Neuropixels" 章节）。

**影响**：

- 旧代码中 phase_shift 位于 highpass_filter 之后（错误顺序），必须修正
- 非 Neuropixels 探针（如 Utah Array）无 TDM-ADC 结构，可通过 `phase_shift.enabled: false` 跳过此步骤
- discover stage 需要将探针型号（`imProbeOpt`）写入 ProbeInfo，供 preprocess 判断是否执行 phase_shift
