# Prompt: 创建 CLAUDE.md

根据 docs/legacy_analysis.md 的分析结果，在项目根目录创建 CLAUDE.md 文件。
这是项目的核心规范文档，请严格按以下内容生成：

---

# CLAUDE.md

## 项目概述

pynpxpipe：神经电生理数据预处理工具包。
输入：SpikeGLX 录制数据文件夹（含 AP/LF/NI 三类数据流，支持多 probe）+ MonkeyLogic BHV2 行为文件
输出：标准 NWB 格式文件（一个 session 一个 NWB，包含所有 probe 的数据）

## 核心设计原则

1. **多探针优先**：所有模块必须以 probe_id 为参数，支持 N 个 IMEC 探针。单探针是 N=1 的特例，不是默认假设。
2. **断点续跑**：每个 stage 完成后写 checkpoint 文件到 session 输出目录。Pipeline 启动时检查 checkpoint，自动跳过已完成的 stage。
3. **内存安全**：禁止一次性加载整个大文件到内存。大数组处理必须用分块/流式。每个 stage 结束时 del 大对象 + gc.collect()。sorting 每处理完一个 probe 立即释放。
4. **零硬编码**：采样率、通道 ID、事件码、探针编号等全部从数据 meta 或配置文件读取，代码中禁止出现 magic number。
5. **日志完备**：所有 stage 操作写入结构化日志（JSON Lines），含时间戳、stage 名、probe_id、参数、耗时、成功/失败状态。
6. **远程 sorting 兼容**：sorting stage 必须支持两种模式——本地运行和导入外部结果（从 Windows 实验室电脑拷贝过来的 kilosort 输出）。

## Pipeline 架构

### Stage 定义（按顺序执行）

1. **discover** — 扫描 SpikeGLX 文件夹，发现所有 probe、验证数据完整性（meta + bin 文件大小匹配）、提取元信息
2. **preprocess** — 对每个 probe 的 AP 数据做预处理：bandpass filter → common median reference → 运动校正(motion correction/drift correction with dredge)
3. **sort** — 对每个 probe 独立运行 spike sorting（默认 Kilosort4 via SpikeInterface），或导入外部 sorting 结果
4. **curate** — 质控与自动筛选：使用 SpikeInterface 内置的 quality_metrics + curation（替代旧版 bombcell）
5. **postprocess** — SpikeInterface SortingAnalyzer：waveforms, templates, unit locations 等
6. **synchronize** — 使用 SpikeGLX 同步信号对齐所有数据流时间戳，解析 MonkeyLogic BHV2 行为事件
7. **export** — 将所有数据整合写入 NWB 文件

### Session 对象

```python
@dataclass
class Session:
    session_dir: Path          # SpikeGLX 原始数据根目录
    output_dir: Path           # 处理输出目录
    subject: SubjectConfig     # 动物信息（从 monkeys/*.yaml 加载）
    probes: list[ProbeInfo]    # 自动发现的探针列表
    bhv_file: Path             # MonkeyLogic BHV2 文件路径
    checkpoint: dict           # 各 stage 完成状态
    log_path: Path             # 日志文件路径
```

### 多探针处理流程

- discover 阶段自动枚举所有 imec{N} 目录
- preprocess / sort / curate / postprocess 阶段：对 probes 列表串行处理，每完成一个 probe 写 checkpoint + 释放内存
- synchronize 阶段：先对齐所有 probe 到 NI 时钟，再对齐行为事件
- export 阶段：所有 probe 数据写入同一个 NWB 文件的不同 ElectrodeGroup

## 技术栈

- Python >= 3.11
- spikeinterface >= 0.101（使用最新稳定版 API）
- probeinterface
- pynwb >= 2.8
- neo
- numpy, scipy
- click（CLI 框架）
- pyyaml（配置管理）
- structlog（结构化日志）
- uv（包管理，pyproject.toml 为唯一依赖声明）

## 目录结构

```
src/pynpxpipe/
  cli/              # 命令行入口
    __init__.py
    main.py         # click group 定义
  core/             # 核心对象
    __init__.py
    session.py      # Session dataclass + 生命周期管理
    checkpoint.py   # checkpoint 读写
    logging.py      # 结构化日志
    config.py       # YAML 配置加载与验证
  io/               # 数据读写
    __init__.py
    spikeglx.py     # SpikeGLX 数据发现与加载（多探针）
    bhv.py          # MonkeyLogic BHV2 解析
    nwb_writer.py   # NWB 文件生成
  stages/           # 处理阶段
    __init__.py
    base.py         # Stage 基类（含 checkpoint/logging 通用逻辑）
    discover.py
    preprocess.py
    sort.py
    curate.py
    postprocess.py
    synchronize.py
    export.py
  pipelines/        # Pipeline 编排
    __init__.py
    runner.py       # 顺序执行 stages，处理断点续跑
tests/
  test_io/
  test_stages/
  test_integration/
```

## 代码规范

- 所有函数和类必须有 type hints
- Docstrings 用 Google style
- 私有函数用 _ 前缀
- 配置项在 YAML 中定义，代码中通过 config 对象访问，禁止 magic number
- 测试文件和被测模块同名，如 test_spikeglx.py 测试 spikeglx.py
- 使用 ruff 做 lint 和 format（pyproject.toml 中配置）

## Windows 兼容性注意

- 开发环境为 Windows + VSCode
- 所有路径操作必须用 pathlib.Path，禁止手写 / 或 \\
- 文件读写指定 encoding='utf-8'
- 长路径问题：SpikeGLX 输出路径可能很深，注意 Windows 260 字符限制

## 从旧代码迁移的注意事项

参照 docs/legacy_analysis.md 中的问题清单：
- 旧代码中所有硬编码的 30000Hz、imec0、通道名、事件码 64 等必须参数化
- 旧代码的 neo_reader.signals_info_dict 私有属性访问必须替换为 spikeinterface 公开 API
- bombcell 的功能用 spikeinterface.curation 和 quality_metrics 替代
- 旧代码的眼动矩阵预分配方式需要改为按 trial 分块处理

---

生成完成后，告诉我文件内容，我来审阅修改。