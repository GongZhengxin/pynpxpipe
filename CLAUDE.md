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
2. **preprocess** — 对每个 probe 的 AP 数据做预处理：phase shift（Neuropixels ADC 时序校正，必须第一步）→ bandpass filter → 坏道检测与剔除 → CMR → 运动校正（DREDge，可选；与 KS4 内部 nblocks 互斥）→ 保存 Zarr
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

### synchronize 设计约束

同步采用以 NIDQ 为中介的三级对齐架构：
IMEC↔NIDQ 时钟对齐（线性回归）→ BHV2↔NIDQ 事件匹配 → Photodiode 模拟信号校准。
详细算法和参数见 `docs/architecture.md` Section 2.4。

**关键约束**：
- BHV2 解析必须通过 MATLAB 引擎（`matlab.engine`），不能用 h5py 直接读 .bhv2
- .bhv2 是 MonkeyLogic 自定义二进制格式（非 HDF5）；h5py 只用于读中间 .mat 文件
- BHV2 文件验证 magic：前 21 字节 = `b'\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition'`
- BHV2 所有读取操作（元信息 + trial 数据 + 眼动）统一在 synchronize 阶段，不拆到 discover
- 诊断图生成逻辑独立为 `io/sync_plots.py`，stages 层禁止 import matplotlib
- 输出：`sync_tables.json` + `behavior_events.parquet` + `sync/figures/`

**IO 模块 spec 写作规则**：写外部格式模块的 spec 前，必须先读 `legacy_reference/` 确认实际格式，不得凭假设。

### Bombcell 集成（curate 阶段）

- Bombcell 用于基于 quality metrics 的阈值分类（noise / mua / good / non-somatic）
- **SpikeInterface 0.104+ 原生集成**：`spikeinterface.curation.bombcell_label_units(analyzer, thresholds)`
- 调用流程：
  1. 先计算 quality metrics：`analyzer.compute("quality_metrics")`
  2. 获取阈值：`thresholds = sc.bombcell_get_default_thresholds()`（或从 config 加载）
  3. 分类：`labels = sc.bombcell_label_units(analyzer, thresholds, label_non_somatic=True)`
- 输出：DataFrame with `bombcell_label` 列（值："noise" / "mua" / "good" / "non_soma_mua"）

### SLAy 集成（postprocess 阶段）

- SLAy (Splitting and Labeling Algorithm) 用于检测并合并被 sorter 过度分割的同一神经元
- **SpikeInterface 0.104+ 原生集成**：作为 `compute_merge_unit_groups()` 的 preset
- 调用方式：
  ```python
  from spikeinterface.curation import compute_merge_unit_groups
  merge_groups = compute_merge_unit_groups(analyzer, preset="slay", resolve_graph=True)
  analyzer_merged = analyzer.merge_units(merge_unit_groups=merge_groups)
  ```
- 其他可用 presets：`similarity_correlograms`, `temporal_splits`, `x_contaminations`, `feature_neighbors`
- 注意：合并操作不可逆

### LFP 处理（预留）

- 当前版本不实现 LFP 专项处理
- discover stage 中会发现并记录 LF 数据流信息
- export stage 中预留 LFP 数据写入 NWB 的接口（函数签名和 docstring，方法体为 raise NotImplementedError）
- 未来可在 preprocess 和 sort 之间插入独立的 lfp_process stage

## 技术栈

- Python >= 3.11
- spikeinterface >= 0.104（使用最新稳定版 API，内置 Bombcell 和 SLAY）
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

## 开发流程（harness 原则）

每个模块**必须**严格按以下顺序完成，禁止跳步：

1. **写 spec**：在 `docs/specs/{模块名}.md` 回答五个问题（目标 / 输入 / 输出 / 处理步骤 / 可配参数）
2. **用户确认 spec**：spec 经用户审阅通过后，才能开始写代码
3. **TDD — RED**：先写测试文件，运行确认全部失败（原因是功能缺失，不是语法错误）
4. **TDD — GREEN**：写最小实现使测试通过，再次运行确认全绿
5. **lint**：`uv run ruff check src/ tests/` 通过，`ruff format` 不报错
6. **更新进度**：将 `docs/progress.md` 对应行状态改为 `✅`，填写测试数量

**即使模块已有骨架代码（`raise NotImplementedError`），也必须先补写 spec 才能开始 TDD。**
骨架代码的存在不构成跳过 spec 的理由。

## 开发工具链

### 运行命令（只允许这些方式）

```bash
uv run pytest                           # 运行全部测试
uv run pytest tests/path/test.py -v    # 运行单个测试文件
uv run ruff check src/ tests/          # Lint 检查
uv run ruff format src/ tests/         # 格式化
uv run jupyter lab                     # 启动 JupyterLab 打开 tutorials/
uv run pytest --nbmake tutorials/      # 自动执行所有 notebook cell（CI 验证用）
```

### 绝对禁止

- 禁止 `pip install` 任何包（uv 管理所有依赖，依赖只能改 pyproject.toml）
- 禁止 `python -m pytest`（绕过 uv 虚拟环境，可能找不到已安装的包）
- 禁止 `pip install -e .` 或 `python setup.py`

### 开发进度追踪

每完成一个模块实现（测试全绿 + ruff 通过），立即将 `docs/progress.md`
中对应行的状态从 `⬜` 更新为 `✅`（完成）或 `🔵`（实现中）。

## Windows 兼容性注意

- 开发环境为 Windows + VSCode
- 所有路径操作必须用 pathlib.Path，禁止手写 / 或 \\
- 文件读写指定 encoding='utf-8'
- 长路径问题：SpikeGLX 输出路径可能很深，注意 Windows 260 字符限制

## 从旧代码迁移的注意事项

参照 `docs/legacy_analysis.md` 中的详细问题清单和新旧对比表。关键原则：
- 旧代码所有硬编码值（采样率 30000 Hz、探针名 imec0、事件码 64 等）全部参数化
- 用 SpikeInterface 公开 API 替代私有属性（`neo_reader.signals_info_dict` 等）
- 用 SpikeInterface 原生 quality_metrics 替代 bombcell
- 眼动矩阵预分配（3D）→ 按 trial 分块处理
- `matplotlib.use('Agg')` 从业务层移除，图表生成统一到 `io/sync_plots.py`
- 预处理链顺序已修正：phase_shift 必须在 bandpass_filter **之前**（旧代码顺序错误）
- 新增 DREDge 运动校正（旧代码无此步骤）；与 KS4 内部 nblocks 互斥，二选一
