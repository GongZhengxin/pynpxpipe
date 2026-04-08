"""ui/components/session_form.py — Session path configuration panel."""

from __future__ import annotations

from pathlib import Path

import panel as pn

from pynpxpipe.ui.state import AppState


class SessionForm:
    """Three path inputs for session_dir, bhv_file, and output_dir."""

    def __init__(self, state: AppState) -> None:
        self._state = state
        self.validation_message: str = ""

        self.session_dir_input = pn.widgets.TextInput(
            name="Session Directory",
            placeholder="/path/to/session_root",
        )
        self.bhv_file_input = pn.widgets.TextInput(
            name="BHV2 File",
            placeholder="/path/to/recording.bhv2",
        )
        self.output_dir_input = pn.widgets.TextInput(
            name="Output Directory",
            placeholder="/path/to/output",
        )

        self.session_dir_input.param.watch(self._on_session_dir, "value")
        self.bhv_file_input.param.watch(self._on_bhv_file, "value")
        self.output_dir_input.param.watch(self._on_output_dir, "value")

    # ── Watchers ──

    def _on_session_dir(self, event) -> None:
        self._state.session_dir = Path(event.new) if event.new else None

    def _on_bhv_file(self, event) -> None:
        val: str = event.new or ""
        if val and not val.endswith(".bhv2"):
            self.validation_message = "BHV2 file must end with .bhv2"
        else:
            self.validation_message = ""
            self._state.bhv_file = Path(val) if val else None

    def _on_output_dir(self, event) -> None:
        self._state.output_dir = Path(event.new) if event.new else None

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("### Session Paths"),
            self.session_dir_input,
            self.bhv_file_input,
            self.output_dir_input,
        )
