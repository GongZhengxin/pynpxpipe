# M2 实施方案与 Session 接续策略

## 1. M1 工作方式复盘

### 做得好的

- **implement-module skill + TDD 流水线**：spec → RED → GREEN → REFACTOR → lint → progress.md 更新，流程清晰，每个 session 产出可验证
- **spec 先行**：详细的输入/输出/步骤/测试范围规格文档，使 AI 在新 session 中能快速对齐上下文
- **progress.md 作为状态锚点**：每次 session 完成后更新，新 session 读取即知全局进度
- **mock 隔离**：业务层与 IO 层完全 mock，测试快速且不依赖真实数据/硬件
- **context 压缩指令**：`压缩已完成任务上下文` 有效延长单 session 工作量

### 需要改进的

| 问题 | 影响 | M2 对策 |
|------|------|---------|
| 单 session 上下文有限（~200k token） | 复杂模块（如 postprocess 26 tests）接近极限，需要压缩 | 将 UI 组件拆分为更小的独立 session 单元 |
| spec 与实现偶尔偏差（如 `si.load_extractor` → `si.load`） | 运行时发现 spec 过期 | spec 中标注"已验证"字段 vs "待验证"假设 |
| 跨 session 状态丢失 | 新 session 无法感知上个 session 的具体调试经验 | 关键决策和 gotcha 记录到 CLAUDE.md |
| `--enable-auto-mode` 下偶尔一个 session 完成 2+ 模块 | 压缩后 context 质量下降 | M2 中一个 session 只做一个阶段任务 |

---

## 2. M2 Session 规划

### 轨道 A — Panel Web UI

| Session | 任务 | 输入上下文 | 产出 | 验收 |
|---------|------|-----------|------|------|
| **A-S1** | A1 基础设施 | `docs/specs/ui.md` §3.1-3.2 | `ui/__init__.py`, `app.py`, `state.py`, spike test 可运行 | `panel serve app.py` 显示按钮+进度条 |
| **A-S2** | A2.1-A2.3 表单(上) | `docs/specs/ui.md` §3.3-3.5 + A-S1 产出 | `session_form.py`, `subject_form.py`, `pipeline_form.py` | 表单可填写，值绑定到 AppState |
| **A-S3** | A2.4-A2.5 + A3.1 表单(下)+桥接 | `docs/specs/ui.md` §3.6-3.7, §3.8 top | `sorting_form.py`, `stage_selector.py`, ProgressBridge | Sorting 表单 + stage 选择器 + bridge 单元测试 |
| **A-S4** | A3.2-A3.4 执行+进度+日志 | `docs/specs/ui.md` §3.8-3.10 | `run_panel.py`, `progress_view.py`, `log_viewer.py` | mock pipeline 能在 UI 中跑通全流程 |
| **A-S5** | A4 状态+恢复 | `docs/specs/ui.md` §3.11 | `status_view.py`, `session_loader.py` | 已有 output_dir 能加载+显示状态+reset |
| **A-S6** | A5 整合+测试 | 全部组件 | `app.py` 完善, `tests/test_ui/`, pyproject.toml | 全部 UI 测试通过，端到端可用 |

### 轨道 B — Pure-Python BHV2

| Session | 任务 | 输入上下文 | 产出 | 验收 |
|---------|------|-----------|------|------|
| **B-S1** | B1 逆向工程 | `docs/specs/bhv2_reader.md` §2 + mlbhv2.m + 真实 bhv2 文件 | `docs/specs/bhv2_binary_format.md`, ground-truth JSON fixtures | 格式文档完整，fixtures 覆盖 11 trials |
| **B-S2** | B2.1-B2.2 Reader 实现 | `docs/specs/bhv2_reader.md` §4.1 + B-S1 格式文档 | `io/bhv2_reader.py` + `tests/test_io/test_bhv2_reader.py` | Reader 对 ground-truth 逐字段 exact match |
| **B-S3** | B2.3-B2.5 Parser 替换+回归 | `docs/specs/bhv2_reader.md` §4.2 + §6 | `io/bhv.py` 重写, `io/_bhv_matlab.py` | 全量 pytest 通过（779+ tests） |
| **B-S4** | B3 集成+PR | B-S3 完成 | pyproject.toml, 兼容性开关, PR | `feat/pure-python-bhv2` merge 到 main |

---

## 3. Session 接续协议

每个 session 开始和结束时遵循的标准流程：

### Session 开始时

```
1. 读取 docs/progress.md           → 了解全局进度
2. 读取 docs/ROADMAP.md            → 确认当前里程碑和下一个任务
3. 读取对应的 spec 文档             → 了解要实现的内容
4. 读取 CLAUDE.md                  → 项目约定和已知陷阱
5. git status + git log --oneline -5  → 了解最近变更
```

### Session 结束时

```
1. 确保代码通过 lint (ruff check + ruff format)
2. 确保测试通过 (uv run pytest 相关测试 -q)
3. 更新 docs/progress.md           → 标记完成的阶段
4. 如有新发现的陷阱/决策，更新 CLAUDE.md
5. git add + commit（如果用户要求）
```

### 跨 Session 传递的关键信息

不依赖 context 压缩，而是依赖**文件系统**：

| 信息类型 | 存储位置 | 说明 |
|----------|---------|------|
| 全局进度 | `docs/progress.md` | 哪些阶段完成了 |
| 下一步计划 | `docs/ROADMAP.md` | 当前在哪个 session |
| 技术规格 | `docs/specs/*.md` | 每个模块怎么实现 |
| 项目约定 | `CLAUDE.md` | 命名、测试、lint 规则 |
| 已知陷阱 | `CLAUDE.md` 技术债节 | 如 `si.load` vs `si.load_extractor` |
| 代码本身 | `src/` + `tests/` | 最权威的状态来源 |

**原则**：新 session 只读以上文件即可完全恢复上下文，无需依赖对话历史。

---

## 4. 新 Session 启动模板

用户在新 session 中只需发送如下指令：

```
请阅读 docs/progress.md 和 docs/ROADMAP.md，确认当前进度。
然后使用 implement-module skill 实现下一个阶段任务。
```

或者更精确：

```
请阅读 docs/specs/ui.md，实现 A-S2（表单组件上半部分：session_form, subject_form, pipeline_form）。
参考 docs/progress.md 确认前置任务已完成。
```

---

## 5. 轨道 B 分支管理

```bash
# B-S1 开始时
git checkout -b feat/pure-python-bhv2

# B-S1 ~ B-S3 在此分支上工作
# 每个 session 结束时 commit

# B-S4 合并
git checkout main
git merge feat/pure-python-bhv2
git branch -d feat/pure-python-bhv2
```

注意：轨道 A 在 main 分支上工作，轨道 B 在 feature 分支。两者文件不重叠（A 在 `ui/`，B 在 `io/`），merge 不会冲突。

---

## 6. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| Panel API 在实际使用中有坑（如文件选择器跨平台问题） | 中 | A-S1/A-S2 延期 | A1 spike test 提前验证关键路径 |
| BHV2 格式逆向不完整（未覆盖的类型） | 中 | B-S2 阻塞 | B1 阶段充分分析 mlbhv2.m 所有分支 |
| progress_callback 粒度不够（只有 stage 级，无 probe 级） | 低 | A3 进度显示粗糙 | 检查 BaseStage._report_progress 实际调用点 |
| 测试文件太大无法提交到 git | 低 | B1 fixtures 管理 | 用 git-lfs 或只提交小型 JSON 摘录 |

---

## 7. 建议实施顺序

```
A-S1 → A-S2 → A-S3 → B-S1 → B-S2 → A-S4 → A-S5 → B-S3 → B-S4 → A-S6
 UI基础  表单上  表单下  逆向   Reader  执行进度 状态恢复 Parser  合并   整合
```

理由：
- 先做 A-S1~S3 建立 UI 骨架，用户可以提前试用表单部分
- 穿插 B-S1~S2 做逆向+Reader，利用等待反馈的间隙
- A-S4~S5 需要 mock pipeline 跑通，是 UI 的核心价值
- B-S3~S4 最后合并，因为它改动现有代码，风险最高
- A-S6 最后整合测试，确保一切工作

总计约 10 个 session。
