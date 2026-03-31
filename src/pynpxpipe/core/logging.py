"""Structured logging setup for pynpxpipe.

All pipeline stages write JSON Lines logs via structlog. No print() calls anywhere
in business logic — all user-visible information goes through this module.
No UI dependencies.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import structlog


def setup_logging(log_path: Path, level: int = logging.INFO) -> None:
    """Configure structlog to write JSON Lines to log_path and human-readable text to stderr.

    Must be called once before any stage runs, typically in SessionManager.create()
    or at CLI entry point.

    Args:
        log_path: Path to the JSON Lines log file. Parent directory must exist.
        level: Python logging level (default INFO).

    Raises:
        OSError: If log_path cannot be opened for writing.
    """
    raise NotImplementedError("TODO")


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog bound logger with the given name.

    All stage classes call this at init time to obtain their logger.

    Args:
        name: Logger name, typically ``__name__`` of the calling module.

    Returns:
        A structlog BoundLogger that outputs JSON Lines to the configured handlers.
    """
    raise NotImplementedError("TODO")


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
        raise NotImplementedError("TODO")

    def start(self) -> None:
        """Log stage start with timestamp. Records start time for elapsed calculation."""
        raise NotImplementedError("TODO")

    def complete(self, data: dict[str, Any] | None = None) -> None:
        """Log stage completion with elapsed time.

        Args:
            data: Optional dict of stage-specific summary fields to include in the log entry.
        """
        raise NotImplementedError("TODO")

    def error(self, error: Exception, data: dict[str, Any] | None = None) -> None:
        """Log stage failure with traceback.

        Args:
            error: The exception that caused the failure.
            data: Optional dict of additional context fields.
        """
        raise NotImplementedError("TODO")

    def info(self, message: str, **kwargs: Any) -> None:
        """Log an informational message with stage context.

        Args:
            message: Human-readable message string.
            **kwargs: Additional structured fields (e.g. ``progress=0.5``).
        """
        raise NotImplementedError("TODO")
