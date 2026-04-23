# Spec: io/derivatives.py & ExportStage Phase 2.5

## 1. 目标

给下游分析代码提供 **session 级**派生文件，内容完全可以从 NWB 文件重算，但以
小型独立文件的形式预先导出（落盘在 `{output_dir}/07_derivatives/`，接替被
删除的旧 `07_export/` 目录），便于：

- 批量脚本无需打开 NWB 即可读取 spike raster
- 跨机器分发（不用传输几百 GB 的 NWB 原始数据段）
- 与用户已有的 analysis 脚本 (`spike_times_to_raster` / `raster_to_psth`) 对接

三个输出：

| 文件 | 结构 | 来源 |
|---|---|---|
| `TrialRaster_{session_id}.h5` | (n_units, n_trials, n_timebins) uint8 | NWB `units.spike_times` + `trials.start_time` |
| `UnitProp_{session_id}.csv` | 每行一个 unit，3 列 | NWB `units.to_dataframe()` |
| `TrialRecord_{session_id}.csv` | 每行一个 trial onset | NWB `trials.to_dataframe()` |

插入位置：**ExportStage Phase 2.5**，即 Phase 2 核心 NWB 写完后、Phase 3 原始
数据压缩之前。同步阻塞执行（相对 Phase 3 的背景线程而言）。

---

## 2. 输入

### `io/derivatives.py` 模块级函数

- `spike_times_to_raster(unit_df, trial_df, pre_onset, post_onset, bin_size=1, n_jobs=1) -> np.ndarray`
- `save_raster_h5(filepath, raster, metadata=None, compression="gzip", compression_opts=4, use_sparse=True, sparsity_threshold=0.5) -> dict`
- `export_unit_prop(units_df, out_path) -> Path`
- `export_trial_record(trials_df, out_path) -> Path`
- `resolve_post_onset_ms(bhv_parser) -> float`

### Phase 2.5 依赖的 session 字段

| 字段 | 说明 |
|---|---|
| `session.output_dir` | 输出根目录 |
| `session.session_id.canonical()` | 文件命名用 session 标识 |
| `session.bhv_file` | 读 `VariableChanges.onset_time / offset_time` |
| `session.config.export.derivatives` | 配置（见 §4） |

### 外部数据依赖

| 文件 | 说明 |
|---|---|
| `{output_dir}/{session_id}.nwb` | Phase 2 刚写完的 NWB 文件，重开 `"r"` 模式读取 |

---

## 3. 输出

| 文件 | 路径 |
|---|---|
| Raster H5 | `{output_dir}/07_derivatives/TrialRaster_{session_id}.h5` |
| UnitProp CSV | `{output_dir}/07_derivatives/UnitProp_{session_id}.csv` |
| TrialRecord CSV | `{output_dir}/07_derivatives/TrialRecord_{session_id}.csv` |

**目录编号约定**：`07_derivatives/` 严格替换旧 `07_export/`；实现时必须删除旧路径所有代码，不保留兼容层。

其中 `{session_id}` = `session.session_id.canonical()`（例：`251024_FanFan_nsd1w_MSB-V4`）。

### `TrialRaster_*.h5` 结构

```
/ (root)
├── attrs:
│   ├── storage_format: "sparse" | "dense"
│   ├── original_shape: (n_units, n_trials, n_timebins)
│   ├── sparsity: float
│   └── dtype: "uint8"
├── /data, /row, /col  (when sparse, from scipy.sparse.coo_matrix)
│   OR /raster         (when dense)
└── /metadata (group)
    ├── attrs:
    │   ├── pre_onset_ms: float
    │   ├── post_onset_ms: float
    │   ├── bin_size_ms: float
    │   └── session_id: str
```

稀疏阈值 0.5：零元素比例 ≥ 0.5 时走稀疏（COO）格式，显著减小体积（典型神经
raster 稀疏度在 0.9+）。

### `UnitProp_*.csv` 列

5 列投影（与 MATLAB 参考 pipeline 列布局对齐；内部调试列留在 NWB `units` 表内）：

| 列 | 类型 | 来源 |
|---|---|---|
| `id` | int | row index（0-based, 非 NWB unit_id） |
| `ks_id` | int | NWB `units.ks_id`（Kilosort cluster id） |
| `unitpos` | list\[float\] shape (2,) | NWB `units.unit_location[:, [0, 1]]` — 探针平面 x + depth (μm)。3D → 2D 仅 CSV 投影，NWB 保留完整 3D |
| `unittype` | int | 由 `unittype_string` 推导的枚举（见下表） |
| `unittype_string` | str | NWB `units.unittype_string`（"SUA"/"MUA"/"NON-SOMA"/"NOISE"/未知） |

**`unittype` 枚举**（与 MATLAB 参考 pipeline 一致）：

| `unittype_string` | `unittype` |
|---|---|
| `"SUA"` 或 `"GOOD"` | 1 |
| `"MUA"` | 2 |
| `"NON-SOMA"` 或 `"NOISE"` | 3 |
| 其他（空、未知） | 0 |

**序列化**：`unitpos` 写入 CSV 时，先把每行的 numpy array `[x, y]` 转成 Python `list`，pandas
会渲染为 `"[x, y]"`。下游读回用 `ast.literal_eval(cell)` 即可。

**丢弃列**：`spike_times` / `waveform_mean` / 其它 SortingAnalyzer 扩展列 **不进 CSV**（体积 + 下游不需要），
仍保留在 NWB `units` 表内。

### `TrialRecord_*.csv` 列

6 列投影（与 MATLAB 参考 pipeline 列布局对齐；内部同步/诊断列留在 NWB `trials` 表内）：

| 列 | 类型 | 来源 |
|---|---|---|
| `id` | int | row index（0-based, 非 NWB trial_id） |
| `start_time` | float | NWB `trials.start_time`（秒，trial onset） |
| `stop_time` | float | NWB `trials.stop_time`（秒，trial 结束） |
| `stim_index` | int | NWB `trials.stim_index` |
| `stim_name` | str | NWB `trials.stim_name` |
| `fix_success` | bool/int | NWB `trials.trial_valid` 语义重命名（见 `docs/ground_truth/step5_matlab_vs_python.md:335`，`trial_valid` ≡ `fix_success`） |

**丢弃列**：`stim_onset_nidq_s_diag` / `onset_time_ms` / `offset_time_ms` / `stim_onset_imec_*` /
`photodiode_onset_s` / `trial_id` / `condition_id` / `onset_nidq_s` / `stim_onset_nidq_s` 等内部同步与
诊断列 **不进 CSV**，仍保留在 NWB `trials` 表内供深度分析。

---

## 4. 配置

`pipeline.yaml` 新增 section：

```yaml
export:
  derivatives:
    enabled: true           # 默认启用
    pre_onset_ms: 50        # raster 窗口左侧（ms）
    post_onset_ms: auto     # "auto" or number
    bin_size_ms: 1
    n_jobs: 1
```

对应 `config.py`：

```python
@dataclass
class DerivativesConfig:
    enabled: bool = True
    pre_onset_ms: float = 50.0
    post_onset_ms: float | str = "auto"   # 数字或 "auto"
    bin_size_ms: float = 1.0
    n_jobs: int = 1


@dataclass
class ExportConfig:
    derivatives: DerivativesConfig = field(default_factory=DerivativesConfig)


# 在 PipelineConfig:
export: ExportConfig = field(default_factory=ExportConfig)
```

`"auto"` 语义：`resolve_post_onset_ms(bhv_parser)` 读取所有 trial 的
`variable_changes['onset_time']` 和 `variable_changes['offset_time']`，取
`max(onset_time + offset_time)`。所有 trial 都缺字段时，fallback 为 800.0 并记 WARNING。

---

## 5. 处理步骤

### `io/derivatives.py`

#### `spike_times_to_raster(unit_df, trial_df, pre_onset, post_onset, bin_size=1, n_jobs=1) -> np.ndarray`

- 原 `F:\#Datasets\TripleN10k\io\analysis_codes\utils.py` 的实现移植
- 去除 `memmap` 分支（简化；神经 raster 在 session 级通常 < 2GB）
- 保留 `n_jobs > 1` 的 joblib 并行分支（joblib 已是 spikeinterface 依赖）
- `start_col` 固定 `"start_time"`（NWB 标准），不再暴露参数
- `spike_col` 固定 `"spike_times"`
- `stop_col` 参数删除（不使用）
- 窗口含义：`[-pre_onset, +post_onset]` ms 相对 `trial_df.start_time`
- `n_timebins = int(ceil((pre_onset + post_onset) / bin_size))`
- 返回 `np.ndarray` shape `(n_units, n_trials, n_timebins)` dtype `np.uint8`
- 单元格 clip 到 255（uint8 上限）

#### `save_raster_h5(filepath, raster, metadata=None, ...) -> dict`

- 原 `io.py` 的实现移植（去重：原文件同一函数定义两次，只留一份）
- 稀疏度 ≥ 0.5 自动走 scipy `coo_matrix` 稀疏格式
- 文件不以 `.h5`/`.hdf5` 结尾时自动加 `.h5`
- 返回统计字典 `{filepath, storage_format, original_size_mb, file_size_mb, compression_ratio, sparsity, shape}`

#### `export_unit_prop(units_df, out_path) -> Path`

投影为 5 列：`id, ks_id, unitpos, unittype, unittype_string`。`unitpos` = `unit_location[:, [0, 1]]`，
`unittype` = `unittype_string` 的枚举映射（SUA/GOOD → 1, MUA → 2, NON-SOMA/NOISE → 3, 其他 → 0）。
源列保证由上游 ExportStage Phase 2 NWB 写入（units 表契约），不做 missing-column defensive fallback。

#### `export_trial_record(trials_df, out_path) -> Path`

投影为 6 列：`id, start_time, stop_time, stim_index, stim_name, fix_success`。
`fix_success` ← `trial_valid`（语义等价重命名，见 `docs/ground_truth/step5_matlab_vs_python.md:335`）。
源列保证由上游 ExportStage Phase 2 NWB 写入（trials 表契约），不做 missing-column defensive fallback。

#### `resolve_post_onset_ms(bhv_parser) -> float`

```python
def resolve_post_onset_ms(bhv_parser: BHV2Parser) -> float:
    """Compute max(onset_time + offset_time) across all trials' VariableChanges.

    Fallback 800.0 if parsing fails or no trial supplies both fields.
    """
    try:
        trials = bhv_parser.parse()
    except Exception:
        return 800.0
    values: list[float] = []
    for t in trials:
        vc = t.variable_changes or {}
        if "onset_time" in vc and "offset_time" in vc:
            values.append(float(vc["onset_time"]) + float(vc["offset_time"]))
    if not values:
        return 800.0
    return max(values)
```

### `ExportStage._export_phase2` 重写（**替换现有内容**）

旧 Phase 2 写 `export/trials.csv|units.csv|raster_{probe_id}.h5`。**删除**这部分
代码，替换为：

```python
def _export_phase2(self, nwb_path_written: Path, behavior_events: pd.DataFrame) -> None:
    """Phase 2.5: export session-level derivative files (TrialRaster/UnitProp/TrialRecord).

    Reads the just-written NWB file (units + trials), computes a combined
    spike raster, and writes three files under ``{output_dir}/derivatives/``.
    """
    from pynpxpipe.io.bhv import BHV2Parser
    from pynpxpipe.io.derivatives import (
        export_trial_record,
        export_unit_prop,
        resolve_post_onset_ms,
        save_raster_h5,
        spike_times_to_raster,
    )

    # Config access — falls back to defaults when session.config is not wired.
    cfg = getattr(getattr(self.session, "config", None), "export", None)
    dcfg = getattr(cfg, "derivatives", None)
    if dcfg is not None and not dcfg.enabled:
        self.logger.info("Phase 2.5 (derivatives) disabled by config; skipping")
        return

    pre_onset_ms = float(getattr(dcfg, "pre_onset_ms", 50.0))
    post_onset_raw = getattr(dcfg, "post_onset_ms", "auto")
    bin_size_ms = float(getattr(dcfg, "bin_size_ms", 1.0))
    n_jobs = int(getattr(dcfg, "n_jobs", 1))

    session_id = self.session.session_id.canonical()
    derivatives_dir = self.session.output_dir / "07_derivatives"
    derivatives_dir.mkdir(parents=True, exist_ok=True)

    # Open the NWB we just wrote and extract dataframes.
    with pynwb.NWBHDF5IO(str(nwb_path_written), "r") as io:
        nwbfile = io.read()
        trials_df = nwbfile.trials.to_dataframe() if nwbfile.trials is not None else pd.DataFrame()
        units_df = nwbfile.units.to_dataframe() if nwbfile.units is not None else pd.DataFrame()

    if post_onset_raw == "auto":
        try:
            post_onset_ms = resolve_post_onset_ms(BHV2Parser(self.session.bhv_file))
        except Exception as exc:
            self.logger.warning("resolve_post_onset_ms failed, using 800.0: %s", exc)
            post_onset_ms = 800.0
    else:
        post_onset_ms = float(post_onset_raw)

    # CSV exports (cheap, always first)
    export_trial_record(trials_df, derivatives_dir / f"TrialRecord_{session_id}.csv")
    export_unit_prop(units_df, derivatives_dir / f"UnitProp_{session_id}.csv")

    # Raster (expensive): need spike_times + start_time columns.
    if len(units_df) and len(trials_df) and "spike_times" in units_df.columns:
        raster = spike_times_to_raster(
            units_df, trials_df,
            pre_onset=pre_onset_ms,
            post_onset=post_onset_ms,
            bin_size=bin_size_ms,
            n_jobs=n_jobs,
        )
        save_raster_h5(
            str(derivatives_dir / f"TrialRaster_{session_id}.h5"),
            raster,
            metadata={
                "pre_onset_ms": pre_onset_ms,
                "post_onset_ms": post_onset_ms,
                "bin_size_ms": bin_size_ms,
                "session_id": session_id,
            },
        )
    else:
        self.logger.warning(
            "Skipping TrialRaster export (units=%d, trials=%d, spike_times_col=%s)",
            len(units_df), len(trials_df), "spike_times" in units_df.columns,
        )
```

`run()` 调用位置从：
```python
self._export_phase2(behavior_events, n_units_total)
```
改为：
```python
self._export_phase2(nwb_path_written, behavior_events)
```

---

## 6. 公开 API

```python
# src/pynpxpipe/io/derivatives.py
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from pynpxpipe.io.bhv import BHV2Parser


def spike_times_to_raster(
    unit_df: pd.DataFrame,
    trial_df: pd.DataFrame,
    pre_onset: float,
    post_onset: float,
    bin_size: float = 1.0,
    n_jobs: int = 1,
    verbose: bool = False,
) -> np.ndarray: ...


def save_raster_h5(
    filepath: str,
    raster: np.ndarray,
    metadata: dict[str, Any] | None = None,
    compression: str = "gzip",
    compression_opts: int = 4,
    use_sparse: bool = True,
    sparsity_threshold: float = 0.5,
) -> dict[str, Any]: ...


def export_unit_prop(units_df: pd.DataFrame, out_path: Path) -> Path: ...


def export_trial_record(trials_df: pd.DataFrame, out_path: Path) -> Path: ...


def resolve_post_onset_ms(bhv_parser: BHV2Parser) -> float: ...
```

---

## 7. 测试范围（TDD）

测试文件：`tests/test_io/test_derivatives.py`

### `spike_times_to_raster`

| 测试名 | 输入 | 预期 |
|---|---|---|
| `test_raster_shape` | 2 units × 3 trials, pre=50, post=300, bin=1 | shape `(2, 3, 350)` |
| `test_raster_dtype_uint8` | 同上 | `dtype == np.uint8` |
| `test_raster_empty_spikes` | 某 unit 无 spike | 该 unit raster 全 0 |
| `test_raster_spike_inside_window` | 单 spike 在 onset+100ms，bin=1, pre=50 | raster\[unit, trial, 150\] == 1 |
| `test_raster_spike_outside_window` | 单 spike 在 onset+500ms，post=300 | raster 全 0 |
| `test_raster_saturation_uint8` | 1 unit 300 个 spike 挤在 1 个 bin | 该 bin 值 = 255（clip） |
| `test_raster_bin_size_10ms` | bin=10, pre=50, post=50 | n_timebins = 10 |

### `save_raster_h5`

| 测试名 | 输入 | 预期 |
|---|---|---|
| `test_save_appends_h5_extension` | filepath 无扩展名 | 实际文件带 `.h5` |
| `test_save_dense_when_low_sparsity` | raster 全 1（sparsity=0） | attrs\['storage_format'\]=="dense"，有 `raster` 数据集 |
| `test_save_sparse_when_high_sparsity` | raster 几乎全 0（sparsity>0.5） | attrs\['storage_format'\]=="sparse"，有 `data/row/col` |
| `test_save_metadata_written` | metadata={"pre_onset_ms": 50} | `/metadata` 组 attrs 里有 pre_onset_ms=50 |
| `test_save_returns_stats_dict` | — | 返回值含 filepath/storage_format/shape 等 key |

### `export_unit_prop` / `export_trial_record`

| 测试名 | 输入 | 预期 |
|---|---|---|
| `test_unit_prop_columns` | units_df 含所有源列（ks_id/unit_location 3D/unittype_string 等） | CSV 5 列顺序：`id, ks_id, unitpos, unittype, unittype_string` |
| `test_unit_prop_unitpos_is_2d` | 任一 row 的 unitpos | 恰好 2 个数值元素 |
| `test_unit_prop_id_is_row_index` | N 行 units_df | `id` 列 == `list(range(N))` |
| `test_unit_prop_unittype_enum` | unittype_string=SUA/MUA/NON-SOMA/unknown | unittype = 1/2/3/0 |
| `test_trial_record_projects_six_columns` | trials_df 含 start/stop/stim_index/stim_name/trial_valid + 内部列 | CSV 6 列顺序：`id, start_time, stop_time, stim_index, stim_name, fix_success`；`fix_success` 值 == 源 `trial_valid` |
| `test_trial_record_id_is_row_index` | N 行 trials_df | `id` 列 == `list(range(N))` |

### `resolve_post_onset_ms`

| 测试名 | 输入 | 预期 |
|---|---|---|
| `test_resolve_max_across_trials` | 3 trials VC={100+200, 150+250, 50+50} | 返回 400.0（150+250） |
| `test_resolve_fallback_no_bhv` | BHV2Parser.parse() raises | 返回 800.0 |
| `test_resolve_fallback_missing_fields` | 所有 trial VC 为空 dict | 返回 800.0 |
| `test_resolve_skips_partial_trials` | 一个 trial 只有 onset_time | 该 trial 被跳过（另一个完整的生效） |

### ExportStage Phase 2.5 集成（`tests/test_stages/test_export.py`）

| 测试名 | 预期 |
|---|---|
| `test_phase2_writes_derivatives_dir` | 运行后 `output_dir/07_derivatives/` 存在，且旧 `07_export/` 不存在 |
| `test_phase2_writes_three_files` | TrialRaster/UnitProp/TrialRecord 各 1 份 |
| `test_phase2_filenames_use_session_id_canonical` | 文件名含 `canonical()` |
| `test_phase2_disabled_skips` | `derivatives.enabled=False` → 目录不创建 |
| `test_phase2_auto_post_onset_calls_resolver` | `post_onset_ms="auto"` → `resolve_post_onset_ms` 被调用 |
| `test_phase2_numeric_post_onset_bypasses_resolver` | `post_onset_ms=500` → resolver 不调用 |
| `test_phase2_reads_nwb_post_write` | mock `pynwb.NWBHDF5IO` 被以 `"r"` 打开刚写的 NWB |
| `test_phase2_runs_before_phase3` | Phase 2.5 在 `_export_phase3_background` 前完成（顺序断言） |

**现有测试删除/修改**：
- 现有 `_export_phase2` 相关测试（若存在 `export/trials.csv` / `units.csv` / `raster_*.h5` 断言）全部删除或改写
- `compute_probe_rasters` 相关 Group F 测试**保留**（功能独立，仍用于 NWB 嵌入 Raster 列）

---

## 8. 与 MATLAB 参考实现的关系

MATLAB 参考 pipeline 无对应 step。这是 Python 端为分析工作流新增的导出，目标：

- 补齐 MATLAB 老 pipeline 的 `TrialRaster_*.mat` / `UnitProp_*.mat` 分发产物
- 采用 HDF5 + CSV 而非 `.mat`（跨语言 + 纯开源工具链）
- 稀疏格式兼容 scipy.sparse.coo_matrix（下游可直接读回）

---

## 9. 可配参数汇总

| 参数 | 路径 | 默认 | 说明 |
|---|---|---|---|
| 启用开关 | `export.derivatives.enabled` | `True` | 关闭后完整跳过 Phase 2.5 |
| 预采样窗口 | `export.derivatives.pre_onset_ms` | 50.0 | 相对 trial start_time |
| 后采样窗口 | `export.derivatives.post_onset_ms` | `"auto"` | `"auto"` = BHV2 `max(VC.onset_time+offset_time)` |
| Bin 大小 | `export.derivatives.bin_size_ms` | 1.0 | ms |
| 并行度 | `export.derivatives.n_jobs` | 1 | joblib 并行单元数 |
