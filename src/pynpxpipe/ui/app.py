"""ui/app.py — Entry point for the pynpxpipe Panel Web UI.

A5 production layout: FastListTemplate with sidebar navigation,
three content sections (Configure, Execute, Review), and error banner.

Usage:
    pynpxpipe-ui
    panel serve src/pynpxpipe/ui/app.py --show
"""

from __future__ import annotations

import panel as pn

from pynpxpipe.ui.components.log_viewer import LogViewer
from pynpxpipe.ui.components.pipeline_form import PipelineForm
from pynpxpipe.ui.components.progress_view import ProgressView
from pynpxpipe.ui.components.run_panel import RunPanel
from pynpxpipe.ui.components.session_form import SessionForm
from pynpxpipe.ui.components.session_loader import SessionLoader
from pynpxpipe.ui.components.sorting_form import SortingForm
from pynpxpipe.ui.components.stage_selector import StageSelector
from pynpxpipe.ui.components.status_view import StatusView
from pynpxpipe.ui.components.subject_form import SubjectForm
from pynpxpipe.ui.state import AppState

pn.extension()


def create_app() -> pn.viewable.Viewable:
    """Create and return the Panel app layout.

    Returns a FastListTemplate with sidebar navigation and three content
    sections: Configure, Execute, Review.  The returned template exposes
    internal state via private attributes for testability:

    - ``_pynpx_sections``: dict of section name -> Column
    - ``_pynpx_switch(name)``: callable to switch visible section
    - ``_pynpx_error_banner``: the error alert pane
    - ``_pynpx_state``: the AppState instance
    """
    state = AppState()

    # ── Components ──
    session_form = SessionForm(state)
    subject_form = SubjectForm(state)
    pipeline_form = PipelineForm(state)
    sorting_form = SortingForm(state)
    stage_selector = StageSelector(state)

    run_panel = RunPanel(state)
    progress_view = ProgressView(state)
    log_viewer = LogViewer()

    session_loader = SessionLoader(state)
    status_view = StatusView(state)

    # ── Sections ──
    configure_section = pn.Column(
        session_form.panel(),
        subject_form.panel(),
        pipeline_form.panel(),
        sorting_form.panel(),
        stage_selector.panel(),
        sizing_mode="stretch_width",
    )

    execute_section = pn.Column(
        run_panel.panel(),
        progress_view.panel(),
        log_viewer.panel(),
        sizing_mode="stretch_width",
        visible=False,
    )

    review_section = pn.Column(
        session_loader.panel(),
        status_view.panel(),
        sizing_mode="stretch_width",
        visible=False,
    )

    sections = {
        "configure": configure_section,
        "execute": execute_section,
        "review": review_section,
    }

    # ── Section switching ──
    def switch_section(name: str) -> None:
        for key, col in sections.items():
            col.visible = key == name

    # ── Error banner ──
    error_banner = pn.pane.Alert(
        "",
        alert_type="danger",
        visible=False,
        sizing_mode="stretch_width",
    )

    def _on_error_change(event) -> None:
        msg = event.new
        if msg:
            error_banner.object = msg
            error_banner.visible = True
        else:
            error_banner.visible = False

    state.param.watch(_on_error_change, ["error_message"])

    # ── Sidebar navigation ──
    nav_buttons = {}
    for label in ("Configure", "Execute", "Review"):
        btn = pn.widgets.Button(
            name=label,
            button_type="primary" if label == "Configure" else "default",
            width=150,
        )
        nav_buttons[label.lower()] = btn

    def _make_nav_handler(name: str):
        def handler(event):
            switch_section(name)
            for key, btn in nav_buttons.items():
                btn.button_type = "primary" if key == name else "default"

        return handler

    for name, btn in nav_buttons.items():
        btn.on_click(_make_nav_handler(name))

    status_indicator = pn.pane.Str(
        "Status: idle",
        styles={"font-size": "12px", "color": "#8b949e", "margin-top": "16px"},
    )

    def _on_run_status_change(event) -> None:
        status_indicator.object = f"Status: {event.new}"

    state.param.watch(_on_run_status_change, ["run_status"])

    # ── Template ──
    template = pn.template.FastListTemplate(
        title="pynpxpipe",
        theme="dark",
        accent_base_color="#1f6feb",
        sidebar=[
            *nav_buttons.values(),
            status_indicator,
        ],
        main=[
            error_banner,
            configure_section,
            execute_section,
            review_section,
        ],
    )

    # ── Expose internals for testing ──
    template._pynpx_sections = sections
    template._pynpx_switch = switch_section
    template._pynpx_error_banner = error_banner
    template._pynpx_state = state

    return template


def main() -> None:
    """Entry point for `pynpxpipe-ui` script."""
    app = create_app()
    app.show(title="pynpxpipe UI")
