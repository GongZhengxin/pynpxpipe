# UI 改版：以 Session 为中心的工作流

> 状态：**已确认**（§7、§8，2026-11-26） | 日期：2026-11-26
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
- 方案：保留 `PipelineForm` 的 Auto-Merge 卡片及其开关作为唯一来源（它写入 `merge.enabled`），只去掉重复；`StageSelector` 的 merge 勾选改为只读显示，并附说明"在参数中开启"（见 §7 问题 1）。

**P0-4 从此阶段重跑：确认弹窗**（设计稿 `RerunConfirm.dc.html`）

- `StatusView` 的 Reset 按钮改名为"从此阶段重跑…"，点击后打开模态框（用模板的 modal 区域，`template.open_modal()`）。
- 模态框内容：
  1. 范围：全部探针；若该阶段属于 `PER_PROBE_STAGES`，可以只选某一根探针。
  2. 将清除：该阶段**及其下游所有阶段**中实际存在的检查点文件，逐条列出路径。
  3. 将保留：上游结果。若某探针的 `01_preprocessed/{probe_id}.zarr` 已不存在（runner 在 `preprocess.delete_zarr_after_postprocess` 开启且 postprocess 完成后会删除它；以文件实际是否存在为准），此时必须提示"需要连同 preprocess 一起重跑"，并把 preprocess 也加入清除列表。
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

- 最近打开的输出目录存到项目目录下（具体路径在 P1-2 开工前确认，需加入 `.gitignore`；见 §7 问题 3），每次加载 session 或运行时更新。
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
- 只重跑 `select_segments` 不会触发重新同步，但单段模式下它目前会覆盖自己的输入 `04_sync/behavior_events.parquet`，重复运行会损坏数据。**前置条件**：先单独开 PR 修复 select_segments，使其不再覆盖输入（见 §7 问题 5）。

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

- 最近 session 列表（项目目录下）的最大条目数（默认 20）。
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

## 7. 用户确认的问题（状态：已确认，2026-11-26）

1. 自动合并开关以 `PipelineForm` 为唯一来源、`StageSelector` 只读显示，这样可以吗？
   - **已确认**：只去重。保留 `PipelineForm` 的 Auto-Merge 卡片及开关，`StageSelector` 的 merge 勾选改为只读。
2. `pd_hignline_*` 是否是 "highline" 的笔误？若是笔误，要不要另开 PR 修改字段名并兼容旧 YAML？本次只改界面标签。
   - **已确认**：是笔误，沿用自 MATLAB 变量名 `hignline`（`docs/ground_truth/step4_full_pipeline_analysis.md:617`）。另开 PR 改字段名并兼容旧 YAML；本改版只改界面标签。
3. 最近 session 列表存在 `~/.pynpxpipe/` 下可以吗？还是存到项目目录？
   - **已确认**：存到项目目录。具体文件路径在 P1-2 开工前确认，并加入 `.gitignore`。
4. "待确认任务时段"状态用标记文件持久化，可以吗？
   - **已确认**：可以，使用 `checkpoints/task_window_pending.json`。
5. 只重跑 `select_segments` 是否依赖重新执行 `synchronize`？需要核实 `stages/select_segments.py` 的输入。
   - **核实结果**：不重新执行 synchronize，只读取其产物（`04_sync/sync_tables.json`、`trial_intervals.parquet`、`behavior_events.parquet`，见 `select_segments.py:96-140`）；runner 在 `stages=["select_segments"]` 时也不补跑 synchronize。但单段模式下 `sync_dir` 与输出的 `04_sync` 是同一目录，select_segments 会覆盖自己读取的 `behavior_events.parquet`（`select_segments.py:276`，`stim_onset_imec_s` 变为 JSON 字符串、`attempt_id` 加前缀），重复运行会损坏数据；联合模式不受影响。
   - **已确认**：修复 select_segments，使其不再覆盖输入。作为 core 层改动单独开 PR，是 P1-4 的前置条件。
6. 主题：保留深色作为默认，还是按设计稿改为浅色，深色作为选项？
   - **已确认**：按设计稿默认浅色，深色可选（与 §5 一致）。
7. P1-5 的按探针进度采用方案 A（不改回调签名），可以吗？
   - **已确认**：采用方案 A。`BaseStage._report_progress` 已加 `"stage:"` 前缀（`stages/base.py:80`），在 message 中约定 `probe_id` 字段，由 UI 解析。

## 8. P1 细化（状态：已确认，2026-11-26）

本节把 §4.3 落到数据契约与改动范围，依据是设计稿（9 张画板与 `docs/design/ui_redesign/` 一致）加源码核对。设计稿只规定"长什么样"，下面补的是"数据从哪来、谁负责写、失败怎么办"。确认后 P1 按 §8.10 的 session 顺序连续实施，整期完成后集中验收。

### 8.0 已定决策（2026-11-26，用户逐条确认）

| # | 设计稿要求 | 源码现状 | 决定 |
|---|---|---|---|
| 1 | 开始后可关闭浏览器，回首页看进度 | 运行线程属于单个浏览器会话（`run_panel.py` 的 `threading.Thread`），其他会话看不到 | **做**：运行登记文件 + 进程级运行管理器（§8.2） |
| 2 | 各阶段预计用时、预计 sort 用时 | 无估算器；日志里有 `stage_complete.elapsed_s` | **按历史日志估算**（§8.4） |
| 3 | BHV2 选择项显示 trial 数、开始时间 | 只能完整解析 BHV2 | **只显示文件名、大小、修改时间** |
| 4 | 参数页分组卡（中文标签、说明、互斥提示）与全部参数搜索 | 需要字段元数据（P2 schema） | **推迟到 P2**；P1 第 3 步沿用现有表单 + 预设条 |
| 5 | 失败页"按建议修改并重跑" | `Classifier` 只给文字 `suggestion` | **扩展 Classifier** 给出结构化参数修改（§8.6） |
| 6 | 预填该动物上次填写的脑区 | 无历史存储 | **从最近 session 的 `session.json` 读 `probe_plan`**（§8.7） |

### 8.1 前置独立 PR（不属于 UI，先于对应 P1 子项合入）

- **select_segments 不覆盖输入**（P1-4 的前置）：单段模式下 `04_sync/behavior_events.parquet` 既是输入又被改写（`select_segments.py:276`）。方案：首次运行时把 synchronize 的原表保存为 `04_sync/behavior_events_source.parquet`（已存在则不覆盖），之后一律从它读取；输出路径不变，下游无感。单独写 spec（`docs/specs/task_segments.md` 增补）并 TDD。
- **`pd_hignline_*` → `pd_highline_*`**：加载旧键时映射并记 warning，保存只写新键。

### 8.2 运行登记与运行管理器（P1-2/P1-4/P1-5 共用）

- **登记文件** `{output_dir}/checkpoints/run_state.json`，原子写入，字段：`run_id`、`pid`、`started_at`、`heartbeat_at`、`stages`（本次计划）、`current_stage`、`current_probe`、`fraction`、`status`（`running` / `awaiting_confirmation` / `completed` / `failed` / `stopped`）、`error`（首行）、`log_path`。
- 由新模块 `pipelines/run_state.py` 读写（零 UI 依赖）；`PipelineRunner` 不改签名，用包装后的 `progress_callback` 更新进度，心跳间隔 `ui.heartbeat_s`（默认 5 s）。
- **判定"运行中"**：`status == running` 且心跳距今 < `ui.heartbeat_timeout_s`（默认 60 s）且 pid 存活；否则显示"已中断"，可续跑。
- **进程级运行管理器** `ui/run_manager.py`：模块级单例，持有运行线程和中断事件，按 `output_dir` 去重（同一目录不允许并行两次运行）。浏览器会话只订阅：`pn.state.add_periodic_callback` 每 `ui.poll_s`（默认 2 s）读登记文件刷新界面。关闭浏览器不影响运行；关闭 `pynpxpipe-ui` 进程会终止运行，界面文案改为"可以关闭浏览器标签页，但不要关闭运行 pynpxpipe-ui 的终端"。
- "停止"按钮设置中断事件，在当前阶段结束后停止（与现有 `run_panel` 行为一致）。

### 8.3 最近 session 列表（P1-2）

- 存储：`<项目根>/.pynpxpipe/recent_sessions.json`，加入 `.gitignore`。条目：`output_dir`、`name`、`subject_id`、`probe_ids`、`last_opened`。上限 `ui.recent_sessions_max`（默认 20）。
- 更新时机：加载已有输出目录、开始运行。路径不存在的条目显示为灰色并可移除，不自动删除。
- 每行状态由 `read_pipeline_status` + `run_state.json` + `task_window_pending.json` 合成；9 段色条：完成 / 运行中 / 待确认 / 失败 / 未开始 / 跳过（merge 未开启）。
- 顶部 4 个计数与行点击跳转按 §4.3 P1-2。

### 8.4 预计用时（P1-3 第 4 步、P1-4、P1-5）

- 新模块 `pipelines/estimates.py`：扫描最近 session 的 `logs/*.log`，取 `stage_complete` 事件的 `elapsed_s`，除以该 session 保留的记录时长（`03_segments/summary.json`，无则用 AP 时长），得到每阶段（per-probe 阶段按探针）秒/记录秒的中位数。
- 只有样本数 ≥ `ui.eta_min_samples`（默认 3）的阶段才显示估算，其余显示"—"；旁注"基于 N 个历史 session"。不区分 GPU 型号，若当前 GPU 与样本不同则加注"不同硬件，仅供参考"。
- 任务时段试算中的"预计 sort 用时"用同一比率乘以试算保留时长。

### 8.5 按探针进度（P1-5，方案 A）

- `BaseStage` 新增 `_report_probe_progress(probe_id, message, fraction)`，发出 `"{stage}:[{probe_id}] {message}"`；per-probe 阶段改用它。回调签名不变，CLI 显示不受影响。
- UI 用 `^\[(?P<probe>[^\]]+)\] ` 解析；不带前缀的消息归为阶段级。

### 8.6 Classifier 结构化建议（P1-6）

- `ErrorClassification` 增加 `suggested_changes: tuple[tuple[str, object], ...]`（点号键、建议值）与 `probe_id: str | None`。只对能确定修改方向的已知模式填写，初始两条：CUDA OOM → `sorter.params.batch_size` 取当前值的 2/3（下限 `ui.min_batch_size`，默认 10000）；DREDge 内存不足 → `preprocess.motion_correction.bin_s` 加倍。
- 失败页"按建议修改并重跑"：把修改应用到当前表单（复用 `preset_bar._replace_path`），然后打开 P0-4 重跑弹窗，范围预选失败探针。无结构化建议时只显示文字与"问 AI 助手"（`ChatHelp`，附当前配置与日志尾部）。

### 8.7 动物与探针（P1-3 第 2 步）

- 档案卡来自 `monkeys/*.yaml`（`load_subject_config`）；"+ 新动物"展开现有 `SubjectForm`。
- 探针行由第 1 步识别结果决定；脑区预填：在最近 session 中找同一 `subject_id` 最新的 `session.json`，按相同 `probe_id` 取 `probe_plan`。输入提示列出该动物在最近 session 中用过的全部脑区。

### 8.8 与设计稿的有意差异

- BHV2 选择项不显示 trial 数与开始时间（决定 3）。
- 第 3 步不做分组卡与全部参数搜索（决定 4）。
- 重跑弹窗只清除检查点，不删除 sorting 输出目录（P0-4 已实现；重跑的阶段会覆盖输出）。
- 机器状态（GPU / RAM / 磁盘）每 `ui.poll_s` 刷新，来自 `ResourceDetector`，探测失败时隐藏对应项。

### 8.9 新增可配参数

`ui.heartbeat_s`（5）、`ui.heartbeat_timeout_s`（60）、`ui.poll_s`（2）、`ui.recent_sessions_max`（20）、`ui.eta_min_samples`（3）、`ui.min_batch_size`（10000）。存放在 `config/ui.yaml`（新文件，缺省时用默认值），不进入 `PipelineConfig`。

### 8.10 P1 session 拆分（每个 ≤ 5 个源文件）

| Session | 内容 | 主要文件 |
|---|---|---|
| S5 | 前置 PR：select_segments 不覆盖输入 | `stages/select_segments.py`，`docs/specs/task_segments.md` |
| S6 | 运行登记 + 运行管理器（§8.2） | 新 `pipelines/run_state.py`、`ui/run_manager.py`，`ui/components/run_panel.py`，`ui/state.py` |
| S7 | P1-1 路由与顶栏 | `ui/app.py`，新 `ui/router.py`、`ui/components/top_bar.py` |
| S8 | P1-2 Session 列表 | 新 `ui/components/session_list.py`、`ui/recent_sessions.py`，`ui/app.py` |
| S9 | P1-3 向导外壳 + 第 1、2 步 | 新 `ui/components/wizard.py`，`session_form.py`，`subject_form.py`，`probe_region_editor.py` |
| S10 | P1-3 第 3、4 步 + 预计用时 | `wizard.py`，新 `pipelines/estimates.py`，`harness/preflight.py`（只读调用） |
| S11 | P1-4 任务时段确认页 | 新 `ui/components/task_window_page.py`，`task_timeline.py`，`pipelines/run_state.py` |
| S12 | P1-5 工作区 + 按探针进度 | 新 `ui/components/workspace.py`，`stages/base.py`，per-probe stages 的进度调用，`log_viewer.py` |
| S13 | P1-6 失败视图 + Classifier 扩展 | `harness/classifier.py`，新 `ui/components/error_view.py`，`workspace.py` |

S6 之后 S7–S13 依赖其登记文件；S11 依赖 S5 合入。每个 session 仍按 TDD 流程，`progress.md` 逐个更新。
