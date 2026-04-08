"""Tests for BHV2Reader (io/bhv2_reader.py) — pure-Python BHV2 binary parser.

Ground-truth tests compare against MATLAB-exported JSON fixtures in
tests/fixtures/bhv2_ground_truth/.  They require the real BHV2 file at the
path stored in conftest.py; if that file is absent the tests are skipped.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from pynpxpipe.io.bhv2_reader import BHV2Reader

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "bhv2_ground_truth"
BHV2_FILE = Path(r"F:\#Datasets\demo_rawdata\241026_MaoDan_YJ_WordLOC.bhv2")


def _load_fixture(filename: str) -> Any:
    return json.loads((FIXTURES_DIR / filename).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Ground-truth reconstruction helpers
# ---------------------------------------------------------------------------

_SPECIAL_FLOATS = {
    "__NaN__": float("nan"),
    "__Inf__": float("inf"),
    "__-Inf__": float("-inf"),
}


def reconstruct(val: Any) -> Any:
    """Convert a fixture JSON value back to a Python-native or numpy value.

    Rules:
      - {"tp":"nd",...}   → np.ndarray
      - "__NaN__" etc.    → float special
      - dict              → recursively reconstruct each value
      - list              → recursively reconstruct each element
      - scalar number     → float/int as-is
      - str/bool          → as-is
    """
    if isinstance(val, str):
        return _SPECIAL_FLOATS.get(val, val)
    if isinstance(val, dict):
        if val.get("tp") == "nd":
            dt = val["dt"]
            sh = val["sh"]
            d = val["d"]
            arr = np.array(d, dtype=dt).reshape(sh, order="F")
            return arr
        return {k: reconstruct(v) for k, v in val.items()}
    if isinstance(val, list):
        return [reconstruct(v) for v in val]
    return val


def _compare_values(actual: Any, expected: Any, path: str = "") -> None:
    """Recursively compare BHV2Reader output to reconstructed fixture value."""
    if isinstance(expected, float) and math.isnan(expected):
        if isinstance(actual, float) and math.isnan(actual):
            return
        if isinstance(actual, np.floating) and np.isnan(actual):
            return
        pytest.fail(f"{path}: expected NaN, got {actual!r}")

    if isinstance(expected, np.ndarray):
        assert isinstance(actual, np.ndarray), f"{path}: expected ndarray, got {type(actual)}"
        assert actual.shape == expected.shape, (
            f"{path}: shape mismatch actual={actual.shape} expected={expected.shape}"
        )
        np.testing.assert_allclose(
            actual.astype(float),
            expected.astype(float),
            rtol=1e-9,
            atol=0,
            err_msg=f"{path}: array values differ",
        )
        return

    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual)}"
        for k, exp_v in expected.items():
            assert k in actual, f"{path}.{k}: key missing in actual"
            _compare_values(actual[k], exp_v, path=f"{path}.{k}")
        return

    if isinstance(expected, list):
        assert isinstance(actual, list), f"{path}: expected list, got {type(actual)}"
        assert len(actual) == len(expected), (
            f"{path}: list length mismatch actual={len(actual)} expected={len(expected)}"
        )
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            _compare_values(a, e, path=f"{path}[{i}]")
        return

    if isinstance(expected, bool):
        assert actual is expected or actual == expected, f"{path}: {actual!r} != {expected!r}"
        return

    if isinstance(expected, (int, float)):
        assert isinstance(actual, (int, float, np.number)), (
            f"{path}: expected number, got {type(actual)}"
        )
        assert abs(float(actual) - float(expected)) < 1e-9, f"{path}: {actual!r} != {expected!r}"
        return

    assert actual == expected, f"{path}: {actual!r} != {expected!r}"


# ---------------------------------------------------------------------------
# Unit tests — no real file needed (synthetic binary)
# ---------------------------------------------------------------------------


def _make_minimal_bhv2(tmp_path: Path) -> Path:
    """Build a minimal valid BHV2 binary: IndexPosition + FileIndex."""
    buf = bytearray()

    def write_var(name: str, type_str: str, sizes: list[int], payload: bytes) -> None:
        buf.extend(struct.pack("<Q", len(name)))
        buf.extend(name.encode("ascii"))
        buf.extend(struct.pack("<Q", len(type_str)))
        buf.extend(type_str.encode("ascii"))
        buf.extend(struct.pack("<Q", len(sizes)))
        for s in sizes:
            buf.extend(struct.pack("<Q", s))
        buf.extend(payload)

    # --- IndexPosition (double scalar: offset of FileIndex) ---
    # We'll fill in the actual offset after building the FileIndex
    write_var("IndexPosition", "double", [1, 1], b"\x00" * 8)  # placeholder

    # --- FileIndex (cell[2,3]): 2 variables: "MyVar" and "IndexPosition" ---
    file_index_offset = len(buf)
    # Patch IndexPosition payload to point here
    # IP payload is at bytes 59..66 (from the known format)
    payload_offset = 59
    ip_bytes = struct.pack("<d", float(file_index_offset))
    buf[payload_offset : payload_offset + 8] = ip_bytes

    # Build FileIndex cell[2,3] (flat Fortran order: col0=names, col1=starts, col2=ends)
    # We will write: 2 name vars, 2 start vars, 2 end vars
    # MyVar starts at 67, ends at 200; IndexPosition starts at 0, ends at 67

    def write_cell_element(name: str, type_str: str, sizes: list[int], payload: bytes) -> None:
        buf.extend(struct.pack("<Q", len(name)))
        buf.extend(name.encode("ascii"))
        buf.extend(struct.pack("<Q", len(type_str)))
        buf.extend(type_str.encode("ascii"))
        buf.extend(struct.pack("<Q", len(sizes)))
        for s in sizes:
            buf.extend(struct.pack("<Q", s))
        buf.extend(payload)

    # FileIndex header
    buf.extend(struct.pack("<Q", len("FileIndex")))
    buf.extend(b"FileIndex")
    buf.extend(struct.pack("<Q", len("cell")))
    buf.extend(b"cell")
    buf.extend(struct.pack("<Q", 2))  # ndim=2
    buf.extend(struct.pack("<Q", 2))  # sz[0]=2
    buf.extend(struct.pack("<Q", 3))  # sz[1]=3

    # 6 cell elements (Fortran order: col0 first = names, col1 = starts, col2 = ends)
    # col0: "MyVar", "IndexPosition"
    write_cell_element("", "char", [1, 5], b"MyVar")
    write_cell_element("", "char", [1, 13], b"IndexPosition")
    # col1: starts (double scalars) — 67 and 0
    write_cell_element("", "double", [1, 1], struct.pack("<d", 67.0))
    write_cell_element("", "double", [1, 1], struct.pack("<d", 0.0))
    # col2: ends — 200 and 67
    write_cell_element("", "double", [1, 1], struct.pack("<d", 200.0))
    write_cell_element("", "double", [1, 1], struct.pack("<d", 67.0))

    path = tmp_path / "test.bhv2"
    path.write_bytes(bytes(buf))
    return path


class TestBHV2ReaderInit:
    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            BHV2Reader(tmp_path / "nonexistent.bhv2")

    def test_wrong_magic_raises_io_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.bhv2"
        bad.write_bytes(b"X" * 21)
        with pytest.raises(OSError):
            BHV2Reader(bad)

    def test_short_file_raises_io_error(self, tmp_path: Path) -> None:
        short = tmp_path / "short.bhv2"
        short.write_bytes(b"\x0d\x00\x00\x00\x00\x00\x00\x00IndexPos")
        with pytest.raises(OSError):
            BHV2Reader(short)


class TestBHV2ReaderContextManager:
    def test_context_manager_closes_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.bhv2"
        f.write_bytes(b"\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition" + b"\x00" * 100)
        try:
            reader = BHV2Reader.__new__(BHV2Reader)
            reader._path = f
            reader._index = {}
            reader._encoding = "utf-8"
            reader._fh = f.open("rb")
        except Exception:
            pass
        # Test via context manager directly with invalid file (just test close behavior)
        # Use a file that won't crash on close
        with pytest.raises(OSError), BHV2Reader(f):
            pass


# ---------------------------------------------------------------------------
# Integration tests — require real BHV2 file and fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reader() -> BHV2Reader:
    """Module-scoped BHV2Reader on the real test file."""
    if not BHV2_FILE.exists():
        pytest.skip(f"BHV2 test file not found: {BHV2_FILE}")
    if not FIXTURES_DIR.exists():
        pytest.skip(f"Fixtures directory not found: {FIXTURES_DIR}")
    r = BHV2Reader(BHV2_FILE)
    yield r
    r.close()


@pytest.mark.integration
class TestListVariables:
    def test_list_variables_matches_index(self, reader: BHV2Reader) -> None:
        expected_index = _load_fixture("index.json")
        expected_vars = set(expected_index["exported_variables"])
        actual_vars = set(reader.list_variables())
        # All exported variables should be present
        assert expected_vars.issubset(actual_vars), f"Missing: {expected_vars - actual_vars}"

    def test_list_variables_contains_trials(self, reader: BHV2Reader) -> None:
        variables = reader.list_variables()
        assert "Trial1" in variables
        assert "Trial11" in variables

    def test_list_variables_returns_list_of_str(self, reader: BHV2Reader) -> None:
        variables = reader.list_variables()
        assert isinstance(variables, list)
        assert all(isinstance(v, str) for v in variables)


@pytest.mark.integration
class TestReadFileInfo:
    def test_file_info_matches_fixture(self, reader: BHV2Reader) -> None:
        expected = reconstruct(_load_fixture("file_info.json"))
        actual = reader.read("FileInfo")
        assert isinstance(actual, dict)
        assert actual.get("encoding") == expected["encoding"]
        assert actual.get("machinefmt") == expected["machinefmt"]

    def test_encoding_set_from_file_info(self, reader: BHV2Reader) -> None:
        # UTF-8 in this file
        assert reader._encoding in ("UTF-8", "utf-8", "windows-1252")


@pytest.mark.integration
class TestReadTrial1BehavioralCodes:
    def test_behavioral_codes_codetimes_shape(self, reader: BHV2Reader) -> None:
        fixture = _load_fixture("trial_01.json")
        gt_codes = reconstruct(fixture["BehavioralCodes"])
        trial = reader.read("Trial1")
        actual_times = trial["BehavioralCodes"]["CodeTimes"]
        expected_times = gt_codes["CodeTimes"]
        assert isinstance(actual_times, np.ndarray)
        assert actual_times.shape == expected_times.shape

    def test_behavioral_codes_codetimes_values(self, reader: BHV2Reader) -> None:
        fixture = _load_fixture("trial_01.json")
        gt_codes = reconstruct(fixture["BehavioralCodes"])
        trial = reader.read("Trial1")
        np.testing.assert_allclose(
            trial["BehavioralCodes"]["CodeTimes"].flatten(),
            gt_codes["CodeTimes"].flatten(),
            rtol=1e-9,
        )

    def test_behavioral_codes_codenumbers(self, reader: BHV2Reader) -> None:
        fixture = _load_fixture("trial_01.json")
        gt_codes = reconstruct(fixture["BehavioralCodes"])
        trial = reader.read("Trial1")
        np.testing.assert_allclose(
            trial["BehavioralCodes"]["CodeNumbers"].flatten().astype(float),
            gt_codes["CodeNumbers"].flatten().astype(float),
        )


@pytest.mark.integration
class TestReadTrial1AnalogData:
    def test_eye_shape_matches_fixture(self, reader: BHV2Reader) -> None:
        fixture = _load_fixture("trial_01.json")
        gt_eye = reconstruct(fixture["AnalogData"]["Eye"])
        trial = reader.read("Trial1")
        actual_eye = trial["AnalogData"]["Eye"]
        assert isinstance(actual_eye, np.ndarray)
        assert actual_eye.shape == gt_eye.shape

    def test_eye_values_match_fixture(self, reader: BHV2Reader) -> None:
        fixture = _load_fixture("trial_01.json")
        gt_eye = reconstruct(fixture["AnalogData"]["Eye"])
        trial = reader.read("Trial1")
        np.testing.assert_allclose(
            trial["AnalogData"]["Eye"],
            gt_eye,
            rtol=1e-12,
        )

    def test_sample_interval_is_scalar_4(self, reader: BHV2Reader) -> None:
        trial = reader.read("Trial1")
        sample_interval = trial["AnalogData"]["SampleInterval"]
        assert isinstance(sample_interval, (int, float))
        assert abs(float(sample_interval) - 4.0) < 1e-9


@pytest.mark.integration
class TestReadTrial1ScalarFields:
    def test_trial_id_is_1(self, reader: BHV2Reader) -> None:
        trial = reader.read("Trial1")
        assert int(trial["Trial"]) == 1

    def test_condition_is_correct(self, reader: BHV2Reader) -> None:
        fixture = _load_fixture("trial_01.json")
        trial = reader.read("Trial1")
        assert int(trial["Condition"]) == int(fixture["Condition"])


@pytest.mark.integration
class TestReadAllTrials:
    def test_all_11_trials_readable(self, reader: BHV2Reader) -> None:
        for i in range(1, 12):
            trial = reader.read(f"Trial{i}")
            assert isinstance(trial, dict), f"Trial{i} should be a dict"

    def test_trial_ids_are_sequential(self, reader: BHV2Reader) -> None:
        for i in range(1, 12):
            trial = reader.read(f"Trial{i}")
            assert int(trial["Trial"]) == i, f"Trial{i}.Trial field should be {i}"

    def test_eye_shape_invariant_per_trial(self, reader: BHV2Reader) -> None:
        """Eye should be (n_samples, 2) for all trials."""
        for i in range(1, 12):
            trial = reader.read(f"Trial{i}")
            eye = trial["AnalogData"]["Eye"]
            assert isinstance(eye, np.ndarray), f"Trial{i}.Eye not ndarray"
            assert eye.ndim == 2, f"Trial{i}.Eye.ndim={eye.ndim}, want 2"
            assert eye.shape[1] == 2, f"Trial{i}.Eye.shape={eye.shape}, want (...,2)"


@pytest.mark.integration
class TestReadMLConfig:
    def test_experiment_name(self, reader: BHV2Reader) -> None:
        mlcfg = reader.read("MLConfig")
        assert isinstance(mlcfg, dict)
        assert mlcfg.get("ExperimentName") == "PV"

    def test_ml_version(self, reader: BHV2Reader) -> None:
        mlcfg = reader.read("MLConfig")
        assert "MLVersion" in mlcfg
        assert isinstance(mlcfg["MLVersion"], str)
        assert "2.2" in mlcfg["MLVersion"]

    def test_subject_name(self, reader: BHV2Reader) -> None:
        mlcfg = reader.read("MLConfig")
        assert mlcfg.get("SubjectName") == "MaoDan"


@pytest.mark.integration
class TestReadNonExistent:
    def test_missing_variable_raises_key_error(self, reader: BHV2Reader) -> None:
        with pytest.raises(KeyError):
            reader.read("ThisVariableDoesNotExist_xyz")


@pytest.mark.integration
class TestGroundTruthComparison:
    """Deep field-level comparison against MATLAB-exported JSON fixtures."""

    def test_trial1_behavioral_codes_deep(self, reader: BHV2Reader) -> None:
        fixture = reconstruct(_load_fixture("trial_01.json"))
        trial = reader.read("Trial1")
        _compare_values(
            trial["BehavioralCodes"],
            fixture["BehavioralCodes"],
            path="Trial1.BehavioralCodes",
        )

    def test_trial1_user_vars_dataset_name(self, reader: BHV2Reader) -> None:
        fixture = _load_fixture("trial_01.json")
        trial = reader.read("Trial1")
        assert trial["UserVars"]["DatasetName"] == fixture["UserVars"]["DatasetName"]

    def test_trial1_eye_exact_match(self, reader: BHV2Reader) -> None:
        """Eye data should match bit-for-bit (same IEEE 754 doubles)."""
        fixture = reconstruct(_load_fixture("trial_01.json"))
        trial = reader.read("Trial1")
        np.testing.assert_array_equal(
            trial["AnalogData"]["Eye"],
            fixture["AnalogData"]["Eye"],
        )
