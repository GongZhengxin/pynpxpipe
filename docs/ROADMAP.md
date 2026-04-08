# Roadmap

## M1 — 复现 MATLAB 预处理（v0.2.0）✅ 已完成

22/22 模块全部实现，779 测试通过。详见 `docs/progress.md`。

**遗留项**（不阻塞 M2）：
- `io/sync_plots.py`：spec 已写，未实现（优先级低，可在 M2 Panel UI 中直接嵌入）
- Phase 5 集成验证：端到端真实数据测试 + NWB DANDI 验证 + MATLAB 数值对比

---

## 当前里程碑：M2 — UI + Pure-Python BHV2（v0.3.0）

### 目标

在 M1 的完整 pipeline 基础上完成两件事：

1. **Panel Web UI**（主分支）：为 pipeline 提供友好的浏览器交互界面，用户无需编写代码即可配置参数、启动运行、监控进度、查看结果
2. **Pure-Python BHV2 解析器**（feature 分支 → merge 主分支）：去除 MATLAB Engine 依赖，用纯 Python 逆向解析 MonkeyLogic BHV2 二进制格式

### 验收标准

- [ ] `panel serve src/pynpxpipe/ui/app.py` 启动后，用户能在浏览器中完成完整 pipeline 运行
- [ ] UI 实时显示 stage 级别和 probe 级别进度（对接已有 `progress_callback`）
- [ ] Pure-Python BHV2Parser 对测试文件输出与 MATLAB 版本逐字段一致
- [ ] `matlabengine` 降为可选依赖（`pip install pynpxpipe` 不再需要 MATLAB）
- [ ] 所有新增代码覆盖率 >= 80%

### 技术选型

**UI 框架：Panel (HoloViz)**

选择理由：
- Pipeline 所有 stage 已有 `progress_callback: Callable[[str, float], None]` — Panel 可零改动对接
- 原生支持 threading/async 长任务，不阻塞 UI（pipeline 单 session 可能运行数小时）
- `param` 库可将 `PipelineConfig`/`SortingConfig` 等 dataclass 映射为表单 widget
- matplotlib 图表可直接嵌入（为未来 sync_plots 做准备）
- 部署简单：`panel serve app.py --show`

---

### 工作轨道 A：Panel Web UI（主分支）

#### A1 — 基础设施搭建

| 任务 | 说明 | 产出 |
|------|------|------|
| A1.1 添加 Panel 依赖 | `pyproject.toml` 新增 `panel>=1.0` 到 optional `[ui]` | pyproject.toml |
| A1.2 创建 UI 模块结构 | `src/pynpxpipe/ui/` 包：`app.py`（入口）、`components/`（可复用组件）、`state.py`（全局状态管理） | 目录结构 |
| A1.3 Panel 原型验证 | 最小可运行原型：一个按钮 + 进度条 + mock pipeline，验证 threading + progress_callback 通路 | spike test |

#### A2 — 配置与元信息表单

| 任务 | 说明 | 产出 |
|------|------|------|
| A2.1 Session 配置面板 | 文件选择器：session_dir（目录）、bhv_file（.bhv2）；输出目录选择 | `components/session_form.py` |
| A2.2 Subject 元信息表单 | subject_id / species / sex / age / weight 表单；支持从 YAML 加载预填 | `components/subject_form.py` |
| A2.3 Pipeline 参数面板 | ResourcesConfig（n_jobs / chunk_duration / max_memory）、ParallelConfig、BandpassConfig 等；"auto" 选项有说明提示 | `components/pipeline_form.py` |
| A2.4 Sorting 参数面板 | SorterConfig（name / params / batch_size）、mode（local / import）；GPU 检测状态显示 | `components/sorting_form.py` |
| A2.5 Stage 选择器 | 多选框选择要运行的 stage；显示依赖关系提示 | `components/stage_selector.py` |

#### A3 — Pipeline 执行与进度追踪

| 任务 | 说明 | 产出 |
|------|------|------|
| A3.1 进度追踪桥接 | 将 PipelineRunner 的 `progress_callback` 桥接到 Panel widget：stage 名称 + 百分比 + 耗时 | `state.py` 中的 ProgressBridge |
| A3.2 执行控制面板 | "Run" 按钮（threading 启动 pipeline）、"Stop"（设置中断标志）、状态文字（idle / running / completed / failed） | `components/run_panel.py` |
| A3.3 Stage 进度可视化 | 7-stage 横向进度条组；per-probe 子进度；当前 stage 高亮 | `components/progress_view.py` |
| A3.4 日志面板 | 实时滚动显示 structlog JSON 日志（过滤级别 INFO+）；错误高亮 | `components/log_viewer.py` |

#### A4 — 结果查看与状态恢复

| 任务 | 说明 | 产出 |
|------|------|------|
| A4.1 Status 面板 | 读取 output_dir 中的 checkpoint，渲染 stage 状态表（对接 `PipelineRunner.get_status()`） | `components/status_view.py` |
| A4.2 Reset-stage 操作 | 右键/按钮重置指定 stage 的 checkpoint，确认对话框 | status_view.py 扩展 |
| A4.3 Session 恢复 | 选择已有 output_dir → 加载 session.json → 自动填充表单 → 显示状态 → 支持断点续跑 | `components/session_loader.py` |

#### A5 — 整合与打磨

| 任务 | 说明 | 产出 |
|------|------|------|
| A5.1 主页面布局 | 侧边栏导航（New Run / Resume / Status）+ 主内容区 | `app.py` |
| A5.2 错误处理 | PynpxpipeError → UI 错误面板（非崩溃）；未预期异常 → 错误报告界面 | app.py |
| A5.3 pyproject.toml 入口 | `[project.scripts]` 添加 `pynpxpipe-ui = "pynpxpipe.ui.app:main"` | pyproject.toml |
| A5.4 测试 | CliRunner 类似的 Panel 测试（`panel.io.server` 或 playwright）；mock pipeline 端到端 | `tests/test_ui/` |

---

### 工作轨道 B：Pure-Python BHV2（feature 分支 `feat/pure-python-bhv2`）

#### 背景

当前 `io/bhv.py` 通过 MATLAB Engine 调用 `mlbhv2.m` 读取 BHV2。这要求用户安装 MATLAB（昂贵且不便携）。BHV2 是 MonkeyLogic 的自定义二进制格式（**不是** HDF5），需要完整逆向。

已有参考材料：
- `docs/ground_truth/bhv2_consumption_analysis.md`：14 个消费点的完整字段需求清单
- `docs/ground_truth/bhv2_verification_report.txt`：真实文件的字段验证结果
- `docs/ground_truth/verify_bhv2_structure.m`：MATLAB 验证脚本
- `legacy_reference/pyneuralpipe/Util/mlbhv2.m`：MATLAB 参考实现

#### B1 — 逆向工程

| 任务 | 说明 | 产出 |
|------|------|------|
| B1.1 BHV2 二进制格式文档 | 用 MATLAB 脚本逐字节 dump 真实 BHV2 文件结构：magic → index → variable offsets → per-trial struct 布局 | `docs/specs/bhv2_binary_format.md` |
| B1.2 MATLAB mlbhv2.m 逻辑分析 | 逐行注释 mlbhv2.m 的 `read()` 方法：如何定位变量、解析嵌套 struct、处理 MATLAB 类型映射 | `docs/specs/bhv2_matlab_analysis.md` |
| B1.3 Ground-truth 数据导出 | 用 MATLAB 对测试文件的每个 Trial 逐字段导出为 JSON/MAT，作为 Python 解析的对照基准 | `tests/fixtures/bhv2_ground_truth/` |

#### B2 — 解析器实现（TDD）

| 任务 | 说明 | 产出 |
|------|------|------|
| B2.1 底层二进制读取器 | `io/bhv2_reader.py`：读取 BHV2 索引表、定位变量偏移、按类型反序列化（uint8/double/char/struct/cell） | `io/bhv2_reader.py` + tests |
| B2.2 Trial 解析层 | 在 reader 之上，将原始数据映射到 `TrialData` dataclass（与现有 `TrialData` 完全兼容） | `io/bhv2_reader.py` 扩展 |
| B2.3 BHV2Parser 替换 | 重写 `io/bhv.py` 的 `BHV2Parser`：`__init__` / `parse()` / `get_event_code_times()` / `get_session_metadata()` / `get_analog_data()` 全部改为调用 bhv2_reader | `io/bhv.py` 重写 |
| B2.4 Ground-truth 验证测试 | 对照 B1.3 的基准数据，逐字段比较 Python 输出 vs MATLAB 输出 | `tests/test_io/test_bhv2_reader.py` |
| B2.5 回归测试 | 确保上层消费者（synchronize / postprocess）的现有测试全部通过 | pytest 全量通过 |

#### B3 — 集成与合并

| 任务 | 说明 | 产出 |
|------|------|------|
| B3.1 依赖清理 | `matlabengine` 移到 `[project.optional-dependencies]` 的 `matlab` 组（已是）；确保无 MATLAB 环境时 `import pynpxpipe` 不报错 | pyproject.toml |
| B3.2 兼容性开关 | 如果用户同时安装了 MATLAB，提供 `BHV2_BACKEND=matlab` 环境变量切换回 MATLAB 解析器（用于对比验证） | `io/bhv.py` |
| B3.3 PR & merge | feature 分支 PR → code review → merge 到 main | Git PR |

---

### 实施顺序与依赖

```
轨道 A（Panel UI）─────────────────────────────────────────────────────
  A1 基础设施 → A2 表单组件 → A3 执行+进度 → A4 结果+恢复 → A5 整合
      │
      └── 主分支持续开发

轨道 B（Pure-Python BHV2）──────────────────────────────────────────────
  B1 逆向工程 → B2 解析器实现 → B3 集成合并 ──→ merge 到主分支
      │
      └── feat/pure-python-bhv2 分支

两条轨道完全独立，可以穿插进行。
建议优先级：A1-A2 → B1-B2 → A3-A4 → B3 → A5
```

**预计工作量**：A 轨道 ~6-8 个 session，B 轨道 ~4-5 个 session

---

## 未来里程碑

### M3 — 多 session 批处理（v0.4.0）

支持一个命令处理整个实验日的所有 session。
新增：`pipelines/batch_runner.py`。修改：`cli/main.py` 增加 batch 命令，UI 增加批量面板。

### Backlog（无排期）

- LFP 处理（`stages/lfp_process.py` + `nwb_writer.add_lfp()` 实现）
- Tutorials 完备（覆盖所有 stage 的用法演示）
- sync_plots 嵌入 UI（Panel + matplotlib）
- 云端 sorting（AWS Batch）
- 实时处理模式
