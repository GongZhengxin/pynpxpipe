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

    def test_stim_onset_multiple_occurrences_uses_first(self):
        """Trial with 2 stim_onset_code events → uses first occurrence."""
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

        expected = 5.0 + 0.1  # onset 5.0 + 100ms offset
        assert abs(result.trial_events_df.iloc[0]["stim_onset_nidq_s"] - expected) < 1e-9


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
