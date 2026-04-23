"""ui/components/progress_view.py — Stage progress visualization.

Renders a 7-row progress display (one per pipeline stage). Each row shows:
stage name, progress bar, percentage, and status indicator.

Binds to AppState.stage_statuses, .current_stage, and .stage_progress for
automatic updates via param.watch.
"""

from __future__ import annotations

import panel as pn

from pynpxpipe.pipelines.constants import STAGE_ORDER
from pynpxpipe.ui.state import AppState

_STATUS_ICONS = {
    "pending": "-",
    "running": "...",
    "completed": "done",
    "failed": "ERR",
}


class ProgressView:
    """7-stage progress bar display bound to AppState.

    Args:
        state: Shared AppState instance.
    """

    def __init__(self, state: AppState) -> None:
        self._state = state
        self.stage_rows: dict[str, dict] = {}

        for stage_name in STAGE_ORDER:
            self.stage_rows[stage_name] = {
                "label": pn.pane.Str(
                    f"{stage_name:<14}", styles={"font-family": "monospace", "font-size": "13px"}
                ),
                "bar": pn.indicators.Progress(value=0, max=100, width=200, active=False),
                "pct": pn.pane.Str("  0%", styles={"font-family": "monospace", "width": "40px"}),
                "icon": pn.pane.Str(
                    _STATUS_ICONS["pending"],
                    styles={"font-family": "monospace", "width": "40px"},
                ),
            }

        # Watch state changes
        state.param.watch(self._on_statuses_change, ["stage_statuses"])
        state.param.watch(self._on_progress_change, ["stage_progress", "current_stage"])

    def get_row_info(self, stage_name: str) -> dict:
        """Return current status and progress for a stage (for testing).

        Args:
            stage_name: Name from STAGE_ORDER.

        Returns:
            Dict with 'status' and 'progress' keys.
        """
        statuses = self._state.stage_statuses
        status = statuses.get(stage_name, "pending")

        progress = 0.0
        if status == "completed":
            progress = 1.0
        elif status == "running" and self._state.current_stage == stage_name:
            progress = self._state.stage_progress

        return {"status": status, "progress": progress}

    def refresh(self) -> None:
        """Force refresh all row widgets from current state."""
        for stage_name, widgets in self.stage_rows.items():
            info = self.get_row_info(stage_name)
            status = info["status"]
            progress = info["progress"]

            pct_int = int(progress * 100)
            widgets["bar"].value = pct_int
            widgets["bar"].active = status == "running"
            widgets["pct"].object = f"{pct_int:>3}%"
            widgets["icon"].object = _STATUS_ICONS.get(status, "-")

    def _on_statuses_change(self, event) -> None:
        self.refresh()

    def _on_progress_change(self, event) -> None:
        self.refresh()

    def panel(self) -> pn.viewable.Viewable:
        """Return the Panel layout."""
        rows = []
        for stage_name in STAGE_ORDER:
            w = self.stage_rows[stage_name]
            rows.append(pn.Row(w["label"], w["bar"], w["pct"], w["icon"]))

        return pn.Column(*rows, sizing_mode="stretch_width")
