"""Curate stage: quality metric computation and unit filtering per probe.

Uses SpikeInterface quality_metrics extension. No UI dependencies.
"""

from __future__ import annotations

import gc
from collections.abc import Callable
from typing import TYPE_CHECKING

import spikeinterface.core as si

from pynpxpipe.core.errors import CurateError
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class CurateStage(BaseStage):
    """Computes quality metrics and filters units for each probe.

    Uses SpikeInterface's built-in quality metrics (isi_violation_ratio,
    amplitude_cutoff, presence_ratio, snr). Thresholds are read from
    config.pipeline.curation — never hardcoded.

    SortingAnalyzer uses format="memory" (no disk write needed for curation).
    Curated sorting saved as binary_folder. quality_metrics.csv saved for
    all units (pre-filter) for manual inspection.

    Zero units after curation: WARNING, not error (pipeline continues).

    Raises:
        CurateError: If sorting or recording cannot be loaded.
    """

    STAGE_NAME = "curate"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the curate stage.

        Args:
            session: Active pipeline session with sorting results available.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        super().__init__(session, progress_callback)

    def run(self) -> None:
        """Compute quality metrics and curate all probes serially."""
        if self._is_complete():
            self._report_progress("Curate already complete", 1.0)
            return

        self._report_progress("Starting curate", 0.0)

        n_probes = len(self.session.probes)
        for i, probe in enumerate(self.session.probes):
            probe_id = probe.probe_id
            try:
                self._curate_probe(probe_id)
            except Exception as exc:
                self._write_failed_checkpoint(exc, probe_id=probe_id)
                raise
            self._report_progress(f"Curated {probe_id}", (i + 1) / n_probes)

        self._write_checkpoint({"probe_ids": [p.probe_id for p in self.session.probes]})
        self._report_progress("Curate complete", 1.0)

    def _curate_probe(self, probe_id: str) -> tuple[int, int]:
        """Run curation for a single probe.

        Args:
            probe_id: Probe identifier (e.g. "imec0").

        Returns:
            Tuple (n_units_before, n_units_after).
        """
        if self._is_complete(probe_id=probe_id):
            return (0, 0)

        sorted_path = self.session.output_dir / "sorted" / probe_id
        recording_path = self.session.output_dir / "preprocessed" / f"{probe_id}.zarr"

        try:
            sorting = si.load(sorted_path)
            recording = si.load(recording_path)
        except Exception as exc:
            raise CurateError(f"Failed to load data for {probe_id}: {exc}") from exc

        cfg = self.session.config
        resources = cfg.resources
        n_jobs = resources.n_jobs if resources.n_jobs != "auto" else 1
        chunk_duration = resources.chunk_duration if resources.chunk_duration != "auto" else "1s"

        analyzer = si.create_sorting_analyzer(
            sorting,
            recording,
            format="memory",
            sparse=True,
        )
        analyzer.compute("random_spikes")
        analyzer.compute("waveforms", chunk_duration=chunk_duration, n_jobs=n_jobs)
        analyzer.compute("templates")
        analyzer.compute("noise_levels")
        analyzer.compute("spike_amplitudes", chunk_duration=chunk_duration, n_jobs=n_jobs)
        analyzer.compute(
            "quality_metrics",
            metric_names=["isi_violation", "amplitude_cutoff", "presence_ratio", "snr"],
        )

        qm = analyzer.get_extension("quality_metrics").get_data()

        output_probe_dir = self.session.output_dir / "curated" / probe_id
        output_probe_dir.mkdir(parents=True, exist_ok=True)

        n_before = len(sorting.get_unit_ids())

        curation = cfg.curation
        keep_mask = (
            (qm["isi_violations_ratio"] <= curation.isi_violation_ratio_max)
            & (qm["amplitude_cutoff"] <= curation.amplitude_cutoff_max)
            & (qm["presence_ratio"] >= curation.presence_ratio_min)
            & (qm["snr"] >= curation.snr_min)
        )
        good_unit_ids = qm.index[keep_mask].tolist()
        curated_sorting = sorting.select_units(good_unit_ids)

        n_after = len(good_unit_ids)
        if n_after == 0:
            self.logger.warning("Zero units after curation", probe_id=probe_id)

        curated_sorting.save(folder=output_probe_dir, overwrite=True)
        # Write csv after save so overwrite=True doesn't delete it
        qm.to_csv(output_probe_dir / "quality_metrics.csv")

        self._write_checkpoint(
            {
                "probe_id": probe_id,
                "n_units_before": n_before,
                "n_units_after": n_after,
                "thresholds": {
                    "isi_violation_ratio_max": curation.isi_violation_ratio_max,
                    "amplitude_cutoff_max": curation.amplitude_cutoff_max,
                    "presence_ratio_min": curation.presence_ratio_min,
                    "snr_min": curation.snr_min,
                },
            },
            probe_id=probe_id,
        )

        del analyzer, sorting, recording
        gc.collect()

        return (n_before, n_after)
