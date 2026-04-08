"""ui/components/run_panel.py — Execution control panel.

Provides Run/Stop buttons, status text, and threading for pipeline execution.
The actual pipeline function is injected (for testability). In production it
calls SessionManager + PipelineRunner; tests inject a mock callable.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import panel as pn

from pynpxpipe.ui.state import AppState, ProgressBridge


class RunPanel:
    """Execution control: Run, Stop, status display.

    Args:
        state: Shared AppState instance.
        pipeline_fn: Callable(state, bridge) executed in a background thread.
            If None, defaults to a no-op (useful for layout-only testing).
    """

    def __init__(
        self,
        state: AppState,
        pipeline_fn: Callable[[AppState, ProgressBridge], None] | None = None,
    ) -> None:
        self._state = state
        self._pipeline_fn = pipeline_fn or (lambda st, br: None)
        self._bridge = ProgressBridge(state)
        self._thread: threading.Thread | None = None
        self._interrupt = threading.Event()

        # ── Widgets ──
        self.run_btn = pn.widgets.Button(name="Run", button_type="primary")
        self.stop_btn = pn.widgets.Button(name="Stop", button_type="danger", disabled=True)
        self.status_text = pn.pane.Str("Status: idle", styles={"font-size": "14px"})

        # ── Wire events ──
        self.run_btn.on_click(self._on_run_click)
        self.stop_btn.on_click(self._on_stop_click)

        # Watch run_status for button enable/disable and status text
        state.param.watch(self._on_status_change, ["run_status"])

    def _on_run_click(self, event) -> None:
        """Start pipeline in background thread (ignored if already running)."""
        if self._state.run_status == "running":
            return

        self._state.run_status = "running"
        self._state.stage_progress = 0.0
        self._state.current_stage = ""
        self._state.error_message = ""
        self._state.stage_statuses = {}
        self._interrupt.clear()

        self._thread = threading.Thread(target=self._run_wrapper, daemon=True)
        self._thread.start()

    def _on_stop_click(self, event) -> None:
        """Set interrupt flag to signal the pipeline to stop."""
        self._interrupt.set()

    def _run_wrapper(self) -> None:
        """Execute pipeline_fn and update state on completion or failure."""
        try:
            self._pipeline_fn(self._state, self._bridge)
            if not self._interrupt.is_set():
                self._state.run_status = "completed"
            else:
                self._state.run_status = "failed"
                self._state.error_message = "Interrupted by user"
        except Exception as exc:  # noqa: BLE001
            self._state.error_message = str(exc)
            self._state.run_status = "failed"

    def _on_status_change(self, event) -> None:
        """Update button states and status text when run_status changes."""
        status = event.new
        self.run_btn.disabled = status == "running"
        self.stop_btn.disabled = status != "running"

        labels = {
            "idle": "Status: idle",
            "running": "Status: running",
            "completed": "Status: completed",
            "failed": f"Status: failed — {self._state.error_message}",
        }
        self.status_text.object = labels.get(status, f"Status: {status}")

    def panel(self) -> pn.viewable.Viewable:
        """Return the Panel layout for this component."""
        return pn.Column(
            pn.Row(self.run_btn, self.stop_btn),
            self.status_text,
        )
