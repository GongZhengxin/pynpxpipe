"""Synchronize stage: three-level time alignment.

Level 1 — IMEC ↔ NIDQ: linear regression per probe (t_nidq = a*t_imec + b).
Level 2 — BHV2 ↔ NIDQ: MonkeyLogic event codes matched to BHV2 trials.
Level 3 — Photodiode: calibrates stim onset times from the analog signal.

Outputs:
- ``{output_dir}/04_sync/sync_tables.json``   — per-probe linear correction params
- ``{output_dir}/04_sync/{probe_id}_imec_nidq.json`` — per-probe fit (one file per
  probe; consumed by ``NWBWriter.add_sync_tables`` to populate the NWB scratch
  ``sync_tables`` block)
- ``{output_dir}/04_sync/behavior_events.parquet`` — unified behavioral events
- ``{output_dir}/04_sync/figures/``           — optional diagnostic PNGs

No UI dependencies (no click, no print, no sys.exit).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np

from pynpxpipe.core.errors import SyncError
from pynpxpipe.io.bhv import BHV2Parser
from pynpxpipe.io.spikeglx import SpikeGLXDiscovery, SpikeGLXLoader
from pynpxpipe.io.sync.bhv_nidq_align import align_bhv2_to_nidq
from pynpxpipe.io.sync.imec_nidq_align import SyncResult, align_imec_to_nidq
from pynpxpipe.io.sync.photodiode_calibrate import calibrate_photodiode
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session
    from pynpxpipe.io.sync.bhv_nidq_align import TrialAlignment
    from pynpxpipe.io.sync.photodiode_calibrate import CalibratedOnsets

logger = logging.getLogger(__name__)


class SynchronizeStage(BaseStage):
    """Aligns all data streams to NIDQ clock and extracts behavioral events.

    Three-level alignment:
    1. IMEC ↔ NIDQ: linear regression per probe (t_nidq = a*t_imec + b).
    2. BHV2 ↔ NIDQ: MonkeyLogic event codes matched to BHV2 trials.
    3. Photodiode: calibrates stim onset times from analog photodiode signal.

    Outputs: sync_tables.json, behavior_events.parquet, optional figures/.
    Uses single stage-level checkpoint (not per-probe).

    Raises:
        SyncError: If any alignment error exceeds max_time_error_ms, trial count
            mismatch exceeds tolerance, or photodiode signal is dead.
    """

    STAGE_NAME = "synchronize"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the synchronize stage.

        Args:
            session: Active pipeline session with probes and bhv_file available.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        super().__init__(session, progress_callback)

    def run(self) -> None:
        """Execute three-level synchronization.

        Steps:
        1.  Check stage-level checkpoint; return immediately if completed.
        2.  Report progress 0 %.
        3.  Discover NIDQ files, parse meta, load recording.
        4.  Level 1 — align each probe AP clock to NIDQ.
        5.  Decode NIDQ multi-bit event codes.
        6.  Level 2 — align BHV2 events to NIDQ clock.
        7.  Level 3 — calibrate photodiode onset times.
        8.  Convert stim onset times to each probe's IMEC clock.
        9.  Build behavior_events DataFrame.
        10. Write sync_tables.json.
        11. Write behavior_events.parquet.
        12. Optionally generate diagnostic plots.
        13. Write completed stage checkpoint.
        14. Report progress 100 %.

        Raises:
            SyncError: On any alignment or calibration failure.
        """
        # Step 1: skip if already done
        if self._is_complete():
            return

        try:
            self._report_progress("Starting synchronize", 0.0)

            # Step 3: NIDQ files + meta
            discovery = SpikeGLXDiscovery(self.session.session_dir)
            nidq_bin, nidq_meta = discovery.discover_nidq()
            nidq_meta_dict = discovery.parse_meta(nidq_meta)
            nidq_sample_rate = float(nidq_meta_dict["niSampRate"])
            voltage_range = float(nidq_meta_dict.get("niAiRangeMax", "5.0"))

            nidq_recording = SpikeGLXLoader.load_nidq(nidq_bin, nidq_meta)
            sync = self.session.config.sync
            nidq_sync_times = np.array(
                SpikeGLXLoader.extract_sync_edges(
                    nidq_recording, sync.nidq_sync_bit, nidq_sample_rate
                )
            )

            # Step 4: Level 1 — per-probe alignment
            sync_results: dict[str, SyncResult] = {}
            ap_sync_times_map: dict[str, np.ndarray] = {}
            for probe in self.session.probes:
                ap_times, sync_result = self._align_probe_to_nidq(probe.probe_id, nidq_sync_times)
                sync_results[probe.probe_id] = sync_result
                ap_sync_times_map[probe.probe_id] = ap_times
            self._report_progress("Level 1 complete", 0.33)

            # Step 5: Decode NIDQ event codes
            nidq_event_times, nidq_event_codes = self._decode_nidq_events(
                nidq_recording, sync.event_bits, nidq_sample_rate
            )

            # Step 6: Level 2 — BHV2 alignment
            trial_alignment: TrialAlignment = self._align_bhv2_to_nidq(
                nidq_event_times, nidq_event_codes
            )
            self._report_progress("Level 2 complete", 0.55)

            # Step 7: Level 3 — Photodiode calibration
            pd_idx = sync.photodiode_channel_index
            raw_traces = nidq_recording.get_traces()
            if raw_traces.ndim > 1:
                pd_signal = raw_traces[:, pd_idx].astype(np.int16)
            else:
                pd_signal = raw_traces.astype(np.int16)

            stim_onsets_digital = trial_alignment.trial_events_df["stim_onset_nidq_s"].to_numpy()
            calibrated: CalibratedOnsets = calibrate_photodiode(
                pd_signal,
                nidq_sample_rate,
                voltage_range,
                stim_onsets_digital,
                monitor_delay_ms=sync.monitor_delay_ms,
                pd_window_pre_ms=sync.pd_window_pre_ms,
                pd_window_post_ms=sync.pd_window_post_ms,
                pd_hignline_skip_ms=sync.pd_hignline_skip_ms,
                pd_hignline_width_ms=sync.pd_hignline_width_ms,
                min_signal_variance=sync.pd_min_signal_variance,
            )
            self._report_progress("Level 3 complete", 0.75)

            # Step 8: Convert stim onset to IMEC clock per probe
            # t_nidq = a * t_imec + b  →  t_imec = (t_nidq - b) / a
            n_trials = len(calibrated.stim_onset_nidq_s)
            stim_onset_imec_strs: list[str] = []
            for trial_idx in range(n_trials):
                t_nidq = calibrated.stim_onset_nidq_s[trial_idx]
                per_probe = {pid: (t_nidq - sr.b) / sr.a for pid, sr in sync_results.items()}
                stim_onset_imec_strs.append(json.dumps(per_probe))

            # Step 9: Build behavior_events DataFrame
            df = trial_alignment.trial_events_df.copy()
            df["stim_onset_nidq_s"] = calibrated.stim_onset_nidq_s
            df["stim_onset_imec_s"] = stim_onset_imec_strs
            df["onset_latency_ms"] = calibrated.onset_latency_ms
            df["quality_flag"] = calibrated.quality_flags
            df["dataset_name"] = trial_alignment.dataset_name

            # Step 10: Write sync_tables.json
            sync_dir = self.session.output_dir / "04_sync"
            sync_dir.mkdir(parents=True, exist_ok=True)

            sync_tables = {
                "probes": {
                    pid: {
                        "a": sr.a,
                        "b": sr.b,
                        "residual_ms": sr.residual_ms,
                        "n_repaired": sr.n_repaired,
                    }
                    for pid, sr in sync_results.items()
                },
                "dataset_name": trial_alignment.dataset_name,
                "n_trials": n_trials,
                "bhv_metadata": trial_alignment.bhv_metadata,
            }
            (sync_dir / "sync_tables.json").write_text(
                json.dumps(sync_tables, indent=2), encoding="utf-8"
            )

            # Per-probe {probe_id}_imec_nidq.json consumed by
            # NWBWriter.add_sync_tables — one file per probe preserves the raw
            # inputs needed to re-derive imec_i↔imec0 alignment via NIDQ as
            # bridge, which the consolidated sync_tables.json also carries but
            # under a different key path.
            for pid, sr in sync_results.items():
                (sync_dir / f"{pid}_imec_nidq.json").write_text(
                    json.dumps(
                        {
                            "a": sr.a,
                            "b": sr.b,
                            "residual_ms": sr.residual_ms,
                            "n_repaired": sr.n_repaired,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )

            # Step 11: Write behavior_events.parquet
            df.to_parquet(sync_dir / "behavior_events.parquet", engine="pyarrow")

            # Step 12: Optional diagnostic plots
            if sync.generate_plots:
                eye_points = self._collect_eye_points()
                try:
                    from pynpxpipe.plots.sync import emit_all as _emit_sync_plots

                    figures_dir = sync_dir / "figures"
                    figures_dir.mkdir(parents=True, exist_ok=True)
                    _emit_sync_plots(
                        sync_results=sync_results,
                        ap_sync_times_map=ap_sync_times_map,
                        nidq_sync_times=nidq_sync_times,
                        trial_alignment=trial_alignment,
                        calibrated=calibrated,
                        output_dir=figures_dir,
                        pd_signal=pd_signal,
                        nidq_sample_rate=nidq_sample_rate,
                        voltage_range=voltage_range,
                        monitor_delay_ms=sync.monitor_delay_ms,
                        pre_ms=sync.pd_window_pre_ms,
                        post_ms=sync.pd_window_post_ms,
                        session_label=self.session.session_dir.name,
                        eye_points=eye_points,
                    )
                except ImportError:
                    # matplotlib not installed — sync still succeeded.
                    pass
                except Exception as exc:  # noqa: BLE001
                    logger.warning("sync figure generation failed: %s", exc)

            # Step 13: Write stage checkpoint
            self._write_checkpoint(
                {
                    "n_probes": len(self.session.probes),
                    "probe_ids": [p.probe_id for p in self.session.probes],
                    "n_trials": n_trials,
                    "n_suspicious_pd": calibrated.n_suspicious,
                    "dataset_name": trial_alignment.dataset_name,
                }
            )
            self._report_progress("Synchronize complete", 1.0)

        except SyncError as exc:
            self._write_failed_checkpoint(exc)
            raise

    def _align_probe_to_nidq(
        self,
        probe_id: str,
        nidq_sync_times: np.ndarray,
    ) -> tuple[np.ndarray, SyncResult]:
        """Fit linear time correction for one probe.

        Extracts sync pulse rising edges from the AP digital channel,
        pairs them with NIDQ sync edges, and runs least-squares regression.

        Args:
            probe_id: Probe identifier (e.g. "imec0").
            nidq_sync_times: Rising-edge times from the NIDQ sync channel (seconds).

        Returns:
            Tuple (ap_sync_times, SyncResult) where SyncResult holds (a, b, residual_ms).

        Raises:
            SyncError: If residual exceeds max_time_error_ms.
        """
        probe = next(p for p in self.session.probes if p.probe_id == probe_id)
        ap_recording = SpikeGLXLoader.load_ap(probe, load_sync_channel=True)
        ap_sync_times = np.array(
            SpikeGLXLoader.extract_sync_edges(
                ap_recording, self.session.config.sync.imec_sync_bit, probe.sample_rate
            )
        )
        sync = self.session.config.sync
        sync_result = align_imec_to_nidq(
            probe_id,
            ap_sync_times,
            nidq_sync_times,
            max_time_error_ms=sync.max_time_error_ms,
            gap_threshold_ms=sync.gap_threshold_ms,
        )
        return ap_sync_times, sync_result

    def _align_bhv2_to_nidq(
        self,
        nidq_event_times: np.ndarray,
        nidq_event_codes: np.ndarray,
    ) -> TrialAlignment:
        """Align BHV2 events to the NIDQ clock.

        Parses the BHV2 file, matches trial onset event codes, and produces
        the per-trial event table in NIDQ clock seconds.

        Args:
            nidq_event_times: 1D float64 array of NIDQ event times (seconds).
            nidq_event_codes: 1D int array of decoded NIDQ event codes.

        Returns:
            TrialAlignment with per-trial DataFrame and metadata.

        Raises:
            SyncError: If trial count mismatch exceeds tolerance.
        """
        sync = self.session.config.sync
        bhv_parser = BHV2Parser(self.session.bhv_file)
        return align_bhv2_to_nidq(
            bhv_parser,
            nidq_event_times,
            nidq_event_codes,
            stim_onset_code=sync.stim_onset_code,
            trial_start_bit=sync.trial_start_bit,
            stim_onset_bit=sync.stim_onset_bit,
            max_time_error_ms=sync.max_time_error_ms,
            trial_count_tolerance=sync.trial_count_tolerance,
            stim_count_tolerance=sync.stim_count_tolerance,
        )

    def _collect_eye_points(self) -> np.ndarray | None:
        """Concatenate per-trial analog ``Eye`` samples into an ``(N, 2)`` array.

        Reads ``AnalogData["Eye"]`` from every BHV2 trial via
        :meth:`BHV2Parser.get_analog_data`, keeps rows with at least two
        columns (x, y), and stacks them for the eye-density heat-map
        (``eye_density.png`` in MATLAB reference plot #5).

        Returns:
            ``(N, 2) float64`` ndarray of gaze samples, or ``None`` if the
            parser raises, no trial carries an ``Eye`` channel, or the data
            is malformed. Failures are logged as warnings — they do not
            abort the stage since the eye plot is a diagnostic, not a
            pipeline invariant.
        """
        try:
            parser = BHV2Parser(self.session.bhv_file)
            eye_data = parser.get_analog_data("Eye")
        except Exception as exc:  # noqa: BLE001 - diagnostic, never abort sync
            logger.warning("eye data extraction failed: %s", exc)
            return None

        blocks: list[np.ndarray] = []
        for arr in eye_data.values():
            a = np.asarray(arr)
            if a.ndim == 2 and a.shape[1] >= 2 and a.shape[0] > 0:
                blocks.append(a[:, :2].astype(np.float64))
        if not blocks:
            return None
        return np.vstack(blocks)

    def _decode_nidq_events(
        self,
        nidq_recording,
        event_bits: list[int],
        sample_rate: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Decode MonkeyLogic event codes from NIDQ digital channel bits.

        Reads the digital channel word, extracts each bit in event_bits, packs
        them into a contiguous integer (bit_vals[0]<<0 | bit_vals[1]<<1 | ...),
        finds transitions, and converts sample indices to seconds.

        Args:
            nidq_recording: SpikeInterface-like recording with get_traces().
            event_bits: Bit positions in the digital word to decode.
            sample_rate: NIDQ sampling rate in Hz.

        Returns:
            (event_times_s, event_codes) as float64 and int32 numpy arrays.
        """
        raw = nidq_recording.get_traces()
        # Digital word is the last saved channel (after analog channels)
        digital = raw[:, -1].astype(np.uint16) if raw.ndim > 1 else raw.astype(np.uint16)

        n_samples = len(digital)
        code_values = np.zeros(n_samples, dtype=np.uint32)
        for i, bit in enumerate(event_bits):
            bit_vals = (digital >> bit) & np.uint16(1)
            code_values |= bit_vals.astype(np.uint32) << i

        diff_nonzero = np.where(np.diff(code_values) != 0)[0]
        if len(diff_nonzero) == 0:
            return np.array([], dtype=np.float64), np.array([], dtype=np.int32)

        transition_samples = diff_nonzero + 1
        event_times_s = transition_samples / sample_rate
        event_codes = code_values[transition_samples].astype(np.int32)

        return event_times_s, event_codes
