"""Select complete task blocks and persist the authoritative time mapping."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from pynpxpipe.core.segments import (
    Segment,
    SegmentManifest,
    presented_events,
    select_task_windows,
    window_frames,
)
from pynpxpipe.io.segment_recordings import acquisition_start, validate_sources
from pynpxpipe.io.spikeglx import SpikeGLXDiscovery
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import ProbeInfo, RecordingSource


class SelectSegmentsStage(BaseStage):
    """Convert aligned trials into retained source/sample intervals."""

    STAGE_NAME = "select_segments"

    def _reference_clock(
        self, source: RecordingSource
    ) -> tuple[ProbeInfo, dict[str, str], datetime]:
        probe = next((p for p in source.probes if p.probe_id == "imec0"), None)
        if probe is None:
            raise ValueError(f"Source {source.source_id} requires a discovered imec0 reference")
        meta = SpikeGLXDiscovery.parse_meta(probe.ap_meta)
        try:
            start = acquisition_start(meta, self.session.config.task_windows.recording_timezone)
        except ValueError as exc:
            raise ValueError(f"Source {source.source_id} ({probe.ap_meta}): {exc}") from exc
        return probe, meta, start

    def check_acquisition_times(self) -> None:
        """Validate the discovered reference clocks before loading any sync signals.

        Raises:
            ValueError: If a source has no usable reference timestamp.
        """
        try:
            for source in self.session.recording_sources:
                self._reference_clock(source)
        except (OSError, ValueError) as exc:
            self._report_progress("Acquisition timestamp check failed", 0.0)
            self._write_failed_checkpoint(exc)
            raise

    def run(self) -> None:
        """Build selection, behavioral tables and source-clock provenance.

        Raises:
            ValueError: If trials, timestamps or probe configurations are ambiguous.
        """
        if not self.session.segmented:
            self._write_checkpoint({"enabled": False})
            return
        if (
            self._is_complete()
            and (self.session.output_dir / "03_segments" / "segments.json").exists()
        ):
            self._report_progress("Task selection already complete", 1.0)
            return
        try:
            self._report_progress("Selecting task segments", 0.0)
            self._select()
        except Exception as exc:
            self._write_failed_checkpoint(exc)
            raise

    def _select(self) -> None:
        joint_error = None
        try:
            validate_sources(self.session)
        except ValueError as exc:
            joint_error = str(exc)
        cfg = self.session.config.task_windows
        sources = self.session.recording_sources
        segments, metadata, all_trials, all_events = [], [], [], []
        nidq_durations = {}
        offsets: dict[tuple[str, str], int] = {}
        first_time = None
        first_meta = None
        previous_end = -np.inf
        for source in sources:
            sync_dir = (
                self.session.output_dir / "sources" / source.source_id
                if len(sources) > 1
                else self.session.output_dir
            ) / "04_sync"
            sync = json.loads((sync_dir / "sync_tables.json").read_text(encoding="utf-8"))["probes"]
            if "imec0" not in sync:
                raise ValueError("Segmented export requires imec0 as the experiment reference")
            ref = sync["imec0"]
            ref_probe, ref_meta, timestamp = self._reference_clock(source)
            method = "explicit_offset"
            if first_time is None:
                first_time, first_meta = timestamp, ref_meta
                if source.start_offset_s not in (None, 0.0):
                    raise ValueError("The first source start_offset_s must be zero")
                offset = 0.0
                method = "reference"
            elif source.start_offset_s is not None:
                offset = source.start_offset_s
            elif (
                ref_meta.get("fileCreateTime") == first_meta.get("fileCreateTime")
                and ref_meta.get("runName")
                and ref_meta.get("runName") == first_meta.get("runName")
                and "firstSample" in ref_meta
                and "firstSample" in first_meta
            ):
                offset = (
                    int(ref_meta["firstSample"]) - int(first_meta["firstSample"])
                ) / ref_probe.sample_rate
                method = "same_acquisition_counter"
            else:
                offset = (timestamp - first_time).total_seconds()
                method = "acquisition_wall_clock"
            ref_duration = (
                ref_probe.ap_bin.stat().st_size
                / (2 * int(ref_meta["nSavedChans"]))
                / ref_probe.sample_rate
            )
            if offset < previous_end - 1 / ref_probe.sample_rate:
                raise ValueError(
                    "Source acquisition times overlap or are out of order; provide corrected start_offset_s"
                )
            previous_end = offset + ref_duration
            trials = pd.read_parquet(sync_dir / "trial_intervals.parquet")
            events = pd.read_parquet(sync_dir / "behavior_events.parquet")
            events = presented_events(events).copy()
            if (
                not events.trial_id.isin(trials.trial_id).all()
                or trials.trial_id.duplicated().any()
            ):
                raise ValueError(
                    f"{source.source_id}: stimulus events and trial identifiers disagree"
                )
            trials["n_presentations"] = (
                trials.trial_id.map(events.trial_id.value_counts()).fillna(0).astype(int)
            )
            empty = trials.loc[trials.n_presentations == 0]
            empty_intervals = list(zip(empty.start_time, empty.stop_time, strict=True))
            empty_stops = sorted(empty.stop_time) if cfg.enabled else []
            trials = trials.loc[trials.n_presentations > 0].copy()
            nidq_bin, nidq_meta_path = SpikeGLXDiscovery(source.session_dir).discover_nidq()
            nidq_meta = SpikeGLXDiscovery.parse_meta(nidq_meta_path)
            ni_rate = float(nidq_meta["niSampRate"])
            ni_frames = nidq_bin.stat().st_size // (2 * int(nidq_meta["nSavedChans"]))
            nidq_durations[source.source_id] = ni_frames / ni_rate
            windows = select_task_windows(
                list(zip(trials.start_time, trials.stop_time, strict=True)),
                nidq_durations[source.source_id],
                cfg,
                empty_trials=empty_intervals,
            )
            stream_specs = [("nidq", "nidq", ni_rate, ni_frames, 1.0, 0.0)]
            for probe in source.probes:
                fit = sync[probe.probe_id]
                ap_meta = SpikeGLXDiscovery.parse_meta(probe.ap_meta)
                frames = probe.ap_bin.stat().st_size // (2 * int(ap_meta["nSavedChans"]))
                stream_specs.append(
                    (probe.probe_id, "ap", probe.sample_rate, frames, fit["a"], fit["b"])
                )
                if probe.lf_bin:
                    lf_meta = SpikeGLXDiscovery.parse_meta(probe.lf_meta)
                    rate = float(lf_meta["imSampRate"])
                    frames = probe.lf_bin.stat().st_size // (2 * int(lf_meta["nSavedChans"]))
                    shift = (
                        int(lf_meta.get("firstSample", 0)) / rate
                        - int(ap_meta.get("firstSample", 0)) / probe.sample_rate
                    )
                    stream_specs.append(
                        (probe.probe_id, "lf", rate, frames, fit["a"], fit["b"] + shift * fit["a"])
                    )
            for pid, stream, rate, n_frames, a, b in stream_specs:
                if cfg.enabled and stream == "ap":
                    trial_bounds = (trials[["start_time", "stop_time"]].to_numpy() - b) / a * rate
                    if np.any(trial_bounds[:, 0] < -1) or np.any(trial_bounds[:, 1] > n_frames + 1):
                        raise ValueError(
                            f"{source.source_id}/{pid}: task trials extend beyond neural recording"
                        )
                for start, stop in windows:
                    lo, hi = window_frames(
                        start, stop, rate, n_frames, a, b, empty_stops=empty_stops
                    )
                    if hi <= lo:
                        raise ValueError(
                            f"{source.source_id}/{pid}/{stream}: task block has no samples"
                        )
                    key = (pid, stream)
                    segments.append(
                        Segment(
                            source.source_id,
                            pid,
                            lo,
                            hi,
                            offsets.get(key, 0),
                            rate,
                            a / ref["a"],
                            offset + (b - ref["b"]) / ref["a"],
                            stream,
                        )
                    )
                    offsets[key] = offsets.get(key, 0) + hi - lo
            trials["source_id"] = source.source_id
            trials["trial_key"] = [f"{source.source_id}:{tid}" for tid in trials.trial_id]
            for col in ("start_time", "stop_time", "bhv_zero_nidq_s"):
                trials[f"source_{col}"] = trials[col]
                trials[col] = (trials[col] - ref["b"]) / ref["a"] + offset
            events["source_id"] = source.source_id
            events["trial_key"] = [f"{source.source_id}:{tid}" for tid in events.trial_id]
            events["source_stim_onset_imec_s"] = events.stim_onset_imec_s
            times = (events.stim_onset_nidq_s - ref["b"]) / ref["a"] + offset
            events["stim_onset_imec_s"] = [
                json.dumps({p.probe_id: t for p in source.probes}) for t in times
            ]
            if "attempt_id" in events:
                events["source_attempt_id"] = events.attempt_id
                events["attempt_id"] = source.source_id + ":" + events.attempt_id.astype(str)
            all_trials.append(trials)
            all_events.append(events)
            metadata.append(
                {
                    **source.to_dict(),
                    "offset_s": offset,
                    "offset_method": method,
                    "sync": sync,
                    "sync_dir": str(sync_dir),
                    "windows_nidq_s": windows,
                    "original_duration_s": ref_duration,
                    "n_trials": len(trials),
                    "empty_trials_nidq_s": empty_intervals,
                    "nidq_metadata": nidq_meta,
                    "probe_metadata": {
                        p.probe_id: {
                            "ap": SpikeGLXDiscovery.parse_meta(p.ap_meta),
                            "lf": SpikeGLXDiscovery.parse_meta(p.lf_meta) if p.lf_meta else None,
                        }
                        for p in source.probes
                    },
                }
            )
        if not segments:
            raise ValueError("所有记录都没有呈现刺激的 trial，没有可保留的神经数据。")
        event_tables = [events for events in all_events if not events.empty]
        if len({"planned_event_id" in events.columns for events in event_tables}) > 1:
            raise ValueError(
                "Joint sources must use the same behavioral event protocol; target and legacy events cannot be mixed"
            )
        manifest = SegmentManifest(
            segments,
            cfg.join_guard_s,
            metadata,
            first_time.isoformat(),
            getattr(self.session, "input_signature", ""),
        )
        for probe in self.session.probes:
            manifest.analysis_ranges(probe.probe_id)
        manifest.save(self.session.output_dir / "03_segments" / "segments.json")
        sync_root = self.session.output_dir / "04_sync"
        sync_root.mkdir(parents=True, exist_ok=True)
        pd.concat(all_trials, ignore_index=True).to_parquet(
            sync_root / "full_trials.parquet", index=False
        )
        pd.concat(event_tables or all_events, ignore_index=True).to_parquet(
            sync_root / "behavior_events.parquet", index=False
        )
        summary = {
            "joint_sorting_compatible": joint_error is None,
            "joint_sorting_error": joint_error,
            "n_sources": len(sources),
            "n_trials": sum(s["n_trials"] for s in metadata),
            "n_empty_trials": sum(len(s["empty_trials_nidq_s"]) for s in metadata),
            "n_blocks": len(manifest.for_probe("imec0")),
            "signature": manifest.signature,
            "nidq_durations_s": nidq_durations,
            "original_duration_s": sum(s["original_duration_s"] for s in metadata),
            "retained_duration_s": sum(
                s.length / s.sample_rate for s in manifest.for_probe("imec0")
            ),
            "max_sync_residual_ms": max(
                f["residual_ms"] for s in metadata for f in s["sync"].values()
            ),
        }
        (self.session.output_dir / "03_segments" / "summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        self._write_checkpoint(summary)
        self._report_progress("Task selection complete", 1.0)
