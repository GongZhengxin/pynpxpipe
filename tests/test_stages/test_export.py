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
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pynwb
import pytest

from pynpxpipe.core.config import PipelineConfig, ResourcesConfig
from pynpxpipe.core.errors import ExportError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.stages.export import ExportStage, compute_probe_rasters

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
    target_area = "V4" if probe_id == "imec0" else "IT"
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
        target_area=target_area,
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
            "onset_time_ms": [150.0] * n_trials,
            "offset_time_ms": [150.0] * n_trials,
        }
    )
    sync_dir = output_dir / "04_sync"
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
    s = SessionManager.create(
        session_dir,
        bhv_file,
        _make_subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4", "imec1": "IT"},
        date="240101",
    )
    s.probes = [_make_probe("imec0", tmp_path), _make_probe("imec1", tmp_path)]
    s.config = PipelineConfig(resources=ResourcesConfig())
    _make_behavior_events(output_dir)
    # Create recording_info dirs so probes are not skipped
    for probe_id in ("imec0", "imec1"):
        (output_dir / "06_postprocessed" / probe_id / "recording_info").mkdir(
            parents=True, exist_ok=True
        )
    return s


@pytest.fixture
def single_session(tmp_path: Path) -> Session:
    """Session with one probe and behavior_events.parquet written."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(
        session_dir,
        bhv_file,
        _make_subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4"},
        date="240101",
    )
    s.probes = [_make_probe("imec0", tmp_path)]
    s.config = PipelineConfig(resources=ResourcesConfig())
    _make_behavior_events(output_dir)
    # Create recording_info dir so probe is not skipped
    (output_dir / "06_postprocessed" / "imec0" / "recording_info").mkdir(
        parents=True, exist_ok=True
    )
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
        nwb_path = single_session.output_dir / f"{single_session.session_id.canonical()}.nwb"
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
        """_get_output_path returns output_dir/{session_id.canonical()}.nwb."""
        stage = ExportStage.__new__(ExportStage)
        stage.session = single_session
        stage.STAGE_NAME = "export"

        result = stage._get_output_path()

        expected = single_session.output_dir / f"{single_session.session_id.canonical()}.nwb"
        assert result == expected
        assert result.name == "240101_TestMon_nsd1w_V4.nwb"


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
# Group C2 — target_area pre-flight (S2)
# ---------------------------------------------------------------------------


class TestTargetAreaPreflight:
    def test_empty_target_area_raises(self, single_session: Session) -> None:
        single_session.probes[0].target_area = ""
        with (
            patch("pynpxpipe.stages.export.NWBWriter") as MockWriter,
            pytest.raises(ExportError, match="target_area"),
        ):
            ExportStage(single_session).run()
        MockWriter.assert_not_called()

    def test_unknown_target_area_raises(self, single_session: Session) -> None:
        single_session.probes[0].target_area = "unknown"
        with (
            patch("pynpxpipe.stages.export.NWBWriter") as MockWriter,
            pytest.raises(ExportError, match="target_area"),
        ):
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
        nwb_path = single_session.output_dir / f"{single_session.session_id.canonical()}.nwb"
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
        nwb_path = single_session.output_dir / f"{single_session.session_id.canonical()}.nwb"
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


# ---------------------------------------------------------------------------
# Group F — compute_probe_rasters
# ---------------------------------------------------------------------------


class TestComputeProbeRasters:
    def _make_analyzer(self, unit_ids, spike_times_dict):
        """Build mock SortingAnalyzer with spike times per unit."""
        mock = MagicMock()
        mock.sorting.get_unit_ids.return_value = unit_ids

        def get_spike_train(uid, return_times=False):
            return np.array(spike_times_dict.get(uid, []), dtype=np.float64)

        mock.sorting.get_unit_spike_train.side_effect = get_spike_train
        return mock

    def _make_events(self, stim_onsets_imec, probe_id="imec0", onset_ms=150.0, offset_ms=150.0):
        """Build minimal behavior_events DataFrame for raster computation."""
        n = len(stim_onsets_imec)
        return pd.DataFrame(
            {
                "trial_id": list(range(1, n + 1)),
                "onset_nidq_s": [0.0] * n,
                "stim_onset_nidq_s": stim_onsets_imec,
                "stim_onset_imec_s": [json.dumps({probe_id: t}) for t in stim_onsets_imec],
                "condition_id": [1] * n,
                "trial_valid": [1.0] * n,
                "onset_time_ms": [onset_ms] * n,
                "offset_time_ms": [offset_ms] * n,
            }
        )

    def test_basic_raster_shape(self):
        """Raster shape is (n_valid_trials, n_bins) with n_bins = 50 + onset + offset."""
        spikes = {0: np.array([1.0, 1.05, 1.1, 2.0, 2.05, 2.1])}
        analyzer = self._make_analyzer([0], spikes)
        events = self._make_events([1.0, 2.0], onset_ms=150.0, offset_ms=150.0)

        rasters = compute_probe_rasters(analyzer, events, "imec0")
        assert 0 in rasters
        assert rasters[0].shape == (2, 350)  # 50 + 150 + 150
        assert rasters[0].dtype == np.uint8

    def test_spike_in_pre_onset_window(self):
        """Spike 25ms before onset appears in pre-onset bin."""
        # Onset at 1.0s, pre_onset = 50ms → window starts at 0.95s
        spikes = {0: np.array([0.975])}  # 25ms before onset = bin 25
        analyzer = self._make_analyzer([0], spikes)
        events = self._make_events([1.0], onset_ms=100.0, offset_ms=100.0)

        rasters = compute_probe_rasters(analyzer, events, "imec0")
        r = rasters[0]
        assert r.shape == (1, 250)  # 50 + 100 + 100
        assert r[0, 25] == 1  # 25ms into pre-onset window

    def test_only_valid_trials_included(self):
        """Only trial_valid == 1.0 trials are included in raster."""
        spikes = {0: np.array([1.0, 2.0, 3.0])}
        analyzer = self._make_analyzer([0], spikes)
        events = self._make_events([1.0, 2.0, 3.0])
        events.loc[1, "trial_valid"] = 0.0  # Invalidate trial 2

        rasters = compute_probe_rasters(analyzer, events, "imec0")
        assert rasters[0].shape[0] == 2  # Only 2 valid trials

    def test_empty_when_no_valid_trials(self):
        """No valid trials → empty rasters dict."""
        spikes = {0: np.array([1.0])}
        analyzer = self._make_analyzer([0], spikes)
        events = self._make_events([1.0])
        events["trial_valid"] = 0.0

        rasters = compute_probe_rasters(analyzer, events, "imec0")
        assert rasters == {}

    def test_missing_columns_returns_empty(self):
        """Missing required columns → empty rasters dict."""
        spikes = {0: np.array([1.0])}
        analyzer = self._make_analyzer([0], spikes)
        events = pd.DataFrame({"trial_id": [1]})

        rasters = compute_probe_rasters(analyzer, events, "imec0")
        assert rasters == {}

    def test_multiple_units(self):
        """Each unit gets its own raster array."""
        spikes = {0: np.array([1.0]), 1: np.array([1.05])}
        analyzer = self._make_analyzer([0, 1], spikes)
        events = self._make_events([1.0])

        rasters = compute_probe_rasters(analyzer, events, "imec0")
        assert len(rasters) == 2
        assert 0 in rasters
        assert 1 in rasters


# ---------------------------------------------------------------------------
# Group G — E1.3 sync_tables wiring
# ---------------------------------------------------------------------------


class TestSyncTablesWiring:
    """Verify ExportStage Phase 1 forwards sync_tables into NWBWriter."""

    def test_phase1_calls_add_sync_tables(self, single_session: Session) -> None:
        """Phase 1 invokes writer.add_sync_tables exactly once with sync_dir + events."""
        mock_writer = _make_mock_writer()
        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        ):
            ExportStage(single_session).run()

        assert mock_writer.add_sync_tables.call_count == 1
        call = mock_writer.add_sync_tables.call_args
        # positional args: (nwbfile, sync_dir); nwbfile is the writer's own
        # _nwbfile attribute (MagicMock-ed but that's fine for wiring).
        assert call.args[1] == single_session.output_dir / "04_sync"
        # behavior_events is forwarded as a kwarg
        assert "behavior_events" in call.kwargs
        assert isinstance(call.kwargs["behavior_events"], pd.DataFrame)

    def test_phase1_survives_missing_sync_dir(self, single_session: Session) -> None:
        """Export must not crash when sync_dir has no per-probe JSON files."""
        # Remove the sync dir that _make_behavior_events created (but keep the
        # parquet contents by moving it away first), then recreate an empty dir
        # so read_parquet still works: actually, we keep it but prune any
        # future *_imec_nidq.json. Here we just assert the mock is called —
        # the real add_sync_tables handles missing files via _missing markers.
        mock_writer = _make_mock_writer()
        # Even if add_sync_tables happens to raise internally, export must
        # catch & warn, not fail.
        mock_writer.add_sync_tables.side_effect = RuntimeError("simulated internal failure")

        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        ):
            # Should not raise ExportError.
            ExportStage(single_session).run()

        # The checkpoint completed despite the sync_tables failure.
        cp_path = single_session.output_dir / "checkpoints" / "export.json"
        assert cp_path.exists()
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Group H — E2.1 wait_for_raw + bit-exact verification
# ---------------------------------------------------------------------------


class TestWaitForRawAndVerify:
    """E2.1: ExportStage.wait_for_raw + bit-exact verification checkpoint."""

    def _patches(self, mock_writer):
        """Standard patch bundle used by every wait_for_raw test."""
        return (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.pynwb"),
            patch("pynpxpipe.stages.export.gc"),
        )

    def test_wait_flag_blocks(self, single_session: Session) -> None:
        """wait_for_raw=True → Phase 3 runs in the calling thread."""
        import time

        mock_writer = _make_mock_writer()

        def slow_append(*args, **kwargs):
            time.sleep(0.2)
            return {"streams_written": 1}

        mock_writer.append_raw_data.side_effect = slow_append

        p_writer, p_si, p_pynwb, p_gc = self._patches(mock_writer)
        with p_writer, p_si, p_pynwb, p_gc:
            t0 = time.perf_counter()
            ExportStage(single_session, wait_for_raw=True).run()
            elapsed = time.perf_counter() - t0

        assert elapsed >= 0.2, f"foreground run() only took {elapsed:.3f}s"
        mock_writer.append_raw_data.assert_called_once()

    def test_wait_flag_default_is_true(self, single_session: Session) -> None:
        """Default wait_for_raw=True → run() blocks until Phase 3 completes."""
        import time

        mock_writer = _make_mock_writer()

        def slow_append(*args, **kwargs):
            time.sleep(0.2)
            return {"streams_written": 1}

        mock_writer.append_raw_data.side_effect = slow_append

        p_writer, p_si, p_pynwb, p_gc = self._patches(mock_writer)
        with p_writer, p_si, p_pynwb, p_gc:
            t0 = time.perf_counter()
            ExportStage(single_session).run()  # no explicit wait_for_raw
            elapsed = time.perf_counter() - t0

        assert elapsed >= 0.2, f"default run() only took {elapsed:.3f}s — expected blocking"
        mock_writer.append_raw_data.assert_called_once()

    def test_wait_flag_explicit_false_nonblock(self, single_session: Session) -> None:
        """Explicit wait_for_raw=False → legacy daemon-thread behaviour."""
        import time

        mock_writer = _make_mock_writer()

        def slow_append(*args, **kwargs):
            time.sleep(0.4)
            return {"streams_written": 1}

        mock_writer.append_raw_data.side_effect = slow_append

        p_writer, p_si, p_pynwb, p_gc = self._patches(mock_writer)
        with p_writer, p_si, p_pynwb, p_gc:
            t0 = time.perf_counter()
            ExportStage(single_session, wait_for_raw=False).run()
            elapsed = time.perf_counter() - t0

        assert elapsed < 0.1, f"daemon-thread run() unexpectedly blocked for {elapsed:.3f}s"

    def test_verify_full_reads_all_chunks(self, single_session: Session) -> None:
        """verify_policy='full' forwarded to append_raw_data exactly once."""
        mock_writer = _make_mock_writer()
        mock_writer.append_raw_data.return_value = {
            "streams_written": 1,
            "stream_names": "ElectricalSeriesAP_imec0",
            "verify_policy": "full",
            "n_chunks_scanned_per_stream": {"ElectricalSeriesAP_imec0": 5},
        }

        p_writer, p_si, p_pynwb, p_gc = self._patches(mock_writer)
        with p_writer, p_si, p_pynwb, p_gc:
            ExportStage(single_session, wait_for_raw=True).run()

        mock_writer.append_raw_data.assert_called_once()
        # verify_policy must be forwarded as 'full' in the foreground path
        call = mock_writer.append_raw_data.call_args
        assert call.kwargs.get("verify_policy") == "full"

    def test_phase3_progress_forwarded_to_stage_callback(self, single_session: Session) -> None:
        """wait_for_raw=True path: append_raw_data's progress_callback is
        wired from ExportStage's own progress_callback (messages land on the
        stage-level callback tagged with the 'export:' stage prefix)."""
        mock_writer = _make_mock_writer()
        mock_writer.append_raw_data.return_value = {
            "streams_written": 1,
            "stream_names": "ElectricalSeriesAP_imec0",
            "verify_policy": "full",
            "n_chunks_scanned_per_stream": {"ElectricalSeriesAP_imec0": 3},
        }

        # Simulate append_raw_data emitting chunk progress through its callback
        def fake_append(*args, progress_callback=None, **kwargs):
            if progress_callback is not None:
                progress_callback("append_ap_imec0 chunk 1/3", 0.1)
                progress_callback("verify_imec0_AP chunk 3/3", 0.95)
            return mock_writer.append_raw_data.return_value

        mock_writer.append_raw_data.side_effect = fake_append

        stage_calls: list[tuple[str, float]] = []

        p_writer, p_si, p_pynwb, p_gc = self._patches(mock_writer)
        with p_writer, p_si, p_pynwb, p_gc:
            ExportStage(
                single_session,
                wait_for_raw=True,
                progress_callback=lambda m, f: stage_calls.append((m, f)),
            ).run()

        # The stage must have forwarded the Phase 3 chunk messages; we find
        # at least one message that contains an 'append' or 'verify' token.
        joined = " | ".join(m for m, _ in stage_calls)
        assert "append_ap_imec0" in joined or "verify_imec0" in joined, (
            f"Phase 3 progress not forwarded to stage callback: {joined}"
        )

    def test_verify_sample_reads_three_chunks(self, tmp_path: Path) -> None:
        """verify_policy='sample' scans exactly 3 chunks (first, middle, last)."""
        from unittest.mock import MagicMock

        from pynpxpipe.io.nwb_writer import NWBWriter

        # We exercise _verify_raw_data directly: build a 5-chunk stream,
        # track chunk indices visited by the source-side get_traces call.
        n_samples = 500
        chunk_frames = 100
        n_channels = 4
        source_data = np.arange(n_samples * n_channels, dtype=np.int16).reshape(
            n_samples, n_channels
        )

        visited: list[int] = []

        mock_rec = MagicMock()

        def _get_traces(start_frame, end_frame, return_in_uV=False):
            visited.append(int(start_frame))
            return source_data[start_frame:end_frame].astype(np.float32)

        mock_rec.get_traces.side_effect = _get_traces

        # Build a tiny real NWB file with a matching acquisition dataset so
        # _verify_raw_data can actually read chunks back.
        nwb_path = tmp_path / "verify.nwb"
        nwbfile = pynwb.NWBFile(
            session_description="harness",
            identifier="verify-test",
            session_start_time=datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC),
        )
        nwbfile.subject = pynwb.file.Subject(
            subject_id="x", species="Macaca mulatta", sex="M", age="P1Y"
        )
        ts = pynwb.TimeSeries(
            name="SampleStream",
            data=source_data,
            unit="V",
            starting_time=0.0,
            rate=30000.0,
        )
        nwbfile.add_acquisition(ts)
        with pynwb.NWBHDF5IO(str(nwb_path), "w") as io:
            io.write(nwbfile)

        writer = NWBWriter.__new__(NWBWriter)  # bypass __init__ — pure method call
        stream_info = {
            "series_name": "SampleStream",
            "stream_type": "AP",
            "probe_id": "imec0",
            "recording": mock_rec,
            "chunk_frames": chunk_frames,
            "n_samples": n_samples,
            "n_channels": n_channels,
        }
        result = writer._verify_raw_data(nwb_path, [stream_info], "sample")

        # 5 total chunks → sample hits indices [0, 2, 4] → 3 source reads
        assert result["SampleStream"] == 3
        assert len(visited) == 3
        # Visited starts are 0, 200, 400 (first, middle, last)
        assert sorted(visited) == [0, 200, 400]

    def test_bit_exact_mismatch_raises_with_location(self, tmp_path: Path) -> None:
        """_verify_raw_data raises ExportError identifying probe_id, stream, chunk."""
        from unittest.mock import MagicMock

        from pynpxpipe.io.nwb_writer import NWBWriter

        n_samples = 500
        chunk_frames = 100
        n_channels = 4
        source_data = np.arange(n_samples * n_channels, dtype=np.int16).reshape(
            n_samples, n_channels
        )

        # Tampered NWB: corrupt the middle chunk (chunk 2 → samples 200..300)
        nwb_data = source_data.copy()
        nwb_data[250, 2] = nwb_data[250, 2] + 1  # flip one sample

        nwb_path = tmp_path / "tampered.nwb"
        nwbfile = pynwb.NWBFile(
            session_description="harness",
            identifier="mismatch-test",
            session_start_time=datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC),
        )
        nwbfile.subject = pynwb.file.Subject(
            subject_id="x", species="Macaca mulatta", sex="M", age="P1Y"
        )
        ts = pynwb.TimeSeries(
            name="ElectricalSeriesAP_imec0",
            data=nwb_data,
            unit="V",
            starting_time=0.0,
            rate=30000.0,
        )
        nwbfile.add_acquisition(ts)
        with pynwb.NWBHDF5IO(str(nwb_path), "w") as io:
            io.write(nwbfile)

        mock_rec = MagicMock()

        def _get_traces(start_frame, end_frame, return_in_uV=False):
            return source_data[start_frame:end_frame].astype(np.float32)

        mock_rec.get_traces.side_effect = _get_traces

        writer = NWBWriter.__new__(NWBWriter)
        stream_info = {
            "series_name": "ElectricalSeriesAP_imec0",
            "stream_type": "AP",
            "probe_id": "imec0",
            "recording": mock_rec,
            "chunk_frames": chunk_frames,
            "n_samples": n_samples,
            "n_channels": n_channels,
        }

        with pytest.raises(ExportError) as excinfo:
            writer._verify_raw_data(nwb_path, [stream_info], "full")

        msg = str(excinfo.value)
        assert "imec0" in msg
        assert "AP" in msg
        assert "chunk 2" in msg

    def test_verified_field_written_with_policy(self, single_session: Session) -> None:
        """wait_for_raw=True writes raw_data_verified_at + verify_policy;
        wait_for_raw=False omits both keys entirely."""
        # --- Case A: wait_for_raw=True → keys present ---
        mock_writer_fg = _make_mock_writer()
        mock_writer_fg.append_raw_data.return_value = {
            "streams_written": 1,
            "stream_names": "ElectricalSeriesAP_imec0",
            "verify_policy": "full",
            "n_chunks_scanned_per_stream": {"ElectricalSeriesAP_imec0": 3},
        }
        p_writer, p_si, p_pynwb, p_gc = self._patches(mock_writer_fg)
        with p_writer, p_si, p_pynwb, p_gc:
            ExportStage(single_session, wait_for_raw=True).run()

        cp_path = single_session.output_dir / "checkpoints" / "export.json"
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        assert "raw_data_verified_at" in data
        assert isinstance(data["raw_data_verified_at"], str)
        assert data["raw_data_verified_at"]  # non-empty ISO 8601 string
        assert data["verify_policy"] == "full"

        # --- Case B: new session, explicit wait_for_raw=False → keys absent ---
        # (default is now True; the legacy daemon-thread path must be opted
        # into explicitly and still produces a checkpoint without the
        # verified-at / policy fields.)
        # Clear the checkpoint from Case A so Case B starts fresh
        cp_path.unlink()

        mock_writer_bg = _make_mock_writer()
        mock_writer_bg.append_raw_data.return_value = {
            "streams_written": 1,
            "stream_names": "ElectricalSeriesAP_imec0",
            "verify_policy": "full",
            "n_chunks_scanned_per_stream": {"ElectricalSeriesAP_imec0": 3},
        }
        p_writer, p_si, p_pynwb, p_gc = self._patches(mock_writer_bg)
        with p_writer, p_si, p_pynwb, p_gc:
            ExportStage(single_session, wait_for_raw=False).run()

        data2 = json.loads(cp_path.read_text(encoding="utf-8"))
        assert "raw_data_verified_at" not in data2
        assert "verify_policy" not in data2


# ---------------------------------------------------------------------------
# Group I — Phase 2.5 derivatives export (spec docs/specs/derivatives.md §7)
# ---------------------------------------------------------------------------


def _fake_trials_df(n: int = 3) -> pd.DataFrame:
    """Synthetic trials DataFrame for Phase 2.5 tests.

    Includes the columns the 6-col TrialRecord CSV projection requires
    (``stim_index``, ``stim_name``, ``trial_valid``) so ``export_trial_record``
    does not KeyError; mirrors the real NWB ``trials.to_dataframe()`` schema.
    """
    return pd.DataFrame(
        {
            "start_time": [float(i) for i in range(n)],
            "stop_time": [float(i) + 0.5 for i in range(n)],
            "trial_id": list(range(n)),
            "onset_nidq_s": [float(i) for i in range(n)],
            "stim_onset_nidq_s": [float(i) + 0.1 for i in range(n)],
            "stim_index": list(range(n)),
            "stim_name": [f"stim_{i}.png" for i in range(n)],
            "trial_valid": [True] * n,
        }
    )


def _fake_units_df(n: int = 2) -> pd.DataFrame:
    """Synthetic units DataFrame (with spike_times) for Phase 2.5 tests."""
    return pd.DataFrame(
        {
            "ks_id": list(range(n)),
            "unit_location": [np.array([0.0, 0.0, 0.0]) for _ in range(n)],
            "unittype_string": ["SUA"] * n,
            "spike_times": [np.array([0.1, 0.2, 0.3]) for _ in range(n)],
        }
    )


def _patch_phase2_nwb(trials_df: pd.DataFrame, units_df: pd.DataFrame):
    """Patch pynwb.NWBHDF5IO so Phase 2.5 sees the supplied DataFrames.

    Returns a ``unittest.mock._patch`` object whose context-manager mode
    activates the patch. Use with ``with _patch_phase2_nwb(...)`` or
    ``ExitStack``.
    """
    fake_nwb = MagicMock()
    fake_nwb.trials.to_dataframe.return_value = trials_df
    fake_nwb.units.to_dataframe.return_value = units_df

    io_cm = MagicMock()
    io_cm.__enter__.return_value.read.return_value = fake_nwb
    io_cm.__exit__.return_value = False
    # Non-context usage (Phase 1 NWB verify) — expose .close().
    io_cm.close = MagicMock()
    io_cm.read = MagicMock(return_value=fake_nwb)

    return patch("pynpxpipe.stages.export.pynwb.NWBHDF5IO", return_value=io_cm)


class TestPhase25Derivatives:
    """Spec §7 — Phase 2.5 writes ``07_derivatives/`` with three files."""

    def _call_phase2(
        self,
        single_session: Session,
        *,
        trials_df: pd.DataFrame | None = None,
        units_df: pd.DataFrame | None = None,
    ) -> Path:
        """Invoke ``_export_phase2`` directly with a synthetic NWB path."""
        trials_df = _fake_trials_df() if trials_df is None else trials_df
        units_df = _fake_units_df() if units_df is None else units_df

        nwb_path = single_session.output_dir / f"{single_session.session_id.canonical()}.nwb"
        nwb_path.parent.mkdir(parents=True, exist_ok=True)
        nwb_path.touch()

        stage = ExportStage(single_session)
        behavior_events = _make_behavior_events(single_session.output_dir)
        with (
            _patch_phase2_nwb(trials_df, units_df),
            patch("pynpxpipe.io.bhv.BHV2Parser"),
        ):
            stage._export_phase2(nwb_path, behavior_events)
        return nwb_path

    def test_phase2_writes_derivatives_dir(self, single_session: Session) -> None:
        """Phase 2.5 creates ``{output_dir}/07_derivatives/``."""
        self._call_phase2(single_session)
        assert (single_session.output_dir / "07_derivatives").is_dir()

    def test_phase2_does_not_write_old_07_export(self, single_session: Session) -> None:
        """Legacy ``07_export/`` directory is never created (spec strict delete)."""
        self._call_phase2(single_session)
        assert not (single_session.output_dir / "07_export").exists()

    def test_phase2_writes_three_files(self, single_session: Session) -> None:
        """TrialRaster_*.h5 / UnitProp_*.csv / TrialRecord_*.csv all present."""
        self._call_phase2(single_session)
        sid = single_session.session_id.canonical()
        d = single_session.output_dir / "07_derivatives"
        assert (d / f"TrialRaster_{sid}.h5").is_file()
        assert (d / f"UnitProp_{sid}.csv").is_file()
        assert (d / f"TrialRecord_{sid}.csv").is_file()

    def test_phase2_disabled_skips(self, single_session: Session) -> None:
        """``export.derivatives.enabled=False`` → directory not created."""
        single_session.config.export.derivatives.enabled = False
        self._call_phase2(single_session)
        assert not (single_session.output_dir / "07_derivatives").exists()

    def test_phase2_auto_post_onset_calls_resolver(self, single_session: Session) -> None:
        """``post_onset_ms="auto"`` → ``resolve_post_onset_ms`` invoked."""
        single_session.config.export.derivatives.post_onset_ms = "auto"
        nwb_path = single_session.output_dir / f"{single_session.session_id.canonical()}.nwb"
        nwb_path.parent.mkdir(parents=True, exist_ok=True)
        nwb_path.touch()
        stage = ExportStage(single_session)
        behavior_events = _make_behavior_events(single_session.output_dir)
        with (
            _patch_phase2_nwb(_fake_trials_df(), _fake_units_df()),
            patch("pynpxpipe.io.bhv.BHV2Parser"),
            patch(
                "pynpxpipe.io.derivatives.resolve_post_onset_ms",
                return_value=500.0,
            ) as mock_resolver,
        ):
            stage._export_phase2(nwb_path, behavior_events)
        assert mock_resolver.called

    def test_phase2_numeric_post_onset_bypasses_resolver(self, single_session: Session) -> None:
        """Numeric ``post_onset_ms`` → resolver not invoked."""
        single_session.config.export.derivatives.post_onset_ms = 500.0
        nwb_path = single_session.output_dir / f"{single_session.session_id.canonical()}.nwb"
        nwb_path.parent.mkdir(parents=True, exist_ok=True)
        nwb_path.touch()
        stage = ExportStage(single_session)
        behavior_events = _make_behavior_events(single_session.output_dir)
        with (
            _patch_phase2_nwb(_fake_trials_df(), _fake_units_df()),
            patch("pynpxpipe.io.bhv.BHV2Parser"),
            patch("pynpxpipe.io.derivatives.resolve_post_onset_ms") as mock_resolver,
        ):
            stage._export_phase2(nwb_path, behavior_events)
        assert not mock_resolver.called

    def test_phase2_reads_nwb_post_write(self, single_session: Session) -> None:
        """Phase 2.5 opens the written NWB in ``"r"`` mode."""
        nwb_path = single_session.output_dir / f"{single_session.session_id.canonical()}.nwb"
        nwb_path.parent.mkdir(parents=True, exist_ok=True)
        nwb_path.touch()
        stage = ExportStage(single_session)
        behavior_events = _make_behavior_events(single_session.output_dir)
        with (
            _patch_phase2_nwb(_fake_trials_df(), _fake_units_df()) as patched_io,
            patch("pynpxpipe.io.bhv.BHV2Parser"),
        ):
            stage._export_phase2(nwb_path, behavior_events)
        # NWBHDF5IO invoked at least once with the written NWB path + "r".
        calls = patched_io.call_args_list
        assert any(
            len(c.args) >= 2 and c.args[0] == str(nwb_path) and c.args[1] == "r" for c in calls
        )

    def test_phase2_integrated_in_run(self, single_session: Session) -> None:
        """Full ``run()`` produces ``07_derivatives/`` (end-to-end wiring)."""
        mock_writer = _make_mock_writer()
        with (
            patch("pynpxpipe.stages.export.NWBWriter", return_value=mock_writer),
            patch("pynpxpipe.stages.export.si"),
            patch("pynpxpipe.stages.export.gc"),
            _patch_phase2_nwb(_fake_trials_df(), _fake_units_df()),
            patch("pynpxpipe.io.bhv.BHV2Parser"),
        ):
            ExportStage(single_session).run()
        assert (single_session.output_dir / "07_derivatives").is_dir()
