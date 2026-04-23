"""Tests for core/logging.py — structured logging setup.

Tests follow the spec section 8 test points exactly, using tmp_path
fixtures for file isolation and json.loads for JSON Lines validation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from pynpxpipe.core.logging import StageLogger, get_logger, setup_logging

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_jsonlines(log_path: Path) -> list[dict]:
    """Read a JSON Lines file and return a list of parsed dicts."""
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _setup_and_write(log_path: Path, write_fn) -> list[dict]:
    """Setup logging, execute write_fn, return parsed log lines."""
    setup_logging(log_path)
    write_fn()
    return _read_jsonlines(log_path)


# ---------------------------------------------------------------------------
# Test 1: setup_logging creates a log file when parent dir exists
# ---------------------------------------------------------------------------


def test_setup_logging_creates_log_file(tmp_path: Path) -> None:
    """setup_logging(log_path) creates the log file when parent dir exists."""
    log_path = tmp_path / "pipeline.log"
    assert not log_path.exists()
    setup_logging(log_path)
    assert log_path.exists()


# ---------------------------------------------------------------------------
# Test 2: setup_logging raises OSError when parent dir does not exist
# ---------------------------------------------------------------------------


def test_setup_logging_missing_parent_raises_oserror(tmp_path: Path) -> None:
    """setup_logging raises OSError when parent directory does not exist."""
    log_path = tmp_path / "nonexistent_dir" / "pipeline.log"
    with pytest.raises(OSError):
        setup_logging(log_path)


# ---------------------------------------------------------------------------
# Test 3: get_logger returns BoundLogger, .info() does not raise
# ---------------------------------------------------------------------------


def test_get_logger_returns_bound_logger_and_info_does_not_raise(tmp_path: Path) -> None:
    """get_logger('foo') returns a structlog logger proxy; calling .info() does not raise.

    structlog.get_logger() returns a BoundLoggerLazyProxy that wraps BoundLogger.
    We verify it has the expected .info() interface rather than checking exact type.
    """
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)
    logger = get_logger("foo")
    # structlog returns a BoundLoggerLazyProxy that wraps BoundLogger after setup_logging
    # configures wrapper_class=structlog.stdlib.BoundLogger.
    # The proxy implements the same interface; verify it has .info callable.
    assert callable(getattr(logger, "info", None))
    # Should not raise
    logger.info("test message from get_logger")


# ---------------------------------------------------------------------------
# Test 4: StageLogger.start() writes stage_start JSON line
# ---------------------------------------------------------------------------


def test_stage_logger_start_writes_stage_start(tmp_path: Path) -> None:
    """StageLogger.start() writes a JSON line with event='stage_start'."""
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)
    sl = StageLogger("sort", "imec0")
    sl.start()

    lines = _read_jsonlines(log_path)
    assert len(lines) >= 1
    events = [ln["event"] for ln in lines]
    assert "stage_start" in events


# ---------------------------------------------------------------------------
# Test 5: StageLogger.complete({"n_units": 42}) writes required fields
# ---------------------------------------------------------------------------


def test_stage_logger_complete_with_data(tmp_path: Path) -> None:
    """StageLogger.complete({'n_units': 42}) writes stage_complete, elapsed_s, n_units."""
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)
    sl = StageLogger("sort", "imec0")
    sl.start()
    sl.complete({"n_units": 42})

    lines = _read_jsonlines(log_path)
    complete_lines = [ln for ln in lines if ln.get("event") == "stage_complete"]
    assert len(complete_lines) == 1
    entry = complete_lines[0]
    assert "elapsed_s" in entry
    assert isinstance(entry["elapsed_s"], (int, float))
    assert entry["n_units"] == 42


# ---------------------------------------------------------------------------
# Test 6: StageLogger.complete() without start() gives elapsed_s=0, no raise
# ---------------------------------------------------------------------------


def test_stage_logger_complete_without_start_gives_zero_elapsed(tmp_path: Path) -> None:
    """complete() before start() sets elapsed_s=0.0 and does not raise."""
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)
    sl = StageLogger("sort", "imec0")
    # Intentionally skip sl.start()
    sl.complete()  # must not raise

    lines = _read_jsonlines(log_path)
    complete_lines = [ln for ln in lines if ln.get("event") == "stage_complete"]
    assert len(complete_lines) == 1
    assert complete_lines[0]["elapsed_s"] == 0.0


# ---------------------------------------------------------------------------
# Test 7: StageLogger.error(exc) writes stage_failed with error and traceback
# ---------------------------------------------------------------------------


def test_stage_logger_error_writes_stage_failed(tmp_path: Path) -> None:
    """StageLogger.error(exc) writes stage_failed with 'error' and 'traceback' fields."""
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)
    sl = StageLogger("sort", "imec0")
    sl.start()

    try:
        raise ValueError("CUDA out of memory")
    except ValueError as exc:
        sl.error(exc)

    lines = _read_jsonlines(log_path)
    failed_lines = [ln for ln in lines if ln.get("event") == "stage_failed"]
    assert len(failed_lines) == 1
    entry = failed_lines[0]
    assert "error" in entry
    assert "traceback" in entry
    assert isinstance(entry["error"], str)
    assert isinstance(entry["traceback"], str)
    assert "CUDA out of memory" in entry["error"]


# ---------------------------------------------------------------------------
# Test 8: StageLogger.info("msg", progress=0.5) writes event and progress fields
# ---------------------------------------------------------------------------


def test_stage_logger_info_with_progress(tmp_path: Path) -> None:
    """StageLogger.info('msg', progress=0.5) writes event='msg' and progress=0.5."""
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)
    sl = StageLogger("postprocess", "imec0")
    sl.info("Extracting waveforms", progress=0.5)

    lines = _read_jsonlines(log_path)
    progress_lines = [ln for ln in lines if ln.get("event") == "Extracting waveforms"]
    assert len(progress_lines) == 1
    entry = progress_lines[0]
    assert entry["progress"] == 0.5


# ---------------------------------------------------------------------------
# Test 9: Every line in the log file is valid JSON
# ---------------------------------------------------------------------------


def test_log_file_every_line_is_valid_json(tmp_path: Path) -> None:
    """All lines written by StageLogger are valid JSON objects."""
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)
    sl = StageLogger("discover", "imec0")
    sl.start()
    sl.info("Found probe", n_channels=384)
    sl.complete({"n_probes": 2})

    raw = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(raw) >= 3  # at least start, info, complete
    for line in raw:
        if line.strip():
            parsed = json.loads(line)  # must not raise
            assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# Test 10: stage and probe_id fields exist in all StageLogger output
# ---------------------------------------------------------------------------


def test_stage_and_probe_id_in_all_stage_logger_output(tmp_path: Path) -> None:
    """All StageLogger log lines contain 'stage' and 'probe_id' fields."""
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)
    sl = StageLogger("curate", "imec1")
    sl.start()
    sl.info("checking units")
    sl.complete({"n_units_kept": 10})

    lines = _read_jsonlines(log_path)
    assert len(lines) >= 3
    for entry in lines:
        assert "stage" in entry, f"Missing 'stage' in: {entry}"
        assert "probe_id" in entry, f"Missing 'probe_id' in: {entry}"
        assert entry["stage"] == "curate"
        assert entry["probe_id"] == "imec1"


# ---------------------------------------------------------------------------
# Test 11: setup_logging called twice does not double handlers
# ---------------------------------------------------------------------------


def test_setup_logging_twice_no_duplicate_handlers(tmp_path: Path) -> None:
    """Calling setup_logging twice clears old handlers; handler count does not double."""
    log_path1 = tmp_path / "pipeline1.log"
    log_path2 = tmp_path / "pipeline2.log"

    setup_logging(log_path1)
    handler_count_after_first = len(logging.getLogger().handlers)

    setup_logging(log_path2)
    handler_count_after_second = len(logging.getLogger().handlers)

    assert handler_count_after_second == handler_count_after_first, (
        f"Handler count grew from {handler_count_after_first} to "
        f"{handler_count_after_second} on second call"
    )


# ---------------------------------------------------------------------------
# Test 12: Third-party loggers (spikeinterface) suppressed below WARNING
# ---------------------------------------------------------------------------


def test_third_party_logger_suppressed(tmp_path: Path) -> None:
    """spikeinterface DEBUG messages do not appear; INFO and WARNING do.

    spikeinterface is set to INFO level (not WARNING) so that progress
    messages reach the UI log handler.  Only DEBUG is suppressed.
    """
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)

    # Emit a DEBUG message from spikeinterface — should NOT appear
    si_logger = logging.getLogger("spikeinterface")
    si_logger.debug("spikeinterface debug noise")
    si_logger.info("spikeinterface info noise")
    # Emit a WARNING — SHOULD appear
    si_logger.warning("spikeinterface warning message")

    lines = _read_jsonlines(log_path)
    events = [ln.get("event", "") for ln in lines]
    assert "spikeinterface debug noise" not in events
    # INFO is now allowed through (level=INFO for UI progress messages)
    assert "spikeinterface info noise" in events
    # Warning should be present
    assert any("spikeinterface warning message" in e for e in events)


# ---------------------------------------------------------------------------
# Test: StageLogger with probe_id=None stores null
# ---------------------------------------------------------------------------


def test_stage_logger_none_probe_id(tmp_path: Path) -> None:
    """StageLogger with probe_id=None writes probe_id=null (None) in JSON."""
    log_path = tmp_path / "pipeline.log"
    setup_logging(log_path)
    sl = StageLogger("discover", None)
    sl.start()

    lines = _read_jsonlines(log_path)
    start_lines = [ln for ln in lines if ln.get("event") == "stage_start"]
    assert len(start_lines) == 1
    assert start_lines[0]["probe_id"] is None
