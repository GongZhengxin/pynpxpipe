"""Pipeline runner: orchestrates stage execution with checkpoint-aware skip logic.

Supports serial execution and optional parallel multi-probe processing.
No UI dependencies.
"""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session
    from pynpxpipe.core.config import PipelineConfig, SortingConfig


STAGE_ORDER = [
    "discover",
    "preprocess",
    "sort",
    "synchronize",
    "curate",
    "postprocess",
    "export",
]


class PipelineRunner:
    """Orchestrates the full pipeline from discover through export.

    Checks checkpoints before each stage. Stages with a completed checkpoint
    are automatically skipped, enabling resume after interruption.

    The sort stage always runs serially. Other stages respect
    ``config.pipeline.parallel.enabled`` for optional multi-probe parallelism
    (when enabled, uses ``concurrent.futures.ProcessPoolExecutor``).
    """

    def __init__(
        self,
        session: "Session",
        pipeline_config: "PipelineConfig",
        sorting_config: "SortingConfig",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the pipeline runner.

        Args:
            session: Active session (may be newly created or loaded from checkpoint).
            pipeline_config: Full pipeline configuration.
            sorting_config: Sorting-specific configuration.
            progress_callback: Optional GUI/progress callback propagated to all stages.
        """
        raise NotImplementedError("TODO")

    def run(self, stages: list[str] | None = None) -> None:
        """Run the pipeline, optionally restricted to a subset of stages.

        Stages are executed in the canonical order defined by STAGE_ORDER.
        Each stage is skipped automatically if its checkpoint exists.

        Args:
            stages: List of stage names to execute (e.g. ``["sort", "curate"]``).
                If None, all stages are run.

        Raises:
            ValueError: If an unknown stage name is provided.
            StageError: Propagated from any failing stage.
        """
        raise NotImplementedError("TODO")

    def run_stage(self, stage_name: str) -> None:
        """Instantiate and run a single stage by name.

        Args:
            stage_name: Name of the stage to run (must be in STAGE_ORDER).

        Raises:
            ValueError: If stage_name is not recognized.
            StageError: Propagated from the stage's run() method.
        """
        raise NotImplementedError("TODO")

    def get_status(self) -> dict[str, str]:
        """Return the completion status of all stages.

        Returns:
            Dict mapping stage name to "completed", "failed", or "pending".
        """
        raise NotImplementedError("TODO")
