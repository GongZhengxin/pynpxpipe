"""Tests for ui/components/workspace.py — Session workspace (ui_redesign.md §4.3 P1-5)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import panel as pn
import pytest

from pynpxpipe.pipelines.constants import PER_PROBE_STAGES
from pynpxpipe.pipelines.run_state import RunState, write_run_state
from pynpxpipe.ui.components.log_viewer import LogViewer
from pynpxpipe.ui.router import Router
from pynpxpipe.ui.state import AppState


def _cp(out: Path, name: str, status: str = "completed") -> None:
    (out / "checkpoints").mkdir(parents=True, exist_ok=True)
    (out / "checkpoints" / f"{name}.json").write_text(json.dumps({"status": status}), "utf-8")


@pytest.fixture
def out(tmp_path):
    out = tmp_path / "MaoDan_251024_nsd1w"
    for stage in ("discover", "synchronize", "select_segments", "preprocess"):
        _cp(out, stage)
        if stage in PER_PROBE_STAGES:
            _cp(out, f"{stage}_imec0")
            _cp(out, f"{stage}_imec1")
    _cp(out, "sort_imec0")
    (out / "03_segments").mkdir()
    (out / "03_segments" / "summary.json").write_text(
        json.dumps({"n_blocks": 3, "retained_duration_s": 2892.0, "original_duration_s": 3720.0}),
        "utf-8",
    )
    now = time.time()
    write_run_state(
        out,
        RunState("r", os.getpid(), now - 100, now, ["sort"], "sort", "imec1", 0.64, "running", ""),
    )
    return out


@pytest.fixture
def ws(out):
    from pynpxpipe.ui.components.workspace import Workspace

    state = AppState()
    state.output_dir = str(out)
    state.probe_plan = {"imec0": "V4", "imec1": "IT"}
    router = Router()
    router.go("session", output_dir=str(out))
    calls = {"rerun": [], "stop": 0, "params": 0}
    w = Workspace(
        state,
        router,
        log_viewer=LogViewer(),
        figures=pn.pane.Markdown("figs"),
        export_actions=pn.pane.Markdown("export actions"),
        advanced=[("运行控制", pn.pane.Markdown("advanced"))],
        rerun_fn=calls["rerun"].append,
        stop_fn=lambda: calls.__setitem__("stop", calls["stop"] + 1),
        open_params_fn=lambda: calls.__setitem__("params", calls["params"] + 1),
    )
    w.refresh()
    return w, state, router, calls


def test_header_shows_name_probes_and_running_badge(ws):
    w, *_ = ws
    assert "MaoDan_251024_nsd1w" in w.header.object
    assert "imec0 V4" in w.header.object and "imec1 IT" in w.header.object
    assert "运行中" in w.badge.object
    assert w.stop_btn.visible


def test_stage_rail_status(ws):
    w, *_ = ws
    names = [b.name for b in w.rail_buttons.values()]
    assert names[0].startswith("✓ discover")
    assert w.rail_buttons["sort"].name.startswith("▶ sort")
    assert "64%" in w.rail_buttons["sort"].name
    assert w.rail_buttons["curate"].name.startswith("○ curate")


def test_default_selection_is_running_stage(ws):
    w, *_ = ws
    assert w.selected == "sort"
    assert w.rail_buttons["sort"].button_type == "primary"


def test_probe_bars_for_per_probe_stage(ws):
    w, *_ = ws
    text = " ".join(str(p.object) for p in w.probes_pane.select(pn.pane.Markdown))
    assert "imec0" in text and "完成" in text
    assert "imec1" in text and "64%" in text
    bars = list(w.probes_pane.select(pn.indicators.Progress))
    assert [b.value for b in bars] == [100, 64]


def test_selecting_a_stage_updates_router_and_log_filter(ws):
    w, _, router, _ = ws
    w.rail_buttons["preprocess"].clicks += 1
    assert w.selected == "preprocess" and router.stage == "preprocess"
    assert w._log_viewer.current_stage == "preprocess"


def test_router_stage_is_respected(ws):
    w, _, router, _ = ws
    router.go("session", output_dir=router.output_dir, stage="discover")
    w.refresh()
    assert w.selected == "discover"


def test_actions(ws):
    w, _, _, calls = ws
    w.rerun_btn.clicks += 1
    w.stop_btn.clicks += 1
    w.params_btn.clicks += 1
    assert calls == {"rerun": ["sort"], "stop": 1, "params": 1}
    assert w.import_btn.visible  # sort offers external results
    w.select("export")
    assert not w.import_btn.visible
    assert w.export_box.visible


def test_task_window_card(ws):
    w, _, router, _ = ws
    assert "3 段" in w.task_card.object and "48.2 min" in w.task_card.object
    w.task_btn.clicks += 1
    assert router.view == "task_window"


def test_idle_session_hides_stop(ws, out):
    w, *_ = ws
    write_run_state(
        out, RunState("r", os.getpid(), 0, 0, ["sort"], "sort", None, 1.0, "completed", "")
    )
    w.refresh()
    assert not w.stop_btn.visible
    assert w.selected in w.rail_buttons


def test_panel_contains_advanced_and_figures(ws):
    w, *_ = ws
    texts = " ".join(str(p.object) for p in w.panel().select(pn.pane.Markdown))
    assert "figs" in texts and "advanced" in texts


def test_failed_stage_shows_error_view(out, tmp_path):
    from pynpxpipe.ui.components.workspace import Workspace

    (out / "checkpoints" / "sort_imec1.json").write_text(
        json.dumps({"status": "failed", "error": "CUDA out of memory"}), "utf-8"
    )
    write_run_state(
        out, RunState("r", os.getpid(), 0, 0, ["sort"], "sort", "imec1", 0.3, "failed", "CUDA")
    )
    loaded = []

    class FakeErrorView:
        def load(self, output_dir, stage):
            loaded.append(stage)
            return True

        def panel(self):
            return pn.pane.Markdown("error view")

    state = AppState()
    state.output_dir = str(out)
    state.probe_plan = {"imec0": "V4", "imec1": "IT"}
    router = Router()
    router.go("session", output_dir=str(out))
    w = Workspace(
        state, router, log_viewer=LogViewer(), figures=pn.pane.Markdown(""),
        export_actions=pn.pane.Markdown(""), advanced=[], rerun_fn=print, stop_fn=print,
        open_params_fn=print, error_view=FakeErrorView(),
    )  # fmt: skip
    w.refresh()
    assert w.selected == "sort" and loaded == ["sort"]
    assert w.error_box.visible
    assert "已停止 · sort 失败" in w.badge.object
    w.select("discover")
    assert not w.error_box.visible


def test_continue_button_when_not_running(out):
    from pynpxpipe.ui.components.workspace import Workspace

    write_run_state(
        out, RunState("r", os.getpid(), 0, 0, ["sort"], "sort", None, 0.5, "stopped", "")
    )
    resumed = []
    state = AppState()
    state.output_dir = str(out)
    state.probe_plan = {"imec0": "V4", "imec1": "IT"}
    w = Workspace(
        state, Router(), log_viewer=LogViewer(), figures=pn.pane.Markdown(""),
        export_actions=pn.pane.Markdown(""), advanced=[], rerun_fn=print, stop_fn=print,
        open_params_fn=print, resume_fn=lambda: resumed.append(1),
    )  # fmt: skip
    w.refresh()
    assert w.continue_btn.visible and not w.stop_btn.visible
    w.continue_btn.clicks += 1
    assert resumed == [1]


def test_no_session_hides_run_controls():
    from pynpxpipe.ui.components.workspace import Workspace

    w = Workspace(
        AppState(), Router(), log_viewer=LogViewer(), figures=pn.pane.Markdown(""),
        export_actions=pn.pane.Markdown(""), advanced=[], rerun_fn=print, stop_fn=print,
        open_params_fn=print, resume_fn=print,
    )  # fmt: skip
    w.refresh()
    assert not w.stop_btn.visible and not w.continue_btn.visible
    assert "未打开 session" in w.header.object
