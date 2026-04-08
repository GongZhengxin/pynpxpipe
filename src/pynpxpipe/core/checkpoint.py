"""Checkpoint read/write for pipeline stage resumption.

Each stage writes a JSON checkpoint file upon successful completion so that
a re-run can skip already-completed stages. No UI dependencies.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pynpxpipe.core.errors import CheckpointError
from pynpxpipe.core.logging import get_logger


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

        Raises:
            OSError: If the checkpoints/ directory cannot be created.
        """
        self._checkpoints_dir = output_dir / "checkpoints"
        self._checkpoints_dir.mkdir(parents=True, exist_ok=True)
        self._logger = get_logger(__name__)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _checkpoint_path(self, stage_name: str, probe_id: str | None) -> Path:
        """Return the canonical path for a checkpoint file.

        Args:
            stage_name: Pipeline stage name.
            probe_id: Probe identifier, or None for stage-level.

        Returns:
            Absolute path to the checkpoint JSON file.
        """
        if probe_id is None:
            return self._checkpoints_dir / f"{stage_name}.json"
        return self._checkpoints_dir / f"{stage_name}_{probe_id}.json"

    def _atomic_write(self, path: Path, data: dict[str, Any], stage_name: str) -> None:
        """Write data to path atomically via a temporary file.

        Writes to ``{path}.tmp`` first, then renames to ``path``.
        Cleans up the temporary file if the rename fails.

        Args:
            path: Target checkpoint file path.
            data: Dict to serialise as JSON.
            stage_name: Stage name used in CheckpointError if write fails.

        Raises:
            CheckpointError: If writing or renaming the temporary file fails.
        """
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise CheckpointError(stage_name, path, str(exc)) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_complete(self, stage_name: str, probe_id: str | None = None) -> bool:
        """Return True if the given stage (and optional probe) has a completed checkpoint.

        Args:
            stage_name: Name of the pipeline stage (e.g. "discover", "sort").
            probe_id: Probe identifier (e.g. "imec0"). Pass None for stage-level checks.

        Returns:
            True if a checkpoint with ``status == "completed"`` exists, False otherwise.

        Raises:
            CheckpointError: If the checkpoint file exists but cannot be parsed (corrupt JSON).
        """
        path = self._checkpoint_path(stage_name, probe_id)
        if not path.exists():
            return False
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise CheckpointError(stage_name, path, f"corrupt checkpoint: {exc}") from exc
        return data.get("status") == "completed"

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
            CheckpointError: If the checkpoint file cannot be written.
        """
        path = self._checkpoint_path(stage_name, probe_id)
        payload: dict[str, Any] = {"stage": stage_name}
        if probe_id is not None:
            payload["probe_id"] = probe_id
        payload["status"] = "completed"
        payload["completed_at"] = datetime.now(UTC).isoformat()
        payload.update(data)
        self._atomic_write(path, payload, stage_name)
        self._logger.debug(
            "checkpoint written",
            stage=stage_name,
            probe_id=probe_id,
            status="completed",
        )

    def mark_failed(
        self,
        stage_name: str,
        error: str,
        probe_id: str | None = None,
    ) -> None:
        """Write a failed checkpoint for a stage.

        If writing the checkpoint itself fails, logs the error and returns
        without raising — this avoids masking the original stage exception.

        Args:
            stage_name: Name of the pipeline stage.
            error: String representation of the exception.
            probe_id: Probe identifier for probe-level checkpoints, or None.
        """
        path = self._checkpoint_path(stage_name, probe_id)
        payload: dict[str, Any] = {"stage": stage_name}
        if probe_id is not None:
            payload["probe_id"] = probe_id
        payload["status"] = "failed"
        payload["failed_at"] = datetime.now(UTC).isoformat()
        payload["error"] = str(error)
        try:
            self._atomic_write(path, payload, stage_name)
        except (CheckpointError, OSError) as exc:
            self._logger.error(
                "failed to write failed checkpoint",
                stage=stage_name,
                probe_id=probe_id,
                error=str(exc),
            )
            return  # do NOT re-raise; avoid masking the original stage exception
        self._logger.debug(
            "checkpoint written",
            stage=stage_name,
            probe_id=probe_id,
            status="failed",
        )

    def read(self, stage_name: str, probe_id: str | None = None) -> dict[str, Any] | None:
        """Read a checkpoint file and return its contents.

        Args:
            stage_name: Name of the pipeline stage.
            probe_id: Probe identifier, or None for stage-level.

        Returns:
            The parsed checkpoint dict, or None if no checkpoint file exists.

        Raises:
            CheckpointError: If the file exists but JSON is corrupt or unreadable.
        """
        path = self._checkpoint_path(stage_name, probe_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise CheckpointError(stage_name, path, f"corrupt checkpoint: {exc}") from exc

    def clear(self, stage_name: str, probe_id: str | None = None) -> None:
        """Delete a checkpoint file (e.g. to force a stage to re-run).

        Silently returns if the file does not exist.

        Args:
            stage_name: Name of the pipeline stage.
            probe_id: Probe identifier, or None for stage-level.
        """
        path = self._checkpoint_path(stage_name, probe_id)
        path.unlink(missing_ok=True)

    def list_completed_stages(self) -> list[str]:
        """Return a list of stage names that have completed checkpoints.

        Scans the checkpoints/ directory, reads each JSON file, and collects
        stage names from files with ``status == "completed"``. Deduplicates
        so that multiple probe-level checkpoints for the same stage contribute
        only one entry.

        Returns:
            List of unique stage names (e.g. ``["discover", "preprocess"]``).
        """
        completed: list[str] = []
        for filepath in self._checkpoints_dir.glob("*.json"):
            try:
                data = json.loads(filepath.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if data.get("status") != "completed":
                continue
            stage = data.get("stage")
            if stage and stage not in completed:
                completed.append(stage)
        return completed
