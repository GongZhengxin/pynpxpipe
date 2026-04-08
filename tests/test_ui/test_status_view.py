"""Tests for ui/components/status_view.py — Stage status display + reset."""

from __future__ import annotations

from unittest.mock import MagicMock

import panel as pn
import pytest

from pynpxpipe.ui.state import AppState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def state():
    return AppState()


@pytest.fixture()
def mock_status():
    """Return a typical get_status() result."""
    return {
        "discover": "completed",
        "preprocess": "completed",
        "sort": "completed",
        "synchronize": "pending",
        "curate": "pending",
        "postprocess": "pending",
        "export": "pending",
    }


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestStatusViewConstruction:
    def test_creates_panel_layout(self, state):
        from pynpxpipe.ui.components.status_view import StatusView

        view = StatusView(state)
        layout = view.panel()
        assert isinstance(layout, pn.viewable.Viewable)

    def test_initial_state_no_output_dir(self, state):
        """When output_dir is not set, show a placeholder message."""
        from pynpxpipe.ui.components.status_view import StatusView

        view = StatusView(state)
        view.panel()
        # Should contain a message about no output_dir
        assert view.message_pane.object != ""


# ---------------------------------------------------------------------------
# Status rendering
# ---------------------------------------------------------------------------


class TestStatusRendering:
    def test_load_status_shows_all_stages(self, state, mock_status, tmp_path):
        """After loading status, all 7 stages should be displayed."""
        from pynpxpipe.ui.components.status_view import StatusView

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: mock_status)
        view.load_status()

        # Should have 7 stage rows
        assert len(view.stage_rows) == 7

    def test_stage_status_text_shows_correctly(self, state, mock_status, tmp_path):
        """Each stage row should display the stage name and its status."""
        from pynpxpipe.ui.components.status_view import StatusView

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: mock_status)
        view.load_status()

        # Check that completed stages show "completed"
        discover_row = view.stage_rows["discover"]
        assert "completed" in discover_row["status_text"].object.lower()

        # Check pending stages
        curate_row = view.stage_rows["curate"]
        assert "pending" in curate_row["status_text"].object.lower()

    def test_partial_status_shown(self, state, tmp_path):
        """Partial probe completion should be displayed."""
        from pynpxpipe.ui.components.status_view import StatusView

        partial_status = {
            "discover": "completed",
            "preprocess": "partial (1/2 probes)",
            "sort": "pending",
            "synchronize": "pending",
            "curate": "pending",
            "postprocess": "pending",
            "export": "pending",
        }
        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: partial_status)
        view.load_status()

        preprocess_row = view.stage_rows["preprocess"]
        assert "partial" in preprocess_row["status_text"].object.lower()

    def test_failed_status_shown(self, state, tmp_path):
        """Failed stages should be shown with failed status."""
        from pynpxpipe.ui.components.status_view import StatusView

        failed_status = {
            "discover": "completed",
            "preprocess": "failed",
            "sort": "pending",
            "synchronize": "pending",
            "curate": "pending",
            "postprocess": "pending",
            "export": "pending",
        }
        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: failed_status)
        view.load_status()

        preprocess_row = view.stage_rows["preprocess"]
        assert "failed" in preprocess_row["status_text"].object.lower()


# ---------------------------------------------------------------------------
# Reset functionality
# ---------------------------------------------------------------------------


class TestResetStage:
    def test_reset_button_exists_for_each_stage(self, state, mock_status, tmp_path):
        """Each stage row should have a Reset button."""
        from pynpxpipe.ui.components.status_view import StatusView

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: mock_status)
        view.load_status()

        for stage_name in mock_status:
            assert "reset_btn" in view.stage_rows[stage_name]

    def test_reset_calls_clear_fn(self, state, mock_status, tmp_path):
        """Clicking Reset should call the clear function with the stage name."""
        from pynpxpipe.ui.components.status_view import StatusView

        clear_fn = MagicMock()
        state.output_dir = str(tmp_path)
        view = StatusView(
            state,
            get_status_fn=lambda output_dir: mock_status,
            clear_stage_fn=clear_fn,
        )
        view.load_status()

        # Simulate clicking the reset button for "discover"
        view._on_reset_click("discover")
        clear_fn.assert_called_once_with(str(tmp_path), "discover")

    def test_reset_refreshes_status(self, state, tmp_path):
        """After reset, the status should be refreshed."""
        from pynpxpipe.ui.components.status_view import StatusView

        call_count = 0

        def counting_get_status(output_dir):
            nonlocal call_count
            call_count += 1
            return {
                "discover": "pending" if call_count > 1 else "completed",
                "preprocess": "pending",
                "sort": "pending",
                "synchronize": "pending",
                "curate": "pending",
                "postprocess": "pending",
                "export": "pending",
            }

        state.output_dir = str(tmp_path)
        view = StatusView(
            state,
            get_status_fn=counting_get_status,
            clear_stage_fn=lambda output_dir, name: None,
        )
        view.load_status()

        # Reset discover
        view._on_reset_click("discover")

        # Should have called get_status twice (initial + after reset)
        assert call_count == 2
        # After reset, discover should show pending
        assert "pending" in view.stage_rows["discover"]["status_text"].object.lower()

    def test_reset_clears_probe_checkpoints(self, state, mock_status, tmp_path):
        """Reset for a per-probe stage should clear all probe checkpoints."""
        from pynpxpipe.ui.components.status_view import StatusView

        clear_fn = MagicMock()
        state.output_dir = str(tmp_path)
        view = StatusView(
            state,
            get_status_fn=lambda output_dir: mock_status,
            clear_stage_fn=clear_fn,
        )
        view.load_status()

        # Reset preprocess (a per-probe stage)
        view._on_reset_click("preprocess")
        clear_fn.assert_called_once_with(str(tmp_path), "preprocess")


# ---------------------------------------------------------------------------
# Output dir change
# ---------------------------------------------------------------------------


class TestOutputDirChange:
    def test_load_button_triggers_status_load(self, state, mock_status, tmp_path):
        """Clicking the Load button should trigger a status load."""
        from pynpxpipe.ui.components.status_view import StatusView

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: mock_status)
        view._on_load_click(None)

        assert len(view.stage_rows) == 7

    def test_load_with_no_output_dir_shows_message(self, state):
        """Loading when output_dir is empty should show an error message."""
        from pynpxpipe.ui.components.status_view import StatusView

        view = StatusView(state)
        view._on_load_click(None)

        assert "output" in view.message_pane.object.lower()

    def test_load_with_error_shows_message(self, state, tmp_path):
        """If get_status_fn raises, show the error message."""
        from pynpxpipe.ui.components.status_view import StatusView

        def failing_get_status(output_dir):
            raise FileNotFoundError("session.json not found")

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=failing_get_status)
        view._on_load_click(None)

        assert "not found" in view.message_pane.object.lower()
