"""Time selection contracts; all times are half-open intervals."""

import numpy as np
import pandas as pd
import pytest

from pynpxpipe.core.config import TaskWindowConfig
from pynpxpipe.core.segments import Segment, SegmentManifest, presented_events, select_task_windows


@pytest.mark.parametrize("gap,count", [(179, 1), (180, 1), (181, 2)])
def test_idle_threshold_measured_from_trial_end(gap, count):
    windows = select_task_windows(
        [(100, 110), (110 + gap, 120 + gap)], 4000, TaskWindowConfig(enabled=True)
    )
    assert len(windows) == count
    assert windows[0][0] == 70
    assert windows[-1][1] == 150 + gap


def test_sparse_trials_padding_clipping_and_overlap():
    cfg = TaskWindowConfig(enabled=True, max_idle_s=1)
    assert select_task_windows([(5, 10), (50, 60), (3500, 3510)], 3520, cfg) == [
        (0.0, 90.0),
        (3470.0, 3520.0),
    ]


def test_invalid_or_missing_trials_cannot_silently_crop():
    for intervals in ([], [(10, 9)], [(0, np.nan)], [(100, 110)]):
        with pytest.raises(ValueError):
            select_task_windows(intervals, 50, TaskWindowConfig(enabled=True))


def test_presentation_evidence_in_new_and_legacy_event_tables():
    events = pd.DataFrame(
        {
            "stim_onset_bhv_ms": [0, np.nan, np.inf],
            "stim_onset_nidq_s": [np.nan, 1, np.inf],
            "planned_event_id": [1, 2, 3],
        }
    )
    assert presented_events(events).index.tolist() == [0]
    assert presented_events(events.drop(columns="stim_onset_bhv_ms")).index.tolist() == [1]
    with pytest.raises(ValueError, match="刺激呈现时间"):
        presented_events(events[["planned_event_id"]])


def test_frame_time_round_trip_and_signature(tmp_path):
    segs = [
        Segment("a", "imec0", 100, 200, 0, 1000, 1.0, 0.0),
        Segment("b", "imec0", 400, 500, 100, 1000, 1.001, 10.0),
    ]
    manifest = SegmentManifest(segs, join_guard_s=0.01)
    frames = np.array([0, 99, 100, 199])
    times = manifest.frames_to_times("imec0", frames)
    np.testing.assert_allclose(times, [0.1, 0.199, 10.4004, 10.499499])
    np.testing.assert_array_equal(manifest.times_to_frames("imec0", times), frames)
    assert manifest.times_to_frames("imec0", np.array([5.0])).tolist() == [-1]
    path = tmp_path / "segments.json"
    manifest.save(path)
    assert SegmentManifest.load(path).signature == manifest.signature
    with pytest.raises(ValueError):
        manifest.frames_to_times("imec0", np.array([200]))


def test_guards_remove_only_joins_from_observation():
    manifest = SegmentManifest(
        [
            Segment("a", "imec0", 0, 1000, 0, 1000, 1, 0),
            Segment("b", "imec0", 0, 1000, 1000, 1000, 1, 10),
        ],
        join_guard_s=0.1,
    )
    assert manifest.analysis_ranges("imec0") == [(0, 900), (1100, 2000)]
    np.testing.assert_allclose(manifest.observation_intervals("imec0"), [[0, 0.9], [10.1, 11]])
