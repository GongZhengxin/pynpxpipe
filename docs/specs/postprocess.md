# Spec: stages/postprocess.py

## 1. 目标

实现 pipeline 第六个 stage：**后处理（Postprocess）**。

对每个 probe 的 curated sorting 结果运行完整的 SortingAnalyzer 扩展流程（waveforms → templates → unit_locations → template_similarity），计算每个单元的 SLAY（Stimulus-Locked Activity Yield）分数，并执行眼动有效性验证（可选）。保存 SortingAnalyzer 到 `{output_dir}/postprocessed/{probe_id}/`，供 export stage 使用。

**内存管理**：waveform 提取可能 OOM；遇到 `MemoryError` 时将 `chunk_duration` 减半，重试一次。若仍失败 → raise `PostprocessError`。

---

## 2. 输入

### `PostprocessStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `probes`、`output_dir`、`config` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调 |

### `session.config` 中读取的配置键

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `config.pipeline.n_jobs` | `int` | `1` | SpikeInterface job 数 |
| `config.pipeline.chunk_duration` | `str` | `"1s"` | 初始分块时间窗；OOM 时减半 |
| `config.pipeline.postprocess.slay_pre_s` | `float` | `0.05` | SLAY 预刺激窗口（秒） |
| `config.pipeline.postprocess.slay_post_s` | `float` | `0.30` | SLAY 刺激后窗口（秒） |
| `config.pipeline.postprocess.eye_validation.enabled` | `bool` | `True` | 是否执行眼动验证 |
| `config.pipeline.postprocess.eye_validation.eye_threshold` | `float` | `0.999` | 注视比例阈值（cf. MATLAB `eye_thres=0.999`） |

### 外部数据依赖

| 文件 | 路径 | 说明 |
|---|---|---|
| behavior_events.parquet | `{output_dir}/sync/behavior_events.parquet` | 由 synchronize stage 写出，含 `stim_onset_nidq_s`、`stim_onset_imec_s` |
| curated sorting | `{output_dir}/curated/{probe_id}/` | 由 curate stage 写出 |
| preprocessed recording | `{output_dir}/preprocessed/{probe_id}/` | 由 preprocess stage 写出（Zarr） |

---

## 3. 输出

### 每个 probe 的输出

| 输出 | 路径 | 说明 |
|---|---|---|
| SortingAnalyzer | `{output_dir}/postprocessed/{probe_id}/` | binary_folder 格式，含所有扩展 |
| SLAY 分数 | `{output_dir}/postprocessed/{probe_id}/slay_scores.json` | 每个 unit_id → SLAY float |
| per-probe checkpoint | `{output_dir}/checkpoints/postprocess_{probe_id}.json` | 含 unit 数量和 SLAY 统计 |

### behavior_events.parquet 更新（眼动验证）

若 `eye_validation.enabled=True`，读取并更新 `trial_valid` 列后写回。

### per-probe checkpoint payload

```json
{
  "probe_id": "imec0",
  "n_units": 87,
  "slay_mean": 0.62,
  "slay_nan_count": 3,
  "analyzer_path": "/output/postprocessed/imec0"
}
```

---

## 4. 处理步骤

### `run()`

1. 检查 stage 级 checkpoint；若完成 → return
2. **读取 behavior_events**：`pd.read_parquet(output_dir / "sync" / "behavior_events.parquet")`
3. `_report_progress("Starting postprocess", 0.0)`
4. 对 `session.probes` 串行遍历，调用 `_postprocess_probe(probe_id, behavior_events_df)`
5. 每个 probe 完成后报告进度
6. **眼动验证（可选）**：若 `eye_validation.enabled`，调用 `_run_eye_validation(behavior_events_df)` 更新 `trial_valid`，写回 parquet
7. 所有完成 → `_write_checkpoint({...})` + `_report_progress("Postprocess complete", 1.0)`

### `_postprocess_probe(probe_id, behavior_events_df)`

1. 检查 per-probe checkpoint；若已完成 → return
2. **加载资源**（lazy）：curated sorting + preprocessed recording
3. **提取该 probe 的 stim onset 时间**：从 `behavior_events_df.stim_onset_imec_s` 列解析 JSON，取 `probe_id` 对应的值；转换为 numpy 数组（IMEC 时钟秒）；过滤掉 NaN
4. **创建 SortingAnalyzer**（`format="binary_folder"`，写磁盘）：
   ```python
   analyzer = si.create_sorting_analyzer(
       sorting,
       recording,
       format="binary_folder",
       folder=output_dir / "postprocessed" / probe_id,
       sparse=True,
   )
   ```
5. **计算扩展序列**（顺序不可颠倒）：
   - `random_spikes`
   - `waveforms`（含 OOM 重试逻辑，见下）
   - `templates`
   - `unit_locations`
   - `template_similarity`
6. **SLAY 计算**：对每个 unit，调用 `_compute_slay(spike_times, stim_onset_times, pre_s, post_s)` → `slay_score`；收集为 dict `{unit_id: float}`；写到 `slay_scores.json`
7. **写 per-probe checkpoint**
8. **释放内存**：`del analyzer, sorting, recording; import gc; gc.collect()`

#### OOM 重试逻辑（waveforms 计算）

```python
chunk_duration = config.pipeline.chunk_duration
try:
    analyzer.compute("waveforms", chunk_duration=chunk_duration, n_jobs=n_jobs)
except MemoryError:
    # 减半 chunk_duration，重试一次
    reduced = _halve_chunk_duration(chunk_duration)
    logger.warning(f"MemoryError on waveforms, retrying with chunk_duration={reduced}")
    try:
        analyzer.compute("waveforms", chunk_duration=reduced, n_jobs=n_jobs)
    except MemoryError as e:
        raise PostprocessError(f"OOM on waveforms even with {reduced}: {e}") from e
```

`_halve_chunk_duration("1s") → "0.5s"`；`_halve_chunk_duration("500ms") → "250ms"`。

### `_compute_slay(spike_times, stim_onset_times, pre_s, post_s) -> float`

SLAY（Stimulus-Locked Activity Yield）：计算该 unit 响应的 trial-to-trial 可靠性。

**算法**：
1. **过滤有效 stim onset**：`valid_onsets = stim_onset_times[~np.isnan(stim_onset_times)]`
2. **检查最小 trial 数**：若 `len(valid_onsets) < 5` → return `np.nan`（数据不足）
3. **分 bin**：将 [pre_s, post_s] 窗口分成 10ms bins，`n_bins = int((pre_s + post_s) / 0.01)`
4. **逐 trial 计算 spike count 向量**：
   ```python
   trial_vectors = []
   for onset in valid_onsets:
       window_start = onset - pre_s
       window_end = onset + post_s
       spikes_in_window = spike_times[(spike_times >= window_start) & (spike_times < window_end)]
       counts, _ = np.histogram(spikes_in_window - window_start, bins=n_bins, range=(0, pre_s + post_s))
       trial_vectors.append(counts)
   trial_vectors = np.array(trial_vectors)  # shape: (n_trials, n_bins)
   ```
5. **计算 trial 对之间的 Spearman 相关系数**：
   ```python
   from scipy.stats import spearmanr
   correlations = []
   n_trials = len(trial_vectors)
   for i in range(n_trials):
       for j in range(i + 1, n_trials):
           corr, _ = spearmanr(trial_vectors[i], trial_vectors[j])
           if not np.isnan(corr):
               correlations.append(corr)
   ```
6. **方向性过滤**（cf. MATLAB step #19: `mean(response) > mean(baseline)`）：
   - 计算各 trial 的 baseline 平均发放率：`baseline_rate = trial_vectors[:, :pre_bins].mean(axis=1)`（前 `pre_bins = int(pre_s / 0.01)` 个 bin）
   - 计算各 trial 的 response 平均发放率：`response_rate = trial_vectors[:, pre_bins:].mean(axis=1)`
   - 计算跨 trial 均值：`mean_baseline = baseline_rate.mean()`，`mean_response = response_rate.mean()`
   - 若 `mean_response <= mean_baseline`：该 unit 为抑制性响应 → return `np.nan`（排除，不纳入有效 unit）
   - **理由**：MATLAB 原始实现要求 response > baseline，排除抑制性响应的 unit；这是实验范式的假设（视觉刺激应引起兴奋性响应）
7. **返回平均相关系数**：`return float(np.mean(correlations))` 若 `len(correlations) > 0` 否则 `np.nan`

**返回值**：
- `float`：0-1 范围，1 表示所有 trial 响应模式完全一致
- `np.nan`：有效 trial 数 < 5，或所有相关系数为 NaN

**为什么用 Spearman 而非 Pearson**：低发放率时 spike count 分布非正态，Spearman 更稳健，不受极端值影响。

### `_run_eye_validation(behavior_events_df) -> pd.DataFrame`

（若 `eye_validation.enabled=False`，跳过此方法）

1. 通过 `BHV2Parser(session.bhv_file).get_analog_data("Eye")` 获取眼动数据（逐 trial 分块读取，不预分配 3D 矩阵）
2. 对每个 trial，在 stim onset 窗口内检查 gaze 是否在注视窗口内（`fixation_window` 从 BHV2 TrialData 读取）
3. 计算 fixation ratio：`ratio = sum(distance < fixation_window) / n_samples`
4. 若 `ratio > eye_threshold`（从 config 读取，默认 `0.999`；cf. MATLAB `eye_thres = 0.999`）：`trial_valid = 1.0`；否则 `trial_valid = 0.0`
5. 更新 `behavior_events_df["trial_valid"]` 列
6. 写回 parquet：`df.to_parquet(output_dir / "sync" / "behavior_events.parquet")`
7. 返回更新后的 DataFrame

**trial_valid_idx 语义对照（❌5）**：
- **MATLAB**：`trial_valid_idx` 存储的是 image index（有效 trial 的图像编号），无效 trial 的 image index=0（零值作为"无效"标记）
- **Python**：`trial_valid` 列存储 1.0（有效）/ 0.0（无效）/ NaN（未验证），是布尔语义而非图像编号
- **兼容策略**：export stage 生成 NWB 时需根据 `trial_valid + condition_id` 重建有效图像列表。Python 不直接存储 image index，而是让 export 按需查询 `behavior_events_df[trial_valid == 1.0].condition_id`。两种方式在最终结果（哪些图像有足够有效 trial）上等价，但中间表示不同。

---

## 5. 公开 API

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    import numpy as np

    from pynpxpipe.core.session import Session


class PostprocessStage(BaseStage):
    """Computes SortingAnalyzer extensions and SLAY scores for each probe.

    Extension sequence: random_spikes → waveforms → templates →
    unit_locations → template_similarity.

    OOM handling: if waveform extraction runs out of memory, chunk_duration
    is halved and retried once. Still OOM → PostprocessError.

    SLAY: trial-to-trial Spearman correlation of spike rate vectors.
    Quantifies response reliability: 1.0 = perfect consistency,
    0.0 = random. Returns NaN if fewer than 5 qualifying trials.

    Eye validation (optional): reads BHV2 analog eye channel per trial
    (chunked, no pre-allocated 3D matrix), updates trial_valid column.
    """

    STAGE_NAME = "postprocess"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None: ...

    def run(self) -> None: ...

    def _postprocess_probe(self, probe_id: str, behavior_events_df) -> None:
        """Full postprocessing for one probe.

        Args:
            probe_id: Probe identifier.
            behavior_events_df: Trial events DataFrame from synchronize stage.

        Raises:
            PostprocessError: If OOM cannot be resolved by halving chunk_duration.
        """

    def _compute_slay(
        self,
        spike_times: np.ndarray,
        stim_onset_times: np.ndarray,
        pre_s: float = 0.05,
        post_s: float = 0.30,
    ) -> float:
        """Compute SLAY score for a single unit.

        Returns:
            Float in [0,1], or np.nan if fewer than 5 valid trials.
        """
```

### 可配参数

| 参数 | 配置键 | 默认 | 说明 |
|---|---|---|---|
| `slay_pre_s` | `config.pipeline.postprocess.slay_pre_s` | `0.05` | **禁止硬编码** |
| `slay_post_s` | `config.pipeline.postprocess.slay_post_s` | `0.30` | **禁止硬编码** |
| `eye_validation_enabled` | `config.pipeline.postprocess.eye_validation.enabled` | `True` | 眼动验证开关 |
| `eye_threshold` | `config.pipeline.postprocess.eye_validation.eye_threshold` | `0.999` | 注视比例阈值，**禁止硬编码** |
| `chunk_duration` | `config.pipeline.chunk_duration` | `"1s"` | 初始分块；OOM 时减半 |

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_postprocess.py`

### `_compute_slay` 单元测试

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_slay_identical_trials_returns_one` | 所有 trial spike 模式完全相同 | 返回 1.0 |
| `test_slay_uncorrelated_trials_returns_near_zero` | 各 trial spike 随机无规律 | 返回接近 0 的值 |
| `test_slay_nan_if_fewer_than_5_trials` | 3 valid onsets | 返回 `np.nan` |
| `test_slay_nan_onset_excluded` | 3 NaN onsets，2 valid | `len(valid_onsets) < 5` → `np.nan` |
| `test_slay_range_zero_to_one` | 正常输入（非完全相关非完全不相关） | 结果 ∈ [0.0, 1.0] |
| `test_slay_pre_post_window_from_params` | `pre_s=0.1, post_s=0.5` | 窗口边界正确（`n_bins = int(0.6/0.01) = 60`） |
| `test_slay_bin_size_10ms` | `pre_s=0.05, post_s=0.30` | `n_bins = int(0.35/0.01) = 35` |
| `test_slay_inhibitory_response_returns_nan` | mean(response) < mean(baseline) | 返回 `np.nan`（方向性过滤） |
| `test_slay_excitatory_response_passes` | mean(response) > mean(baseline) | 正常返回 float |
| `test_slay_equal_response_baseline_returns_nan` | mean(response) == mean(baseline) | 返回 `np.nan`（<= 均排除） |

### 正常流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_postprocesses_all_probes` | 2 probes | `_postprocess_probe` 各调用一次 |
| `test_analyzer_saved_to_binary_folder` | 正常 | `postprocessed/imec0/` 存在 |
| `test_slay_scores_json_written` | 正常 | `postprocessed/imec0/slay_scores.json` 存在 |
| `test_probe_checkpoint_written` | 正常 | `checkpoints/postprocess_imec0.json` status=completed |
| `test_extension_order` | 正常 | extensions 按 random_spikes→waveforms→templates→unit_locations→template_similarity 顺序调用 |
| `test_analyzer_uses_binary_folder_format` | 正常 | `create_sorting_analyzer` 以 `format="binary_folder"` 调用 |
| `test_gc_called_after_probe` | 正常 | `gc.collect` 在每个 probe 后被调用 |

### OOM 重试

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_oom_retries_with_halved_chunk` | 第一次 waveforms 抛 MemoryError | 以减半的 chunk_duration 重试 |
| `test_oom_retry_succeeds` | 重试成功 | 不 raise，处理继续 |
| `test_oom_retry_fails_raises_postprocess_error` | 两次 OOM | raise `PostprocessError` |

### 断点续跑

| 测试名 | 预期行为 |
|---|---|
| `test_skips_postprocessed_probe` | imec0 checkpoint complete → 不重新计算 |
| `test_stage_skips_if_complete` | stage checkpoint complete → run() 立即返回 |

### 眼动验证

| 测试名 | 预期行为 |
|---|---|
| `test_eye_validation_updates_trial_valid` | `enabled=True` | `trial_valid` 列被更新（非全 NaN） |
| `test_eye_validation_skipped_when_disabled` | `enabled=False` | `BHV2Parser.get_analog_data` 未被调用 |

### SLAY JSON 内容

| 测试名 | 预期行为 |
|---|---|
| `test_slay_json_keys_are_unit_ids` | JSON keys 为 unit_id 字符串 |
| `test_slay_json_values_are_floats` | JSON values 为 float（含 nan 序列化） |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.PostprocessError` | 项目内部 | 后处理失败时抛出 |
| `pynpxpipe.io.bhv.BHV2Parser` | 项目内部 | 眼动数据读取（分 trial 块） |
| `spikeinterface.core` | 第三方 | `create_sorting_analyzer`、`load_extractor` |
| `numpy` | 必选 | SLAY 计算 |
| `scipy.stats` | 必选 | Spearman 相关系数计算（`spearmanr`） |
| `pandas` | 必选 | behavior_events DataFrame |
| `gc` | 标准库 | 显式内存释放 |
| `json` | 标准库 | slay_scores.json 写出 |

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #9（眼动验证）, #15（KS4 输出加载+时钟对齐）, #18（Raster+PSTH 构建）, #19（统计过滤+波形修剪） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #9, #15, #18, #19 段落 |

### MATLAB 算法概要

**Step #9 — 眼动验证：**
- `eye_thres = 0.999`（硬编码），逐 onset 检查注视比例
- `eye_dist = sqrt(eye_data(:,1).^2 + eye_data(:,2).^2)`
- 有效判定：`eye_ratio > 0.999`
- 输出：`trial_valid_idx`（image index，0=无效），`dataset_valid_idx`（dataset 成员标记）

**Step #15 — KS4 输出时钟对齐：**
- 将 KS4 spike times 从 IMEC 时钟对齐到 NIDQ 时钟
- Python 在 export stage 中按需转换，不在 postprocess 阶段做

**Step #18 — Raster + PSTH 构建：**
- 对每个 unit，在 stim onset 窗口内统计 spike count → 10ms bin → 逐 trial 向量
- Python 的 SLAY 算法中 trial vector 构建等价于此步骤

**Step #19 — 统计过滤：**
- `mean(response) > mean(baseline)`：排除抑制性响应
- Spearman 相关系数计算 trial-to-trial 一致性
- 保留相关系数 > 阈值的 unit 为 "GoodUnit"

### 有意偏离

| 偏离 | 理由 |
|------|------|
| `trial_valid` 用 0.0/1.0 而非 image index | 语义更清晰；image index 可从 `condition_id + trial_valid` 联合查询 |
| `eye_threshold` 从 config 读取而非硬编码 | MATLAB 硬编码 0.999；Python 支持不同实验范式调整 |
| 眼动数据逐 trial 分块读取 | MATLAB 预分配 3D 矩阵 `eye_matrix [2 × onsets × T]`；Python 避免 OOM |
| SLAY 方向性过滤在计算函数内部 | MATLAB 在步骤 #19 独立做统计过滤；Python 将方向性检查集成到 `_compute_slay` 中，简化流程 |
| KS4 时钟对齐推迟到 export | MATLAB 在 #15 做一次性转换；Python 在 export 按需转换（spike times 保持原始 IMEC 时钟直到写 NWB） |
| Raster/PSTH 不单独生成 | MATLAB 生成 raster 和 PSTH 图；Python 的 SLAY 计算包含等价的 binned spike count 逻辑，可视化由下游 notebook 完成 |
