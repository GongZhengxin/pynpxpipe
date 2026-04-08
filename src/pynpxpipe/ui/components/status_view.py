"""ui/components/status_view.py — Stage status display and reset.

Shows the checkpoint-based completion status of all 7 pipeline stages.
Each stage row includes a Reset button that clears the checkpoint so the
stage will re-run on the next pipeline invocation.

Dependencies are injected (get_status_fn, clear_stage_fn) for testability.
In production, these call PipelineRunner.get_status() and
CheckpointManager.clear() respectively.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import panel as pn

from pynpxpipe.pipelines.runner import STAGE_ORDER
from pynpxpipe.ui.state import AppState

# Status → display style mapping
_STATUS_STYLES: dict[str, str] = {
    "completed": "color: green; font-weight: bold",
    "failed": "color: red; font-weight: bold",
    "pending": "color: gray",
}


class StatusView:
    """Displays pipeline stage status and provides per-stage reset.

    Args:
        state: Shared AppState instance.
        get_status_fn: Callable(output_dir) -> dict[str, str]. Defaults to
            using PipelineRunner.get_status() via SessionManager.load().
        clear_stage_fn: Callable(output_dir, stage_name) -> None. Defaults to
            CheckpointManager.clear() for both stage-level and probe-level checkpoints.
    """

    def __init__(
        self,
        state: AppState,
        get_status_fn: Callable[[str], dict[str, str]] | None = None,
        clear_stage_fn: Callable[[str, str], None] | None = None,
    ) -> None:
        self._state = state
        self._get_status_fn = get_status_fn or self._default_get_status
        self._clear_stage_fn = clear_stage_fn or self._default_clear_stage

        # ── Widgets ──
        self.message_pane = pn.pane.Str(
            "Set output directory and click Load to view status.",
            styles={"font-size": "13px"},
        )
        self.load_btn = pn.widgets.Button(name="Load Status", button_type="primary")
        self.load_btn.on_click(self._on_load_click)

        # stage_rows: {stage_name: {"status_text": Str, "reset_btn": Button, "row": Row}}
        self.stage_rows: dict[str, dict] = {}
        self._table_container = pn.Column()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_status(self) -> None:
        """Fetch status from output_dir and rebuild the stage table."""
        output_dir = self._state.output_dir
        if not output_dir:
            self.message_pane.object = "No output directory set."
            return

        try:
            statuses = self._get_status_fn(output_dir)
        except Exception as exc:  # noqa: BLE001
            self.message_pane.object = str(exc).lower() if str(exc) == str(exc) else str(exc)
            # Preserve original case but ensure message is accessible
            self.message_pane.object = str(exc)
            return

        self.message_pane.object = ""
        self._build_table(statuses)

    def panel(self) -> pn.viewable.Viewable:
        """Return the Panel layout for this component."""
        return pn.Column(
            pn.pane.Markdown("## Pipeline Status"),
            pn.Row(self.load_btn),
            self.message_pane,
            self._table_container,
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_load_click(self, event) -> None:
        """Handle Load button click."""
        self.load_status()

    def _on_reset_click(self, stage_name: str) -> None:
        """Reset a stage's checkpoint and refresh the status display."""
        output_dir = self._state.output_dir
        if not output_dir:
            return
        self._clear_stage_fn(output_dir, stage_name)
        self.load_status()

    # ------------------------------------------------------------------
    # Table building
    # ------------------------------------------------------------------

    def _build_table(self, statuses: dict[str, str]) -> None:
        """Build the stage status table from a status dict."""
        self.stage_rows.clear()
        rows = []

        for stage_name in STAGE_ORDER:
            status = statuses.get(stage_name, "pending")
            style = _STATUS_STYLES.get(
                status.split()[0] if " " in status else status,
                "color: orange",
            )

            status_text = pn.pane.HTML(
                f'<span style="{style}">{status}</span>',
                styles={"min-width": "200px"},
            )
            reset_btn = pn.widgets.Button(
                name="Reset",
                button_type="warning",
                width=80,
            )
            # Bind reset click to this stage
            reset_btn.on_click(lambda event, sn=stage_name: self._on_reset_click(sn))

            stage_label = pn.pane.Str(
                stage_name,
                styles={"font-weight": "bold", "min-width": "120px"},
            )

            row = pn.Row(stage_label, status_text, reset_btn)
            self.stage_rows[stage_name] = {
                "status_text": status_text,
                "reset_btn": reset_btn,
                "row": row,
            }
            rows.append(row)

        self._table_container.clear()
        self._table_container.extend(rows)

    # ------------------------------------------------------------------
    # Default implementations (production wiring)
    # ------------------------------------------------------------------

    @staticmethod
    def _default_get_status(output_dir: str) -> dict[str, str]:
        """Load session and return PipelineRunner.get_status()."""
        from pynpxpipe.core.config import load_pipeline_config, load_sorting_config
        from pynpxpipe.core.session import SessionManager
        from pynpxpipe.pipelines.runner import PipelineRunner

        session = SessionManager.load(Path(output_dir))
        pipeline_config = load_pipeline_config()
        sorting_config = load_sorting_config()
        runner = PipelineRunner(session, pipeline_config, sorting_config)
        return runner.get_status()

    @staticmethod
    def _default_clear_stage(output_dir: str, stage_name: str) -> None:
        """Clear stage-level and all probe-level checkpoints."""
        from pynpxpipe.core.checkpoint import CheckpointManager

        cm = CheckpointManager(Path(output_dir))
        cm.clear(stage_name)
        # Also clear probe-level checkpoints by scanning for matching files
        cp_dir = Path(output_dir) / "checkpoints"
        if cp_dir.exists():
            for f in cp_dir.glob(f"{stage_name}_*.json"):
                f.unlink(missing_ok=True)
