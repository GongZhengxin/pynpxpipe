# Smoke Test Harness — Spec

## 1. 目标

为 pynpxpipe UI + Pipeline 集成调试提供**开发者级**自适应闭环工具。

解决三类问题：
- **程序 BUG**：CUDA 检测失败但配置要求 CUDA、config 字段定义但未使用（如 `amplitude_cutoff_max`）
- **参数疑惑**：curation thresholds 与 Bombcell 习惯不一致、互斥选项同时启用
- **功能缺失**：中间结果不可视、Stage 输出未验证

**不解决**：终端用户自助排错 UI（那是 M3+ 的方向）。

## 2. 使用方式

```bash
# Phase 1: 预检（pipeline 运行前）
python smoke_test_harness.py preflight \
    --session-dir /path/to/spikeglx_session \
    --config config/pipeline.yaml \
    --sorting-config config/sorting.yaml \
    --output-dir /path/to/output

# Phase 2: 逐 stage 验证（用真实数据）
python smoke_test_harness.py validate \
    --session-dir /path/to/spikeglx_session \
    --stop-after sort \
    --output-dir /path/to/output
```

输出写入 `<output_dir>/.harness/`：
- `preflight_report.json` — 环境 + 配置 + 数据检查结果
- `validation_report.json` — 逐 stage 验证结果（增量追加）
- `auto_fixes.json` — 已自动应用的修复审计日志
- `suggested_fixes.md` — 需要人工/CC 判断的修复建议

## 3. 架构

### 3.1 设计原则

- Harness 是 pipeline 的**消费者**，调用 `pynpxpipe.core` 和 `pynpxpipe.pipelines` 的公开 API
- 不 monkey-patch、不子类化 `PipelineRunner`
- 当发现 **明确的源码 BUG**（config 字段未使用、校验缺失、指标名错误），harness 可以修补源码，但必须记录完整 diff 到 `auto_fixes.json`
- 涉及算法选择、阈值调优、架构决策的问题**只建议不自动修**

### 3.2 文件布局

```
pynpxpipe/
├── smoke_test_harness.py              # 入口（CLI: preflight | validate）
├── src/pynpxpipe/harness/             # Harness 内部模块
│   ├── __init__.py
│   ├── preflight.py                   # 环境、配置、数据预检
│   ├── validators/                    # 每 stage 一个 validator
│   │   ├── __init__.py
│   │   ├── discover_validator.py
│   │   ├── preprocess_validator.py
│   │   ├── sort_validator.py
│   │   ├── sync_validator.py
│   │   ├── curate_validator.py
│   │   ├── postprocess_validator.py
│   │   └── export_validator.py
│   ├── fixers.py                      # GREEN + YELLOW 自动修复逻辑
│   ├── classifier.py                  # 错误分类引擎
│   └── reporter.py                    # JSON + markdown 报告生成
├── <output_dir>/.harness/             # 每次运行的输出
│   ├── preflight_report.json
│   ├── validation_report.json
│   ├── auto_fixes.json
│   └── suggested_fixes.md
```

### 3.3 依赖关系

```
smoke_test_harness.py
    └── src/pynpxpipe/harness/
            ├── imports from: core.config, core.resources, core.session, core.checkpoint
            ├── imports from: pipelines.runner
            ├── imports from: io.spikeglx (数据验证)
            └── imports from: stages.* (仅用于读取 STAGE_NAME 常量)
```

Harness 不依赖 UI 层（`ui/`），不依赖 CLI 层（`cli/`）。

## 4. Phase 1 — Preflight 预检

在 pipeline 运行前执行，检查三类条件。

### 4.1 环境检查

| 检查项 | PASS 条件 | FAIL 条件 | 自动修复 |
|--------|-----------|-----------|---------|
| CUDA 可用性 vs `torch_device` | GPU 检测到 + config 为 "cuda" 或 "auto" | Config 为 "cuda" 但无 GPU | GREEN：设 `torch_device` 为 "auto" |
| torch 安装与版本 | `torch.cuda.is_available()` 与检测一致 | torch 缺失或 CUDA 不匹配 | 日志警告，建议 `uv add torch` |
| SpikeInterface 版本 | >= 0.104 | 低于 0.104 | 日志错误，不自动修复 |
| 磁盘空间 | 预估输出空间充足 | 可用空间 < 50GB | 仅警告 |
| VRAM vs batch_size | `batch_size` 在检测到的空闲 VRAM 安全范围内 | 预计 OOM | GREEN：降低 `batch_size` 到安全档位 |

### 4.2 配置一致性检查

| 检查项 | PASS 条件 | FAIL 条件 | 自动修复 |
|--------|-----------|-----------|---------|
| `amplitude_cutoff_max` 实际使用 | curate.py 计算并应用该指标 | config 有阈值但代码未用 | YELLOW：修补 `curate.py` 添加指标计算和过滤 |
| 运动校正 vs KS4 nblocks 互斥 | 仅启用一个 | 同时启用 | GREEN：禁用运动校正，日志记录原因 |
| Curation 阈值范围 | 所有值在合理范围（比率 0-1） | 超出范围 | 仅警告（用户意图不明） |
| sorting mode vs 输出目录 | mode="import" 时外部结果路径存在 | 路径不存在 | 日志错误 |

### 4.3 数据检查

| 检查项 | PASS 条件 | FAIL 条件 | 自动修复 |
|--------|-----------|-----------|---------|
| Session 目录结构 | `.ap.bin` + `.ap.meta` 存在 | 文件缺失 | 日志列出缺失文件 |
| BHV2 文件可读 | 成功解析 header | 读取失败 | 日志错误 |
| Probe 数量 > 0 | 至少发现一个 IMEC probe | 零探针 | 日志错误 |
| NIDQ 数据存在 | `.nidq.bin` + `.nidq.meta` 存在 | 缺失 | 日志错误 |

### 4.4 Preflight 报告格式

```json
{
  "timestamp": "2026-04-11T14:30:00",
  "overall_status": "FAIL",
  "checks": [
    {
      "category": "environment",
      "name": "cuda_vs_config",
      "status": "FAIL",
      "message": "torch_device='cuda' but no CUDA GPU detected (3 detection methods tried)",
      "auto_fixable": true,
      "fix_tier": "GREEN",
      "fix_description": "Set torch_device to 'auto' in sorting config"
    }
  ],
  "summary": {
    "total": 12,
    "pass": 10,
    "warn": 1,
    "fail": 1,
    "auto_fixed": 1
  }
}
```

## 5. Phase 2 — Stage-by-Stage Validation

使用真实数据运行 pipeline，每个 stage 完成/失败后执行对应 validator。

### 5.1 执行模型

1. 用与 UI 相同的方式实例化 `PipelineRunner`（传入 session、config、sorting_config）
2. 调用 `runner.run(stages=stages_up_to_stop_after)` — runner 内部按顺序执行，遇到第一个失败 stage 停止
3. `runner.run()` 返回后（无论成功或失败），harness 遍历所有目标 stage 的 checkpoint 文件，对每个 stage 执行对应 validator
4. 已完成的 stage：validator 检查输出完整性和质量
5. 失败的 stage：validator 分类错误、生成修复建议
6. 未执行的 stage（被前序失败阻塞）：标记为 "skipped"

### 5.2 每 Stage Validator

| Stage | 成功时验证 | 失败时分类 |
|-------|-----------|-----------|
| **discover** | `session.probes` 非空；meta 文件解析成功；采样率已提取 | 文件缺失 / 解析错误 / 路径编码问题 |
| **preprocess** | 每个 probe 的 Zarr 输出存在；recording 可通过 SI 加载；无 NaN 通道 | OOM / 坏道检测崩溃 / Zarr 写入错误 |
| **sort** | 每个 probe 的 sorting 输出目录存在；>0 个单元；KS4 日志可解析 | CUDA OOM → 建议降低 batch_size；sorter 未安装 → 建议安装；零单元 → 警告阈值问题 |
| **synchronize** | 对齐残差在阈值内；trial 数量与 BHV2 匹配 | 漂移过大 → 建议人工检查；trial 不匹配 → 建议检查事件码 |
| **curate** | `quality_metrics.csv` 每 probe 存在；>0 个 good unit；checkpoint 阈值与 config 一致 | 零单元 → 建议放松阈值；指标缺失 → 源码 BUG |
| **postprocess** | SortingAnalyzer 扩展已计算；waveform template 存在 | OOM（已有内置重试）→ 报告两次都失败 |
| **export** | NWB 文件存在、可读、包含预期 probe 数量 | 写入错误 / 验证错误 |

### 5.3 错误分类引擎

`classifier.py` 将异常映射到结构化错误类别：

```python
ERROR_PATTERNS = {
    "cuda_oom": {
        "patterns": ["CUDA out of memory", "OutOfMemoryError", "torch.cuda.OutOfMemoryError"],
        "tier": "GREEN",
        "fix": "reduce batch_size to next lower tier",
    },
    "cuda_unavailable": {
        "patterns": ["CUDA is not available", "no CUDA-capable device"],
        "tier": "GREEN",
        "fix": "set torch_device to 'cpu' or 'auto'",
    },
    "sorter_not_found": {
        "patterns": ["sorter not installed", "No module named 'kilosort'"],
        "tier": "RED",
        "fix": "suggest: uv add kilosort4",
    },
    "zero_units_after_curation": {
        "patterns": [],  # 检测逻辑：good_unit_count == 0
        "tier": "RED",
        "fix": "分析哪个阈值是瓶颈，建议放松",
    },
    "amplitude_cutoff_not_computed": {
        "patterns": [],  # 检测逻辑：config 有阈值但 metrics CSV 无列
        "tier": "YELLOW",
        "fix": "修补 curate.py 添加 amplitude_cutoff 计算",
    },
}
```

### 5.4 Validation 报告格式

```json
{
  "timestamp": "2026-04-11T15:00:00",
  "stop_after": "sort",
  "stages": [
    {
      "name": "discover",
      "status": "passed",
      "duration_s": 3.2,
      "validations": [
        {"check": "probes_found", "status": "pass", "detail": "2 probes: imec0, imec1"},
        {"check": "meta_parsed", "status": "pass", "detail": "sample_rate=30000.0 Hz"}
      ]
    },
    {
      "name": "sort",
      "status": "failed",
      "duration_s": 1847.5,
      "error": {
        "class": "cuda_oom",
        "message": "CUDA out of memory. Tried to allocate 2.50 GiB...",
        "traceback": "...(完整 traceback)...",
        "suggestion": "Reduce batch_size from 60000 to 40000",
        "auto_fixable": true,
        "fix_tier": "GREEN",
        "fix_applied": true,
        "fix_detail": "Updated sorting_config.sorter_params.batch_size: 60000 → 40000"
      }
    }
  ]
}
```

## 6. 自动修复层

### 6.1 三级分类

| 级别 | 条件 | 动作 | 示例 |
|------|------|------|------|
| **GREEN** | 修复明确、可逆、不改算法行为 | 立即应用，记录到 `auto_fixes.json` | `torch_device: cuda → auto`；降低 `batch_size` |
| **YELLOW** | 明确的源码 BUG：config 字段未使用、校验缺失、指标名错误 | 修补源文件，记录完整 diff | 添加 `amplitude_cutoff` 到 curate 指标；添加 CUDA 校验到 config |
| **RED** | 涉及算法选择、阈值调优、架构决策、意图不明 | 写入 `suggested_fixes.md`，不自动应用 | "零单元 — 放松阈值还是检查 sorting？"；"运动校正 + nblocks 同时启用" |

### 6.2 YELLOW 级安全护栏

- 仅修改 `src/pynpxpipe/` 下的文件 — 不碰测试、文档、配置模板
- 每次修复记录完整 before/after diff 到 `auto_fixes.json`
- 不能生成干净、最小 diff 时，降级为 RED
- **只添加缺失逻辑，不删除代码**

### 6.3 审计日志格式

```json
{
  "timestamp": "2026-04-11T14:32:00",
  "fixes": [
    {
      "tier": "GREEN",
      "target": "config",
      "description": "Set torch_device to auto (no CUDA GPU detected)",
      "file": "config/sorting.yaml",
      "before": "torch_device: cuda",
      "after": "torch_device: auto",
      "reversible": true
    },
    {
      "tier": "YELLOW",
      "target": "source",
      "description": "Add amplitude_cutoff to curate stage metrics and filter mask",
      "file": "src/pynpxpipe/stages/curate.py",
      "line_range": [100, 130],
      "diff": "--- a/src/pynpxpipe/stages/curate.py\n+++ b/src/pynpxpipe/stages/curate.py\n@@ ... @@",
      "reversible": true,
      "rationale": "CurationConfig.amplitude_cutoff_max is defined and exposed in UI but curate.py never computes or applies it"
    }
  ]
}
```

### 6.4 `suggested_fixes.md` 格式

```markdown
# Suggested Fixes — 2026-04-11T14:32

## RED: Curation yielded 0 good units for imec1
- **Stage**: curate
- **Thresholds applied**: isi_max=0.1, presence_min=0.9, snr_min=0.5
- **Total units before filter**: 47
- **Units passing each threshold**: isi=42, presence=3, snr=45
- **Bottleneck**: presence_ratio_min=0.9 filters out 44/47 units
- **Suggestion**: Consider lowering presence_ratio_min to 0.5, or investigate why presence ratios are low
- **NOT auto-fixed**: Threshold tuning is an algorithm decision
```

## 7. CC Session 集成（闭环流程）

### 7.1 闭环示意

```
CC Session 开始
  ├── 1. 读 ROADMAP.md、progress.md（现有仪式）
  ├── 2. 读 .harness/preflight_report.json
  ├── 3. 读 .harness/validation_report.json
  ├── 4. 读 .harness/suggested_fixes.md
  └── 5. 优先处理 RED 项，审计 YELLOW 已应用的修复
         │
         ▼
CC 工作阶段
  ├── 修复 harness 报告中识别的问题
  ├── 分析后应用 RED 建议
  └── 审查 auto_fixes.json 中的 YELLOW 修复
         │
         ▼
CC 验证阶段
  ├── 1. 重新运行 preflight
  ├── 2. 重新运行 validate --stop-after <已修复的 stage>
  ├── 3. 读取更新后的报告
  ├── 4. 有新问题 → 回到工作阶段
  └── 5. 全部 PASS → session 完成
         │
         ▼
CC Session 结束
  ├── 更新 progress.md
  └── 报告："Harness: N checks PASS, 0 FAIL"
```

### 7.2 CLAUDE.md 自调试闭环规则更新

现有的"核心层（L0-L3）全自动闭环"规则保持不变。新增 UI 层规则：

```
### UI 层调试（使用 harness）

1. CC 运行 `python smoke_test_harness.py preflight --session-dir <path> --config config/pipeline.yaml --sorting-config config/sorting.yaml --output-dir <output>`
2. 读取 .harness/preflight_report.json，处理所有 FAIL 项
3. CC 运行 `python smoke_test_harness.py validate --session-dir <path> --stop-after <当前stage> --output-dir <output>`
4. 读取 .harness/validation_report.json + suggested_fixes.md
5. 修复 → 重新运行 → 直到全绿
6. 将最终 harness 输出摘要粘贴在 session 收尾报告中
```

## 8. 已知的首批源码修复目标

基于当前代码审查，harness 首次运行预计会识别以下 YELLOW/RED 项：

| 问题 | 级别 | 位置 | 修复方案 |
|------|------|------|---------|
| `amplitude_cutoff_max` 有配置无计算 | YELLOW | `stages/curate.py:100-130` | 添加 `"amplitude_cutoff"` 到 `metric_names` 列表 + `keep_mask` |
| `torch_device="cuda"` 无 GPU 校验 | YELLOW | `core/config.py` 或 `stages/sort.py` | 在 sort stage 启动前校验 GPU 可用性，无 GPU 时降级为 CPU 并警告 |
| Sort stage 无 CUDA OOM 特化处理 | YELLOW | `stages/sort.py:138-149` | 捕获 `torch.cuda.OutOfMemoryError`，降低 batch_size 重试一次 |
| 运动校正 vs nblocks 互斥未强制 | GREEN | `core/config.py` 校验层 | 配置校验时检查互斥，自动禁用运动校正并警告 |
| StatusView 不显示 curation 阈值 | RED | `ui/components/status_view.py` | 需要设计：从 checkpoint JSON 提取阈值并展示（UI 变更需讨论） |

## 9. 与 MATLAB 参考实现的关系

Harness 不直接涉及 MATLAB 对比。但 `sync_validator.py` 中的对齐残差阈值应参考 `docs/ground_truth/step4_full_pipeline_analysis.md` 中 MATLAB 实现的同步精度标准。

## 10. 可配参数

| 参数 | 位置 | 默认值 | 说明 |
|------|------|--------|------|
| `--session-dir` | CLI | 必填 | SpikeGLX 录制文件夹路径 |
| `--config` | CLI | `config/pipeline.yaml` | Pipeline 配置文件 |
| `--sorting-config` | CLI | `config/sorting.yaml` | Sorting 配置文件 |
| `--output-dir` | CLI | 必填 | Pipeline 输出目录（harness 写入 `.harness/` 子目录） |
| `--stop-after` | CLI (validate) | 最后一个 stage | 验证到哪个 stage 停止 |
| `--no-auto-fix` | CLI | False | 禁用所有自动修复（仅报告） |
| `--fix-tier` | CLI | `GREEN` | 允许的最高自动修复级别（GREEN / YELLOW） |
| `--bhv-file` | CLI | 自动发现 | BHV2 文件路径（可选，默认从 session 目录推断） |
