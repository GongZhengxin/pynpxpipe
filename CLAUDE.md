# CLAUDE.md

## 项目概述

pynpxpipe：神经电生理数据预处理工具包。
输入：SpikeGLX 录制数据文件夹（含 AP/LF/NI 三类数据流，支持多 probe）+ MonkeyLogic BHV2 行为文件
输出：标准 NWB 格式文件（一个 session 一个 NWB，包含所有 probe 的数据）

## 核心设计原则

1. **多探针优先**：所有模块必须以 probe_id 为参数，支持 N 个 IMEC 探针。单探针是 N=1 的特例，不是默认假设。
2. **断点续跑**：每个 stage 完成后写 checkpoint 文件到 session 输出目录。Pipeline 启动时检查 checkpoint，自动跳过已完成的 stage。
3. **资源感知**：
   - **内存安全**：单个大文件（AP bin 可达 400-500GB）禁止一次性加载到内存，必须用 SpikeInterface 的 lazy recording 机制或分块处理。每个 stage 结束时 del 大对象 + gc.collect()。
   - **多探针并行可选**：默认按 probe 串行处理（安全、低内存占用）。在配置文件中提供 `parallel: true` 选项和 `max_workers` 参数，允许用户在资源充足时并行处理多个 probe（使用 concurrent.futures.ProcessPoolExecutor）。sorting stage 由于 GPU 限制默认始终串行。
   - **资源配置**：pipeline 配置文件中设置 `n_jobs`（SpikeInterface 内部并行线程数）、`chunk_duration`（分块处理的时间窗长度）、`max_memory`（内存上限提示）等参数，用户根据自己的机器资源调整。
   - **自动资源探测**：core/resources.py 中的 ResourceDetector 在 pipeline
     启动时自动探测 CPU 核心数、可用内存、GPU 显存、磁盘空间，
     推算 n_jobs、chunk_duration、max_workers、sorting batch_size 的最优值。
     pipeline.yaml 中支持 "auto" 关键字表示使用自动探测值。
     优先级：用户显式配置 > 自动探测 > 硬编码兜底值。
     探测结果写入结构化日志。GPU 探测优先使用 torch.cuda（若已安装），
     fallback 到 nvidia-smi subprocess。不实现磁盘测速。
4. **零硬编码**：采样率、通道 ID、事件码、探针编号等全部从数据 meta 或配置文件读取，代码中禁止出现 magic number。
5. **日志完备**：所有 stage 操作写入结构化日志（JSON Lines），含时间戳、stage 名、probe_id、参数、耗时、成功/失败状态。
6. **远程 sorting 兼容**：sorting stage 必须支持两种模式——本地运行和导入外部结果（从 Windows 实验室电脑拷贝过来的 kilosort 输出）。
7. **前后端分离**：CLI 只是调用 core/stages/pipelines 层的"薄壳入口"。所有业务逻辑严禁放在 cli/ 中。core、io、stages、pipelines 层不得 import click 或任何 CLI 框架。不得在业务逻辑中使用 print 输出用户信息（统一走 logging）。不得在业务逻辑中使用 sys.exit()。这样做的目的是：未来可以在不修改任何业务代码的情况下，接入 GUI 前端（PyQt / Streamlit / Web），GUI 同样只是另一个薄壳入口。

## Pipeline 架构

### Stage 定义（按顺序执行）

1. **discover** — 扫描 SpikeGLX 文件夹，发现所有 probe、验证数据完整性（meta + bin 文件大小匹配）、提取元信息
2. **preprocess** — 对每个 probe 的 AP 数据做预处理：bandpass filter → common median reference → 运动校正(motion correction/drift correction with dredge)
3. **sort** — 对每个 probe 独立运行 spike sorting（默认 Kilosort4 via SpikeInterface），或导入外部 sorting 结果
4. **synchronize** — 多层时间同步 + 行为事件解析（详见下方同步设计）
5. **curate** — 质控与自动筛选：使用 SpikeInterface 内置的 quality_metrics + curation
6. **postprocess** — SpikeInterface SortingAnalyzer：waveforms, templates, unit locations；包含 SLAY 计算；包含眼动验证（逐 trial 检查注视有效性，结果写入 behavior_events 的 trial_valid 列）
   - 注意：眼动验证是必须步骤，不是可选步骤。但可通过配置跳过（用于没有眼动数据的 session）。
7. **export** — 将所有数据整合写入 NWB 文件

### Session 对象

```python
@dataclass
class Session:
    session_dir: Path          # SpikeGLX 原始数据根目录
    output_dir: Path           # 处理输出目录
    subject: SubjectConfig     # 动物信息（从 monkeys/*.yaml 加载）
    probes: list[ProbeInfo]    # 自动发现的探针列表
    bhv_file: Path             # MonkeyLogic BHV2 文件路径
    checkpoint: dict           # 各 stage 完成状态
    log_path: Path             # 日志文件路径
```

### Subject 配置（monkeys/*.yaml）

每只实验动物一个 yaml 文件（如 JianJian.yaml, MaoDan.yaml），字段定义：

```yaml
Subject:
  subject_id: "MaoDan"          # required by DANDI
  description: "good monkey"     # 自由描述
  species: "Macaca mulatta"      # required by DANDI
  sex: "M"                       # required by DANDI
  age: "P4Y"                     # ISO 8601 duration 格式, required by DANDI
  weight: "12.8kg"               # 体重
```

对应的 SubjectConfig dataclass：

```python
@dataclass
class SubjectConfig:
    subject_id: str
    description: str
    species: str
    sex: str       # "M" | "F" | "U" | "O"
    age: str       # ISO 8601 duration, e.g. "P4Y"
    weight: str    # 含单位, e.g. "12.8kg"
```

注意：这些字段遵循 DANDI 归档标准，export 到 NWB 时直接映射到 NWBFile.subject。

### 多探针处理流程

- discover 阶段自动枚举所有 imec{N} 目录
- preprocess / sort / curate / postprocess 阶段：对 probes 列表串行处理，每完成一个 probe 写 checkpoint + 释放内存
- synchronize 阶段：先对齐所有 probe 到 NI 时钟，再对齐行为事件
- export 阶段：所有 probe 数据写入同一个 NWB 文件的不同 ElectrodeGroup

### synchronize 详细设计

同步架构（以 NIDQ 为中介的三级对齐）：

- 第一级：IMEC ↔ NIDQ 时钟对齐。每个 IMEC probe 的 AP 数据流通过
  SpikeGLX 内置的同步脉冲（数字口）与 NIDQ 时钟对齐。提取双方 sync 脉冲
  上升沿时间序列，线性回归建立校正函数 t_nidq = a × t_imec + b，
  验证残差 < max_time_error_ms。

- 第二级：BHV2 ↔ NIDQ 事件对齐。MonkeyLogic 在每个行为事件发生时，
  通过数字口向 NIDQ 发送特定的数字编码信号。从 NIDQ 数字通道解码事件码序列，
  与 BHV2 文件中的事件时间戳按 trial 匹配对齐。自动检测并修复 trial_start_bit
  映射错误（遍历 bit 0-7 找匹配）。同时提取 BHV2 元信息（DatasetName 等）。
  注意：BHV2 解析需要 MATLAB 引擎（通过 Python 调用），因此 BHV2 相关的
  所有读取操作（包括元信息提取）统一在 synchronize 阶段完成，不拆到 discover。

- 第三级：Photodiode 模拟信号校准。NIDQ 模拟通道中的 photodiode 信号
  精确检测每个 stimulus 的实际显示时刻，校正数字事件码与实际显示的延迟差。
  算法流程：
  1. 从 NIDQ 模拟通道（索引由 config sync.photodiode_channel_index 指定）
     读取 photodiode 信号，int16 转电压（量程从 nidq.meta 读取）
  2. 重采样到 1ms 分辨率（resample_poly，比率从采样率精确计算）
  3. 以数字事件码 stim onset 为参考，提取 [-10ms, +100ms] 窗口
  4. 逐 trial 独立 z-score 归一化
  5. 计算全局阈值（跨 trial 共享）：0.1×baseline_mean + 0.9×stimulus_period_mean
  6. 逐 trial 首次超阈值检测确定 onset_latency（相对数字触发的延迟 ms）
  7. 校正显示器系统延迟（monitor_delay_ms，从配置读取，60Hz 约 -5ms）
  8. 通过 np.interp 将校准后的 onset 时间从 NI 时钟转换到 IMEC 时钟
  边界情况处理（旧代码未覆盖，新架构必须处理）：
  - onset_latency < 0（信号在触发前超阈）：记录警告，标记该 trial 为可疑
  - photodiode 信号接近零（接头松动）：检测信号方差，过低时 raise SyncError
  - 窗口越界（录制起始附近的 onset）：跳过该 trial，记录警告

同步验证（诊断图）：
- 每个对齐步骤完成后生成诊断图，保存到 {output_dir}/sync/figures/
- 由配置项 sync.generate_plots 控制（默认 true）
- 必须包含的图表：
  1. sync_drift_{probe_id}.png — IMEC↔NIDQ 时钟漂移散点图 + 线性回归拟合线
  2. event_alignment.png — BHV2 vs NIDQ 逐 trial onset 数量散点图
  3. photodiode_heatmap.png — 所有 trial 的校准后 photodiode 信号热力图
  4. onset_latency_histogram.png — 逐 trial photodiode 延迟分布直方图
  5. photodiode_mean_signal.png — 校准前 vs 校准后平均 photodiode 信号叠加对比
  6. sync_pulse_interval.png — 相邻 sync 脉冲间隔 vs 期望间隔（检测时钟不稳定）
- 诊断图生成逻辑独立为 io/sync_plots.py，stages 层不 import matplotlib

同步结果：
- 所有数据流的时间戳统一到 NIDQ 时钟
- 每个 probe 的时间校正函数参数
- Photodiode 校准后的精确 stimulus onset 时间（IMEC 时钟）
- BHV2 行为事件表（统一时间轴）
- BHV2 元信息（dataset_name 等）
- 输出文件：sync_tables.json + behavior_events.parquet + figures/

### SLAY 集成（postprocess 阶段）

- SLAY (Stimulus-Locked Activity Yield) 用于评估每个 unit 对 stimulus 响应的可靠性
- 依赖：sorting 结果（spike times）+ 同步后的 stimulus onset times（来自 synchronize stage）
- 使用 spikeinterface 生态中的 SLAY 实现（如可用），否则独立实现
- SLAY 分数作为 unit 的附加 quality metric，写入 NWB 的 units table

### LFP 处理（预留）

- 当前版本不实现 LFP 专项处理
- discover stage 中会发现并记录 LF 数据流信息
- export stage 中预留 LFP 数据写入 NWB 的接口（函数签名和 docstring，方法体为 raise NotImplementedError）
- 未来可在 preprocess 和 sort 之间插入独立的 lfp_process stage

## 技术栈

- Python >= 3.11
- spikeinterface >= 0.101（使用最新稳定版 API）
- probeinterface
- pynwb >= 2.8
- neo
- numpy, scipy
- click（CLI 框架）
- pyyaml（配置管理）
- structlog（结构化日志）
- uv（包管理，pyproject.toml 为唯一依赖声明）
- psutil（系统资源探测，必选依赖）

## 目录结构

```
src/pynpxpipe/
  cli/              # CLI 薄壳入口（仅依赖 click + pipelines 层）
    __init__.py
    main.py         # click group 定义
  core/             # 核心对象（零 UI 依赖）
    __init__.py
    session.py      # Session dataclass + 生命周期管理
    checkpoint.py   # checkpoint 读写
    logging.py      # 结构化日志
    config.py       # YAML 配置加载与验证
    resources.py    # 自动资源探测（ResourceDetector）
  io/               # 数据读写（零 UI 依赖）
    __init__.py
    spikeglx.py     # SpikeGLX 数据发现与加载（多探针）
    bhv.py          # MonkeyLogic BHV2 解析
    nwb_writer.py   # NWB 文件生成
    sync/               # 同步子模块（按对齐级别拆分）
      __init__.py
      imec_nidq_align.py    # 第一级：IMEC↔NIDQ 时钟对齐
      bhv_nidq_align.py     # 第二级：BHV2↔NIDQ 事件匹配 + BHV2 元信息提取
      photodiode_calibrate.py  # 第三级：Photodiode 校准
    sync_plots.py       # 同步诊断图生成（独立于 stage 层，可选依赖 matplotlib）
  stages/           # 处理阶段（零 UI 依赖）
    __init__.py
    base.py         # Stage 基类（含 checkpoint/logging/进度回调 通用逻辑）
    discover.py
    preprocess.py
    sort.py
    synchronize.py  # 注意：顺序调整到 sort 之后
    curate.py
    postprocess.py  # 含 SLAY 计算
    export.py
  pipelines/        # Pipeline 编排（零 UI 依赖）
    __init__.py
    runner.py       # 顺序/并行执行 stages，处理断点续跑和资源配置
config/             # 默认配置文件模板
  pipeline.yaml     # pipeline 参数（n_jobs, chunk_duration, parallel, max_workers 等）
  sorting.yaml      # sorting 参数（sorter_name, sorter_params, import_mode 等）
monkeys/            # subject 配置（每只动物一个 yaml）
tests/
  test_io/
  test_stages/
  test_integration/
```

## 代码规范

- 所有函数和类必须有 type hints
- Docstrings 用 Google style
- 私有函数用 _ 前缀
- 配置项在 YAML 中定义，代码中通过 config 对象访问，禁止 magic number
- 测试文件和被测模块同名，如 test_spikeglx.py 测试 spikeglx.py
- 使用 ruff 做 lint 和 format（pyproject.toml 中配置）

### 进度回调（为 GUI 预留）

Stage 基类提供 progress_callback 参数：
```python
class BaseStage:
    def __init__(self, session: Session, progress_callback: Callable[[str, float], None] | None = None):
        ...
    def _report_progress(self, message: str, fraction: float):
        """fraction: 0.0 ~ 1.0"""
        if self.progress_callback:
            self.progress_callback(message, fraction)
        self.logger.info(message, progress=fraction)
```

- CLI 模式下 progress_callback 为 None，进度仅写日志
- 未来 GUI 模式下传入 GUI 的进度更新函数
- 所有 stage 在关键节点调用 _report_progress

## Windows 兼容性注意

- 开发环境为 Windows + VSCode
- 所有路径操作必须用 pathlib.Path，禁止手写 / 或 \\
- 文件读写指定 encoding='utf-8'
- 长路径问题：SpikeGLX 输出路径可能很深，注意 Windows 260 字符限制

## 从旧代码迁移的注意事项

参照 docs/legacy_analysis.md 中的问题清单：
- 旧代码中所有硬编码的 30000Hz、imec0、通道名、事件码 64 等必须参数化
- 旧代码的 neo_reader.signals_info_dict 私有属性访问必须替换为 spikeinterface 公开 API
- bombcell 的功能用 spikeinterface.curation 和 quality_metrics 替代
- 旧代码的眼动矩阵预分配方式需要改为按 trial 分块处理
- synchronizer.py 行 201 的 CodeVal==64 硬编码必须参数化为 config 中的 sync.imec_sync_code
  （或从信号自动检测：找频率约 1Hz 的码值）
- synchronizer.py 行 397 的 trial_codes==64 必须使用 config.sync.stim_onset_code
- photodiode np.squeeze 假设单列的问题，改为按 sync.photodiode_channel_index 显式索引
- eye_matrix 3D 预分配改为按 trial 分块处理，移至 postprocess 阶段
- matplotlib.use('Agg') 移除，图表生成独立到 io/sync_plots.py
- synchronizer 中 BHV2 文件名解析（split('_')[1:3]）改为从 BHV2 内容或 Session 对象读取
- monitor_delay_correction 硬编码 -5 改为从 config.sync.monitor_delay_ms 读取
