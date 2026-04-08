# Spec: ui/ — Panel Web UI

## 1. 目标

为 pynpxpipe pipeline 提供基于 Panel (HoloViz) 的浏览器交互界面。用户无需写代码即可：

1. 配置 session 参数（数据路径、受试者元信息、pipeline/sorting 参数）
2. 选择要运行的 stage 子集
3. 启动 pipeline 并实时监控 stage 级 + probe 级进度
4. 查看已有 output_dir 的运行状态、重置失败的 stage、断点续跑

**约束**：
- UI 层只调用 `core/`、`pipelines/` 的公开 API，不直接操作 IO 或 stage 内部逻辑
- 业务层不得 import Panel/param — 唯一桥接点是 `progress_callback: Callable[[str, float], None]`
- 长时间 pipeline 运行在后台线程中执行，UI 主线程不阻塞

---

## 2. 模块结构

```
src/pynpxpipe/ui/
    __init__.py
    app.py                 # 入口：panel serve / pynpxpipe-ui 命令
    state.py               # 全局状态：AppState param 类 + ProgressBridge
    components/
        __init__.py
        session_form.py    # Session 配置面板（路径选择 + 输出目录）
        subject_form.py    # Subject 元信息表单
        pipeline_form.py   # PipelineConfig 参数面板
        sorting_form.py    # SortingConfig 参数面板
        stage_selector.py  # Stage 多选器
        run_panel.py       # 执行控制面板（Run / Stop / 状态）
        progress_view.py   # Stage 进度可视化
        log_viewer.py      # 实时日志面板
        status_view.py     # 已有 session 状态查看 + Reset
        session_loader.py  # Session 恢复（从 output_dir 加载）
```

---

## 3. 核心组件规格

### 3.1 state.py — AppState

```python
import param

class AppState(param.Parameterized):
    """全局应用状态，所有组件共享同一实例。"""

    # ── 输入路径 ──
    session_dir = param.Path(doc="SpikeGLX 录制根目录")
    bhv_file = param.Path(doc="MonkeyLogic BHV2 文件")
    output_dir = param.Path(doc="输出根目录")
    subject_yaml = param.Path(doc="Subject YAML 文件（可选预填）")

    # ── 配置对象（由表单填充） ──
    pipeline_config = param.Parameter(doc="PipelineConfig dataclass 实例")
    sorting_config = param.Parameter(doc="SortingConfig dataclass 实例")
    subject_config = param.Parameter(doc="SubjectConfig dataclass 实例")

    # ── 运行时状态 ──
    run_status = param.Selector(
        default="idle",
        objects=["idle", "running", "completed", "failed"],
    )
    selected_stages = param.List(default=[], doc="要运行的 stage 名称列表")
    error_message = param.String(default="")

    # ── 进度（由 ProgressBridge 写入） ──
    current_stage = param.String(default="")
    stage_progress = param.Number(default=0.0, bounds=(0.0, 1.0))
    stage_statuses = param.Dict(default={})  # {stage_name: "pending"|"completed"|...}
```

### 3.2 state.py — ProgressBridge

将 `PipelineRunner.progress_callback` 桥接到 `AppState` 的 param 属性，使 Panel widget 自动响应更新。

```python
class ProgressBridge:
    """线程安全的 progress_callback → param 属性桥接。"""

    def __init__(self, state: AppState):
        self._state = state

    def callback(self, message: str, fraction: float) -> None:
        """传递给 PipelineRunner 的 progress_callback。

        在后台线程中被调用，通过 pn.state.execute 安全更新 UI。
        """
        import panel as pn
        pn.state.execute(lambda: self._update(message, fraction))

    def _update(self, message: str, fraction: float) -> None:
        self._state.current_stage = message
        self._state.stage_progress = fraction
```

### 3.3 session_form.py — Session 配置面板

| Widget | 绑定到 | 类型 | 约束 |
|--------|--------|------|------|
| session_dir 选择器 | `state.session_dir` | `pn.widgets.TextInput` + 浏览按钮 | 目录必须存在且含 `*_g[0-9]*` 子目录 |
| bhv_file 选择器 | `state.bhv_file` | `pn.widgets.TextInput` + 浏览按钮 | 文件必须存在且以 `.bhv2` 结尾 |
| output_dir 选择器 | `state.output_dir` | `pn.widgets.TextInput` + 浏览按钮 | 可以不存在（会自动创建） |

验证逻辑：所有路径填写后显示绿色勾；缺失项显示红色提示。

### 3.4 subject_form.py — Subject 元信息表单

| 字段 | Widget 类型 | 默认值 | 约束 |
|------|-------------|--------|------|
| subject_id | TextInput | "" | 必填 |
| description | TextInput | "" | 可选 |
| species | TextInput | "Macaca mulatta" | 必填 |
| sex | Select | "M" | ["M", "F", "U", "O"] |
| age | TextInput | "" | 必填，ISO 8601 duration (如 "P3Y") |
| weight | TextInput | "" | 必填 (如 "10kg") |

支持从 YAML 文件加载预填（`load_subject_config(yaml_path)` → 填充表单）。

### 3.5 pipeline_form.py — Pipeline 参数面板

按分组折叠面板展示所有 `PipelineConfig` 子配置：

| 分组 | 配置类 | 参数 |
|------|--------|------|
| Resources | `ResourcesConfig` | n_jobs (`auto`/int), chunk_duration (`auto`/str), max_memory (`auto`/str) |
| Parallel | `ParallelConfig` | enabled (bool), max_workers (`auto`/int) |
| Bandpass | `BandpassConfig` | freq_min (float, 300.0), freq_max (float, 6000.0) |
| Bad Channel | `BadChannelConfig` | method (str), dead_channel_threshold (float) |
| Common Ref | `CommonReferenceConfig` | reference (`global`/`local`), operator (`median`/`mean`) |
| Motion Correction | `MotionCorrectionConfig` | method (`dredge`/`kilosort`/None), preset (str) |
| Curation | `CurationConfig` | isi_violation_ratio_max, amplitude_cutoff_max, presence_ratio_min, snr_min |
| Sync | `SyncConfig` | sync_bit, event_bits, max_time_error_ms, 等 |
| Postprocess | `PostprocessConfig` | slay_pre_s, slay_post_s, eye_validation.enabled, eye_threshold |

`"auto"` 字段用 Switch + 数值输入组合：开关打开时显示 "auto"，关闭时用户输入具体数值。

### 3.6 sorting_form.py — Sorting 参数面板

| 参数 | Widget 类型 | 默认值 |
|------|-------------|--------|
| sorter name | Select | "kilosort4" |
| mode | Select | "local" / "import" |
| nblocks | IntInput | 15 |
| Th_learned | FloatInput | 7.0 |
| do_CAR | Checkbox | False |
| batch_size | auto/int | "auto" |
| n_jobs | IntInput | 1 |
| import_path | TextInput | (mode=import 时显示) |

GPU 检测状态指示器：调用 `ResourceDetector().detect()` 显示 GPU 可用性。

### 3.7 stage_selector.py — Stage 选择器

7 个 Checkbox，按 `STAGE_ORDER` 排列。全选/全不选按钮。

```
[✓] discover     [✓] preprocess   [✓] sort
[✓] synchronize  [✓] curate       [✓] postprocess   [✓] export
```

下方显示依赖提示：选了 `export` 但没选 `sort` → 警告"export 依赖 sort 的输出"。

### 3.8 run_panel.py — 执行控制面板

| 按钮/状态 | 行为 |
|-----------|------|
| **Run** 按钮 | 1. 从各表单收集参数构建 `SubjectConfig`, `PipelineConfig`, `SortingConfig`<br>2. 调用 `SessionManager.create(...)` 创建 session<br>3. 创建 `PipelineRunner(session, pipeline_config, sorting_config, progress_callback=bridge.callback)`<br>4. 在 `threading.Thread` 中调用 `runner.run(stages=...)`<br>5. 完成后更新 `state.run_status` |
| **Stop** 按钮 | 设置中断标志（需要 pipeline 层支持 — M2 scope 内暂用线程终止） |
| 状态文字 | `idle` → "Ready" / `running` → "Running stage: {name}" / `completed` → "Pipeline complete" / `failed` → "Error: {msg}" |

### 3.9 progress_view.py — 进度可视化

7 行，每行一个 stage：

```
discover      ████████████████████ 100%  ✓  (3.2s)
preprocess    ██████████░░░░░░░░░░  52%  ⏳ (imec0: done, imec1: running)
sort          ░░░░░░░░░░░░░░░░░░░░   0%  -
...
```

每行绑定到 `state.stage_statuses[stage_name]`，通过 `ProgressBridge` 更新。

### 3.10 log_viewer.py — 日志面板

使用 `pn.pane.HTML` 或 `pn.widgets.Terminal` 实时显示 structlog 输出。

实现方式：
1. 添加一个自定义 structlog processor 将日志事件写入 `collections.deque(maxlen=500)`
2. Panel `pn.state.add_periodic_callback(update_log, period=1000)` 定期刷新显示

### 3.11 status_view.py + session_loader.py — 状态查看与恢复

**status_view**：
- 输入：`output_dir` 路径
- 调用 `SessionManager.load(output_dir)` → `PipelineRunner(session, ...).get_status()`
- 渲染状态表（同 CLI `status` 命令的输出格式）
- 每个 stage 行尾有 "Reset" 按钮 → 调用 `CheckpointManager.clear(stage)` + 清理 per-probe checkpoints

**session_loader**：
- 选择已有 output_dir → 读取 `session.json` → 自动填充 session_form + subject_form
- 显示当前状态 → 用户可修改参数后点 Run 断点续跑

---

## 4. 线程模型

```
UI 主线程 (Panel/Tornado)
    │
    ├── 用户交互 → 读写 AppState param 属性
    │
    └── 点击 Run →  创建 threading.Thread(target=_run_pipeline)
                        │
                        ├── PipelineRunner.run() (可能跑数小时)
                        │     └── stage.run() 内部调用 progress_callback
                        │           └── ProgressBridge.callback(msg, frac)
                        │                 └── pn.state.execute(lambda: state.update(...))
                        │                       └── UI 自动刷新（param watch 机制）
                        │
                        └── 完成/异常 → 更新 state.run_status
```

关键点：
- `progress_callback` 在后台线程中调用，必须通过 `pn.state.execute()` 将 param 更新调度回 UI 线程
- `AppState` 上的 `param.watch()` 自动触发 widget 刷新，无需手动管理

---

## 5. 依赖

| 依赖 | 类型 | 说明 |
|------|------|------|
| `panel>=1.0` | 第三方，optional `[ui]` | Web UI 框架 |
| `param` | 第三方（Panel 自带） | 响应式参数系统 |
| `pynpxpipe.pipelines.runner` | 项目内部 | `PipelineRunner`, `STAGE_ORDER` |
| `pynpxpipe.core.session` | 项目内部 | `SessionManager`, `SubjectConfig` |
| `pynpxpipe.core.config` | 项目内部 | `load_pipeline_config`, `load_sorting_config`, `load_subject_config`, 所有 Config dataclass |
| `pynpxpipe.core.checkpoint` | 项目内部 | `CheckpointManager`（status/reset） |
| `pynpxpipe.core.resources` | 项目内部 | `ResourceDetector`（GPU 检测显示） |
| `pynpxpipe.core.errors` | 项目内部 | `PynpxpipeError`（错误分类） |

---

## 6. 入口

```toml
# pyproject.toml
[project.optional-dependencies]
ui = ["panel>=1.0"]

[project.scripts]
pynpxpipe-ui = "pynpxpipe.ui.app:main"
```

启动方式：
- `pynpxpipe-ui` — 直接启动浏览器
- `panel serve src/pynpxpipe/ui/app.py --show` — 开发模式

---

## 7. 测试策略

| 层次 | 方法 | 工具 |
|------|------|------|
| 组件单元测试 | 实例化各 component，mock AppState，验证 param 绑定和回调 | pytest + param |
| ProgressBridge 测试 | 模拟后台线程调用 callback，验证 AppState 属性更新 | pytest + threading |
| 集成测试 | `panel.io.server` 启动临时服务器，mock PipelineRunner，验证完整流程 | pytest + panel.io |
| 端到端（可选） | Playwright 操作浏览器，验证用户交互 | playwright |

---

## 8. 实施阶段对应关系

| 阶段 | Session 数 | 内容 | 产出文件 |
|------|-----------|------|----------|
| **A1** | 1 | pyproject.toml + 目录结构 + spike test（按钮+进度条+mock） | ui/__init__.py, app.py, state.py |
| **A2** | 2 | 5 个表单组件 + Subject YAML 加载 | components/session_form.py ~ stage_selector.py |
| **A3** | 2 | ProgressBridge + 线程执行 + 进度可视化 + 日志面板 | run_panel.py, progress_view.py, log_viewer.py |
| **A4** | 1 | Status 查看 + Reset + Session 恢复 | status_view.py, session_loader.py |
| **A5** | 1 | 布局整合 + 错误处理 + 入口命令 + 测试 | app.py 完善, tests/test_ui/ |
