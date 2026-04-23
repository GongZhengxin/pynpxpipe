# Plots — Nature-style diagnostic figure package

## 目标

将 pipeline 运行期产出的中间结果以 Nature 期刊排版规范的 PNG 图导出到
`{output_dir}/<stage>/figures/`，供 `ui/components/figs_viewer.py` 浏览，
并作为 session 交付物保留。覆盖 MATLAB 参考实现 `step3_output_analysis.md`
第二部分的 16 张中间图，外加 Bombcell 单元分类波形图与 Postprocess 单元摘要图。

**定位**：横切工具包，与 `io/`、`stages/` 平级；各 stage 在 `run()` 末尾调用
`pynpxpipe.plots.<stage>.emit_all(...)` 钩子写图；不引入 stage 依赖。

## 非目标

- 不做矢量 PDF 输出。只产 PNG。
- 不做交互式 bokeh/panel 图（V1）。`figs_viewer` 扫 PNG 已够用；交互式留 V2。
- 不做像素级回归对比。测试仅验证文件生成、DPI、尺寸、title、数据轴范围
  与受限配色。
- 不替换 Bombcell 库内部绘图。Bombcell 自带的单元分类图沿用其输出文件；
  我们仅补充 `plot_unit_waveforms_by_type`（按 unittype 汇总波形）。

## 目录结构

```
src/pynpxpipe/plots/
  __init__.py        # 导入即 apply_nature_style()；导出 savefig/palette
  style.py           # Nature 风格 rcParams、Okabe-Ito 调色板、figure_size
  sync.py            # MATLAB #1-#13 (sync 间隔 + photodiode 系列)
  postprocess.py     # 单元波形汇总、raster、PSTH、MATLAB #15 stim coverage
  curate.py          # quality-metric 分布、Bombcell 单元分类波形
  preprocess.py      # 坏道热图、CMR 前后 traces、运动校正位移曲线（P1）
```

每个子模块暴露单一公开入口 `emit_all(..., output_dir: Path) -> list[Path]`，
返回已生成 PNG 路径列表。各子模块允许内部私有 `_plot_xxx(ax, ...)` 函数，
但 stage 集成只调 `emit_all`。

## Nature 风格规范（字号按用户确认）

| 项 | 值 |
|----|---|
| 字体族 | Arial → DejaVu Sans 回退 |
| `axes.titlesize` | **12 pt bold** |
| `axes.labelsize` | **11 pt** |
| `xtick.labelsize` / `ytick.labelsize` | **10 pt** |
| `legend.fontsize` | 10 pt |
| `figure.titlesize` | 12 pt bold（sgtitle 用） |
| Spine | 关闭 top + right；left/bottom 线宽 0.8 pt |
| 主线线宽 | 1.0 pt |
| Grid | 默认关闭 |
| 背景 | figure & axes 均白 |
| DPI（保存） | 300 |
| bbox | `tight`，pad=0.05 in |
| 单栏宽 | 89 mm（3.5 in） |
| 双栏宽 | 183 mm（7.2 in） |

### 调色板（Okabe-Ito 8 色色盲友好）

```
BLACK     = "#000000"
ORANGE    = "#E69F00"
SKY       = "#56B4E9"
GREEN     = "#009E73"
YELLOW    = "#F0E442"
BLUE      = "#0072B2"
VERMILION = "#D55E00"
PURPLE    = "#CC79A7"
```

分类语义锁定：
- **SUA** = GREEN
- **MUA** = ORANGE
- **NON-SOMA** = PURPLE
- **NOISE** = `#888888`（灰）
- is_visual=True = BLUE；False = BLACK

## 公共 API（`plots.style`）

```python
def apply_nature_style() -> None: ...
def figure_size(cols: int = 1, height_ratio: float = 0.75) -> tuple[float, float]:
    """Return (width_in, height_in). cols ∈ {1,2}. height_ratio multiplies width."""
def savefig(fig, path: Path, *, title: str | None = None, dpi: int = 300) -> Path:
    """Set suptitle if given; tight_layout; write PNG; return path."""

PALETTE: dict[str, str]          # name → hex
UNITTYPE_COLORS: dict[str, str]  # "SUA"/"MUA"/"NON-SOMA"/"NOISE" → hex
```

`plots/__init__.py` 导入时即调用 `apply_nature_style()`；个别测试若需重置，
可手动 `plt.rcdefaults()`。

## 图表目录（覆盖 MATLAB 16 张 + 扩展）

### plots/sync.py — 由 `SynchronizeStage` 末尾触发
输入：`sync_results`, `ap_sync_times_map`, `nidq_sync_times`, `trial_alignment`,
`calibrated`（CalibratedOnsets），`pd_signal`（可选），`nidq_sample_rate`。
输出目录：`{output_dir}/04_sync/figures/`。

| 函数 | 覆盖 MATLAB# | 产出文件 |
|------|--------------|----------|
| `plot_sync_intervals` | #1, #2 | `sync_intervals_imec.png`, `sync_intervals_nidq.png`（按 probe） |
| `plot_sync_residuals` | #3 | `sync_residuals_{probe_id}.png` |
| `plot_trial_onset_consistency` | #4 | `trial_onset_consistency.png` |
| `plot_eye_density` | #5 | `eye_density.png` |
| `plot_photodiode_raw_stack` | #6-#9 | `photodiode_raw.png`, `photodiode_diff.png`, `photodiode_diff_abs.png`, `photodiode_polarity_corrected.png` |
| `plot_photodiode_calibration` | #10, #12, #13 | `photodiode_before_calibration.png`, `photodiode_after_calibration.png`, `photodiode_valid_only.png` |
| `plot_onset_latency_hist` | #11 | `onset_latency_hist.png` |

### plots/curate.py — 由 `CurateStage` 每 probe 末尾触发
输入：`analyzer`（已 compute templates + waveforms）、`qm` DataFrame、
`unittype_map: dict[uid, str]`、`probe_id`。
输出目录：`{output_dir}/05_05_curated/{probe_id}/figures/`。

| 函数 | 覆盖 | 产出文件 |
|------|------|----------|
| `plot_quality_metrics_dist` | 新 | `quality_metrics_dist.png`（4 subplot：isi/amp/pr/snr） |
| `plot_unittype_pie` | 扩展 #16 | `unittype_pie.png` |
| `plot_unit_waveforms_by_type` | 扩展 #16 | `waveforms_by_unittype.png`（4 subplot，每 unittype 最多 50 根波形 + 均值） |

### plots/postprocess.py — 由 `PostprocessStage` 每 probe 末尾触发
输入：`analyzer`（含 templates + unit_locations）、`unit_scores`（含 slay + is_visual）、
`behavior_events_df`、`probe_id`、可选 raster h5 路径。
输出目录：`{output_dir}/06_06_postprocessed/{probe_id}/figures/`。

| 函数 | 覆盖 MATLAB# | 产出文件 |
|------|--------------|----------|
| `plot_unit_location_scatter` | 新 | `unit_locations.png`（x vs y，点色=is_visual） |
| `plot_slay_distribution` | 新 | `slay_distribution.png` |
| `plot_stim_coverage` | #15 | `stim_coverage.png` |
| `plot_psth_top_units` | 新 | `psth_top_units.png`（按 SLAY 排序取前 9 个 unit） |
| `plot_raster_top_units` | 新 | `raster_top_units.png` |

### plots/preprocess.py（P1）— 由 `PreprocessStage` 每 probe 末尾触发
输出目录：`{output_dir}/01_01_preprocessed/{probe_id}/figures/`。

| 函数 | 产出文件 |
|------|----------|
| `plot_bad_channels` | `bad_channels.png` |
| `plot_traces_before_after` | `traces_cmr_beforeafter.png` |
| `plot_motion_displacement`（可选） | `motion_displacement.png` |

## 集成契约

每个 stage 在 `run()` 的**写 checkpoint 之前**调用：

```python
try:
    from pynpxpipe.plots.<stage> import emit_all
    emit_all(..., output_dir=figures_dir)
except ImportError:
    pass  # matplotlib 未安装，静默跳过
except Exception as exc:
    self.logger.warning("figure generation failed: %s", exc)  # 绘图失败不阻塞主流程
```

**设计原则**：绘图失败**绝不**抛 stage 级异常；仅 warning 日志。Stage 主路径
（数据写盘 + checkpoint）不受绘图影响。

## 测试策略

- `tests/test_plots/test_style.py` — rcParams 验证、palette 完整性、figure_size
  数值、savefig 落盘 + DPI 验证。
- `tests/test_plots/test_sync.py` / `test_postprocess.py` / `test_curate.py` /
  `test_preprocess.py` — 各自构造 mock 数据调用 `emit_all`，断言：
  - 返回路径列表非空
  - 每个 PNG 文件存在 + 非空 + 可被 PIL 打开
  - matplotlib backend 切到 `Agg`（tests 会话 fixture）
- stage 集成测试：`tests/test_stages/test_<stage>.py` 增加 1 条 test：
  `emit_all` 被调用一次 + 绘图异常被 swallow 不抛。

## UI 交互

`ui/components/figs_viewer.py` 现有递归 `glob("**/*.png")` 已能自动发现。
S3 (Agent 4) 可选增强：按 `.parent.name` 分组（sync/curated/postprocessed/
preprocessed）做 accordion 折叠显示；metadata（ctime + 文件大小）悬浮显示。

## 依赖

- `matplotlib>=3.7` 已在 `[plots]` optional extras 中；**不加入 core deps**。
- `plots/` 子包的**每个文件顶部**用 `try/except ImportError` 守护 matplotlib
  导入，使得 core 环境（无 plots extras）仍可 import `pynpxpipe` 不报错。

## 执行顺序（本次 session）

1. Phase A（主 agent）：写本 spec + `plots/__init__.py` + `plots/style.py`
   + `tests/test_plots/test_style.py`。
2. Phase B（4 subagent 并行）：sync / curate / postprocess / preprocess+UI
   各自独立实现（disjoint file 集合，不会冲突）。
3. Phase C（主 agent）：全量 `uv run pytest` + `ruff check/format` +
   更新 `docs/progress.md` + 写新行 `plots` 模块记录。
