"""Tests for stages/synchronize.py — SynchronizeStage.

All IO-layer dependencies are mocked; no real files or recordings needed.

Groups:
  A. Normal flow (run)          — JSON / Parquet outputs, checkpoint, plots
  B. _decode_nidq_events        — bit extraction, code packing, timing
  C. _align_probe_to_nidq       — calls align_imec_to_nidq with correct args
  D. Checkpoint skip            — completed checkpoint → immediate return
  E. Error handling             — SyncError propagation + failed checkpoint
  F. Parquet content            — column values for trial_valid, dataset_name, quality_flag
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from pynpxpipe.core.config import PipelineConfig, SyncConfig
from pynpxpipe.core.errors import SyncError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.io.sync.bhv_nidq_align import TrialAlignment
from pynpxpipe.io.sync.imec_nidq_align import SyncResult
from pynpxpipe.io.sync.photodiode_calibrate import CalibratedOnsets
from pynpxpipe.stages.synchronize import SynchronizeStage

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

N_TRIALS = 3
NIDQ_SR = 25_000.0
PROBE_SR = 30_000.0


def _make_subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="M01",
        description="test monkey",
        species="Macaca mulatta",
        sex="M",
        age="P5Y",
        weight="10kg",
    )


def _make_probe(probe_id: str, base: Path) -> ProbeInfo:
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=base / f"{probe_id}.ap.bin",
        ap_meta=base / f"{probe_id}.ap.meta",
        lf_bin=None,
        lf_meta=None,
        sample_rate=PROBE_SR,
        n_channels=385,
        probe_type="NP1010",
        serial_number="12345",
    )


def _make_sync_result(probe_id: str, a: float = 1.0, b: float = 0.0) -> SyncResult:
    return SyncResult(probe_id=probe_id, a=a, b=b, residual_ms=0.05, n_repaired=0)


def _make_trial_alignment(n: int = N_TRIALS, dataset_name: str = "exp_20260101") -> TrialAlignment:
    df = pd.DataFrame(
        {
            "trial_id": list(range(1, n + 1)),
            "onset_nidq_s": [float(i) for i in range(1, n + 1)],
            "stim_onset_nidq_s": [float(i) + 0.1 for i in range(1, n + 1)],
            "condition_id": [1] * n,
            "trial_valid": [float("nan")] * n,
        }
    )
    return TrialAlignment(
        trial_events_df=df,
        dataset_name=dataset_name,
        bhv_metadata={"DatasetName": dataset_name, "TotalTrials": n},
        detected_trial_start_bit=1,
    )


def _make_calibrated(n: int = N_TRIALS) -> CalibratedOnsets:
    return CalibratedOnsets(
        stim_onset_nidq_s=np.array([float(i) + 0.12 for i in range(1, n + 1)]),
        onset_latency_ms=np.array([20.0] * n),
        quality_flags=np.array([0] * n),
        n_suspicious=0,
    )


def _nidq_traces(n_samples: int = 5000, n_channels: int = 2) -> np.ndarray:
    """Return a 2D int16 array for mocking get_traces(); includes photodiode signal."""
    data = np.zeros((n_samples, n_channels), dtype=np.int16)
    # Add variance in channel 0 so photodiode check passes
    data[n_samples // 2 :, 0] = 1000
    return data


class _MockRecording:
    """Minimal SpikeInterface-like recording for _decode_nidq_events tests."""

    def __init__(self, data: np.ndarray) -> None:
        self._data = data

    def get_traces(self, **_kwargs: Any) -> np.ndarray:  # noqa: ANN401
        return self._data


@contextmanager
def _patch_run(session: Session, n_probes: int = 2):  # type: ignore[return]
    """Context manager: patch all IO deps for a successful SynchronizeStage.run()."""
    sr_0 = _make_sync_result("imec0")
    sr_1 = _make_sync_result("imec1")
    trial_aln = _make_trial_alignment()
    calibrated = _make_calibrated()
    nidq_traces = _nidq_traces()
    sync_edge_times = np.linspace(0, 100, 101).tolist()

    mock_nidq_rec = MagicMock()
    mock_nidq_rec.get_traces.return_value = nidq_traces
    mock_ap_rec = MagicMock()

    disc_inst = MagicMock()
    disc_inst.discover_nidq.return_value = (Path("nidq.bin"), Path("nidq.meta"))
    disc_inst.parse_meta.return_value = {"niSampRate": str(NIDQ_SR), "niAiRangeMax": "5.0"}

    with (
        patch("pynpxpipe.stages.synchronize.SpikeGLXDiscovery") as mock_disc_cls,
        patch("pynpxpipe.stages.synchronize.SpikeGLXLoader") as mock_loader_cls,
        patch("pynpxpipe.stages.synchronize.align_imec_to_nidq") as mock_align_imec,
        patch("pynpxpipe.stages.synchronize.align_bhv2_to_nidq") as mock_align_bhv,
        patch("pynpxpipe.stages.synchronize.calibrate_photodiode") as mock_pd,
        patch("pynpxpipe.stages.synchronize.BHV2Parser"),
        patch("pynpxpipe.stages.synchronize.generate_all_plots") as mock_plots,
    ):
        mock_disc_cls.return_value = disc_inst
        mock_loader_cls.load_nidq.return_value = mock_nidq_rec
        mock_loader_cls.load_ap.return_value = mock_ap_rec
        mock_loader_cls.extract_sync_edges.return_value = sync_edge_times
        mock_align_imec.side_effect = [sr_0, sr_1][:n_probes]
        mock_align_bhv.return_value = trial_aln
        mock_pd.return_value = calibrated

        yield {
            "mock_disc_cls": mock_disc_cls,
            "mock_loader_cls": mock_loader_cls,
            "mock_align_imec": mock_align_imec,
            "mock_align_bhv": mock_align_bhv,
            "mock_pd": mock_pd,
            "mock_plots": mock_plots,
            "trial_aln": trial_aln,
            "calibrated": calibrated,
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sync_config() -> SyncConfig:
    return SyncConfig(
        sync_bit=0,
        event_bits=[0, 1, 2],
        max_time_error_ms=17.0,
        trial_count_tolerance=2,
        photodiode_channel_index=0,
        monitor_delay_ms=0.0,
        stim_onset_code=64,
        generate_plots=False,
        gap_threshold_ms=1200.0,
        trial_start_bit=None,
        pd_window_pre_ms=10.0,
        pd_window_post_ms=100.0,
        pd_min_signal_variance=1e-6,
    )


@pytest.fixture
def session(tmp_path: Path, sync_config: SyncConfig) -> Session:
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 50)
    config = PipelineConfig()
    config.sync = sync_config
    sess = SessionManager.create(session_dir, bhv_file, _make_subject(), tmp_path / "output")
    sess.config = config
    sess.probes = [_make_probe("imec0", tmp_path), _make_probe("imec1", tmp_path)]
    return sess


@pytest.fixture
def stage(session: Session) -> SynchronizeStage:
    return SynchronizeStage(session)


# ---------------------------------------------------------------------------
# Group A — Normal flow
# ---------------------------------------------------------------------------


class TestNormalFlow:
    def test_run_writes_sync_tables_json(self, stage: SynchronizeStage, session: Session) -> None:
        with _patch_run(session):
            stage.run()

        sync_json = session.output_dir / "sync" / "sync_tables.json"
        assert sync_json.exists()
        data = json.loads(sync_json.read_text(encoding="utf-8"))
        assert "probes" in data
        assert "imec0" in data["probes"]
        assert "imec1" in data["probes"]
        assert "a" in data["probes"]["imec0"]
        assert "b" in data["probes"]["imec0"]
        assert "residual_ms" in data["probes"]["imec0"]

    def test_run_writes_behavior_events_parquet(
        self, stage: SynchronizeStage, session: Session
    ) -> None:
        with _patch_run(session):
            stage.run()

        parquet = session.output_dir / "sync" / "behavior_events.parquet"
        assert parquet.exists()
        df = pd.read_parquet(parquet)
        assert len(df) == N_TRIALS

    def test_behavior_events_columns(self, stage: SynchronizeStage, session: Session) -> None:
        with _patch_run(session):
            stage.run()

        df = pd.read_parquet(session.output_dir / "sync" / "behavior_events.parquet")
        required = {
            "trial_id",
            "onset_nidq_s",
            "stim_onset_nidq_s",
            "stim_onset_imec_s",
            "condition_id",
            "trial_valid",
            "onset_latency_ms",
            "quality_flag",
            "dataset_name",
        }
        assert required.issubset(set(df.columns))

    def test_stim_onset_imec_s_computed_per_probe(
        self, stage: SynchronizeStage, session: Session
    ) -> None:
        """With a=1.0, b=0.0: t_imec == t_nidq for both probes."""
        with _patch_run(session):
            stage.run()

        df = pd.read_parquet(session.output_dir / "sync" / "behavior_events.parquet")
        for raw_val, nidq_val in zip(df["stim_onset_imec_s"], df["stim_onset_nidq_s"], strict=True):
            per_probe = json.loads(raw_val)
            assert "imec0" in per_probe
            assert "imec1" in per_probe
            assert abs(per_probe["imec0"] - nidq_val) < 1e-6
            assert abs(per_probe["imec1"] - nidq_val) < 1e-6

    def test_run_writes_checkpoint(self, stage: SynchronizeStage, session: Session) -> None:
        with _patch_run(session):
            stage.run()

        cp = session.output_dir / "checkpoints" / "synchronize.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "completed"
        assert "n_trials" in data
        assert "probe_ids" in data

    def test_generate_plots_called_when_configured(
        self, session: Session, sync_config: SyncConfig
    ) -> None:
        sync_config.generate_plots = True
        stage = SynchronizeStage(session)
        with _patch_run(session) as ctx:
            stage.run()
        ctx["mock_plots"].assert_called_once()

    def test_generate_plots_skipped_when_disabled(
        self, stage: SynchronizeStage, session: Session, sync_config: SyncConfig
    ) -> None:
        assert not sync_config.generate_plots
        with _patch_run(session) as ctx:
            stage.run()
        ctx["mock_plots"].assert_not_called()


# ---------------------------------------------------------------------------
# Group B — _decode_nidq_events
# ---------------------------------------------------------------------------


class TestDecodeNidqEvents:
    def test_decode_single_bit_events(self, stage: SynchronizeStage) -> None:
        """event_bits=[1] with 3 transitions → 3 events."""
        n = 100
        data = np.zeros(n, dtype=np.uint16)
        data[20:40] = 2  # bit 1 set
        data[60:100] = 2  # bit 1 set again (no trailing 0)
        mock_rec = _MockRecording(data.reshape(-1, 1))
        times, codes = stage._decode_nidq_events(mock_rec, event_bits=[1], sample_rate=1000.0)
        assert len(times) == 3
        assert int(codes[0]) == 1  # bit 1 set → code 1 in remapped pos 0
        assert int(codes[1]) == 0
        assert int(codes[2]) == 1

    def test_decode_multi_bit_events(self, stage: SynchronizeStage) -> None:
        """event_bits=[0,1,2]: combined codes 1-7 encoded correctly."""
        data = np.array([0, 1, 2, 3, 4, 5, 6, 7, 0], dtype=np.uint16)
        mock_rec = _MockRecording(data.reshape(-1, 1))
        times, codes = stage._decode_nidq_events(mock_rec, event_bits=[0, 1, 2], sample_rate=1000.0)
        # 8 transitions (values change at each sample)
        assert len(codes) == 8
        assert set(codes[:7].tolist()) == {1, 2, 3, 4, 5, 6, 7}
        assert int(codes[7]) == 0

    def test_decode_times_from_sample_rate(self, stage: SynchronizeStage) -> None:
        """Transition at sample 30000 with SR=30000 → event_time ≈ 1.0s."""
        n = 60_001
        data = np.zeros(n, dtype=np.uint16)
        data[30_000:] = 1  # bit 0 set from sample 30000
        mock_rec = _MockRecording(data.reshape(-1, 1))
        times, codes = stage._decode_nidq_events(mock_rec, event_bits=[0], sample_rate=30_000.0)
        assert len(times) == 1
        assert abs(times[0] - 1.0) < 1e-6

    def test_decode_returns_numpy_arrays(self, stage: SynchronizeStage) -> None:
        data = np.array([0, 1, 0], dtype=np.uint16)
        mock_rec = _MockRecording(data.reshape(-1, 1))
        times, codes = stage._decode_nidq_events(mock_rec, event_bits=[0], sample_rate=1000.0)
        assert isinstance(times, np.ndarray)
        assert isinstance(codes, np.ndarray)


# ---------------------------------------------------------------------------
# Group C — _align_probe_to_nidq
# ---------------------------------------------------------------------------


class TestAlignProbeToNidq:
    def test_align_probe_calls_align_imec_to_nidq(self, stage: SynchronizeStage) -> None:
        nidq_times = np.linspace(0, 100, 101)
        sr_mock = _make_sync_result("imec0")
        with (
            patch("pynpxpipe.stages.synchronize.SpikeGLXLoader") as mock_loader,
            patch("pynpxpipe.stages.synchronize.align_imec_to_nidq") as mock_align,
        ):
            mock_loader.load_ap.return_value = MagicMock()
            mock_loader.extract_sync_edges.return_value = np.linspace(0, 100, 101).tolist()
            mock_align.return_value = sr_mock
            stage._align_probe_to_nidq("imec0", nidq_times)

        mock_align.assert_called_once()
        call_args = mock_align.call_args
        assert call_args[0][0] == "imec0"  # probe_id positional arg

    def test_align_probe_returns_sync_result(self, stage: SynchronizeStage) -> None:
        nidq_times = np.linspace(0, 100, 101)
        sr_expected = _make_sync_result("imec0", a=1.000001, b=0.002)
        with (
            patch("pynpxpipe.stages.synchronize.SpikeGLXLoader") as mock_loader,
            patch("pynpxpipe.stages.synchronize.align_imec_to_nidq") as mock_align,
        ):
            mock_loader.load_ap.return_value = MagicMock()
            mock_loader.extract_sync_edges.return_value = np.linspace(0, 100, 101).tolist()
            mock_align.return_value = sr_expected
            ap_times, sync_result = stage._align_probe_to_nidq("imec0", nidq_times)

        assert isinstance(ap_times, np.ndarray)
        assert sync_result is sr_expected


# ---------------------------------------------------------------------------
# Group D — Checkpoint skip
# ---------------------------------------------------------------------------


class TestCheckpointSkip:
    def test_skips_if_checkpoint_complete(self, stage: SynchronizeStage, session: Session) -> None:
        """Already-complete checkpoint → run() returns immediately without IO."""
        # Write a completed checkpoint
        cp_dir = session.output_dir / "checkpoints"
        cp_dir.mkdir(parents=True, exist_ok=True)
        (cp_dir / "synchronize.json").write_text(
            json.dumps({"status": "completed", "n_trials": 3}), encoding="utf-8"
        )

        with _patch_run(session) as ctx:
            stage.run()

        # No IO should have been called
        ctx["mock_loader_cls"].load_nidq.assert_not_called()
        ctx["mock_align_imec"].assert_not_called()


# ---------------------------------------------------------------------------
# Group E — Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_sync_error_propagates(self, stage: SynchronizeStage, session: Session) -> None:
        with _patch_run(session) as ctx:
            ctx["mock_align_imec"].side_effect = SyncError("alignment failed")
            with pytest.raises(SyncError, match="alignment failed"):
                stage.run()

    def test_failed_checkpoint_written_on_error(
        self, stage: SynchronizeStage, session: Session
    ) -> None:
        with _patch_run(session) as ctx:
            ctx["mock_align_imec"].side_effect = SyncError("probe sync failed")
            with pytest.raises(SyncError):
                stage.run()

        cp = session.output_dir / "checkpoints" / "synchronize.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "failed"

    def test_photodiode_dead_signal_raises(self, stage: SynchronizeStage, session: Session) -> None:
        with _patch_run(session) as ctx:
            ctx["mock_pd"].side_effect = SyncError("Photodiode signal variance too low")
            with pytest.raises(SyncError, match="Photodiode"):
                stage.run()


# ---------------------------------------------------------------------------
# Group F — Parquet content
# ---------------------------------------------------------------------------


class TestParquetContent:
    def test_trial_valid_column_is_nan(self, stage: SynchronizeStage, session: Session) -> None:
        with _patch_run(session):
            stage.run()

        df = pd.read_parquet(session.output_dir / "sync" / "behavior_events.parquet")
        assert df["trial_valid"].isna().all()

    def test_dataset_name_in_every_row(self, stage: SynchronizeStage, session: Session) -> None:
        with _patch_run(session):
            stage.run()

        df = pd.read_parquet(session.output_dir / "sync" / "behavior_events.parquet")
        assert (df["dataset_name"] == "exp_20260101").all()

    def test_quality_flag_from_calibration(self, stage: SynchronizeStage, session: Session) -> None:
        with _patch_run(session) as ctx:
            # Quality flags: first trial suspicious
            ctx["calibrated"] = CalibratedOnsets(
                stim_onset_nidq_s=np.array([1.12, 2.12, 3.12]),
                onset_latency_ms=np.array([np.nan, 20.0, 20.0]),
                quality_flags=np.array([2, 0, 0]),
                n_suspicious=1,
            )
            ctx["mock_pd"].return_value = ctx["calibrated"]
            stage.run()

        df = pd.read_parquet(session.output_dir / "sync" / "behavior_events.parquet")
        assert int(df["quality_flag"].iloc[0]) == 2
        assert int(df["quality_flag"].iloc[1]) == 0
