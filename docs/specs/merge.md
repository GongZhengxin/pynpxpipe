# Spec: stages/merge.py

## 1. 目标

实现 pipeline 可选 stage：**自动合并（Merge）**。

使用 SpikeInterface 的 `auto_merge()` 合并相似 unit，减少过度分裂（over-splitting）。默认关闭（`config.merge.enabled = False`），用户确认 sorting 质量后主动开启。

**关键约束**：
- **不可逆操作**：`auto_merge()` 合并后无法恢复，必须创建新 SortingAnalyzer（SI 官方建议）
- **原始 sorting 保留**：sort stage 输出 `{output_dir}/02_02_sorted/{probe_id}/` 不被覆盖
- **位于 curate 之前**：合并改变 unit 集合，Bombcell 分类必须在合并后运行
- **默认关闭**：`config.merge.enabled = False`，跳过时立即 return

---

## 2. 输入

### `MergeStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `probes`、`output_dir`、`config` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调 |

### `session.config` 中读取的配置键

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `config.merge.enabled` | `bool` | `False` | 是否执行 auto-merge，**默认关闭** |

### 外部数据依赖

| 文件 | 路径 | 说明 |
|---|---|---|
| sorted SortingAnalyzer | `{output_dir}/02_02_sorted/{probe_id}/` | 由 sort stage 写出（binary_folder 格式） |

---

## 3. 输出

### 每个 probe 的输出

| 输出 | 路径 | 说明 |
|---|---|---|
| merged SortingAnalyzer | `{output_dir}/03_03_merged/{probe_id}/` | 新建的 binary_folder，含合并后 sorting |
| merge 日志 | `{output_dir}/03_03_merged/{probe_id}/merge_log.json` | 合并详情（哪些 unit 被合并、前后数量） |
| per-probe checkpoint | `{output_dir}/checkpoints/merge_{probe_id}.json` | 含合并前后 unit 数量 |

### per-probe checkpoint payload

```json
{
  "probe_id": "imec0",
  "n_units_before": 142,
  "n_units_after": 118,
  "n_merges": 12
}
```

### merge_log.json 结构

```json
{
  "merges": [
    {"merged_ids": [23, 45], "new_id": 23},
    {"merged_ids": [67, 89, 91], "new_id": 67}
  ],
  "n_units_before": 142,
  "n_units_after": 118
}
```

---

## 4. 处理步骤

### `run()`

1. **检查 enabled**：若 `config.merge.enabled == False` → `_report_progress("Merge skipped (disabled)", 1.0)` → return
2. 检查 stage 级 checkpoint；若完成 → return
3. `_report_progress("Starting merge", 0.0)`
4. 对 `session.probes` 串行遍历，调用 `_merge_probe(probe_id)`
5. 每个 probe 完成后报告进度
6. 所有完成 → `_write_checkpoint({...})` + `_report_progress("Merge complete", 1.0)`

### `_merge_probe(probe_id)`

1. **检查 per-probe checkpoint**；若已完成 → return
2. **加载 sorted SortingAnalyzer**：`si.load(output_dir / "sorted" / probe_id)`
3. **确保必要扩展已计算**：`auto_merge()` 需要 `templates` 和 `template_similarity`。若缺失则计算：
   ```python
   if not analyzer.has_extension("templates"):
       analyzer.compute("random_spikes")
       analyzer.compute("waveforms")
       analyzer.compute("templates")
   if not analyzer.has_extension("template_similarity"):
       analyzer.compute("template_similarity")
   ```
4. **执行 auto_merge**：
   ```python
   from spikeinterface.curation import auto_merge
   merged_sorting, merge_info = auto_merge(analyzer, return_merge_info=True)
   ```
5. **创建新 SortingAnalyzer**（不修改原始）：
   ```python
   merged_analyzer = si.create_sorting_analyzer(
       merged_sorting,
       analyzer.recording,
       format="binary_folder",
       folder=output_dir / "merged" / probe_id,
       sparse=True,
   )
   ```
6. **写 merge_log.json**：记录合并详情
7. **写 per-probe checkpoint**
8. **释放内存**：`del analyzer, merged_analyzer; gc.collect()`

---

## 5. 公开 API

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class MergeStage(BaseStage):
    """Optional auto-merge stage using SpikeInterface auto_merge().

    Default OFF (config.merge.enabled = False). When enabled, merges
    similar units to reduce over-splitting. Creates a new SortingAnalyzer
    in 03_merged/{probe_id}/ — original sorted output is preserved.

    Must run BEFORE curate so that Bombcell classification operates
    on the final (merged) unit set.

    Raises:
        MergeError: If sorted analyzer cannot be loaded.
    """

    STAGE_NAME = "merge"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None: ...

    def run(self) -> None:
        """Run auto-merge for all probes, or skip if disabled."""

    def _merge_probe(self, probe_id: str) -> None:
        """Auto-merge one probe's sorted units.

        Args:
            probe_id: Probe identifier (e.g. "imec0").
        """
```

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_merge.py`

### 跳过逻辑

| 测试名 | 预期行为 |
|---|---|
| `test_skip_when_disabled` | `enabled=False` → run() 立即返回，不加载 analyzer |
| `test_stage_skips_if_checkpoint_complete` | stage checkpoint complete → run() 立即返回 |

### 正常流程

| 测试名 | 预期行为 |
|---|---|
| `test_merge_creates_new_analyzer` | `merged/imec0/` 目录存在（binary_folder） |
| `test_original_sorted_preserved` | `sorted/imec0/` 目录未被修改 |
| `test_merge_log_written` | `merged/imec0/merge_log.json` 存在，含 merges 列表 |
| `test_probe_checkpoint_written` | `checkpoints/merge_imec0.json` status=completed |
| `test_unit_count_decreases_or_equal` | n_units_after <= n_units_before |
| `test_gc_called_after_probe` | `gc.collect` 在每个 probe 后被调用 |

### 断点续跑

| 测试名 | 预期行为 |
|---|---|
| `test_skips_merged_probe` | imec0 checkpoint complete → 不重新合并 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.MergeError` | 项目内部 | 合并失败时抛出 |
| `spikeinterface.core` | 第三方 | `load`、`create_sorting_analyzer` |
| `spikeinterface.curation` | 第三方 | `auto_merge`（SI ≥0.102） |
| `gc` | 标准库 | 显式内存释放 |
| `json` | 标准库 | merge_log.json 写出 |

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | 无直接对应——MATLAB 管线不包含自动合并步骤 |

### 有意偏离

| 偏离 | 理由 |
|------|------|
| 新增 auto-merge stage | MATLAB 依赖 Kilosort 内部合并；Python 使用 SI `auto_merge()` 提供更灵活的后处理合并 |
| 默认关闭 | auto-merge 是不可逆操作，默认关闭更安全；用户确认 sorting 质量后主动开启 |
| 创建新 analyzer 而非原地修改 | SI 官方建议：merges cannot be reverted |
