# 入门指南：运行 UI 并预处理数据

本教程演示如何安装 pynpxpipe、启动 Web UI，以及在 SpikeGLX 录制数据上运行预处理管线。

## 前置条件

- **Python 3.11 或 3.12**（不支持 3.13）
- **uv** 包管理器（[安装指南](https://docs.astral.sh/uv/getting-started/installation/)）
- **SpikeGLX 录制数据**（session 目录下包含 `imec0/`、`imec1/`…… 子目录，内含 `.ap.bin`/`.ap.meta` 文件，以及 NIDQ 的 `.bin`/`.meta` 一对）
- **MonkeyLogic BHV2 文件**（与该 session 对应的 `.bhv2` 行为数据文件）
- （可选）**NVIDIA GPU** + CUDA，用于 Kilosort4 spike sorting

## 1. 安装 pynpxpipe

根据使用场景，有两种安装模式。

### 模式 A — 作为依赖引入（多数用户）

第 1 步 — 在你自己的 uv 项目中添加 pynpxpipe：

```bash
# 推荐：完整管线（Web UI + GPU 探测 + 诊断图）
uv add "pynpxpipe[ui,gpu,plots] @ git+https://github.com/GongZhengxin/pynpxpipe.git"

# 额外加上 LLM 助手
uv add "pynpxpipe[ui,gpu,plots,chat] @ git+https://github.com/GongZhengxin/pynpxpipe.git"

# 仅核心（不含 UI 和诊断图）
uv add git+https://github.com/GongZhengxin/pynpxpipe.git
```

第 2 步 — 安装 sort stack（**一次性**，不需要每次更新都重装）：

```bash
# 从仓库拿 install_sort_stack.py（模式 B 克隆过的可跳过）
curl -O https://raw.githubusercontent.com/GongZhengxin/pynpxpipe/main/tools/install_sort_stack.py
curl -O https://raw.githubusercontent.com/GongZhengxin/pynpxpipe/main/tools/cuda_matrix.yaml
mkdir -p tools && mv install_sort_stack.py cuda_matrix.yaml tools/

# 交互式安装 —— 自动探测 GPU + 驱动，推荐匹配的 CUDA wheel
uv run python tools/install_sort_stack.py
```

> **为什么要单独装？** `torch` 和 `kilosort` 有意**不**写进 `pyproject.toml`。
> 如果写进去，每次 `uv sync` 都会把你装好的 CUDA 版 torch 覆盖回 pypi 的
> CPU wheel，导致你在不知情的情况下退回到 CPU 执行。把它们排除在 pyproject
> 之外，你选的 wheel 就能跨更新保留，每个用户根据自己的 CUDA 版本装对应 wheel。
>
> 安装器读取 `tools/cuda_matrix.yaml`，为你的驱动选对的 wheel。它总是先给
> 出推荐，然后让你确认或覆盖。重复运行是幂等的（`.venv/.gpu_stack_lock.json`
> 会记录已装内容）。

### 模式 B — 克隆仓库（开发 / 贡献）

```bash
git clone https://github.com/GongZhengxin/pynpxpipe.git
cd pynpxpipe
uv sync --all-groups

# 一次性 sort stack 安装（原因见模式 A 第 2 步）
uv run python tools/install_sort_stack.py
```

随时可以通过以下命令验证：

```bash
uv run python tools/verify_gpu.py
```

### 让 torch 在后续 sync 后仍然在位

安装器跑完之后，**以后重新 sync 一律带 `--inexact`**：

```bash
uv sync --inexact --extra ui --extra gpu --extra plots         # 保留 torch/kilosort
uv sync --extra ui --extra gpu --extra plots                   # ✗ 别这样 —— 会清掉 torch
```

原因：`uv sync` 默认严格模式，会卸载所有不在 `uv.lock` 里的包。由于 `torch` /
`kilosort` 不在 lock 中（这正是 CUDA 构建能按用户保留的机制），严格 sync 会
把它们清掉。`--inexact` 告诉 uv 放过不在 lock 里的包。截至 uv 0.8 还没有
对应的环境变量，只能显式传参（或写进 shell alias / Makefile）。

如果 `uv sync` 之后看到 `ModuleNotFoundError: No module named 'torch'`，那
就是忘了 `--inexact` —— 重跑安装器即可（`--force` 跳过提示）：

```bash
uv run python tools/install_sort_stack.py --yes --force
```

### 验证安装

```bash
uv run pynpxpipe --version
uv run pynpxpipe --help
```

## 2. 准备数据

### 2.1 SpikeGLX Session 目录

SpikeGLX 录制文件夹结构应该是：

```
my_session_g0/
  my_session_g0_imec0/
    my_session_g0_t0.imec0.ap.bin
    my_session_g0_t0.imec0.ap.meta
    my_session_g0_t0.imec0.lf.bin      # 可选
    my_session_g0_t0.imec0.lf.meta     # 可选
  my_session_g0_imec1/                  # 多 probe 时存在
    ...
  my_session_g0_t0.nidq.bin
  my_session_g0_t0.nidq.meta
```

### 2.2 BHV2 行为文件

MonkeyLogic 导出的同一 session 的 `.bhv2` 文件。pynpxpipe 用纯 Python 解析器读（不需要 MATLAB）。

### 2.3 Subject 配置（YAML）

为你的 subject 创建一个 YAML（或用 `monkeys/` 下已有的）。示例 —— `monkeys/MaoDan.yaml`：

```yaml
Subject:
  subject_id: "MaoDan"            # DANDI 必填
  description: "good monkey"      # 自由文本
  species: "Macaca mulatta"       # DANDI 必填
  sex: "M"                        # DANDI 必填
  age: "P4Y"                      # ISO 8601 时长
  weight: "12.8kg"                # 含单位的体重
```

### 2.4 输出目录

选一个目录存放处理结果。pynpxpipe 会在其下创建 checkpoint、预处理数据、sorting 结果、同步表和最终 NWB 的子目录。

## 3. 启动 Web UI

Web UI 是配置和运行管线最简单的方式。

```bash
uv run pynpxpipe-ui
```

会启动本地 Panel 服务器，并在默认浏览器打开 UI（通常在 `http://localhost:5006`）。

也可以手动启动：

```bash
uv run panel serve src/pynpxpipe/ui/app.py --show
```

### UI 总览

UI 分三个区，从侧边栏进入：

| 区域 | 用途 |
|------|------|
| **Configure**（配置） | 设置输入路径、subject 元数据、管线参数、sorting 选项，选择要跑的 stage。Subject 表单支持保存为可复用的 YAML。 |
| **Execute**（执行） | 启动/停止管线、监控 stage 级和 probe 级进度、查看实时日志 |
| **Review**（回看） | 加载历史 session、查看 checkpoint 状态、重置 stage 以重跑、用 **Figures Viewer** 浏览生成的诊断图，用 **Chat Help** 面板提问（需 `chat` extra + API key） |

## 4. 配置一次管线运行（通过 UI）

### 步骤 1：Session 表单

在 **Configure** 区填写：

- **Session Directory** —— SpikeGLX 录制文件夹路径（如 `D:/data/my_session_g0/`）
- **BHV File** —— `.bhv2` 文件路径（如 `D:/data/my_session.bhv2`）
- **Output Directory** —— 结果输出路径（如 `D:/output/my_session/`）

### 步骤 2：Subject 元数据

填写 subject 字段（或从 YAML 加载）：

- **Subject ID** —— 唯一标识符（如 `MaoDan`）
- **Species** —— 学名（如 `Macaca mulatta`）
- **Sex** —— `M`、`F`、`U` 或 `O`
- **Age** —— ISO 8601 时长（如 4 岁写 `P4Y`）
- **Weight** —— 含单位（如 `12.8kg`）

### 步骤 3：管线参数

调整处理参数（默认值通常够用）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| **n_jobs** | auto | 并行线程数 |
| **chunk_duration** | auto | 分块时长（如 `1s`） |
| **max_memory** | auto | 日志记录用的内存上限 |
| **Bandpass freq_min** | 300 Hz | 高通截止 |
| **Bandpass freq_max** | 6000 Hz | 低通截止 |
| **Motion correction** | dredge | `dredge`、`kilosort` 或禁用 |

### 步骤 4：Sorting 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| **Mode** | local | `local`（本地跑 Kilosort4）或 `import`（导入外部结果） |
| **nblocks** | 15 | 漂移校正分块数（0 = 禁用） |
| **do_CAR** | false | 始终 false（预处理已经做过 CMR） |
| **batch_size** | auto | 根据 GPU VRAM 自动探测 |

### 步骤 5：选择 Stage

勾选要跑的 stage。完整管线顺序：

1. **discover** —— 扫描 SpikeGLX 目录，探测 probe
2. **preprocess** —— 滤波、坏道去除、CMR、运动校正，保存 Zarr
3. **sort** —— Kilosort4 spike sorting（或导入外部结果）
4. **synchronize** —— IMEC、NIDQ、BHV2 之间的时间对齐
5. **curate** —— 质量指标和单元分类
6. **postprocess** —— 波形分析、自动合并
7. **export** —— 组装最终 NWB 文件

只想做预处理就勾选 **discover** + **preprocess**。

## 5. 运行管线

1. 点击侧边栏 **Execute** 切到执行区。
2. 点击 **Run**。管线在后台线程启动（UI 保持响应）。
3. 监控进度：
   - **进度条** —— 显示当前 stage 和每个 probe 的子进度
   - **日志查看器** —— 实时结构化日志，支持级别过滤（INFO、WARNING、ERROR）
   - **状态** —— idle / running / completed / failed
4. 提前终止：点击 **Stop**（设置中断标志；当前 probe 跑完后停）。

## 6. 通过命令行运行（替代方案）

如果更习惯 CLI：

```bash
uv run pynpxpipe run \
  D:/data/my_session_g0 \
  D:/data/my_session.bhv2 \
  --subject monkeys/MaoDan.yaml \
  --output-dir D:/output/my_session \
  --pipeline-config config/pipeline.yaml \
  --sorting-config config/sorting.yaml
```

只跑部分 stage：

```bash
# 只跑 discover + preprocess
uv run pynpxpipe run \
  D:/data/my_session_g0 \
  D:/data/my_session.bhv2 \
  --subject monkeys/MaoDan.yaml \
  --output-dir D:/output/my_session \
  --stages discover --stages preprocess
```

查看管线状态：

```bash
uv run pynpxpipe status D:/output/my_session
```

重置某个 stage 以重跑：

```bash
uv run pynpxpipe reset-stage D:/output/my_session preprocess
```

## 7. 解读预处理输出

跑完 **discover** 和 **preprocess** 后，输出目录会包含：

```
D:/output/my_session/
  session_info.json              # Session 元数据（probe 列表、路径）
  logs/
    pipeline.jsonl               # 结构化 JSON Lines 日志
  checkpoints/
    discover.json                # Stage checkpoint
    preprocess_imec0.json        # Probe 级 checkpoint
    preprocess_imec1.json        # （多 probe 时）
  preprocessed/
    imec0/                       # Zarr 录制数据（分块，内存友好）
    imec1/                       # （多 probe 时）
```

### 预处理步骤（每个 probe）

预处理 stage 按严格顺序执行：

| 步骤 | 操作 | 原因 |
|------|------|------|
| 1 | **Phase shift** | 修正 ADC 多路复用采样时差 —— 必须第一步 |
| 2 | **Bandpass filter** | 300-6000 Hz（可配） |
| 3 | **坏道检测** | Coherence + PSD 方法 |
| 4 | **坏道去除** | 移除探测到的坏道 |
| 5 | **共同中值参考** | 全局中值减法 |
| 6 | **运动校正** | DREDge 漂移校正（可选） |
| 7 | **保存 Zarr** | 分块格式，供下游 stage 使用 |

每个 probe 顺序处理。probe 之间释放内存（`del` + `gc.collect()`），所以 400+ GB 的 AP 文件在普通硬件上也能跑。

## 8. 从中断处恢复

pynpxpipe 基于 checkpoint 支持恢复。如果管线中断：

**通过 UI：**
1. 打开 **Review** 区
2. 用 **Session Loader** 浏览输出目录
3. 点 **Load** —— 会根据保存的 session 自动填充所有表单
4. 切到 **Execute** 点 **Run** —— 已完成的 stage 会自动跳过

**通过 CLI：**
```bash
# 重跑相同命令即可 —— 已完成 stage 自动跳过
uv run pynpxpipe run D:/data/my_session_g0 D:/data/my_session.bhv2 \
  --subject monkeys/MaoDan.yaml --output-dir D:/output/my_session
```

强制重跑某个 stage，先重置它的 checkpoint：

**通过 UI：** 在 **Review** 区用 **Status View** 重置 stage。

**通过 CLI：**
```bash
uv run pynpxpipe reset-stage D:/output/my_session preprocess
```

## 9. 配置参考

### 管线配置（`config/pipeline.yaml`）

```yaml
resources:
  n_jobs: auto                   # "auto" 或整数
  chunk_duration: auto           # "auto" 或 "1s"、"2s"、"0.5s"
  max_memory: auto               # "auto" 或 "32G"

preprocess:
  bandpass:
    freq_min: 300
    freq_max: 6000
  bad_channel_detection:
    method: "coherence+psd"
    dead_channel_threshold: 0.5
  common_reference:
    reference: "global"
    operator: "median"
  motion_correction:
    method: "dredge"             # "dredge" | "kilosort" | null
    preset: "nonrigid_accurate"
```

### Sorting 配置（`config/sorting.yaml`）

```yaml
mode: "local"                    # "local" | "import"

sorter:
  name: "kilosort4"
  params:
    nblocks: 15
    Th_learned: 7.0
    do_CAR: false                # 始终 false（预处理已做 CMR）
    batch_size: auto
```

### Subject 配置（`monkeys/*.yaml`）

```yaml
Subject:
  subject_id: "MaoDan"
  description: "good monkey"
  species: "Macaca mulatta"
  sex: "M"
  age: "P4Y"
  weight: "12.8kg"
```

## 10. 疑难排查

| 问题 | 解决方法 |
|------|----------|
| `ModuleNotFoundError: No module named 'panel'` | 装 UI extra：`uv sync --extra ui` |
| `ModuleNotFoundError: No module named 'torch'` | 跑 `uv run python tools/install_sort_stack.py`（torch 不在 pyproject，见安装指南） |
| `The dredge method require torch: pip install torch` | 同上 —— 跑 sort stack 安装器；DREDge 需要 `torch` |
| `ModuleNotFoundError: No module named 'kilosort'` | 同上 —— 跑 sort stack 安装器 |
| `TorchEnvError: torch_device='cuda' was requested ... CPU-only build` | 当前 torch 是 CPU wheel。跑 `uv run python tools/install_sort_stack.py --force` 选匹配驱动的 CUDA wheel |
| `TorchEnvError: torch_device='cuda' was requested but no NVIDIA GPU` | 在 `config/sorting.yaml` 把 `torch_device` 设为 `cpu`（或 `auto`） |
| `pynpxpipe-ui` 命令找不到 | 用 `uv run pynpxpipe-ui` 或先 `uv sync` |
| UI 没自动打开浏览器 | 手动访问 `http://localhost:5006` |
| 预处理阶段内存溢出 | 把 `pipeline.yaml` 里的 `chunk_duration` 调小（如 `"0.5s"`）或降低 `n_jobs` |
| 运动校正 + KS4 nblocks 冲突 | 两者互斥。用 KS4 nblocks > 0 时把运动校正设为 `null`；用 DREDge 时把 nblocks 设为 0 |
| Sorting 时检测不到 GPU | 装 GPU extra：`uv sync --extra gpu`。确保已装 CUDA 驱动 |
| 管线卡在某个 stage | 检查 `logs/pipeline.jsonl` 看错误。用 `reset-stage` 清 checkpoint 重试 |
| BHV2 解析错误 | pynpxpipe 默认用纯 Python 解析器。设 `BHV2_BACKEND=matlab` 用 MATLAB Engine 回退（需要 MATLAB） |
