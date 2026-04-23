# Spec: stages/curate.py

## 1. 目标

实现 pipeline 第五个 stage：**质控（Curate）**。

对每个 probe 的 sorting 结果计算质量指标，使用 `bombcell_label_units()` 进行四分类（SUA / MUA / NON-SOMA / NOISE），仅丢弃 NOISE。保存过滤后的 sorting 到 `{output_dir}/05_curated/{probe_id}/`，同时保存全部单元（过滤前）的 quality_metrics.csv 和 bombcell 诊断图供人工检查。

**关键约束**：
- **分类方法**：主路径使用 `spikeinterface.curation.bombcell_label_units(sorting_analyzer)` 进行四分类（`good` → SUA, `mua` → MUA, `non_soma` → NON-SOMA, `noise` → NOISE）。需要 SortingAnalyzer 已计算 `quality_metrics`（包含 bombcell 专属 4 个 metric：`amplitude_median`、`num_spikes`、`rp_contamination`（来自 `rp_violation`）、`drift_ptp`（来自 `drift`））和 `template_metrics` 两个扩展。`drift` 指标额外依赖 `spike_locations` 扩展。当 `config.curation.use_bombcell = False` 时退回手动阈值两级分类（SUA / MUA / NOISE）作为 fallback。
- `unittype_string` 属性（"SUA"/"MUA"/"NON-SOMA"/"NOISE"）设置在 curated sorting 上，供下游 export 使用。仅 NOISE 被丢弃，SUA + MUA + NON-SOMA 保留。
- SortingAnalyzer 使用 `format="memory"`（不写磁盘）—— 只需要 quality_metrics，不需要 waveforms
- 过滤后 0 个单元是 WARNING，不是 error
- **bombcell labels DataFrame 列名为 `bombcell_label`**（SI ≥0.104 的命名）。历史 spec 误写为 `label`，实现需以当前 SI API 为准。

---

## 2. 输入

### `CurateStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `probes`、`output_dir`、`config` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调 |

### `session.config` 中读取的配置键

**顶层 `curation` 段**（fallback 路径专用，`use_bombcell=False` 时生效）：

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `config.curation.use_bombcell` | `bool` | `True` | True: 走 bombcell 主路径；False: 走手动阈值 fallback |
| `config.curation.isi_violation_ratio_max` | `float` | `2.0` | fallback：NOISE 过滤 ISI 上限 |
| `config.curation.amplitude_cutoff_max` | `float` | `0.5` | fallback：NOISE 过滤 amplitude_cutoff 上限 |
| `config.curation.presence_ratio_min` | `float` | `0.5` | fallback：NOISE 过滤 presence_ratio 下限 |
| `config.curation.snr_min` | `float` | `0.3` | fallback：NOISE 过滤 SNR 下限 |
| `config.curation.good_isi_max` | `float` | `0.1` | fallback：SUA 分类 ISI 上限 |
| `config.curation.good_snr_min` | `float` | `3.0` | fallback：SUA 分类 SNR 下限 |

**嵌套 `curation.bombcell` 段**（主路径专用，覆盖 SI `bombcell_label_units` 的 `mua` 层阈值；默认值向 MATLAB `bc_qualityParamValues` 对齐，显著宽于 SI 默认）：

| 配置键 | 类型 | 默认 (MATLAB) | SI 默认 | 映射到 SI thresholds dict |
|---|---|---|---|---|
| `config.curation.bombcell.amplitude_median_min` | `float` | `20.0` µV | `30.0` | `mua.amplitude_median.greater` |
| `config.curation.bombcell.num_spikes_min` | `int` | `50` | `300` | `mua.num_spikes.greater` |
| `config.curation.bombcell.presence_ratio_min` | `float` | `0.2` | `0.7` | `mua.presence_ratio.greater` |
| `config.curation.bombcell.snr_min` | `float` | `3.0` | `5.0` | `mua.snr.greater` |
| `config.curation.bombcell.amplitude_cutoff_max` | `float` | `0.2` | `0.2` | `mua.amplitude_cutoff.less` |
| `config.curation.bombcell.rp_contamination_max` | `float` | `0.1` | `0.1` | `mua.rp_contamination.less` |
| `config.curation.bombcell.drift_ptp_max` | `float` | `100.0` µm | `100.0` | `mua.drift_ptp.less` |
| `config.curation.bombcell.label_non_somatic` | `bool` | `True` | `True` | `bombcell_label_units(label_non_somatic=...)` |
| `config.curation.bombcell.split_non_somatic_good_mua` | `bool` | `False` | `False` | `bombcell_label_units(split_non_somatic_good_mua=...)` |
| `config.curation.bombcell.extra_overrides` | `dict` | `{}` | — | 嵌套 dict，deep-merge 进最终 thresholds（可覆盖 `noise`/`non-somatic` 层或任何未暴露 metric） |

**构造流程**（`_build_bombcell_thresholds`）：
1. 调 `sc.bombcell_get_default_thresholds()` 拿 SI 默认（含 `noise` / `mua` / `non-somatic` 三层）
2. deepcopy，按 BombcellConfig 字段覆盖 `mua` 层对应 metric 的 `greater` / `less` 键（保留同 metric 下的 `abs` 等其他键）
3. 若 `extra_overrides` 非空，deep-merge 进 thresholds（key 冲突时 overrides 优先）
4. 传入 `bombcell_label_units(analyzer, thresholds=..., label_non_somatic=..., split_non_somatic_good_mua=...)`

---

## 3. 输出

### 每个 probe 的输出

| 输出 | 路径 | 说明 |
|---|---|---|
| 过滤后 sorting | `{output_dir}/05_curated/{probe_id}/` | binary_folder 格式，含 SUA + MUA + NON-SOMA 单元（NOISE 已丢弃），带 `unittype_string` 属性 |
| 质量指标 CSV | `{output_dir}/05_curated/{probe_id}/quality_metrics.csv` | 全部单元（含被过滤的），含各指标值 |
| 自制诊断图 | `{output_dir}/05_curated/{probe_id}/figures/quality_metrics_dist.png` 等 3 张 | 由 `pynpxpipe.plots.curate.emit_all()` 写入 |
| Bombcell 诊断图（主路径） | `{output_dir}/05_curated/{probe_id}/figures/bombcell_unit_labels.png`, `bombcell_metric_histograms.png`, `bombcell_labels_upset.png` | 由 `pynpxpipe.plots.bombcell.emit_bombcell_plots()` 写入，仅 `use_bombcell=True` 且 bombcell 成功返回 `labels_df` 时全部生成 |
| Bombcell 降级图（fallback） | `{output_dir}/05_curated/{probe_id}/figures/bombcell_unit_labels.png` | bombcell 失败或 `use_bombcell=False` 时，用手动/降级 label 仅绘制 `plot_unit_labels` 一张，另两张（需要 bombcell thresholds）跳过 |
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
2. **加载 sorting**：从 `{output_dir}/02_02_sorted/{probe_id}/` 加载，`si.load(sorted_path)`
3. **加载预处理录制**（用于计算 noise levels）：从 `{output_dir}/01_01_preprocessed/{probe_id}/` lazy 加载
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
   analyzer.compute("spike_amplitudes")
   if curation.use_bombcell:
       # spike_locations 必需，drift 指标依赖它（monopolar triangulation，分钟级）
       analyzer.compute("spike_locations")
   # template_metrics 供 bombcell 形态学分类使用（non_soma 判断）
   analyzer.compute("template_metrics")
   # quality_metrics：bombcell 路径多算 amplitude_median / num_spikes /
   # rp_violation (→ rp_contamination) / drift (→ drift_ptp) / firing_rate
   if curation.use_bombcell:
       metric_names = [
           "snr", "amplitude_cutoff", "amplitude_median", "presence_ratio",
           "num_spikes", "isi_violation", "rp_violation", "drift", "firing_rate",
       ]
   else:
       metric_names = ["isi_violation", "amplitude_cutoff", "presence_ratio", "snr"]
   analyzer.compute("quality_metrics", metric_names=metric_names)
   ```
6. **获取质量指标**：`qm = analyzer.get_extension("quality_metrics").get_data()`（返回 DataFrame）
7. **保存 quality_metrics.csv**：`qm.to_csv(output_dir / "curated" / probe_id / "quality_metrics.csv")`，`mkdir(parents=True, exist_ok=True)`
8. **记录过滤前数量**：`n_before = len(sorting.get_unit_ids())`
9. **四级分类 SUA / MUA / NON-SOMA / NOISE**：

   **主路径**（`use_bombcell=True`，默认）：
   ```python
   from spikeinterface.curation import bombcell_label_units
   bombcell_cfg = curation.bombcell  # BombcellConfig
   thresholds_dict = _build_bombcell_thresholds(bombcell_cfg)  # see §2 构造流程
   labels_df = bombcell_label_units(
       analyzer,
       thresholds=thresholds_dict,
       label_non_somatic=bombcell_cfg.label_non_somatic,
       split_non_somatic_good_mua=bombcell_cfg.split_non_somatic_good_mua,
   )
   label_map = {"good": "SUA", "mua": "MUA", "non_soma": "NON-SOMA", "noise": "NOISE"}
   unittype_map = {
       uid: label_map.get(str(label).lower(), "NOISE")
       for uid, label in labels_df["bombcell_label"].items()
   }
   # labels_df 和 thresholds_dict 随后传给 bombcell 诊断绘图层（见步骤 11bis）。
   # 若 bombcell 失败（记 WARNING），退入 fallback，labels_df / thresholds_dict 置 None。
   ```

   **Fallback 路径**（`use_bombcell=False`）：
   ```python
   for uid in unit_ids:
       isi = qm.loc[uid, "isi_violation_ratio"]
       snr_val = qm.loc[uid, "snr"]
       if isi <= curation.good_isi_max and snr_val >= curation.good_snr_min:
           unittype_map[uid] = "SUA"
       elif isi <= curation.isi_violation_ratio_max and snr_val >= curation.snr_min:
           unittype_map[uid] = "MUA"
       else:
           unittype_map[uid] = "NOISE"
   ```

   **分类逻辑**：
   - **SUA**（Single Unit Activity）：高质量单细胞（bombcell `good` 或手动阈值 `isi <= good_isi_max AND snr >= good_snr_min`）
   - **MUA**（Multi-Unit Activity）：多单元活动，不满足 SUA 条件但仍可用
   - **NON-SOMA**：非胞体信号（仅 bombcell 路径产生，基于 waveform 形态特征）
   - **NOISE**：不满足以上条件的均为 NOISE（丢弃）
   
   过滤保留 SUA + MUA + NON-SOMA，丢弃 NOISE：
   ```python
   keep_ids = [uid for uid, utype in unittype_map.items() if utype != "NOISE"]
   curated_sorting = sorting.select_units(keep_ids)
   curated_sorting.set_property("unittype_string", [unittype_map[uid] for uid in keep_ids])
   ```
10. **检查结果**：`n_after = len(keep_ids)`；若 `n_after == 0` → 记录 WARNING（继续）
11. **保存过滤后 sorting**：`curated_sorting.save(folder=output_dir / "curated" / probe_id, overwrite=True)`
12. **写 per-probe checkpoint**：含 n_before、n_after、thresholds
13. **绘图**：
    - `pynpxpipe.plots.curate.emit_all(...)`：3 张自制 QM 分布 / 分类饼图 / 波形图到 `05_curated/{probe_id}/figures/`（现有逻辑不变）。
    - `pynpxpipe.plots.bombcell.emit_bombcell_plots(analyzer, unittype_map, labels_df, thresholds, probe_id, figures_dir)`：
      - 接收的 `labels_df` 可以是 DataFrame（主路径）或 `None`（fallback 路径）。`thresholds` 同理。
      - 主路径（`labels_df is not None and thresholds is not None`）：依序调用 `sw.plot_unit_labels` → `sw.plot_metric_histograms` → `sw.plot_bombcell_labels_upset`，每张图单独 try/except，fail-open。
      - Fallback 路径（`labels_df is None`）：只绘制 `sw.plot_unit_labels`（sw 函数只要 label ndarray，不依赖 bombcell thresholds），其余两张跳过。
      - matplotlib / spikeinterface.widgets 不可用时返回空列表，记 INFO 日志。
14. **释放内存**：`del analyzer, sorting, recording; import gc; gc.collect()`
15. 返回 `(n_before, n_after)`

### 诊断图（可选，`{output_dir}/05_curated/{probe_id}/figures/`）

若 `config.sync.generate_plots == True` 且 matplotlib 可用，在 `_curate_probe()` 步骤 11 后为每个 probe 生成一张汇总图。

**文件名**: `curate_qm_summary_{probe_id}.png`

**布局**: 2×3 subplot，sgtitle 显示 `{session_path} / {probe_id}`

| subplot | 图表类型 | 数据来源 | QC 检查要点 | MATLAB 对照 |
|---------|---------|---------|------------|------------|
| (1,1) | 直方图 + 阈值线 | `quality_metrics.isi_violation_ratio` | ISI 分布应双峰，NOISE 阈值线（2.0）右侧为噪声 | #16 (Bombcell) |
| (1,2) | 直方图 + 双阈值线 | `quality_metrics.snr` | SUA 阈值线（3.0）+ MUA 阈值线（0.3），分布应集中在高 SNR | #16 |
| (1,3) | 直方图 + 阈值线 | `quality_metrics.amplitude_cutoff` | 截断分布，阈值线（0.5）以上为 NOISE | #16 |
| (2,1) | 直方图 + 阈值线 | `quality_metrics.presence_ratio` | 分布应集中在高 presence，阈值线（0.5）以下为 NOISE | #16 |
| (2,2) | 饼图 | SUA / MUA / NON-SOMA / NOISE 各分类计数 | 确认 NOISE 比例合理（通常 <30%） | #16 |
| (2,3) | 散点图 | SNR vs ISI violation ratio，颜色按分类 | 四类应可视分离 | — |

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

    Primary classification: bombcell_label_units() → SUA/MUA/NON-SOMA/NOISE.
    Fallback (use_bombcell=False): manual threshold → SUA/MUA/NOISE.
    Requires quality_metrics + template_metrics extensions.

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

见 §2 输入"`session.config` 中读取的配置键" 两张表。所有阈值均可配，**禁止硬编码**。

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_curate.py`

测试策略：用 `si.NumpyRecording` + `si.NumpySorting` 创建合成测试数据（避免真实文件依赖）；mock `si.load` 返回合成对象；用 `tmp_path` 作为 output_dir。

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
| `test_extension_order_correct` | `random_spikes → waveforms → templates → noise_levels → spike_amplitudes → spike_locations (bombcell only) → template_metrics → quality_metrics` 顺序调用 |

### Bombcell metric 集（RED 对应根因 fix）

| 测试名 | 预期行为 |
|---|---|
| `test_metric_names_include_bombcell_set_when_use_bombcell` | `analyzer.compute("quality_metrics", metric_names=...)` 的 `metric_names` 包含 `{amplitude_median, num_spikes, rp_violation, drift}` 四个键 |
| `test_metric_names_minimal_when_use_bombcell_false` | `use_bombcell=False` 时 metric_names 只有 4 个默认项 |
| `test_spike_locations_computed_when_use_bombcell` | bombcell 路径调用了 `analyzer.compute("spike_locations")` |
| `test_spike_locations_skipped_when_use_bombcell_false` | fallback 路径不计算 `spike_locations`（节省分钟级耗时） |
| `test_classify_bombcell_reads_bombcell_label_column` | `labels_df["bombcell_label"]` 读取有效，不再读历史错误的 `["label"]` |
| `test_classify_bombcell_returns_triple` | `_classify_bombcell` 返回 `(unittype_map, labels_df, thresholds_dict)` |
| `test_classify_bombcell_fallback_returns_nones` | bombcell 异常时，triple 的第二、三项为 `None` |

### Bombcell thresholds 配置传参（MATLAB 对齐）

| 测试名 | 预期行为 |
|---|---|
| `test_classify_bombcell_passes_merged_thresholds` | `bombcell_label_units` 的 `thresholds=` 关键字含 BombcellConfig 字段覆写后的 `mua` 层（`presence_ratio.greater == 0.2` 等 MATLAB 值） |
| `test_classify_bombcell_passes_label_non_somatic_flag` | `bombcell_label_units` 收到 `label_non_somatic=True` 和 `split_non_somatic_good_mua=False`（默认） |
| `test_classify_bombcell_passes_custom_label_non_somatic` | 用户把 config 改成 `label_non_somatic=False` 时透传到 SI |
| `test_build_bombcell_thresholds_preserves_noise_layer` | `noise` 层 metric 未被 `mua` 覆写（deepcopy + 只改 mua） |
| `test_build_bombcell_thresholds_extra_overrides_deep_merge` | `extra_overrides={"noise": {"waveform_baseline_flatness": {"less": 0.9}}}` 正确 merge，不清掉 noise 层其他项 |
| `test_build_bombcell_thresholds_preserves_abs_flag` | 覆写 `amplitude_median.greater` 时保留同 metric 下的 `abs: True` |

### Bombcell 诊断图

| 测试名 | 预期行为 |
|---|---|
| `test_bombcell_plots_emitted_on_main_path` | 3 张 PNG 存在于 `05_curated/{probe_id}/figures/` |
| `test_bombcell_plots_single_on_fallback` | fallback 时仅 `bombcell_unit_labels.png` 存在，其余两张缺失 |
| `test_bombcell_plots_failopen_on_widget_error` | 某张 sw 图抛异常时 stage 不 raise，其他图仍生成 |
| `test_bombcell_plots_skipped_without_mpl` | matplotlib 未安装时返回空列表并记 INFO |

### 断点续跑

| 测试名 | 预期行为 |
|---|---|
| `test_skips_curated_probe` | imec0 checkpoint complete → 不重新计算 |
| `test_stage_skips_if_complete` | stage checkpoint complete → run() 立即返回 |

### 错误处理

| 测试名 | 预期行为 |
|---|---|
| `test_loading_failure_raises_curate_error` | `si.load` raise → raise `CurateError` |
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
| `spikeinterface.core` | 第三方 | `load`（SI ≥0.101）、`create_sorting_analyzer`、`select_units` |
| `spikeinterface.curation` | 第三方 | `bombcell_label_units`、`bombcell_get_default_thresholds`（SI ≥0.104） |
| `spikeinterface.qualitymetrics` | 第三方 | quality_metrics 扩展计算 |
| `spikeinterface.widgets` | 第三方（可选） | `plot_unit_labels` / `plot_metric_histograms` / `plot_bombcell_labels_upset` —— 由 `pynpxpipe.plots.bombcell` 封装 |
| `pynpxpipe.plots.curate.emit_all` | 项目内部 | 现有 3 张自制 QM 图 |
| `pynpxpipe.plots.bombcell.emit_bombcell_plots` | 项目内部（本次新增） | bombcell 3 张 widget 图 + fallback 降级为 1 张 |
| `gc` | 标准库 | 显式内存释放 |
| `pandas` | 第三方 | quality_metrics CSV |
| `pathlib.Path` | 标准库 | 路径操作 |

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #14（Bombcell 质控） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #14 段落 |

### MATLAB 算法概要

MATLAB step #14 使用 Bombcell 工具箱进行质控：
1. 运行 `bc_qualityParamValues` 获取默认参数
2. 运行 `bc_runAllQualityMetrics` 计算全套 Bombcell 指标（ISI contamination、presence ratio、amplitude distribution 等）
3. 使用 `bc_getQualityUnitType` 将 unit 自动分类为 good/mua/noise
4. 输出 `_bc_qualityMetrics.parquet` + `_bc_unitType.tsv`

### 有意偏离

| 偏离 | 理由 |
|------|------|
| 使用 SI `bombcell_label_units()` 替代 MATLAB Bombcell 工具箱 | SI ≥0.102 内置 bombcell 四分类（good/mua/non_soma/noise），无需外部 MATLAB 依赖；手动阈值保留为 fallback |
| SortingAnalyzer 用 memory 格式 | curate 阶段仅需指标数值，不需持久化 analyzer |
| 保存全部 unit 的 CSV（含被过滤的） | MATLAB Bombcell 也保存全套指标文件；Python 同样保留供人工检查 |
| 零 unit 后 WARNING 继续 | MATLAB Bombcell 无此处理；Python 允许 pipeline 继续到 export（生成空 NWB 也是有效输出） |
| `BombcellConfig` 默认值向 MATLAB `bc_qualityParamValues` 对齐（而非 SI 默认） | SI 默认（`presence_ratio>0.7`、`num_spikes>300`、`snr>5`、`amplitude_median>30 µV`）在实际数据上产生过少 SUA；MATLAB 默认（0.2 / 50 / 3 / 20）经过长期使用验证，本项目明确以 MATLAB pipeline 为对照目标 |

### 已知限制（SI bombcell 内部行为，本 stage 无法直接控制）

- **NaN policy**：SI `bombcell_label_units` 的 `noise` 层硬编码 `nan_policy="fail"`，任何 metric 计算失败返回 NaN → 该 unit 直接判 NOISE；`mua` 层用 `nan_policy="ignore"`。MATLAB Bombcell 对缺失 metric 更宽容。绕过需要 patch SI 或改走原生 `bombcell` PyPI 包，非本 stage 范围。
- **metric_params（如 `rp_violation` 的 `refractory_period_ms`、`censored_period_ms`）**：这是 `analyzer.compute("quality_metrics", metric_params=...)` 层的参数，对应 MATLAB 的 `tauR` / `tauC`。SI 默认 2.0 ms / 0.0 ms，与 MATLAB 默认（`tauR`=2ms）基本一致，当前未暴露到 config。如需调整，另起一个 spec 改动。
