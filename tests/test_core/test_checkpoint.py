"""Tests for core/checkpoint.py — CheckpointManager.

Covers all 16 test points from spec section 10.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pynpxpipe.core.errors import CheckpointError

# ---------------------------------------------------------------------------
# Helper: create a CheckpointManager with get_logger mocked
# ---------------------------------------------------------------------------

def _make_manager(tmp_path: Path):
    """Return a CheckpointManager for tmp_path with get_logger mocked."""
    with patch("pynpxpipe.core.checkpoint.get_logger") as mock_gl:
        mock_gl.return_value = MagicMock()
        from pynpxpipe.core.checkpoint import CheckpointManager
        mgr = CheckpointManager(tmp_path)
    # Keep mock alive via the manager's stored logger (already assigned)
    return mgr


# ---------------------------------------------------------------------------
# Test 1: __init__ creates checkpoints/ subdirectory
# ---------------------------------------------------------------------------

def test_init_creates_checkpoints_dir(tmp_path):
    """CheckpointManager(output_dir) must create output_dir/checkpoints/."""
    with patch("pynpxpipe.core.checkpoint.get_logger", return_value=MagicMock()):
        from pynpxpipe.core.checkpoint import CheckpointManager
        CheckpointManager(tmp_path)
    assert (tmp_path / "checkpoints").is_dir()


def test_init_checkpoints_dir_already_exists(tmp_path):
    """__init__ must not fail if checkpoints/ already exists."""
    (tmp_path / "checkpoints").mkdir()
    with patch("pynpxpipe.core.checkpoint.get_logger", return_value=MagicMock()):
        from pynpxpipe.core.checkpoint import CheckpointManager
        CheckpointManager(tmp_path)  # should not raise
    assert (tmp_path / "checkpoints").is_dir()


# ---------------------------------------------------------------------------
# Test 2: mark_complete (stage-level) writes discover.json with status=completed
# ---------------------------------------------------------------------------

def test_mark_complete_stage_level_creates_file(tmp_path):
    """mark_complete('discover', {...}) writes discover.json."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 2, "probe_ids": ["imec0", "imec1"]})
    assert (tmp_path / "checkpoints" / "discover.json").exists()


def test_mark_complete_stage_level_status_completed(tmp_path):
    """discover.json must contain status='completed'."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 2})
    data = json.loads((tmp_path / "checkpoints" / "discover.json").read_text(encoding="utf-8"))
    assert data["status"] == "completed"


def test_mark_complete_stage_level_contains_stage_name(tmp_path):
    """discover.json must contain stage='discover'."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 2})
    data = json.loads((tmp_path / "checkpoints" / "discover.json").read_text(encoding="utf-8"))
    assert data["stage"] == "discover"


def test_mark_complete_stage_level_contains_completed_at(tmp_path):
    """discover.json must contain completed_at timestamp."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 2})
    data = json.loads((tmp_path / "checkpoints" / "discover.json").read_text(encoding="utf-8"))
    assert "completed_at" in data


def test_mark_complete_stage_level_merges_data(tmp_path):
    """discover.json must contain the data payload fields."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 2, "nidq_found": True})
    data = json.loads((tmp_path / "checkpoints" / "discover.json").read_text(encoding="utf-8"))
    assert data["n_probes"] == 2
    assert data["nidq_found"] is True


def test_mark_complete_stage_level_no_probe_id_key(tmp_path):
    """Stage-level checkpoint must NOT contain probe_id key."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 2})
    data = json.loads((tmp_path / "checkpoints" / "discover.json").read_text(encoding="utf-8"))
    assert "probe_id" not in data


# ---------------------------------------------------------------------------
# Test 3: mark_complete (probe-level) writes preprocess_imec0.json
# ---------------------------------------------------------------------------

def test_mark_complete_probe_level_creates_file(tmp_path):
    """mark_complete('preprocess', {...}, probe_id='imec0') writes preprocess_imec0.json."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("preprocess", {"n_channels_after": 381}, probe_id="imec0")
    assert (tmp_path / "checkpoints" / "preprocess_imec0.json").exists()


def test_mark_complete_probe_level_contains_probe_id(tmp_path):
    """Probe-level checkpoint must contain probe_id field."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("preprocess", {"n_channels_after": 381}, probe_id="imec0")
    data = json.loads(
        (tmp_path / "checkpoints" / "preprocess_imec0.json").read_text(encoding="utf-8")
    )
    assert data["probe_id"] == "imec0"


def test_mark_complete_probe_level_status_completed(tmp_path):
    """Probe-level checkpoint must have status='completed'."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("preprocess", {"n_channels_after": 381}, probe_id="imec0")
    data = json.loads(
        (tmp_path / "checkpoints" / "preprocess_imec0.json").read_text(encoding="utf-8")
    )
    assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Test 4: is_complete — file exists with status=completed → True
# ---------------------------------------------------------------------------

def test_is_complete_returns_true_when_completed(tmp_path):
    """is_complete('discover') returns True if discover.json has status=completed."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 1})
    assert mgr.is_complete("discover") is True


def test_is_complete_probe_level_returns_true_when_completed(tmp_path):
    """is_complete('preprocess', 'imec0') returns True for probe-level completed."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("preprocess", {"n_channels_after": 381}, probe_id="imec0")
    assert mgr.is_complete("preprocess", "imec0") is True


# ---------------------------------------------------------------------------
# Test 5: is_complete — file does not exist → False
# ---------------------------------------------------------------------------

def test_is_complete_returns_false_when_no_file(tmp_path):
    """is_complete('discover') returns False when no checkpoint file exists."""
    mgr = _make_manager(tmp_path)
    assert mgr.is_complete("discover") is False


def test_is_complete_probe_level_returns_false_when_no_file(tmp_path):
    """is_complete('sort', 'imec0') returns False when file is absent."""
    mgr = _make_manager(tmp_path)
    assert mgr.is_complete("sort", "imec0") is False


# ---------------------------------------------------------------------------
# Test 6: is_complete — status="failed" → False
# ---------------------------------------------------------------------------

def test_is_complete_returns_false_for_failed_status(tmp_path):
    """is_complete('sort', 'imec0') returns False when status='failed'."""
    mgr = _make_manager(tmp_path)
    mgr.mark_failed("sort", "CUDA OOM", probe_id="imec0")
    assert mgr.is_complete("sort", "imec0") is False


# ---------------------------------------------------------------------------
# Test 7: is_complete — JSON corrupted → raise CheckpointError
# ---------------------------------------------------------------------------

def test_is_complete_raises_checkpoint_error_on_corrupt_json(tmp_path):
    """is_complete raises CheckpointError if checkpoint file has invalid JSON."""
    ckpt_dir = tmp_path / "checkpoints"
    ckpt_dir.mkdir()
    corrupt_file = ckpt_dir / "sort_imec0.json"
    corrupt_file.write_text("{ NOT VALID JSON }", encoding="utf-8")

    mgr = _make_manager(tmp_path)
    with pytest.raises(CheckpointError) as exc_info:
        mgr.is_complete("sort", "imec0")
    assert exc_info.value.stage == "sort"


# ---------------------------------------------------------------------------
# Test 8: mark_failed writes status="failed" and error field
# ---------------------------------------------------------------------------

def test_mark_failed_creates_file_with_status_failed(tmp_path):
    """mark_failed writes sort_imec0.json with status='failed'."""
    mgr = _make_manager(tmp_path)
    mgr.mark_failed("sort", "CUDA OOM", probe_id="imec0")
    data = json.loads(
        (tmp_path / "checkpoints" / "sort_imec0.json").read_text(encoding="utf-8")
    )
    assert data["status"] == "failed"


def test_mark_failed_contains_error_field(tmp_path):
    """mark_failed writes the error message into the 'error' field."""
    mgr = _make_manager(tmp_path)
    mgr.mark_failed("sort", "CUDA OOM", probe_id="imec0")
    data = json.loads(
        (tmp_path / "checkpoints" / "sort_imec0.json").read_text(encoding="utf-8")
    )
    assert data["error"] == "CUDA OOM"


def test_mark_failed_stage_level_no_probe_id(tmp_path):
    """mark_failed without probe_id writes stage-level file without probe_id key."""
    mgr = _make_manager(tmp_path)
    mgr.mark_failed("discover", "some error")
    assert (tmp_path / "checkpoints" / "discover.json").exists()
    data = json.loads((tmp_path / "checkpoints" / "discover.json").read_text(encoding="utf-8"))
    assert "probe_id" not in data


def test_mark_failed_contains_failed_at(tmp_path):
    """mark_failed checkpoint must contain failed_at timestamp, not completed_at."""
    mgr = _make_manager(tmp_path)
    mgr.mark_failed("sort", "CUDA OOM", probe_id="imec0")
    data = json.loads(
        (tmp_path / "checkpoints" / "sort_imec0.json").read_text(encoding="utf-8")
    )
    assert "failed_at" in data
    assert "completed_at" not in data


# ---------------------------------------------------------------------------
# Test 9: read — file exists → returns full dict
# ---------------------------------------------------------------------------

def test_read_returns_dict_when_file_exists(tmp_path):
    """read('discover') returns the full checkpoint dict."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 2, "probe_ids": ["imec0"]})
    result = mgr.read("discover")
    assert isinstance(result, dict)
    assert result["stage"] == "discover"
    assert result["n_probes"] == 2


def test_read_probe_level_returns_dict(tmp_path):
    """read('preprocess', 'imec0') returns probe-level checkpoint dict."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("preprocess", {"n_channels_after": 381}, probe_id="imec0")
    result = mgr.read("preprocess", "imec0")
    assert result is not None
    assert result["probe_id"] == "imec0"


# ---------------------------------------------------------------------------
# Test 10: read — file does not exist → returns None
# ---------------------------------------------------------------------------

def test_read_returns_none_when_file_missing(tmp_path):
    """read('discover') returns None if no checkpoint file exists."""
    mgr = _make_manager(tmp_path)
    assert mgr.read("discover") is None


def test_read_probe_level_returns_none_when_missing(tmp_path):
    """read('sort', 'imec0') returns None if probe checkpoint is absent."""
    mgr = _make_manager(tmp_path)
    assert mgr.read("sort", "imec0") is None


# ---------------------------------------------------------------------------
# Test 11: clear — file exists → file is deleted
# ---------------------------------------------------------------------------

def test_clear_deletes_existing_file(tmp_path):
    """clear('discover') removes discover.json if it exists."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 1})
    assert (tmp_path / "checkpoints" / "discover.json").exists()
    mgr.clear("discover")
    assert not (tmp_path / "checkpoints" / "discover.json").exists()


def test_clear_probe_level_deletes_file(tmp_path):
    """clear('preprocess', 'imec0') removes preprocess_imec0.json."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("preprocess", {"n_channels_after": 381}, probe_id="imec0")
    mgr.clear("preprocess", "imec0")
    assert not (tmp_path / "checkpoints" / "preprocess_imec0.json").exists()


# ---------------------------------------------------------------------------
# Test 12: clear — file does not exist → silent, no exception
# ---------------------------------------------------------------------------

def test_clear_nonexistent_file_does_not_raise(tmp_path):
    """clear('discover') when file is absent must not raise any exception."""
    mgr = _make_manager(tmp_path)
    mgr.clear("discover")  # should not raise


def test_clear_probe_level_nonexistent_does_not_raise(tmp_path):
    """clear('sort', 'imec0') when absent must not raise."""
    mgr = _make_manager(tmp_path)
    mgr.clear("sort", "imec0")  # should not raise


# ---------------------------------------------------------------------------
# Test 13: list_completed_stages — correct stage names, deduplicated
# ---------------------------------------------------------------------------

def test_list_completed_stages_returns_completed_names(tmp_path):
    """list_completed_stages returns stage names of all completed checkpoints."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 2})
    mgr.mark_complete("preprocess", {"n_channels_after": 381}, probe_id="imec0")
    mgr.mark_complete("preprocess", {"n_channels_after": 379}, probe_id="imec1")
    result = mgr.list_completed_stages()
    assert "discover" in result
    assert "preprocess" in result


def test_list_completed_stages_excludes_failed(tmp_path):
    """list_completed_stages must not include failed stages."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 2})
    mgr.mark_failed("sort", "CUDA OOM", probe_id="imec0")
    result = mgr.list_completed_stages()
    assert "discover" in result
    assert "sort" not in result


def test_list_completed_stages_deduplicates(tmp_path):
    """list_completed_stages returns each stage name only once even with multiple probes."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("preprocess", {"n_channels_after": 381}, probe_id="imec0")
    mgr.mark_complete("preprocess", {"n_channels_after": 379}, probe_id="imec1")
    result = mgr.list_completed_stages()
    assert result.count("preprocess") == 1


def test_list_completed_stages_empty_when_none(tmp_path):
    """list_completed_stages returns [] when no stages completed."""
    mgr = _make_manager(tmp_path)
    assert mgr.list_completed_stages() == []


# ---------------------------------------------------------------------------
# Test 14: atomic write — mock Path.replace raises OSError → tmp file cleaned up,
#          CheckpointError raised
# ---------------------------------------------------------------------------

def test_atomic_write_cleans_tmp_file_on_error(tmp_path):
    """If Path.replace fails, the .tmp file must be deleted and CheckpointError raised."""
    mgr = _make_manager(tmp_path)

    def fake_replace(self, target):
        raise OSError("simulated disk error")

    with patch.object(Path, "replace", fake_replace), pytest.raises(CheckpointError):
        mgr.mark_complete("discover", {"n_probes": 1})

    # The .tmp file must have been cleaned up
    tmp_files = list((tmp_path / "checkpoints").glob("*.tmp"))
    assert tmp_files == [], f"Unexpected .tmp files left: {tmp_files}"


def test_atomic_write_raises_checkpoint_error_on_oserror(tmp_path):
    """mark_complete must raise CheckpointError (not raw OSError) when replace fails."""
    mgr = _make_manager(tmp_path)

    def fake_replace(self, target):
        raise OSError("simulated disk error")

    with patch.object(Path, "replace", fake_replace), pytest.raises(CheckpointError) as exc_info:
        mgr.mark_complete("discover", {"n_probes": 1})
    assert exc_info.value.stage == "discover"


# ---------------------------------------------------------------------------
# Test 15: mark_complete called multiple times → latest result overwrites
# ---------------------------------------------------------------------------

def test_mark_complete_overwrites_on_repeat_call(tmp_path):
    """Calling mark_complete twice for same stage writes latest data."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("discover", {"n_probes": 1})
    mgr.mark_complete("discover", {"n_probes": 3})
    data = json.loads((tmp_path / "checkpoints" / "discover.json").read_text(encoding="utf-8"))
    assert data["n_probes"] == 3


def test_mark_complete_probe_level_overwrites(tmp_path):
    """Repeated probe-level mark_complete overwrites with latest data."""
    mgr = _make_manager(tmp_path)
    mgr.mark_complete("sort", {"n_units": 100}, probe_id="imec0")
    mgr.mark_complete("sort", {"n_units": 142}, probe_id="imec0")
    data = json.loads(
        (tmp_path / "checkpoints" / "sort_imec0.json").read_text(encoding="utf-8")
    )
    assert data["n_units"] == 142


# ---------------------------------------------------------------------------
# Test 16: mark_failed write failure → no raise (does not propagate)
# ---------------------------------------------------------------------------

def test_mark_failed_does_not_raise_on_write_failure(tmp_path):
    """mark_failed must NOT raise even if the file write fails (avoids masking original error)."""
    mgr = _make_manager(tmp_path)

    # Patch _atomic_write to always raise CheckpointError
    with patch.object(mgr, "_atomic_write", side_effect=CheckpointError("sort", tmp_path, "disk full")):
        # Should NOT raise
        mgr.mark_failed("sort", "original pipeline error", probe_id="imec0")
