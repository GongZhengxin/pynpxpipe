"""Tests for ui/components/wizard.py and the wizard steps 1–2 (ui_redesign.md §4.3 P1-3, §8.7)."""

from __future__ import annotations

import json
from pathlib import Path

import panel as pn

from pynpxpipe.ui.state import AppState


def _wizard(validators=None):
    from pynpxpipe.ui.components.wizard import Wizard, WizardStep

    validators = validators or {}
    steps = [
        WizardStep(title, pn.pane.Markdown(f"body {i}"), validators.get(i))
        for i, title in enumerate(["数据", "动物与探针", "参数", "检查并运行"])
    ]
    cancelled = []
    return Wizard(steps, on_cancel=lambda: cancelled.append(1)), cancelled


class TestWizardShell:
    def test_starts_on_first_step_with_only_its_body_visible(self):
        wizard, _ = _wizard()
        assert wizard.index == 0
        assert [s.body.visible for s in wizard.steps] == [True, False, False, False]
        assert wizard.next_btn.name == "下一步：动物与探针"
        assert wizard.prev_btn.visible is False

    def test_next_and_prev(self):
        wizard, _ = _wizard()
        wizard.next_btn.clicks += 1
        assert wizard.index == 1 and wizard.steps[1].body.visible
        assert wizard.prev_btn.visible is True
        wizard.prev_btn.clicks += 1
        assert wizard.index == 0

    def test_validation_blocks_next_and_shows_reason(self):
        wizard, _ = _wizard({0: lambda: "请先选择数据目录"})
        wizard.next_btn.clicks += 1
        assert wizard.index == 0
        assert wizard.alert.visible and "请先选择数据目录" in wizard.alert.object

    def test_indicator_marks_done_and_current(self):
        wizard, _ = _wizard()
        wizard.next_btn.clicks += 1
        html = wizard.indicator.object
        assert "✓" in html and "数据" in html
        assert 'aria-current="step"' in html

    def test_last_step_hides_next(self):
        wizard, _ = _wizard()
        for _ in range(3):
            wizard.next_btn.clicks += 1
        assert wizard.index == 3 and wizard.next_btn.visible is False

    def test_cancel_and_draft_note(self):
        wizard, cancelled = _wizard()
        wizard.cancel_btn.clicks += 1
        assert cancelled == [1]
        assert "草稿已自动保存" in wizard.draft_note.object

    def test_reset_returns_to_first_step(self):
        wizard, _ = _wizard()
        wizard.next_btn.clicks += 1
        wizard.reset()
        assert wizard.index == 0


# ── Step 1: data ──


def _make_recording(root: Path, probes=("imec0", "imec1")) -> None:
    gate = root / "run_g0"
    gate.mkdir()
    (gate / "run_g0_t0.nidq.bin").write_bytes(b"\0" * 16)
    (gate / "run_g0_t0.nidq.meta").write_text("niSampRate=25000\nnSavedChans=8\n", encoding="utf-8")
    for probe in probes:
        d = gate / f"run_g0_{probe}"
        d.mkdir()
        (d / f"run_g0_t0.{probe}.ap.bin").write_bytes(b"\0" * 64)
        (d / f"run_g0_t0.{probe}.ap.meta").write_text(
            "fileCreateTime=2025-10-24T14:30:00\nimSampRate=30000\nnSavedChans=385\n"
            "imDatPrb_sn=1\nimDatPrb_type=0\n",
            encoding="utf-8",
        )
    (root / "task.bhv2").write_bytes(b"")


class TestDataStep:
    def test_discovered_probes_are_announced(self, tmp_path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(tmp_path)
        form = SessionForm(AppState())
        seen = []
        form.probe_listeners.append(seen.append)
        form.data_dir_input.value = str(tmp_path)
        assert seen == [["imec0", "imec1"]]
        assert form.discovered_probe_ids == ["imec0", "imec1"]

    def test_add_recording_button_replaces_mode_toggle(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        layout = form.panel()
        assert not any(w is form.input_mode for w in layout.select(pn.widgets.RadioButtonGroup))
        assert form.add_recording_btn.name.startswith("+ 添加同一天的另一段记录")
        form.add_recording_btn.clicks += 1
        assert state.input_mode == "joint"
        assert form.single_mode_btn.visible and not form.add_recording_btn.visible
        form.single_mode_btn.clicks += 1
        assert state.input_mode == "single"


# ── Step 2: subject + probes ──


def _monkeys(root: Path) -> None:
    d = root / "monkeys"
    d.mkdir()
    for name, sex in (("MaoDan", "M"), ("XiaoHei", "F")):
        (d / f"{name}.yaml").write_text(
            f"Subject:\n  subject_id: {name}\n  description: test\n  species: Macaca mulatta\n"
            f"  sex: {sex}\n  age: P6Y\n  weight: 9.8kg\n",
            encoding="utf-8",
        )


class TestSubjectStep:
    def test_profile_cards_from_monkeys_dir(self, tmp_path):
        from pynpxpipe.ui.components.subject_form import SubjectForm

        _monkeys(tmp_path)
        form = SubjectForm(AppState(), project_root=tmp_path)
        assert list(form.profile_buttons) == ["MaoDan", "XiaoHei"]
        assert form.new_subject_btn.name == "+ 新动物"

    def test_selecting_profile_shows_read_only_summary(self, tmp_path):
        from pynpxpipe.ui.components.subject_form import SubjectForm

        _monkeys(tmp_path)
        state = AppState()
        form = SubjectForm(state, project_root=tmp_path)
        form.profile_buttons["XiaoHei"].clicks += 1
        assert state.subject_config.subject_id == "XiaoHei"
        assert form.profile_summary.visible and "P6Y" in form.profile_summary.object
        assert form.fields_box.visible is False
        assert form.profile_buttons["XiaoHei"].button_type == "primary"
        form.edit_btn.clicks += 1
        assert form.fields_box.visible is True

    def test_new_subject_opens_empty_form(self, tmp_path):
        from pynpxpipe.ui.components.subject_form import SubjectForm

        _monkeys(tmp_path)
        form = SubjectForm(AppState(), project_root=tmp_path)
        form.profile_buttons["MaoDan"].clicks += 1
        form.new_subject_btn.clicks += 1
        assert form.fields_box.visible and not form.profile_summary.visible
        assert form.subject_id_input.value == ""

    def test_wizard_panel_contains_cards_and_heading(self, tmp_path):
        from pynpxpipe.ui.components.subject_form import SubjectForm

        _monkeys(tmp_path)
        form = SubjectForm(AppState(), project_root=tmp_path)
        layout = form.wizard_panel()
        assert "实验动物" in " ".join(str(p.object) for p in layout.select(pn.pane.Markdown))
        assert form.profile_buttons["MaoDan"] in list(layout.select(pn.widgets.Button))


def _remember_session(store: Path, out: Path, subject: str, plan: dict) -> None:
    from pynpxpipe.ui.recent_sessions import entry_from_output, remember

    out.mkdir(parents=True)
    (out / "session.json").write_text(
        json.dumps({"subject": {"subject_id": subject}, "probe_plan": plan}), encoding="utf-8"
    )
    remember(store, entry_from_output(out, now=0.0), max_entries=20, now=float(len(plan)))


class TestProbeStep:
    def test_set_probes_follows_discovery_and_keeps_typed_areas(self):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor

        state = AppState()
        editor = ProbeRegionEditor(state)
        state.probe_plan = {"imec0": "V4"}
        editor.set_probes(["imec0", "imec1"])
        assert state.probe_plan == {"imec0": "V4", "imec1": ""}

    def test_prefill_from_latest_session_of_same_subject(self, tmp_path, monkeypatch):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor
        from pynpxpipe.ui.recent_sessions import RECENT_PATH_ENV

        store = tmp_path / "recent.json"
        monkeypatch.setenv(RECENT_PATH_ENV, str(store))
        _remember_session(store, tmp_path / "old", "MaoDan", {"imec0": "PFC"})
        _remember_session(store, tmp_path / "new", "MaoDan", {"imec0": "V4", "imec1": "IT"})
        _remember_session(store, tmp_path / "other", "XiaoHei", {"imec0": "MT", "imec1": "LIP"})

        state = AppState()
        editor = ProbeRegionEditor(state)
        editor.set_probes(["imec0", "imec1"])
        editor.prefill_from_history("MaoDan")
        assert state.probe_plan == {"imec0": "V4", "imec1": "IT"}
        hint = editor.history_hint.object
        assert "imec0 = V4" in hint and "PFC" in hint and "MT" not in hint

    def test_prefill_never_overwrites_typed_area(self, tmp_path, monkeypatch):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor
        from pynpxpipe.ui.recent_sessions import RECENT_PATH_ENV

        store = tmp_path / "recent.json"
        monkeypatch.setenv(RECENT_PATH_ENV, str(store))
        _remember_session(store, tmp_path / "s", "MaoDan", {"imec0": "V4"})
        state = AppState()
        editor = ProbeRegionEditor(state)
        state.probe_plan = {"imec0": "IT"}
        editor.prefill_from_history("MaoDan")
        assert state.probe_plan == {"imec0": "IT"}

    def test_heading_is_chinese(self):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor

        layout = ProbeRegionEditor(AppState()).panel()
        assert "探针脑区" in " ".join(str(p.object) for p in layout.select(pn.pane.Markdown))


# ── Step 4: review and run (S10) ──


def _review(checks=None, eta=None, merge=False):
    import dataclasses

    from pynpxpipe.core.config import MergeConfig, PipelineConfig
    from pynpxpipe.core.session import SubjectConfig
    from pynpxpipe.harness.preflight import CheckResult
    from pynpxpipe.ui.components.wizard import ReviewStep

    state = AppState()
    state.subject_config = SubjectConfig("MaoDan", "d", "Macaca mulatta", "M", "P6Y", "9kg")
    state.experiment, state.recording_date = "nsd1w", "251024"
    state.probe_plan = {"imec0": "V4", "imec1": "IT"}
    state.output_dir = "D:/out"
    state.pipeline_config = dataclasses.replace(PipelineConfig(), merge=MergeConfig(enabled=merge))
    state.selected_stages = [
        "discover", "synchronize", "select_segments", "preprocess", "sort", "curate",
        "postprocess", "export",
    ]  # fmt: skip
    started = []
    default_checks = [
        CheckResult("env", "GPU", "pass", "RTX 4090 · 24 GB"),
        CheckResult("disk", "磁盘", "warn", "可用 60 GB"),
    ]
    step = ReviewStep(
        state,
        checks_fn=lambda: default_checks if checks is None else checks,
        eta_fn=eta or (lambda stage: None),
        start_fn=started.append,
        params_summary_fn=lambda: "预设 E2，改了 3 项",
    )
    return step, state, started


class TestReviewStep:
    def test_summary_lists_session_probes_params_and_output(self):
        step, *_ = _review()
        step.refresh()
        text = step.summary.object
        assert "251024_MaoDan_nsd1w" in text
        assert "imec0 V4" in text and "imec1 IT" in text
        assert "预设 E2，改了 3 项" in text and "D:/out" in text

    def test_checks_are_listed_with_counts(self):
        step, *_ = _review()
        step.refresh()
        assert "1 项通过 · 1 项提醒" in step.checks_title.object
        assert "RTX 4090" in step.checks_pane.object and "可用 60 GB" in step.checks_pane.object
        assert step.start_btn.disabled is False

    def test_failed_check_blocks_start(self):
        from pynpxpipe.harness.preflight import CheckResult

        step, *_ = _review(
            checks=[CheckResult("cfg", "nblocks", "fail", "运动校正与 nblocks 互斥")]
        )
        step.refresh()
        assert step.start_btn.disabled is True
        assert "1 项未通过" in step.checks_title.object

    def test_default_mode_aligns_first(self):
        step, _, started = _review()
        step.refresh()
        assert step.mode.value == "align"
        assert step.start_btn.name == "开始对齐"
        step.start_btn.clicks += 1
        assert started == ["align"]

    def test_full_run_mode(self):
        step, _, started = _review()
        step.mode.value = "full"
        assert step.start_btn.name == "开始全部运行"
        step.start_btn.clicks += 1
        assert started == ["full"]

    def test_stage_list_shows_skipped_merge_and_hides_unknown_eta(self):
        step, *_ = _review()
        step.refresh()
        html = step.stages_pane.object
        assert "merge" in html and "跳过" in html
        assert "—" in html
        assert step.total_eta.object == ""

    def test_known_etas_add_up(self):
        step, *_ = _review(eta=lambda stage: 600.0)
        step.refresh()
        assert "10 min" in step.stages_pane.object
        assert "预计 1 h 20 min" in step.total_eta.object  # 8 stages × 10 min

    def test_align_mode_lists_only_alignment_stages(self):
        step, *_ = _review(eta=lambda stage: 60.0)
        step.refresh()
        assert "preprocess" in step.stages_pane.object
        assert "先跑完" in step.mode_note.object


def test_on_enter_runs_when_step_becomes_active():
    from pynpxpipe.ui.components.wizard import Wizard, WizardStep

    entered = []
    steps = [
        WizardStep("a", pn.pane.Markdown("a")),
        WizardStep("b", pn.pane.Markdown("b"), on_enter=lambda: entered.append("b")),
    ]
    wizard = Wizard(steps)
    assert entered == []
    wizard.next_btn.clicks += 1
    assert entered == ["b"]


def test_run_panel_public_start(tmp_path):
    from pynpxpipe.ui.components.run_panel import RunPanel

    calls = []
    panel = RunPanel(AppState())
    panel._on_run_click = lambda event, preview=False: calls.append(preview)
    panel.start(preview=True)
    panel.start(preview=False)
    assert calls == [True, False]
