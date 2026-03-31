# Spec: stages/base.py

## 1. 目标

`stages/base.py` 提供所有 pipeline stage 的抽象基类 `BaseStage`，将三个横切关注点
（checkpoint 集成、结构化日志、进度回调）集中在基类中，
让子类只需专注于各自的业务逻辑（`run()` 方法）。

无 UI 依赖：不 import click、不 print、不 sys.exit。
子类通过 `STAGE_NAME` 类常量唯一标识自己，此名称同时用于 checkpoint 文件命名和日志标签。

---

## 2. 输入

`BaseStage.__init__(session, progress_callback=None)`:

| 参数 | 类型 | 说明 |
|------|------|------|
| `session` | `Session` | 当前 pipeline 会话，提供 `output_dir`、probes 列表等 |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调，CLI 模式传 `None`，GUI 模式传更新函数 |

子类还必须在类级别定义：

| 属性 | 类型 | 说明 |
|------|------|------|
| `STAGE_NAME` | `str` | 非空字符串，唯一标识该 stage，e.g. `"discover"`, `"sort"` |

---

## 3. 输出

`BaseStage` 本身无返回值；所有输出通过副作用产生：
- 进度通过 `progress_callback` 传出（GUI 模式）或写入结构化日志（CLI 模式）
- 完成/失败状态写入 checkpoint 文件（`{output_dir}/checkpoints/{STAGE_NAME}.json` 或 `{STAGE_NAME}_{probe_id}.json`）

`run()` 是抽象方法，返回 `None`，子类的输出由各自 stage 定义。

---

## 4. 处理步骤

### `__init__` 初始化流程

1. 验证 `STAGE_NAME` 非空 → `ValueError` if empty（防止子类忘记设置）
2. `self.session = session`
3. `self.progress_callback = progress_callback`
4. `self.logger = get_logger(f"pynpxpipe.stages.{self.STAGE_NAME}")`  
   （使用 `core.logging.get_logger`，structlog BoundLogger）
5. `self.checkpoint_manager = CheckpointManager(session.output_dir)`

### `_report_progress(message, fraction)`

```
if self.progress_callback:
    self.progress_callback(message, fraction)
self.logger.info(message, progress=fraction)
```

两条路径并行：有 callback 时调用，同时始终写日志。fraction 语义：0.0 = 开始，1.0 = 完成。

### `_is_complete(probe_id=None)` / `_write_checkpoint(data, probe_id=None)` / `_write_failed_checkpoint(error, probe_id=None)`

均直接委托给 `self.checkpoint_manager`：

| 方法 | 委托调用 |
|------|---------|
| `_is_complete(probe_id)` | `checkpoint_manager.is_complete(STAGE_NAME, probe_id)` |
| `_write_checkpoint(data, probe_id)` | `checkpoint_manager.mark_complete(STAGE_NAME, data, probe_id)` |
| `_write_failed_checkpoint(error, probe_id)` | `checkpoint_manager.mark_failed(STAGE_NAME, str(error), probe_id)` |

stage 级（`probe_id=None`）与 probe 级（`probe_id="imec0"`）checkpoint 相互独立。

---

## 5. 公开 API

```python
class BaseStage(ABC):
    STAGE_NAME: str = ""   # 子类必须覆写为非空字符串

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Raises ValueError if STAGE_NAME is empty."""

    @abstractmethod
    def run(self) -> None:
        """子类实现：执行该 stage 的全部业务逻辑。"""

    def _report_progress(self, message: str, fraction: float) -> None:
        """fraction ∈ [0.0, 1.0]。调用 callback（若有）并写日志。"""

    def _is_complete(self, probe_id: str | None = None) -> bool:
        """查询 checkpoint：该 stage（或该 probe）是否已完成。"""

    def _write_checkpoint(self, data: dict, probe_id: str | None = None) -> None:
        """写入完成 checkpoint，data 为 stage 自定义 payload。"""

    def _write_failed_checkpoint(self, error: Exception, probe_id: str | None = None) -> None:
        """写入失败 checkpoint，error 转为字符串存储。"""
```

**子类模板：**

```python
class DiscoverStage(BaseStage):
    STAGE_NAME = "discover"

    def run(self) -> None:
        if self._is_complete():
            return
        self._report_progress("Scanning session directory", 0.0)
        # ... 业务逻辑 ...
        self._report_progress("Discover complete", 1.0)
        self._write_checkpoint({"n_probes": len(self.session.probes)})
```

---

## 6. 测试范围

测试文件：`tests/test_stages/test_base.py`

| 组 | 测试点 |
|----|-------|
| A. `__init__` | 存储 session；callback 默认 None；存储非 None callback；拥有 CheckpointManager；CheckpointManager 在 output_dir 创建 checkpoints/；拥有 logger |
| B. `_report_progress` | callback 存在时调用；多次调用全部转发；无 callback 不报错 |
| C. checkpoint 集成 | 初始未完成；写 checkpoint 后完成；probe 级初始未完成；写 probe checkpoint 后完成；stage 完成不影响 probe 检查；probe 完成不影响 stage 检查；写失败 checkpoint 不标记为完成；失败 checkpoint 记录 status=failed |
| D. STAGE_NAME 守卫 | 空 STAGE_NAME 抛 ValueError；非空不报错 |

---

## 7. 依赖

| 依赖 | 用途 |
|------|------|
| `core/checkpoint.py` — `CheckpointManager` | checkpoint 读写 |
| `core/logging.py` — `get_logger` | structlog BoundLogger |
| `core/session.py` — `Session` | TYPE_CHECKING 只用于类型标注（避免循环导入） |
| 标准库：`abc`, `collections.abc`, `typing` | ABC / Callable |
