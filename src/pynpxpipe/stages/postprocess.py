"""Postprocess stage: full SortingAnalyzer computation and SLAY scoring.

Computes waveforms, templates, unit locations, and SLAY scores per probe.
No UI dependencies.
"""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    import numpy as np
    from pynpxpipe.core.session import Session


class PostprocessStage(BaseStage):
    """Computes SortingAnalyzer extensions and SLAY scores for each probe.

    Processing per probe:
    - random_spikes → waveforms → templates → unit_locations → template_similarity
    - SLAY (Stimulus-Locked Activity Yield): requires behavior_events from synchronize stage

    SLAY assesses each unit's reliability of response to stimulus onset.
    SLAY scores are stored in the analyzer as a custom extension and later
    written to the NWB units table.
    """

    STAGE_NAME = "postprocess"

    def __init__(
        self,
        session: "Session",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the postprocess stage.

        Args:
            session: Active pipeline session with curated sortings available.
                The synchronize stage must have completed (behavior_events.parquet needed).
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        raise NotImplementedError("TODO")

    def run(self) -> None:
        """Compute all postprocessing extensions for all probes serially.

        For each probe (skipping those with a completed checkpoint):
        1. Create full SortingAnalyzer with curated sorting + preprocessed recording.
        2. Compute extension pipeline: random_spikes → waveforms → templates →
           unit_locations → template_similarity.
        3. Compute SLAY scores for all units.
        4. Save analyzer to {output_dir}/postprocessed/{probe_id}/.
        5. Write per-probe checkpoint; del analyzer + gc.collect().

        Raises:
            PostprocessError: If waveform extraction OOM cannot be resolved by
                halving chunk_duration.
        """
        raise NotImplementedError("TODO")

    def _postprocess_probe(self, probe_id: str) -> None:
        """Run full postprocessing for a single probe.

        Args:
            probe_id: Probe identifier (e.g. "imec0").

        Raises:
            PostprocessError: On unrecoverable memory or computation error.
        """
        raise NotImplementedError("TODO")

    def _compute_slay(
        self,
        spike_times: "np.ndarray",
        stim_onset_times: "np.ndarray",
        pre_s: float = 0.05,
        post_s: float = 0.30,
    ) -> float:
        """Compute the SLAY score for a single unit.

        SLAY (Stimulus-Locked Activity Yield) measures the reliability of a unit's
        response to stimulus onset across trials. Higher scores indicate more
        consistent peri-stimulus responses.

        Args:
            spike_times: All spike times for this unit in seconds (NIDQ clock).
            stim_onset_times: Stimulus onset times in seconds from behavior_events.
            pre_s: Pre-stimulus window in seconds for baseline.
            post_s: Post-stimulus window in seconds for response window.

        Returns:
            SLAY score as a float in [0, 1]. Returns NaN if fewer than 5 trials
            have spikes in the analysis window.
        """
        raise NotImplementedError("TODO")
