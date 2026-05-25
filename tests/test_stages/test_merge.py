"""Tests for stages/merge.py error handling."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from pynpxpipe.core.config import MergeConfig, PipelineConfig
from pynpxpipe.core.errors import MergeError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.stages.merge import MergeStage


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
        target_area="V4",
    )


@pytest.fixture
def merge_session(tmp_path: Path) -> Session:
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
    s.config = PipelineConfig(merge=MergeConfig(enabled=True))
    return s


def test_disabled_merge_skips_without_processing(merge_session: Session) -> None:
    merge_session.config.merge.enabled = False

    with patch.object(MergeStage, "_merge_probe") as mock_merge:
        MergeStage(merge_session).run()

    mock_merge.assert_not_called()


def test_load_failure_raises_merge_error(merge_session: Session) -> None:
    with (
        patch("pynpxpipe.stages.merge.si.load", side_effect=RuntimeError("missing sorted")),
        pytest.raises(MergeError, match="imec0"),
    ):
        MergeStage(merge_session)._merge_probe("imec0")


def test_unexpected_probe_error_wrapped_as_merge_error(merge_session: Session) -> None:
    with (
        patch.object(
            MergeStage,
            "_merge_probe",
            side_effect=RuntimeError("auto_merge failed"),
        ),
        pytest.raises(MergeError, match="Failed to merge imec0"),
    ):
        MergeStage(merge_session).run()

    cp = merge_session.output_dir / "checkpoints" / "merge_imec0.json"
    data = json.loads(cp.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert "Failed to merge imec0" in data["error"]


def test_merge_probe_writes_log_and_checkpoint(merge_session: Session) -> None:
    sorting = MagicMock()
    sorting.get_unit_ids.return_value = [1, 2, 3]
    analyzer = MagicMock()
    analyzer.sorting = sorting
    analyzer.recording = MagicMock()
    analyzer.has_extension.return_value = False

    merged_sorting = MagicMock()
    merged_sorting.get_unit_ids.return_value = [1, 3]
    merge_info = SimpleNamespace(merge_unit_groups=[[1, 2], [3]])

    with (
        patch("pynpxpipe.stages.merge.si.load", return_value=analyzer),
        patch("pynpxpipe.stages.merge.si.create_sorting_analyzer") as mock_create,
        patch(
            "spikeinterface.curation.auto_merge",
            return_value=(merged_sorting, merge_info),
        ) as mock_auto_merge,
    ):
        MergeStage(merge_session)._merge_probe("imec0")

    mock_auto_merge.assert_called_once_with(analyzer, return_merge_info=True)
    mock_create.assert_called_once()
    analyzer.compute.assert_any_call("random_spikes")
    analyzer.compute.assert_any_call("waveforms")
    analyzer.compute.assert_any_call("templates")
    analyzer.compute.assert_any_call("template_similarity")

    merged_dir = merge_session.output_dir / "03_merged" / "imec0"
    merge_log = json.loads((merged_dir / "merge_log.json").read_text(encoding="utf-8"))
    assert merge_log["merges"] == [{"merged_ids": [1, 2], "new_id": 1}]
    assert merge_log["n_units_before"] == 3
    assert merge_log["n_units_after"] == 2

    cp = merge_session.output_dir / "checkpoints" / "merge_imec0.json"
    data = json.loads(cp.read_text(encoding="utf-8"))
    assert data["status"] == "completed"
    assert data["n_merges"] == 1
