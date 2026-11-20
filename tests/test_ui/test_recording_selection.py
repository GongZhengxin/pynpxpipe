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
    state = AppState(input_mode="joint")
    form = SessionForm(state)
    _fill_pair(form, tmp_path, "a")
    form._add_pair()
    assert len(state.recordings) == 1
    assert state.recordings[0]["source_id"] == "source0"
    _fill_pair(form, tmp_path, "b")
    form._add_pair()
    assert form.pairs_table.value.source_id.tolist() == ["source0", "source1"]
    form.pairs_table.selection = [0]
    form._remove_pair()
    assert state.recordings[0]["source_id"] == "source1"
    state.recordings = [
        {"source_id": "loaded", "session_dir": str(tmp_path), "bhv_file": str(tmp_path / "c.bhv2")}
    ]
    assert form.pairs_table.value.source_id.tolist() == ["loaded"]


def _fill_pair(form, root, name):
    folder = root / f"{name}_g0"
    probe = folder / f"{name}_g0_imec0"
    probe.mkdir(parents=True, exist_ok=True)
    (probe / "run.ap.meta").write_text("imDatPrb_sn=123\n")
    (folder / "run.nidq.meta").touch()
    (folder / "run.nidq.bin").touch()
    bhv = root / f"{name}.bhv2"
    bhv.touch()
    form.pair_session_dir_input.value = str(folder)
    form.pair_bhv_file_input.value = str(bhv)


def test_mode_switch_isolates_single_inputs_and_saved_pairs(tmp_path):
    state = AppState(session_dir=tmp_path / "single", bhv_file=tmp_path / "single.bhv2")
    form = SessionForm(state)
    assert form.single_paths.visible and not form.joint_paths.visible
    form.input_mode.value = "joint"
    _fill_pair(form, tmp_path, "a")
    form._add_pair()
    saved = dict(state.recordings[0])
    form.pair_bhv_file_input.value = str(tmp_path / "unsaved.bhv2")
    assert state.recordings[0] == saved
    assert not form.single_paths.visible and form.joint_paths.visible
    assert str(state.active_session_dir).endswith("a_g0")
    form.input_mode.value = "single"
    assert state.active_recordings == []
    assert state.active_session_dir == tmp_path / "single"
    assert state.recordings == [saved]
    form.input_mode.value = "joint"
    assert state.active_recordings == [saved]


def test_saved_pair_can_be_edited_and_reordered(tmp_path):
    state = AppState(input_mode="joint")
    form = SessionForm(state)
    for name in ("a", "b"):
        _fill_pair(form, tmp_path, name)
        form._add_pair()
    form.pairs_table.selection = [1]
    form._move_pair(-1)
    assert [s["source_id"] for s in state.recordings] == ["source1", "source0"]
    form.pairs_table.selection = [0]
    form._edit_pair()
    form.source_offset_input.value = "120"
    form._save_pair()
    assert state.recordings[0]["start_offset_s"] == 120
    assert len(state.recordings) == 2


def test_wrong_directory_level_is_explained(tmp_path):
    state = AppState(input_mode="joint")
    form = SessionForm(state)
    _fill_pair(form, tmp_path, "a")
    form.pair_session_dir_input.value = str(tmp_path)
    form._add_pair()
    assert state.recordings == []
    assert "NIDQ" in str(form.pairs_alert.object)


def test_joint_validation_uses_saved_pairs_and_requires_two(tmp_path):
    from pynpxpipe.core.session import SubjectConfig
    from pynpxpipe.ui.components.run_panel import RunPanel

    state = AppState(
        input_mode="joint",
        output_dir=tmp_path / "out",
        experiment="test",
        recording_date="261109",
        probe_plan={"imec0": "V4"},
        subject_config=SubjectConfig("test", "test", "Macaca mulatta", "M", "P5Y", "10kg"),
    )
    panel = RunPanel(state)
    assert "两" in panel._validate_before_run()
    form = SessionForm(state)
    for name in ("a", "b"):
        _fill_pair(form, tmp_path, name)
        form._add_pair()
    assert panel._validate_before_run() is None
