# Spec: pipelines/runner.py

## 1. 目标

实现 pipeline 编排层：`PipelineRunner`。

按照 `STAGE_ORDER` 定义的顺序（discover → preprocess → sort → merge → synchronize → curate → postprocess → export）调度各 stage 执行。核心功能：

1. **断点续跑**：检查每个 stage 的 checkpoint，已完成的自动跳过
2. **资源配置**：若 config 中有 `"auto"` 值，启动 ResourceDetector 自动解析为具体数值
3. **子集执行**：`run(stages=["sort", "curate"])` 只执行指定的 stage，但按 STAGE_ORDER 顺序
4. **状态查询**：`get_status()` 返回每个 stage 的当前状态

无 UI 依赖：不 import click，不 print，不 sys.exit。

---

## 2. 输入

### `PipelineRunner.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 活跃的 pipeline session |
| `pipeline_config` | `PipelineConfig` | 完整的 pipeline 配置对象 |
| `sorting_config` | `SortingConfig` | Sorting 专属配置对象 |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调，传递给所有 stage |

### `run(stages=None)` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `stages` | `list[str] \| None` | stage 名称列表，None 表示全部执行 |

---

## 3. 输出

### `run()` → `None`

副作用：按顺序执行各 stage，每个 stage 写 checkpoint 文件。

### `get_status()` → `dict[str, str]`

```python
{
  "discover":    "completed",      # stage checkpoint exists, status=completed
  "preprocess":  "partial (1/2)",  # per-probe stages: partial if some probes done
  "sort":        "completed",
  "merge":       "skipped",        # config.merge.enabled=False → skipped
  "synchronize": "pending",        # no checkpoint yet
  "curate":      "pending",
  "postprocess": "pending",
  "export":      "pending",
}
```

状态值：
- `"completed"` — stage 级 checkpoint 存在且 status=completed
- `"failed"` — stage 级 checkpoint 存在且 status=failed
- `"partial (N/M probes)"` — per-probe 阶段，部分 probe 完成（只用于 preprocess/sort/curate/postprocess）
- `"pending"` — 无 checkpoint
- `"skipped"` — stage 被配置禁用（如 `config.merge.enabled=False`）

---

## 4. 处理步骤

### `__init__`

1. 存储 `session`、`pipeline_config`、`sorting_config`、`progress_callback`
2. **解析 "auto" 配置值**：
   - 扫描 `pipeline_config` 中的 `n_jobs`、`chunk_duration`、`max_workers`
   - 扫描 `sorting_config` 中的 `sorter.params.batch_size`
   - 若任意值为字符串 `"auto"` → 创建 `ResourceDetector` 实例，调用 `detect()` 和 `recommend()`
   - 将 `"auto"` 替换为推荐值（整数或字符串）；非 `"auto"` 值保持原样
   - 记录 info 日志：resolved auto values
3. 存储 `self.checkpoint_manager = CheckpointManager(session.output_dir)`

### `run(stages=None)`

1. **验证 stage 名称**：若 `stages` 不为 None，检查每个名称是否在 `STAGE_ORDER` 中；非法名称 → raise `ValueError("Unknown stage: {name}")`
2. 确定要执行的 stage 列表：
   - `stages=None` → `STAGE_ORDER`
   - 否则 → `[s for s in STAGE_ORDER if s in stages]`（保持顺序）
3. 对每个 stage 调用 `run_stage(stage_name)`
4. 若 `run_stage` raise `StageError`（或其子类）→ re-raise（fail-fast，不继续后续 stage）

### `run_stage(stage_name)`

1. 验证 `stage_name` 在 `STAGE_ORDER`；否则 raise `ValueError`
2. 实例化对应 stage 类（通过 `STAGE_CLASS_MAP[stage_name](session, progress_callback)`）
3. 调用 `stage.run()`；若 raise → re-raise

```python
STAGE_CLASS_MAP = {
    "discover":     DiscoverStage,
    "preprocess":   PreprocessStage,
    "sort":         SortStage,
    "merge":        MergeStage,
    "synchronize":  SynchronizeStage,
    "curate":       CurateStage,
    "postprocess":  PostprocessStage,
    "export":       ExportStage,
}
```

**merge stage 特殊处理**：`run_stage("merge")` 在实例化 `MergeStage` 之前先检查 `config.merge.enabled`；若为 `False`（默认值），立即 return 跳过该 stage，不写 checkpoint。

（SortStage 内部已保证串行，runner 无需额外处理）

### `get_status() -> dict[str, str]`

对每个 stage 检查 checkpoint：

**Per-probe stages**（preprocess, sort, curate, postprocess）：
- 若 stage 级 checkpoint completed → `"completed"`
- 若 stage 级 checkpoint failed → `"failed"`
- 否则：计算 `n_done = sum(1 for p in session.probes if checkpoint_manager.is_complete(stage, p.probe_id))`
  - `n_done == 0` → `"pending"`
  - `0 < n_done < n_probes` → `f"partial ({n_done}/{n_probes} probes)"`
  - `n_done == n_probes` → `"completed"`（stage 级 checkpoint 未写时的兜底）

**Single-checkpoint stages**（discover, synchronize, export）：
- stage 级 completed → `"completed"`
- stage 级 failed → `"failed"`
- 无 checkpoint → `"pending"`

**Optional stages**（merge）：
- `config.merge.enabled=False` → `"skipped"`
- 否则按 per-probe stages 逻辑处理

---

## 5. 公开 API

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pynpxpipe.core.config import PipelineConfig, SortingConfig
    from pynpxpipe.core.session import Session


STAGE_ORDER: list[str] = [
    "discover",
    "preprocess",
    "sort",
    "merge",          # NEW — optional, default OFF
    "synchronize",
    "curate",
    "postprocess",
    "export",
]


class PipelineRunner:
    """Orchestrates the full pipeline from discover through export.

    Checks checkpoints before each stage — completed stages are skipped.
    'auto' values in config are resolved via ResourceDetector at init time.
    Sort stage always runs serially (enforced inside SortStage itself).

    Raises:
        ValueError: If an unknown stage name is provided to run() or run_stage().
        StageError: Propagated from any failing stage (fail-fast).
    """

    def __init__(
        self,
        session: Session,
        pipeline_config: PipelineConfig,
        sorting_config: SortingConfig,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None: ...

    def run(self, stages: list[str] | None = None) -> None:
        """Run the pipeline, optionally restricted to a subset of stages.

        Stages execute in STAGE_ORDER, even if a subset is specified.

        Args:
            stages: Stage names to run (e.g. ["sort", "curate"]).
                If None, all stages are run.

        Raises:
            ValueError: If any stage name is not in STAGE_ORDER.
            StageError: Propagated from the first failing stage.
        """

    def run_stage(self, stage_name: str) -> None:
        """Instantiate and run a single stage by name.

        Raises:
            ValueError: If stage_name not in STAGE_ORDER.
            StageError: Propagated from stage.run().
        """

    def get_status(self) -> dict[str, str]:
        """Return completion status of all stages.

        Returns:
            Dict mapping stage_name → status string.
            Status values: "completed", "failed", "pending",
            "partial (N/M probes)" for per-probe stages.
        """
```

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_runner.py`（或 `tests/test_pipelines/test_runner.py`）

测试策略：mock 每个 stage 的 `run()` 方法（避免真实 stage 执行）；使用合成 session + config；用 `tmp_path` 作为 output_dir。

### 基本执行

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_executes_all_stages_in_order` | stages=None | 8 个 stage 按 STAGE_ORDER 调用（merge 默认 skipped） |
| `test_run_subset_of_stages` | stages=["sort", "curate"] | 仅 2 个 stage 被调用，顺序按 STAGE_ORDER |
| `test_run_subset_maintains_order` | stages=["export", "discover"] | 按 discover→export 顺序（不按输入顺序） |
| `test_run_stage_by_name` | `run_stage("sort")` | SortStage.run() 被调用一次 |
| `test_run_stage_unknown_raises_value_error` | `run_stage("invalid")` | raise `ValueError` |
| `test_run_unknown_stage_raises_value_error` | `run(["unknown"])` | raise `ValueError` |

### 断点续跑

| 测试名 | 预期行为 |
|---|---|
| `test_completed_stage_checkpoint_skips_stage` | discover checkpoint=completed → DiscoverStage.run() 内部自行跳过（runner 不需要额外检查） |

### Auto 配置解析

| 测试名 | 预期行为 |
|---|---|
| `test_auto_n_jobs_resolved_at_init` | `n_jobs="auto"` → `ResourceDetector` 被实例化并调用 |
| `test_explicit_n_jobs_not_overridden` | `n_jobs=4` → `ResourceDetector` 未被实例化 |
| `test_auto_batch_size_resolved` | `sorting.sorter.params.batch_size="auto"` → 解析为整数 |

### Fail-fast

| 测试名 | 预期行为 |
|---|---|
| `test_stage_error_stops_pipeline` | sort.run() raise `SortError` → run() re-raise，curate 未被调用 |
| `test_non_stage_error_propagates` | sort.run() raise `RuntimeError` → re-raise |

### `get_status`

| 测试名 | 预期行为 |
|---|---|
| `test_status_all_pending` | 无任何 checkpoint | 所有 stage "pending" |
| `test_status_completed_after_run` | discover 完成 | `get_status()["discover"] == "completed"` |
| `test_status_partial_per_probe` | 2 probes，imec0 preprocess 完成 | `get_status()["preprocess"] == "partial (1/2 probes)"` |
| `test_status_failed` | stage checkpoint status=failed | `get_status()[stage] == "failed"` |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.core.checkpoint.CheckpointManager` | 项目内部 | checkpoint 状态查询 |
| `pynpxpipe.core.resources.ResourceDetector` | 项目内部 | "auto" 值解析 |
| `pynpxpipe.stages.*` (all 8 stage classes) | 项目内部 | stage 实例化 |
| `pynpxpipe.stages.merge.MergeStage` | 项目内部 | merge stage（optional, default OFF） |
| `pynpxpipe.core.config.PipelineConfig` | 项目内部 | TYPE_CHECKING |
| `pynpxpipe.core.config.SortingConfig` | 项目内部 | TYPE_CHECKING |
| `pynpxpipe.core.session.Session` | 项目内部 | TYPE_CHECKING |
