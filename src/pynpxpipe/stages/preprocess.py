"""Preprocess stage: bandpass filter, CMR, and motion correction per probe.

Saves preprocessed recordings as Zarr format. No UI dependencies.
"""

from __future__ import annotations

import gc
from collections.abc import Callable
from typing import TYPE_CHECKING

import spikeinterface.preprocessing as spp

from pynpxpipe.core.config import PipelineConfig
from pynpxpipe.core.errors import PreprocessError
from pynpxpipe.io.spikeglx import SpikeGLXLoader
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class PreprocessStage(BaseStage):
    """Applies preprocessing pipeline to each probe's AP recording.

    Processing order per probe:
        phase_shift → bandpass_filter → detect_bad_channels →
        remove_bad_channels → CMR → motion_correction (optional) → Zarr save.

    Phase shift corrects Neuropixels time-division multiplexed ADC offsets;
    it must precede CMR so per-channel sub-sample offsets do not leak into the
    spatial median. Its position relative to bandpass_filter is LTI-equivalent
    (see ADR-003); this pipeline keeps phase_shift first by convention.
    Each probe processed serially. Memory released between probes (del + gc.collect).
    AP recordings are never fully loaded into memory (SpikeInterface lazy).

    Raises:
        PreprocessError: If Zarr save fails (disk full, permissions) or
            motion correction method is unsupported.
    """

    STAGE_NAME = "preprocess"

    def __init__(
        self,
        session: Session,
        pipeline_config: PipelineConfig | None = None,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the preprocess stage.

        Args:
            session: Active pipeline session with probes populated.
            pipeline_config: Pipeline configuration; uses PipelineConfig defaults
                when None (e.g. standalone testing without a runner).
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        super().__init__(session, progress_callback)
        self.pipeline_config = pipeline_config if pipeline_config is not None else PipelineConfig()

    def run(self) -> None:
        """Preprocess all probes serially.

        For each probe (skipping those with completed per-probe checkpoint):
        1. Load AP recording lazily via SpikeGLXLoader.
        2. Phase shift (Neuropixels ADC timing correction — FIRST step).
        3. Bandpass filter (freq_min, freq_max from config).
        4. Detect and remove bad channels (on filtered data).
        5. Common median reference.
        6. Motion correction if config.preprocess.motion_correction.method not None.
        7. Save to Zarr at {output_dir}/01_01_preprocessed/{probe_id}/.
        8. Write per-probe checkpoint; del recording + gc.collect().

        Raises:
            PreprocessError: If Zarr write fails or motion correction unsupported.
        """
        if self._is_complete():
            self._report_progress("Preprocess already complete", 1.0)
            return

        self._report_progress("Starting preprocess", 0.0)
        self._setup_spikeinterface_jobs(self.pipeline_config)

        if not self.session.probes:
            raise PreprocessError(
                "No probes in session. The discover stage may not have run or "
                "failed to populate probes. Re-run from discover."
            )

        n_probes = len(self.session.probes)
        for i, probe in enumerate(self.session.probes):
            try:
                self._preprocess_probe(probe.probe_id)
            except PreprocessError:
                raise
            self._report_progress(f"Preprocessed {probe.probe_id}", (i + 1) / n_probes)

        self._write_checkpoint({"probe_ids": [p.probe_id for p in self.session.probes]})
        self._report_progress("Preprocess complete", 1.0)

    def _preprocess_probe(self, probe_id: str) -> None:
        """Run the full preprocessing pipeline for one probe.

        Args:
            probe_id: Probe identifier (e.g. "imec0").

        Raises:
            PreprocessError: On unrecoverable processing failure.
        """
        if self._is_complete(probe_id=probe_id):
            self._report_progress(f"Skipping already preprocessed probe {probe_id}", 0.0)
            return

        probe = next(p for p in self.session.probes if p.probe_id == probe_id)
        cfg = self.pipeline_config

        # Step 1: lazy load AP recording (no data read yet)
        recording = SpikeGLXLoader.load_ap(probe)
        # Keep a handle on the unprocessed recording for diagnostic plots.
        raw_recording = recording

        # Step 2: phase shift — TDM-ADC per-channel sub-sample offset correction.
        # Must precede CMR; LTI-equivalent to placing it after bandpass (ADR-003).
        recording = spp.phase_shift(recording)

        # Step 3: bandpass filter
        recording = spp.bandpass_filter(
            recording,
            freq_min=cfg.preprocess.bandpass.freq_min,
            freq_max=cfg.preprocess.bandpass.freq_max,
        )

        # Step 4: detect bad channels (on filtered data for better accuracy)
        bad_channel_ids, _ = spp.detect_bad_channels(
            recording,
            method=cfg.preprocess.bad_channel_detection.method,
        )

        # Step 5: remove bad channels (only if any found)
        if len(bad_channel_ids) > 0:
            recording = recording.remove_channels(bad_channel_ids)

        # Step 6: common median reference
        recording = spp.common_reference(
            recording,
            reference=cfg.preprocess.common_reference.reference,
            operator=cfg.preprocess.common_reference.operator,
        )

        # Step 7: optional motion correction
        if cfg.preprocess.motion_correction.method is not None:
            recording = spp.correct_motion(
                recording,
                preset=cfg.preprocess.motion_correction.preset,
            )

        # Step 8: save as Zarr
        zarr_path = self.session.output_dir / "01_preprocessed" / f"{probe_id}.zarr"
        try:
            recording.save(
                folder=zarr_path,
                format="zarr",
            )
        except Exception as exc:
            err = PreprocessError(f"Failed to save Zarr for {probe_id}: {exc}")
            self._write_failed_checkpoint(err, probe_id=probe_id)
            raise err from exc

        # Step 8.5: emit diagnostic PNG figures (never blocks main path).
        try:
            from pynpxpipe.plots.preprocess import emit_all as _emit_pp_plots

            figures_dir = self.session.output_dir / "01_preprocessed" / probe_id / "figures"
            motion_info = None
            if cfg.preprocess.motion_correction.method is not None:
                # SI 0.104 correct_motion attaches motion info to the recording.
                try:
                    motion_obj = getattr(recording, "motion", None)
                    if motion_obj is not None:
                        motion_info = {
                            "displacement": getattr(motion_obj, "displacement", None),
                            "temporal_bins": getattr(motion_obj, "temporal_bins_s", None),
                            "spatial_bins": getattr(motion_obj, "spatial_bins_um", None),
                        }
                        if motion_info["displacement"] is None:
                            motion_info = None
                except Exception:
                    motion_info = None

            _emit_pp_plots(
                recording_raw=raw_recording,
                recording_processed=recording,
                bad_channel_ids=list(bad_channel_ids) if bad_channel_ids is not None else [],
                probe_id=probe_id,
                output_dir=figures_dir,
                session_label=self.session.session_id.canonical(),
                motion_info=motion_info,
            )
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001 - diagnostic plots never block pipeline
            self.logger.warning("preprocess figure generation failed: %s", exc)

        # Step 9: write per-probe checkpoint
        self._write_checkpoint(
            {
                "probe_id": probe_id,
                "n_bad_channels": len(bad_channel_ids),
                "freq_min": cfg.preprocess.bandpass.freq_min,
                "freq_max": cfg.preprocess.bandpass.freq_max,
                "motion_correction_method": cfg.preprocess.motion_correction.method,
                "zarr_path": str(zarr_path),
            },
            probe_id=probe_id,
        )

        # Step 10: release memory
        del recording
        gc.collect()
