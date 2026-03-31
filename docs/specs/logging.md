# Spec: core/logging.py — 结构化日志

> 版本：0.1.0  
> 日期：2026-03-31  
> 状态：待实现

---

## 1. 目标

为 pipeline 所有 stage 提供统一的结构化日志机制。

- 所有操作写入 JSON Lines 格式日志文件（供机器解析、审计追踪）
- 同时向 stderr 输出人类可读格式（供命令行实时查看）
- 禁止在业务逻辑（core / io / stages / pipelines 层）中使用 `print()`
- `StageLogger` 自动记录 stage 名、probe_id、起止时间、耗时、成功/失败状态
- 无 UI 依赖：不 import click，不 sys.exit()

---

## 2. 依赖

```
structlog >= 21.5.0   ← 结构化日志框架（必选）
logging               ← Python 标准库（structlog 基于此配置）
pathlib.Path          ← 标准库
datetime              ← 标准库
traceback             ← 标准库（error() 方法需要）
```

---

## 3. 公开 API

### 3.1 `setup_logging(log_path, level)`

```python
def setup_logging(log_path: Path, level: int = logging.INFO) -> None:
    """配置 structlog，将 JSON Lines 写入 log_path，将人类可读格式写入 stderr。

    必须在任何 stage 运行前调用一次，通常在 SessionManager.create() 或 CLI 入口点。

    Args:
        log_path: JSON Lines 日志文件路径，父目录必须已存在。
        level: Python logging 级别（默认 INFO）。

    Raises:
        OSError: 若 log_path 无法打开写入。
    """
```

### 3.2 `get_logger(name)`

```python
def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """返回指定名称的 structlog bound logger。

    所有 stage 类在 __init__ 时调用，获取自己的 logger。

    Args:
        name: logger 名称，通常为调用模块的 __name__。

    Returns:
        输出 JSON Lines 到已配置 handler 的 structlog BoundLogger。
    """
```

### 3.3 `StageLogger`

```python
class StageLogger:
    """Stage 级结构化日志的便利封装。

    自动将 stage 和 probe_id 上下文键绑定到每条日志，并记录 wall-clock 耗时。

    Example::

        logger = StageLogger("sort", "imec0")
        logger.start()
        # ... do work ...
        logger.complete({"n_units": 142})
    """

    def __init__(self, stage_name: str, probe_id: str | None = None) -> None:
        """
        Args:
            stage_name: Pipeline stage 名称（如 "sort"）。
            probe_id: 探针标识符（如 "imec0"），None 表示 stage 级日志上下文。
        """

    def start(self) -> None:
        """记录 stage 开始，并保存起始时间供 complete() 计算耗时。"""

    def complete(self, data: dict[str, Any] | None = None) -> None:
        """记录 stage 完成，包含耗时。

        Args:
            data: 可选的 stage 特定汇总字段（如 {"n_units": 142}）。
        """

    def error(self, error: Exception, data: dict[str, Any] | None = None) -> None:
        """记录 stage 失败，包含完整 traceback。

        Args:
            error: 导致失败的异常对象。
            data: 可选的附加上下文字段。
        """

    def info(self, message: str, **kwargs: Any) -> None:
        """在 stage 上下文中记录一条 INFO 消息。

        Args:
            message: 人类可读消息字符串（作为 "event" 字段）。
            **kwargs: 附加结构化字段（如 progress=0.5）。
        """
```

---

## 4. JSON Lines 日志格式

每行一个 JSON 对象，写入 `{output_dir}/pipeline.log`（文件名由 Session 确定）。

### 4.1 通用字段（每条日志必有）

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | str | ISO 8601 格式，含微秒，如 `"2026-03-31T10:00:00.123456"` |
| `level` | str | `"debug"` / `"info"` / `"warning"` / `"error"` |
| `event` | str | 消息字符串 |
| `logger` | str | logger 名称（`__name__`） |

### 4.2 Stage 上下文字段（StageLogger 自动添加）

| 字段 | 类型 | 说明 |
|------|------|------|
| `stage` | str | Stage 名称，如 `"sort"` |
| `probe_id` | str \| null | 探针 ID，无 probe 上下文时为 null |

### 4.3 进度消息（`_report_progress` 调用时）

```json
{
  "timestamp": "2026-03-31T10:05:00.000000",
  "level": "info",
  "event": "Extracting waveforms",
  "logger": "pynpxpipe.stages.postprocess",
  "stage": "postprocess",
  "probe_id": "imec0",
  "progress": 0.45
}
```

### 4.4 Stage 开始事件（`StageLogger.start()`）

```json
{
  "timestamp": "2026-03-31T10:00:00.000000",
  "level": "info",
  "event": "stage_start",
  "logger": "pynpxpipe.stages.sort",
  "stage": "sort",
  "probe_id": "imec0"
}
```

### 4.5 Stage 完成事件（`StageLogger.complete()`）

```json
{
  "timestamp": "2026-03-31T14:00:00.000000",
  "level": "info",
  "event": "stage_complete",
  "logger": "pynpxpipe.stages.sort",
  "stage": "sort",
  "probe_id": "imec0",
  "status": "completed",
  "elapsed_s": 14400.0,
  "n_units": 142,
  "sorting_path": "sorting/imec0"
}
```

### 4.6 Stage 失败事件（`StageLogger.error()`）

```json
{
  "timestamp": "2026-03-31T14:00:00.000000",
  "level": "error",
  "event": "stage_failed",
  "logger": "pynpxpipe.stages.sort",
  "stage": "sort",
  "probe_id": "imec0",
  "status": "failed",
  "elapsed_s": 3600.0,
  "error": "CUDA out of memory. Tried to allocate 2.50 GiB...",
  "traceback": "Traceback (most recent call last):\n  ..."
}
```

---

## 5. 双输出配置（setup_logging 实现流程）

```
setup_logging(log_path, level) 内部步骤：

1. 创建 FileHandler → log_path（mode="a", encoding="utf-8"）
   - 使用 JSON formatter（structlog JSONRenderer）
   - 保留所有结构化字段

2. 创建 StreamHandler → sys.stderr
   - 使用人类可读 formatter（structlog ConsoleRenderer）
   - 颜色支持可选（stdout 重定向时自动关闭）

3. 配置 structlog：
   structlog.configure(
       processors=[
           structlog.stdlib.add_log_level,
           structlog.stdlib.add_logger_name,
           structlog.processors.TimeStamper(fmt="iso", utc=False),
           structlog.stdlib.PositionalArgumentsFormatter(),
           structlog.processors.StackInfoRenderer(),
           structlog.processors.format_exc_info,
           structlog.processors.UnicodeDecoder(),
           # 分流：FileHandler → JSONRenderer，StreamHandler → ConsoleRenderer
           structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
       ],
       logger_factory=structlog.stdlib.LoggerFactory(),
       wrapper_class=structlog.stdlib.BoundLogger,
       cache_logger_on_first_use=True,
   )

4. 配置 Python 标准 logging：
   root_logger = logging.getLogger()
   root_logger.setLevel(level)
   root_logger.addHandler(file_handler_with_json_formatter)
   root_logger.addHandler(stderr_handler_with_console_formatter)

5. 抑制第三方库的冗长日志（避免 spikeinterface 内部日志淹没 pipeline 日志）：
   logging.getLogger("spikeinterface").setLevel(logging.WARNING)
   logging.getLogger("probeinterface").setLevel(logging.WARNING)
```

---

## 6. StageLogger 实现步骤

### 6.1 `__init__(stage_name, probe_id)`

```
self._stage_name = stage_name
self._probe_id = probe_id
self._start_time: float | None = None
self._logger = get_logger(__name__).bind(stage=stage_name, probe_id=probe_id)
```

### 6.2 `start()`

```
import time
self._start_time = time.monotonic()
self._logger.info("stage_start")
```

### 6.3 `complete(data)`

```
elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
extra = data or {}
self._logger.info("stage_complete", status="completed", elapsed_s=round(elapsed, 3), **extra)
```

### 6.4 `error(error, data)`

```
import traceback
elapsed = time.monotonic() - self._start_time if self._start_time else 0.0
tb = traceback.format_exc()
extra = data or {}
self._logger.error(
    "stage_failed",
    status="failed",
    elapsed_s=round(elapsed, 3),
    error=str(error),
    traceback=tb,
    **extra,
)
```

### 6.5 `info(message, **kwargs)`

```
self._logger.info(message, **kwargs)
```

---

## 7. 与 BaseStage 的集成模式

`stages/base.py` 中的 `BaseStage` 使用 `StageLogger` 和 `get_logger`：

```python
class BaseStage:
    def __init__(self, session: Session, ...):
        self.logger = StageLogger(self.STAGE_NAME)
        # 或 per-probe：
        # self.logger = StageLogger(self.STAGE_NAME, probe_id)

    def _report_progress(self, message: str, fraction: float) -> None:
        if self.progress_callback:
            self.progress_callback(message, fraction)
        self.logger.info(message, progress=fraction)
```

---

## 8. 测试要点

以下行为**每条都必须有对应的单元测试**：

1. `setup_logging(log_path)` — 创建日志文件（父目录已存在）
2. `setup_logging(log_path)` — 父目录不存在时 raise OSError（不自动创建）
3. `get_logger("foo")` — 返回 BoundLogger 实例，调用 `.info()` 不抛异常
4. `StageLogger.start()` — 日志文件中写入一条包含 `"event": "stage_start"` 的 JSON 行
5. `StageLogger.complete({"n_units": 42})` — 日志中含 `"event": "stage_complete"`, `"elapsed_s": float`, `"n_units": 42`
6. `StageLogger.complete()` 在 `start()` 未调用时 — `elapsed_s` 为 0，不 raise
7. `StageLogger.error(exc)` — 日志中含 `"event": "stage_failed"`, `"error": str`, `"traceback": str`
8. `StageLogger.info("msg", progress=0.5)` — 日志中含 `"event": "msg"`, `"progress": 0.5`
9. 日志文件中每行均为有效 JSON（可被 `json.loads` 解析）
10. `stage` 和 `probe_id` 字段在所有 StageLogger 输出的行中均存在
11. `setup_logging` 调用两次（如 GUI 重载场景）— 不产生重复 handler（handler 数量不翻倍）
12. 第三方库日志（spikeinterface）— 在日志文件中 level 为 WARNING 以上才出现

---

## 9. 与其他模块的接口

| 调用方 | 调用方式 |
|--------|---------|
| `core/session.py` (`SessionManager.create`) | `setup_logging(session.log_path)` |
| `cli/main.py` | `setup_logging(log_path, level=logging.DEBUG if verbose else logging.INFO)` |
| `stages/base.py` | `get_logger(__name__)` 和 `StageLogger(stage_name, probe_id)` |
| 所有 `stages/*.py`、`io/*.py`、`core/*.py` | `get_logger(__name__)` 获取模块级 logger |

---

## 10. 与现有 skeleton 的差异（实现时需同步修改）

| 差异 | skeleton 现状 | spec 要求 |
|------|--------------|----------|
| `setup_logging` 双输出 | 未定义 | FileHandler（JSON）+ StreamHandler（stderr，人类可读） |
| `StageLogger._start_time` | skeleton 无此字段 | 新增，`start()` 写入，`complete()` / `error()` 读取 |
| 第三方库日志抑制 | 未定义 | `setup_logging` 中设置 spikeinterface / probeinterface 为 WARNING |
| `StageLogger.error()` 的 traceback | 未定义 | `traceback.format_exc()` 写入 `traceback` 字段 |
| `setup_logging` 重复调用 | 未定义 | 清除已有 handler 再添加新 handler，防止重复输出 |
