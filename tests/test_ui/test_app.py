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

    def test_default_section_is_configure(self):
        """Configure should be visible, others hidden on startup."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        sections = app._pynpx_sections
        assert sections["configure"].visible is True
        assert sections["execute"].visible is False
        assert sections["review"].visible is False
        assert sections["help"].visible is False

    def test_configure_has_five_forms(self):
        """Configure section should contain 5 form components across both columns."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        configure = app._pynpx_sections["configure"]
        # Left col: session + subject + stages (3); Right col: pipeline + sorting (2)
        left_count = len(configure.objects[0].objects)
        right_count = len(configure.objects[1].objects)
        assert left_count + right_count >= 5

    def test_execute_has_two_columns(self):
        """Execute section should be a Row with left (RunPanel+ProgressView) and right (LogViewer)."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        execute = app._pynpx_sections["execute"]
        # Row with 2 Column children
        assert len(execute.objects) == 2

    def test_review_has_two_components(self):
        """Review section should contain SessionLoader + StatusView."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        review = app._pynpx_sections["review"]
        # Should have at least 2 child objects
        assert len(review.objects) >= 2


# ---------------------------------------------------------------------------
# C. Navigation
# ---------------------------------------------------------------------------


class TestNavigation:
    def test_switch_to_execute(self):
        """After switching to execute, only execute should be visible."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        app._pynpx_switch("execute")
        sections = app._pynpx_sections
        assert sections["configure"].visible is False
        assert sections["execute"].visible is True
        assert sections["review"].visible is False

    def test_switch_to_review(self):
        """After switching to review, only review should be visible."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        app._pynpx_switch("review")
        sections = app._pynpx_sections
        assert sections["configure"].visible is False
        assert sections["execute"].visible is False
        assert sections["review"].visible is True


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


# ---------------------------------------------------------------------------
# E. Configure two-column layout
# ---------------------------------------------------------------------------


class TestConfigureLayout:
    def test_configure_section_is_row(self):
        """Configure section should be a pn.Row (two-column layout)."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        configure = app._pynpx_sections["configure"]
        assert isinstance(configure, pn.Row)

    def test_configure_has_two_columns(self):
        """Configure row should contain exactly two Column children."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        configure = app._pynpx_sections["configure"]
        assert len(configure.objects) == 2
        assert all(isinstance(c, pn.Column) for c in configure.objects)

    def test_left_column_has_session_subject_stages(self):
        """Left column should contain at least 3 components (session, subject, stages)."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        left_col = app._pynpx_sections["configure"].objects[0]
        assert len(left_col.objects) >= 3

    def test_right_column_has_pipeline_sorting(self):
        """Right column should contain at least 2 components (pipeline, sorting)."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        right_col = app._pynpx_sections["configure"].objects[1]
        assert len(right_col.objects) >= 2

    def test_configure_sizing_mode_stretch_width(self):
        """Configure row should have sizing_mode='stretch_width'."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        configure = app._pynpx_sections["configure"]
        assert configure.sizing_mode == "stretch_width"


# ---------------------------------------------------------------------------
# F. SID S3 — ProbeRegionEditor mounted in the left column
# ---------------------------------------------------------------------------


class TestProbeRegionEditorMount:
    def test_left_column_includes_probe_region_editor(self):
        """Left column should contain 'Probe Regions' heading somewhere under configure."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        left_col = app._pynpx_sections["configure"].objects[0]
        # Flatten the column and look for the Probe Regions markdown heading.
        haystack: list = []

        def _walk(obj):
            haystack.append(obj)
            for child in getattr(obj, "objects", []) or []:
                _walk(child)

        _walk(left_col)
        texts = [getattr(o, "object", "") for o in haystack if hasattr(o, "object")]
        assert any("Probe Regions" in str(t) for t in texts)
