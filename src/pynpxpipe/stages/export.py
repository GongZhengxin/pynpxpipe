"""Export stage: write all processed data to NWB + session-level derivatives.

Three-phase export strategy:
- Phase 1 (seconds): units/trials/eye tracking/KS4 → NWB
- Phase 2.5 (seconds): derivatives (TrialRaster/UnitProp/TrialRecord) →
    ``{output_dir}/07_derivatives/``
- Phase 3 (minutes, background thread): raw AP/LF/NIDQ compression → NWB

No UI dependencies.
"""

from __future__ import annotations

import dataclasses
import gc
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd
import pynwb
import spikeinterface.core as si

from pynpxpipe.core.errors import ExportError
from pynpxpipe.io.nwb_writer import NWBWriter
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


def compute_probe_rasters(
    analyzer: si.SortingAnalyzer,
    behavior_events: pd.DataFrame,
    probe_id: str,
    pre_onset_ms: int = 50,
) -> dict:
    """Compute per-unit rasters (spike counts in 1ms bins) for one probe.

    Raster window: [-pre_onset_ms, onset_time_ms + offset_time_ms] relative
    to each stimulus onset, using IMEC-referenced spike times.

    Args:
        analyzer: SortingAnalyzer with spike times in IMEC seconds.
        behavior_events: DataFrame with stim_onset_imec_s (JSON), trial_valid,
            onset_time_ms, offset_time_ms columns.
        probe_id: Probe identifier to extract from stim_onset_imec_s JSON.
        pre_onset_ms: Pre-stimulus window in ms (default 50).

    Returns:
        Dict mapping unit_id → np.ndarray of shape (n_valid_trials, n_bins), dtype uint8.
        Empty dict if no valid trials or missing columns.
    """
    required = {"stim_onset_imec_s", "trial_valid", "onset_time_ms", "offset_time_ms"}
    if not required.issubset(behavior_events.columns):
        return {}

    # Filter valid trials
    valid_mask = behavior_events["trial_valid"] == 1.0
    valid_df = behavior_events[valid_mask].reset_index(drop=True)
    if len(valid_df) == 0:
        return {}

    # Parse IMEC onset times for this probe
    stim_onsets_s: list[float] = []
    for _, row in valid_df.iterrows():
        imec_json = row["stim_onset_imec_s"]
        if isinstance(imec_json, str):
            per_probe = json.loads(imec_json)
            t_imec = per_probe.get(probe_id)
            if t_imec is not None:
                stim_onsets_s.append(float(t_imec))
            else:
                stim_onsets_s.append(np.nan)
        else:
            stim_onsets_s.append(np.nan)

    stim_onsets = np.array(stim_onsets_s, dtype=np.float64)
    onset_valid = ~np.isnan(stim_onsets)
    if onset_valid.sum() == 0:
        return {}

    # Determine bin count (constant per session)
    onset_time_ms = float(valid_df.iloc[0]["onset_time_ms"])
    offset_time_ms = float(valid_df.iloc[0]["offset_time_ms"])
    n_bins = pre_onset_ms + int(onset_time_ms) + int(offset_time_ms)

    # Filter to trials with valid IMEC onset
    trial_onsets = stim_onsets[onset_valid]
    n_valid = len(trial_onsets)

    # Pre-compute bin edges relative to onset (in seconds)
    pre_s = pre_onset_ms / 1000.0
    total_dur_s = n_bins / 1000.0

    unit_ids = list(analyzer.sorting.get_unit_ids())
    rasters: dict = {}

    for unit_id in unit_ids:
        spike_times = np.asarray(
            analyzer.sorting.get_unit_spike_train(unit_id, return_times=True),
            dtype=np.float64,
        )
        raster = np.zeros((n_valid, n_bins), dtype=np.uint8)

        for trial_idx, onset_s in enumerate(trial_onsets):
            t_start = onset_s - pre_s
            t_end = t_start + total_dur_s
            # Find spikes in window
            mask = (spike_times >= t_start) & (spike_times < t_end)
            trial_spikes = spike_times[mask]
            # Convert to bin indices (1ms bins)
            bin_indices = ((trial_spikes - t_start) * 1000.0).astype(int)
            bin_indices = bin_indices[(bin_indices >= 0) & (bin_indices < n_bins)]
            np.add.at(raster[trial_idx], bin_indices, 1)

        rasters[unit_id] = raster

    return rasters


class ExportStage(BaseStage):
    """Three-phase export: NWB → session-level derivatives → raw compression.

    Phase 1 (seconds): units/trials/eye tracking/KS4 → NWB file.
    Phase 2.5 (seconds): TrialRaster/UnitProp/TrialRecord →
        ``{output_dir}/07_derivatives/`` (see ``docs/specs/derivatives.md``).
    Phase 3 (background thread): raw AP/LF/NIDQ compressed into NWB.

    On Phase 1 failure: partial NWB deleted before re-raising ExportError.
    Phase 3 failure does not affect already-exported derivative data.

    Raises:
        ExportError: If Phase 1 NWBWriter raises or file cannot be verified.
    """

    STAGE_NAME = "export"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
        wait_for_raw: bool = True,
    ) -> None:
        """Initialize the export stage.

        Args:
            session: Active pipeline session with all upstream stages completed.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
            wait_for_raw: When True (default), Phase 3 (raw AP/LF/NIDQ
                compression + the E2.1 bit-exact verification scan) runs in
                the foreground and blocks ``run()`` until it completes so
                the UI can show a single "safe to exit" banner and the CLI
                can render a terminal-wide tqdm bar. On success the export
                checkpoint gains ``raw_data_verified_at`` (ISO8601) and
                ``verify_policy`` keys. When False (legacy behaviour), Phase
                3 runs in a daemon thread and those keys are absent — the
                caller is responsible for waiting on the thread elsewhere.
        """
        super().__init__(session, progress_callback)
        self.wait_for_raw = wait_for_raw

    def run(self) -> None:
        """Run three-phase export.

        Raises:
            ExportError: On Phase 1 write failure or file verification failure.
        """
        if self._is_complete():
            return

        # Pre-flight: target_area must be populated on every probe (discover's job).
        for probe in self.session.probes:
            if not probe.target_area or probe.target_area == "unknown":
                raise ExportError(
                    f"Probe {probe.probe_id} has target_area={probe.target_area!r}; "
                    "discover stage must populate target_area from session.probe_plan "
                    "before export"
                )

        self._report_progress("Starting export", 0.0)
        nwb_path = self._get_output_path()
        writer = NWBWriter(self.session, nwb_path)

        try:
            # ── Phase 1: NWB write (units/trials/eye/KS4) ──────────────────
            writer.create_file()

            behavior_events_path = self.session.output_dir / "04_sync" / "behavior_events.parquet"
            behavior_events = pd.read_parquet(behavior_events_path)

            n_units_total = 0
            n_probes = len(self.session.probes)
            for i, probe in enumerate(self.session.probes):
                probe_id = probe.probe_id
                postprocessed_dir = self.session.output_dir / "06_postprocessed" / probe_id
                if not (postprocessed_dir / "recording_info").exists():
                    self.logger.info(
                        "No SortingAnalyzer in %s — skipping probe export", postprocessed_dir
                    )
                    self._report_progress(
                        f"Skipped {probe_id} (no units)",
                        0.1 + 0.5 * (i + 1) / n_probes,
                    )
                    continue
                analyzer = si.load(postprocessed_dir)
                rasters = compute_probe_rasters(analyzer, behavior_events, probe_id)
                n_units = writer.add_probe_data(probe, analyzer, rasters=rasters)
                if isinstance(n_units, int):
                    n_units_total += n_units
                del analyzer, rasters
                gc.collect()
                self._report_progress(
                    f"Exported {probe_id}",
                    0.1 + 0.5 * (i + 1) / n_probes,
                )

            # E3.3: resolve UserVars.DatasetName → external tsv → 1-based
            # stim_index → FileName map, then hand it to add_trials together
            # with the per-onset stim_index column. Every step is wrapped in
            # a try/except because the legacy paradigms (no DatasetName) and
            # the cross-machine case (path unreachable, no vault configured)
            # are both legitimate — they should yield an empty stim_name
            # column without aborting the rest of export.
            stim_map: dict[int, str] | None = None
            dataset_name: str | None = None
            resolved_tsv_path: Path | None = None
            source_tag = "no_dataset_name"
            try:
                from pynpxpipe.io.bhv import BHV2Parser
                from pynpxpipe.io.stim_resolver import (
                    load_stim_map,
                    resolve_dataset_tsv,
                )

                bhv_path = getattr(self.session, "bhv_file", None)
                if bhv_path is not None:
                    dataset_name = BHV2Parser(bhv_path).get_dataset_tsv_path()
                vault_paths = list(getattr(self.session.subject, "image_vault_paths", []) or [])
                resolved_tsv_path, source_tag = resolve_dataset_tsv(dataset_name, vault_paths)
                if resolved_tsv_path is not None:
                    stim_map = load_stim_map(resolved_tsv_path)
            except Exception as exc:
                self.logger.warning(
                    "Could not build stim_index→stim_name map from BHV2 tsv: %s",
                    exc,
                )
                stim_map = None

            writer.add_trials(behavior_events, stim_map=stim_map)
            try:
                writer.add_stim_provenance(
                    dataset_name=dataset_name,
                    resolved_tsv_path=(str(resolved_tsv_path) if resolved_tsv_path else None),
                    source_tag=source_tag,
                )
            except Exception as exc:
                self.logger.warning("stim_name_provenance scratch block skipped: %s", exc)

            # Persist IMEC↔NIDQ fits + photodiode + event-code triples into
            # nwbfile.scratch so downstream consumers can redo sync even
            # after the raw bins are gone. Missing source files are flagged
            # in the JSON blob (``_missing: true``) rather than raising.
            sync_dir = self.session.output_dir / "04_sync"
            try:
                writer.add_sync_tables(
                    writer._nwbfile,
                    sync_dir,
                    behavior_events=behavior_events,
                )
            except Exception as exc:
                # add_sync_tables is internally fault-tolerant, but a bug in
                # the helper mustn't kill Phase 1 export.
                self.logger.warning("sync_tables scratch block skipped: %s", exc)

            # E3.1 — serialize effective PipelineConfig into nwbfile.scratch
            # for provenance. Legacy code paths may leave session.config as
            # the default empty dict; warn and skip in that case.
            session_config = getattr(self.session, "config", None)
            if dataclasses.is_dataclass(session_config) and not isinstance(session_config, type):
                try:
                    writer.add_pipeline_metadata(session_config)
                except Exception as exc:
                    self.logger.warning("pipeline_config scratch block skipped: %s", exc)
            else:
                self.logger.warning(
                    "session.config is not a dataclass (got %s); "
                    "skipping pipeline_config scratch write",
                    type(session_config).__name__,
                )

            # Eye tracking (optional)
            try:
                from pynpxpipe.io.bhv import BHV2Parser

                bhv_parser = BHV2Parser(self.session.bhv_file)
                writer.add_eye_tracking(bhv_parser, behavior_events)
            except Exception as exc:
                self.logger.warning("Eye tracking export skipped: %s", exc)

            # KS4 sorter output (optional, per probe)
            for probe in self.session.probes:
                ks4_path = self.session.output_dir / "02_sorted" / probe.probe_id / "sorter_output"
                if ks4_path.exists():
                    writer.add_ks4_sorting(probe.probe_id, ks4_path)

            nwb_path_written = writer.write()
            self._report_progress("Phase 1 complete (NWB written)", 0.65)

            # Verify NWB readable
            io = pynwb.NWBHDF5IO(str(nwb_path_written), "r")
            io.close()

        except Exception as exc:
            nwb_path.unlink(missing_ok=True)
            self._write_failed_checkpoint(exc)
            if isinstance(exc, ExportError):
                raise
            raise ExportError(str(exc)) from exc

        # ── Phase 2.5: session-level derivatives (07_derivatives/) ─────────
        try:
            self._export_phase2(nwb_path_written, behavior_events)
            self._report_progress("Phase 2.5 complete (derivatives)", 0.85)
        except Exception as exc:
            self.logger.warning("Phase 2.5 export failed (non-fatal): %s", exc)

        n_trials = len(behavior_events)
        self._write_checkpoint(
            {
                "nwb_path": str(nwb_path_written),
                "n_probes": n_probes,
                "n_units_total": n_units_total,
                "n_trials": n_trials,
            }
        )

        # ── Phase 3: raw data compression + E2.1 verification ───────────────
        # wait_for_raw=True   → foreground, blocking, full bit-exact scan,
        #                        checkpoint gets raw_data_verified_at + policy
        # wait_for_raw=False  → legacy daemon thread, checkpoint unchanged
        if self.wait_for_raw:
            self._export_phase3_background(
                nwb_path_written,
                verify_policy="full",
            )
            self._merge_verified_checkpoint("full")
        else:
            t = threading.Thread(
                target=self._export_phase3_background,
                args=(nwb_path_written,),
                daemon=True,
            )
            t.start()

        self._report_progress("Export complete", 1.0)

    def _merge_verified_checkpoint(
        self,
        verify_policy: Literal["full", "sample"],
    ) -> None:
        """Add verification metadata to an already-written export checkpoint.

        Re-reads ``checkpoints/export.json``, merges the ``raw_data_verified_at``
        (ISO8601 UTC) and ``verify_policy`` keys, and writes the result back.
        Called only on the ``wait_for_raw=True`` success path; never invoked
        when Phase 3 ran as a daemon thread.

        Args:
            verify_policy: The policy actually applied during the scan.
        """
        cp_path = self.session.output_dir / "checkpoints" / "export.json"
        if not cp_path.exists():
            self.logger.warning(
                "export checkpoint missing at %s — cannot merge verified fields",
                cp_path,
            )
            return
        try:
            existing = json.loads(cp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("could not read export checkpoint for merge: %s", exc)
            return
        existing["raw_data_verified_at"] = datetime.now(UTC).isoformat()
        existing["verify_policy"] = verify_policy
        cp_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def _export_phase2(self, nwb_path_written: Path, behavior_events: pd.DataFrame) -> None:
        """Phase 2.5: write session-level derivatives to ``07_derivatives/``.

        Reads the just-written NWB (``units`` + ``trials``), computes a combined
        spike raster, and writes three files under
        ``{output_dir}/07_derivatives/``:

        - ``TrialRaster_{session_id}.h5``  — (n_units, n_trials, n_timebins) uint8
        - ``UnitProp_{session_id}.csv``    — reduced unit properties
        - ``TrialRecord_{session_id}.csv`` — full NWB trials table

        Controlled by ``session.config.export.derivatives``; when disabled the
        directory is not created. Spec: ``docs/specs/derivatives.md`` §5.

        Args:
            nwb_path_written: NWB path returned by Phase 1 ``writer.write()``.
            behavior_events: Trial events DataFrame (reserved for future use).
        """
        from pynpxpipe.io.bhv import BHV2Parser
        from pynpxpipe.io.derivatives import (
            export_trial_record,
            export_unit_prop,
            resolve_post_onset_ms,
            save_raster_h5,
            spike_times_to_raster,
        )

        cfg = getattr(getattr(self.session, "config", None), "export", None)
        dcfg = getattr(cfg, "derivatives", None)
        if dcfg is not None and not dcfg.enabled:
            self.logger.info("Phase 2.5 (derivatives) disabled by config; skipping")
            return

        pre_onset_ms = float(getattr(dcfg, "pre_onset_ms", 50.0))
        post_onset_raw = getattr(dcfg, "post_onset_ms", "auto")
        bin_size_ms = float(getattr(dcfg, "bin_size_ms", 1.0))
        n_jobs = int(getattr(dcfg, "n_jobs", 1))

        session_id = self.session.session_id.canonical()
        derivatives_dir = self.session.output_dir / "07_derivatives"
        derivatives_dir.mkdir(parents=True, exist_ok=True)

        with pynwb.NWBHDF5IO(str(nwb_path_written), "r") as io:
            nwbfile = io.read()
            trials_df = (
                nwbfile.trials.to_dataframe() if nwbfile.trials is not None else pd.DataFrame()
            )
            units_df = nwbfile.units.to_dataframe() if nwbfile.units is not None else pd.DataFrame()

        if post_onset_raw == "auto":
            try:
                post_onset_ms = resolve_post_onset_ms(BHV2Parser(self.session.bhv_file))
            except Exception as exc:
                self.logger.warning("resolve_post_onset_ms failed, using 800.0: %s", exc)
                post_onset_ms = 800.0
        else:
            post_onset_ms = float(post_onset_raw)

        export_trial_record(trials_df, derivatives_dir / f"TrialRecord_{session_id}.csv")
        export_unit_prop(units_df, derivatives_dir / f"UnitProp_{session_id}.csv")

        if len(units_df) and len(trials_df) and "spike_times" in units_df.columns:
            raster = spike_times_to_raster(
                units_df,
                trials_df,
                pre_onset=pre_onset_ms,
                post_onset=post_onset_ms,
                bin_size=bin_size_ms,
                n_jobs=n_jobs,
            )
            save_raster_h5(
                str(derivatives_dir / f"TrialRaster_{session_id}.h5"),
                raster,
                metadata={
                    "pre_onset_ms": pre_onset_ms,
                    "post_onset_ms": post_onset_ms,
                    "bin_size_ms": bin_size_ms,
                    "session_id": session_id,
                },
            )
        else:
            self.logger.warning(
                "Skipping TrialRaster export (units=%d, trials=%d, spike_times_col=%s)",
                len(units_df),
                len(trials_df),
                "spike_times" in units_df.columns,
            )

    def _export_phase3_background(
        self,
        nwb_path: Path,
        time_range: tuple[float, float] | None = None,
        verify_policy: Literal["full", "sample"] = "full",
    ) -> None:
        """Phase 3: raw data compression (daemon thread or foreground).

        Streams raw AP/LF voltage data into the existing NWB file with Blosc
        zstd compression and then runs the E2.1 bit-exact verification scan.
        In the legacy daemon-thread path (``wait_for_raw=False``) a failure
        is logged but does not affect already-exported analysis data. When
        called from the foreground (``wait_for_raw=True``, the default) any
        ``ExportError`` from verification is re-raised to the caller so the
        pipeline can fail loudly, and Phase 3's internal fraction [0.0, 1.0]
        is relayed through the stage's progress_callback mapped into the
        overall stage's trailing [0.85, 0.99] band.

        Args:
            nwb_path: Path to the existing NWB file to append raw data to.
            time_range: Optional (start_sec, end_sec) to export a subset.
            verify_policy: Forwarded to ``append_raw_data``; ``"full"`` for
                blocking mode, unused by the daemon thread default which
                still performs a full scan but only logs mismatches.
        """
        phase3_callback: Callable[[str, float], None] | None = None
        if self.wait_for_raw and self.progress_callback is not None:

            def phase3_callback(msg: str, frac: float) -> None:
                # Phase 3 occupies the tail of the stage's progress budget:
                # Phase 1 ends at 0.65, derivatives at 0.85; reserve 1.0 for
                # the final "Export complete" emit and cap Phase 3 at 0.99.
                bounded = max(0.0, min(1.0, frac))
                overall = 0.85 + 0.14 * bounded
                self._report_progress(f"Phase 3: {msg}", overall)

        try:
            writer = NWBWriter(self.session, nwb_path)
            result = writer.append_raw_data(
                self.session,
                nwb_path,
                time_range=time_range,
                verify_policy=verify_policy,
                progress_callback=phase3_callback,
            )
            self.logger.info("Phase 3 complete: %s", result)
        except ExportError:
            # Foreground (wait_for_raw=True) callers need the verification
            # failure to propagate so the pipeline can abort; background
            # thread callers never see this branch because nothing awaits them.
            if self.wait_for_raw:
                raise
            self.logger.warning("Phase 3 background raw compression failed (verification)")
        except Exception as exc:
            self.logger.warning("Phase 3 background raw compression failed: %s", exc)

    def _get_output_path(self) -> Path:
        """Compute the NWB output path from the canonical SessionID."""
        return self.session.output_dir / f"{self.session.session_id.canonical()}.nwb"
