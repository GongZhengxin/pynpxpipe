"""SpikeInterface views and acquisition metadata for selected recordings."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import numpy as np
import spikeinterface.core as si

from pynpxpipe.core.segments import SegmentManifest
from pynpxpipe.io.spikeglx import SpikeGLXDiscovery, SpikeGLXLoader

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class AcquisitionRateRecording(si.BaseRecording):
    """Restore nominal sample coordinates without resampling exported raw values."""

    def __init__(self, recording: si.BaseRecording, sampling_frequency: float) -> None:
        super().__init__(sampling_frequency, recording.channel_ids, recording.get_dtype())
        recording.copy_metadata(self)
        self.add_recording_segment(_AcquisitionSegment(recording, sampling_frequency))
        self._kwargs = {"recording": recording, "sampling_frequency": sampling_frequency}


class _AcquisitionSegment(si.BaseRecordingSegment):
    def __init__(self, recording: si.BaseRecording, sampling_frequency: float) -> None:
        super().__init__(sampling_frequency=sampling_frequency)
        self.recording = recording

    def get_num_samples(self) -> int:
        return self.recording.get_num_samples()

    def get_traces(
        self, start_frame: int, end_frame: int, channel_indices: np.ndarray | slice
    ) -> np.ndarray:
        return self.recording.get_traces(
            start_frame=start_frame,
            end_frame=end_frame,
            channel_ids=self.recording.channel_ids[channel_indices],
        )


def validate_sources(session: Session) -> None:
    """Reject joint sorting across incompatible probe identities/configurations."""
    if len(session.recording_sources) < 2:
        return
    for source in session.recording_sources:
        if not source.probes:
            raise ValueError(f"{source.source_id}: no discovered probes; run discovery first")
        for probe in source.probes:
            if not probe.serial_number or probe.serial_number.lower() in ("unknown", "none"):
                raise ValueError(
                    f"{source.source_id}/{probe.probe_id}: joint sorting requires a probe serial "
                    f"number in {probe.ap_meta} (imDatPrb_sn or legacy imProbeSN). "
                    "Alignment preview is available; verify the acquisition metadata before joint sorting."
                )
    reference = session.recording_sources[0]
    for source in session.recording_sources[1:]:
        if {p.probe_id for p in source.probes} != {p.probe_id for p in reference.probes}:
            raise ValueError("All sources must have the same probes")
        for first in reference.probes:
            current = next(p for p in source.probes if p.probe_id == first.probe_id)
            for key in (
                "serial_number",
                "probe_type",
                "sample_rate",
                "n_channels",
                "channel_positions",
            ):
                if getattr(first, key) != getattr(current, key):
                    raise ValueError(f"{source.source_id}/{first.probe_id}: incompatible {key}")
            a = SpikeGLXDiscovery.parse_meta(first.ap_meta)
            b = SpikeGLXDiscovery.parse_meta(current.ap_meta)
            for key in (
                "snsSaveChanSubset",
                "snsChanMap",
                "snsShankMap",
                "snsGeomMap",
                "imroTbl",
                "~snsChanMap",
                "~snsShankMap",
                "~snsGeomMap",
                "~imroTbl",
                "imAiRangeMax",
                "imMaxInt",
            ):
                if a.get(key) != b.get(key):
                    raise ValueError(f"{source.source_id}/{first.probe_id}: incompatible {key}")
            if a.get("fileCreateTime", "")[:10] != b.get("fileCreateTime", "")[:10]:
                raise ValueError("Joint sources must belong to the same recording day")


def acquisition_start(meta: dict, timezone: str | None) -> datetime:
    """Read an acquisition timestamp without guessing its timezone."""
    value = meta.get("fileCreateTime")
    if not value:
        raise ValueError("Missing fileCreateTime; an acquisition timestamp is required")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        if not timezone:
            raise ValueError(
                "Acquisition timestamp has no timezone; set task_windows.recording_timezone (IANA name)"
            )
        zone = ZoneInfo(timezone)
        if (
            dt.replace(tzinfo=zone, fold=0).utcoffset()
            != dt.replace(tzinfo=zone, fold=1).utcoffset()
        ):
            raise ValueError("Ambiguous acquisition local time; supply a timestamp with UTC offset")
        dt = dt.replace(tzinfo=zone)
    return dt


def load_source_stream(
    session: Session, source_id: str, probe_id: str, stream: str
) -> si.BaseRecording:
    """Load a raw stream lazily, excluding IMEC digital channels for NWB/AP."""
    source = next(s for s in session.recording_sources if s.source_id == source_id)
    if stream == "nidq":
        binary, meta = SpikeGLXDiscovery(source.session_dir).discover_nidq()
        return SpikeGLXLoader.load_nidq(binary, meta)
    probe = next(p for p in source.probes if p.probe_id == probe_id)
    if stream == "ap":
        return SpikeGLXLoader.load_ap(probe)
    return SpikeGLXLoader.load_lf(probe)


def analysis_recording(
    recording: si.BaseRecording, manifest: SegmentManifest, probe_id: str
) -> si.BaseRecording:
    """Expose join-free analysis segments from a concatenated processed stream."""
    return si.append_recordings(
        [recording.frame_slice(start, stop) for start, stop in manifest.analysis_ranges(probe_id)]
    )


def split_analysis_sorting(
    sorting: si.BaseSorting, manifest: SegmentManifest, probe_id: str, recording: si.BaseRecording
) -> si.BaseSorting:
    """Split shared unit IDs while excluding join guards from observations."""
    segments = manifest.for_probe(probe_id)
    total = sum(s.length for s in segments)
    if sorting.get_num_segments() != 1:
        raise ValueError("Joint sorter output must use one concatenated segment")
    vector = sorting.to_spike_vector()
    if len(vector) and (vector["sample_index"].min() < 0 or vector["sample_index"].max() >= total):
        raise ValueError("Imported sorting contains frames outside the selected recording")
    if not np.isclose(sorting.get_sampling_frequency(), segments[0].sample_rate, rtol=0, atol=1e-8):
        raise ValueError("Sorting sampling frequency does not match selected sources")
    split = si.split_sorting(
        sorting,
        [recording.frame_slice(s.concat_start, s.concat_start + s.length) for s in segments],
    )
    parts = []
    for i, (s, (start, stop)) in enumerate(
        zip(segments, manifest.analysis_ranges(probe_id), strict=True)
    ):
        part = si.select_segment_sorting(split, i)
        parts.append(part.frame_slice(start - s.concat_start, stop - s.concat_start))
    from dataclasses import asdict

    result = si.append_sortings(parts)
    result.annotate(
        segment_manifest={**asdict(manifest), "signature": manifest.signature}, probe_id=probe_id
    )
    return result


def check_channel_compatibility(first: si.BaseRecording, current: si.BaseRecording) -> None:
    """Validate effective channel order, gains, offsets and geometry before concat."""
    for method in (
        "get_channel_ids",
        "get_channel_gains",
        "get_channel_offsets",
        "get_channel_locations",
    ):
        a, b = getattr(first, method)(), getattr(current, method)()
        if a is None or b is None:
            if a is not b:
                raise ValueError(f"Incompatible {method}")
        elif not np.array_equal(a, b, equal_nan=np.asarray(a).dtype.kind in "fc"):
            raise ValueError(f"Incompatible {method}")
