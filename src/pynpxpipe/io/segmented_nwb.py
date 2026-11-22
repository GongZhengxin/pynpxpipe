"""Combined NWB export retaining source clocks, gaps and raw sample values."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

import h5py
import numpy as np
import pandas as pd
from hdmf.backends.hdf5.h5_utils import H5DataIO
from pynwb import NWBHDF5IO, TimeSeries
from pynwb.behavior import EyeTracking, SpatialSeries
from pynwb.ecephys import ElectricalSeries
from pynwb.epoch import TimeIntervals

from pynpxpipe.core.segments import Segment, SegmentManifest
from pynpxpipe.io.bhv import BHV2Parser
from pynpxpipe.io.segment_recordings import load_source_stream

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pynpxpipe.core.session import ProbeInfo, Session
    from pynpxpipe.io.nwb_writer import NWBWriter


def series_name(segment: Segment, index: int) -> str:
    """Return a deterministic series name, also used by the NWB reader."""
    prefix = (
        "NIDQ_raw"
        if segment.stream == "nidq"
        else f"ElectricalSeries{segment.stream.upper()}_{segment.probe_id}"
    )
    return f"{prefix}__{segment.source_id}__{index:04d}"


def verify_manifest(path: Path, manifest: SegmentManifest) -> None:
    """Refuse stale partial exports before any raw append or repair."""
    with NWBHDF5IO(path, "r") as io:
        nf = io.read()
        if "segment_manifest" not in nf.scratch:
            raise ValueError("Existing NWB lacks the required segment mapping")
        stored = json.loads(nf.scratch["segment_manifest"].data)
        if stored.get("signature") != manifest.signature:
            raise ValueError("Existing NWB segment signature does not match this run")


def ensure_raw_electrodes(writer: NWBWriter, probe: ProbeInfo) -> None:
    """Export electrode metadata even when a probe has zero sorted units."""
    nf = writer._nwbfile
    if probe.probe_id in nf.electrode_groups:
        return
    rec = load_source_stream(
        writer.session, writer.session.recording_sources[0].source_id, probe.probe_id, "ap"
    )
    device = nf.create_device(
        name=probe.probe_id, description=f"{probe.probe_type} SN:{probe.serial_number}"
    )
    group = nf.create_electrode_group(
        name=probe.probe_id, description=probe.probe_type, location=probe.target_area, device=device
    )
    if nf.electrodes is None or "probe_id" not in nf.electrodes.colnames:
        nf.add_electrode_column("probe_id", "Probe identifier")
    if "channel_id" not in nf.electrodes.colnames:
        nf.add_electrode_column("channel_id", "Channel index within probe")
    if "inter_sample_shift" not in nf.electrodes.colnames:
        nf.add_electrode_column(
            "inter_sample_shift", "Per-channel ADC sample shift", data=[np.nan] * len(nf.electrodes)
        )
    locations = rec.get_channel_locations()
    shifts = rec.get_property("inter_sample_shift")
    for i in range(rec.get_num_channels()):
        nf.add_electrode(
            x=float(locations[i, 0]),
            y=float(locations[i, 1]),
            z=np.nan,
            location=probe.target_area,
            group=group,
            probe_id=probe.probe_id,
            channel_id=i,
            inter_sample_shift=float(shifts[i]) if shifts is not None else np.nan,
        )


def add_segment_metadata(writer: NWBWriter, manifest: SegmentManifest) -> None:
    """Store full trials, retained blocks and reversible source provenance."""
    nf = writer._nwbfile
    nf.add_scratch(
        json.dumps({**asdict(manifest), "signature": manifest.signature}),
        name="segment_manifest",
        description="Original frames, compressed sorting frames and experiment clocks",
    )
    nf.add_scratch(
        json.dumps({s["source_id"]: s["sync"] for s in manifest.sources}),
        name="sync_tables",
        description="Independent IMEC/NIDQ linear fits for each source",
    )
    blocks = TimeIntervals(
        name="task_blocks",
        description="Retained source data; half-open intervals in experiment seconds",
    )
    for name in (
        "source_id",
        "probe_id",
        "stream",
        "start_frame",
        "stop_frame",
        "concat_start",
        "series_name",
    ):
        blocks.add_column(name=name, description=name)
    for i, s in enumerate(manifest.segments):
        blocks.add_interval(
            start_time=float(s.time(s.start_frame)),
            stop_time=float(s.time(s.stop_frame)),
            source_id=s.source_id,
            probe_id=s.probe_id,
            stream=s.stream,
            start_frame=s.start_frame,
            stop_frame=s.stop_frame,
            concat_start=s.concat_start,
            series_name=series_name(s, i),
        )
    nf.add_time_intervals(blocks)
    trials = pd.read_parquet(writer.session.output_dir / "04_sync" / "full_trials.parquet")
    table = TimeIntervals(
        name="full_trials",
        description="Full interval of each retained behavioral trial (including unsuccessful presentations).",
    )
    columns = [c for c in trials.columns if c not in ("start_time", "stop_time")]
    for col in columns:
        table.add_column(col, col)
    for row in trials.to_dict("records"):
        table.add_interval(**row)
    nf.add_time_intervals(table)


def resolve_source_stimuli(session: Session, events: pd.DataFrame) -> pd.DataFrame:
    """Resolve each BHV2's stimulus table independently, preserving local indices."""
    from pynpxpipe.io.stim_resolver import (
        load_stim_map,
        resolve_dataset_tsv,
        resolve_target_stimuli,
    )

    result = events.copy()
    result["stim_name"] = ""
    result["stimulus_key"] = ""
    for source in session.recording_sources:
        mask = result.source_id == source.source_id
        subset = result[mask]
        if subset.empty:
            continue
        dataset = BHV2Parser(source.bhv_file).get_dataset_tsv_path()
        if "planned_event_id" in subset:
            path, mapping = resolve_target_stimuli(
                dataset, session.subject.image_vault_paths, subset, source.source_id
            )
            logger.info(
                "Verified stimulus package for %s: %s (%d events)",
                source.source_id,
                path,
                len(subset),
            )
        else:
            path, _ = resolve_dataset_tsv(dataset, session.subject.image_vault_paths)
            mapping = load_stim_map(path) if path else {}
        if "stim_index" in subset:
            result.loc[mask, "stim_name"] = subset.stim_index.astype(int).map(mapping).fillna("")
            result.loc[mask, "stimulus_key"] = (
                source.source_id + ":" + subset.stim_index.astype(int).astype(str)
            )
    return result


def add_segmented_eye(writer: NWBWriter, manifest: SegmentManifest) -> None:
    """Write trial eye samples at aligned times, retaining real trial gaps."""
    trials = pd.read_parquet(writer.session.output_dir / "04_sync" / "full_trials.parquet")
    tracking = EyeTracking(name="EyeTracking")
    count = 0
    for source in writer.session.recording_sources:
        source_trials = trials.loc[trials.source_id == source.source_id]
        if source_trials.empty:
            continue
        parser = BHV2Parser(source.bhv_file)
        eyes = parser.get_analog_data("Eye")
        ref = next(s for s in manifest.sources if s["source_id"] == source.source_id)["sync"][
            "imec0"
        ]
        for row in source_trials.itertuples():
            if row.trial_id not in eyes:
                continue
            data = np.asarray(eyes[row.trial_id])
            if data.ndim != 2 or data.shape[1] < 2 or len(data) == 0:
                continue
            interval = parser.get_sample_interval(trial_id=row.trial_id) / 1000 / ref["a"]
            times = row.bhv_zero_nidq_s + np.arange(len(data)) * interval
            keep = (times >= row.start_time) & (times < row.stop_time)
            if not keep.any():
                continue
            tracking.add_spatial_series(
                SpatialSeries(
                    name=f"eye_{source.source_id}_{row.trial_id}",
                    data=data[keep, :2],
                    timestamps=times[keep],
                    unit="degrees",
                    reference_frame="screen center",
                )
            )
            count += 1
    if count:
        module = writer._nwbfile.create_processing_module("behavior", "Aligned behavioral data")
        module.add(tracking)


def append_segmented_raw(
    session: Session,
    path: Path,
    manifest: SegmentManifest,
    callback: Callable[[str, float], None] | None = None,
) -> dict:
    """Stream selected blocks with per-block resume/repair and bit-exact checks.

    Raw values are copied unchanged. IMEC clocks are represented with transformed
    starting_time and rate; NIDQ retains all analog/digital words as ADC counts.
    """
    from pynpxpipe.io.nwb_writer import (
        NWBWriter,
        SpikeGLXDataChunkIterator,
        _get_compression_filter,
    )

    verify_manifest(path, manifest)
    written, repaired, scanned = [], [], {}
    for index, s in enumerate(manifest.segments):
        name = series_name(s, index)
        raw = load_source_stream(session, s.source_id, s.probe_id, s.stream)
        rec = raw.frame_slice(s.start_frame, s.stop_frame)
        expected_shape = (s.length, rec.get_num_channels())
        with h5py.File(path, "r") as handle:
            group = handle.get(f"acquisition/{name}")
            present = group is not None
            valid = present and group["data"].shape == expected_shape
            if valid:
                valid = np.isclose(
                    group["starting_time"][()], s.time(s.start_frame), atol=1e-10, rtol=0
                ) and np.isclose(group["starting_time"].attrs["rate"], s.sample_rate / s.time_scale)
            if valid and session.config.export.repair_verify == "full":
                valid = NWBWriter._stream_matches_source(group["data"], rec)
        if present and not valid:
            if not session.config.export.repair_incomplete_streams:
                raise ValueError(
                    f"Incomplete raw block {name}; enable export.repair_incomplete_streams"
                )
            with h5py.File(path, "a") as handle:
                del handle[f"acquisition/{name}"]
            repaired.append(name)
        if not valid:
            with NWBHDF5IO(path, "a") as io:
                nf = io.read()
                iterator = SpikeGLXDataChunkIterator(rec, buffer_gb=0.1, chunk_mb=1.0)
                data = H5DataIO(
                    iterator,
                    chunks=(min(40000, s.length), min(64, rec.get_num_channels())),
                    **_get_compression_filter(),
                )
                kwargs = {
                    "name": name,
                    "data": data,
                    "starting_time": float(s.time(s.start_frame)),
                    "rate": float(s.sample_rate / s.time_scale),
                    "description": json.dumps(
                        {
                            "source_id": s.source_id,
                            "start_frame": s.start_frame,
                            "stop_frame": s.stop_frame,
                        }
                    ),
                }
                if s.stream == "nidq":
                    series = TimeSeries(**kwargs, unit="ADC counts", conversion=1.0)
                else:
                    gains = rec.get_channel_gains()
                    if gains is None or not np.isfinite(gains).all():
                        raise ValueError(f"Missing/invalid channel gains for {name}")
                    offsets = rec.get_channel_offsets()
                    if (
                        offsets is None
                        or not np.isfinite(offsets).all()
                        or not np.all(offsets == offsets[0])
                    ):
                        raise ValueError(
                            f"Raw ElectricalSeries requires a common finite channel offset: {name}"
                        )
                    region = nf.create_electrode_table_region(
                        NWBWriter._find_electrode_indices(nf, s.probe_id, rec.get_num_channels()),
                        "Raw channels",
                    )
                    series = ElectricalSeries(
                        **kwargs,
                        electrodes=region,
                        conversion=1e-6,
                        offset=float(offsets[0]) * 1e-6,
                        channel_conversion=np.asarray(gains, dtype=float),
                    )
                nf.add_acquisition(series)
                io.write(nf)
            written.append(name)
        n_chunks = 0
        with h5py.File(path, "r") as handle:
            dataset = handle[f"acquisition/{name}/data"]
            for start in range(0, s.length, 200_000):
                stop = min(s.length, start + 200_000)
                if not np.array_equal(
                    dataset[start:stop], rec.get_traces(start_frame=start, end_frame=stop)
                ):
                    raise ValueError(f"Raw bit-exact verification failed: {name}, frame {start}")
                n_chunks += 1
        scanned[name] = n_chunks
        if callback:
            callback(f"export:Verified {name}", 0.65 + 0.35 * (index + 1) / len(manifest.segments))
    return {
        "streams_written": len(written),
        "streams_repaired": len(repaired),
        "stream_names": written,
        "verify_policy": "full",
        "n_chunks_scanned_per_stream": scanned,
    }
