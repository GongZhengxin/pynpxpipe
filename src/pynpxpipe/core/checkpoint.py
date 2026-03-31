"""Checkpoint read/write for pipeline stage resumption.

Each stage writes a JSON checkpoint file upon successful completion so that
a re-run can skip already-completed stages. No UI dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


class CheckpointManager:
    """Manages per-stage checkpoint files under {output_dir}/checkpoints/.

    Checkpoint file naming convention:
        - Stage-level:  checkpoints/{stage_name}.json
        - Probe-level:  checkpoints/{stage_name}_{probe_id}.json

    The checkpoint JSON always contains at least:
        ``{"stage": str, "completed_at": ISO8601, "status": "completed"|"failed"}``
    """

    def __init__(self, output_dir: Path) -> None:
        """Initialize the checkpoint manager.

        Args:
            output_dir: Session output directory. Checkpoint files are stored
                under ``{output_dir}/checkpoints/``.
        """
        raise NotImplementedError("TODO")

    def is_complete(self, stage_name: str, probe_id: str | None = None) -> bool:
        """Return True if the given stage (and optional probe) has a completed checkpoint.

        Args:
            stage_name: Name of the pipeline stage (e.g. "discover", "sort").
            probe_id: Probe identifier (e.g. "imec0"). Pass None for stage-level checks.

        Returns:
            True if a checkpoint with ``status == "completed"`` exists, False otherwise.
        """
        raise NotImplementedError("TODO")

    def mark_complete(
        self,
        stage_name: str,
        data: dict[str, Any],
        probe_id: str | None = None,
    ) -> None:
        """Write a completed checkpoint for a stage.

        Args:
            stage_name: Name of the pipeline stage.
            data: Stage-specific payload (e.g. ``{"n_units": 142, "sorting_path": "..."}``).
            probe_id: Probe identifier for probe-level checkpoints, or None for stage-level.

        Raises:
            OSError: If the checkpoint file cannot be written.
        """
        raise NotImplementedError("TODO")

    def mark_failed(
        self,
        stage_name: str,
        error: str,
        probe_id: str | None = None,
    ) -> None:
        """Write a failed checkpoint for a stage.

        Args:
            stage_name: Name of the pipeline stage.
            error: String representation of the exception.
            probe_id: Probe identifier for probe-level checkpoints, or None.

        Raises:
            OSError: If the checkpoint file cannot be written.
        """
        raise NotImplementedError("TODO")

    def read(self, stage_name: str, probe_id: str | None = None) -> dict[str, Any] | None:
        """Read a checkpoint file and return its contents.

        Args:
            stage_name: Name of the pipeline stage.
            probe_id: Probe identifier, or None for stage-level.

        Returns:
            The parsed checkpoint dict, or None if no checkpoint file exists.
        """
        raise NotImplementedError("TODO")

    def clear(self, stage_name: str, probe_id: str | None = None) -> None:
        """Delete a checkpoint file (e.g. to force a stage to re-run).

        Args:
            stage_name: Name of the pipeline stage.
            probe_id: Probe identifier, or None for stage-level.
        """
        raise NotImplementedError("TODO")

    def list_completed_stages(self) -> list[str]:
        """Return a list of stage names that have completed checkpoints.

        Returns:
            List of stage names (e.g. ``["discover", "preprocess"]``).
        """
        raise NotImplementedError("TODO")
