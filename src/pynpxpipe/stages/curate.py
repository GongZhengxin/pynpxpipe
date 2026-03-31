"""Curate stage: quality metric computation and unit filtering per probe.

Uses SpikeInterface quality_metrics extension. No UI dependencies.
"""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class CurateStage(BaseStage):
    """Computes quality metrics and filters units for each probe.

    Uses SpikeInterface's built-in quality metrics (isi_violation_ratio,
    amplitude_cutoff, presence_ratio, snr). Thresholds are read from
    config.pipeline.curation — never hardcoded.

    Replaces the legacy Bombcell-based quality control.
    """

    STAGE_NAME = "curate"

    def __init__(
        self,
        session: "Session",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the curate stage.

        Args:
            session: Active pipeline session with sorting results available.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        raise NotImplementedError("TODO")

    def run(self) -> None:
        """Compute quality metrics and curate all probes serially.

        For each probe (skipping those with a completed checkpoint):
        1. Load sorting result.
        2. Create lightweight SortingAnalyzer (quality metrics only).
        3. Compute quality metrics.
        4. Filter units by configured thresholds.
        5. Save curated sorting and quality_metrics.csv.
        6. Write per-probe checkpoint; del analyzer + gc.collect().

        Note: An empty curated sorting (0 good units) is NOT an error. A warning
        is logged and processing continues with the empty sorting.
        """
        raise NotImplementedError("TODO")

    def _curate_probe(self, probe_id: str) -> tuple[int, int]:
        """Run curation for a single probe.

        Args:
            probe_id: Probe identifier (e.g. "imec0").

        Returns:
            Tuple (n_units_before, n_units_after).
        """
        raise NotImplementedError("TODO")
