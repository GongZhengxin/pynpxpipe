"""Reversible mappings between sorting frames and acquisition clocks.

Sample ranges are half-open. Gaps are never interpreted as silent observation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from pynpxpipe.core.config import TaskWindowConfig

if TYPE_CHECKING:
    from spikeinterface.core import BaseSorting

    from pynpxpipe.core.session import Session


def select_task_windows(
    trials: list[tuple[float, float]], duration_s: float, config: TaskWindowConfig
) -> list[tuple[float, float]]:
    """Group complete trials by idle gap, then pad, clamp and merge overlaps.

    Raises:
        ValueError: If boundaries are missing, nonfinite or outside the recording.
    """
    if not np.isfinite(duration_s) or duration_s <= 0:
        raise ValueError("Recording duration must be positive")
    if not config.enabled:
        return [(0.0, float(duration_s))]
    if not trials:
        raise ValueError("No reliable trial intervals; refusing to discard neural data")
    blocks: list[list[float]] = []
    for start, stop in sorted(trials):
        if (
            not np.isfinite([start, stop]).all()
            or stop <= start
            or stop <= 0
            or start >= duration_s
        ):
            raise ValueError(f"Invalid or out-of-recording trial interval: {(start, stop)}")
        if blocks and start - blocks[-1][1] <= config.max_idle_s:
            blocks[-1][1] = max(stop, blocks[-1][1])
        else:
            blocks.append([start, stop])
    windows: list[tuple[float, float]] = []
    for start, stop in blocks:
        start = max(0.0, start - config.padding_before_s)
        stop = min(duration_s, stop + config.padding_after_s)
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], stop))
        else:
            windows.append((start, stop))
    return windows


@dataclass(frozen=True)
class Segment:
    """One retained source interval and its affine experiment-time mapping."""

    source_id: str
    probe_id: str
    start_frame: int
    stop_frame: int
    concat_start: int
    sample_rate: float
    time_scale: float
    time_offset: float
    stream: str = "ap"

    def __post_init__(self) -> None:
        if self.start_frame < 0 or self.stop_frame <= self.start_frame or self.concat_start < 0:
            raise ValueError("Invalid half-open segment frame range")
        if (
            not np.isfinite([self.sample_rate, self.time_scale, self.time_offset]).all()
            or self.sample_rate <= 0
            or self.time_scale <= 0
        ):
            raise ValueError("Segment clocks must be finite and increasing")

    @property
    def length(self) -> int:
        return self.stop_frame - self.start_frame

    def time(self, frame: np.ndarray | float) -> np.ndarray | float:
        """Convert an original-source sample coordinate to experiment seconds."""
        return frame / self.sample_rate * self.time_scale + self.time_offset


@dataclass
class SegmentManifest:
    """Persistent mapping shared by processing, export, import and resume."""

    segments: list[Segment]
    join_guard_s: float = 0.1
    sources: list[dict] = field(default_factory=list)
    session_start_time: str | None = None
    input_signature: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        if not np.isfinite(self.join_guard_s) or self.join_guard_s < 0:
            raise ValueError("Invalid join guard")
        for key in {(s.probe_id, s.stream) for s in self.segments}:
            offset = 0
            last_stop = -np.inf
            for s in self.for_probe(*key):
                if s.concat_start != offset or s.time(s.start_frame) < last_stop - 1e-9:
                    raise ValueError(
                        "Segments must have contiguous sorting frames and ordered, nonoverlapping real times"
                    )
                offset += s.length
                last_stop = s.time(s.stop_frame)

    def for_probe(self, probe_id: str, stream: str = "ap") -> list[Segment]:
        """Return ordered segments of a probe/stream."""
        return [s for s in self.segments if s.probe_id == probe_id and s.stream == stream]

    @property
    def signature(self) -> str:
        return hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, allow_nan=False).encode()
        ).hexdigest()

    def save(self, path: Path) -> None:
        """Atomically persist the mapping and its integrity signature."""
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({**asdict(self), "signature": self.signature}, indent=2), encoding="utf-8"
        )
        temporary.replace(path)

    @classmethod
    def load(cls, path: Path) -> SegmentManifest:
        """Read a mapping and reject corruption or unsupported versions."""
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> SegmentManifest:
        """Validate a persisted mapping (including NWB scratch storage)."""
        raw = dict(raw)
        signature = raw.pop("signature")
        if raw.get("version") != 1:
            raise ValueError("Unsupported segment manifest version")
        raw["segments"] = [Segment(**s) for s in raw["segments"]]
        manifest = cls(**raw)
        if signature != manifest.signature:
            raise ValueError("Segment manifest signature mismatch")
        return manifest

    def frames_to_times(self, probe_id: str, frames: np.ndarray) -> np.ndarray:
        """Map concatenated sorting frames to real experiment time; reject gaps."""
        frames = np.asarray(frames)
        result = np.full(frames.shape, np.nan)
        for s in self.for_probe(probe_id):
            mask = (frames >= s.concat_start) & (frames < s.concat_start + s.length)
            result[mask] = s.time(frames[mask] - s.concat_start + s.start_frame)
        if np.isnan(result).any():
            raise ValueError("Sorting frames outside retained segments")
        return result

    def times_to_frames(self, probe_id: str, times: np.ndarray) -> np.ndarray:
        """Map experiment seconds to concatenated frames; return -1 in gaps."""
        times = np.asarray(times)
        result = np.full(times.shape, -1, dtype=np.int64)
        for s in self.for_probe(probe_id):
            source = np.rint((times - s.time_offset) / s.time_scale * s.sample_rate).astype(
                np.int64
            )
            mask = (source >= s.start_frame) & (source < s.stop_frame)
            result[mask] = source[mask] - s.start_frame + s.concat_start
        return result

    def analysis_ranges(self, probe_id: str) -> list[tuple[int, int]]:
        """Sorting-frame ranges after excluding both sides of each join."""
        segments = self.for_probe(probe_id)
        ranges = []
        for i, s in enumerate(segments):
            guard = int(np.ceil(self.join_guard_s * s.sample_rate))
            start = s.concat_start + (guard if i > 0 else 0)
            stop = s.concat_start + s.length - (guard if i < len(segments) - 1 else 0)
            if start >= stop:
                raise ValueError("Join guard consumes an entire retained segment")
            ranges.append((start, stop))
        return ranges

    def observation_intervals(self, probe_id: str) -> np.ndarray:
        """Return observed, guard-excluded intervals in real experiment seconds."""
        return np.array(
            [
                [
                    s.time(start - s.concat_start + s.start_frame),
                    s.time(stop - s.concat_start + s.start_frame),
                ]
                for s, (start, stop) in zip(
                    self.for_probe(probe_id), self.analysis_ranges(probe_id), strict=True
                )
            ]
        )

    def unit_times(self, sorting: BaseSorting, probe_id: str, unit_id: int | str) -> np.ndarray:
        """Restore a split analysis sorting's spikes to experiment time."""
        ranges = self.analysis_ranges(probe_id)
        if sorting.get_num_segments() != len(ranges):
            raise ValueError("Sorting segment count does not match the time mapping")
        return np.concatenate(
            [
                self.frames_to_times(
                    probe_id, sorting.get_unit_spike_train(unit_id, segment_index=i) + start
                )
                for i, (start, _) in enumerate(ranges)
            ]
        )


def load_manifest(session: Session) -> SegmentManifest | None:
    """Load the mapping only when selection/joint processing is enabled."""
    if not getattr(session, "segmented", False):
        return None
    return SegmentManifest.load(session.output_dir / "03_segments" / "segments.json")
