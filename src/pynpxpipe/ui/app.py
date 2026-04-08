"""ui/app.py — Entry point for the pynpxpipe Panel Web UI.

A1 spike test: button + progress bar + mock pipeline.
Validates the threading + ProgressBridge + param-watch pathway.

Usage:
    pynpxpipe-ui
    panel serve src/pynpxpipe/ui/app.py --show
"""

from __future__ import annotations

import threading
import time

import panel as pn
import param

from pynpxpipe.ui.state import AppState, ProgressBridge

pn.extension()

_MOCK_STAGES = [
    ("discover", 0.0),
    ("discover", 0.5),
    ("discover", 1.0),
    ("preprocess", 0.0),
    ("preprocess", 0.5),
    ("preprocess", 1.0),
    ("sort", 0.0),
    ("sort", 1.0),
]


def _run_mock_pipeline(bridge: ProgressBridge, state: AppState) -> None:
    """Mock pipeline that simulates stage-by-stage progress in a background thread."""
    try:
        for stage, frac in _MOCK_STAGES:
            time.sleep(0.3)
            bridge.callback(stage, frac)
        state.run_status = "completed"
    except Exception as exc:
        state.error_message = str(exc)
        state.run_status = "failed"


def create_app() -> pn.viewable.Viewable:
    """Create and return the Panel app layout (spike prototype)."""
    state = AppState()
    bridge = ProgressBridge(state)

    # ── Widgets ──
    run_button = pn.widgets.Button(name="Run", button_type="primary")
    progress = pn.indicators.Progress(
        name="stage_progress",
        value=0,
        max=100,
        active=False,
        width=400,
    )
    status_text = pn.pane.Str("Status: idle", styles={"font-size": "14px"})
    stage_text = pn.pane.Str("", styles={"font-size": "12px", "color": "gray"})

    # ── Bind state → widgets ──
    @param.depends(state.param.stage_progress, watch=True)
    def _on_progress(progress_val):
        progress.value = int(progress_val * 100)
        progress.active = state.run_status == "running"

    @param.depends(state.param.run_status, watch=True)
    def _on_status(status):
        progress.active = status == "running"
        status_text.object = f"Status: {status}"

    @param.depends(state.param.current_stage, watch=True)
    def _on_stage(stage):
        if stage:
            stage_text.object = f"Stage: {stage}  ({int(state.stage_progress * 100)}%)"

    # ── Button click ──
    def _on_run_click(event):
        if state.run_status == "running":
            return
        state.run_status = "running"
        state.stage_progress = 0.0
        state.current_stage = ""
        t = threading.Thread(
            target=_run_mock_pipeline,
            args=(bridge, state),
            daemon=True,
        )
        t.start()

    run_button.on_click(_on_run_click)

    # ── Layout ──
    layout = pn.Column(
        pn.pane.Markdown("## pynpxpipe — Pipeline UI (spike)"),
        pn.Row(run_button),
        progress,
        status_text,
        stage_text,
        sizing_mode="stretch_width",
        max_width=600,
    )
    return layout


def main() -> None:
    """Entry point for `pynpxpipe-ui` script."""
    app = create_app()
    pn.serve(app, show=True, title="pynpxpipe UI")
