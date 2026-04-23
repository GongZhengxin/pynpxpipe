"""Tests for A3 — execution control, progress tracking, and log viewing.

Groups:
  A. ProgressBridge enhanced — stage_statuses tracking, timing
  B. RunPanel — Run/Stop buttons, threading, state transitions
  C. ProgressView — 7-stage progress bars, status icons
  D. LogViewer — deque buffering, structlog processor, periodic refresh
"""

from __future__ import annotations

import threading
import time

import panel as pn
import pytest

from pynpxpipe.ui.state import AppState, ProgressBridge

# ─────────────────────────────────────────────────────────────────────────────
# A. ProgressBridge enhanced — stage_statuses tracking
# ─────────────────────────────────────────────────────────────────────────────


class TestProgressBridgeStageStatuses:
    """ProgressBridge._update should maintain stage_statuses on AppState."""

    def test_update_sets_current_stage_to_running(self):
        """When a stage starts (fraction=0.0), stage_statuses marks it 'running'."""
        state = AppState()
        bridge = ProgressBridge(state)
        bridge._update("discover", 0.0)
        assert state.stage_statuses.get("discover") == "running"

    def test_update_sets_stage_completed_at_fraction_one(self):
        """When fraction reaches 1.0, stage_statuses marks it 'completed'."""
        state = AppState()
        bridge = ProgressBridge(state)
        bridge._update("discover", 1.0)
        assert state.stage_statuses.get("discover") == "completed"

    def test_update_keeps_previous_stages_completed(self):
        """Starting a new stage doesn't erase the previous stage's 'completed' status."""
        state = AppState()
        bridge = ProgressBridge(state)
        bridge._update("discover", 1.0)
        bridge._update("preprocess", 0.0)
        assert state.stage_statuses.get("discover") == "completed"
        assert state.stage_statuses.get("preprocess") == "running"

    def test_update_intermediate_fraction_keeps_running(self):
        """Fraction between 0 and 1 keeps stage as 'running'."""
        state = AppState()
        bridge = ProgressBridge(state)
        bridge._update("sort", 0.5)
        assert state.stage_statuses.get("sort") == "running"

    def test_multiple_stages_sequential(self):
        """Simulating a full pipeline run updates each stage correctly."""
        state = AppState()
        bridge = ProgressBridge(state)
        for stage in ["discover", "preprocess", "sort"]:
            bridge._update(stage, 0.0)
            bridge._update(stage, 0.5)
            bridge._update(stage, 1.0)
        assert state.stage_statuses == {
            "discover": "completed",
            "preprocess": "completed",
            "sort": "completed",
        }


# ─────────────────────────────────────────────────────────────────────────────
# B. RunPanel — execution control
# ─────────────────────────────────────────────────────────────────────────────


class TestRunPanel:
    """RunPanel component: Run/Stop buttons, threading, state transitions."""

    def test_run_panel_is_viewable(self):
        """RunPanel.panel() returns a Panel Viewable."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = AppState()
        rp = RunPanel(state)
        assert isinstance(rp.panel(), pn.viewable.Viewable)

    def test_run_panel_has_run_button(self):
        """RunPanel exposes run_btn widget."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = AppState()
        rp = RunPanel(state)
        assert isinstance(rp.run_btn, pn.widgets.Button)
        assert "Run" in rp.run_btn.name

    def test_run_panel_has_stop_button(self):
        """RunPanel exposes stop_btn widget."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = AppState()
        rp = RunPanel(state)
        assert isinstance(rp.stop_btn, pn.widgets.Button)
        assert "Stop" in rp.stop_btn.name

    def test_run_panel_stop_disabled_when_idle(self):
        """Stop button is disabled when run_status is 'idle'."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = AppState()
        rp = RunPanel(state)
        assert rp.stop_btn.disabled is True

    def test_run_panel_status_text_shows_idle(self):
        """Status text shows 'idle' initially."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = AppState()
        rp = RunPanel(state)
        assert "idle" in rp.status_text.object.lower() or "ready" in rp.status_text.object.lower()

    def test_run_sets_status_running(self, tmp_path):
        """Clicking Run with a mock pipeline_fn sets run_status to 'running'."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)
        started = threading.Event()
        proceed = threading.Event()

        def blocking_fn(st, bridge):
            started.set()
            proceed.wait(timeout=5)

        rp = RunPanel(state, pipeline_fn=blocking_fn)

        # Simulate click
        rp._on_run_click(None)
        started.wait(timeout=3)
        assert state.run_status == "running"

        proceed.set()
        if rp._thread is not None:
            rp._thread.join(timeout=3)

    def test_run_completes_sets_status_completed(self, tmp_path):
        """When pipeline_fn completes without error, status becomes 'completed'."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)

        def mock_fn(st, bridge):
            pass  # instant completion

        rp = RunPanel(state, pipeline_fn=mock_fn)
        rp._on_run_click(None)

        # Wait for background thread
        if rp._thread is not None:
            rp._thread.join(timeout=3)
        assert state.run_status == "completed"

    def test_run_completes_sets_safe_to_exit_true(self, tmp_path):
        """On success, safe_to_exit flips to True for the 'safe to close' banner."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)
        assert state.safe_to_exit is False

        rp = RunPanel(state, pipeline_fn=lambda st, br: None)
        rp._on_run_click(None)
        if rp._thread is not None:
            rp._thread.join(timeout=3)

        assert state.run_status == "completed"
        assert state.safe_to_exit is True

    def test_run_failure_keeps_safe_to_exit_false(self, tmp_path):
        """On pipeline failure, safe_to_exit remains False."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)

        def failing_fn(st, bridge):
            raise RuntimeError("boom")

        rp = RunPanel(state, pipeline_fn=failing_fn)
        rp._on_run_click(None)
        if rp._thread is not None:
            rp._thread.join(timeout=3)

        assert state.run_status == "failed"
        assert state.safe_to_exit is False

    def test_run_error_sets_status_failed(self, tmp_path):
        """When pipeline_fn raises, status becomes 'failed' with error_message."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)

        def failing_fn(st, bridge):
            raise RuntimeError("test explosion")

        rp = RunPanel(state, pipeline_fn=failing_fn)
        rp._on_run_click(None)
        if rp._thread is not None:
            rp._thread.join(timeout=3)
        assert state.run_status == "failed"
        assert "test explosion" in state.error_message

    def test_run_button_disabled_during_running(self, tmp_path):
        """Run button is disabled while pipeline is running."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)

        started = threading.Event()
        proceed = threading.Event()

        def blocking_fn(st, bridge):
            started.set()
            proceed.wait(timeout=5)

        rp = RunPanel(state, pipeline_fn=blocking_fn)
        rp._on_run_click(None)
        started.wait(timeout=3)
        assert rp.run_btn.disabled is True

        proceed.set()
        if rp._thread is not None:
            rp._thread.join(timeout=3)

    def test_stop_sets_interrupt_flag(self, tmp_path):
        """Clicking Stop sets the interrupt event."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)

        started = threading.Event()

        def blocking_fn(st, bridge):
            started.set()
            time.sleep(5)

        rp = RunPanel(state, pipeline_fn=blocking_fn)
        rp._on_run_click(None)
        started.wait(timeout=3)
        rp._on_stop_click(None)
        assert rp._interrupt.is_set()

        # cleanup
        if rp._thread is not None:
            rp._thread.join(timeout=3)

    def test_double_run_ignored(self, tmp_path):
        """Clicking Run while already running does nothing (no second thread)."""
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)

        started = threading.Event()
        proceed = threading.Event()

        def blocking_fn(st, bridge):
            started.set()
            proceed.wait(timeout=5)

        rp = RunPanel(state, pipeline_fn=blocking_fn)
        rp._on_run_click(None)
        started.wait(timeout=3)
        first_thread = rp._thread
        rp._on_run_click(None)  # second click
        assert rp._thread is first_thread  # same thread, no new one

        proceed.set()
        if rp._thread is not None:
            rp._thread.join(timeout=3)


# ─────────────────────────────────────────────────────────────────────────────
# B'. RunPanel — SID S3 pre-execution validation
# ─────────────────────────────────────────────────────────────────────────────


def _fully_populated_state(tmp_path) -> AppState:
    """Return an AppState that passes all pre-exec null-checks."""
    from pynpxpipe.core.session import SubjectConfig

    state = AppState()
    session_dir = tmp_path / "run_g0"
    session_dir.mkdir()
    state.session_dir = session_dir
    state.output_dir = tmp_path / "out"
    state.subject_config = SubjectConfig(
        subject_id="MaoDan",
        description="",
        species="Macaca mulatta",
        sex="M",
        age="P4Y",
        weight="12kg",
    )
    state.experiment = "nsd1w"
    state.recording_date = "251024"
    state.probe_plan = {"imec0": "V4"}
    return state


class TestRunPanelPreExecValidation:
    """Null-check gate: the run thread must not start when any NWB field is blank."""

    def test_blocks_when_experiment_blank(self, tmp_path):
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)
        state.experiment = ""
        called = []
        rp = RunPanel(state, pipeline_fn=lambda st, br: called.append(True))
        rp._on_run_click(None)
        assert rp._thread is None
        assert rp.validation_alert.visible is True
        assert "Experiment" in rp.validation_alert.object
        assert state.run_status == "idle"
        assert called == []

    def test_blocks_when_recording_date_blank(self, tmp_path):
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)
        state.recording_date = ""
        rp = RunPanel(state, pipeline_fn=lambda st, br: None)
        rp._on_run_click(None)
        assert rp._thread is None
        assert "Recording date" in rp.validation_alert.object

    def test_blocks_when_probe_plan_empty_area(self, tmp_path):
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)
        state.probe_plan = {"imec0": ""}
        rp = RunPanel(state, pipeline_fn=lambda st, br: None)
        rp._on_run_click(None)
        assert rp._thread is None
        assert "probe" in rp.validation_alert.object.lower()

    def test_blocks_when_subject_missing(self, tmp_path):
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)
        state.subject_config = None
        rp = RunPanel(state, pipeline_fn=lambda st, br: None)
        rp._on_run_click(None)
        assert rp._thread is None
        assert "Subject" in rp.validation_alert.object

    def test_passes_when_all_fields_populated(self, tmp_path):
        from pynpxpipe.ui.components.run_panel import RunPanel

        state = _fully_populated_state(tmp_path)
        ran = threading.Event()

        def fn(st, br):
            ran.set()

        rp = RunPanel(state, pipeline_fn=fn)
        rp._on_run_click(None)
        if rp._thread is not None:
            rp._thread.join(timeout=3)
        assert ran.is_set()
        assert rp.validation_alert.visible is False


# ─────────────────────────────────────────────────────────────────────────────
# C. ProgressView — stage progress visualization
# ─────────────────────────────────────────────────────────────────────────────


class TestProgressView:
    """ProgressView: 7-stage progress bars bound to AppState."""

    def test_progress_view_is_viewable(self):
        """ProgressView.panel() returns a Panel Viewable."""
        from pynpxpipe.ui.components.progress_view import ProgressView

        state = AppState()
        pv = ProgressView(state)
        assert isinstance(pv.panel(), pn.viewable.Viewable)

    def test_progress_view_has_seven_rows(self):
        """ProgressView contains one row per STAGE_ORDER entry."""
        from pynpxpipe.pipelines.runner import STAGE_ORDER
        from pynpxpipe.ui.components.progress_view import ProgressView

        state = AppState()
        pv = ProgressView(state)
        assert len(pv.stage_rows) == len(STAGE_ORDER)

    def test_progress_view_stage_names_match_order(self):
        """Row labels match STAGE_ORDER names."""
        from pynpxpipe.pipelines.runner import STAGE_ORDER
        from pynpxpipe.ui.components.progress_view import ProgressView

        state = AppState()
        pv = ProgressView(state)
        assert list(pv.stage_rows.keys()) == STAGE_ORDER

    def test_progress_view_updates_on_stage_status_change(self):
        """Changing stage_statuses triggers visual update."""
        from pynpxpipe.ui.components.progress_view import ProgressView

        state = AppState()
        pv = ProgressView(state)
        state.stage_statuses = {"discover": "completed", "preprocess": "running"}
        # After update, discover row should show completed indicator
        row_info = pv.get_row_info("discover")
        assert row_info["status"] == "completed"

    def test_progress_view_default_all_pending(self):
        """Initially all stages show 'pending' status."""
        from pynpxpipe.pipelines.runner import STAGE_ORDER
        from pynpxpipe.ui.components.progress_view import ProgressView

        state = AppState()
        pv = ProgressView(state)
        for stage in STAGE_ORDER:
            assert pv.get_row_info(stage)["status"] == "pending"

    def test_progress_view_running_stage_shows_progress_bar(self):
        """A running stage shows a non-zero progress bar when fraction > 0."""
        from pynpxpipe.ui.components.progress_view import ProgressView

        state = AppState()
        pv = ProgressView(state)
        state.stage_statuses = {"preprocess": "running"}
        state.current_stage = "preprocess"
        state.stage_progress = 0.5
        pv.refresh()
        row_info = pv.get_row_info("preprocess")
        assert row_info["progress"] == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# D. LogViewer — real-time log display
# ─────────────────────────────────────────────────────────────────────────────


class TestLogViewer:
    """LogViewer: deque-buffered, structlog-compatible log display."""

    def test_log_viewer_is_viewable(self):
        """LogViewer.panel() returns a Panel Viewable."""
        from pynpxpipe.ui.components.log_viewer import LogViewer

        lv = LogViewer()
        assert isinstance(lv.panel(), pn.viewable.Viewable)

    def test_log_viewer_append_message(self):
        """append() adds a line to the internal buffer."""
        from pynpxpipe.ui.components.log_viewer import LogViewer

        lv = LogViewer()
        lv.append("INFO: test message")
        assert len(lv.buffer) == 1
        assert "test message" in lv.buffer[0]

    def test_log_viewer_buffer_max_size(self):
        """Buffer respects maxlen; oldest entries are evicted."""
        from pynpxpipe.ui.components.log_viewer import LogViewer

        lv = LogViewer(maxlen=5)
        for i in range(10):
            lv.append(f"line {i}")
        assert len(lv.buffer) == 5
        assert "line 5" in lv.buffer[0]

    def test_log_viewer_refresh_updates_display(self):
        """refresh() updates the display pane content."""
        from pynpxpipe.ui.components.log_viewer import LogViewer

        lv = LogViewer()
        lv.append("hello world")
        lv.refresh()
        assert "hello world" in lv.display.object

    def test_log_viewer_structlog_processor(self):
        """get_processor() returns a callable that appends formatted log entries."""
        from pynpxpipe.ui.components.log_viewer import LogViewer

        lv = LogViewer()
        processor = lv.get_processor()
        # structlog processors take (logger, method_name, event_dict)
        event_dict = {"event": "stage started", "stage": "discover", "level": "info"}
        processor(None, "info", event_dict)
        assert len(lv.buffer) == 1

    def test_log_viewer_empty_buffer_shows_placeholder(self):
        """When buffer is empty, display shows a placeholder message."""
        from pynpxpipe.ui.components.log_viewer import LogViewer

        lv = LogViewer()
        lv.refresh()
        # Should contain some placeholder text
        assert lv.display.object != ""
