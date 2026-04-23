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
# Recommended: full pipeline with Web UI
uv add "pynpxpipe[ui,sort,gpu,plots] @ git+https://github.com/GongZhengxin/pynpxpipe.git"

# Core only (no Kilosort4, no DREDge motion correction, no UI)
uv add git+https://github.com/GongZhengxin/pynpxpipe.git
```

> The `sort` extra pulls `kilosort` which brings `torch` along — required for
> both the `sort` stage (Kilosort4) and DREDge motion correction in `preprocess`.
> CPU torch from pypi is installed by default; for GPU acceleration install a
> CUDA build of torch from [pytorch.org](https://pytorch.org) after `uv sync`.

**For development / contributing:**

```bash
git clone https://github.com/GongZhengxin/pynpxpipe.git
cd pynpxpipe
uv sync --all-groups
```

### Optional extras

| Extra | Purpose |
|---|---|
| `sort` | Kilosort4 sorter + DREDge motion correction (pulls `kilosort` → `torch`) |
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
# 推荐：完整 pipeline + Web UI
uv add "pynpxpipe[ui,sort,gpu,plots] @ git+https://github.com/GongZhengxin/pynpxpipe.git"

# 仅核心功能（不含 Kilosort4、DREDge 运动校正、UI）
uv add git+https://github.com/GongZhengxin/pynpxpipe.git
```

> `sort` extra 会拉 `kilosort`（及其依赖 `torch`），同时覆盖 `sort` 阶段的
> Kilosort4 和 `preprocess` 阶段的 DREDge 运动校正。默认安装的是 pypi 上的 CPU
> 版 torch；需要 GPU 加速的用户请在 `uv sync` 之后从 pytorch.org 安装 CUDA 版
> torch。

开发者请 clone 仓库后运行 `uv sync --all-groups`。

## 快速开始

```bash
uv run pynpxpipe-ui
```

详细教程请参考 [`getting_started.md`](getting_started.md)。

## 许可

MIT 许可证。
