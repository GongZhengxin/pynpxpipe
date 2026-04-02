# Spec: stages/curate.py

## 1. 目标

实现 pipeline 第五个 stage：**质控（Curate）**。

对每个 probe 的 sorting 结果计算质量指标（ISI violation ratio、amplitude cutoff、presence ratio、SNR），并按配置的阈值过滤出 "good" 单元。保存过滤后的 sorting 到 `{output_dir}/curated/{probe_id}/`，同时保存全部单元（过滤前）的 quality_metrics.csv 供人工检查。

**关键约束**：
- **过滤方法**：使用 SpikeInterface 内置的 quality_metrics 扩展计算指标，然后应用**手动阈值过滤**（不使用 Bombcell 自动标注），保留配置灵活性
- SortingAnalyzer 使用 `format="memory"`（不写磁盘）—— 只需要 quality_metrics，不需要 waveforms
- 过滤后 0 个单元是 WARNING，不是 error

---

## 2. 输入

### `CurateStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `probes`、`output_dir`、`config` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调 |

### `session.config` 中读取的配置键

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `config.pipeline.curation.isi_violation_ratio_max` | `float` | `0.1` | ISI violation ratio 上限 |
| `config.pipeline.curation.amplitude_cutoff_max` | `float` | `0.1` | amplitude cutoff 上限 |
| `config.pipeline.curation.presence_ratio_min` | `float` | `0.9` | presence ratio 下限 |
| `config.pipeline.curation.snr_min` | `float` | `0.5` | SNR 下限 |
| `config.pipeline.n_jobs` | `int` | `1` | SpikeInterface 并行数 |
| `config.pipeline.chunk_duration` | `str` | `"1s"` | 分块时间窗 |

---

## 3. 输出

### 每个 probe 的输出

| 输出 | 路径 | 说明 |
|---|---|---|
| 过滤后 sorting | `{output_dir}/curated/{probe_id}/` | binary_folder 格式，仅含 good 单元 |
| 质量指标 CSV | `{output_dir}/curated/{probe_id}/quality_metrics.csv` | 全部单元（含被过滤的），含各指标值 |
| per-probe checkpoint | `{output_dir}/checkpoints/curate_{probe_id}.json` | 含过滤前后数量 |

### per-probe checkpoint payload

```json
{
  "probe_id": "imec0",
  "n_units_before": 142,
  "n_units_after": 87,
  "thresholds": {
    "isi_violation_ratio_max": 0.1,
    "amplitude_cutoff_max": 0.1,
    "presence_ratio_min": 0.9,
    "snr_min": 0.5
  }
}
```

---

## 4. 处理步骤

### `run()`

1. 检查 stage 级 checkpoint；若完成 → return
2. `_report_progress("Starting curate", 0.0)`
3. 对 `session.probes` 串行遍历，对每个 probe 调用 `_curate_probe(probe_id)`
4. 每个 probe 完成后报告进度
5. 所有 probe 完成 → `_write_checkpoint({"probe_ids": [...]})` + `_report_progress("Curate complete", 1.0)`

若某 probe raise：`_write_failed_checkpoint(error, probe_id=probe_id)` 后 re-raise。

### `_curate_probe(probe_id) -> tuple[int, int]`

1. **检查 per-probe checkpoint**：`_is_complete(probe_id=probe_id)` → 若已完成则 return `(0, 0)`（或从 checkpoint 读出已记录的值）
2. **加载 sorting**：从 `{output_dir}/sorted/{probe_id}/` 加载，`si.load_extractor(sorted_path)`
3. **加载预处理录制**（用于计算 noise levels）：从 `{output_dir}/preprocessed/{probe_id}/` lazy 加载
4. **创建 in-memory SortingAnalyzer**：
   ```python
   analyzer = si.create_sorting_analyzer(
       sorting,
       recording,
       format="memory",   # 不写磁盘，只用于计算质量指标
       sparse=True,
   )
   ```
5. **计算扩展序列**（顺序不可颠倒）：
   ```python
   analyzer.compute("random_spikes")
   analyzer.compute("waveforms", chunk_duration=..., n_jobs=...)
   analyzer.compute("templates")
   analyzer.compute("noise_levels")
   analyzer.compute("quality_metrics",
       metric_names=["isi_violation_ratio", "amplitude_cutoff",
                     "presence_ratio", "snr"])
   ```
6. **获取质量指标**：`qm = analyzer.get_extension("quality_metrics").get_data()`（返回 DataFrame）
7. **保存 quality_metrics.csv**：`qm.to_csv(output_dir / "curated" / probe_id / "quality_metrics.csv")`，`mkdir(parents=True, exist_ok=True)`
8. **记录过滤前数量**：`n_before = len(sorting.get_unit_ids())`
9. **应用过滤规则（手动阈值，不使用 Bombcell 自动标注）**：
   ```python
   keep_mask = (
       (qm["isi_violation_ratio"] <= config_isi_max) &
       (qm["amplitude_cutoff"] <= config_amp_max) &
       (qm["presence_ratio"] >= config_pr_min) &
       (qm["snr"] >= config_snr_min)
   )
   good_unit_ids = qm.index[keep_mask].tolist()
   curated_sorting = sorting.select_units(good_unit_ids)
   ```
   **注**：过滤完全由配置中的阈值驱动，不调用任何 Bombcell API。这样做是为了保留配置灵活性，允许用户通过调整 YAML 参数快速迭代过滤策略，而无需修改代码。
10. **检查结果**：`n_after = len(good_unit_ids)`；若 `n_after == 0` → 记录 WARNING（继续）
11. **保存过滤后 sorting**：`curated_sorting.save(folder=output_dir / "curated" / probe_id, format="binary_folder")`
12. **写 per-probe checkpoint**：含 n_before、n_after、thresholds
13. **释放内存**：`del analyzer, sorting, recording; import gc; gc.collect()`
14. 返回 `(n_before, n_after)`

---

## 5. 公开 API

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class CurateStage(BaseStage):
    """Computes quality metrics and filters units for each probe.

    Uses SpikeInterface built-in quality_metrics extension (ISI violation ratio,
    amplitude cutoff, presence ratio, SNR). Thresholds read from
    config.pipeline.curation — never hardcoded.

    SortingAnalyzer uses format="memory" (no disk write needed for curation).
    Curated sorting saved as binary_folder. quality_metrics.csv saved for
    all units (pre-filter) for manual inspection.

    Zero units after curation: WARNING, not error (pipeline continues).

    Raises:
        CurateError: If sorting or recording cannot be loaded.
    """

    STAGE_NAME = "curate"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None: ...

    def run(self) -> None:
        """Compute quality metrics and curate all probes serially."""

    def _curate_probe(self, probe_id: str) -> tuple[int, int]:
        """Run curation for a single probe.

        Args:
            probe_id: Probe identifier (e.g. "imec0").

        Returns:
            Tuple (n_units_before, n_units_after).
        """
```

### 可配参数

| 参数 | 配置键 | 默认 | 说明 |
|---|---|---|---|
| `isi_violation_ratio_max` | `config.pipeline.curation.isi_violation_ratio_max` | `0.1` | **禁止硬编码** |
| `amplitude_cutoff_max` | `config.pipeline.curation.amplitude_cutoff_max` | `0.1` | **禁止硬编码** |
| `presence_ratio_min` | `config.pipeline.curation.presence_ratio_min` | `0.9` | **禁止硬编码** |
| `snr_min` | `config.pipeline.curation.snr_min` | `0.5` | **禁止硬编码** |

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_curate.py`

测试策略：用 `si.NumpyRecording` + `si.NumpySorting` 创建合成测试数据（避免真实文件依赖）；mock `si.load_extractor` 返回合成对象；用 `tmp_path` 作为 output_dir。

### 正常流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_curates_all_probes` | 2 probes，各 10 units | `_curate_probe` 对每个 probe 调用一次 |
| `test_quality_metrics_csv_written` | 正常 | `curated/imec0/quality_metrics.csv` 存在 |
| `test_curated_sorting_saved` | 正常 | `curated/imec0/` 目录存在（binary_folder） |
| `test_probe_checkpoint_written` | 正常 | `checkpoints/curate_imec0.json` status=completed |
| `test_curate_returns_unit_counts` | 10 units，5 pass filter | `_curate_probe` 返回 `(10, 5)` |
| `test_stage_checkpoint_written` | 所有 probe 完成 | `checkpoints/curate.json` status=completed |
| `test_gc_called_after_probe` | 任意 | `gc.collect` 在每个 probe 后被调用 |

### 过滤逻辑

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_units_passing_all_thresholds_kept` | 所有指标在阈值内 | good units 被保留 |
| `test_units_failing_any_threshold_removed` | isi > max | 该 unit 被过滤 |
| `test_zero_units_after_curation_logs_warning` | 所有 units 均不过关 | 不 raise，`n_after == 0`，记录 WARNING |
| `test_thresholds_read_from_config` | `snr_min=2.0` | 过滤以 config 中的阈值执行 |

### 析构顺序

| 测试名 | 预期行为 |
|---|---|
| `test_analyzer_uses_memory_format` | `create_sorting_analyzer` 以 `format="memory"` 调用 |
| `test_extension_order_correct` | random_spikes → waveforms → templates → noise_levels → quality_metrics 顺序调用 |

### 断点续跑

| 测试名 | 预期行为 |
|---|---|
| `test_skips_curated_probe` | imec0 checkpoint complete → 不重新计算 |
| `test_stage_skips_if_complete` | stage checkpoint complete → run() 立即返回 |

### 错误处理

| 测试名 | 预期行为 |
|---|---|
| `test_loading_failure_raises_curate_error` | `si.load_extractor` raise → raise `CurateError` |
| `test_failed_checkpoint_written_on_error` | 任意失败 | `checkpoints/curate_imec0.json` status=failed |

### CSV 内容

| 测试名 | 预期行为 |
|---|---|
| `test_quality_metrics_csv_contains_all_units` | CSV 行数 == n_before（含被过滤单元） |
| `test_quality_metrics_csv_has_required_columns` | CSV 含 isi_violation_ratio、snr 等列 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.CurateError` | 项目内部 | 质控失败时抛出 |
| `spikeinterface.core` | 第三方 | `load_extractor`、`create_sorting_analyzer`、`select_units` |
| `spikeinterface.qualitymetrics` | 第三方 | quality_metrics 扩展计算 |
| `gc` | 标准库 | 显式内存释放 |
| `pandas` | 第三方 | quality_metrics CSV |
| `pathlib.Path` | 标准库 | 路径操作 |
