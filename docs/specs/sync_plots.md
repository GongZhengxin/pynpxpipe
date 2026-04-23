# Spec: io/sync_plots.py

## 1. 目标

生成同步流程的六张诊断 PNG 图表，保存到 `{output_dir}/04_sync/figures/` 目录。图表用于人工验证各级对齐质量，不参与数据处理逻辑，属于纯 IO 层辅助模块。

matplotlib 是**可选依赖**：若未安装，所有公开函数静默返回 `None`（不 raise，不影响 pipeline 主流程）。诊断图生成逻辑完全隔离在本模块，stages 层不 import matplotlib。

`generate_all_plots` 是主调用接口，stages/synchronize.py 仅调用该函数，不直接调用六个子函数。

---

## 2. 输入

### `generate_all_plots` 主函数参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `probe_id` | `str` | 探针标识符（如 `"imec0"`），用于文件命名 |
| `ap_sync_times` | `np.ndarray` (float64, 1D) | AP 时钟的 sync 脉冲时间序列（秒） |
| `nidq_sync_times` | `np.ndarray` (float64, 1D) | NIDQ 时钟的 sync 脉冲时间序列（秒），与 `ap_sync_times` 等长 |
| `sync_result` | `SyncResult` | IMEC↔NIDQ 对齐结果（来自 `imec_nidq_align.py`），含 `a, b, residual_ms` |
| `trial_events_df` | `pd.DataFrame` | 第二级对齐输出的 trial 事件表，含 `onset_nidq_s, stim_onset_nidq_s` 等列 |
| `calibrated_onsets` | `CalibratedOnsets` | 第三级 photodiode 校准结果，含 `onset_latency_ms, quality_flags` |
| `nidq_recording` | `si.BaseRecording` | 懒加载的 NIDQ SpikeInterface Recording 对象，用于提取 photodiode 模拟信号 |
| `config` | 配置对象 | 含 `config.sync.photodiode_channel_index`、`config.sync.pd_window_pre_ms`、`config.sync.pd_window_post_ms` |
| `output_dir` | `Path` | pipeline session 的输出根目录；图表保存在 `{output_dir}/04_sync/figures/` |

### 各子函数专属参数

| 函数 | 额外参数说明 |
|---|---|
| `plot_sync_drift` | 不需要 `trial_events_df`，`calibrated_onsets`，`nidq_recording` |
| `plot_event_alignment` | 不需要 `ap_sync_times`，`nidq_sync_times`，`sync_result`，`calibrated_onsets`，`nidq_recording` |
| `plot_photodiode_heatmap` | 不需要 `ap_sync_times`，`nidq_sync_times`，`sync_result`，`calibrated_onsets` |
| `plot_onset_latency_histogram` | 只需要 `calibrated_onsets` 和 `output_dir` |
| `plot_photodiode_mean_signal` | 不需要 `ap_sync_times`，`nidq_sync_times`，`sync_result` |
| `plot_sync_pulse_interval` | 只需要 `probe_id`，`ap_sync_times`，`output_dir` |

---

## 3. 输出

每个函数在 matplotlib 可用时保存一张 PNG 文件，返回保存路径（`Path`）；matplotlib 不可用时返回 `None`。

| 函数名 | 输出文件名 | 图表内容 |
|---|---|---|
| `plot_sync_drift` | `sync_drift_{probe_id}.png` | IMEC↔NIDQ 时钟漂移散点图 + 线性回归拟合线 |
| `plot_event_alignment` | `event_alignment.png` | BHV2 vs NIDQ 逐 trial onset 数量散点图 |
| `plot_photodiode_heatmap` | `photodiode_heatmap.png` | 所有 trial 的 photodiode 信号热力图 |
| `plot_onset_latency_histogram` | `onset_latency_histogram.png` | 逐 trial photodiode 延迟分布直方图 |
| `plot_photodiode_mean_signal` | `photodiode_mean_signal.png` | 校准前 vs 校准后平均 photodiode 信号叠加对比 |
| `plot_sync_pulse_interval` | `sync_pulse_interval.png` | 相邻 sync 脉冲间隔 vs 期望间隔散点图（检测时钟不稳定性） |

所有输出均保存在 `{output_dir}/04_sync/figures/`，该目录由各函数负责创建（`mkdir(parents=True, exist_ok=True)`）。

---

## 4. 处理步骤

### matplotlib 可用性检查（所有函数共用）

每个公开函数（包括 `generate_all_plots`）入口处执行：
```python
try:
    import matplotlib
    import matplotlib.pyplot as plt
except ImportError:
    return None
```
若 `ImportError`，**立即** return None，不执行任何后续代码，不 raise。

### `generate_all_plots`

1. 尝试 import matplotlib；失败则立即 return 空列表，记录一条 warning 日志（"matplotlib not available, skipping sync diagnostic plots"）
2. 创建输出目录 `figures_dir = output_dir / "sync" / "figures"`，`mkdir(parents=True, exist_ok=True)`
3. 依次调用六个子函数，每次调用包裹在 `try/except Exception as e`：
   - 若某个子函数 raise（非 matplotlib 缺失，而是如数据为空等运行时错误），记录 warning 日志，继续调用下一个
4. 返回成功保存的文件路径列表 `list[Path]`（或空列表）

---

### `plot_sync_drift`

**图表描述**：横轴为 AP 时钟 sync 脉冲时间（秒），纵轴为 NIDQ 时钟 sync 脉冲时间（秒）。散点图 + 拟合直线。标注 `a`、`b`、`residual_ms`。

**步骤**：
1. matplotlib 可用性检查
2. 创建 figures_dir
3. `fig, ax = plt.subplots()`
4. `ax.scatter(ap_sync_times, nidq_sync_times, s=3, alpha=0.5, label="sync pulses")`
5. 计算拟合线：`fit_y = sync_result.a * ap_sync_times + sync_result.b`，绘制 `ax.plot(ap_sync_times, fit_y, ...)`
6. 设置标题：`f"Sync Drift — {probe_id}"`，xlabel="IMEC AP clock (s)"，ylabel="NIDQ clock (s)"
7. 图例添加文字：`f"a={sync_result.a:.8f}, b={sync_result.b:.4f}s, residual={sync_result.residual_ms:.3f}ms"`
8. `fig.savefig(figures_dir / f"sync_drift_{probe_id}.png", dpi=150, bbox_inches="tight")`
9. `plt.close(fig)`；返回保存路径

---

### `plot_event_alignment`

**图表描述**：横轴为 trial 编号，纵轴为 `onset_nidq_s`（NIDQ 时钟 onset 时间，秒），散点图，每个 trial 一个点，用于直观验证 onset 序列单调递增且无异常跳变。

**步骤**：
1. matplotlib 可用性检查
2. 从 `trial_events_df` 提取 `trial_id` 和 `onset_nidq_s` 列
3. `ax.scatter(trial_id, onset_nidq_s, s=5)`
4. 标题：`"BHV2 ↔ NIDQ Event Alignment"`，xlabel="Trial ID"，ylabel="onset_nidq_s (s)"
5. 保存为 `event_alignment.png`；`plt.close(fig)`；返回路径

---

### `plot_photodiode_heatmap`

**图表描述**：热力图，行 = trial，列 = 时间（ms，[-pd_window_pre_ms, +pd_window_post_ms] 区间），颜色 = z-score 后的 photodiode 信号值。

**步骤**：
1. matplotlib 可用性检查
2. 从 `nidq_recording` 按 `config.sync.photodiode_channel_index` 提取 photodiode 信号，按 trial 分块读取（不全量加载）
3. int16→电压转换；重采样到 1ms（与 photodiode_calibrate.py 逻辑一致）
4. 对每个 trial 提取窗口，z-score 归一化后收集成 2D 矩阵 `(n_valid_trials × window_len_ms)`
5. `ax.imshow(matrix, aspect="auto", origin="upper", cmap="RdBu_r", vmin=-3, vmax=3)`
6. x 轴：时间（ms），以 0 为 stim onset 参考点；y 轴：trial index；添加 t=0 垂直线
7. colorbar 标签 "z-score"；保存为 `photodiode_heatmap.png`；`plt.close(fig)`；返回路径

---

### `plot_onset_latency_histogram`

**图表描述**：直方图，x 轴为 onset_latency_ms，y 轴为 trial 计数，仅包含 `quality_flags == 0` 的 trial。

**步骤**：
1. matplotlib 可用性检查
2. 提取 `good_latencies = calibrated_onsets.onset_latency_ms[calibrated_onsets.quality_flags == 0]`
3. 若 `len(good_latencies) == 0`：记录 warning，return None（不写空图）
4. `ax.hist(good_latencies, bins=30, edgecolor="black")`
5. 添加垂直线标记中位延迟；标题含 `n_suspicious` 数量
6. 保存为 `onset_latency_histogram.png`；`plt.close(fig)`；返回路径

---

### `plot_photodiode_mean_signal`

**图表描述**：两条曲线对比：校准前均值（以数字触发时间对齐）与校准后均值（以 photodiode onset 时间对齐），验证校准是否使信号上升沿更锐利。

**步骤**：
1. matplotlib 可用性检查
2. 准备 1ms 分辨率 photodiode 信号（与 heatmap 同方式）
3. 校准前：以 `trial_events_df.stim_onset_nidq_s` 为参考取均值 → `mean_before`
4. 校准后：以 `calibrated_onsets.stim_onset_nidq_s`（仅 `quality_flags==0`）为参考取均值 → `mean_after`
5. 叠加绘制；添加 t=0 垂直线；保存为 `photodiode_mean_signal.png`；`plt.close(fig)`；返回路径

---

### `plot_sync_pulse_interval`

**图表描述**：散点图，横轴为脉冲编号，纵轴为相邻 sync 脉冲间隔（秒），添加期望间隔（中位数）水平参考线。

**步骤**：
1. matplotlib 可用性检查
2. 计算 `intervals = np.diff(ap_sync_times)`；若 `len(intervals) == 0`：return None
3. `expected_interval = np.median(intervals)`（不硬编码 1.0）
4. `ax.scatter(range(len(intervals)), intervals, s=3, alpha=0.7)`
5. 添加水平线，标注期望间隔；保存为 `sync_pulse_interval.png`；`plt.close(fig)`；返回路径

---

## 5. 公开 API 与可配参数

```python
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd
    import spikeinterface.core as si

    from pynpxpipe.io.sync.imec_nidq_align import SyncResult
    from pynpxpipe.io.sync.photodiode_calibrate import CalibratedOnsets


def generate_all_plots(
    probe_id: str,
    ap_sync_times: np.ndarray,
    nidq_sync_times: np.ndarray,
    sync_result: SyncResult,
    trial_events_df: pd.DataFrame,
    calibrated_onsets: CalibratedOnsets,
    nidq_recording: si.BaseRecording,
    config,
    output_dir: Path,
) -> list[Path]:
    """Generate all 6 synchronization diagnostic PNG figures.

    If matplotlib is not installed, logs a warning and returns an empty list
    without raising. Each individual plot function is called in a try/except
    to prevent a single plot failure from blocking the rest.

    Args:
        probe_id: Probe identifier string, e.g. "imec0". Used in file names.
        ap_sync_times: 1D float64 array of AP sync pulse times (seconds).
        nidq_sync_times: 1D float64 array of NIDQ sync pulse times (seconds).
        sync_result: IMEC↔NIDQ linear alignment result from imec_nidq_align.
        trial_events_df: DataFrame with trial alignment table from bhv_nidq_align.
        calibrated_onsets: Photodiode calibration result from photodiode_calibrate.
        nidq_recording: Lazy NIDQ SpikeInterface Recording (not fully loaded).
        config: Pipeline config object; uses config.sync.photodiode_channel_index,
            config.sync.pd_window_pre_ms, config.sync.pd_window_post_ms.
        output_dir: Session output root directory. Figures saved to
            {output_dir}/04_sync/figures/.

    Returns:
        List of Path objects for successfully saved PNG files. Empty list if
        matplotlib is unavailable or all plots failed.
    """


def plot_sync_drift(
    probe_id: str,
    ap_sync_times: np.ndarray,
    nidq_sync_times: np.ndarray,
    sync_result: SyncResult,
    output_dir: Path,
) -> Path | None:
    """Scatter plot of IMEC vs NIDQ sync pulse times with linear fit overlay.

    Saves sync_drift_{probe_id}.png to {output_dir}/04_sync/figures/.

    Returns:
        Path to saved PNG, or None if matplotlib is unavailable.
    """


def plot_event_alignment(
    trial_events_df: pd.DataFrame,
    output_dir: Path,
) -> Path | None:
    """Scatter plot of trial_id vs onset_nidq_s for alignment quality check.

    Saves event_alignment.png to {output_dir}/04_sync/figures/.

    Returns:
        Path to saved PNG, or None if matplotlib is unavailable.
    """


def plot_photodiode_heatmap(
    nidq_recording: si.BaseRecording,
    trial_events_df: pd.DataFrame,
    config,
    output_dir: Path,
) -> Path | None:
    """Heatmap of per-trial photodiode z-score signals (trials × time).

    Saves photodiode_heatmap.png to {output_dir}/04_sync/figures/.
    Extracts photodiode signal from nidq_recording in per-trial chunks
    (does not load the full analog channel into memory).

    Returns:
        Path to saved PNG, or None if matplotlib is unavailable.
    """


def plot_onset_latency_histogram(
    calibrated_onsets: CalibratedOnsets,
    output_dir: Path,
) -> Path | None:
    """Histogram of per-trial photodiode onset latencies for good trials.

    Saves onset_latency_histogram.png to {output_dir}/04_sync/figures/.
    Only includes trials where quality_flag == 0.

    Returns:
        Path to saved PNG, or None if matplotlib is unavailable or no good trials.
    """


def plot_photodiode_mean_signal(
    nidq_recording: si.BaseRecording,
    trial_events_df: pd.DataFrame,
    calibrated_onsets: CalibratedOnsets,
    config,
    output_dir: Path,
) -> Path | None:
    """Mean photodiode signal before vs after calibration alignment.

    Saves photodiode_mean_signal.png to {output_dir}/04_sync/figures/.

    Returns:
        Path to saved PNG, or None if matplotlib is unavailable.
    """


def plot_sync_pulse_interval(
    probe_id: str,
    ap_sync_times: np.ndarray,
    output_dir: Path,
) -> Path | None:
    """Scatter plot of consecutive AP sync pulse intervals.

    Saves sync_pulse_interval.png to {output_dir}/04_sync/figures/.
    Useful for detecting clock instability or missed sync pulses.

    Returns:
        Path to saved PNG, or None if matplotlib is unavailable or
        fewer than 2 sync pulses.
    """
```

### 可配参数

| 参数 | 来源 | 说明 |
|---|---|---|
| `config.sync.photodiode_channel_index` | pipeline.yaml | NIDQ 模拟通道中 photodiode 的通道索引，**禁止硬编码** |
| `config.sync.pd_window_pre_ms` | pipeline.yaml | 基线窗口时长（ms），默认 `10.0` |
| `config.sync.pd_window_post_ms` | pipeline.yaml | 检测窗口时长（ms），默认 `100.0` |

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_io/test_sync_plots.py`

测试策略：使用 `unittest.mock.patch` 和 `pytest.importorskip("matplotlib")` 组合。对于需要真实图像内容的测试，使用 `matplotlib.use("Agg")` 后端（不显示窗口）。

### matplotlib 缺失的静默降级

| 测试名 | 测试方式 | 预期行为 |
|---|---|---|
| `test_generate_all_plots_no_matplotlib` | mock `builtins.__import__` 使 matplotlib ImportError | 返回空列表，不 raise |
| `test_plot_sync_drift_no_matplotlib` | 同上 | 返回 `None`，不 raise |
| `test_plot_event_alignment_no_matplotlib` | 同上 | 返回 `None`，不 raise |
| `test_plot_onset_latency_histogram_no_matplotlib` | 同上 | 返回 `None`，不 raise |
| `test_plot_sync_pulse_interval_no_matplotlib` | 同上 | 返回 `None`，不 raise |

### 输出路径

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_sync_drift_saves_to_correct_path` | 合法 sync 数据，`output_dir=tmp_path` | 文件存在于 `tmp_path/sync/figures/sync_drift_imec0.png` |
| `test_event_alignment_saves_to_correct_path` | 合法 trial_events_df | 文件存在于 `tmp_path/sync/figures/event_alignment.png` |
| `test_photodiode_heatmap_saves_to_correct_path` | mock nidq_recording | 文件存在于 `tmp_path/sync/figures/photodiode_heatmap.png` |
| `test_onset_latency_histogram_saves_to_correct_path` | calibrated_onsets 有 good trial | 文件存在于 `tmp_path/sync/figures/onset_latency_histogram.png` |
| `test_photodiode_mean_signal_saves_to_correct_path` | mock nidq_recording + calibrated_onsets | 文件存在于 `tmp_path/sync/figures/photodiode_mean_signal.png` |
| `test_sync_pulse_interval_saves_to_correct_path` | ap_sync_times 有 10 个脉冲 | 文件存在于 `tmp_path/sync/figures/sync_pulse_interval_{probe_id}.png` |

### 目录自动创建

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_figures_dir_created_if_not_exists` | `output_dir` 指向不存在的目录 | 调用后 `output_dir/sync/figures/` 目录存在 |

### `generate_all_plots` 容错

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_generate_all_plots_returns_path_list` | 所有子函数正常 | 返回包含 6 个 Path 的列表 |
| `test_generate_all_plots_partial_failure` | 某一子函数 raise RuntimeError | 不 raise，返回已成功保存的路径（< 6 个），并记录 warning |
| `test_generate_all_plots_calls_all_six` | mock 六个子函数 | 每个子函数恰好被调用一次 |

### 图表内容（使用 Agg 后端）

| 测试名 | 验证内容 |
|---|---|
| `test_sync_drift_file_is_valid_png` | 保存的文件能被 PIL/matplotlib 重新打开（格式合法） |
| `test_onset_latency_histogram_no_good_trials_returns_none` | `quality_flags` 全非零 → `plot_onset_latency_histogram` 返回 None，不保存文件 |
| `test_sync_pulse_interval_single_pulse_returns_none` | `ap_sync_times` 只有 1 个点 → 返回 None |
| `test_probe_id_in_sync_drift_filename` | `probe_id="imec1"` | 文件名为 `sync_drift_imec1.png` |

### `plot_sync_pulse_interval` 数值

| 测试名 | 验证内容 |
|---|---|
| `test_interval_median_as_expected` | 5 个等间距脉冲，间隔 = 1.0s → median ≈ 1.0（标注正确） |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `matplotlib` | **可选** | 图表生成；`ImportError` 时所有函数静默返回 `None` |
| `matplotlib.pyplot` | 可选（随 matplotlib） | 创建 Figure/Axes，保存 PNG |
| `numpy` | 必选 | 数组运算（`np.diff`，`np.median`，`np.arange`） |
| `scipy.signal.resample_poly` | 必选（间接） | photodiode heatmap/mean_signal 内部重采样逻辑 |
| `pandas` | 必选 | `trial_events_df` DataFrame 读取 |
| `pathlib.Path` | 标准库 | 文件路径操作，`mkdir` |
| `pynpxpipe.io.sync.imec_nidq_align.SyncResult` | 项目内部 | `plot_sync_drift` 参数类型（TYPE_CHECKING） |
| `pynpxpipe.io.sync.photodiode_calibrate.CalibratedOnsets` | 项目内部 | `plot_onset_latency_histogram`、`plot_photodiode_mean_signal` 参数类型（TYPE_CHECKING） |
| `spikeinterface.core.BaseRecording` | 项目内部 | TYPE_CHECKING 中引用，运行时不 import |

stages 层（`synchronize.py`）不直接 import matplotlib，仅 import `generate_all_plots`。

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #12（诊断图 + META 输出） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #12 段落 |

### MATLAB 诊断图布局

MATLAB 在 `Load_Data_function.m` 中绘制 14 个子图（3×6 grid），内容散布在 step #6-#10 的代码中，最终在 step #12 一并保存为 `.fig` + `.png`。

| MATLAB subplot | 对应 Python 函数 | 说明 |
|----------------|-----------------|------|
| (3,6,1) | `plot_event_alignment` | ML vs SGLX onset scatter（MaxErr） |
| (3,6,2-5) | `plot_photodiode_heatmap` | Raw/diff/abs-diff/polarity-corrected heatmaps |
| (3,6,7-8) | `plot_photodiode_mean_signal` | Pre/post-calibration mean ± std |
| (3,6,10) | `plot_onset_latency_histogram` | Latency 直方图 + min/max 标线 |
| (3,6,12) | N/A | Eye density heatmap（Python 在 postprocess 阶段处理） |
| (3,6,13-15) | `plot_sync_drift` + `plot_sync_pulse_interval` | IMEC/NI intervals + clock drift |

### 有意偏离

| 偏离 | 理由 |
|------|------|
| 6 张独立 PNG 替代 1 张 14-subplot figure | 独立图表更易于自动化审阅和选择性查看 |
| matplotlib 为可选依赖 | CI 环境和纯计算节点可能无 matplotlib；诊断图不影响数据流 |
| 眼动密度图不在 sync_plots 中 | 眼动验证在 postprocess 阶段执行，诊断图随之生成 |
| 不保存 .fig 格式 | MATLAB 专有格式；Python 用 PNG（静态）即可满足诊断需求 |
