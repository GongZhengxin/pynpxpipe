"""GUI pairing and task-window configuration contracts."""

from pynpxpipe.core.config import PipelineConfig, TaskWindowConfig
from pynpxpipe.ui.components.pipeline_form import PipelineForm
from pynpxpipe.ui.components.session_form import SessionForm
from pynpxpipe.ui.components.session_loader import SessionLoader
from pynpxpipe.ui.state import AppState


def test_new_gui_selects_tasks_and_resume_respects_legacy_default(tmp_path):
    state = AppState()
    form = PipelineForm(state)
    assert state.pipeline_config.task_windows.enabled is True
    SessionLoader(state)._restore_effective_configs(tmp_path)
    assert state.pipeline_config.task_windows.enabled is False
    form.apply_pipeline(PipelineConfig())
    assert state.pipeline_config.task_windows.enabled is False
    cfg = PipelineConfig(
        task_windows=TaskWindowConfig(
            enabled=True,
            max_idle_s=75,
            padding_before_s=3,
            padding_after_s=4,
            recording_timezone="UTC",
        )
    )
    form.apply_pipeline(cfg)
    assert state.pipeline_config.task_windows == cfg.task_windows


def test_pair_add_remove_and_restore(tmp_path):
    state = AppState(session_dir=tmp_path, bhv_file=tmp_path / "a.bhv2")
    form = SessionForm(state)
    form._add_pair()
    assert len(state.recordings) == 1
    assert state.recordings[0]["source_id"] == "source0"
    state.bhv_file = tmp_path / "b.bhv2"
    form._add_pair()
    assert form.pairs_table.value.source_id.tolist() == ["source0", "source1"]
    form.pairs_table.selection = [0]
    form._remove_pair()
    assert state.recordings[0]["source_id"] == "source1"
    state.recordings = [
        {"source_id": "loaded", "session_dir": str(tmp_path), "bhv_file": str(tmp_path / "c.bhv2")}
    ]
    assert form.pairs_table.value.source_id.tolist() == ["loaded"]
