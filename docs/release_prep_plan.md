# GitHub Release Preparation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare pynpxpipe for public release on GitHub so that other Windows users can install it via `uv add git+https://github.com/GongZhengxin/pynpxpipe.git`, with only necessary files uploaded, while leaving the 45 unrelated in-progress file modifications untouched.

**Architecture:** All edits are scoped to release-facing files (LICENSE, README, .gitignore, pyproject.toml, getting_started.md, CLAUDE.md, docs/progress.md). Already-tracked private/internal files are untracked via `git rm --cached` (on-disk copies preserved). Two clean commits on a renamed `main` branch, then remote add, then pause for user confirmation before push.

**Tech Stack:** git, uv, Python 3.11+

**Spec:** `docs/release_prep_design.md`

**Execution guardrails:**
- Never `git add -A` or `git add .` — always add files explicitly by path so unrelated WIP changes stay out.
- Never run `git commit --amend` — every fix is a new commit.
- Never force-push or rewrite history.
- Never `git push` without the user's explicit go-ahead in the final task.
- Never touch the 45 unrelated M files listed in the initial `git status`.

---

## File Structure

**Created files:**
- `LICENSE` — standard MIT license text, © 2026 GongZhengxin
- `README.md` — bilingual (EN + 中文) storefront

**Modified files:**
- `.gitignore` — replaced with comprehensive exclude list
- `pyproject.toml` — PyPI metadata added (license, urls, classifiers, keywords); build backend unchanged
- `getting_started.md` — rewritten §1 Install section; added short notes for new UI features
- `CLAUDE.md` — updated current-phase paragraph; added `agent/` subtree
- `docs/progress.md` — appended UI S6/S7/S8 rows, updated total test count

**Untracked-but-preserved:** `.claude/settings.local.json`, `docs/superpowers/specs/2025-04-30-b-s1-design.md`, `docs/temp/*.md`, `monkeys/{JianJian,MaoDan}.yaml`, `legacy_reference/` (all), `tests/fixtures/bhv2_ground_truth/` (all).

---

## Task 1: Create LICENSE

**Files:**
- Create: `LICENSE`

- [ ] **Step 1: Write LICENSE with standard MIT text**

Create `LICENSE` with this exact content:

```
MIT License

Copyright (c) 2026 GongZhengxin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Verify file exists**

Run: `ls F:/tools/pynpxpipe/LICENSE`
Expected: file listed, size ~1.1 KB

---

## Task 2: Replace `.gitignore`

**Files:**
- Modify: `.gitignore` (full replacement)

- [ ] **Step 1: Overwrite `.gitignore` with comprehensive exclude list**

Replace the entire content of `.gitignore` with:

```
# Python
__pycache__/
*.py[cod]
*.egg
*.egg-info/
dist/
build/
.eggs/

# Virtualenv
.venv/
venv/

# Test / lint / type cache
.pytest_cache/
.ruff_cache/
.mypy_cache/
.coverage
htmlcov/

# Tool working dirs
.claude/
.superpowers/
.prompt4claude/
.graphify_cached.json
graphify-out/

# IDE
.vscode/
.idea/
*.code-workspace

# Runtime / data outputs
kilosort4_output/
logs/
*.nwb
*.zarr/
*.mat

# Private / internal dirs (not distributed)
legacy_reference/
spec_manifests/
tests/fixtures/bhv2_ground_truth/
docs/audit/
docs/bug_spec/
docs/temp/
docs/superpowers/

# Private subject configs — keep only the template
monkeys/*.yaml
!monkeys/MonkeyTemplate.yaml
```

- [ ] **Step 2: Verify `.gitignore` now lists the expected entries**

Run: `Grep` for `legacy_reference` in `.gitignore` — expected: one match. Run `Grep` for `MonkeyTemplate` — expected: one match.

---

## Task 3: Untrack files that should be excluded

**Files:**
- Git index: remove ~372 entries (on-disk copies preserved)

- [ ] **Step 1: Untrack `.claude/settings.local.json`**

```bash
cd F:/tools/pynpxpipe
git rm --cached .claude/settings.local.json
```

Expected: `rm '.claude/settings.local.json'`

- [ ] **Step 2: Untrack `docs/superpowers/` tracked file**

```bash
git rm --cached docs/superpowers/specs/2025-04-30-b-s1-design.md
```

- [ ] **Step 3: Untrack `docs/temp/` tracked files**

```bash
git rm --cached docs/temp/api_verification_needed.md docs/temp/project_review.md
```

- [ ] **Step 4: Untrack private `monkeys/` yamls**

```bash
git rm --cached monkeys/JianJian.yaml monkeys/MaoDan.yaml
```

- [ ] **Step 5: Untrack the entire `legacy_reference/` tree**

```bash
git rm -r --cached legacy_reference/
```

Expected: hundreds of `rm '...'` lines.

- [ ] **Step 6: Untrack `tests/fixtures/bhv2_ground_truth/`**

```bash
git rm -r --cached tests/fixtures/bhv2_ground_truth/
```

- [ ] **Step 7: Verify that excluded paths are no longer in the index**

```bash
git ls-files | grep -E '^(legacy_reference|tests/fixtures/bhv2_ground_truth|docs/(temp|superpowers)|monkeys/(JianJian|MaoDan)|\.claude/settings)'
```

Expected: **empty output**. If anything matches, it was missed — untrack it before proceeding.

- [ ] **Step 8: Verify on-disk files still exist**

```bash
ls F:/tools/pynpxpipe/monkeys/JianJian.yaml F:/tools/pynpxpipe/legacy_reference/pyneuralpipe/README.md
```

Expected: both files still present on disk (only the git index entries were removed).

---

## Task 4: Create README.md (bilingual)

**Files:**
- Create / overwrite: `README.md` (currently empty)

- [ ] **Step 1: Write the bilingual README**

Overwrite `README.md` with this exact content:

````markdown
# pynpxpipe

**Neural electrophysiology preprocessing pipeline for SpikeGLX multi-probe recordings, producing DANDI-compatible NWB files.**

神经电生理数据预处理流水线：SpikeGLX 多探针录制数据 → 标准 NWB 文件。

---

## Features

- **End-to-end pipeline** — discover → preprocess → sort → synchronize → curate → postprocess → export
- **Multi-probe first** — N Neuropixels probes in one session, single-probe is just N=1
- **Checkpoint-based resume** — every stage writes a checkpoint; pipeline restarts skip completed work
- **Resource-aware** — auto-detects CPU / RAM / GPU, streams 400+ GB AP bins via SpikeInterface lazy recordings
- **Two entry points** — Panel Web UI (`pynpxpipe-ui`) for interactive runs, CLI (`pynpxpipe run`) for scripted / batch use
- **Pure-Python BHV2** — no MATLAB Engine required for MonkeyLogic behavioral files
- **Structured logs** — JSON Lines per stage for downstream analysis

## Installation

Requires Python 3.11 or 3.12 and [uv](https://docs.astral.sh/uv/).

**As a dependency in your own project:**

```bash
# Core only
uv add git+https://github.com/GongZhengxin/pynpxpipe.git

# With Web UI + GPU detection + plots
uv add "pynpxpipe[ui,gpu,plots] @ git+https://github.com/GongZhengxin/pynpxpipe.git"
```

**For development / contributing:**

```bash
git clone https://github.com/GongZhengxin/pynpxpipe.git
cd pynpxpipe
uv sync --all-groups
```

### Optional extras

| Extra | Purpose |
|---|---|
| `ui` | Panel Web UI (`pynpxpipe-ui` command) |
| `gpu` | NVIDIA VRAM detection via `nvidia-ml-py` |
| `plots` | matplotlib-based sync diagnostic figures |
| `chat` | In-UI LLM help assistant (requires your own API key) |
| `matlab` | Fallback MATLAB Engine BHV2 parser (legacy, usually not needed) |

## Quick Start

```bash
# Launch the Web UI (easiest)
uv run pynpxpipe-ui

# Or run the CLI directly
uv run pynpxpipe run \
    D:/data/my_session_g0 \
    D:/data/my_session.bhv2 \
    --subject monkeys/MonkeyTemplate.yaml \
    --output-dir D:/output/my_session
```

Full walkthrough: **[getting_started.md](getting_started.md)**

## Documentation

| Document | Purpose |
|---|---|
| [`getting_started.md`](getting_started.md) | Step-by-step tutorial for first-time users |
| [`docs/architecture.md`](docs/architecture.md) | Architecture overview: stages, configs, NWB layout |
| [`docs/specs/`](docs/specs/) | Per-module design specs |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Milestone plan and backlog |
| [`docs/progress.md`](docs/progress.md) | Module-level status and test counts |

## License

MIT — see [`LICENSE`](LICENSE).

---

# pynpxpipe（中文说明）

神经电生理数据预处理工具包：将 SpikeGLX 多探针录制数据与 MonkeyLogic 行为数据整合，输出符合 DANDI 规范的 NWB 文件。

## 核心特性

- **端到端流水线**：discover → preprocess → sort → synchronize → curate → postprocess → export
- **多探针优先**：单次 session 支持任意数量 Neuropixels 探针
- **断点续跑**：每个阶段写 checkpoint，中断后自动跳过已完成阶段
- **资源感知**：自动探测 CPU/RAM/GPU，以 lazy recording 方式处理 400+ GB 数据
- **双入口**：Panel Web UI（`pynpxpipe-ui`）与 CLI（`pynpxpipe run`）
- **Pure-Python BHV2 解析器**：不再依赖 MATLAB Engine
- **结构化日志**：JSON Lines 格式，便于下游分析

## 安装

需要 Python 3.11 或 3.12，以及 [uv](https://docs.astral.sh/uv/) 包管理器。

```bash
# 仅核心功能
uv add git+https://github.com/GongZhengxin/pynpxpipe.git

# Web UI + GPU 检测 + 诊断图
uv add "pynpxpipe[ui,gpu,plots] @ git+https://github.com/GongZhengxin/pynpxpipe.git"
```

开发者请 clone 仓库后运行 `uv sync --all-groups`。

## 快速开始

```bash
uv run pynpxpipe-ui
```

详细教程请参考 [`getting_started.md`](getting_started.md)。

## 许可

MIT 许可证。
````

- [ ] **Step 2: Verify README builds the right shape**

Run: `Bash wc -l F:/tools/pynpxpipe/README.md`
Expected: ~110 lines (not 0).

---

## Task 5: Update `pyproject.toml` metadata

**Files:**
- Modify: `pyproject.toml:1-32` (the `[project]` table — add fields, do NOT touch dependencies or build-system)

- [ ] **Step 1: Add license/keywords/classifiers/urls to the `[project]` table**

Use the Edit tool to replace the following block:

**Old** (lines 1-9):
```toml
[project]
name = "pynpxpipe"
version = "0.1.0"
description = "Neural electrophysiology preprocessing pipeline for SpikeGLX multi-probe recordings"
readme = "README.md"
authors = [
    { name = "GongZhengxin", email = "1045418215@qq.com" }
]
requires-python = ">=3.11,<3.13"
```

**New:**
```toml
[project]
name = "pynpxpipe"
version = "0.1.0"
description = "Neural electrophysiology preprocessing pipeline for SpikeGLX multi-probe recordings"
readme = "README.md"
license = { text = "MIT" }
authors = [
    { name = "GongZhengxin", email = "1045418215@qq.com" }
]
requires-python = ">=3.11,<3.13"
keywords = [
    "neuroscience",
    "electrophysiology",
    "neuropixels",
    "spikeglx",
    "kilosort",
    "nwb",
    "dandi",
    "spikeinterface",
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Science/Research",
    "License :: OSI Approved :: MIT License",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: POSIX :: Linux",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering",
    "Topic :: Scientific/Engineering :: Bio-Informatics",
]
```

- [ ] **Step 2: Append `[project.urls]` block immediately after `[project.scripts]`**

Use the Edit tool. Insert after line 64 (`pynpxpipe-ui = "pynpxpipe.ui.app:main"`), BEFORE the existing `[build-system]` section:

```toml

[project.urls]
Homepage = "https://github.com/GongZhengxin/pynpxpipe"
Repository = "https://github.com/GongZhengxin/pynpxpipe"
Issues = "https://github.com/GongZhengxin/pynpxpipe/issues"
```

- [ ] **Step 3: Verify toml is still valid**

Run: `cd F:/tools/pynpxpipe && uv run python -c "import tomllib; tomllib.loads(open('pyproject.toml','rb').read().decode())"`
Expected: no output, exit code 0. Any `tomllib.TOMLDecodeError` = broken syntax, fix inline.

- [ ] **Step 4: Verify `uv sync` still works with the new metadata**

Run: `cd F:/tools/pynpxpipe && uv sync --no-dev 2>&1 | tail -5`
Expected: "Resolved N packages" or "Audited N packages" — no errors.

---

## Task 6: Update `getting_started.md`

**Files:**
- Modify: `getting_started.md:13-36` (the `## 1. Install pynpxpipe` section)
- Modify: `getting_started.md:94-103` (UI Overview table — add new UI features)

- [ ] **Step 1: Replace the Install section**

Use Edit to replace lines 13-36 (current content: "## 1. Install pynpxpipe" through "uv run pynpxpipe --help").

**Old:**
```markdown
## 1. Install pynpxpipe

```bash
# Clone the repository
git clone <repo-url>
cd pynpxpipe

# Install with uv (recommended)
uv sync --all-groups

# If you only need the UI (no dev tools):
uv sync --extra ui

# If you also need GPU support:
uv sync --extra ui --extra gpu
```

Verify the installation:

```bash
uv run pynpxpipe --version
uv run pynpxpipe --help
```
```

**New:**
```markdown
## 1. Install pynpxpipe

You have two installation modes depending on your use case.

### Mode A — Consume as a dependency (most users)

Add it to your own uv project:

\`\`\`bash
# Core only
uv add git+https://github.com/GongZhengxin/pynpxpipe.git

# Web UI + GPU detection + diagnostic plots
uv add "pynpxpipe[ui,gpu,plots] @ git+https://github.com/GongZhengxin/pynpxpipe.git"

# Web UI + LLM help assistant
uv add "pynpxpipe[ui,chat] @ git+https://github.com/GongZhengxin/pynpxpipe.git"
\`\`\`

Or with plain pip in a venv:

\`\`\`bash
pip install "pynpxpipe[ui,gpu] @ git+https://github.com/GongZhengxin/pynpxpipe.git"
\`\`\`

### Mode B — Clone for development / contribution

\`\`\`bash
git clone https://github.com/GongZhengxin/pynpxpipe.git
cd pynpxpipe
uv sync --all-groups
\`\`\`

### Verify the installation

\`\`\`bash
uv run pynpxpipe --version
uv run pynpxpipe --help
\`\`\`
```

*(Note: the backticks above are escaped in the plan for display only. In the actual file, use real triple backticks without backslashes.)*

- [ ] **Step 2: Run the Edit tool for Step 1**

Use the Edit tool with `file_path = F:/tools/pynpxpipe/getting_started.md`, with the old/new strings above. Remove the `\\` escapes from the code fences when writing — they must be real triple backticks.

- [ ] **Step 3: Add new UI features to the UI Overview table**

Edit the UI Overview table (around lines 98-103). Replace:

**Old:**
```markdown
| Section | Purpose |
|---------|---------|
| **Configure** | Set input paths, subject metadata, pipeline parameters, sorting options, and select stages |
| **Execute** | Start/stop the pipeline, monitor stage-level and probe-level progress, view real-time logs |
| **Review** | Load previous sessions, inspect checkpoint status, reset stages for re-run |
```

**New:**
```markdown
| Section | Purpose |
|---------|---------|
| **Configure** | Set input paths, subject metadata, pipeline parameters, sorting options, and select stages. Subject forms can now be saved as reusable YAML files. |
| **Execute** | Start/stop the pipeline, monitor stage-level and probe-level progress, view real-time logs |
| **Review** | Load previous sessions, inspect checkpoint status, reset stages for re-run, browse generated figures via the **Figures Viewer**, and ask questions via the **Chat Help** panel (requires `chat` extra + API key) |
```

- [ ] **Step 4: Verify the updated file**

Run: `Grep` for `uv add git+` in `getting_started.md`. Expected: 2+ matches (Mode A block).

---

## Task 7: Update `CLAUDE.md` — current phase + directory tree

**Files:**
- Modify: `CLAUDE.md:22-23` (current phase paragraph)
- Modify: `CLAUDE.md:168-208` (directory structure block — add `agent/` subtree)

- [ ] **Step 1: Locate the "当前开发阶段" paragraph**

Read `CLAUDE.md` lines 20-26 to confirm the current content. You're looking for a line that starts with `当前开发阶段：M2`.

- [ ] **Step 2: Update the current-phase line**

Use Edit. Replace:

**Old:**
```
当前开发阶段：M2（UI + Pure-Python BHV2 + 生产环境验证）。M1 已完成（22/22 模块，779 tests）。路线图见 `docs/ROADMAP.md`，进度见 `docs/progress.md`。新用户教程见 `docs/getting_started.md`。
```

**New:**
```
当前开发阶段：M2（UI + Pure-Python BHV2 + 生产环境验证）。M1 已完成（22/22 模块，779 tests）。M2 Panel UI 主体已完成（含 Chat Help / Figures Viewer / SubjectForm save-yaml），当前总测试数 ~1160。路线图见 `docs/ROADMAP.md`，进度见 `docs/progress.md`。新用户教程见 `getting_started.md`。
```

- [ ] **Step 3: Add `agent/` to the directory structure code block**

Read `CLAUDE.md` around lines 168-210 to find the directory tree. Insert a new entry for the agent module right after the `ui/` subtree and before `core/`.

Use Edit. Replace:

**Old:**
```
  ui/               # Panel Web UI（仅依赖 panel + pipelines 层）
    app.py, state.py, components/
  core/             # 核心对象（零 UI 依赖）
```

**New:**
```
  ui/               # Panel Web UI（仅依赖 panel + pipelines 层）
    app.py, state.py, components/
  agent/            # LLM 辅助层（UI Chat Help / self-check harness）
    llm_client.py, chat_harness.py
  core/             # 核心对象（零 UI 依赖）
```

- [ ] **Step 4: Verify both edits landed**

Run: `Grep` for `~1160` in `CLAUDE.md` — expected: 1 match. `Grep` for `agent/` — expected: 1+ match in the directory tree block.

---

## Task 8: Update `docs/progress.md`

**Files:**
- Modify: `docs/progress.md` — append UI S6/S7/S8 rows + fix records + update total test count

- [ ] **Step 1: Verify the exact current test count**

Run: `cd F:/tools/pynpxpipe && uv run pytest --collect-only -q 2>&1 | tail -3`
Expected: a line like `NNNN tests collected in X.XXs`. Record the actual number (should be around 1160).

- [ ] **Step 2: Add UI S6/S7/S8 rows to the "轨道 A" table**

Read `docs/progress.md` lines 70-85 to confirm the table shape. Use Edit to append new rows after the `UI S5` row.

**Old (the last table row):**
```
| UI S5 | Pipeline/Sorting form 与 core/config.py 对齐 | ✅ | pipeline_form +16 widgets, sorting_form +7 analyzer widgets, harness 4 coverage tests（+40 tests，193 total） |
```

**New:**
```
| UI S5 | Pipeline/Sorting form 与 core/config.py 对齐 | ✅ | pipeline_form +16 widgets, sorting_form +7 analyzer widgets, harness 4 coverage tests（+40 tests，193 total） |
| UI S6 | Chat Help（LLM 助手） | ✅ | src/pynpxpipe/agent/{llm_client,chat_harness}.py + ui/components/chat_help.py，optional `[chat]` extra，self-check harness |
| UI S7 | Figures Viewer | ✅ | ui/components/figs_viewer.py — Review 区浏览 pipeline 产物图表 |
| UI S8 | SubjectForm save-yaml 按钮 | ✅ | subject_form.py — 当前填写的 subject 一键导出为 monkeys/*.yaml |
```

- [ ] **Step 3: Add a "修复与改进" subsection immediately after the 轨道 A table**

Use Edit to insert a new subsection between the end of the 轨道 A block (around line 84) and the `### 轨道 B` line. The current source has:

```
| UI S5 | ... 193 total） |

### 轨道 B — Pure-Python BHV2（feature 分支）
```

After Step 2's edit, it will look like:

```
| UI S8 | SubjectForm save-yaml 按钮 | ✅ | ... |

### 轨道 B — Pure-Python BHV2（feature 分支）
```

Now insert the fixes block. Replace:

**Old:**
```
| UI S8 | SubjectForm save-yaml 按钮 | ✅ | subject_form.py — 当前填写的 subject 一键导出为 monkeys/*.yaml |

### 轨道 B — Pure-Python BHV2（feature 分支）
```

**New:**
```
| UI S8 | SubjectForm save-yaml 按钮 | ✅ | subject_form.py — 当前填写的 subject 一键导出为 monkeys/*.yaml |

#### 修复与改进（M2 期间）

| Commit | 说明 |
|--------|------|
| `fix(sync)` | 移除废案 `imec_sync_code` 字段，清理同步接口 |
| `fix(config)` | `SorterParams.nblocks` 默认值 15→0，避免与 DREDge 运动校正的双重漂移校正冲突 |

### 轨道 B — Pure-Python BHV2（feature 分支）
```

- [ ] **Step 4: Update the M1 overall test count line if needed**

The M1 header says `完成：22/22 模块 | 测试：779 passed | 覆盖率：~80%` — leave this alone (it's an M1 snapshot).

Instead, append a new line at the bottom of the file recording the current total. Read the last 5 lines of `docs/progress.md` to find the bottom, then Edit to append:

**Old (the very last lines of the file — the 技术债 table):**
```
| `docs/specs/nwb_writer.md` 步骤 add_trials | 写 `TimeIntervals + add_time_intervals`，但 pynwb 2.8 此路径不设置 `nwbfile.trials`，实现改用 `add_trial_column + add_trial` | 低 |
```

**New:**
```
| `docs/specs/nwb_writer.md` 步骤 add_trials | 写 `TimeIntervals + add_time_intervals`，但 pynwb 2.8 此路径不设置 `nwbfile.trials`，实现改用 `add_trial_column + add_trial` | 低 |

---

**当前全量测试数（2026-04-14 首次 GitHub 发布前）**：<fill in the exact number from Task 8 Step 1> tests collected。
```

Replace the `<fill in…>` placeholder with the actual integer from Step 1.

- [ ] **Step 5: Verify the updates**

Run: `Grep` for `UI S8` in `docs/progress.md` — expected: 1 match.
Run: `Grep` for `修复与改进` in `docs/progress.md` — expected: 1 match.

---

## Task 9: First commit — license/metadata/gitignore/README

**Files:**
- Stage: `LICENSE`, `README.md`, `.gitignore`, `pyproject.toml`, plus all the `git rm --cached` entries from Task 3
- Do NOT stage: any of the 45 unrelated M files

- [ ] **Step 1: Stage release-facing files only (explicit paths)**

```bash
cd F:/tools/pynpxpipe
git add LICENSE README.md .gitignore pyproject.toml
```

- [ ] **Step 2: Verify the stage preview**

```bash
git diff --cached --stat
```

Expected: 4 files (LICENSE new, README.md modified, .gitignore modified, pyproject.toml modified) PLUS the deletion entries from Task 3's `git rm --cached` commands (since those staged deletions are already in the index).

**Red flag:** if any unrelated M file from the original `git status` appears here, STOP and un-stage it with `git restore --staged <path>`.

- [ ] **Step 3: Create the first commit**

```bash
git commit -m "$(cat <<'EOF'
chore(release): add LICENSE, README, .gitignore; pyproject metadata

- MIT LICENSE
- Bilingual README.md (EN + 中文) with install / quick-start
- Comprehensive .gitignore (tool dirs, private data, runtime outputs)
- pyproject metadata: license, keywords, classifiers, project.urls
- Untrack legacy_reference/, tests/fixtures/bhv2_ground_truth/,
  docs/temp/, docs/superpowers/, private monkeys yamls, .claude/
EOF
)"
```

- [ ] **Step 4: Verify the commit landed**

```bash
git log --oneline -1
```

Expected: the new commit hash + subject line `chore(release): add LICENSE, README, .gitignore; pyproject metadata`.

---

## Task 10: Second commit — docs refresh

**Files:**
- Stage: `getting_started.md`, `CLAUDE.md`, `docs/progress.md`, `docs/release_prep_design.md`, `docs/release_prep_plan.md`
- Do NOT stage: any of the 45 unrelated M files

- [ ] **Step 1: Stage the doc updates (explicit paths)**

```bash
cd F:/tools/pynpxpipe
git add getting_started.md CLAUDE.md docs/progress.md docs/release_prep_design.md docs/release_prep_plan.md
```

- [ ] **Step 2: Verify the stage preview**

```bash
git diff --cached --stat
```

Expected: exactly 5 files listed. Same red flag rule: if unrelated M files appear, un-stage them.

- [ ] **Step 3: Create the second commit**

```bash
git commit -m "$(cat <<'EOF'
docs(release): refresh install guide, phase note, progress for public release

- getting_started.md: split Install into Mode A (consume) / Mode B (clone);
  document new UI features (Chat Help, Figures Viewer, Subject save-yaml)
- CLAUDE.md: bump current-phase note; add agent/ subtree
- docs/progress.md: append UI S6/S7/S8; record M2 bug fixes;
  total test count updated
- docs/release_prep_{design,plan}.md: first-release preparation design + plan
EOF
)"
```

- [ ] **Step 4: Verify the commit**

```bash
git log --oneline -2
```

Expected: two new commits on top, the release chore commit and the docs commit.

---

## Task 11: Rename branch and add remote

**Files:**
- Git metadata only

- [ ] **Step 1: Confirm current branch is `master`**

```bash
cd F:/tools/pynpxpipe && git branch --show-current
```

Expected: `master`

- [ ] **Step 2: Rename `master` → `main`**

```bash
git branch -m master main
```

- [ ] **Step 3: Confirm rename worked**

```bash
git branch --show-current
```

Expected: `main`

- [ ] **Step 4: Add the GitHub remote**

```bash
git remote add origin https://github.com/GongZhengxin/pynpxpipe.git
```

- [ ] **Step 5: Confirm remote is set**

```bash
git remote -v
```

Expected:
```
origin  https://github.com/GongZhengxin/pynpxpipe.git (fetch)
origin  https://github.com/GongZhengxin/pynpxpipe.git (push)
```

---

## Task 12: Pre-push verification (NO PUSH YET)

**Files:** none modified. Pure verification.

- [ ] **Step 1: Verify unrelated WIP is still modified, not committed**

```bash
git status --porcelain | grep -c '^ M'
```

Expected: a number ≥ 40 (the original 45 unrelated M files; count may shift slightly if any had been edited by earlier steps — should NOT be the case).

Also run:

```bash
git status --porcelain | grep '^ M' | head -20
```

Expected: the list includes files like `src/pynpxpipe/core/errors.py`, `tests/test_io/test_bhv.py`, etc. — the same files flagged as M at session start.

- [ ] **Step 2: Verify excluded paths are NOT in the tree to be pushed**

```bash
git ls-files | grep -E '^(\.claude|legacy_reference|tests/fixtures/bhv2_ground_truth|docs/(temp|superpowers)|monkeys/(JianJian|MaoDan))' | head
```

Expected: **empty output**.

- [ ] **Step 3: Verify the last two commits are what we expect**

```bash
git log --oneline -2
```

Expected: the chore and docs commits from Tasks 9 and 10, in that order (docs on top).

- [ ] **Step 4: Show the full list of files that would be pushed**

```bash
git ls-files | wc -l
```

Expected: a count. Also run `git ls-files | head -30` to spot-check that it contains `LICENSE`, `README.md`, `pyproject.toml`, `src/pynpxpipe/...`, but NOT `legacy_reference/...`.

- [ ] **Step 5: Stop and report to the user**

Report back:
1. The two commit subjects
2. The total file count that will be pushed
3. Confirm unrelated WIP is untouched

**Then wait for the user's explicit "go" before Task 13.**

---

## Task 13: Push to GitHub (ONLY after user confirmation)

**Files:** network only

- [ ] **Step 1: User has said "push it" or equivalent**

If the user has not explicitly confirmed, STOP. Do not proceed.

- [ ] **Step 2: Push `main` to `origin` with upstream tracking**

```bash
cd F:/tools/pynpxpipe && git push -u origin main
```

Expected: `Branch 'main' set up to track remote branch 'main' from 'origin'.` and no errors.

- [ ] **Step 3: Verify the push succeeded**

```bash
git log --oneline origin/main -3
```

Expected: the same three most recent commits as local `main`.

- [ ] **Step 4: Report back to user**

Print the GitHub URL: `https://github.com/GongZhengxin/pynpxpipe` and confirm push success.

---

## Self-Review Results

1. **Spec coverage** — every design.md decision has a task:
   - LICENSE → Task 1
   - .gitignore → Task 2
   - Untrack → Task 3
   - README → Task 4
   - pyproject.toml → Task 5
   - getting_started.md → Task 6
   - CLAUDE.md → Task 7
   - docs/progress.md → Task 8
   - Commit strategy → Tasks 9-10
   - Branch rename → Task 11
   - Push → Tasks 12-13
2. **Placeholder scan** — no "TBD" / "handle edge cases" / "similar to". Task 8 Step 4 has one `<fill in>` slot that is explicitly instructed to be filled from Step 1's pytest output. Acceptable.
3. **Consistency** — file paths, branch names, and remote URL match across tasks.
