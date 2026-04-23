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


class DiscoverError(PynpxpipeError):
    """Raised when the session directory does not contain expected SpikeGLX data.

    Examples: no imec probe directories found, NIDQ files missing.
    """


class ProbeDeclarationMismatchError(DiscoverError):
    """Raised when session.probe_plan does not match probes found on disk.

    Attributes:
        declared: Set of probe_ids declared by the user via probe_plan.
        found: Set of probe_ids actually discovered in session_dir.
        missing_on_disk: declared - found (user declared but disk lacks).
        unexpected_on_disk: found - declared (disk has but user did not declare).
    """

    def __init__(self, declared: set[str], found: set[str]) -> None:
        self.declared = declared
        self.found = found
        self.missing_on_disk = declared - found
        self.unexpected_on_disk = found - declared
        parts = []
        if self.missing_on_disk:
            parts.append(f"declared but not on disk: {sorted(self.missing_on_disk)}")
        if self.unexpected_on_disk:
            parts.append(f"on disk but not declared: {sorted(self.unexpected_on_disk)}")
        super().__init__(
            f"probe_plan mismatch — {'; '.join(parts)}. "
            f"declared={sorted(declared)}, found={sorted(found)}"
        )


class PreprocessError(PynpxpipeError):
    """Raised when preprocessing fails for a probe.

    Examples: Zarr save fails (disk full, permissions), unsupported motion
    correction method.
    """


class SortError(PynpxpipeError):
    """Raised when spike sorting fails for a probe.

    Examples: CUDA out-of-memory, sorter not installed, unknown mode,
    import path missing or corrupted.
    """


class SyncError(PynpxpipeError):
    """Raised when time synchronization between data streams fails.

    Examples: sync pulse count mismatch, alignment residual exceeds threshold,
    invalid sync times (NaN/Inf), insufficient sync pulses.
    """


class CurateError(PynpxpipeError):
    """Raised when quality metric computation or unit filtering fails for a probe.

    Examples: sorted or preprocessed recording cannot be loaded, SortingAnalyzer
    computation fails.
    """


class PostprocessError(PynpxpipeError):
    """Raised when post-processing (SLAY score computation) fails for a probe.

    Examples: waveform/template computation fails, eye data missing for validation.
    """


class ExportError(PynpxpipeError):
    """Raised when writing the output NWB file fails.

    Examples: NWBWriter error, written file cannot be read back (HDF5 corrupt),
    behavior_events.parquet missing.
    """


class MergeError(PynpxpipeError):
    """Raised when auto-merge fails for a probe.

    Examples: sorted SortingAnalyzer cannot be loaded, auto_merge() raises.
    """
