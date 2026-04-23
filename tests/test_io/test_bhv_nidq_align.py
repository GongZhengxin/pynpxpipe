"""Tests for io/sync/bhv_nidq_align.py — TDD (RED → GREEN → REFACTOR)."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from pynpxpipe.core.errors import PynpxpipeError, SyncError
from pynpxpipe.io.sync.bhv_nidq_align import TrialAlignment, align_bhv2_to_nidq

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bhv_parser(
    trials_data: list[dict],
    metadata: dict | None = None,
) -> MagicMock:
    """Build a mock BHV2Parser from a compact description.

    Each entry in trials_data should be a dict with:
        trial_id (int), condition_id (int),
        events: list of (time_ms, code) tuples,
        user_vars: dict (optional)
    """
    if metadata is None:
        metadata = {
            "ExperimentName": "test_exp",
            "MLVersion": "2.0",
            "SubjectName": "Monkey",
            "TotalTrials": len(trials_data),
        }

    from pynpxpipe.io.bhv import TrialData

    trial_objs = [
        TrialData(
            trial_id=d["trial_id"],
            condition_id=d["condition_id"],
            events=d.get("events", []),
            user_vars=d.get("user_vars", {}),
            variable_changes=d.get("variable_changes", {}),
        )
        for d in trials_data
    ]

    parser = MagicMock()
    parser.parse.return_value = trial_objs
    parser.get_session_metadata.return_value = metadata

    # get_event_code_times: scan events in all trials
    def _get_event_code_times(event_code, trials=None):
        result = []
        for t in trial_objs:
            if trials is not None and t.trial_id not in trials:
                continue
            for time_ms, code in t.events:
                if code == event_code:
                    result.append((t.trial_id, time_ms))
        return result

    parser.get_event_code_times.side_effect = _get_event_code_times
    return parser


def _make_nidq_events(
    n_trials: int,
    trial_start_bit: int = 1,
    onset_times: list[float] | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Build NIDQ event arrays with exactly n_trials trial-start events on trial_start_bit."""
    if onset_times is None:
        onset_times = [float(i + 1) for i in range(n_trials)]
    code_val = 2**trial_start_bit
    times = np.array(onset_times, dtype=np.float64)
    codes = np.full(n_trials, code_val, dtype=int)
    return times, codes


def _make_nidq_events_with_stim(
    trial_anchors_s: list[float],
    stim_times_per_trial_s: list[list[float]],
    *,
    trial_start_bit: int = 1,
    stim_onset_bit: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    """Build NIDQ event arrays containing BOTH trial_start and stim_onset rising edges.

    Args:
        trial_anchors_s: Absolute NIDQ times (s) for each trial start rising.
        stim_times_per_trial_s: Per-trial list of absolute NIDQ stim rising times.
            Length must equal len(trial_anchors_s). Each inner list is the absolute
            NIDQ time of each stim in that trial (not an offset — absolute).
        trial_start_bit: Decoded-domain bit index for trial_start. Default 1.
        stim_onset_bit: Decoded-domain bit index for stim_onset. Default 5
            (matches real data: decoded bit 5 = ML raw bit 6 = BHV code 64).

    Returns:
        (event_times_s, event_codes) sorted by time.
    """
    assert len(trial_anchors_s) == len(stim_times_per_trial_s)
    trial_code = 1 << trial_start_bit
    stim_code = 1 << stim_onset_bit

    rows: list[tuple[float, int]] = []
    for anchor, stims in zip(trial_anchors_s, stim_times_per_trial_s, strict=True):
        rows.append((float(anchor), trial_code))
        for s in stims:
            rows.append((float(s), stim_code))
    rows.sort(key=lambda x: x[0])

    times = np.array([r[0] for r in rows], dtype=np.float64)
    codes = np.array([r[1] for r in rows], dtype=int)
    return times, codes


# ---------------------------------------------------------------------------
# Normal alignment flow
# ---------------------------------------------------------------------------


class TestPerfectAlignment:
    def test_perfect_alignment_returns_dataframe(self):
        """3-trial alignment returns a TrialAlignment with 3-row DataFrame."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": i,
                "condition_id": i * 10,
                "events": [(100.0, stim_code)],
            }
            for i in range(1, 4)
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(3, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        assert isinstance(result, TrialAlignment)
        assert isinstance(result.trial_events_df, pd.DataFrame)
        assert len(result.trial_events_df) == 3

    def test_onset_nidq_s_column_values(self):
        """onset_nidq_s column matches NIDQ input times directly."""
        stim_code = 64
        onset_times = [1.0, 2.0, 3.0]
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]} for i in range(1, 4)
        ]
        parser = _make_bhv_parser(trials_data)
        times = np.array(onset_times, dtype=np.float64)
        codes = np.full(3, 2**1, dtype=int)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        np.testing.assert_array_almost_equal(
            result.trial_events_df["onset_nidq_s"].to_numpy(), onset_times
        )

    def test_stim_onset_nidq_s_offset_correct(self):
        """stim_onset_nidq_s = onset_nidq_s + bhv2_offset_s."""
        stim_code = 64
        # BHV2 trial onset at time 0 ms, stim onset at 200 ms → offset = 200 ms
        # But bhv_parser doesn't give us trial onset time directly in this interface;
        # we test the offset by placing trial events at time 0 ms (trial onset) and
        # stim event at 200 ms. The relative offset is 200 ms = 0.2 s.
        # NIDQ onset times: [1.0, 2.0, 3.0]
        onset_times = [1.0, 2.0, 3.0]
        # BHV2 events: each trial has onset at 0 ms, stim at 200 ms
        trials_data = [
            {
                "trial_id": i,
                "condition_id": 1,
                # No explicit trial onset event stored; stim onset at 200 ms
                "events": [(200.0, stim_code)],
            }
            for i in range(1, 4)
        ]
        # BHV2 trial onset times are implicit (trial_start in BHV2 = 0 ms by convention)
        # The relative offset in BHV2 time from trial start to stim: 200 ms
        # But spec step 6: offset = stim_time_ms - trial_onset_time_ms_bhv
        # trial_onset_time_ms_bhv is the time of the first event with trial start code,
        # but BHV2 doesn't have a separate "trial onset" event in the same sense.
        # Per spec: offset = stim_time_ms - trial_onset_time_ms_bhv
        # In BHV2, trial onset time = 0 ms (start of trial) by convention.
        # So offset_s = 200/1000 = 0.2 s
        parser = _make_bhv_parser(trials_data)
        times = np.array(onset_times, dtype=np.float64)
        codes = np.full(3, 2**1, dtype=int)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        expected = np.array(onset_times) + 0.2
        np.testing.assert_array_almost_equal(
            result.trial_events_df["stim_onset_nidq_s"].to_numpy(), expected
        )

    def test_condition_id_preserved(self):
        """condition_id column matches BHV2 trial condition IDs."""
        stim_code = 64
        condition_ids = [5, 7, 3]
        trials_data = [
            {"trial_id": i + 1, "condition_id": cid, "events": [(100.0, stim_code)]}
            for i, cid in enumerate(condition_ids)
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(3, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        assert result.trial_events_df["condition_id"].tolist() == condition_ids

    def test_trial_valid_column_is_nan(self):
        """trial_valid column is all NaN (placeholder for postprocess)."""
        stim_code = 64
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]} for i in range(1, 4)
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(3, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        assert result.trial_events_df["trial_valid"].isna().all()

    def test_dataset_name_extracted(self):
        """dataset_name is extracted from bhv_metadata['DatasetName']."""
        stim_code = 64
        trials_data = [{"trial_id": 1, "condition_id": 1, "events": [(100.0, stim_code)]}]
        metadata = {
            "ExperimentName": "test",
            "MLVersion": "2.0",
            "SubjectName": "M",
            "TotalTrials": 1,
            "DatasetName": "exp_20260101",
        }
        parser = _make_bhv_parser(trials_data, metadata=metadata)
        times, codes = _make_nidq_events(1, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        assert result.dataset_name == "exp_20260101"

    def test_bhv_metadata_populated(self):
        """bhv_metadata dict is populated from get_session_metadata()."""
        stim_code = 64
        trials_data = [{"trial_id": 1, "condition_id": 1, "events": [(100.0, stim_code)]}]
        metadata = {
            "ExperimentName": "test",
            "MLVersion": "2.0",
            "SubjectName": "M",
            "TotalTrials": 42,
        }
        parser = _make_bhv_parser(trials_data, metadata=metadata)
        times, codes = _make_nidq_events(1, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        assert result.bhv_metadata["TotalTrials"] == 42

    def test_detected_trial_start_bit_matches_input(self):
        """detected_trial_start_bit equals the explicitly provided trial_start_bit."""
        stim_code = 64
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]} for i in range(1, 4)
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(3, trial_start_bit=3)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=3,
        )

        assert result.detected_trial_start_bit == 3

    def test_trial_id_column_1indexed(self):
        """trial_id column is 1-indexed matching BHV2 trial IDs."""
        stim_code = 64
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]} for i in range(1, 4)
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(3, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        assert result.trial_events_df["trial_id"].tolist() == [1, 2, 3]


# ---------------------------------------------------------------------------
# Auto-detect trial_start_bit
# ---------------------------------------------------------------------------


class TestAutoDetectTrialStartBit:
    def test_auto_detect_selects_correct_bit(self):
        """When trial_start_bit=None, auto-detect picks the bit whose count matches n_bhv."""
        stim_code = 64
        n_bhv = 5
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]}
            for i in range(1, n_bhv + 1)
        ]
        parser = _make_bhv_parser(trials_data)

        # Build NIDQ events: bit=2 has n_bhv events, bit=0 has 2 events, rest noise
        code_bit2 = 2**2  # 4
        times = np.array([float(i) for i in range(n_bhv + 2)], dtype=np.float64)
        codes = np.array(
            [code_bit2] * n_bhv + [2**0, 2**0],  # 5x bit2 + 2x bit0
            dtype=int,
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=None,
        )

        assert result.detected_trial_start_bit == 2

    def test_auto_detect_picks_closest_count(self):
        """Auto-detect picks bit=2 (count=10) over bit=1 (count=5) when n_bhv=10."""
        stim_code = 64
        n_bhv = 10
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]}
            for i in range(1, n_bhv + 1)
        ]
        parser = _make_bhv_parser(trials_data)

        code_bit1 = 2**1  # 2
        code_bit2 = 2**2  # 4
        times = np.arange(15, dtype=np.float64)
        codes = np.array(
            [code_bit1] * 5 + [code_bit2] * 10,
            dtype=int,
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=None,
        )

        assert result.detected_trial_start_bit == 2

    def test_auto_detect_fails_no_matching_bit(self):
        """Auto-detect raises SyncError if no bit count is within tolerance."""
        stim_code = 64
        n_bhv = 10
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]}
            for i in range(1, n_bhv + 1)
        ]
        parser = _make_bhv_parser(trials_data)

        # All bits have count far from n_bhv=10 (only 1 event total)
        times = np.array([1.0], dtype=np.float64)
        codes = np.array([2**0], dtype=int)

        with pytest.raises(SyncError):
            align_bhv2_to_nidq(
                bhv_parser=parser,
                nidq_event_times=times,
                nidq_event_codes=codes,
                stim_onset_code=stim_code,
                trial_start_bit=None,
                trial_count_tolerance=2,
            )

    def test_explicit_bit_skips_auto_detect(self):
        """Explicit trial_start_bit=5 is used even if another bit would match better."""
        stim_code = 64
        n_bhv = 3
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]}
            for i in range(1, n_bhv + 1)
        ]
        parser = _make_bhv_parser(trials_data)

        # bit=1 has 3 events (perfect), bit=5 has 3 events too
        code_bit1 = 2**1
        code_bit5 = 2**5
        times = np.arange(6, dtype=np.float64)
        codes = np.array([code_bit1] * 3 + [code_bit5] * 3, dtype=int)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=5,
        )

        assert result.detected_trial_start_bit == 5


# ---------------------------------------------------------------------------
# trial count mismatch handling
# ---------------------------------------------------------------------------


class TestTrialCountMismatch:
    def test_trial_count_within_tolerance_truncates(self):
        """n_bhv=10, n_nidq=11, tolerance=2 → no error, 10-row DataFrame."""
        stim_code = 64
        n_bhv = 10
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]}
            for i in range(1, n_bhv + 1)
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(11, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            trial_count_tolerance=2,
        )

        assert len(result.trial_events_df) == 10

    def test_trial_count_exceeds_tolerance_raises(self):
        """n_bhv=10, n_nidq=15, tolerance=2 → SyncError with 'mismatch' in message."""
        stim_code = 64
        n_bhv = 10
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]}
            for i in range(1, n_bhv + 1)
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(15, trial_start_bit=1)

        with pytest.raises(SyncError, match="mismatch"):
            align_bhv2_to_nidq(
                bhv_parser=parser,
                nidq_event_times=times,
                nidq_event_codes=codes,
                stim_onset_code=stim_code,
                trial_start_bit=1,
                trial_count_tolerance=2,
            )

    def test_trial_count_exact_match(self):
        """n_bhv=n_nidq=20 → no error, 20-row DataFrame."""
        stim_code = 64
        n_bhv = 20
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]}
            for i in range(1, n_bhv + 1)
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(20, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        assert len(result.trial_events_df) == 20

    def test_bhv2_longer_truncated(self):
        """n_bhv=12, n_nidq=11, tolerance=2 → 11-row DataFrame (BHV2 truncated)."""
        stim_code = 64
        n_bhv = 12
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]}
            for i in range(1, n_bhv + 1)
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(11, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            trial_count_tolerance=2,
        )

        assert len(result.trial_events_df) == 11


# ---------------------------------------------------------------------------
# stim onset missing / multiple occurrences
# ---------------------------------------------------------------------------


class TestStimOnsetHandling:
    def test_missing_stim_onset_gives_nan(self):
        """Trial without stim_onset_code in BHV2 → stim_onset_nidq_s = NaN."""
        stim_code = 64
        trials_data = [
            {"trial_id": 1, "condition_id": 1, "events": [(100.0, stim_code)]},
            {"trial_id": 2, "condition_id": 1, "events": []},  # no stim onset
            {"trial_id": 3, "condition_id": 1, "events": [(100.0, stim_code)]},
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(3, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        df = result.trial_events_df
        assert not np.isnan(df.iloc[0]["stim_onset_nidq_s"])
        assert np.isnan(df.iloc[1]["stim_onset_nidq_s"])
        assert not np.isnan(df.iloc[2]["stim_onset_nidq_s"])

    def test_stim_onset_multiple_occurrences_expands_rows(self):
        """Trial with 2 stim_onset_code events → 2 rows (RSVP expansion)."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [(100.0, stim_code), (200.0, stim_code)],
            }
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(1, trial_start_bit=1, onset_times=[5.0])

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        df = result.trial_events_df
        assert len(df) == 2
        assert df.iloc[0]["stim_onset_nidq_s"] == pytest.approx(5.0 + 0.1)
        assert df.iloc[1]["stim_onset_nidq_s"] == pytest.approx(5.0 + 0.2)
        # Both rows share the same trial_id
        assert df.iloc[0]["trial_id"] == 1
        assert df.iloc[1]["trial_id"] == 1

    def test_rsvp_expansion_with_current_image_train(self):
        """RSVP trial with Current_Image_Train populates stim_index column."""
        stim_code = 64
        cit = np.array([[42.0, 7.0, 99.0] + [0.0] * 97])  # 1x100 padded
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [
                    (100.0, stim_code),
                    (250.0, stim_code),
                    (400.0, stim_code),
                ],
                "user_vars": {"Current_Image_Train": cit},
            }
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(1, trial_start_bit=1, onset_times=[10.0])

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        df = result.trial_events_df
        assert len(df) == 3
        assert df["stim_index"].tolist() == [42, 7, 99]

    def test_stim_index_zero_when_no_current_image_train(self):
        """Without Current_Image_Train in user_vars, stim_index defaults to 0."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [(100.0, stim_code), (200.0, stim_code)],
            }
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(1, trial_start_bit=1, onset_times=[5.0])

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        assert result.trial_events_df["stim_index"].tolist() == [0, 0]

    def test_mixed_single_and_rsvp_trials(self):
        """Mix of single-stimulus and RSVP trials expands correctly."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [(100.0, stim_code)],  # single stim
            },
            {
                "trial_id": 2,
                "condition_id": 2,
                "events": [(100.0, stim_code), (250.0, stim_code), (400.0, stim_code)],
            },
            {
                "trial_id": 3,
                "condition_id": 3,
                "events": [(100.0, stim_code)],  # single stim
            },
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(3, trial_start_bit=1, onset_times=[1.0, 2.0, 3.0])

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        df = result.trial_events_df
        assert len(df) == 5  # 1 + 3 + 1
        assert df["trial_id"].tolist() == [1, 2, 2, 2, 3]
        assert df["condition_id"].tolist() == [1, 2, 2, 2, 3]

    def test_timing_columns_from_variable_changes(self):
        """onset_time_ms, offset_time_ms, fixation_window populated from VariableChanges."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [(100.0, stim_code)],
                "variable_changes": {
                    "onset_time": 200.0,
                    "offset_time": 100.0,
                    "fixation_window": 3.0,
                },
            }
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(1, trial_start_bit=1, onset_times=[5.0])

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        df = result.trial_events_df
        assert df.iloc[0]["onset_time_ms"] == 200.0
        assert df.iloc[0]["offset_time_ms"] == 100.0
        assert df.iloc[0]["fixation_window"] == 3.0

    def test_timing_columns_default_when_no_variable_changes(self):
        """Without VariableChanges, timing columns use defaults."""
        stim_code = 64
        trials_data = [{"trial_id": 1, "condition_id": 1, "events": [(100.0, stim_code)]}]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(1, trial_start_bit=1)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        df = result.trial_events_df
        assert df.iloc[0]["onset_time_ms"] == 150.0
        assert df.iloc[0]["offset_time_ms"] == 150.0
        assert df.iloc[0]["fixation_window"] == 5.0

    def test_stim_onset_bhv_ms_column(self):
        """stim_onset_bhv_ms stores BHV2-relative stimulus time in ms."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [(100.0, stim_code), (250.0, stim_code)],
            }
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(1, trial_start_bit=1, onset_times=[5.0])

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        df = result.trial_events_df
        assert df.iloc[0]["stim_onset_bhv_ms"] == 100.0
        assert df.iloc[1]["stim_onset_bhv_ms"] == 250.0

    def test_rsvp_timing_columns_replicated_per_stim(self):
        """In RSVP expansion, timing columns are replicated for each stimulus."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [(100.0, stim_code), (250.0, stim_code), (400.0, stim_code)],
                "variable_changes": {
                    "onset_time": 120.0,
                    "offset_time": 80.0,
                    "fixation_window": 4.0,
                },
            }
        ]
        parser = _make_bhv_parser(trials_data)
        times, codes = _make_nidq_events(1, trial_start_bit=1, onset_times=[10.0])

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        df = result.trial_events_df
        assert len(df) == 3
        assert df["onset_time_ms"].tolist() == [120.0, 120.0, 120.0]
        assert df["offset_time_ms"].tolist() == [80.0, 80.0, 80.0]
        assert df["fixation_window"].tolist() == [4.0, 4.0, 4.0]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_event_arrays_length_mismatch(self):
        """Mismatched nidq_event_times / nidq_event_codes lengths → SyncError with 'mismatch'."""
        parser = _make_bhv_parser([{"trial_id": 1, "condition_id": 1, "events": []}])

        with pytest.raises(SyncError, match="mismatch"):
            align_bhv2_to_nidq(
                bhv_parser=parser,
                nidq_event_times=np.array([1.0, 2.0]),
                nidq_event_codes=np.array([1]),
                stim_onset_code=64,
                trial_start_bit=1,
            )

    def test_stim_onset_code_out_of_range(self):
        """stim_onset_code=300 → SyncError with '0-255' in message."""
        parser = _make_bhv_parser([{"trial_id": 1, "condition_id": 1, "events": []}])
        times, codes = _make_nidq_events(1, trial_start_bit=1)

        with pytest.raises(SyncError, match="0-255"):
            align_bhv2_to_nidq(
                bhv_parser=parser,
                nidq_event_times=times,
                nidq_event_codes=codes,
                stim_onset_code=300,
                trial_start_bit=1,
            )

    def test_stim_onset_code_negative(self):
        """stim_onset_code=-1 → SyncError."""
        parser = _make_bhv_parser([{"trial_id": 1, "condition_id": 1, "events": []}])
        times, codes = _make_nidq_events(1, trial_start_bit=1)

        with pytest.raises(SyncError):
            align_bhv2_to_nidq(
                bhv_parser=parser,
                nidq_event_times=times,
                nidq_event_codes=codes,
                stim_onset_code=-1,
                trial_start_bit=1,
            )

    def test_sync_error_is_pynpxpipe_error(self):
        """SyncError is a subclass of PynpxpipeError."""
        assert issubclass(SyncError, PynpxpipeError)


# ---------------------------------------------------------------------------
# Numerical correctness
# ---------------------------------------------------------------------------


class TestNumericalCorrectness:
    def test_stim_onset_offset_precision(self):
        """stim_onset_nidq_s - onset_nidq_s == 0.5s with sub-nanosecond precision."""
        stim_code = 64
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(500.0, stim_code)]} for i in range(1, 4)
        ]
        parser = _make_bhv_parser(trials_data)
        onset_times = [10.0, 11.0, 12.0]
        times = np.array(onset_times, dtype=np.float64)
        codes = np.full(3, 2**1, dtype=int)

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        for i, row in result.trial_events_df.iterrows():
            diff = abs(row["stim_onset_nidq_s"] - (row["onset_nidq_s"] + 0.5))
            assert diff < 1e-9, f"trial {i}: offset precision {diff} >= 1e-9"

    def test_multiple_calls_are_independent(self):
        """Two independent calls return independent DataFrames."""
        stim_code = 64
        trials_data = [{"trial_id": 1, "condition_id": 1, "events": [(100.0, stim_code)]}]
        parser1 = _make_bhv_parser(trials_data)
        parser2 = _make_bhv_parser(trials_data)

        times1 = np.array([5.0])
        times2 = np.array([50.0])
        codes1 = np.array([2**1])
        codes2 = np.array([2**1])

        result1 = align_bhv2_to_nidq(
            bhv_parser=parser1,
            nidq_event_times=times1,
            nidq_event_codes=codes1,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )
        result2 = align_bhv2_to_nidq(
            bhv_parser=parser2,
            nidq_event_times=times2,
            nidq_event_codes=codes2,
            stim_onset_code=stim_code,
            trial_start_bit=1,
        )

        assert result1.trial_events_df.iloc[0]["onset_nidq_s"] == 5.0
        assert result2.trial_events_df.iloc[0]["onset_nidq_s"] == 50.0


# ---------------------------------------------------------------------------
# MATLAB-style bit-6-direct alignment (new behaviour under bhv_nidq_align redesign)
# ---------------------------------------------------------------------------


class TestStimOnsetFromNidqRising:
    """stim_onset_nidq_s must come from the NIDQ stim rising edge, NOT from
    trial_anchor + BHV offset. The formula accumulates up to ±120ms drift
    because BHV2's "trial zero" and the NIDQ trial_start rising are not
    simultaneous; real NIDQ rising is the source of truth.
    """

    def test_stim_onset_from_nidq_rising_not_offset(self):
        """NIDQ stim rising at anchor+0.230, BHV offset 0.200 → output = 0.230."""
        stim_code = 64
        # BHV says stim at 200ms after trial start
        trials_data = [
            {"trial_id": 1, "condition_id": 1, "events": [(200.0, stim_code)]},
        ]
        parser = _make_bhv_parser(trials_data)

        # NIDQ: trial anchor @ 5.0, stim rising @ 5.230 (NOT 5.200)
        times, codes = _make_nidq_events_with_stim(
            trial_anchors_s=[5.0],
            stim_times_per_trial_s=[[5.230]],
            trial_start_bit=1,
            stim_onset_bit=5,
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            stim_onset_bit=5,
        )

        actual = result.trial_events_df.iloc[0]["stim_onset_nidq_s"]
        assert abs(actual - 5.230) < 1e-9, (
            f"stim_onset_nidq_s should follow NIDQ rising (5.230), got {actual}. "
            f"Hint: impl is probably using trial_anchor + bhv_offset formula."
        )

    def test_no_drift_across_trials(self):
        """Per-trial BHV→NIDQ gap varies (58ms, 85ms, 121ms);
        NIDQ rising is the truth, formula output would diverge.
        """
        stim_code = 64
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(200.0, stim_code)]} for i in range(1, 4)
        ]
        parser = _make_bhv_parser(trials_data)

        # Real NIDQ stim rising positions (absolute, not formula-derived)
        stim_abs = [1.258, 2.285, 3.321]  # each offset = 0.258, 0.285, 0.321 — drifting
        times, codes = _make_nidq_events_with_stim(
            trial_anchors_s=[1.0, 2.0, 3.0],
            stim_times_per_trial_s=[[s] for s in stim_abs],
            trial_start_bit=1,
            stim_onset_bit=5,
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            stim_onset_bit=5,
        )

        np.testing.assert_array_almost_equal(
            result.trial_events_df["stim_onset_nidq_s"].to_numpy(),
            np.array(stim_abs),
            decimal=9,
        )

    def test_rsvp_multi_stim_matched_to_nidq_rising(self):
        """Trial with 3 BHV stims; 3 NIDQ rising edges in trial window → 1:1 match."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [(100.0, stim_code), (250.0, stim_code), (400.0, stim_code)],
            }
        ]
        parser = _make_bhv_parser(trials_data)

        nidq_stims = [10.111, 10.262, 10.419]
        times, codes = _make_nidq_events_with_stim(
            trial_anchors_s=[10.0],
            stim_times_per_trial_s=[nidq_stims],
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            stim_onset_bit=5,
        )

        np.testing.assert_array_almost_equal(
            result.trial_events_df["stim_onset_nidq_s"].to_numpy(),
            np.array(nidq_stims),
            decimal=9,
        )

    def test_last_trial_window_extends_to_infinity(self):
        """Stim rising after the last trial anchor (no next anchor) is still matched."""
        stim_code = 64
        trials_data = [
            {"trial_id": 1, "condition_id": 1, "events": [(100.0, stim_code)]},
            {"trial_id": 2, "condition_id": 1, "events": [(100.0, stim_code)]},
        ]
        parser = _make_bhv_parser(trials_data)

        times, codes = _make_nidq_events_with_stim(
            trial_anchors_s=[1.0, 2.0],
            stim_times_per_trial_s=[[1.1], [2.1]],
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            stim_onset_bit=5,
        )

        assert result.trial_events_df.iloc[1]["stim_onset_nidq_s"] == pytest.approx(2.1)

    def test_per_trial_stim_count_mismatch_gives_nan(self):
        """BHV has 2 stims in a trial, NIDQ has 1 rising → that trial's stims → NaN."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [(100.0, stim_code), (250.0, stim_code)],
            }
        ]
        parser = _make_bhv_parser(trials_data)

        # Only 1 NIDQ stim rising in the trial window — mismatch
        times, codes = _make_nidq_events_with_stim(
            trial_anchors_s=[5.0],
            stim_times_per_trial_s=[[5.11]],
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            stim_onset_bit=5,
            stim_count_tolerance=0,
        )

        # Both stim rows for trial 1 should be NaN under strict tolerance
        assert result.trial_events_df["stim_onset_nidq_s"].isna().all()

    def test_per_trial_stim_count_within_tolerance_takes_shortest(self):
        """Same mismatch but tolerance=1 → take min(n_bhv, n_nidq) rising edges."""
        stim_code = 64
        trials_data = [
            {
                "trial_id": 1,
                "condition_id": 1,
                "events": [(100.0, stim_code), (250.0, stim_code)],
            }
        ]
        parser = _make_bhv_parser(trials_data)

        times, codes = _make_nidq_events_with_stim(
            trial_anchors_s=[5.0],
            stim_times_per_trial_s=[[5.11]],
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            stim_onset_bit=5,
            stim_count_tolerance=1,
        )

        df = result.trial_events_df
        assert df.iloc[0]["stim_onset_nidq_s"] == pytest.approx(5.11)
        # Second BHV stim has no NIDQ rising → NaN
        assert np.isnan(df.iloc[1]["stim_onset_nidq_s"])


class TestAutoDetectStimOnsetBit:
    """stim_onset_bit autodetect: pick decoded-domain bit whose rising count
    best matches total BHV2 stim_onset_code events.
    """

    def test_auto_detect_stim_bit_selects_matching_count(self):
        stim_code = 64
        # 3 trials, each with 2 stims → total 6 BHV stim events
        trials_data = [
            {
                "trial_id": i,
                "condition_id": 1,
                "events": [(100.0, stim_code), (250.0, stim_code)],
            }
            for i in range(1, 4)
        ]
        parser = _make_bhv_parser(trials_data)

        # 3 trial-start rising + 6 stim rising (on decoded bit 5, value 32)
        times, codes = _make_nidq_events_with_stim(
            trial_anchors_s=[1.0, 2.0, 3.0],
            stim_times_per_trial_s=[[1.1, 1.25], [2.1, 2.25], [3.1, 3.25]],
            trial_start_bit=1,
            stim_onset_bit=5,
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            stim_onset_bit=None,  # auto-detect
        )

        assert result.detected_stim_onset_bit == 5

    def test_auto_detect_stim_bit_excludes_trial_start_bit(self):
        """When stim total == trial total, must not collapse onto trial_start bit."""
        stim_code = 64
        # 3 trials, 1 stim each → total 3 stim events (== 3 trials)
        trials_data = [
            {"trial_id": i, "condition_id": 1, "events": [(100.0, stim_code)]} for i in range(1, 4)
        ]
        parser = _make_bhv_parser(trials_data)

        times, codes = _make_nidq_events_with_stim(
            trial_anchors_s=[1.0, 2.0, 3.0],
            stim_times_per_trial_s=[[1.1], [2.1], [3.1]],
            trial_start_bit=1,
            stim_onset_bit=5,
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            stim_onset_bit=None,
        )

        # Must NOT pick bit 1 (trial_start's bit)
        assert result.detected_stim_onset_bit != 1
        assert result.detected_stim_onset_bit == 5

    def test_explicit_stim_onset_bit_skips_auto_detect(self):
        stim_code = 64
        trials_data = [{"trial_id": 1, "condition_id": 1, "events": [(100.0, stim_code)]}]
        parser = _make_bhv_parser(trials_data)

        times, codes = _make_nidq_events_with_stim(
            trial_anchors_s=[1.0],
            stim_times_per_trial_s=[[1.1]],
            trial_start_bit=1,
            stim_onset_bit=6,
        )

        result = align_bhv2_to_nidq(
            bhv_parser=parser,
            nidq_event_times=times,
            nidq_event_codes=codes,
            stim_onset_code=stim_code,
            trial_start_bit=1,
            stim_onset_bit=6,
        )

        assert result.detected_stim_onset_bit == 6
