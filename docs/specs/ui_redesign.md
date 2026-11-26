# UI 改版：以 Session 为中心的工作流

> 状态：**待用户确认** | 日期：2026-11-26
> 设计稿：`docs/design/ui_redesign/`（在线画布见该目录 README）
> 关联：`docs/specs/ui.md`、`docs/specs/a5_app_layout.md`、`docs/specs/ui_improvements_plan.md`、`docs/specs/task_segments.md`

本 spec 按 CLAUDE.md 要求回答五个问题，并给出分期和每个 CC session 的改动范围（每个 session 改动文件不超过 5 个，测试文件与 `progress.md` 除外）。**P0 可以在用户确认后开工；P1/P2 各自开工前还要再确认一次本文对应章节。**

---

## 1. 目标

把 Web UI 从"按组件平铺"（Configure / Execute / Review / Help）改成"按用户任务组织"：

1. 新建 session：一步步完成数据 → 动物与探针 → 参数 → 检查并运行。
2. 已有 session：一眼看到进度、诊断图和失败原因，并能安全地从某个阶段重跑。
3. 任务时段：先预览，调参后即时试算，应用后确认，再继续后续阶段。

不改变 core / io / stages / pipelines 的行为（例外见 §4.3 P1-5，需单独确认）。UI 层仍然零业务逻辑。

## 2. 输入

- `AppState`（`ui/state.py`）及现有组件的公开方法：`apply_subject`、`apply_pipeline`、`apply_sorting`、`apply_paths`、`load_status`、`load_figures`、`load_saved_preview`。
- 配置：`load_pipeline_config` / `load_sorting_config` / `save_pipeline_config` / `save_sorting_config` / `_config_to_dict`（`core/config.py`），预设文件 `config/pipeline*.yaml`、`config/sorting*.yaml`。
- 状态：`read_pipeline_status`（`pipelines/status.py`）、`CheckpointManager.clear(stage, probe_id)`（`core/checkpoint.py`）、`STAGE_ORDER` / `PER_PROBE_STAGES`（`pipelines/constants.py`）。
- 运行前检查和报错归类：`PreflightChecker`（`harness/preflight.py`）、`Classifier.classify(exc, traceback_str)`（`harness/classifier.py`）。
- 任务时段：`TimelineData.load` / `TimelineData.select`（`ui/components/task_timeline.py`）、`select_task_windows`（`core/segments.py`）、`TaskWindowConfig`。

## 3. 输出

- 新的 UI 组件与布局（Panel），全部在 `src/pynpxpipe/ui/` 下。
- `tests/test_ui/` 下的新增和更新测试。
- `docs/specs/ui.md` 的布局章节与本 spec 同步；`docs/progress.md` 按完成情况更新。

## 4. 处理步骤

### 4.1 统一约定（所有期次）

- 语言：界面文案统一为中文；参数在中文标签下方用等宽小字显示 dataclass 键名（如 `task_window.max_idle_s`）；单位作为输入框后缀。
- 按钮文案以动词开头（"应用试算""从此阶段重跑…"），每屏只有一个主按钮。
- 错误文案先说发生了什么，再说怎么办；原始异常折叠显示。
- 危险操作（清除检查点、合并）必须先弹确认，说明影响范围。
- 视觉规格见 `docs/design/ui_redesign/README.md`。

### 4.2 P0：不改信息架构的快速改进

**P0-1 数据发现结果卡**（设计稿 `WizardData.dc.html` 中的绿色和黄色卡片）

- `SessionForm` 已计算的 `discovery_status`、`validation_message` 必须渲染出来（目前只存成属性，界面上看不到）。
- `_discover_paths` 改为返回全部候选：
  - gate 目录多于 1 个：用 `Select` 让用户选，默认选第一个，并显示提示。
  - `.bhv2` 多于 1 个：同样处理。
- 识别成功后列出探针（id、型号、序列号、通道数、AP 文件大小）。从 meta 读取时复用 `io/spikeglx.py` 的解析函数，UI 层不写解析逻辑。
- 识别成功后自动读取采集日期，填入 `recording_date`。保留"Detect Date"按钮作为手动重试。

**P0-2 参数预设与差异**（设计稿 `WizardParams.dc.html` 中的顶部预设条和右侧"差异"卡）

- 新组件 `ui/components/preset_bar.py`：
  - 列出 `config/` 下的预设。按后缀配对：`pipeline_E2.yaml` 对 `sorting_E2.yaml`；某个后缀缺 pipeline 文件时（如 E1、E3）回退到 `pipeline.yaml`，并在界面上注明。
  - 选中预设：调用 `load_*_config`，再调 `PipelineForm.apply_pipeline` 和 `SortingForm.apply_sorting`。
  - "导入 YAML…"：读取用户指定的文件。
  - "导出为 YAML"：调用 `save_*_config` 写出当前配置。
- 差异计算：把当前配置和所选预设各自经 `_config_to_dict` 展平成点号路径，逐项比较，得到 `[(key, preset_value, current_value)]`。
  - 显示"已改 N 项"徽章和差异列表，每项带"恢复"。
  - 被改过的字段在表单里加标记（左侧圆点或边框变色）。
- `pd_hignline_*` 的界面标签：只改显示文字，**不改 dataclass 字段名**（见 §7 问题 2）。

**P0-3 自动合并只保留一个开关**

- 现状：`StageSelector` 有 merge 勾选，`PipelineForm` 的"Auto-Merge"卡片里还有一个，两者重复。
- 方案：保留 `PipelineForm` 的开关作为唯一来源（它写入 `merge.enabled`），删除 Auto-Merge 卡片；`StageSelector` 的 merge 勾选改为只读显示，并附说明"在参数中开启"（见 §7 问题 1）。

**P0-4 从此阶段重跑：确认弹窗**（设计稿 `RerunConfirm.dc.html`）

- `StatusView` 的 Reset 按钮改名为"从此阶段重跑…"，点击后打开模态框（用模板的 modal 区域，`template.open_modal()`）。
- 模态框内容：
  1. 范围：全部探针；若该阶段属于 `PER_PROBE_STAGES`，可以只选某一根探针。
  2. 将清除：该阶段**及其下游所有阶段**中实际存在的检查点文件，逐条列出路径。
  3. 将保留：上游结果。若某探针的 postprocess 已完成，runner 已删除它的 preprocess Zarr，此时必须提示"需要连同 preprocess 一起重跑"，并把 preprocess 也加入清除列表。
  4. 本次参数变化：当前配置与该 session 的 `used_pipeline.yaml` / `used_sorting.yaml` 的差异，复用 P0-2 的差异函数。
- 确认后才执行清除。取消时不触碰任何文件。
- **注意**：现有 Reset 只清除当前阶段，下游检查点仍是 completed，runner 会跳过下游，结果和上游对不上。连带清除下游是正确性修复，不只是交互改进。

**P0-5 顶栏状态与文案统一**

- 侧边栏的灰色小字 `Status: idle` 改成顶栏的彩色状态徽章，颜色按 §4.1 规定；失败时附简短原因。
- 按 §4.1 统一 `session_form`、`subject_form`、`pipeline_form`、`sorting_form`、`stage_selector` 的标签文案。

### 4.3 P1：信息架构重组

**P1-1 路由与外壳**

- 用 `pn.state.location` 做 URL 路由：`?view=sessions|new|session&dir=<output_dir>&stage=<name>`，刷新页面不丢位置。
- 去掉侧边栏导航，改为顶栏：logo、Sessions、新建、帮助、机器状态（GPU、内存、磁盘，取自 `ResourceDetector`）。

**P1-2 Session 列表首页**（`Main.dc.html`）

- 最近打开的输出目录存到 `~/.pynpxpipe/recent_sessions.json`（见 §7 问题 3），每次加载 session 或运行时更新。
- 每行显示：名称、输出路径、动物、探针、9 段阶段色条（来自 `read_pipeline_status`）、状态徽章、更新时间。
- 顶部 4 个计数：运行中、待你确认、失败、已导出。
- 点击行的跳转：待确认 → 任务时段页；失败 → 工作区的报错视图；其他 → 工作区。
- 替代现有的两个 `SessionLoader`；"打开已有输出目录…"保留为入口。

**P1-3 新建向导**（4 步，复用现有表单组件，只重新编排）

1. 数据：P0-1 的发现结果卡。"多段联合"改为"+ 添加同一天的另一段记录"，列表支持拖动排序，取代模式切换按钮和长段说明。
2. 动物与探针：从 `monkeys/*.yaml` 选择动物档案，选中后只读显示，点"编辑档案"才展开 `SubjectForm`；探针脑区的行数由第 1 步识别出的探针决定，并预填该动物上次填写的脑区。
3. 参数：P0-2 的预设条，加上常用参数分组卡（任务时段、同步、预处理、Sorting、质控、自动合并）。全部参数的搜索放在 P2。
4. 检查并运行：
   - 显示摘要，以及 `PreflightChecker` 结果的清单（pass / warn / fail 三态）。
   - 运行方式二选一："先对齐，确认任务时段后再继续"（默认）或"直接全部运行"。
   - 显示将执行的阶段和预估时长。没有可靠的估算依据时不显示时长。
- 草稿自动保存在 `AppState` 中，跳转到其他步骤不会丢失。

**P1-4 任务时段确认页**（`TaskWindow.dc.html`）

- 进入条件：选择"先对齐"后，runner 执行 `stages=["discover","synchronize","select_segments"]`，完成后 session 进入"待确认"状态。
  - 状态持久化为输出目录下的标记文件，例如 `checkpoints/task_window_pending.json`，确认后删除（见 §7 问题 4）。
- 页面内容：
  - 顶部 5 个指标：trial 对齐、最大同步残差、有刺激 trial、空 trial、探针元数据兼容，均来自已保存的预览摘要。
  - 时间轴沿用 `TaskTimeline` 的四种图层。新增：在被切开的空闲段上画斜线，并标注时长。
  - 参数：最大连续空闲、任务前保留、任务后保留用滑块，绑定 `value_throttled`，松手即调用 `TimelineData.select(cfg)` 试算，删除"刷新试算"按钮。滑块下方列出所有长于 30 s 的 trial 间隙，标明在当前阈值下是"切开"还是"保留"。
  - 结果对比表："已保存"与"当前试算"两列（任务块数、保留时长、比原始减少、任务块明细），并检查有刺激 trial 是否全部落在保留区内；若有遗漏，标红并列出被遗漏的 trial。
- 底栏两种状态：
  - 试算与已保存不同：显示"恢复已保存参数"和"应用试算"。应用 = 写入新的 `TaskWindowConfig`，清除 `select_segments` 检查点，只重跑 `select_segments`。
  - 两者一致：显示"稍后再确认"和"确认并继续 preprocess"。确认 = 删除待确认标记，运行剩余阶段。
- 需要核实：只重跑 `select_segments` 时，是否会触发重新同步（见 §7 问题 5）。

**P1-5 Session 工作区**（`Workspace.dc.html`）

- 阶段轨道：9 个阶段，显示状态、耗时或进度。点击某个阶段，下方切换到该阶段的详情。
- 阶段详情：
  - 按探针显示的进度条和计数。
  - 日志面板：级别筛选（全部 / 警告 / 错误）、"仅本阶段"、搜索、自动滚动开关。
  - 操作：查看本阶段参数、"从此阶段重跑…"（P0-4）、sort 阶段另有"改用外部 sorting 结果…"。
  - 诊断图：按阶段归组，复用 `FigsViewer`。
- "续跑 NWB 导出"（`ResumeExportPanel`）和"重算衍生数据"（`RerunDerivatives`）移到 export 阶段的操作区。
- **涉及 pipelines 层**：按探针显示进度，需要 `progress_callback` 携带 probe_id。当前签名是 `(message, fraction)`，且 message 已带 `"stage:"` 前缀。方案 A：在 message 中约定 `"stage:probe_id:..."` 格式，UI 负责解析，不改签名；方案 B：扩展签名。**本条单独确认，推荐方案 A。**

**P1-6 失败视图**（`ErrorState.dc.html`）

- 阶段失败时，用 `Classifier.classify(exc, traceback_str)` 生成原因和建议。
- 若归类结果给出了具体的参数修改，提供"按建议修改并重跑"，并走 P0-4 的确认弹窗；没有具体修改时只显示建议文字。
- 原始 traceback 折叠显示。
- 同时显示其他探针的状态（例如"imec0 已完成，不受影响"）。

### 4.4 P2

- **schema 驱动表单**：在 `core/config.py` 各 dataclass 字段上加 `metadata={"label","help","unit","level","stage"}`，由通用渲染器生成控件、双向绑定和差异对比，替换 `pipeline_form.py` 中手写的字段映射。需单独写 spec，因为它会改到 core 层。
- **全部参数**：搜索、"只看已改"筛选。
- **帮助抽屉**：`ChatHelp` 从顶级页面改为右侧抽屉，每个字段旁加 `?` 提示，文本来自 schema 的 help。
- **批量排队**：多个 session 依次运行。

## 5. 可配参数

- `~/.pynpxpipe/recent_sessions.json` 的最大条目数（默认 20）。
- 任务时段滑块范围：`max_idle_s` 30–600 s，步长 10；`pre_s` / `post_s` 0–120 s，步长 5。超出滑块范围的值可以在旁边的数字框里直接输入。
- 主题：默认浅色，可切换深色（实现方式见 §7 问题 6）。

## 6. 分期与 CC session 拆分

| Session | 内容 | 主要改动文件（不超过 5 个） | 测试 |
|---|---|---|---|
| S1 | P0-1 | `session_form.py` | `test_session_form.py` |
| S2 | P0-2 | 新建 `preset_bar.py`，`pipeline_form.py`，`sorting_form.py`，`app.py` | 新建 `test_preset_bar.py` |
| S3 | P0-3 + P0-4 | `stage_selector.py`，`pipeline_form.py`，`status_view.py` | `test_status_view.py`，`test_components.py` |
| S4 | P0-5 | `app.py`，`subject_form.py`，`sorting_form.py`，`stage_selector.py`，`session_form.py` | 更新涉及标签断言的测试 |
| S5 起 | P1 | 每个子项开工前先补写 spec 细节，再拆分 session | — |

每个 session 都遵循：读本 spec → TDD-RED → TDD-GREEN → `uv run ruff check src/ tests/` 加 `ruff format` → 更新 `docs/progress.md`。

## 7. 待用户确认的问题

1. 自动合并开关以 `PipelineForm` 为唯一来源、`StageSelector` 只读显示，这样可以吗？
2. `pd_hignline_*` 是否是 "highline" 的笔误？若是笔误，要不要另开 PR 修改字段名并兼容旧 YAML？本次只改界面标签。
3. 最近 session 列表存在 `~/.pynpxpipe/` 下可以吗？还是存到项目目录？
4. "待确认任务时段"状态用标记文件持久化，可以吗？
5. 只重跑 `select_segments` 是否依赖重新执行 `synchronize`？需要核实 `stages/select_segments.py` 的输入。
6. 主题：保留深色作为默认，还是按设计稿改为浅色，深色作为选项？
7. P1-5 的按探针进度采用方案 A（不改回调签名），可以吗？
