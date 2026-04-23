"""Tests for stages/preprocess.py — PreprocessStage.

Groups:
  A. Normal flow         — all probes processed, checkpoints written, SI calls correct
  B. Checkpoint skip     — per-probe and stage-level skip logic
  C. Error handling      — Zarr save failure raises PreprocessError, failed checkpoint written
  D. Config params       — freq_min/freq_max and n_jobs passed from config
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pynpxpipe.core.config import (
    BandpassConfig,
    MotionCorrectionConfig,
    PipelineConfig,
    PreprocessConfig,
    ResourcesConfig,
)
from pynpxpipe.core.errors import PreprocessError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.stages.preprocess import PreprocessStage

# ---------------------------------------------------------------------------
# Helpers / fixtures
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


def _make_config(
    freq_min: float = 300.0,
    freq_max: float = 6000.0,
    motion_method: str | None = None,
    n_jobs: int = 4,
    chunk_duration: str = "1s",
) -> PipelineConfig:
    """Build a PipelineConfig with explicit preprocess and resource params."""
    return PipelineConfig(
        resources=ResourcesConfig(n_jobs=n_jobs, chunk_duration=chunk_duration),
        preprocess=PreprocessConfig(
            bandpass=BandpassConfig(freq_min=freq_min, freq_max=freq_max),
            motion_correction=MotionCorrectionConfig(method=motion_method),
        ),
    )


def _make_mock_recording() -> MagicMock:
    rec = MagicMock()
    rec.remove_channels.return_value = rec
    return rec


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Session with two probes (imec0, imec1)."""
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
    s.probes = [
        _make_probe("imec0", tmp_path),
        _make_probe("imec1", tmp_path),
    ]
    return s


@pytest.fixture
def single_session(tmp_path: Path) -> Session:
    """Session with one probe (imec0)."""
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
    return s


def _write_completed_checkpoint(session: Session, stage: str, probe_id: str | None = None) -> None:
    """Write a completed checkpoint file directly (no CheckpointManager)."""
    filename = f"{stage}.json" if probe_id is None else f"{stage}_{probe_id}.json"
    cp_path = session.output_dir / "checkpoints" / filename
    cp_path.write_text(
        json.dumps({"stage": stage, "status": "completed"}),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Group A — Normal flow
# ---------------------------------------------------------------------------


class TestNormalFlow:
    def test_run_processes_all_probes(self, session: Session) -> None:
        """Both probes are preprocessed when no checkpoints exist."""
        mock_rec = _make_mock_recording()
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(session, config).run()

        # load_ap called once per probe
        assert mock_rec.save.call_count == 2  # once for imec0, once for imec1

    def test_run_writes_stage_checkpoint(self, session: Session) -> None:
        """Stage-level checkpoint exists with status=completed after run."""
        mock_rec = _make_mock_recording()
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(session, config).run()

        cp = session.output_dir / "checkpoints" / "preprocess.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "completed"

    def test_probe_checkpoint_written_per_probe(self, session: Session) -> None:
        """Per-probe checkpoint files exist for both imec0 and imec1."""
        mock_rec = _make_mock_recording()
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(session, config).run()

        cp0 = session.output_dir / "checkpoints" / "preprocess_imec0.json"
        cp1 = session.output_dir / "checkpoints" / "preprocess_imec1.json"
        assert cp0.exists()
        assert cp1.exists()

    def test_zarr_saved_to_correct_path(self, single_session: Session) -> None:
        """Zarr is saved to {output_dir}/01_preprocessed/imec0."""
        mock_rec = _make_mock_recording()
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(single_session, config).run()

        folder = mock_rec.save.call_args.kwargs.get("folder") or mock_rec.save.call_args[1].get(
            "folder"
        )
        assert folder is not None
        assert "01_preprocessed" in str(folder)
        assert "imec0" in str(folder)

    def test_bad_channels_removed(self, single_session: Session) -> None:
        """remove_channels is called when detect_bad_channels returns bad channels."""
        mock_rec = _make_mock_recording()
        config = _make_config()
        bad_ids = ["CH1", "CH2"]

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = (bad_ids, ["noise", "noise"])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(single_session, config).run()

        mock_rec.remove_channels.assert_called_once_with(bad_ids)

    def test_no_bad_channels_skips_removal(self, single_session: Session) -> None:
        """remove_channels is NOT called when detect_bad_channels returns empty list."""
        mock_rec = _make_mock_recording()
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(single_session, config).run()

        mock_rec.remove_channels.assert_not_called()

    def test_phase_shift_called(self, single_session: Session) -> None:
        """si.phase_shift is called once per probe."""
        mock_rec = _make_mock_recording()
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(single_session, config).run()

        mock_spp.phase_shift.assert_called_once()

    def test_phase_shift_before_bandpass(self, single_session: Session) -> None:
        """si.phase_shift is called before si.bandpass_filter."""
        mock_rec = _make_mock_recording()
        config = _make_config()
        call_order: list[str] = []

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.side_effect = lambda r: call_order.append("phase_shift") or r
            mock_spp.bandpass_filter.side_effect = lambda r, **kw: (
                call_order.append("bandpass") or r
            )
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(single_session, config).run()

        assert "phase_shift" in call_order
        assert "bandpass" in call_order
        assert call_order.index("phase_shift") < call_order.index("bandpass")

    def test_motion_correction_called_when_configured(self, single_session: Session) -> None:
        """si.correct_motion is called when motion_method='dredge'."""
        mock_rec = _make_mock_recording()
        config = _make_config(motion_method="dredge")

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec
            mock_spp.correct_motion.return_value = mock_rec

            PreprocessStage(single_session, config).run()

        mock_spp.correct_motion.assert_called_once()

    def test_motion_correction_skipped_when_none(self, single_session: Session) -> None:
        """si.correct_motion is NOT called when motion_method=None."""
        mock_rec = _make_mock_recording()
        config = _make_config(motion_method=None)

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(single_session, config).run()

        mock_spp.correct_motion.assert_not_called()

    def test_gc_collect_called_after_probe(self, session: Session) -> None:
        """gc.collect() is called once per probe processed."""
        mock_rec = _make_mock_recording()
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc") as mock_gc,
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(session, config).run()

        # 2 probes → gc.collect called at least 2 times
        assert mock_gc.collect.call_count >= 2


# ---------------------------------------------------------------------------
# Group B — Checkpoint skip
# ---------------------------------------------------------------------------


class TestCheckpointSkip:
    def test_skips_already_preprocessed_probe(self, session: Session) -> None:
        """load_ap is NOT called for imec0 when its per-probe checkpoint is complete."""
        _write_completed_checkpoint(session, "preprocess", "imec0")
        config = _make_config()
        mock_rec = _make_mock_recording()

        with (
            patch(
                "pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec
            ) as mock_load,
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(session, config).run()

        # Only imec1 should have been loaded
        assert mock_load.call_count == 1
        loaded_probe_id = mock_load.call_args[0][0].probe_id
        assert loaded_probe_id == "imec1"

    def test_processes_remaining_probe_after_skip(self, session: Session) -> None:
        """imec1 is processed when imec0 already has a completed checkpoint."""
        _write_completed_checkpoint(session, "preprocess", "imec0")
        config = _make_config()
        mock_rec = _make_mock_recording()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(session, config).run()

        # imec1 checkpoint written
        cp1 = session.output_dir / "checkpoints" / "preprocess_imec1.json"
        assert cp1.exists()

    def test_stage_skips_if_all_probes_complete(self, session: Session) -> None:
        """Entire run() returns immediately when stage-level checkpoint is complete."""
        _write_completed_checkpoint(session, "preprocess")
        config = _make_config()

        with patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap") as mock_load:
            PreprocessStage(session, config).run()

        mock_load.assert_not_called()


# ---------------------------------------------------------------------------
# Group C — Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_zarr_save_failure_raises_preprocess_error(self, single_session: Session) -> None:
        """IOError from recording.save is wrapped and raised as PreprocessError."""
        mock_rec = _make_mock_recording()
        mock_rec.save.side_effect = OSError("disk full")
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            with pytest.raises(PreprocessError, match="imec0"):
                PreprocessStage(single_session, config).run()

    def test_failed_probe_checkpoint_written(self, single_session: Session) -> None:
        """A failed per-probe checkpoint is written when save raises."""
        mock_rec = _make_mock_recording()
        mock_rec.save.side_effect = OSError("disk full")
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            with pytest.raises(PreprocessError):
                PreprocessStage(single_session, config).run()

        cp = single_session.output_dir / "checkpoints" / "preprocess_imec0.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "failed"

    def test_preprocess_error_propagates(self, session: Session) -> None:
        """PreprocessError from the first probe re-raises out of run()."""
        mock_rec = _make_mock_recording()
        mock_rec.save.side_effect = OSError("disk full")
        config = _make_config()

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            with pytest.raises(PreprocessError):
                PreprocessStage(session, config).run()


# ---------------------------------------------------------------------------
# Group D — Config params
# ---------------------------------------------------------------------------


class TestConfigParams:
    def test_bandpass_freq_from_config(self, single_session: Session) -> None:
        """si.bandpass_filter is called with freq_min and freq_max from config."""
        mock_rec = _make_mock_recording()
        config = _make_config(freq_min=500.0, freq_max=5000.0)

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(single_session, config).run()

        call_kwargs = mock_spp.bandpass_filter.call_args.kwargs
        assert call_kwargs.get("freq_min") == 500.0
        assert call_kwargs.get("freq_max") == 5000.0

    def test_n_jobs_passed_to_save(self, single_session: Session) -> None:
        """n_jobs from config.resources is set via si.set_global_job_kwargs.

        SpikeInterface uses global job kwargs so recording.save() inherits
        n_jobs automatically — we verify the global setter was called correctly.
        """
        mock_rec = _make_mock_recording()
        config = _make_config(n_jobs=8)

        with (
            patch("pynpxpipe.stages.preprocess.SpikeGLXLoader.load_ap", return_value=mock_rec),
            patch("pynpxpipe.stages.preprocess.spp") as mock_spp,
            patch("pynpxpipe.stages.preprocess.gc"),
            patch("pynpxpipe.stages.base.si") as mock_si,
        ):
            mock_spp.phase_shift.return_value = mock_rec
            mock_spp.bandpass_filter.return_value = mock_rec
            mock_spp.detect_bad_channels.return_value = ([], [])
            mock_spp.common_reference.return_value = mock_rec

            PreprocessStage(single_session, config).run()

        # n_jobs is set globally via si.set_global_job_kwargs, not per-call
        mock_si.set_global_job_kwargs.assert_called_once()
        global_kwargs = mock_si.set_global_job_kwargs.call_args
        assert global_kwargs.kwargs.get("n_jobs") == 8
