# CLAUDE.md

## 知识图谱导航

`graphify-out/GRAPH_REPORT.md` 存在时，**在回答任何架构、模块关系、设计决策问题之前，先读该文件**。

图谱包含：
- **God Nodes**（核心抽象，最多边节点）：`Session`, `ConfigError`, `ProbeInfo`, `SortingConfig`, `PipelineConfig`, `BaseStage` — 理解这六个节点等于理解项目骨架
- **社区结构**（26 个聚类）：核心基础设施 / 配置系统 / 同步流程 / UI 层 / 各 Stage 群组
- **Surprising Connections**（跨文件隐含依赖）：架构文档 → 实现模块的隐含契约
- **Suggested Questions**：`ConfigError` 为何是全图桥接节点？`Session` 的 76 条 INFERRED 边哪些需要核查？

用图谱**定位**目标节点，再用 Read/Glob/Grep 查看源码。禁止在没有图谱线索时盲目 grep 整个 src/。

---

## 项目概述

pynpxpipe：神经电生理数据预处理工具包。
输入：SpikeGLX 录制数据文件夹（含 AP/LF/NI 三类数据流，支持多 probe）+ MonkeyLogic BHV2 行为文件
输出：标准 NWB 格式文件（一个 session 一个 NWB，包含所有 probe 的数据）

当前开发阶段：M2（UI + Pure-Python BHV2）。M1 已完成（22/22 模块，779 tests）。路线图见 `docs/ROADMAP.md`，进度见 `docs/progress.md`。

## 核心设计原则

1. **多探针优先**：所有模块以 probe_id 为参数，支持 N 个 IMEC 探针。单探针是 N=1 的特例。
2. **断点续跑**：每个 stage 完成后写 checkpoint。Pipeline 启动时检查 checkpoint，跳过已完成 stage。
3. **资源感知**：AP bin 可达 400-500GB，禁止一次性加载，必须用 SpikeInterface lazy recording 或分块处理。每 stage 结束 `del` 大对象 + `gc.collect()`。`n_jobs`/`chunk_duration`/`max_memory` 从配置读取，支持 `"auto"` 自动探测。
4. **零硬编码**：采样率、通道 ID、事件码、探针编号等全部从数据 meta 或配置文件读取，代码中禁止 magic number。
5. **日志完备**：所有 stage 操作写 JSON Lines 结构化日志（时间戳、stage 名、probe_id、参数、耗时、状态）。
6. **远程 sorting 兼容**：sorting stage 支持本地运行和导入外部结果两种模式。
7. **前后端分离**：CLI 是"薄壳入口"。core/io/stages/pipelines 层禁止 import click，禁止 print，禁止 sys.exit()。未来 GUI 只是另一个薄壳入口。

## Pipeline Stages（按顺序执行）

1. **discover** — 扫描 SpikeGLX 文件夹，发现 probes，验证数据完整性
2. **preprocess** — phase shift → bandpass → 坏道检测 → CMR → 运动校正(可选) → Zarr
3. **sort** — Kilosort4 via SpikeInterface，或导入外部 sorting 结果
4. **synchronize** — IMEC↔NIDQ 时钟对齐 → BHV2↔NIDQ 事件匹配 → Photodiode 校准
5. **curate** — SpikeInterface quality_metrics + Bombcell 分类
6. **postprocess** — SortingAnalyzer 扩展计算 + SLAy 自动合并 + 眼动验证
7. **export** — 整合写入 NWB 文件

每个 stage 的摘要见 `docs/architecture.md`（~500 行架构总纲），模块级详细设计见下方 Spec 索引。

## 模块 Spec 索引

<!-- 新增 spec 时同步更新此表 -->

**L0 — Core（基础设施，零业务依赖）**

| 模块 | Spec 路径 | 摘要 |
|------|----------|------|
| config | `docs/specs/config.md` | YAML 配置加载、默认值填充、类型验证 |
| checkpoint | `docs/specs/checkpoint.md` | JSON checkpoint 读写，原子写入，断点续跑 |
| resources | `docs/specs/resources.md` | 自动探测 CPU/RAM/GPU/磁盘，推算 n_jobs/chunk_duration |
| logging | `docs/specs/logging.md` | JSON Lines 结构化日志 + stderr 人类可读输出 |
| session | `docs/specs/session.md` | Session/SubjectConfig/ProbeInfo dataclass + SessionManager 工厂 |
| base | `docs/specs/base.md` | Stage 抽象基类，集成 checkpoint/logging/进度回调 |

**L1 — IO（数据读写，零 UI 依赖）**

| 模块 | Spec 路径 | 摘要 |
|------|----------|------|
| spikeglx | `docs/specs/spikeglx.md` | SpikeGLX 数据发现、meta 解析、AP/NIDQ lazy 加载 |
| bhv | `docs/specs/bhv.md` | BHV2→MATLAB Engine→.mat→h5py 桥接，提供 TrialData 列表 |
| nwb_writer | `docs/specs/nwb_writer.md` | NWB 2.x 文件组装与写盘（DANDI 兼容） |
| imec_nidq_align | `docs/specs/imec_nidq_align.md` | IMEC↔NIDQ sync 脉冲线性回归对齐 |
| bhv_nidq_align | `docs/specs/bhv_nidq_align.md` | BHV2↔NIDQ 事件码序列匹配，输出 trial 级事件表 |
| photodiode_calibrate | `docs/specs/photodiode_calibrate.md` | Photodiode 模拟信号校准，检测 stimulus onset 延迟 |
| sync_plots | `docs/specs/sync_plots.md` | 6 张同步诊断 PNG 图表（matplotlib 可选依赖） |

**L2 — Stages（处理阶段，零 UI 依赖）**

| 模块 | Spec 路径 | 摘要 |
|------|----------|------|
| discover | `docs/specs/discover.md` | 扫描 SpikeGLX 目录，验证数据完整性，填充 session.probes |
| preprocess | `docs/specs/preprocess.md` | phase_shift→bandpass→坏道→CMR→运动校正→Zarr |
| sort | `docs/specs/sort.md` | KS4 本地运行或导入外部 sorting 结果 |
| synchronize | `docs/specs/synchronize.md` | 三级时间对齐编排（调用 io/sync/* 子模块） |
| curate | `docs/specs/curate.md` | quality_metrics 计算 + Bombcell 分类 + 阈值过滤 |
| postprocess | `docs/specs/postprocess.md` | SortingAnalyzer 扩展 + SLAy 自动合并 + 眼动验证 |
| export | `docs/specs/export.md` | 整合写入 NWB 文件（调用 io/nwb_writer） |

**L3 — Orchestration（编排与入口）**

| 模块 | Spec 路径 | 摘要 |
|------|----------|------|
| runner | `docs/specs/runner.md` | Pipeline 编排：断点续跑、资源配置、子集执行 |
| cli_main | `docs/specs/cli_main.md` | CLI 薄壳入口：run / status / reset-stage 三个命令 |

**L4 — UI（Panel Web UI，零业务逻辑）**

| 模块 | Spec 路径 | 摘要 |
|------|----------|------|
| ui | `docs/specs/ui.md` | Panel Web UI：表单配置 + 执行控制 + 进度追踪 + 状态恢复 |

**Pure-Python BHV2（替换 MATLAB Engine 依赖）**

| 模块 | Spec 路径 | 摘要 |
|------|----------|------|
| bhv2_reader | `docs/specs/bhv2_reader.md` | 纯 Python BHV2 二进制解析器，兼容现有 BHV2Parser API |

**实施规划**

| 文档 | 路径 | 说明 |
|------|------|------|
| M2 实施方案 | `docs/specs/m2_implementation_plan.md` | Session 规划、接续协议、风险评估 |

## 技术栈

- Python >= 3.11
- spikeinterface >= 0.104（内置 Bombcell 和 SLAy）
- probeinterface, pynwb >= 2.8, neo
- numpy, scipy, pandas
- click（CLI）, pyyaml（配置）, structlog（日志）, psutil（资源探测）
- panel >= 1.0（Web UI，optional `[ui]`）
- uv（包管理，pyproject.toml 为唯一依赖声明）

## 目录结构

```
src/pynpxpipe/
  cli/              # CLI 薄壳（仅依赖 click + pipelines 层）
    main.py
  ui/               # Panel Web UI（仅依赖 panel + pipelines 层）
    app.py, state.py, components/
  core/             # 核心对象（零 UI 依赖）
    session.py, checkpoint.py, logging.py, config.py, resources.py, errors.py
  io/               # 数据读写（零 UI 依赖）
    spikeglx.py     # SpikeGLX 数据发现与加载
    bhv.py          # MonkeyLogic BHV2 解析（Pure-Python，可选 MATLAB 后端）
    bhv2_reader.py  # BHV2 二进制格式底层读取器
    nwb_writer.py   # NWB 文件生成
    sync/           # 同步子模块
      imec_nidq_align.py, bhv_nidq_align.py, photodiode_calibrate.py
    sync_plots.py   # 诊断图（可选依赖 matplotlib）
  stages/           # 处理阶段（零 UI 依赖）
    base.py         # Stage 基类（checkpoint/logging/进度回调）
    discover.py, preprocess.py, sort.py, synchronize.py
    curate.py, postprocess.py, export.py
  pipelines/
    runner.py       # Pipeline 编排（断点续跑、资源配置）
config/             # 默认配置模板（pipeline.yaml, sorting.yaml）
monkeys/            # Subject 配置（每只动物一个 yaml）
tests/
  test_core/, test_io/, test_stages/, test_cli/, test_ui/, test_integration/
docs/
  architecture.md   # 架构总纲（Stage 详细设计、ADR、NWB 结构、配置体系）
  specs/            # 模块级 spec（每模块一个 md）
  ground_truth/     # MATLAB 参考实现逐步解析 + 新旧对比
  progress.md       # 开发进度追踪
  ROADMAP.md        # 里程碑路线图
```

## 代码规范与文档

### 代码风格

- 所有函数和类必须有 type hints
- 私有函数用 `_` 前缀
- 配置项在 YAML 定义，代码通过 config 对象访问，禁止 magic number
- 测试文件与被测模块同名（`test_spikeglx.py` ↔ `spikeglx.py`）
- 使用 ruff lint + format（配置见 pyproject.toml）

### Docstring 规范

使用 Google style。分级要求：

| 级别 | 适用范围 | 要求 |
|------|---------|------|
| **必须** | 公开类、公开方法、公开函数 | 完整：摘要 + Args + Returns + Raises |
| **必须** | Stage 子类的 `run()` 和关键私有方法 | 完整（pipeline 核心逻辑） |
| **推荐** | 复杂私有函数（>15 行或含非显然算法） | 至少一句话摘要 |
| **不写** | 简单私有辅助、test 函数、仅赋值的 `__init__` | 函数名应自解释 |

### 行内注释规则

- 只在逻辑非显然处加注释（算法选择原因、边界情况、硬件约束）
- 禁止重复代码含义的注释（`# increment counter` 等）
- 引用 MATLAB 参考实现时标注步骤号：`# cf. MATLAB step #10: polarity correction`
- TODO 格式：`# TODO(username): description`，禁止无署名 TODO

## 开发流程（harness 原则）

每个模块**必须**严格按以下顺序，禁止跳步：

1. **写 spec**：在 `docs/specs/{模块名}.md` 回答五个问题（目标 / 输入 / 输出 / 处理步骤 / 可配参数）
2. **用户确认 spec**
3. **TDD — RED**：先写测试，运行确认全部失败（功能缺失，非语法错误）
4. **TDD — GREEN**：写最小实现使测试通过
5. **lint**：`uv run ruff check src/ tests/` + `ruff format` 通过
6. **更新进度**：`docs/progress.md` 对应行状态改为 `✅`

**即使模块已有骨架代码（`raise NotImplementedError`），也必须先补写 spec 才能开始 TDD。**

### Spec 写作规则

- 写 spec 前**必须**阅读 `docs/architecture.md` 对应 Section
- 涉及 MATLAB 已实现算法的模块（synchronize 及其子模块、postprocess），**必须**同时阅读 `docs/ground_truth/step4_full_pipeline_analysis.md` 中对应步骤编号
- Spec 中**必须**包含"与 MATLAB 参考实现的关系"小节，列出有意偏离及理由
- IO 模块的 spec 写作前**必须**读 `docs/ground_truth/step2_input_consumption.md & bhv2_consumption_analysis.md` 确认实际数据格式，不得凭假设

### 开发进度追踪

每完成一个模块（测试全绿 + ruff 通过），立即将 `docs/progress.md` 中对应行状态更新。

## CC 单 Session 工作模式

每个 CC session 聚焦 **1 个模块**（或 2-3 个紧耦合模块）。

### Session 启动仪式

1. 读 `docs/ROADMAP.md` 确认当前里程碑和 Phase
2. 读 `docs/progress.md` 找到实现队列中下一个"阻塞已解除"的 🟡 模块
3. 向用户报告："本次 session 目标：{模块名}，涉及文件：{列表}"

### Session 执行流程

4. 读 `docs/specs/{模块}.md` 全文
5. 读上游模块的输出 dataclass 定义（确认接口）
6. TDD-RED：写测试，运行确认全部失败
7. TDD-GREEN：写最小实现，逐个测试变绿
8. `uv run ruff check src/ tests/` + `uv run ruff format src/ tests/`
9. 更新 `docs/progress.md`：状态 🟡→✅，填写测试数

### Session 收尾

10. 向用户报告完成情况 + 下一个建议模块

### 禁止事项

- 一个 session 内不修改非目标模块的 spec 或实现
- 不"顺便"实现下游模块
- 发现 spec 缺陷时记录 TODO，不在本 session 修
- 单 session 改动文件 <= 5 个（不含测试文件和 progress.md）
- 不跳过 TDD-RED 直接写实现

### ROADMAP 与 progress.md 治理规则

`docs/ROADMAP.md` 是**战略文档**（做什么、为什么），`docs/progress.md` 是**战术文档**（做到哪了）。

| 操作 | 执行者 | 时机 |
|------|--------|------|
| 读 ROADMAP | CC | 每个 session 开头 |
| 更新 ROADMAP Phase 状态 | CC | 某 Phase 最后一个模块完成时，标记该 Phase 为 ✅ |
| 更新 progress.md 模块状态 | CC | 每个模块完成时（🟡→✅ + 填测试数） |
| 调整里程碑定义/优先级 | **仅用户** | 需求变更时 |
| 新增/移除 Backlog | **仅用户** | 随时 |
| 决定下一个里程碑 | **仅用户** | 当前里程碑完成时 |

**CC 不得**自行调整里程碑范围、增删 Backlog 条目、或变更 Phase 内的模块顺序。

## 开发工具链

```bash
uv run pytest                           # 运行全部测试
uv run pytest tests/path/test.py -v    # 运行单个测试文件
uv run pytest --cov=pynpxpipe --cov-fail-under=80  # 覆盖率检查
uv run ruff check src/ tests/          # Lint
uv run ruff format src/ tests/         # Format
uv run jupyter lab                     # JupyterLab
uv run pytest --nbmake tutorials/      # 自动执行 notebook（CI）
```

**禁止**：`pip install`（uv 管理依赖）、`python -m pytest`（绕过 venv）、`pip install -e .`

## 版本控制

### 分支策略

- **main** — 稳定分支，所有合并必须通过 PR + CI 绿灯
- **dev/{module}** — 单模块开发分支（如 `dev/photodiode-calibrate`），完成后 squash merge 到 main
- **feature/{name}** — 跨模块功能分支（如 `feature/pure-python-bhv2`），可长期存在
- 禁止直接 push 到 main（配置 branch protection 后生效）
- 每个 PR 对应 `docs/progress.md` 中一个或多个模块状态变更

### Commit 规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/) 格式：`<type>(<scope>): <subject>`

| type | 含义 | 示例 scope |
|------|------|-----------|
| `feat` | 新功能 | `discover`, `preprocess`, `sync` |
| `fix` | Bug 修复 | `bhv`, `spikeglx` |
| `test` | 仅测试变更 | `test_discover` |
| `docs` | 文档变更 | `specs`, `architecture`, `claude` |
| `refactor` | 重构（不改行为） | `session`, `base` |
| `chore` | 构建/工具/依赖 | `deps`, `ci` |

- subject 用英文祈使句，首字母小写，不加句号
- breaking change 加 `!`：`feat(config)!: rename sync_bit to sync_pulse_bit`

### 版本号

遵循 SemVer。当前 `0.x.y` 阶段：
- `0.1.y` — Layer 0-1 基础设施 + IO
- `0.2.y` — 全部 stages 可运行
- `0.3.y` — NWB 输出验证通过 + tutorials 完备
- `1.0.0` — 首个生产版本（pure-python BHV2 + 多 session 批处理）

版本号仅在 `pyproject.toml` 中维护，禁止在代码中硬编码版本字符串。

### CHANGELOG

项目根目录维护 `CHANGELOG.md`，遵循 [Keep a Changelog](https://keepachangelog.com/) 格式。CC 在创建 PR 时自动更新 `[Unreleased]` 区块，发布版本时重命名为 `[0.x.y] - YYYY-MM-DD`。

## CI/CD

### 本地检查（提交前必过）

```bash
uv run ruff check src/ tests/                       # lint
uv run ruff format --check src/ tests/               # format 检查
uv run pytest --tb=short                             # 全量测试
uv run pytest --cov=pynpxpipe --cov-fail-under=80    # 覆盖率 >= 80%
```

### GitHub Actions（.github/workflows/ci.yml）

CI 在 PR 和 push to main 时触发：

| Step | 命令 | 失败即终止 |
|------|------|-----------|
| Lint | `uv run ruff check src/ tests/` | 是 |
| Format | `uv run ruff format --check src/ tests/` | 是 |
| Test | `uv run pytest --cov=pynpxpipe --cov-fail-under=80` | 是 |
| Notebooks | `uv run pytest --nbmake tutorials/` | 是 |

- CI 环境：Ubuntu latest + Python 3.11
- 跳过 MATLAB/GPU/真实数据测试：`-m "not matlab and not gpu and not integration"`

### pytest 标记约定

| 标记 | 含义 | CI 中行为 |
|------|------|----------|
| `@pytest.mark.matlab` | 需要 MATLAB Engine | CI 跳过 |
| `@pytest.mark.gpu` | 需要 CUDA GPU | CI 跳过 |
| `@pytest.mark.slow` | 运行 > 30s | 默认跳过，`--runslow` 启用 |
| `@pytest.mark.integration` | 需要真实数据文件 | CI 跳过 |
| 无标记 | 纯单元测试（mock） | CI 运行 |

## Windows 兼容

- 路径用 `pathlib.Path`，禁止手写 `/` 或 `\\`
- 文件读写指定 `encoding='utf-8'`
- 注意 SpikeGLX 输出路径的 Windows 260 字符限制

## 从旧代码迁移

参照 `docs/ground_truth/step5_matlab_vs_python.md` 和 `docs/legacy_analysis.md`。关键原则：

- 旧代码所有硬编码值（采样率、探针名 imec0、事件码 64 等）全部参数化
- 用 SpikeInterface 公开 API 替代私有属性（`neo_reader.signals_info_dict` 等）
- 预处理链顺序：phase_shift **必须在** bandpass_filter 之前（旧代码顺序错误）
- Photodiode 校准必须包含极性校正（旧 Python 代码缺失，MATLAB 有）
- IMEC↔NIDQ 对齐必须包含丢脉冲修复逻辑（旧 Python 代码缺失，MATLAB 有）
- DREDge 运动校正与 KS4 内部 nblocks 互斥，二选一
