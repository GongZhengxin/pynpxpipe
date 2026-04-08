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
    def test_has_three_sections(self):
        """App should expose configure, execute, review sections."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        assert hasattr(app, "_pynpx_sections")
        sections = app._pynpx_sections
        assert set(sections.keys()) == {"configure", "execute", "review"}

    def test_default_section_is_configure(self):
        """Configure should be visible, others hidden on startup."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        sections = app._pynpx_sections
        assert sections["configure"].visible is True
        assert sections["execute"].visible is False
        assert sections["review"].visible is False

    def test_configure_has_five_forms(self):
        """Configure section should contain 5 form components."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        configure = app._pynpx_sections["configure"]
        # Should have at least 5 child objects (the 5 forms)
        assert len(configure.objects) >= 5

    def test_execute_has_three_components(self):
        """Execute section should contain RunPanel + ProgressView + LogViewer."""
        from pynpxpipe.ui.app import create_app

        app = create_app()
        execute = app._pynpx_sections["execute"]
        # Should have at least 3 child objects
        assert len(execute.objects) >= 3

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
