"""Base class for all pipeline stages.

Provides checkpoint integration, structured logging, and progress callbacks.
All stage subclasses must inherit from BaseStage. No UI dependencies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from pynpxpipe.core.checkpoint import CheckpointManager
from pynpxpipe.core.logging import get_logger

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class BaseStage(ABC):
    """Abstract base class for pipeline stages.

    Each stage subclass implements ``run()`` and calls ``_report_progress()``
    at key processing milestones. Checkpoint logic and structured logging are
    provided here so stage subclasses stay focused on domain logic.

    Attributes:
        STAGE_NAME: Class-level constant, override in each subclass (e.g. "sort").
    """

    STAGE_NAME: str = ""

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the stage with session state and optional progress callback.

        Args:
            session: The active pipeline session providing config, probes, and paths.
            progress_callback: Optional callable ``(message, fraction)`` where
                ``fraction`` is in [0.0, 1.0]. Pass None in CLI mode (progress
                written to log only). Pass a GUI update function in GUI mode.

        Raises:
            ValueError: If STAGE_NAME is not set on the subclass.
        """
        if not self.STAGE_NAME:
            raise ValueError(
                f"{type(self).__name__}.STAGE_NAME must be set to a non-empty string"
            )
        self.session = session
        self.progress_callback = progress_callback
        self.logger = get_logger(f"pynpxpipe.stages.{self.STAGE_NAME}")
        self.checkpoint_manager = CheckpointManager(session.output_dir)

    @abstractmethod
    def run(self) -> None:
        """Execute this stage.

        Subclasses implement the full stage logic here. Should call
        ``_report_progress()`` at meaningful checkpoints and
        ``_write_checkpoint()`` / ``_write_probe_checkpoint()`` on completion.

        Raises:
            StageError: On unrecoverable failure.
        """
        ...

    def _report_progress(self, message: str, fraction: float) -> None:
        """Report stage progress to the callback and log.

        Args:
            message: Human-readable progress message.
            fraction: Completion fraction in [0.0, 1.0].
        """
        if self.progress_callback:
            self.progress_callback(message, fraction)
        self.logger.info(message, progress=fraction)

    def _is_complete(self, probe_id: str | None = None) -> bool:
        """Check whether this stage (or a per-probe sub-stage) has a completed checkpoint.

        Args:
            probe_id: Probe identifier for per-probe stages, or None for stage-level.

        Returns:
            True if the checkpoint exists and has status "completed".
        """
        return self.checkpoint_manager.is_complete(self.STAGE_NAME, probe_id)

    def _write_checkpoint(self, data: dict, probe_id: str | None = None) -> None:
        """Write a completed checkpoint for this stage.

        Args:
            data: Stage-specific payload to include in the checkpoint JSON.
            probe_id: Probe identifier for per-probe checkpoints, or None.
        """
        self.checkpoint_manager.mark_complete(self.STAGE_NAME, data, probe_id)

    def _write_failed_checkpoint(self, error: Exception, probe_id: str | None = None) -> None:
        """Write a failed checkpoint recording the error message.

        Args:
            error: The exception that caused the failure.
            probe_id: Probe identifier for per-probe checkpoints, or None.
        """
        self.checkpoint_manager.mark_failed(self.STAGE_NAME, str(error), probe_id)
