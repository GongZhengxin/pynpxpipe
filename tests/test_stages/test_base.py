"""Tests for stages/base.py — BaseStage abstract base class.

Groups:
  A. __init__ — stores session, callback, creates logger + CheckpointManager
  B. _report_progress — invokes callback and logs
  C. Checkpoint integration — _is_complete, _write_checkpoint, _write_failed_checkpoint
  D. STAGE_NAME guard — empty name raises ValueError on construction
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pynpxpipe.core.checkpoint import CheckpointManager
from pynpxpipe.core.session import Session, SessionManager, SubjectConfig
from pynpxpipe.stages.base import BaseStage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="test",
        description="desc",
        species="Macaca mulatta",
        sex="M",
        age="P3Y",
        weight="10kg",
    )


def _make_session(tmp_path: Path) -> Session:
    session_dir = tmp_path / "data_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.touch()
    output_dir = tmp_path / "output"
    return SessionManager.create(
        session_dir,
        bhv_file,
        _make_subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4"},
        date="240101",
    )


class ConcreteStage(BaseStage):
    """Minimal concrete subclass for testing BaseStage."""

    STAGE_NAME = "test_stage"

    def run(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Group A — __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_stores_session(self, tmp_path):
        session = _make_session(tmp_path)
        stage = ConcreteStage(session)
        assert stage.session is session

    def test_progress_callback_defaults_to_none(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        assert stage.progress_callback is None

    def test_stores_provided_callback(self, tmp_path):
        def cb(msg: str, frac: float) -> None:
            pass

        stage = ConcreteStage(_make_session(tmp_path), progress_callback=cb)
        assert stage.progress_callback is cb

    def test_has_checkpoint_manager(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        assert isinstance(stage.checkpoint_manager, CheckpointManager)

    def test_checkpoint_manager_uses_session_output_dir(self, tmp_path):
        session = _make_session(tmp_path)
        ConcreteStage(session)
        # CheckpointManager creates {output_dir}/checkpoints/
        assert (session.output_dir / "checkpoints").is_dir()

    def test_has_logger(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        assert stage.logger is not None


# ---------------------------------------------------------------------------
# Group B — _report_progress
# ---------------------------------------------------------------------------


class TestReportProgress:
    def test_calls_callback_with_message_and_fraction(self, tmp_path):
        calls: list[tuple[str, float]] = []
        stage = ConcreteStage(
            _make_session(tmp_path),
            progress_callback=lambda m, f: calls.append((m, f)),
        )
        stage._report_progress("half done", 0.5)
        assert calls == [("test_stage:half done", 0.5)]

    def test_multiple_calls_all_forwarded(self, tmp_path):
        calls: list[tuple[str, float]] = []
        stage = ConcreteStage(
            _make_session(tmp_path),
            progress_callback=lambda m, f: calls.append((m, f)),
        )
        stage._report_progress("start", 0.0)
        stage._report_progress("end", 1.0)
        assert len(calls) == 2
        assert calls[1] == ("test_stage:end", 1.0)

    def test_no_callback_does_not_raise(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        stage._report_progress("no callback", 0.5)  # must not raise


# ---------------------------------------------------------------------------
# Group C — Checkpoint integration
# ---------------------------------------------------------------------------


class TestCheckpointIntegration:
    def test_is_complete_false_initially(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        assert stage._is_complete() is False

    def test_is_complete_true_after_write_checkpoint(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        stage._write_checkpoint({"n_units": 100})
        assert stage._is_complete() is True

    def test_probe_is_complete_false_initially(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        assert stage._is_complete(probe_id="imec0") is False

    def test_probe_is_complete_true_after_write_probe_checkpoint(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        stage._write_checkpoint({"n_spikes": 50000}, probe_id="imec0")
        assert stage._is_complete(probe_id="imec0") is True

    def test_stage_complete_does_not_affect_probe_check(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        stage._write_checkpoint({})  # stage-level
        assert stage._is_complete(probe_id="imec0") is False

    def test_probe_complete_does_not_affect_stage_check(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        stage._write_checkpoint({}, probe_id="imec0")
        assert stage._is_complete() is False

    def test_write_failed_checkpoint_stage_not_complete(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        stage._write_failed_checkpoint(ValueError("oops"))
        assert stage._is_complete() is False

    def test_write_failed_checkpoint_records_failed_status(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        stage._write_failed_checkpoint(RuntimeError("disk full"))
        data = stage.checkpoint_manager.read(stage.STAGE_NAME)
        assert data is not None
        assert data.get("status") == "failed"

    def test_write_failed_probe_checkpoint_records_error(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        stage._write_failed_checkpoint(OSError("disk full"), probe_id="imec1")
        data = stage.checkpoint_manager.read(stage.STAGE_NAME, probe_id="imec1")
        assert data is not None
        assert data.get("status") == "failed"


# ---------------------------------------------------------------------------
# Group D — STAGE_NAME guard
# ---------------------------------------------------------------------------


class TestStageNameGuard:
    def test_empty_stage_name_raises_on_init(self, tmp_path):
        class NoNameStage(BaseStage):
            STAGE_NAME = ""

            def run(self) -> None:
                pass

        with pytest.raises(ValueError, match="STAGE_NAME"):
            NoNameStage(_make_session(tmp_path))

    def test_valid_stage_name_does_not_raise(self, tmp_path):
        stage = ConcreteStage(_make_session(tmp_path))
        assert stage.STAGE_NAME == "test_stage"
