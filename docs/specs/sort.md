# Spec: stages/sort.py

## 1. 目标

实现 pipeline 第三个 stage：**排序（Sort）**。

对每个 probe 运行 spike sorting。支持两种模式：
- **`"local"`**：本地运行配置的 sorter（默认 Kilosort4，通过 SpikeInterface 调用）
- **`"import"`**：从外部路径导入已完成的 sorting 结果（适用于在 Windows 实验室机器上预计算的 Kilosort 输出）

**关键约束**：本 stage **始终串行处理**，不受 `config.pipeline.parallel.enabled` 影响。原因：spike sorting 需要独占 GPU 资源。

---

## 2. 输入

### `SortStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `probes`、`output_dir`、`config` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调，CLI 为 None |

### `session.config` 中读取的配置键

| 配置键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `config.sorting.mode` | `str` | `"local"` | `"local"` 或 `"import"` |
| `config.sorting.sorter.name` | `str` | `"kilosort4"` | SpikeInterface sorter 名称 |
| `config.sorting.sorter.params` | `dict` | `{}` | 传递给 `si.run_sorter` 的参数字典 |
| `config.sorting.sorter.params.batch_size` | `int \| str` | `"auto"` | Kilosort batch_size；`"auto"` 由 ResourceDetector 在 runner 层解析 |
| `config.sorting.import_cfg.format` | `str` | `"kilosort"` | 导入格式：`"kilosort"` 或 `"phy"` |
| `config.sorting.import_cfg.paths` | `dict[str, str]` | `{}` | probe_id → 外部 sorting 路径映射 |
| `config.pipeline.n_jobs` | `int` | `1` | SpikeInterface 内部并行数（sort 建议保持 1） |

---

## 3. 输出

### 每个 probe 的输出

| 输出 | 路径 | 说明 |
|---|---|---|
| Sorting 结果 | `{output_dir}/sorted/{probe_id}/` | SpikeInterface Sorting 对象，保存为 binary_folder 格式 |
| per-probe checkpoint | `{output_dir}/checkpoints/sort_{probe_id}.json` | 含 sorting 摘要 |

### per-probe checkpoint payload

```json
{
  "probe_id": "imec0",
  "mode": "local",
  "sorter_name": "kilosort4",
  "n_units": 142,
  "output_path": "/output/sorted/imec0"
}
```

`n_units == 0` 是允许的（WARNING 日志，不 raise）。

---

## 4. 处理步骤

### `run()`

1. 验证 `config.sorting.mode` 为 `"local"` 或 `"import"`；否则 raise `SortError("Unknown mode: {mode}")`
2. 检查 stage 级 checkpoint；若完成 → return
3. `_report_progress("Starting sort (always serial)", 0.0)`
4. 对 `session.probes` 串行遍历（无视 `parallel.enabled` 配置）：
   - `"local"` 模式：调用 `_sort_probe_local(probe_id)`
   - `"import"` 模式：从 `config.sorting.import_cfg.paths[probe_id]` 取外部路径，调用 `_import_sorting(probe_id, Path(path))`
5. 每个 probe 完成后报告进度
6. 所有 probe 完成 → `_write_checkpoint({...})` + `_report_progress("Sort complete", 1.0)`

若某 probe 失败：`_write_failed_checkpoint(error, probe_id=probe_id)` 后 re-raise。

### `_sort_probe_local(probe_id)`

1. 检查 per-probe checkpoint；若已完成 → return
2. **加载预处理录制**：从 `{output_dir}/preprocessed/{probe_id}/` 读取 Zarr recording（`si.load_extractor(zarr_path)`）
3. **运行 sorter**：
   ```python
   sorting = si.run_sorter(
       config.sorting.sorter.name,
       recording,
       output_folder=Path(output_dir) / "sorter_output" / probe_id,
       **config.sorting.sorter.params,
   )
   ```
4. **验证结果**：`n_units = len(sorting.get_unit_ids())`；若 `n_units == 0` → 记录 WARNING（不 raise）
5. **保存 sorting**：`sorting.save(folder=output_dir / "sorted" / probe_id, format="binary_folder")`
6. **写 checkpoint** + `del sorting, recording; gc.collect()`

若 `si.run_sorter` raise（CUDA OOM、sorter 未安装等）→ raise `SortError` 包装原始异常。

### `_import_sorting(probe_id, import_path)`

1. 检查 per-probe checkpoint；若已完成 → return
2. 验证 `import_path` 存在；不存在 → raise `SortError("Import path not found: {import_path}")`
3. **加载外部结果**：
   - `"kilosort"` 格式：`sorting = si.read_sorter_folder(import_path)` 或 `si.read_kilosort(import_path)`
   - `"phy"` 格式：`sorting = si.read_phy(import_path)`
4. **验证结果**：`n_units = len(sorting.get_unit_ids())`；若 `n_units == 0` → WARNING
5. **保存 sorting**：同 local 模式
6. **写 checkpoint** + `del sorting; gc.collect()`

若加载失败（文件损坏等）→ raise `SortError`。

---

## 5. 公开 API

```python
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class SortStage(BaseStage):
    """Runs spike sorting for each probe and saves the Sorting object.

    Two modes via config.sorting.mode:
    - "local": Run configured sorter (default Kilosort4) locally via SpikeInterface.
    - "import": Load externally computed sorting from disk.

    Always serial regardless of pipeline parallel settings — GPU is exclusive.
    Zero units after sorting is a WARNING, not an error.

    Raises:
        SortError: If mode is unknown, sorter fails (CUDA OOM etc.), or
            import path doesn't exist.
    """

    STAGE_NAME = "sort"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None: ...

    def run(self) -> None:
        """Sort all probes serially (always, regardless of parallel config).

        Raises:
            SortError: On unrecoverable failure.
        """

    def _sort_probe_local(self, probe_id: str) -> None:
        """Run the configured sorter locally for one probe.

        Args:
            probe_id: Probe identifier (e.g. "imec0").

        Raises:
            SortError: On sorting failure.
        """

    def _import_sorting(self, probe_id: str, import_path: Path) -> None:
        """Import an externally computed sorting result for one probe.

        Args:
            probe_id: Probe identifier.
            import_path: Path to the external Kilosort/Phy output folder.

        Raises:
            SortError: If path missing or sorting result invalid.
        """
```

### 可配参数

| 参数 | 配置键 | 默认 | 说明 |
|---|---|---|---|
| `mode` | `config.sorting.mode` | `"local"` | `"local"` 或 `"import"` |
| `sorter_name` | `config.sorting.sorter.name` | `"kilosort4"` | SpikeInterface sorter ID |
| `sorter_params` | `config.sorting.sorter.params` | `{}` | 传递给 run_sorter 的参数（含 batch_size） |
| `import_format` | `config.sorting.import_cfg.format` | `"kilosort"` | 导入格式 |
| `import_paths` | `config.sorting.import_cfg.paths` | `{}` | probe_id → 外部路径映射 |

**KS4 参数设计约束（运动校正互斥）**：
- 若 preprocess 阶段启用了外部运动校正（`motion_correction.method: "dredge"`）：
  `sorter_params.nblocks` 必须为 `0`，`sorter_params.do_CAR` 建议为 `false`（因 preprocess 已做 CMR）
- 若 preprocess 未做运动校正：`sorter_params.nblocks` 可设为 `15`（KS4 内部漂移校正）
- SortStage 本身不验证此约束，由用户在配置文件中保证一致性；运行时日志中应记录当前 nblocks 值

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_sort.py`

测试策略：mock `si.run_sorter`（返回 mock Sorting 对象）和 `si.read_sorter_folder`；mock `sorting.save`；用 `tmp_path`。

### local 模式正常流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_local_mode_calls_run_sorter` | mode="local" | `si.run_sorter` 以 sorter_name 调用 |
| `test_local_mode_saves_sorting` | mode="local"，sorting 返回有效 | `sorting.save` 调用路径含 `sorted/imec0` |
| `test_local_mode_writes_probe_checkpoint` | 成功 | `checkpoints/sort_imec0.json` status=completed |
| `test_local_zero_units_logs_warning_not_error` | `sorting.get_unit_ids()` 返回空 | 不 raise，记录 WARNING |
| `test_sorter_params_passed_to_run_sorter` | `sorter_params={"nblocks": 5}` | `si.run_sorter` 被调以 `nblocks=5` |

### import 模式

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_import_mode_calls_read_sorter_folder` | mode="import", format="kilosort" | `si.read_sorter_folder` 以 import_path 调用 |
| `test_import_mode_path_missing_raises` | import_path 不存在 | raise `SortError`，消息含路径 |
| `test_import_phy_format` | format="phy" | `si.read_phy` 被调用 |
| `test_import_writes_checkpoint` | 成功 | `checkpoints/sort_imec0.json` status=completed |

### 串行保证

| 测试名 | 预期行为 |
|---|---|
| `test_always_serial_even_if_parallel_enabled` | `parallel.enabled=True`，仍串行处理所有 probe（无 ProcessPoolExecutor） |

### 断点续跑

| 测试名 | 预期行为 |
|---|---|
| `test_skips_sorted_probe` | imec0 checkpoint complete → `si.run_sorter` 未被调用 |
| `test_processes_remaining_probe` | imec0 complete，imec1 未完成 → imec1 被处理 |

### 错误处理

| 测试名 | 预期行为 |
|---|---|
| `test_run_sorter_failure_raises_sort_error` | `si.run_sorter` raise RuntimeError | raise `SortError` |
| `test_failed_checkpoint_written_on_error` | 失败 | `checkpoints/sort_imec0.json` status=failed |
| `test_unknown_mode_raises_sort_error` | `mode="invalid"` | raise `SortError`，消息含 "Unknown mode" |

### GC 释放

| 测试名 | 预期行为 |
|---|---|
| `test_gc_collect_called_after_sort` | `gc.collect` 在每个 probe 完成后被调用 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.SortError` | 项目内部 | 排序失败时抛出 |
| `spikeinterface.sorters` | 第三方 | `run_sorter` |
| `spikeinterface.core` | 第三方 | `read_sorter_folder`、`read_phy`、`load_extractor` |
| `gc` | 标准库 | 显式内存释放 |
| `pathlib.Path` | 标准库 | 路径操作 |

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #13（AP 预处理 + KS4） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #13 段落 |
| **ADR 关联** | ADR-001（DREDge vs KS4 nblocks 互斥） |

### MATLAB 算法概要

MATLAB 在 step #13 中直接调用 KS4（或 KS2/KS3），使用其内建的 drift correction（`nblocks` 参数）。不提供 import 模式。

### 有意偏离

| 偏离 | 理由 |
|------|------|
| 支持 local 和 import 两种模式 | MATLAB 仅 local；import 模式允许在 Windows GPU 机器上预计算后导入 |
| nblocks/DREDge 互斥由 runner 层自动联动 | MATLAB 需手动确保参数一致；Python 在 `runner.py` 中根据 preprocess checkpoint 自动注入 nblocks=0（ADR-001） |
| sorting 后立即写 binary_folder | MATLAB 使用 KS4 原生输出格式（ops.mat + rez2.mat + .npy 文件）；Python 统一为 SpikeInterface binary_folder 格式 |
| 零 unit 是 WARNING 不是 error | MATLAB 无此检查；Python 允许 pipeline 继续（后续 stage 可处理空 sorting） |
