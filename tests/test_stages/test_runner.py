"""Tests for pipelines/runner.py — PipelineRunner.

Groups:
  A. Basic execution — stage ordering, subset execution, run_stage
  B. Auto config    — ResourceDetector triggered when any value is "auto"
  C. Fail-fast      — StageError / RuntimeError from a stage propagates
  D. get_status     — pending / completed / partial / failed
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pynpxpipe.core.config import (
    ParallelConfig,
    PipelineConfig,
    ResourcesConfig,
    SorterConfig,
    SorterParams,
    SortingConfig,
)
from pynpxpipe.core.errors import SortError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.pipelines.runner import STAGE_ORDER, PipelineRunner

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


def _make_pipeline_config(n_jobs="auto", chunk_duration="auto", max_workers="auto"):
    return PipelineConfig(
        resources=ResourcesConfig(n_jobs=n_jobs, chunk_duration=chunk_duration),
        parallel=ParallelConfig(max_workers=max_workers),
    )


def _make_sorting_config(batch_size="auto"):
    return SortingConfig(
        sorter=SorterConfig(params=SorterParams(batch_size=batch_size)),
    )


@pytest.fixture
def session(tmp_path: Path) -> Session:
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
    s.probes = [_make_probe("imec0", tmp_path), _make_probe("imec1", tmp_path)]
    return s


def _make_runner(session: Session, n_jobs=1, chunk_duration="1s", max_workers=1, batch_size=65792):
    return PipelineRunner(
        session,
        _make_pipeline_config(
            n_jobs=n_jobs, chunk_duration=chunk_duration, max_workers=max_workers
        ),
        _make_sorting_config(batch_size=batch_size),
    )


def _write_checkpoint(
    session: Session, stage: str, status: str = "completed", probe_id: str | None = None
) -> None:
    filename = f"{stage}.json" if probe_id is None else f"{stage}_{probe_id}.json"
    cp_dir = session.output_dir / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    (cp_dir / filename).write_text(json.dumps({"stage": stage, "status": status}), encoding="utf-8")


# ---------------------------------------------------------------------------
# Patch helper — mocks all 7 stage classes
# ---------------------------------------------------------------------------

_ALL_STAGES = [
    "pynpxpipe.pipelines.runner.DiscoverStage",
    "pynpxpipe.pipelines.runner.PreprocessStage",
    "pynpxpipe.pipelines.runner.SortStage",
    "pynpxpipe.pipelines.runner.SynchronizeStage",
    "pynpxpipe.pipelines.runner.CurateStage",
    "pynpxpipe.pipelines.runner.PostprocessStage",
    "pynpxpipe.pipelines.runner.ExportStage",
]


# ---------------------------------------------------------------------------
# Group A — Basic execution
# ---------------------------------------------------------------------------


class TestBasicExecution:
    def test_run_executes_all_stages_in_order(self, session: Session) -> None:
        """stages=None runs all 7 stages in STAGE_ORDER."""
        runner = _make_runner(session)
        call_order: list[str] = []

        mocks = {}
        patches = []
        for name in _ALL_STAGES:
            stage_name = name.split(".")[-1].replace("Stage", "").lower()
            m = MagicMock()
            m.return_value.run.side_effect = lambda sn=stage_name: call_order.append(sn)
            mocks[stage_name] = m
            patches.append(patch(name, m))

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            runner.run()

        assert call_order == STAGE_ORDER

    def test_run_subset_of_stages(self, session: Session) -> None:
        """stages=["sort","curate"] runs only those 2 stages."""
        runner = _make_runner(session)
        called: list[str] = []

        mocks = {}
        patches = []
        for name in _ALL_STAGES:
            stage_name = name.split(".")[-1].replace("Stage", "").lower()
            m = MagicMock()
            m.return_value.run.side_effect = lambda sn=stage_name: called.append(sn)
            mocks[stage_name] = m
            patches.append(patch(name, m))

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            runner.run(stages=["sort", "curate"])

        assert set(called) == {"sort", "curate"}
        assert len(called) == 2

    def test_run_subset_maintains_order(self, session: Session) -> None:
        """stages=["export","discover"] run in discover→export order."""
        runner = _make_runner(session)
        called: list[str] = []

        mocks = {}
        patches = []
        for name in _ALL_STAGES:
            stage_name = name.split(".")[-1].replace("Stage", "").lower()
            m = MagicMock()
            m.return_value.run.side_effect = lambda sn=stage_name: called.append(sn)
            mocks[stage_name] = m
            patches.append(patch(name, m))

        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            runner.run(stages=["export", "discover"])

        assert called == ["discover", "export"]

    def test_run_stage_by_name(self, session: Session) -> None:
        """run_stage('sort') instantiates SortStage and calls run()."""
        runner = _make_runner(session)
        mock_sort = MagicMock()

        with patch("pynpxpipe.pipelines.runner.SortStage", mock_sort):
            runner.run_stage("sort")

        mock_sort.assert_called_once()
        mock_sort.return_value.run.assert_called_once()

    def test_run_stage_unknown_raises_value_error(self, session: Session) -> None:
        """run_stage('invalid') raises ValueError."""
        runner = _make_runner(session)
        with pytest.raises(ValueError, match="invalid"):
            runner.run_stage("invalid")

    def test_run_unknown_stage_raises_value_error(self, session: Session) -> None:
        """run(stages=['unknown']) raises ValueError."""
        runner = _make_runner(session)
        with pytest.raises(ValueError, match="unknown"):
            runner.run(stages=["unknown"])

    def test_completed_stage_checkpoint_handled_by_stage(self, session: Session) -> None:
        """Runner calls run() on every requested stage; stage itself checks its checkpoint."""
        _write_checkpoint(session, "discover")
        runner = _make_runner(session)
        mock_discover = MagicMock()

        with patch("pynpxpipe.pipelines.runner.DiscoverStage", mock_discover):
            runner.run_stage("discover")

        mock_discover.return_value.run.assert_called_once()


# ---------------------------------------------------------------------------
# Group B — Auto config resolution
# ---------------------------------------------------------------------------


class TestAutoConfig:
    def test_auto_n_jobs_resolved_at_init(self, session: Session) -> None:
        """n_jobs='auto' → ResourceDetector.detect() and recommend() called."""
        mock_detector_cls = MagicMock()
        mock_detector = mock_detector_cls.return_value
        mock_detector.detect.return_value = MagicMock()
        mock_detector.recommend.return_value = MagicMock(
            n_jobs=4, chunk_duration="2s", max_workers=1, sorting_batch_size=65792
        )

        with patch("pynpxpipe.pipelines.runner.ResourceDetector", mock_detector_cls):
            PipelineRunner(
                session,
                _make_pipeline_config(n_jobs="auto"),
                _make_sorting_config(batch_size=65792),
            )

        mock_detector.detect.assert_called_once()
        mock_detector.recommend.assert_called_once()

    def test_explicit_n_jobs_not_overridden(self, session: Session) -> None:
        """n_jobs=4 (explicit) → ResourceDetector never instantiated."""
        with patch("pynpxpipe.pipelines.runner.ResourceDetector") as mock_cls:
            PipelineRunner(
                session,
                _make_pipeline_config(n_jobs=4, chunk_duration="1s", max_workers=1),
                _make_sorting_config(batch_size=65792),
            )

        mock_cls.assert_not_called()

    def test_auto_batch_size_resolved(self, session: Session) -> None:
        """batch_size='auto' → ResourceDetector called and batch_size updated."""
        mock_detector_cls = MagicMock()
        mock_detector = mock_detector_cls.return_value
        mock_detector.detect.return_value = MagicMock()
        mock_detector.recommend.return_value = MagicMock(
            n_jobs=1, chunk_duration="1s", max_workers=1, sorting_batch_size=131072
        )

        with patch("pynpxpipe.pipelines.runner.ResourceDetector", mock_detector_cls):
            PipelineRunner(
                session,
                _make_pipeline_config(n_jobs=1, chunk_duration="1s", max_workers=1),
                _make_sorting_config(batch_size="auto"),
            )

        mock_detector.detect.assert_called_once()


# ---------------------------------------------------------------------------
# Group C — Fail-fast
# ---------------------------------------------------------------------------


class TestFailFast:
    def test_stage_error_stops_pipeline(self, session: Session) -> None:
        """SortError from sort → re-raised, curate not called."""
        runner = _make_runner(session)
        mock_sort = MagicMock()
        mock_sort.return_value.run.side_effect = SortError("GPU OOM")
        mock_curate = MagicMock()

        with (
            patch("pynpxpipe.pipelines.runner.DiscoverStage", MagicMock()),
            patch("pynpxpipe.pipelines.runner.PreprocessStage", MagicMock()),
            patch("pynpxpipe.pipelines.runner.SortStage", mock_sort),
            patch("pynpxpipe.pipelines.runner.SynchronizeStage", MagicMock()),
            patch("pynpxpipe.pipelines.runner.CurateStage", mock_curate),
            patch("pynpxpipe.pipelines.runner.PostprocessStage", MagicMock()),
            patch("pynpxpipe.pipelines.runner.ExportStage", MagicMock()),
            pytest.raises(SortError),
        ):
            runner.run()

        mock_curate.return_value.run.assert_not_called()

    def test_non_stage_error_propagates(self, session: Session) -> None:
        """RuntimeError from sort.run() propagates unchanged."""
        runner = _make_runner(session)
        mock_sort = MagicMock()
        mock_sort.return_value.run.side_effect = RuntimeError("unexpected")

        with (
            patch("pynpxpipe.pipelines.runner.DiscoverStage", MagicMock()),
            patch("pynpxpipe.pipelines.runner.PreprocessStage", MagicMock()),
            patch("pynpxpipe.pipelines.runner.SortStage", mock_sort),
            patch("pynpxpipe.pipelines.runner.SynchronizeStage", MagicMock()),
            patch("pynpxpipe.pipelines.runner.CurateStage", MagicMock()),
            patch("pynpxpipe.pipelines.runner.PostprocessStage", MagicMock()),
            patch("pynpxpipe.pipelines.runner.ExportStage", MagicMock()),
            pytest.raises(RuntimeError, match="unexpected"),
        ):
            runner.run()


# ---------------------------------------------------------------------------
# Group D — get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_status_all_pending(self, session: Session) -> None:
        """No checkpoints → all stages 'pending'."""
        runner = _make_runner(session)
        status = runner.get_status()

        assert set(status.keys()) == set(STAGE_ORDER)
        for stage, val in status.items():
            assert val == "pending", f"{stage}: expected 'pending', got '{val}'"

    def test_status_completed_after_discover(self, session: Session) -> None:
        """discover checkpoint completed → get_status()['discover'] == 'completed'."""
        _write_checkpoint(session, "discover")
        runner = _make_runner(session)
        assert runner.get_status()["discover"] == "completed"

    def test_status_partial_per_probe(self, session: Session) -> None:
        """2 probes, imec0 preprocess done → 'partial (1/2 probes)'."""
        _write_checkpoint(session, "preprocess", probe_id="imec0")
        runner = _make_runner(session)
        assert runner.get_status()["preprocess"] == "partial (1/2 probes)"

    def test_status_failed(self, session: Session) -> None:
        """synchronize checkpoint status=failed → get_status()['synchronize'] == 'failed'."""
        _write_checkpoint(session, "synchronize", status="failed")
        runner = _make_runner(session)
        assert runner.get_status()["synchronize"] == "failed"
