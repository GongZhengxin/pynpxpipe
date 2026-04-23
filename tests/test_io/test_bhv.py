"""Tests for BHV2Parser (io/bhv.py) — pure-Python backend via BHV2Reader.

Unit tests mock BHV2Reader. Integration tests use the real BHV2 file and are
marked @pytest.mark.integration (skipped in CI).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from pynpxpipe.io.bhv import BHV2_MAGIC, BHV2Parser, TrialData

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
BHV2_FILE = Path(r"F:\#Datasets\demo_rawdata\241026_MaoDan_YJ_WordLOC.bhv2")
EXPECTED_TOTAL_TRIALS = 11
EXPECTED_EXPERIMENT_NAME = "PV"


# ---------------------------------------------------------------------------
# Backend switch tests
# ---------------------------------------------------------------------------


class TestBackendSwitch:
    def test_default_backend_is_python(self) -> None:
        """Default BHV2_BACKEND should resolve to the pure-Python parser."""
        assert not hasattr(BHV2Parser, "_get_engine")
        assert hasattr(BHV2Parser, "_get_reader")

    def test_matlab_backend_switch(self) -> None:
        """BHV2_BACKEND=matlab should load the MATLAB-based parser."""
        import subprocess
        import sys

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import os; os.environ['BHV2_BACKEND']='matlab'; "
                "from pynpxpipe.io.bhv import BHV2Parser; "
                "assert hasattr(BHV2Parser, '_get_engine'), 'no _get_engine'; "
                "assert not hasattr(BHV2Parser, '_get_reader'), 'has _get_reader'",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Backend switch failed: {result.stderr}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_bhv2(tmp_path: Path) -> Path:
    """Minimal BHV2 file with valid magic bytes (enough for __init__)."""
    f = tmp_path / "test.bhv2"
    f.write_bytes(BHV2_MAGIC + b"\x00" * 100)
    return f


def _make_mock_reader(
    trial_dicts: dict | None = None,
    mlconfig: dict | None = None,
    var_list: list[str] | None = None,
) -> MagicMock:
    """Build a mock BHV2Reader that returns synthetic data."""
    reader = MagicMock()

    if var_list is None:
        var_list = [
            "Trial1",
            "Trial2",
            "Trial3",
            "MLConfig",
            "FileInfo",
            "FileIndex",
            "IndexPosition",
        ]
    reader.list_variables.return_value = var_list

    if trial_dicts is None:
        trial_dicts = {
            "Trial1": {
                "Trial": 1.0,
                "Condition": 3.0,
                "BehavioralCodes": {
                    "CodeTimes": np.array([[0.0], [100.5], [200.0]]),
                    "CodeNumbers": np.array([[9], [18], [38]], dtype=np.uint16),
                },
                "AnalogData": {
                    "Eye": np.random.rand(100, 2),
                    "SampleInterval": 4.0,
                },
                "UserVars": {"DatasetName": "test_dataset"},
                "VariableChanges": {
                    "onset_time": 150.0,
                    "offset_time": 150.0,
                    "fixation_window": 5.0,
                },
            },
            "Trial2": {
                "Trial": 2.0,
                "Condition": 5.0,
                "BehavioralCodes": {
                    "CodeTimes": np.array([[0.0], [150.0]]),
                    "CodeNumbers": np.array([[9], [18]], dtype=np.uint16),
                },
                "AnalogData": {
                    "Eye": np.random.rand(80, 2),
                    "SampleInterval": 4.0,
                },
                "UserVars": {},
            },
            "Trial3": {
                "Trial": 3.0,
                "Condition": 3.0,
                "BehavioralCodes": {
                    "CodeTimes": np.array([[0.0]]),
                    "CodeNumbers": np.array([[9]], dtype=np.uint16),
                },
                "AnalogData": {
                    "Eye": np.random.rand(120, 2),
                    "SampleInterval": 4.0,
                },
                "UserVars": {"DatasetName": "other"},
            },
        }

    if mlconfig is None:
        mlconfig = {
            "ExperimentName": "TestExp",
            "MLVersion": "2.2.42 (Dec 15, 2023)",
            "SubjectName": "TestMonkey",
        }

    all_data = {**trial_dicts, "MLConfig": mlconfig}
    reader.read.side_effect = lambda name: all_data[name]
    reader.close.return_value = None
    return reader


# ---------------------------------------------------------------------------
# __init__ tests (no backend dependency)
# ---------------------------------------------------------------------------


class TestBHV2ParserInit:
    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            BHV2Parser(tmp_path / "nonexistent.bhv2")

    def test_wrong_magic_raises_io_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.bhv2"
        bad.write_bytes(b"X" * 21)
        with pytest.raises(IOError):
            BHV2Parser(bad)

    def test_short_file_raises_io_error(self, tmp_path: Path) -> None:
        short = tmp_path / "short.bhv2"
        short.write_bytes(b"\x0d\x00\x00")
        with pytest.raises(IOError):
            BHV2Parser(short)

    def test_valid_file_stores_path(self, minimal_bhv2: Path) -> None:
        parser = BHV2Parser(minimal_bhv2)
        assert parser.bhv_file == minimal_bhv2

    def test_cache_is_none_after_init(self, minimal_bhv2: Path) -> None:
        parser = BHV2Parser(minimal_bhv2)
        assert parser._cache is None


# ---------------------------------------------------------------------------
# Unit tests — mock BHV2Reader (parse)
# ---------------------------------------------------------------------------


class TestParsePurePython:
    """BHV2Parser.parse() should use BHV2Reader internally."""

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_reader_created_with_bhv_file(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        parser.parse()
        MockReader.assert_called_once_with(minimal_bhv2)

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_returns_list_of_trial_data(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        assert isinstance(trials, list)
        assert all(isinstance(t, TrialData) for t in trials)
        assert len(trials) == 3

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_maps_trial_id_from_float(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        assert trials[0].trial_id == 1
        assert isinstance(trials[0].trial_id, int)

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_maps_condition_id_from_float(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        assert trials[0].condition_id == 3
        assert isinstance(trials[0].condition_id, int)

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_maps_behavioral_codes_to_events(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        events = trials[0].events
        assert len(events) == 3
        assert events[0] == (0.0, 9)
        assert events[1] == (100.5, 18)
        assert events[2] == (200.0, 38)

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_events_are_float_int_tuples(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        for trial in trials:
            for time_ms, code in trial.events:
                assert isinstance(time_ms, float)
                assert isinstance(code, int)

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_maps_user_vars(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        assert trials[0].user_vars == {"DatasetName": "test_dataset"}

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_empty_user_vars_returns_empty_dict(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        assert trials[1].user_vars == {}

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_maps_variable_changes(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        vc = trials[0].variable_changes
        assert vc["onset_time"] == 150.0
        assert vc["offset_time"] == 150.0
        assert vc["fixation_window"] == 5.0

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_missing_variable_changes_returns_empty_dict(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        # Trial2 has no VariableChanges in mock
        assert trials[1].variable_changes == {}

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_trials_sorted_by_id(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        trials = parser.parse()
        ids = [t.trial_id for t in trials]
        assert ids == sorted(ids)

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_caches_result(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        t1 = parser.parse()
        t2 = parser.parse()
        assert t1 is t2


# ---------------------------------------------------------------------------
# Unit tests — mock BHV2Reader (get_event_code_times)
# ---------------------------------------------------------------------------


class TestGetEventCodeTimesPurePython:
    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_existing_code_returns_results(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        result = parser.get_event_code_times(9)
        assert len(result) == 3  # code 9 in all 3 trials

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_result_is_trial_id_time_tuples(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        result = parser.get_event_code_times(9)
        for trial_id, time_ms in result:
            assert isinstance(trial_id, int)
            assert isinstance(time_ms, float)

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_trials_filter_limits_results(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        result = parser.get_event_code_times(9, trials=[1, 2])
        assert all(tid in (1, 2) for tid, _ in result)
        assert len(result) == 2

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_nonexistent_code_returns_empty(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        result = parser.get_event_code_times(99999)
        assert result == []


# ---------------------------------------------------------------------------
# Unit tests — mock BHV2Reader (get_session_metadata)
# ---------------------------------------------------------------------------


class TestGetSessionMetadataPurePython:
    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_returns_experiment_name(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        meta = parser.get_session_metadata()
        assert meta["ExperimentName"] == "TestExp"

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_returns_total_trials(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        meta = parser.get_session_metadata()
        assert meta["TotalTrials"] == 3

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_returns_ml_version(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        meta = parser.get_session_metadata()
        assert isinstance(meta["MLVersion"], str)
        assert "2.2" in meta["MLVersion"]

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_returns_subject_name(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        meta = parser.get_session_metadata()
        assert meta["SubjectName"] == "TestMonkey"


# ---------------------------------------------------------------------------
# Unit tests — mock BHV2Reader (get_analog_data)
# ---------------------------------------------------------------------------


class TestGetAnalogDataPurePython:
    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_eye_returns_all_trials(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        result = parser.get_analog_data("Eye")
        assert len(result) == 3
        assert all(isinstance(v, np.ndarray) for v in result.values())

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_trials_filter(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        result = parser.get_analog_data("Eye", trials=[1, 2])
        assert set(result.keys()) == {1, 2}

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_missing_channel_returns_empty(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        result = parser.get_analog_data("NonExistentChannel_xyz")
        assert result == {}

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_eye_shape(self, MockReader, minimal_bhv2):
        MockReader.return_value = _make_mock_reader()
        parser = BHV2Parser(minimal_bhv2)
        result = parser.get_analog_data("Eye")
        for arr in result.values():
            assert arr.ndim == 2
            assert arr.shape[1] == 2


def _trial_with_user_vars(trial_id: int, user_vars: dict) -> dict:
    """Build a minimal mock-reader trial dict with a chosen UserVars payload."""
    return {
        "Trial": float(trial_id),
        "Condition": 1.0,
        "BehavioralCodes": {
            "CodeTimes": np.array([[0.0]]),
            "CodeNumbers": np.array([[9]], dtype=np.uint16),
        },
        "AnalogData": {"Eye": np.zeros((1, 2)), "SampleInterval": 4.0},
        "UserVars": user_vars,
    }


class TestGetDatasetTsvPathPurePython:
    """BHV2Parser.get_dataset_tsv_path() — UserVars.DatasetName reader."""

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_returns_first_non_empty_value(self, MockReader, minimal_bhv2):
        trials = {
            "Trial1": _trial_with_user_vars(1, {"DatasetName": ""}),
            "Trial2": _trial_with_user_vars(
                2, {"DatasetName": "C:/#Datasets/TripleN10k/stimuli/nsd1w.tsv"}
            ),
        }
        MockReader.return_value = _make_mock_reader(
            trial_dicts=trials,
            var_list=[*trials.keys(), "MLConfig", "FileInfo", "FileIndex", "IndexPosition"],
        )
        parser = BHV2Parser(minimal_bhv2)
        assert (
            parser.get_dataset_tsv_path()
            == "C:/#Datasets/TripleN10k/stimuli/nsd1w.tsv"
        )

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_returns_none_when_all_empty(self, MockReader, minimal_bhv2):
        trials = {
            "Trial1": _trial_with_user_vars(1, {"DatasetName": ""}),
            "Trial2": _trial_with_user_vars(2, {}),
        }
        MockReader.return_value = _make_mock_reader(
            trial_dicts=trials,
            var_list=[*trials.keys(), "MLConfig", "FileInfo", "FileIndex", "IndexPosition"],
        )
        parser = BHV2Parser(minimal_bhv2)
        assert parser.get_dataset_tsv_path() is None

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_ignores_non_string_values(self, MockReader, minimal_bhv2):
        trials = {
            "Trial1": _trial_with_user_vars(1, {"DatasetName": 42}),
            "Trial2": _trial_with_user_vars(
                2, {"DatasetName": "C:/valid/path.tsv"}
            ),
        }
        MockReader.return_value = _make_mock_reader(
            trial_dicts=trials,
            var_list=[*trials.keys(), "MLConfig", "FileInfo", "FileIndex", "IndexPosition"],
        )
        parser = BHV2Parser(minimal_bhv2)
        assert parser.get_dataset_tsv_path() == "C:/valid/path.tsv"

    @patch("pynpxpipe.io.bhv.BHV2Reader")
    def test_warns_on_divergent_values(self, MockReader, minimal_bhv2, caplog):
        import logging

        trials = {
            "Trial1": _trial_with_user_vars(1, {"DatasetName": "a.tsv"}),
            "Trial2": _trial_with_user_vars(2, {"DatasetName": "b.tsv"}),
        }
        MockReader.return_value = _make_mock_reader(
            trial_dicts=trials,
            var_list=[*trials.keys(), "MLConfig", "FileInfo", "FileIndex", "IndexPosition"],
        )
        parser = BHV2Parser(minimal_bhv2)
        with caplog.at_level(logging.WARNING, logger="pynpxpipe.io.bhv"):
            result = parser.get_dataset_tsv_path()
        assert result == "a.tsv"
        assert any("varies across trials" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Integration tests — real BHV2 file, no MATLAB
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def int_parser() -> BHV2Parser:
    """Module-scoped parser on the real BHV2 file."""
    if not BHV2_FILE.exists():
        pytest.skip(f"BHV2 test file not found: {BHV2_FILE}")
    return BHV2Parser(BHV2_FILE)


@pytest.mark.integration
class TestBHV2ParserIntegration:
    def test_parse_returns_correct_count(self, int_parser: BHV2Parser) -> None:
        trials = int_parser.parse()
        assert len(trials) == EXPECTED_TOTAL_TRIALS

    def test_parse_returns_trial_data(self, int_parser: BHV2Parser) -> None:
        trials = int_parser.parse()
        assert all(isinstance(t, TrialData) for t in trials)

    def test_trial_ids_sequential(self, int_parser: BHV2Parser) -> None:
        trials = int_parser.parse()
        ids = [t.trial_id for t in trials]
        assert ids == list(range(1, 12))

    def test_first_trial_valid_fields(self, int_parser: BHV2Parser) -> None:
        trials = int_parser.parse()
        t = trials[0]
        assert t.trial_id == 1
        assert isinstance(t.condition_id, int)
        assert len(t.events) > 0

    def test_events_structure(self, int_parser: BHV2Parser) -> None:
        trials = int_parser.parse()
        for trial in trials:
            for time_ms, code in trial.events:
                assert isinstance(time_ms, float)
                assert isinstance(code, int)

    def test_user_vars_is_dict(self, int_parser: BHV2Parser) -> None:
        trials = int_parser.parse()
        for trial in trials:
            assert isinstance(trial.user_vars, dict)

    def test_session_metadata_experiment_name(self, int_parser: BHV2Parser) -> None:
        meta = int_parser.get_session_metadata()
        assert meta["ExperimentName"] == EXPECTED_EXPERIMENT_NAME

    def test_session_metadata_total_trials(self, int_parser: BHV2Parser) -> None:
        meta = int_parser.get_session_metadata()
        assert meta["TotalTrials"] == EXPECTED_TOTAL_TRIALS

    def test_session_metadata_ml_version(self, int_parser: BHV2Parser) -> None:
        meta = int_parser.get_session_metadata()
        assert isinstance(meta["MLVersion"], str)
        assert "2.2" in meta["MLVersion"]

    def test_session_metadata_subject_name(self, int_parser: BHV2Parser) -> None:
        meta = int_parser.get_session_metadata()
        assert meta["SubjectName"] == "MaoDan"

    def test_analog_data_eye_all_trials(self, int_parser: BHV2Parser) -> None:
        result = int_parser.get_analog_data("Eye")
        assert len(result) == EXPECTED_TOTAL_TRIALS

    def test_analog_data_eye_shape(self, int_parser: BHV2Parser) -> None:
        result = int_parser.get_analog_data("Eye")
        for arr in result.values():
            assert isinstance(arr, np.ndarray)
            assert arr.ndim == 2
            assert arr.shape[1] == 2

    def test_analog_data_filter_trials(self, int_parser: BHV2Parser) -> None:
        result = int_parser.get_analog_data("Eye", trials=[1, 2])
        assert set(result.keys()) == {1, 2}

    def test_event_code_times_existing(self, int_parser: BHV2Parser) -> None:
        trials = int_parser.parse()
        first_code = trials[0].events[0][1]
        result = int_parser.get_event_code_times(first_code)
        assert len(result) >= 1

    def test_event_code_times_nonexistent(self, int_parser: BHV2Parser) -> None:
        result = int_parser.get_event_code_times(99999)
        assert result == []

    def test_cache_returns_same_object(self, int_parser: BHV2Parser) -> None:
        t1 = int_parser.parse()
        t2 = int_parser.parse()
        assert t1 is t2


# ---------------------------------------------------------------------------
# Ground-truth verification — BHV2Parser vs MATLAB-exported JSON fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "bhv2_ground_truth"


def _load_fixture(filename: str):
    import json

    return json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


def _reconstruct_ndarray(val):
    """Reconstruct np.ndarray from fixture JSON ``{"tp":"nd",...}`` encoding."""
    if isinstance(val, dict) and val.get("tp") == "nd":
        return np.array(val["d"], dtype=val["dt"]).reshape(val["sh"], order="F")
    return val


@pytest.mark.integration
class TestBHV2ParserGroundTruth:
    """Verify BHV2Parser.parse() output matches MATLAB-exported fixtures field by field."""

    def test_trial1_events_match_fixture(self, int_parser: BHV2Parser) -> None:
        fixture = _load_fixture("trial_01.json")
        gt_times = _reconstruct_ndarray(fixture["BehavioralCodes"]["CodeTimes"]).flatten()
        gt_codes = _reconstruct_ndarray(fixture["BehavioralCodes"]["CodeNumbers"]).flatten()

        trials = int_parser.parse()
        t = trials[0]
        actual_times = [time_ms for time_ms, _ in t.events]
        actual_codes = [code for _, code in t.events]

        np.testing.assert_allclose(actual_times, gt_times, rtol=1e-9)
        np.testing.assert_array_equal(actual_codes, gt_codes.astype(int))

    def test_trial1_condition_matches_fixture(self, int_parser: BHV2Parser) -> None:
        fixture = _load_fixture("trial_01.json")
        trials = int_parser.parse()
        assert trials[0].condition_id == int(fixture["Condition"])

    def test_trial1_user_vars_dataset_name(self, int_parser: BHV2Parser) -> None:
        fixture = _load_fixture("trial_01.json")
        trials = int_parser.parse()
        assert trials[0].user_vars["DatasetName"] == fixture["UserVars"]["DatasetName"]

    def test_all_trials_condition_ids_match(self, int_parser: BHV2Parser) -> None:
        trials = int_parser.parse()
        for i, trial in enumerate(trials, start=1):
            fixture = _load_fixture(f"trial_{i:02d}.json")
            assert trial.condition_id == int(fixture["Condition"]), f"Trial{i} condition mismatch"

    def test_all_trials_event_counts_match(self, int_parser: BHV2Parser) -> None:
        trials = int_parser.parse()
        for i, trial in enumerate(trials, start=1):
            fixture = _load_fixture(f"trial_{i:02d}.json")
            gt_codes = _reconstruct_ndarray(fixture["BehavioralCodes"]["CodeNumbers"])
            expected_count = gt_codes.flatten().shape[0]
            assert len(trial.events) == expected_count, f"Trial{i} event count mismatch"

    def test_analog_eye_exact_match_trial1(self, int_parser: BHV2Parser) -> None:
        fixture = _load_fixture("trial_01.json")
        gt_eye = _reconstruct_ndarray(fixture["AnalogData"]["Eye"])

        result = int_parser.get_analog_data("Eye", trials=[1])
        np.testing.assert_array_equal(result[1], gt_eye)

    def test_session_metadata_matches_ml_config(self, int_parser: BHV2Parser) -> None:
        ml_config = _load_fixture("ml_config.json")
        meta = int_parser.get_session_metadata()
        assert meta["ExperimentName"] == ml_config["ExperimentName"]
        assert meta["SubjectName"] == ml_config["SubjectName"]
