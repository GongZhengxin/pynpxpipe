"""Full-trial anchors must match the same event in BHV and NIDQ clocks."""

import numpy as np
import pytest

from pynpxpipe.core.errors import SyncError
from pynpxpipe.io.bhv import TrialData
from pynpxpipe.io.sync.trial_intervals import align_trial_intervals


def _recorded_trials():
    # The first trial failed before any stimulus; the TTL is emitted separately.
    trials = [
        TrialData(1, 1, [(3.665, 9), (228.599, 0), (20913.139, 18)], end_ms=20948, trial_error=3),
        TrialData(
            2,
            1,
            [(2.741, 9), (152.243, 0), (1719.004, 64), (2835.769, 18)],
            end_ms=2872,
            trial_error=0,
        ),
    ]
    times = np.array([10.003665, 10.228599, 30.913139, 40.002741, 40.152243, 41.719004, 42.835769])
    codes = np.array([4, 1, 8, 4, 1, 32, 8])
    return trials, times, codes


@pytest.mark.parametrize("raw_code", [None, 9])
def test_bhv_marker_is_not_the_independent_trial_ttl(raw_code):
    trials, times, codes = _recorded_trials()
    result = align_trial_intervals(
        trials, times, codes, 0, raw_code, event_bits=[1, 2, 3, 4, 5, 6, 7]
    )
    np.testing.assert_allclose(result.start_time, [10, 40])
    np.testing.assert_allclose(result.stop_time, [30.948, 42.872])
    np.testing.assert_allclose(result.bhv_zero_nidq_s, [10, 40])
    assert result.trial_error.tolist() == [3, 0]
    assert result.bhv_anchor_code.tolist() == [9, 9]
    assert result.nidq_anchor_code.tolist() == [4, 4]
    np.testing.assert_allclose(result.nidq_anchor_s, times[[0, 3]])


def test_custom_code_and_event_bit_order_are_not_hardcoded():
    trial = TrialData(1, 1, [(100, 12), (900, 18)], end_ms=1000)
    result = align_trial_intervals(
        [trial], np.array([10.1, 10.3]), np.array([5, 2]), 1, None, event_bits=[3, 1, 2, 4, 5, 6, 7]
    )
    assert result.iloc[0].start_time == pytest.approx(10)
    assert result.iloc[0].bhv_anchor_code == 12
    assert result.iloc[0].nidq_anchor_code == 5


def test_explicit_marker_can_differ_from_first_event():
    trial = TrialData(1, 1, [(3, 9), (200, 2), (900, 18)], end_ms=1000)
    result = align_trial_intervals(
        [trial], np.array([10.2]), np.array([1]), 0, 2, event_bits=[1, 2, 3, 4, 5, 6, 7]
    )
    assert result.iloc[0].start_time == pytest.approx(10)


@pytest.mark.parametrize(
    ("case", "match"),
    [
        ("absent", "marker 2"),
        ("repeated", "marker 9"),
        ("different_first", "first"),
        ("collision", "collision"),
        ("missing_nidq", "NIDQ"),
        ("extra_nidq", "NIDQ"),
        ("outside_ttl", "TTL"),
        ("bad_extent", "timing"),
        ("nan_anchor", "timing"),
        ("nonmonotonic", "increasing"),
    ],
)
def test_ambiguous_or_invalid_anchors_are_rejected(case, match):
    trials, times, codes = _recorded_trials()
    raw_code = None
    if case == "absent":
        raw_code = 2
    elif case == "repeated":
        trials[0].events.append((500, 9))
    elif case == "different_first":
        trials[1].events[0] = (2.741, 8)
    elif case == "collision":
        trials[0].events.append((500, 8))
    elif case == "missing_nidq":
        times, codes = times[1:], codes[1:]
    elif case == "extra_nidq":
        times, codes = np.append(times, 60), np.append(codes, 4)
    elif case == "outside_ttl":
        times[1] = 35
        order = np.argsort(times)
        times, codes = times[order], codes[order]
    elif case == "bad_extent":
        trials[0].end_ms = 0
    elif case == "nan_anchor":
        trials[0].events[0] = (np.nan, 9)
    elif case == "nonmonotonic":
        times = times[::-1]
    with pytest.raises(SyncError, match=match):
        align_trial_intervals(trials, times, codes, 0, raw_code, event_bits=[1, 2, 3, 4, 5, 6, 7])


def test_unrecorded_marker_bits_do_not_anchor_to_zero_transitions():
    trial = TrialData(1, 1, [(3, 1), (900, 18)], end_ms=1000)
    with pytest.raises(SyncError, match="not recorded"):
        align_trial_intervals(
            [trial],
            np.array([10.0, 10.2]),
            np.array([0, 1]),
            0,
            None,
            event_bits=[1, 2, 3, 4, 5, 6, 7],
        )


def test_overlapping_full_trials_still_fail():
    trials, times, codes = _recorded_trials()
    trials[0].end_ms = 40000
    with pytest.raises(SyncError, match="overlap"):
        align_trial_intervals(trials, times, codes, 0, None, event_bits=[1, 2, 3, 4, 5, 6, 7])
