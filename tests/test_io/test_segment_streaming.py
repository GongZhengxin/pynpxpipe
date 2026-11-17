"""Bounded synchronization and full-trial alignment regression tests."""

import numpy as np
import pytest
import spikeinterface.core as si

from pynpxpipe.core.errors import SyncError
from pynpxpipe.io.bhv import TrialData
from pynpxpipe.io.streaming import ChannelSignal, digital_transitions
from pynpxpipe.io.sync.photodiode_calibrate import calibrate_photodiode
from pynpxpipe.io.sync.trial_intervals import align_trial_intervals


def test_digital_changes_across_chunks_and_only_one_channel(monkeypatch):
    data = np.zeros((32, 5), dtype=np.int16)
    data[7:11, -1] = 2
    data[16:20, -1] = 4
    rec = si.NumpyRecording(data, 1000)
    original = rec.get_traces
    calls = []

    def bounded(**kwargs):
        assert kwargs["end_frame"] - kwargs["start_frame"] <= 8
        assert kwargs["channel_ids"] == [4]
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(rec, "get_traces", bounded)
    times, codes = digital_transitions(rec, [1, 2], 1000, chunk_frames=8)
    np.testing.assert_allclose(times, [0.007, 0.011, 0.016, 0.020])
    np.testing.assert_array_equal(codes, [1, 0, 2, 0])
    assert len(calls) == 4


def test_streamed_photodiode_matches_full_array():
    rng = np.random.default_rng(7)
    signal = rng.normal(0, 3, 5000).astype(np.int16)
    onsets = np.array([0.5, 1.5, 2.5, 4.0])
    for onset in onsets:
        start = int(onset * 1000)
        signal[start + 15 : start + 100] += 1000
    rec = si.NumpyRecording(signal[:, None], 1000)
    expected = calibrate_photodiode(signal, 1000, 5, onsets, monitor_delay_ms=-5)
    actual = calibrate_photodiode(
        ChannelSignal(rec, 0, chunk_frames=127), 1000, 5, onsets, monitor_delay_ms=-5
    )
    np.testing.assert_allclose(actual.stim_onset_nidq_s, expected.stim_onset_nidq_s)
    np.testing.assert_array_equal(actual.quality_flags, expected.quality_flags)


def test_failed_and_stimulus_free_trials_preserve_extent_and_trial_zero():
    trials = [
        TrialData(1, 1, [(120, 2), (1100, 9)], end_ms=1200, trial_error=0),
        TrialData(2, 1, [(80, 2), (400, 9)], end_ms=450, trial_error=4),
    ]
    intervals = align_trial_intervals(trials, np.array([10.0, 300.0]), np.array([1, 1]), 0, 2)
    np.testing.assert_allclose(intervals.start_time, [9.88, 299.92])
    np.testing.assert_allclose(intervals.stop_time, [11.08, 300.37])
    assert intervals.trial_error.tolist() == [0, 4]
    with pytest.raises(SyncError, match="every"):
        align_trial_intervals(trials, np.array([10.0]), np.array([1]), 0, 2)
    with pytest.raises(SyncError, match="marker"):
        align_trial_intervals(trials, np.array([10.0, 300.0]), np.array([1, 1]), 0, 32)
