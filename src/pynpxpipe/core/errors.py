from __future__ import annotations

from pathlib import Path


class PynpxpipeError(Exception):
    """Base class for all pynpxpipe custom exceptions."""


class ConfigError(PynpxpipeError):
    """Raised when a configuration field value is invalid or structurally wrong.

    Attributes:
        field: Dot-separated path to the offending field, e.g. "resources.n_jobs"
        value: The invalid value.
        reason: Human-readable explanation of why the value is invalid.
    """

    def __init__(self, field: str, value: object, reason: str) -> None:
        self.field = field
        self.value = value
        self.reason = reason
        super().__init__(f"ConfigError [{field}={value!r}]: {reason}")


class CheckpointError(PynpxpipeError):
    """Raised when a checkpoint file cannot be read or written.

    Attributes:
        stage: Name of the stage that triggered the error (e.g. "sort").
        path: Path to the checkpoint file.
        reason: Human-readable explanation of the failure.
    """

    def __init__(self, stage: str, path: Path, reason: str) -> None:
        self.stage = stage
        self.path = path
        self.reason = reason
        super().__init__(f"CheckpointError [{stage}] {path}: {reason}")
