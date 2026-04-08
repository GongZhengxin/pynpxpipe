"""Tests for stages/export.py — ExportStage.

Groups:
  A. Normal flow   — NWBWriter called, checkpoint written, gc invoked
  B. Output path   — _get_output_path returns correct path
  C. Checkpoint skip — stage complete → run() no-ops
  D. Error handling — write failure → unlink + ExportError + failed checkpoint
  E. Call order    — create_file before add_probe_data, write after add_trials
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pynpxpipe.core.config import PipelineConfig, ResourcesConfig
from pynpxpipe.core.errors import ExportError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.stages.export import ExportStage

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="TestMon",
        description="test monkey",
        species="Macaca mulatta",
        sex="M",
        age="P3Y",
        weight="10kg",
    )


def _make_probe(probe_id: str, base: Path) -> ProbeInfo:
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=base / f"{probe_id}.ap.bin",
        ap_meta=base / f"{probe_id}.ap.meta",
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=384,
        serial_number="SN_TEST",
        probe_type="NP1010",
    )


def _make_behavior_events(output_dir: Path, n_trials: int = 5) -> pd.DataFrame:
    """Create a behavior_events.parquet in the sync/ subdirectory."""
    df = pd.DataFrame(
        {
            "trial_id": list(range(n_trials)),
            "onset_nidq_s": [float(i) for i in range(n_trials)],
            "stim_onset_nidq_s": [i + 0.1 for i in range(n_trials)],
            "condition_id": [1] * n_trials,
            "trial_valid": [True] * n_trials,
        }
    )
    sync_dir = output_dir / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(sync_dir / "behavior_events.parquet")
    return df


def _write_completed_checkpoint(session: Session, stage: str) -> None:
    cp_dir = session.output_dir / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    cp_path = cp_dir / f"{stage}.json"
    cp_path.write_text(json.dumps({"stage": stage, "status": "completed"}), encoding="utf-8")


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Session with two probes and behavior_events.parquet written."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
    s.probes = [_make_probe("imec0", tmp_path), _make_probe("imec1", tmp_path)]
    s.config = PipelineConfig(resources=ResourcesConfig())
    _make_behavior_events(output_dir)
    return s


@pytest.fixture
def single_session(tmp_path: Path) -> Session:
    """Session with one probe and behavior_events.parquet written."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
    s.probes = [_make_probe("imec0", tmp_path)]
    s.config = PipelineConfig(resources=ResourcesConfig())
    _make_behavior_events(output_dir)
    return s


def _make_mock_writer(nwb_path: Path | None = None) -> MagicMock:
    mock = MagicMock()
    if nwb_path is not None:
        mock.write.return_value = nwb_path
    else:
        mock.write.return_value = Path("/tmp/session_g0.nwb")
    mock.add_probe_data.return_value = 3  # n_units
    return mock


# ---------------------------------------------------------------------------
# Group A — Normal flow
# ---------------------------------------------------------------------------


class TestNormalFlow:
    def test_run_calls_writer_write(self, single_session: Session) -> None:
        """NWBWriter.write() is called once during a successful run."""
        mock_writer = _make_mock_writer()
        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        ):
            ExportStage(single_session).run()

        mock_writer.write.assert_called_once()

    def test_run_writes_checkpoint(self, single_session: Session) -> None:
        """checkpoints/export.json is written with status=completed after run()."""
        mock_writer = _make_mock_writer()
        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        ):
            ExportStage(single_session).run()

        cp = single_session.output_dir / "checkpoints" / "export.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "completed"

    def test_checkpoint_contains_nwb_path(self, single_session: Session) -> None:
        """Checkpoint payload includes nwb_path field."""
        nwb_path = single_session.output_dir / "session_g0.nwb"
        mock_writer = _make_mock_writer(nwb_path)
        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        ):
            ExportStage(single_session).run()

        cp = single_session.output_dir / "checkpoints" / "export.json"
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert "nwb_path" in data

    def test_add_probe_data_called_per_probe(self, session: Session) -> None:
        """add_probe_data() is called once for each probe (2 probes → 2 calls)."""
        mock_writer = _make_mock_writer()
        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        ):
            ExportStage(session).run()

        assert mock_writer.add_probe_data.call_count == 2

    def test_add_trials_called_once(self, single_session: Session) -> None:
        """add_trials() is called exactly once."""
        mock_writer = _make_mock_writer()
        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        ):
            ExportStage(single_session).run()

        mock_writer.add_trials.assert_called_once()

    def test_gc_called_after_each_probe(self, session: Session) -> None:
        """gc.collect() is called at least once per probe (2 probes → ≥ 2 calls)."""
        mock_writer = _make_mock_writer()
        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc") as mock_gc,
        ):
            ExportStage(session).run()

        assert mock_gc.collect.call_count >= 2


# ---------------------------------------------------------------------------
# Group B — Output path
# ---------------------------------------------------------------------------


class TestOutputPath:
    def test_get_output_path(self, single_session: Session) -> None:
        """_get_output_path returns output_dir/{session_dir.name}.nwb."""
        stage = ExportStage.__new__(ExportStage)
        stage.session = single_session
        stage.STAGE_NAME = "export"

        result = stage._get_output_path()

        expected = single_session.output_dir / "session_g0.nwb"
        assert result == expected


# ---------------------------------------------------------------------------
# Group C — Checkpoint skip
# ---------------------------------------------------------------------------


class TestCheckpointSkip:
    def test_skips_if_checkpoint_complete(self, single_session: Session) -> None:
        """run() returns immediately without creating NWBWriter when checkpoint is complete."""
        _write_completed_checkpoint(single_session, "export")

        with patch("pynpxpipe.stages.export.NWBWriter") as MockWriter:
            ExportStage(single_session).run()

        MockWriter.assert_not_called()


# ---------------------------------------------------------------------------
# Group D — Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_export_error_raised_on_write_failure(self, single_session: Session) -> None:
        """ExportError is raised when writer.write() raises."""
        mock_writer = MagicMock()
        mock_writer.write.side_effect = RuntimeError("disk full")

        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
            pytest.raises(ExportError),
        ):
            ExportStage(single_session).run()

    def test_partial_nwb_deleted_on_write_failure(self, single_session: Session) -> None:
        """Partial NWB file is deleted when writer.write() raises."""
        mock_writer = MagicMock()
        mock_writer.write.side_effect = RuntimeError("disk full")
        nwb_path = single_session.output_dir / "session_g0.nwb"
        # Create the partial file so unlink has something to delete
        nwb_path.parent.mkdir(parents=True, exist_ok=True)
        nwb_path.write_bytes(b"partial")

        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
            pytest.raises(ExportError),
        ):
            ExportStage(single_session).run()

        assert not nwb_path.exists()

    def test_failed_checkpoint_written_on_error(self, single_session: Session) -> None:
        """checkpoints/export.json with status=failed is written when run() fails."""
        mock_writer = MagicMock()
        mock_writer.write.side_effect = RuntimeError("disk full")

        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
            pytest.raises(ExportError),
        ):
            ExportStage(single_session).run()

        cp = single_session.output_dir / "checkpoints" / "export.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "failed"

    def test_nwb_verification_failure_raises(self, single_session: Session) -> None:
        """ExportError is raised when NWBHDF5IO verification fails."""
        mock_writer = _make_mock_writer()
        mock_pynwb = MagicMock()
        mock_pynwb.NWBHDF5IO.side_effect = RuntimeError("corrupt HDF5")

        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb", mock_pynwb),
            patch("pynpxpipe.stages.export.gc"),
            pytest.raises(ExportError),
        ):
            ExportStage(single_session).run()

    def test_nwb_deleted_on_verification_failure(self, single_session: Session) -> None:
        """Partial NWB file is deleted when verification (NWBHDF5IO) fails."""
        nwb_path = single_session.output_dir / "session_g0.nwb"
        mock_writer = _make_mock_writer(nwb_path)
        nwb_path.parent.mkdir(parents=True, exist_ok=True)
        nwb_path.write_bytes(b"partial")
        mock_pynwb = MagicMock()
        mock_pynwb.NWBHDF5IO.side_effect = RuntimeError("corrupt HDF5")

        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb", mock_pynwb),
            patch("pynpxpipe.stages.export.gc"),
            pytest.raises(ExportError),
        ):
            ExportStage(single_session).run()

        assert not nwb_path.exists()


# ---------------------------------------------------------------------------
# Group E — Call order
# ---------------------------------------------------------------------------


class TestCallOrder:
    def test_create_file_called_before_add_probe_data(self, single_session: Session) -> None:
        """create_file() is called before add_probe_data()."""
        mock_writer = _make_mock_writer()
        call_order: list[str] = []
        mock_writer.create_file.side_effect = lambda: call_order.append("create_file")
        mock_writer.add_probe_data.side_effect = lambda *a, **kw: call_order.append(
            "add_probe_data"
        )

        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        ):
            ExportStage(single_session).run()

        assert call_order.index("create_file") < call_order.index("add_probe_data")

    def test_write_called_after_add_trials(self, single_session: Session) -> None:
        """write() is called after add_trials()."""
        mock_writer = _make_mock_writer()
        call_order: list[str] = []
        mock_writer.add_trials.side_effect = lambda *a, **kw: call_order.append("add_trials")
        mock_writer.write.side_effect = lambda: (
            call_order.append("write") or Path("/tmp/session_g0.nwb")
        )

        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        ):
            ExportStage(single_session).run()

        assert call_order.index("add_trials") < call_order.index("write")
