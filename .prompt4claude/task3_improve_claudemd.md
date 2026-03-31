请根据以下反馈修改项目根目录的 CLAUDE.md 文件，这是本轮的最终修订：

---

## 修改1：新增设计原则 — 前后端分离（GUI 兼容）

在"核心设计原则"部分新增第 7 条：

7. **前后端分离**：CLI 只是调用 core/stages/pipelines 层的"薄壳入口"。所有业务逻辑严禁放在 cli/ 中。core、io、stages、pipelines 层不得 import click 或任何 CLI 框架。不得在业务逻辑中使用 print 输出用户信息（统一走 logging）。不得在业务逻辑中使用 sys.exit()。这样做的目的是：未来可以在不修改任何业务代码的情况下，接入 GUI 前端（PyQt / Streamlit / Web），GUI 同样只是另一个薄壳入口。

## 修改2：修订设计原则第3条 — 内存安全 + 可选并行

将原来的第 3 条替换为：

3. **资源感知**：
   - **内存安全**：单个大文件（AP bin 可达 400-500GB）禁止一次性加载到内存，必须用 SpikeInterface 的 lazy recording 机制或分块处理。每个 stage 结束时 del 大对象 + gc.collect()。
   - **多探针并行可选**：默认按 probe 串行处理（安全、低内存占用）。在配置文件中提供 `parallel: true` 选项和 `max_workers` 参数，允许用户在资源充足时并行处理多个 probe（使用 concurrent.futures.ProcessPoolExecutor）。sorting stage 由于 GPU 限制默认始终串行。
   - **资源配置**：pipeline 配置文件中设置 `n_jobs`（SpikeInterface 内部并行线程数）、`chunk_duration`（分块处理的时间窗长度）、`max_memory`（内存上限提示）等参数，用户根据自己的机器资源调整。

## 修改3：Pipeline stage 顺序最终确认

最终顺序（synchronize 在 sort 之后、curate 之前，已确认可行）：

1. **discover** — 扫描 SpikeGLX 文件夹，发现所有 probe、验证数据完整性（meta + bin 文件大小匹配）、提取元信息
2. **preprocess** — 对每个 probe 的 AP 数据做预处理：bandpass filter → common median reference → 运动校正(motion correction/drift correction with dredge)
3. **sort** — 对每个 probe 独立运行 spike sorting（默认 Kilosort4 via SpikeInterface），或导入外部 sorting 结果
4. **synchronize** — 多层时间同步 + 行为事件解析（详见下方同步设计）
5. **curate** — 质控与自动筛选：使用 SpikeInterface 内置的 quality_metrics + curation
6. **postprocess** — SpikeInterface SortingAnalyzer：waveforms, templates, unit locations；包含 SLAY 计算
7. **export** — 将所有数据整合写入 NWB 文件

### synchronize 详细设计

同步架构（以 NIDQ 为中介的两级对齐）：
- 第一级：IMEC ↔ NIDQ 对齐。每个 IMEC probe 的 AP/LF 数据流通过 SpikeGLX 内置的同步脉冲（数字口）与 NIDQ 时钟对齐。使用 SpikeGLX 的 sync edge 机制提取对应关系。
- 第二级：BHV2 ↔ NIDQ 对齐。MonkeyLogic 在每个行为事件发生时，通过数字口向 NIDQ 发送特定的数字编码信号。从 NIDQ 的数字通道中提取这些事件码，与 BHV2 文件中的事件时间戳对齐。

同步结果：
- 所有数据流（每个 probe 的 AP、LF）的时间戳统一到 NIDQ 时钟
- BHV2 中的 trial 事件（trial onset, stimulus onset, response 等）映射到 NIDQ 时间轴
- 输出：每个 probe 的时间校正函数 + 统一时间轴上的行为事件表

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

## 修改4：Subject 配置 — 使用实际字段

替换 Subject 配置部分为：

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

## 修改5：目录结构微调

在目录结构中体现前后端分离：

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
  io/               # 数据读写（零 UI 依赖）
    __init__.py
    spikeglx.py     # SpikeGLX 数据发现与加载（多探针）
    bhv.py          # MonkeyLogic BHV2 解析
    nwb_writer.py   # NWB 文件生成
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

## 修改6：新增进度回调机制说明

在代码规范部分添加：

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

---

请直接修改 CLAUDE.md 文件，应用以上所有修改。完成后展示完整的最终版 CLAUDE.md 内容。