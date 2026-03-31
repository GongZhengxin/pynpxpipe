# Spec: core/checkpoint.py — 断点续跑 Checkpoint 管理

> 版本：0.1.0  
> 日期：2026-03-31  
> 状态：待实现

---

## 1. 目标

提供轻量、可靠的 checkpoint 文件读写机制，支持 pipeline 断点续跑。

- 每个 stage 成功完成后写入 JSON checkpoint 文件
- Pipeline 启动时检查 checkpoint，自动跳过已完成的 stage
- 支持 stage 级和 probe 级两种粒度的 checkpoint
- **原子写入**：先写临时文件再重命名，防止写入中断导致 checkpoint 损坏
- failed 状态 checkpoint 保留错误信息，支持用户手动修复后删除并重跑
- 无 UI 依赖：不 import click，不 print()，不 sys.exit()
- 写入失败时 raise `CheckpointError`（不静默忽略）

---

## 2. 依赖

```
core/errors.py   ← CheckpointError（本 spec 同步定义，需新增到 errors.py）
json             ← 标准库
datetime         ← 标准库
pathlib.Path     ← 标准库
structlog        ← 日志（写 checkpoint 时记录 DEBUG 日志）
```

---

## 3. CheckpointError 定义（新增到 core/errors.py）

```python
class CheckpointError(PynpxpipeError):
    """Checkpoint 文件读写失败。

    Attributes:
        stage: 出错的 stage 名称（如 "sort"）
        path: checkpoint 文件路径
        reason: 人类可读的错误原因
    """
    def __init__(self, stage: str, path: Path, reason: str) -> None:
        self.stage = stage
        self.path = path
        self.reason = reason
        super().__init__(f"CheckpointError [{stage}] {path}: {reason}")
```

---

## 4. 公开 API

### 4.1 CheckpointManager

```python
class CheckpointManager:
    """Manages per-stage checkpoint files under {output_dir}/checkpoints/.

    Checkpoint file naming convention:
        - Stage-level:  checkpoints/{stage_name}.json
        - Probe-level:  checkpoints/{stage_name}_{probe_id}.json
    """

    def __init__(self, output_dir: Path) -> None:
        """初始化 checkpoint manager，创建 checkpoints/ 子目录（若不存在）。

        Args:
            output_dir: Session 输出目录，checkpoint 文件存储在
                {output_dir}/checkpoints/ 下。

        Raises:
            OSError: 若 checkpoints/ 目录无法创建。
        """

    def is_complete(self, stage_name: str, probe_id: str | None = None) -> bool:
        """检查给定 stage（可选 probe）是否已有 completed checkpoint。

        Args:
            stage_name: Pipeline stage 名称（如 "discover", "sort"）。
            probe_id: 探针标识符（如 "imec0"）。None 表示 stage 级别检查。

        Returns:
            True：checkpoint 文件存在且 status == "completed"。
            False：checkpoint 不存在，或 status != "completed"（如 "failed"）。

        Raises:
            CheckpointError: 若 checkpoint 文件存在但无法解析（JSON 损坏）。
        """

    def mark_complete(
        self,
        stage_name: str,
        data: dict[str, Any],
        probe_id: str | None = None,
    ) -> None:
        """写入 completed checkpoint。

        Args:
            stage_name: Stage 名称。
            data: Stage 特定的 payload（如 {"n_units": 142, "sorting_path": "..."}）。
            probe_id: 探针标识符（probe 级 checkpoint），None 表示 stage 级。

        Raises:
            CheckpointError: 若文件写入失败。
        """

    def mark_failed(
        self,
        stage_name: str,
        error: str,
        probe_id: str | None = None,
    ) -> None:
        """写入 failed checkpoint，保留错误信息。

        Args:
            stage_name: Stage 名称。
            error: 异常的字符串表示（通常是 traceback 末行）。
            probe_id: 探针标识符，None 表示 stage 级。

        Raises:
            CheckpointError: 若文件写入失败（此时错误信息记入日志，不二次 raise）。
        """

    def read(self, stage_name: str, probe_id: str | None = None) -> dict[str, Any] | None:
        """读取 checkpoint 文件内容。

        Args:
            stage_name: Stage 名称。
            probe_id: 探针标识符，None 表示 stage 级。

        Returns:
            解析后的 checkpoint dict；若文件不存在返回 None。

        Raises:
            CheckpointError: 若文件存在但 JSON 损坏无法解析。
        """

    def clear(self, stage_name: str, probe_id: str | None = None) -> None:
        """删除 checkpoint 文件（强制 stage 重跑）。

        文件不存在时静默返回（不 raise）。

        Args:
            stage_name: Stage 名称。
            probe_id: 探针标识符，None 表示 stage 级。
        """

    def list_completed_stages(self) -> list[str]:
        """返回所有已完成 stage 的名称列表（不含 probe_id）。

        扫描 checkpoints/ 目录，收集所有 status == "completed" 的文件名（去重）。

        Returns:
            stage 名称列表，如 ["discover", "preprocess"]。
        """
```

---

## 5. Checkpoint 文件格式

### 5.1 命名规则

| 类型 | 文件名模式 | 示例 |
|------|-----------|------|
| Stage 级 | `{stage_name}.json` | `discover.json` |
| Probe 级 | `{stage_name}_{probe_id}.json` | `preprocess_imec0.json` |

**probe_id 中禁止出现 `/`**（SpikeGLX 标准 probe_id 均为 `imec{N}`，不含特殊字符）。

### 5.2 必填字段（所有 checkpoint 共有）

```json
{
  "stage": "string",
  "status": "completed | failed",
  "completed_at": "ISO8601 timestamp"
}
```

- `completed_at`：对 completed 状态用 `completed_at`，对 failed 状态用 `failed_at`
- `probe_id` 字段：probe 级 checkpoint 时添加，stage 级 checkpoint 不添加

### 5.3 各 Stage 的完整 Checkpoint 格式

**discover**：
```json
{
  "stage": "discover",
  "status": "completed",
  "completed_at": "2026-03-31T10:00:00",
  "n_probes": 2,
  "probe_ids": ["imec0", "imec1"],
  "nidq_found": true,
  "lf_found": {"imec0": true, "imec1": false}
}
```

**preprocess（probe 级）**：
```json
{
  "stage": "preprocess",
  "probe_id": "imec0",
  "status": "completed",
  "completed_at": "2026-03-31T11:30:00",
  "bad_channels": [32, 45, 67],
  "recording_path": "preprocessed/imec0",
  "n_channels_after": 381
}
```

**sort（probe 级）**：
```json
{
  "stage": "sort",
  "probe_id": "imec0",
  "status": "completed",
  "completed_at": "2026-03-31T14:00:00",
  "sorter": "kilosort4",
  "mode": "local",
  "n_units": 142,
  "sorting_path": "sorting/imec0"
}
```

**synchronize**：
```json
{
  "stage": "synchronize",
  "status": "completed",
  "completed_at": "2026-03-31T14:30:00",
  "sync_tables_path": "sync/sync_tables.json",
  "behavior_events_path": "sync/behavior_events.parquet",
  "n_trials": 480,
  "sync_residuals_ms": {"imec0": 0.8, "imec1": 1.2},
  "photodiode_calibrated": true,
  "monitor_delay_ms": -5,
  "dataset_name": "exp_20260101"
}
```

**curate（probe 级）**：
```json
{
  "stage": "curate",
  "probe_id": "imec0",
  "status": "completed",
  "completed_at": "2026-03-31T15:00:00",
  "n_units_before": 142,
  "n_units_after": 87,
  "curated_path": "curated/imec0"
}
```

**postprocess（probe 级）**：
```json
{
  "stage": "postprocess",
  "probe_id": "imec0",
  "status": "completed",
  "completed_at": "2026-03-31T17:00:00",
  "analyzer_path": "postprocessed/imec0",
  "n_units": 87,
  "slay_computed": true,
  "eye_validation_computed": true
}
```

**export**：
```json
{
  "stage": "export",
  "status": "completed",
  "completed_at": "2026-03-31T18:00:00",
  "nwb_path": "NWBFile_session_20260101.nwb",
  "file_size_gb": 2.3
}
```

**failed checkpoint（任意 stage）**：
```json
{
  "stage": "sort",
  "probe_id": "imec0",
  "status": "failed",
  "failed_at": "2026-03-31T14:00:00",
  "error": "CUDA out of memory. Tried to allocate 2.50 GiB..."
}
```

---

## 6. 实现步骤

### 6.1 `__init__(output_dir)`

```
1. self._checkpoints_dir = output_dir / "checkpoints"
2. self._checkpoints_dir.mkdir(parents=True, exist_ok=True)
3. self._logger = get_logger(__name__)
```

### 6.2 `_checkpoint_path(stage_name, probe_id) → Path`（私有辅助）

```
if probe_id is None:
    return self._checkpoints_dir / f"{stage_name}.json"
else:
    return self._checkpoints_dir / f"{stage_name}_{probe_id}.json"
```

### 6.3 `mark_complete(stage_name, data, probe_id)`

```
1. payload = {
       "stage": stage_name,
       "status": "completed",
       "completed_at": datetime.now(timezone.utc).isoformat(),
       **data,
   }
   若 probe_id 不为 None，插入 "probe_id": probe_id 到 payload（紧跟 "stage" 之后）

2. _atomic_write(path, payload)
3. log.debug("checkpoint written", stage=stage_name, probe_id=probe_id, status="completed")
```

### 6.4 `mark_failed(stage_name, error, probe_id)`

```
1. payload = {
       "stage": stage_name,
       "status": "failed",
       "failed_at": datetime.now(timezone.utc).isoformat(),
       "error": str(error),
   }
   若有 probe_id，加入 payload

2. try:
       _atomic_write(path, payload)
   except OSError as e:
       log.error("failed to write failed checkpoint", stage=stage_name, error=str(e))
       # 不 raise：写 failed checkpoint 本身失败时不掩盖原始异常
3. log.debug("checkpoint written", stage=stage_name, status="failed")
```

### 6.5 `is_complete(stage_name, probe_id)`

```
1. path = _checkpoint_path(stage_name, probe_id)
2. 若 path 不存在：return False
3. try:
       data = json.loads(path.read_text(encoding="utf-8"))
   except (json.JSONDecodeError, OSError) as e:
       raise CheckpointError(stage_name, path, f"corrupt checkpoint: {e}") from e
4. return data.get("status") == "completed"
```

### 6.6 `_atomic_write(path, data)`（私有）

```
1. tmp_path = path.with_suffix(".json.tmp")
2. try:
       tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
       tmp_path.replace(path)    # 原子重命名（同卷内）
   except OSError as e:
       tmp_path.unlink(missing_ok=True)   # 清理临时文件
       raise CheckpointError(stage_name_from_data, path, str(e)) from e
```

**Windows 兼容性**：`Path.replace()` 在 Windows 上若目标文件存在会覆盖（Python 3.3+），行为与 POSIX 一致，无需特殊处理。

---

## 7. 原子写入要求

- **必须使用临时文件 + `replace()`**，不得直接 `open(path, "w")`
- 原因：若写入过程中进程被杀，直接写会留下空文件或不完整 JSON，下次启动误认为 checkpoint 存在
- 临时文件命名：`{original_name}.tmp`，写入成功后原子重命名为正式文件名
- 写入失败时清理临时文件（`unlink(missing_ok=True)`），然后 raise CheckpointError

---

## 8. 断点续跑工作流

用户在 stage 失败后的恢复步骤：

```
1. 查看 failed checkpoint：{output_dir}/checkpoints/{stage_name}.json
   → 检查 "error" 字段了解失败原因

2. 修复问题（更新配置、补充数据等）

3. 删除 failed checkpoint（或调用 CheckpointManager.clear()）
   > 注意：clear() 只删除 failed checkpoint，completed 的不影响

4. 重新运行 pipeline：自动从失败点续跑
```

**`is_complete()` 对 failed checkpoint 返回 False**，因此 failed 状态的 stage 会被自动重跑。

---

## 9. 与 stages/base.py 的集成模式

```python
class BaseStage:
    def __init__(self, session: Session, ...):
        self._ckpt = CheckpointManager(session.output_dir)

    def _is_complete(self, probe_id=None) -> bool:
        return self._ckpt.is_complete(self.STAGE_NAME, probe_id)

    def _write_checkpoint(self, data: dict, probe_id=None) -> None:
        self._ckpt.mark_complete(self.STAGE_NAME, data, probe_id)

    def _write_failed_checkpoint(self, error: Exception, probe_id=None) -> None:
        self._ckpt.mark_failed(self.STAGE_NAME, str(error), probe_id)
```

---

## 10. 测试要点

以下行为**每条都必须有对应的单元测试**：

1. `CheckpointManager(output_dir)` — 创建 `output_dir/checkpoints/` 目录（若不存在）
2. `mark_complete("discover", {...})` — 写入 `discover.json`，包含 `status="completed"`
3. `mark_complete("preprocess", {...}, probe_id="imec0")` — 写入 `preprocess_imec0.json`
4. `is_complete("discover")` 文件存在且 status=completed → 返回 True
5. `is_complete("discover")` 文件不存在 → 返回 False（不 raise）
6. `is_complete("sort", "imec0")` status="failed" → 返回 False
7. `is_complete("sort", "imec0")` JSON 损坏 → raise CheckpointError
8. `mark_failed("sort", "CUDA OOM", "imec0")` — 写入 `sort_imec0.json` 含 `status="failed"` 和 `error` 字段
9. `read("discover")` 文件存在 → 返回完整 dict
10. `read("discover")` 文件不存在 → 返回 None（不 raise）
11. `clear("discover")` 文件存在 → 文件被删除
12. `clear("discover")` 文件不存在 → 静默返回，不 raise
13. `list_completed_stages()` — 正确返回所有 completed 的 stage 名（去重，不含 probe 后缀）
14. 原子写入：模拟写入中途失败（mock `replace()` 抛 OSError）→ 临时文件被清理，raise CheckpointError
15. `mark_complete` 多次调用同一 stage → 覆盖写入，最新结果保留
16. `mark_failed` 写入失败（磁盘满）→ 记录日志，**不** raise（避免掩盖原始 stage 异常）

---

## 11. 与其他模块的接口

| 调用方 | 调用方式 |
|--------|---------|
| `stages/base.py` | `BaseStage.__init__` 中创建 `CheckpointManager`；通过 `_is_complete` / `_write_checkpoint` / `_write_failed_checkpoint` 间接调用 |
| `pipelines/runner.py` | `PipelineRunner.run()` 中通过 `stage._is_complete()` 决定是否跳过 stage |
| CLI `reset-stage` 命令 | 调用 `CheckpointManager.clear()` 删除指定 stage 的 checkpoint |
| CLI `status` 命令 | 调用 `CheckpointManager.list_completed_stages()` 显示进度 |

---

## 12. 与现有 skeleton 的差异（实现时需同步修改）

| 差异 | skeleton 现状 | spec 要求 |
|------|--------------|----------|
| `CheckpointError` | 不在 `errors.py` 中 | 新增到 `core/errors.py` |
| `_atomic_write` | skeleton 无此私有方法 | 新增，mark_complete / mark_failed 内部调用 |
| `_checkpoint_path` | skeleton 无此私有方法 | 新增，统一路径计算逻辑 |
| `mark_failed` 写入失败行为 | 未定义 | 记录日志，不 raise（不掩盖原始异常） |
| `list_completed_stages` | 签名存在，行为未定义 | 扫描目录，解析文件名去重（不含 probe 后缀） |
