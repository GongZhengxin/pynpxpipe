# pynpxpipe 架构设计文档

> 版本：0.2.0  
> 日期：2026-04-15  
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

## 2. Stage 摘要

每个 stage 的详细设计见对应的 `docs/specs/{模块名}.md`。本节仅列出输入/输出和关键约束。

### 2.1 discover

**输入**：`session.session_dir`（SpikeGLX 录制根目录）、`session.bhv_file`（BHV2 路径）

**处理逻辑**：
1. 扫描 `session_dir`，匹配 `imec{N}` 子目录
2. 对每个 probe 验证 `.ap.bin` + `.ap.meta` 存在，校验 bin 文件大小与 meta 一致
3. 读取 meta 提取采样率、通道数、探针型号
4. 扫描并验证 NIDQ 数据
5. 验证 BHV2 文件可读
6. 构建 `ProbeInfo` 列表，写入 `session.probes` 和 `session_info.json`

**输出**：`session.probes`（`list[ProbeInfo]`）、`{output_dir}/session_info.json`

> 详细设计见 `docs/specs/discover.md`

---

### 2.2 preprocess

**输入**：`session.probes`、AP bin 数据（lazy loading）、`config.pipeline.preprocess`、`config.pipeline.resources`

**预处理链（顺序严格不可调换，对每个 probe 串行）**：
1. `phase_shift` — Neuropixels TDM-ADC 相位校正，**必须第一步**（见 ADR-002）
2. `bandpass_filter` — 保留 AP 频段（300-6000 Hz）
3. `detect_bad_channels` — coherence+psd 方法，在滤波后数据上运行
4. `remove_channels` — 剔除坏道，在 CMR 之前执行
5. `common_reference` — 全局中位参考（global median）
6. `correct_motion`（可选）— DREDge 漂移校正，与 KS4 `nblocks` 互斥（见 ADR-001）
7. 保存为 Zarr 格式到 `{output_dir}/preprocessed/{probe_id}/`

**输出**：`{output_dir}/preprocessed/{probe_id}/`（Zarr recording）

**跨 stage 约束**：preprocess 的 `motion_correction.method` 决定 sort stage 的 KS4 `nblocks` 值，由 runner 自动联动。

> 详细设计见 `docs/specs/preprocess.md`

---

### 2.3 sort

**输入**：Zarr 预处理 recording、`config.sorting`

**处理逻辑**（对每个 probe 严格串行，同时只占用一个 GPU）：
- **本地模式**（`mode: local`）：调用 KS4 via SpikeInterface，参数 `do_CAR: false`（始终），`nblocks` 由 preprocess 配置联动
- **导入模式**（`mode: import`）：`si.read_sorter_folder()` 加载外部 sorting 结果

**输出**：`{output_dir}/sorting/{probe_id}/`（SpikeInterface Sorting 对象）

**跨 stage 约束**：`do_CAR: false` 对所有 session 强制（preprocess 已做 CMR）。`nblocks` 由 runner 根据 preprocess checkpoint 中的 `motion_correction_method` 自动注入。

> 详细设计见 `docs/specs/sort.md`

---

### 2.4 synchronize

**输入**：NIDQ 数字/模拟通道、各 probe AP sync 通道、BHV2 文件、MATLAB Engine、`config.pipeline.sync`

**处理逻辑（三级对齐）**：
1. **IMEC↔NIDQ 时钟对齐**：每 probe sync 脉冲线性回归 → `t_nidq = a × t_imec + b`
2. **BHV2↔NIDQ 事件匹配**：MATLAB Engine 解析 BHV2 → trial 事件码序列匹配 → trial 级事件表
3. **Photodiode 校准**：NIDQ 模拟通道 → 逐 trial 阈值检测 → onset_latency + monitor_delay 校正 → IMEC 时钟转换
4. **诊断图生成**（可选）：调用 `io/sync_plots.py`

**输出**：
- `{output_dir}/sync/sync_tables.json` — 每个 probe 的 `{a, b, residual_ms}`
- `{output_dir}/sync/behavior_events.parquet` — 统一时间轴行为事件表
- `{output_dir}/sync/figures/` — 诊断图

> 详细设计见 `docs/specs/synchronize.md`（含三级对齐 ASCII 流程图，附录 A）

### 2.4a synchronize 子模块拆分

synchronize stage 内部模块划分（每个子模块可独立测试）：

- **`stages/synchronize.py`** — 主调度，按顺序调用子模块，管理 checkpoint
- **`io/sync/imec_nidq_align.py`** — 第一级：IMEC↔NIDQ 线性回归对齐
- **`io/sync/bhv_nidq_align.py`** — 第二级：BHV2↔NIDQ 事件匹配（依赖 MATLAB Engine）
- **`io/sync/photodiode_calibrate.py`** — 第三级：Photodiode onset 校准
- **`io/sync_plots.py`** — 诊断图（matplotlib 可选依赖）

---

### 2.5 curate

**输入**：Sorting 结果、预处理 recording、`config.pipeline.curation`

**处理逻辑**（对每个 probe 串行）：
1. 创建 `SortingAnalyzer`（sorting + recording，sparse=True）
2. 计算扩展序列：`random_spikes` → `waveforms` → `templates` → `noise_levels` → `spike_amplitudes`
3. 计算 `quality_metrics`
4. Bombcell 分类（`bombcell_label_units`，SI 0.104+）→ 输出 `bombcell_label` 列
5. 按 `bombcell_label` 筛选 units，保存 curated sorting

**输出**：
- `{output_dir}/curated/{probe_id}/` — Curated Sorting
- `quality_metrics.csv`、`bombcell_labels.csv`

> 详细设计见 `docs/specs/curate.md`

---

### 2.6 postprocess

**输入**：Curated sorting、预处理 recording、`behavior_events.parquet`、`config.sorting.analyzer`

**处理逻辑**（对每个 probe 串行）：
1. 创建完整 `SortingAnalyzer`
2. 计算扩展：`random_spikes` → `waveforms` → `templates` → `unit_locations` → `template_similarity` → `correlograms`
3. 自动合并过分割单元（可选，SLAy preset，`compute_merge_unit_groups(preset="slay")`，SI 0.104+）
4. 眼动验证（可选）：逐 trial 检查固视窗口 → 更新 `behavior_events.parquet` 的 `trial_valid` 列
5. SLAY 计算：binned spike count 的 trial 对 Spearman 相关均值，衡量 response reliability

**输出**：
- `{output_dir}/postprocessed/{probe_id}/` — 完整 SortingAnalyzer
- `merge_log.json`（若执行了 auto_merge）

> 详细设计见 `docs/specs/postprocess.md`

---

### 2.7 export

**输入**：各 probe SortingAnalyzer、`behavior_events.parquet`、SubjectConfig、ProbeInfo 列表

**处理逻辑**：
1. 创建 `NWBFile`（subject 从 SubjectConfig，session_start_time 从 SpikeGLX meta）
2. 逐 probe：创建 ElectrodeGroup → 构建电极表 → 写 units table → 释放 analyzer
3. 添加 trials 表（from behavior_events）
4. 添加 stimulus 信息（from BHV2）
5. 预留 LFP 接口（`NotImplementedError`）
6. 写入 NWB 文件（pynwb，Blosc/zstd 压缩）

**输出**：`{output_dir}/NWBFile_{session_id}.nwb`

> 详细设计见 `docs/specs/export.md`（含 NWB 完整结构，附录 A）

---

## 3. 配置文件设计

### 3.1 config/pipeline.yaml

```yaml
resources:
  n_jobs: auto
  chunk_duration: auto
  max_memory: auto

parallel:
  enabled: false
  max_workers: auto                  # sort stage 忽略此选项，始终串行

preprocess:
  phase_shift:
    enabled: true
  bandpass:
    freq_min: 300
    freq_max: 6000
  bad_channel_detection:
    method: "coherence+psd"
    dead_channel_threshold: 0.5
    noisy_channel_threshold: 1.0
  common_reference:
    reference: "global"
    operator: "median"
  motion_correction:
    method: "dredge"                 # "dredge" | null; 与 sorting.yaml nblocks 互斥
    preset: "nonrigid_accurate"

curation:
  isi_violation_ratio_max: 0.1
  amplitude_cutoff_max: 0.1
  presence_ratio_min: 0.9
  snr_min: 0.5

sync:
  sync_bit: 0
  event_bits: [1, 2, 3, 4, 5, 6, 7]
  max_time_error_ms: 17.0
  trial_count_tolerance: 2
  photodiode_channel_index: 0
  monitor_delay_ms: -5
  stim_onset_code: 64
  imec_sync_code: 64
  generate_plots: true
```

### 3.2 config/sorting.yaml

```yaml
mode: "local"                        # "local" | "import"

sorter:
  name: "kilosort4"
  params:
    nblocks: 0                       # 与 preprocess.motion_correction.method 互斥
    Th_learned: 7.0
    do_CAR: false                    # preprocess 已做 CMR，必须关闭
    batch_size: auto
    n_jobs: 1

import:
  format: "kilosort4"               # "kilosort4" | "phy"

analyzer:
  random_spikes:
    max_spikes_per_unit: 500
    method: "uniform"
  waveforms:
    ms_before: 1.0
    ms_after: 2.0
  templates:
    operators: ["average", "std"]
  unit_locations:
    method: "monopolar_triangulation"
  template_similarity:
    method: "cosine_similarity"
```

---

## 4. NWB 输出结构（简化版）

```
NWBFile
├── .subject           NWBSubject（from monkeys/{name}.yaml）
├── .electrode_groups   dict[str, ElectrodeGroup]（每个 probe 一个）
├── .electrodes        DynamicTable（所有 probe 电极合并）
├── .units             Units DynamicTable（合并所有 probe; 含 quality metrics + SLAY + waveforms）
├── .trials            TimeIntervals（from behavior_events）
├── .processing["behavior"]  BehavioralTimeSeries（预留）
└── .processing["ecephys"]   LFP（预留，NotImplementedError）
```

> 完整字段定义见 `docs/specs/export.md` 附录 A

---

## 5. 错误处理策略

### 5.1 异常层次

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

### 5.2 各 Stage 失败场景与恢复方式

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

### 5.3 通用错误处理模式

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

## 6. 关键架构决策（ADR）

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

---

## 7. MATLAB 参考实现对应表

MATLAB 参考实现的 21 个处理步骤（详见 `docs/ground_truth/step4_full_pipeline_analysis.md`）与 pynpxpipe 模块的对应关系。已知差异详见 `docs/ground_truth/step5_matlab_vs_python.md`。

| MATLAB # | 描述 | pynpxpipe 模块 | Stage | 状态 |
|----------|------|---------------|-------|------|
| #0 | SpikeGLX 文件夹发现 | `io/spikeglx.py` | discover | ✅ |
| #1 | NIDQ 数据加载 | `io/spikeglx.py` | discover | ✅ |
| #2 | BHV2 发现与解析 | `io/bhv.py` | discover | ✅ |
| #3 | BHV2 文件名解析 | `io/bhv.py` | synchronize | ✅ |
| #4 | IMEC LF sync 脉冲提取 | N/A（pynpxpipe 使用 AP digital sync） | — | N/A |
| #5 | IMEC AP metadata 加载 | `io/spikeglx.py` | discover | ✅ |
| #6 | IMEC↔NIDQ 时钟对齐 | `io/sync/imec_nidq_align.py` | synchronize | ❌ 缺 sync pulse repair |
| #7 | ML↔NI trial 数量验证 | `io/sync/bhv_nidq_align.py` | synchronize | 🟡 |
| #8 | Dataset 名提取 | `io/sync/bhv_nidq_align.py` | synchronize | 🟡 |
| #9 | 眼动验证 | `stages/postprocess.py` | postprocess | ⚠️ trial_valid_idx 语义差异 |
| #10 | Photodiode onset 校准 | `io/sync/photodiode_calibrate.py` | synchronize | ❌ 缺极性校正 |
| #11 | Monitor delay 校正 (-5ms) | `io/sync/photodiode_calibrate.py` | synchronize | 🟡 |
| #12 | 诊断图 + META 输出 | `io/sync_plots.py` | synchronize | 🟡 |
| #13 | AP 预处理 + KS4 | `stages/preprocess.py` + `stages/sort.py` | preprocess/sort | ❌ phase_shift 顺序（旧代码，已在架构中修正） |
| #14 | Bombcell 质控 | `stages/curate.py` | curate | 🟡 |
| #15 | KS4 输出加载 + 时钟对齐 | `stages/postprocess.py` | postprocess | 🟡 |
| #16 | trial_ML 字段清理 | N/A（NWB 格式不需要） | — | N/A |
| #17 | Bombcell 诊断图 + GoodUnitRaw | N/A（数据直接写入 NWB） | — | N/A |
| #18 | Raster + PSTH 构建 | `stages/postprocess.py` | postprocess | 🟡 |
| #19 | 统计过滤 + 波形修剪 | `stages/postprocess.py` | postprocess | ❌ 缺方向性过滤条件 |
| #20 | GoodUnit 最终输出 | `stages/export.py` + `io/nwb_writer.py` | export | 🟡 |

### 已知必须修复的差异（❌）

1. **#6 sync pulse repair**：MATLAB 自动修复丢失脉冲（检测 >1200ms 间隔，插值补回）。Python 仅记录 "failed"，需实现修复逻辑。
2. **#10 photodiode 极性校正**：MATLAB 逐 trial 检测信号方向，下降沿时翻转。Python 缺失此逻辑，暗刺激 session 会失败。
3. **#13 预处理顺序**：phase_shift 必须在 bandpass 之前。新架构已修正（ADR-002），旧代码需迁移。
4. **#19 方向性过滤**：MATLAB 要求 `mean(response) > mean(baseline)`（排除抑制性响应）。Python 缺失此条件。
5. **#9 trial_valid_idx 语义**：MATLAB 无效眼动偏移量=0；Python 为所有 onset 赋值图像编号，有效性由 `dataset_valid_idx` 控制。结果一致性需验证。
