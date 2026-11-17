"""Bounded single-channel reads for long acquisition streams."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from spikeinterface.core import BaseRecording


class ChannelSignal:
    """Array-like lazy channel view with bounded, numerically stable statistics."""

    def __init__(
        self,
        recording: BaseRecording,
        channel_index: int,
        scale: float = 1.0,
        chunk_frames: int = 1_000_000,
    ) -> None:
        self.recording = recording
        self.channel_id = recording.channel_ids[channel_index]
        self.scale = scale
        self.chunk_frames = chunk_frames

    def __len__(self) -> int:
        return int(self.recording.get_num_samples())

    def __getitem__(self, selection: slice) -> np.ndarray:
        start, stop, step = selection.indices(len(self))
        values = self.recording.get_traces(
            start_frame=start, end_frame=stop, channel_ids=[self.channel_id]
        )[:, 0]
        return values[::step].astype(float) * self.scale

    def voltage(self, factor: float) -> ChannelSignal:
        """Return a scaled view without loading data."""
        view = ChannelSignal(self.recording, 0, self.scale * factor, self.chunk_frames)
        view.channel_id = self.channel_id
        return view

    def variance(self) -> float:
        """Compute population variance using parallel/streaming Welford updates."""
        count, mean, m2 = 0, 0.0, 0.0
        for start in range(0, len(self), self.chunk_frames):
            block = self[start : min(start + self.chunk_frames, len(self))]
            n = len(block)
            delta = float(block.mean()) - mean
            total = count + n
            m2 += float(np.var(block)) * n + delta * delta * count * n / total
            mean += delta * n / total
            count = total
        return m2 / count if count else 0.0


def digital_transitions(
    recording: BaseRecording,
    bits: list[int],
    sample_rate: float,
    *,
    rising_only: bool = False,
    chunk_frames: int = 1_000_000,
) -> tuple[np.ndarray, np.ndarray]:
    """Decode changes while retaining the previous word across chunk boundaries."""
    signal = ChannelSignal(recording, -1, chunk_frames=chunk_frames)
    times, codes = [], []
    previous = None
    for start in range(0, len(signal), chunk_frames):
        word = signal[start : min(start + chunk_frames, len(signal))].astype(np.uint16)
        values = np.zeros(len(word), dtype=np.int32)
        for i, bit in enumerate(bits):
            values |= ((word >> bit) & 1).astype(np.int32) << i
        prior = values[0] if previous is None else previous
        diff = np.diff(values, prepend=prior)
        indices = np.flatnonzero(diff > 0 if rising_only else diff != 0)
        times.extend(((indices + start) / sample_rate).tolist())
        codes.extend(values[indices].tolist())
        previous = values[-1]
    return np.array(times, dtype=float), np.array(codes, dtype=np.int32)
