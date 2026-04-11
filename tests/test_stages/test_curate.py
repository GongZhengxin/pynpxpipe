"""Tests for stages/curate.py — CurateStage.

Groups:
  A. Normal flow    — all probes curated, CSV + checkpoint written, counts returned
  B. Filter logic   — threshold application, zero units, config-driven thresholds
  C. Analyzer       — memory format, extension order
  D. Checkpoint skip — per-probe and stage-level resume
  E. Error handling — load failure → CurateError, failed checkpoint
  F. CSV content    — rows == n_before, required columns
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from pynpxpipe.core.config import CurationConfig, PipelineConfig, ResourcesConfig
from pynpxpipe.core.errors import CurateError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.stages.curate import CurateStage

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


def _make_qm_df(unit_ids: list, n_pass: int | None = None) -> pd.DataFrame:
    """Quality metrics DataFrame where first n_pass units pass all default thresholds.

    Default thresholds: isi_max=0.1, amp_max=0.1, pr_min=0.9, snr_min=0.5.
    """
    n = len(unit_ids)
    if n_pass is None:
        n_pass = n
    return pd.DataFrame(
        {
            "isi_violation_ratio": [0.05] * n_pass + [0.2] * (n - n_pass),
            "amplitude_cutoff": [0.05] * n_pass + [0.2] * (n - n_pass),
            "presence_ratio": [0.95] * n_pass + [0.8] * (n - n_pass),
            "snr": [1.0] * n_pass + [0.3] * (n - n_pass),
        },
        index=unit_ids,
    )


def _make_mock_sorting(unit_ids: list) -> MagicMock:
    mock = MagicMock()
    mock.get_unit_ids.return_value = unit_ids
    curated = MagicMock()
    curated.get_unit_ids.return_value = []
    mock.select_units.return_value = curated
    return mock


def _make_mock_analyzer(qm_df: pd.DataFrame) -> MagicMock:
    mock = MagicMock()
    ext = MagicMock()
    ext.get_data.return_value = qm_df
    mock.get_extension.return_value = ext
    return mock


def _make_pipeline_config(
    isi_max: float = 0.1,
    amp_max: float = 0.1,
    pr_min: float = 0.9,
    snr_min: float = 0.5,
    n_jobs: int = 1,
    chunk_duration: str = "1s",
) -> PipelineConfig:
    return PipelineConfig(
        resources=ResourcesConfig(n_jobs=n_jobs, chunk_duration=chunk_duration),
        curation=CurationConfig(
            isi_violation_ratio_max=isi_max,
            amplitude_cutoff_max=amp_max,
            presence_ratio_min=pr_min,
            snr_min=snr_min,
        ),
    )


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Session with two probes (imec0, imec1)."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
    s.probes = [_make_probe("imec0", tmp_path), _make_probe("imec1", tmp_path)]
    s.config = _make_pipeline_config()
    return s


@pytest.fixture
def single_session(tmp_path: Path) -> Session:
    """Session with one probe (imec0)."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
    s.probes = [_make_probe("imec0", tmp_path)]
    s.config = _make_pipeline_config()
    return s


def _write_completed_checkpoint(session: Session, stage: str, probe_id: str | None = None) -> None:
    filename = f"{stage}.json" if probe_id is None else f"{stage}_{probe_id}.json"
    cp_path = session.output_dir / "checkpoints" / filename
    cp_path.write_text(json.dumps({"stage": stage, "status": "completed"}), encoding="utf-8")


def _patch_curate(
    unit_ids: list,
    n_pass: int | None = None,
    qm_df: pd.DataFrame | None = None,
    load_side_effect=None,
):
    """Context manager tuple for patching si calls in curate stage."""
    if qm_df is None:
        qm_df = _make_qm_df(unit_ids, n_pass)
    mock_sorting = _make_mock_sorting(unit_ids)
    # select_units returns a mock curated sorting with n_pass unit ids
    n = n_pass if n_pass is not None else len(unit_ids)
    mock_curated = MagicMock()
    mock_curated.get_unit_ids.return_value = unit_ids[:n]
    mock_sorting.select_units.return_value = mock_curated
    mock_recording = MagicMock()
    mock_analyzer = _make_mock_analyzer(qm_df)
    return mock_sorting, mock_recording, mock_analyzer, qm_df


# ---------------------------------------------------------------------------
# Group A — Normal flow
# ---------------------------------------------------------------------------


class TestNormalFlow:
    def test_run_curates_all_probes(self, session: Session) -> None:
        """_curate_probe is called once for each probe."""
        unit_ids = [f"u{i}" for i in range(10)]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids, n_pass=5)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording, mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            stage = CurateStage(session)
            stage.run()

        # verify curated/ directories for both probes were created during save
        assert mock_sorting.select_units.call_count == 2

    def test_quality_metrics_csv_written(self, single_session: Session) -> None:
        """curated/imec0/quality_metrics.csv exists after run()."""
        unit_ids = [f"u{i}" for i in range(5)]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session).run()

        csv_path = single_session.output_dir / "curated" / "imec0" / "quality_metrics.csv"
        assert csv_path.exists()

    def test_curated_sorting_saved(self, single_session: Session) -> None:
        """curated_sorting.save is called with folder pointing to curated/imec0."""
        unit_ids = [f"u{i}" for i in range(5)]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids)
        mock_curated = mock_sorting.select_units.return_value

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session).run()

        assert mock_curated.save.called
        folder = mock_curated.save.call_args.kwargs.get("folder") or mock_curated.save.call_args[
            1
        ].get("folder")
        assert folder is not None
        assert "curated" in str(folder)
        assert "imec0" in str(folder)

    def test_probe_checkpoint_written(self, single_session: Session) -> None:
        """checkpoints/curate_imec0.json exists with status=completed."""
        unit_ids = [f"u{i}" for i in range(5)]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session).run()

        cp = single_session.output_dir / "checkpoints" / "curate_imec0.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "completed"

    def test_curate_returns_unit_counts(self, single_session: Session) -> None:
        """_curate_probe returns (n_before, n_after) tuple."""
        unit_ids = [f"u{i}" for i in range(10)]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids, n_pass=5)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            stage = CurateStage(single_session)
            n_before, n_after = stage._curate_probe("imec0")

        assert n_before == 10
        assert n_after == 5

    def test_stage_checkpoint_written(self, single_session: Session) -> None:
        """checkpoints/curate.json exists with status=completed after all probes."""
        unit_ids = [f"u{i}" for i in range(5)]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session).run()

        cp = single_session.output_dir / "checkpoints" / "curate.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "completed"

    def test_gc_called_after_probe(self, session: Session) -> None:
        """gc.collect is called at least once per probe."""
        unit_ids = [f"u{i}" for i in range(5)]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording, mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc") as mock_gc,
        ):
            CurateStage(session).run()

        assert mock_gc.collect.call_count >= 2


# ---------------------------------------------------------------------------
# Group B — Filter logic
# ---------------------------------------------------------------------------


class TestFilterLogic:
    def test_units_passing_all_thresholds_kept(self, single_session: Session) -> None:
        """Units within all threshold bounds are selected (select_units called with them)."""
        unit_ids = ["u0", "u1", "u2"]
        qm_df = _make_qm_df(unit_ids, n_pass=3)  # all pass
        mock_sorting = _make_mock_sorting(unit_ids)
        mock_recording = MagicMock()
        mock_analyzer = _make_mock_analyzer(qm_df)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session)._curate_probe("imec0")

        good_ids = mock_sorting.select_units.call_args[0][0]
        assert set(good_ids) == {"u0", "u1", "u2"}

    def test_units_failing_any_threshold_removed(self, single_session: Session) -> None:
        """Unit with isi_violation_ratio > max is excluded."""
        unit_ids = ["u0", "u1"]
        qm_df = pd.DataFrame(
            {
                "isi_violation_ratio": [0.05, 0.5],  # u1 fails isi
                "amplitude_cutoff": [0.05, 0.05],
                "presence_ratio": [0.95, 0.95],
                "snr": [1.0, 1.0],
            },
            index=unit_ids,
        )
        mock_sorting = _make_mock_sorting(unit_ids)
        mock_recording = MagicMock()
        mock_analyzer = _make_mock_analyzer(qm_df)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session)._curate_probe("imec0")

        good_ids = mock_sorting.select_units.call_args[0][0]
        assert good_ids == ["u0"]

    def test_zero_units_after_curation_logs_warning(self, single_session: Session) -> None:
        """Zero good units after filtering does not raise; n_after == 0."""
        unit_ids = ["u0", "u1"]
        qm_df = _make_qm_df(unit_ids, n_pass=0)  # all fail
        mock_sorting = _make_mock_sorting(unit_ids)
        mock_recording = MagicMock()
        mock_analyzer = _make_mock_analyzer(qm_df)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            stage = CurateStage(single_session)
            n_before, n_after = stage._curate_probe("imec0")  # must not raise

        assert n_after == 0
        assert n_before == 2

    def test_thresholds_read_from_config(self, single_session: Session) -> None:
        """Filtering respects custom snr_min from config (not hardcoded)."""
        single_session.config = _make_pipeline_config(snr_min=2.0)
        unit_ids = ["u0", "u1"]
        # both units have snr=1.0, which is < 2.0 → both should fail
        qm_df = pd.DataFrame(
            {
                "isi_violation_ratio": [0.05, 0.05],
                "amplitude_cutoff": [0.05, 0.05],
                "presence_ratio": [0.95, 0.95],
                "snr": [1.0, 1.0],  # below custom snr_min=2.0
            },
            index=unit_ids,
        )
        mock_sorting = _make_mock_sorting(unit_ids)
        mock_recording = MagicMock()
        mock_analyzer = _make_mock_analyzer(qm_df)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            _, n_after = CurateStage(single_session)._curate_probe("imec0")

        assert n_after == 0


# ---------------------------------------------------------------------------
# Group C — Analyzer construction
# ---------------------------------------------------------------------------


class TestAnalyzerConstruction:
    def test_analyzer_uses_memory_format(self, single_session: Session) -> None:
        """create_sorting_analyzer is called with format='memory'."""
        unit_ids = ["u0"]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ) as mock_create,
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session)._curate_probe("imec0")

        kwargs = mock_create.call_args.kwargs
        assert kwargs.get("format") == "memory"

    def test_extension_order_correct(self, single_session: Session) -> None:
        """Extensions computed in required order: random_spikes→waveforms→templates→noise_levels→quality_metrics."""
        unit_ids = ["u0"]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session)._curate_probe("imec0")

        compute_calls = [c.args[0] for c in mock_analyzer.compute.call_args_list]
        expected_order = [
            "random_spikes",
            "waveforms",
            "templates",
            "noise_levels",
            "quality_metrics",
        ]
        assert compute_calls == expected_order


# ---------------------------------------------------------------------------
# Group D — Checkpoint skip
# ---------------------------------------------------------------------------


class TestCheckpointSkip:
    def test_skips_curated_probe(self, session: Session) -> None:
        """si.load_extractor is NOT called for imec0 when its checkpoint is complete."""
        _write_completed_checkpoint(session, "curate", "imec0")
        unit_ids = [f"u{i}" for i in range(5)]
        mock_sorting, mock_recording, mock_analyzer, _ = _patch_curate(unit_ids)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ) as mock_load,
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(session).run()

        # Only imec1 loaded (not imec0)
        assert mock_load.call_count == 2  # sorting + recording for imec1 only

    def test_stage_skips_if_complete(self, single_session: Session) -> None:
        """run() returns immediately without calling si.load when stage checkpoint is complete."""
        _write_completed_checkpoint(single_session, "curate")

        with patch("pynpxpipe.stages.curate.si.load") as mock_load:
            CurateStage(single_session).run()

        mock_load.assert_not_called()


# ---------------------------------------------------------------------------
# Group E — Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_loading_failure_raises_curate_error(self, single_session: Session) -> None:
        """RuntimeError from si.load_extractor is wrapped and raised as CurateError."""
        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=RuntimeError("file not found"),
            ),
            pytest.raises(CurateError, match="imec0"),
        ):
            CurateStage(single_session).run()

    def test_failed_checkpoint_written_on_error(self, single_session: Session) -> None:
        """checkpoints/curate_imec0.json status=failed is written when loading fails."""
        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=RuntimeError("file not found"),
            ),
            pytest.raises(CurateError),
        ):
            CurateStage(single_session).run()

        cp = single_session.output_dir / "checkpoints" / "curate_imec0.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "failed"


# ---------------------------------------------------------------------------
# Group F — CSV content
# ---------------------------------------------------------------------------


class TestCsvContent:
    def test_quality_metrics_csv_contains_all_units(self, single_session: Session) -> None:
        """CSV row count equals n_before (contains units that were filtered out too)."""
        unit_ids = [f"u{i}" for i in range(8)]
        qm_df = _make_qm_df(unit_ids, n_pass=3)
        mock_sorting = _make_mock_sorting(unit_ids)
        mock_recording = MagicMock()
        mock_analyzer = _make_mock_analyzer(qm_df)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session).run()

        csv_path = single_session.output_dir / "curated" / "imec0" / "quality_metrics.csv"
        written_df = pd.read_csv(csv_path, index_col=0)
        assert len(written_df) == 8

    def test_quality_metrics_csv_has_required_columns(self, single_session: Session) -> None:
        """CSV contains isi_violation_ratio, amplitude_cutoff, presence_ratio, snr columns."""
        unit_ids = ["u0", "u1"]
        qm_df = _make_qm_df(unit_ids)
        mock_sorting = _make_mock_sorting(unit_ids)
        mock_recording = MagicMock()
        mock_analyzer = _make_mock_analyzer(qm_df)

        with (
            patch(
                "pynpxpipe.stages.curate.si.load",
                side_effect=[mock_sorting, mock_recording],
            ),
            patch(
                "pynpxpipe.stages.curate.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.curate.gc"),
        ):
            CurateStage(single_session).run()

        csv_path = single_session.output_dir / "curated" / "imec0" / "quality_metrics.csv"
        written_df = pd.read_csv(csv_path, index_col=0)
        for col in ["isi_violation_ratio", "amplitude_cutoff", "presence_ratio", "snr"]:
            assert col in written_df.columns


def test_amplitude_cutoff_is_computed_and_applied(tmp_path: Path) -> None:
    """Regression: amplitude_cutoff_max must filter units, not just be in config.

    unit0: amplitude_cutoff=0.05 (passes 0.1 max)
    unit1: amplitude_cutoff=0.15 (fails 0.1 max)
    Verify unit1 is excluded from select_units call.
    """
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
    s.probes = [_make_probe("imec0", tmp_path)]
    s.config = _make_pipeline_config(amp_max=0.1)

    qm_df = pd.DataFrame(
        {
            "isi_violation_ratio": [0.05, 0.05],
            "amplitude_cutoff": [0.05, 0.15],  # unit1 exceeds 0.1 max
            "presence_ratio": [0.95, 0.95],
            "snr": [1.5, 1.5],
        },
        index=["unit0", "unit1"],
    )
    mock_sorting = _make_mock_sorting(["unit0", "unit1"])
    mock_recording = MagicMock()
    mock_analyzer = _make_mock_analyzer(qm_df)

    with (
        patch(
            "pynpxpipe.stages.curate.si.load",
            side_effect=[mock_sorting, mock_recording],
        ),
        patch(
            "pynpxpipe.stages.curate.si.create_sorting_analyzer",
            return_value=mock_analyzer,
        ),
        patch("pynpxpipe.stages.curate.gc"),
    ):
        stage = CurateStage(s)
        stage._curate_probe("imec0")

    good_ids = mock_sorting.select_units.call_args[0][0]
    assert "unit0" in good_ids
    assert "unit1" not in good_ids
