"""Pipeline runner: orchestrates stage execution with checkpoint-aware skip logic.

Supports serial execution and optional parallel multi-probe processing.
No UI dependencies.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from pynpxpipe.core.checkpoint import CheckpointManager
from pynpxpipe.core.resources import ResourceDetector
from pynpxpipe.pipelines.constants import PER_PROBE_STAGES, STAGE_ORDER

if TYPE_CHECKING:
    from pynpxpipe.core.config import PipelineConfig, SortingConfig
    from pynpxpipe.core.session import Session

# Re-export for backward compat (tests, CLI, etc.)
__all__ = ["PipelineRunner", "STAGE_ORDER"]

# Internal alias
_PER_PROBE_STAGES = PER_PROBE_STAGES


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
        session: Session,
        pipeline_config: PipelineConfig,
        sorting_config: SortingConfig,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the pipeline runner.

        If any resource parameter is "auto", ResourceDetector is invoked once at
        init and all "auto" fields are replaced with recommended values.

        Args:
            session: Active session (may be newly created or loaded from checkpoint).
            pipeline_config: Full pipeline configuration.
            sorting_config: Sorting-specific configuration.
            progress_callback: Optional GUI/progress callback propagated to all stages.
        """
        self.session = session
        self.pipeline_config = pipeline_config
        self.sorting_config = sorting_config
        self.progress_callback = progress_callback
        self._checkpoint = CheckpointManager(session.output_dir)

        # Resolve "auto" resource values via ResourceDetector
        needs_auto = (
            pipeline_config.resources.n_jobs == "auto"
            or pipeline_config.resources.chunk_duration == "auto"
            or pipeline_config.parallel.max_workers == "auto"
            or sorting_config.sorter.params.batch_size == "auto"
        )
        if needs_auto:
            detector = ResourceDetector(self.session.session_dir, self.session.output_dir)
            profile = detector.detect()
            rec = detector.recommend(profile, session.probes or None)
            if pipeline_config.resources.n_jobs == "auto":
                pipeline_config.resources.n_jobs = rec.n_jobs
            if pipeline_config.resources.chunk_duration == "auto":
                pipeline_config.resources.chunk_duration = rec.chunk_duration
            if pipeline_config.parallel.max_workers == "auto":
                pipeline_config.parallel.max_workers = rec.max_workers
            if sorting_config.sorter.params.batch_size == "auto":
                sorting_config.sorter.params.batch_size = rec.sorting_batch_size

        # Inject resolved config into session for stages to read
        session.config = pipeline_config

        _log = logging.getLogger(__name__)
        _log.info(
            "Resolved resources: n_jobs=%s, chunk_duration=%s, max_workers=%s, sorting_batch_size=%s",
            pipeline_config.resources.n_jobs,
            pipeline_config.resources.chunk_duration,
            pipeline_config.parallel.max_workers,
            sorting_config.sorter.params.batch_size,
        )

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
        if stages is not None:
            unknown = [s for s in stages if s not in STAGE_ORDER]
            if unknown:
                raise ValueError(f"Unknown stage(s): {unknown}")
            to_run = [s for s in STAGE_ORDER if s in stages]
        else:
            to_run = list(STAGE_ORDER)

        for stage_name in to_run:
            self.run_stage(stage_name)

    def run_stage(self, stage_name: str) -> None:
        """Instantiate and run a single stage by name.

        Args:
            stage_name: Name of the stage to run (must be in STAGE_ORDER).

        Raises:
            ValueError: If stage_name is not recognized.
            StageError: Propagated from the stage's run() method.
        """
        if stage_name not in STAGE_ORDER:
            raise ValueError(f"Unknown stage: {stage_name!r}")

        stage = self._build_stage(stage_name)
        stage.run()

    def get_status(self) -> dict[str, str]:
        """Return the completion status of all stages.

        For per-probe stages (preprocess, sort, curate, postprocess), returns:
          - "completed" if all probes have completed checkpoints
          - "partial (N/M probes)" if some probes are done
          - "failed" if any checkpoint has status=failed
          - "pending" if no checkpoints exist

        Returns:
            Dict mapping stage name to status string.
        """
        status: dict[str, str] = {}
        for stage_name in STAGE_ORDER:
            status[stage_name] = self._stage_status(stage_name)
        return status

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_stage(self, stage_name: str):  # noqa: ANN202
        """Instantiate the correct stage class with appropriate args."""
        # Lazy imports — keeps the module importable without pulling in the
        # full scientific stack (spikeinterface, pynwb, …).  The UI layer
        # only needs STAGE_ORDER from constants.py.
        from pynpxpipe.stages.curate import CurateStage
        from pynpxpipe.stages.discover import DiscoverStage
        from pynpxpipe.stages.export import ExportStage
        from pynpxpipe.stages.merge import MergeStage
        from pynpxpipe.stages.postprocess import PostprocessStage
        from pynpxpipe.stages.preprocess import PreprocessStage
        from pynpxpipe.stages.sort import SortStage
        from pynpxpipe.stages.synchronize import SynchronizeStage

        cb = self.progress_callback
        s = self.session
        if stage_name == "discover":
            return DiscoverStage(s, cb)
        if stage_name == "preprocess":
            return PreprocessStage(s, self.pipeline_config, cb)
        if stage_name == "sort":
            return SortStage(s, self.sorting_config, cb)
        if stage_name == "merge":
            return MergeStage(s, cb)
        if stage_name == "synchronize":
            return SynchronizeStage(s, cb)
        if stage_name == "curate":
            return CurateStage(s, cb)
        if stage_name == "postprocess":
            return PostprocessStage(s, cb)
        # export
        return ExportStage(s, cb)

    def _stage_status(self, stage_name: str) -> str:
        """Determine status string for one stage."""
        cp_dir = self.session.output_dir / "checkpoints"

        # Check stage-level checkpoint first
        stage_cp = cp_dir / f"{stage_name}.json"
        if stage_cp.exists():
            try:
                data = json.loads(stage_cp.read_text(encoding="utf-8"))
                return data.get("status", "pending")
            except Exception:  # noqa: BLE001
                pass

        if stage_name not in _PER_PROBE_STAGES or not self.session.probes:
            return "pending"

        # Count per-probe checkpoints
        n_probes = len(self.session.probes)
        completed = 0
        for probe in self.session.probes:
            probe_cp = cp_dir / f"{stage_name}_{probe.probe_id}.json"
            if probe_cp.exists():
                try:
                    data = json.loads(probe_cp.read_text(encoding="utf-8"))
                    if data.get("status") == "completed":
                        completed += 1
                    elif data.get("status") == "failed":
                        return "failed"
                except Exception:  # noqa: BLE001
                    pass

        if completed == 0:
            return "pending"
        if completed == n_probes:
            return "completed"
        return f"partial ({completed}/{n_probes} probes)"
