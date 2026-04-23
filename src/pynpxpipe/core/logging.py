"""Structured logging setup for pynpxpipe.

All pipeline stages write JSON Lines logs via structlog. No print() calls anywhere
in business logic — all user-visible information goes through this module.
No UI dependencies.
"""

from __future__ import annotations

import logging
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import structlog


def _shared_processors() -> list:
    """Return the processor chain shared between file and console formatters."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=False),
    ]


def setup_logging(log_path: Path, level: int = logging.INFO) -> None:
    """Configure structlog to write JSON Lines to log_path and human-readable text to stderr.

    Must be called once before any stage runs, typically in SessionManager.create()
    or at CLI entry point.

    Args:
        log_path: Path to the JSON Lines log file. Parent directory must exist.
        level: Python logging level (default INFO).

    Raises:
        OSError: If log_path cannot be opened for writing (e.g. parent dir missing).
    """
    # Validate parent dir exists — raise OSError early if not
    log_path = Path(log_path)
    if not log_path.parent.exists():
        raise OSError(f"Log file parent directory does not exist: {log_path.parent}")

    # Build formatters
    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
        foreign_pre_chain=_shared_processors(),
    )
    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=False),
        ],
        foreign_pre_chain=_shared_processors(),
    )

    # Build handlers
    file_handler = logging.FileHandler(log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(json_formatter)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(console_formatter)

    # Configure root logger — clear existing handlers to prevent doubling on
    # repeated calls (e.g., GUI reload scenario).
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stderr_handler)
    root.setLevel(level)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,  # False keeps test isolation clean
    )

    # Suppress verbose third-party library logging (allow INFO for spikeinterface
    # so progress messages reach the UI log handler)
    logging.getLogger("spikeinterface").setLevel(logging.INFO)
    logging.getLogger("probeinterface").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger with the given name.

    All stage classes call this at init time to obtain their logger.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A structlog BoundLogger that outputs JSON Lines to the configured handlers.
    """
    return structlog.get_logger(name)


class StageLogger:
    """Convenience wrapper for structured stage-level logging.

    Automatically adds ``stage`` and ``probe_id`` context keys to every log call,
    and records wall-clock timing for each stage run.

    Example::

        logger = StageLogger("sort", "imec0")
        logger.start()
        # ... do work ...
        logger.complete({"n_units": 142})
    """

    def __init__(self, stage_name: str, probe_id: str | None = None) -> None:
        """Initialize the stage logger.

        Args:
            stage_name: Name of the pipeline stage (e.g. "sort").
            probe_id: Probe identifier if this is a per-probe log context, or None.
        """
        self._stage_name = stage_name
        self._probe_id = probe_id
        self._start_time: float | None = None
        self._logger = get_logger(__name__).bind(
            stage=stage_name,
            probe_id=probe_id,
        )

    def start(self) -> None:
        """Log stage start with timestamp. Records start time for elapsed calculation."""
        self._start_time = time.monotonic()
        self._logger.info("stage_start")

    def complete(self, data: dict[str, Any] | None = None) -> None:
        """Log stage completion with elapsed time.

        Args:
            data: Optional dict of stage-specific summary fields to include in the log entry.
        """
        elapsed = time.monotonic() - self._start_time if self._start_time is not None else 0.0
        extra = data or {}
        self._logger.info(
            "stage_complete",
            status="completed",
            elapsed_s=round(elapsed, 3),
            **extra,
        )

    def error(self, error: Exception, data: dict[str, Any] | None = None) -> None:
        """Log stage failure with traceback.

        Args:
            error: The exception that caused the failure.
            data: Optional dict of additional context fields.
        """
        elapsed = time.monotonic() - self._start_time if self._start_time is not None else 0.0
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

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an informational message with stage context.

        Args:
            message: Human-readable message string.
            **kwargs: Additional structured fields (e.g. ``progress=0.5``).
        """
        self._logger.info(message, **kwargs)
