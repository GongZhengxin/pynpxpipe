"""Tests for ui/app.py — A5 Integration & Polish.

Groups:
  A. create_app basics — returns viewable, main exists
  B. Section structure — three sections, default visible, content counts
  C. Navigation — switching sections
  D. Error banner — hidden initially, shows on error
"""

from __future__ import annotations

import panel as pn
import pytest


def test_web_ui_writes_diagnostic_png_in_worker_with_gui_backend_configured(tmp_path):
    import os
    import subprocess
    import sys
    import textwrap

    pytest.importorskip("matplotlib")
    script = textwrap.dedent("""
        import sys
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        import matplotlib
        from pynpxpipe.ui.app import create_app

        app = create_app()
        assert matplotlib.get_backend().lower() == "agg", matplotlib.get_backend()
        from pynpxpipe.io.sync.imec_nidq_align import SyncResult
        from pynpxpipe.plots.sync import _plot_sync_residuals
        import numpy as np
        directory = Path(sys.argv[1])
        with ThreadPoolExecutor(max_workers=1) as pool:
            fit = SyncResult("imec0", 1., 0., 0., 0)
            path = pool.submit(_plot_sync_residuals, "imec0", np.arange(4.), np.arange(4.),
                               fit, directory, None).result()
        assert path.read_bytes().startswith(bytes.fromhex("89504e470d0a1a0a"))
    """)
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        env={**os.environ, "MPLBACKEND": "TkAgg"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "outside of the main thread" not in result.stderr


@pytest.mark.parametrize("mode", ["single", "joint"])
def test_preview_routes_only_active_inputs_and_never_requests_sorting(tmp_path, monkeypatch, mode):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import pynpxpipe.ui.app as app_module
    from pynpxpipe.core.config import PipelineConfig, SortingConfig
    from pynpxpipe.core.session import SessionManager, SubjectConfig
    from pynpxpipe.pipelines.runner import PipelineRunner

    captured = {}
    original = app_module.RunPanel

    def capture_panel(state, **kwargs):
        captured.update(kwargs)
        return original(state, **kwargs)

    monkeypatch.setattr(app_module, "RunPanel", capture_panel)
    session = SimpleNamespace(log_path=tmp_path / "run.log")
    single = Mock(return_value=session)
    joint = Mock(return_value=session)
    monkeypatch.setattr(SessionManager, "create", single)
    monkeypatch.setattr(SessionManager, "create_from_recordings", joint)
    monkeypatch.setattr(PipelineRunner, "__init__", lambda self, *args, **kwargs: None)
    run = Mock()
    monkeypatch.setattr(PipelineRunner, "run", run)
    monkeypatch.setattr("pynpxpipe.core.logging.setup_logging", lambda path: None)
    app = app_module.create_app()
    state = app._pynpx_state
    state.input_mode = mode
    state.session_dir = tmp_path / "single_g0" if mode == "single" else None
    state.bhv_file = tmp_path / "single.bhv2"
    state.output_dir = tmp_path / "out"
    state.subject_config = SubjectConfig("test", "test", "Macaca mulatta", "M", "P5Y", "10kg")
    state.pipeline_config = PipelineConfig()
    state.sorting_config = SortingConfig()
    state.recordings = [
        {
            "source_id": f"s{i}",
            "session_dir": str(tmp_path / f"g{i}"),
            "bhv_file": str(tmp_path / f"{i}.bhv2"),
        }
        for i in range(2)
    ]
    captured["preview_fn"](state, SimpleNamespace(callback=lambda *args: None))
    assert joint.called == (mode == "joint")
    assert single.called == (mode == "single")
    run.assert_called_once_with(stages=["discover", "synchronize", "select_segments"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_result():
    """Call create_app and return (template_or_viewable, app_obj)."""
    from pynpxpipe.ui.app import create_app

    return create_app()


# ---------------------------------------------------------------------------
# A. Basics
# ---------------------------------------------------------------------------


class TestBasics:
    def test_create_app_returns_template(self):
        from pynpxpipe.ui.app import create_app

        app = create_app()
        assert isinstance(app, pn.template.BaseTemplate)

    def test_main_function_exists(self):
        from pynpxpipe.ui.app import main

        assert callable(main)


# ---------------------------------------------------------------------------
# B. Section structure
# ---------------------------------------------------------------------------


class TestSectionStructure:
    def test_has_four_sections(self):
        """App should expose configure, execute, review, help sections."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        assert hasattr(app, "_pynpx_sections")
        sections = app._pynpx_sections
        assert set(sections.keys()) == {"configure", "execute", "review", "help"}

    def test_views_are_routed_and_home_is_session_list(self):
        """P1-1: the router picks one view; the session list is the home page."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        views = app._pynpx_views
        assert set(views) == {"sessions", "new", "session", "task_window", "help"}
        assert app._pynpx_router.view == "sessions"
        assert [k for k, v in views.items() if v.visible] == ["sessions"]
        app._pynpx_router.go("new")
        assert [k for k, v in views.items() if v.visible] == ["new"]
        assert app._pynpx_sections["configure"].visible is True

    def test_home_view_is_the_session_list(self):
        from pynpxpipe.ui.app import create_app
        from pynpxpipe.ui.components.session_list import SessionList

        app = create_app()
        session_list = app._pynpx_session_list
        assert isinstance(session_list, SessionList)
        home = app._pynpx_views["sessions"]
        assert any(b is session_list.new_btn for b in home.select(pn.widgets.Button))

    def test_routing_to_a_session_directory_loads_it(self, tmp_path, monkeypatch):
        from pynpxpipe.ui.app import create_app
        from pynpxpipe.ui.components.session_loader import SessionLoader

        opened = []
        monkeypatch.setattr(SessionLoader, "load", lambda self, d: opened.append(d) or True)
        app = create_app()
        app._pynpx_router.go("session", output_dir=str(tmp_path))
        assert opened == [str(tmp_path)]

    def test_light_theme_by_default_with_dark_toggle(self):

        from pynpxpipe.ui.app import create_app

        app = create_app()
        assert "Dark" not in app.theme.__name__
        assert app.theme_toggle is True

    def test_new_view_is_the_four_step_wizard(self):
        """P1-3: "新建" is a 4-step wizard reusing the existing forms."""
        from pynpxpipe.ui.app import create_app
        from pynpxpipe.ui.components.wizard import Wizard

        app = create_app()
        wizard = app._pynpx_wizard
        assert isinstance(wizard, Wizard)
        assert [s.title for s in wizard.steps] == ["数据", "动物与探针", "参数", "检查并运行"]
        assert app._pynpx_sections["configure"] is app._pynpx_views["new"]

    def test_parameter_step_starts_with_preset_bar(self):
        """P0-2 preset bar sits above the parameter forms in step 3."""
        from pynpxpipe.ui.app import create_app
        from pynpxpipe.ui.components.preset_bar import PresetBar

        app = create_app()
        bar = app._pynpx_preset_bar
        assert isinstance(bar, PresetBar)
        params = app._pynpx_wizard.steps[2].body
        assert any(w is bar.preset_select for w in params.objects[0].select(pn.widgets.Select))

    def test_wizard_steps_hold_the_forms(self):
        from pynpxpipe.ui.app import create_app

        app = create_app()
        steps = app._pynpx_wizard.steps
        data_text = " ".join(str(p.object) for p in steps[0].body.select(pn.pane.Markdown))
        assert "数据与输出" in data_text
        subject_text = " ".join(str(p.object) for p in steps[1].body.select(pn.pane.Markdown))
        assert "实验动物" in subject_text and "探针脑区" in subject_text

    def test_header_status_badge_replaces_sidebar_text(self):
        """P0-5: the run status is a coloured badge in the header, not sidebar text."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        badge = app._pynpx_status_badge
        assert any(obj is badge for obj in pn.Column(*app.header.objects).select(pn.pane.HTML))
        assert "空闲" in badge.object
        assert not any("Status:" in str(getattr(o, "object", "")) for o in app.sidebar.objects)

    @pytest.mark.parametrize(
        ("status", "text", "color"),
        [
            ("running", "运行中", "#0B6E8E"),
            ("exporting", "导出中", "#0B6E8E"),
            ("completed", "已完成", "#2E8B57"),
        ],
    )
    def test_header_status_badge_colours(self, status, text, color):
        from pynpxpipe.ui.app import create_app

        app = create_app()
        app._pynpx_state.run_status = status
        badge = app._pynpx_status_badge.object
        assert text in badge and color in badge

    def test_header_status_badge_shows_short_failure_reason(self):
        from pynpxpipe.ui.app import create_app

        app = create_app()
        state = app._pynpx_state
        state.error_message = "ValueError: " + "x" * 300 + "\nTraceback line"
        state.run_status = "failed"
        badge = app._pynpx_status_badge.object
        assert "失败" in badge and "#C8372D" in badge
        assert "ValueError" in badge
        assert "Traceback line" not in badge
        assert "x" * 200 not in badge

    def test_navigation_moved_from_sidebar_to_header(self):
        """P1-1: no sidebar navigation; the header carries Sessions / 新建 / 帮助."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        assert not any(isinstance(o, pn.widgets.Button) for o in app.sidebar.objects)
        header = pn.Column(*app.header.objects)
        names = [b.name for b in header.select(pn.widgets.Button)]
        assert names[:3] == ["Sessions", "新建", "帮助"]

    def test_rerun_dialog_lives_in_template_modal(self):
        """P0-4: the rerun confirmation uses the template's modal area."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        view = app._pynpx_status_view
        assert any(obj is view.rerun_dialog for obj in app.modal.objects)

    def test_session_view_is_the_workspace(self):
        """P1-5: execute and review become collapsed sections of the workspace."""
        from pynpxpipe.ui.app import create_app
        from pynpxpipe.ui.components.workspace import Workspace

        app = create_app()
        workspace = app._pynpx_workspace
        assert isinstance(workspace, Workspace)
        view = app._pynpx_views["session"]
        assert any(b is workspace.rerun_btn for b in view.select(pn.widgets.Button))
        cards = list(view.select(pn.Card))
        assert {c.title for c in cards} >= {"运行控制与任务时段时间轴", "全部阶段状态"}
        assert any(c is app._pynpx_sections["execute"] for card in cards for c in card.objects)

    def test_no_session_loader_panels_remain(self):
        """P1-2: the session list replaces both "Load Session" panels."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        names = {b.name for v in app._pynpx_views.values() for b in v.select(pn.widgets.Button)}
        assert "Load Session" not in names and "打开已保存的预览" not in names


# ---------------------------------------------------------------------------
# C. Navigation
# ---------------------------------------------------------------------------


class TestNavigation:
    @pytest.mark.parametrize("legacy", ["execute", "review"])
    def test_legacy_section_names_open_the_session_view(self, legacy):
        """Execute and review now live together in the session view."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        app._pynpx_switch(legacy)
        assert app._pynpx_router.view == "session"
        views, sections = app._pynpx_views, app._pynpx_sections
        assert views["session"].visible and not views["new"].visible
        assert sections["execute"].visible and sections["review"].visible
        assert not sections["configure"].visible

    def test_switch_accepts_new_view_names(self):
        from pynpxpipe.ui.app import create_app

        app = create_app()
        app._pynpx_switch("help")
        assert app._pynpx_views["help"].visible


# ---------------------------------------------------------------------------
# D. Error banner
# ---------------------------------------------------------------------------


class TestErrorBanner:
    def test_error_banner_hidden_initially(self):
        """Error banner should not be visible when error_message is empty."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        banner = app._pynpx_error_banner
        assert banner.visible is False

    def test_error_banner_shows_on_error(self):
        """Error banner should appear when state.error_message is set."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        state = app._pynpx_state
        state.error_message = "Something went wrong"
        assert app._pynpx_error_banner.visible is True
        assert "Something went wrong" in app._pynpx_error_banner.object


def test_task_window_view_hosts_the_confirmation_page():
    from pynpxpipe.ui.app import create_app
    from pynpxpipe.ui.components.task_window_page import TaskWindowPage

    app = create_app()
    page = app._pynpx_task_window_page
    assert isinstance(page, TaskWindowPage)
    view = app._pynpx_views["task_window"]
    assert any(b is page.confirm_btn for b in view.select(pn.widgets.Button))


def test_error_suggestion_applies_change_and_opens_rerun(tmp_path):
    """P1-6: "按建议修改并重跑" edits the sorting form and opens the P0-4 dialog."""
    import dataclasses

    from pynpxpipe.ui.app import create_app

    app = create_app()
    state = app._pynpx_state
    state.output_dir = str(tmp_path)
    cfg = state.sorting_config
    params = dataclasses.replace(cfg.sorter.params, batch_size=60000)
    state.sorting_config = dataclasses.replace(
        cfg, sorter=dataclasses.replace(cfg.sorter, params=params)
    )
    view = app._pynpx_status_view
    view.load_status = lambda: None  # no session.json in tmp_path
    app._pynpx_error_view._apply_fn((("sorter.params.batch_size", 40000),), "sort", None)
    assert state.sorting_config.sorter.params.batch_size == 40000
    assert view.rerun_dialog.visible
