"""ui/components/session_loader.py — Restore a session from an existing output directory.

Reads session.json via SessionManager.load() and populates AppState fields
(session_dir, bhv_file, output_dir, subject_config) so the user can review
the prior configuration and resume the pipeline.

The load function is injected for testability. In production it calls
SessionManager.load() and returns the session data as a dict.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from pathlib import Path

import panel as pn

from pynpxpipe.core.session import SubjectConfig
from pynpxpipe.ui.components.browsable_input import BrowsableInput
from pynpxpipe.ui.state import AppState

_SUBJECT_FIELDS = {f.name for f in fields(SubjectConfig)}


class SessionLoader:
    """Load a previously saved session from output_dir into AppState.

    Args:
        state: Shared AppState instance.
        load_session_fn: Callable(output_dir) -> dict. Returns session data
            with keys: session_dir, bhv_file, subject, etc.
            Defaults to SessionManager.load() producing a dict.
        on_session_loaded: Optional callback invoked after successful load.
    """

    def __init__(
        self,
        state: AppState,
        load_session_fn: Callable[[str], dict] | None = None,
        on_session_loaded: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        self._load_session_fn = load_session_fn or self._default_load_session
        self._on_session_loaded = on_session_loaded

        # ── Widgets ──
        self.dir_input = BrowsableInput(
            name="Output Directory",
            placeholder="Path to existing pipeline output directory",
            file_pattern="*",
            only_files=False,
        )
        self.load_btn = pn.widgets.Button(name="Load Session", button_type="success")
        self.load_btn.on_click(self._on_load_click)

        self.message_pane = pn.pane.Str("", styles={"font-size": "13px"})

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def panel(self) -> pn.viewable.Viewable:
        """Return the Panel layout for this component."""
        return pn.Column(
            pn.pane.Markdown("## Resume Session"),
            self.dir_input.panel(),
            self.load_btn,
            self.message_pane,
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_load_click(self, event) -> None:
        """Handle Load Session button click."""
        output_dir = self.dir_input.value
        if not output_dir or not output_dir.strip():
            self.message_pane.object = "Please specify an output directory."
            return

        try:
            session_data = self._load_session_fn(output_dir)
        except Exception as exc:  # noqa: BLE001
            self.message_pane.object = str(exc)
            return

        # Populate AppState from loaded session data
        self._state.output_dir = output_dir
        if "session_dir" in session_data:
            self._state.session_dir = session_data["session_dir"]
        if "bhv_file" in session_data:
            self._state.bhv_file = session_data["bhv_file"]
        if "subject" in session_data:
            raw_subject = session_data["subject"]
            if isinstance(raw_subject, SubjectConfig):
                self._state.subject_config = raw_subject
            elif isinstance(raw_subject, dict):
                # Filter to known dataclass fields so future schema additions
                # in session.json don't crash older clients.
                kwargs = {k: v for k, v in raw_subject.items() if k in _SUBJECT_FIELDS}
                try:
                    self._state.subject_config = SubjectConfig(**kwargs)
                except TypeError as exc:
                    self._state.subject_config = None
                    self.message_pane.object = (
                        f"Subject metadata in session.json is incomplete: {exc}"
                    )
                    return
            else:
                self._state.subject_config = None
                self.message_pane.object = "Subject metadata in session.json has unexpected type."
                return

        # SID S3: restore NWB filename fields (session_id + probe_plan).
        session_id = session_data.get("session_id")
        missing_nwb_fields = session_id is None or "probe_plan" not in session_data
        if isinstance(session_id, dict):
            if "experiment" in session_id:
                self._state.experiment = session_id["experiment"] or ""
            if "date" in session_id:
                self._state.recording_date = session_id["date"] or ""
        probe_plan = session_data.get("probe_plan")
        if isinstance(probe_plan, dict):
            self._state.probe_plan = dict(probe_plan)

        # Restore effective pipeline / sorting configs if previously dumped by
        # PipelineRunner. Failure to read is non-fatal — older output dirs
        # may predate the snapshotting feature.
        self._restore_effective_configs(Path(output_dir))

        if missing_nwb_fields:
            self.message_pane.object = (
                "Session loaded. Note: session.json lacks NWB filename metadata; "
                "please fill experiment / recording date / probe regions before running."
            )
        else:
            self.message_pane.object = "Session loaded successfully."

        if self._on_session_loaded:
            self._on_session_loaded()

    def _restore_effective_configs(self, output_dir: Path) -> None:
        """Reload used_pipeline.yaml / used_sorting.yaml into AppState if present.

        Read failures are silently tolerated — older output dirs may predate
        the snapshot feature, and a corrupt snapshot should not block the rest
        of the resume flow.
        """
        import contextlib

        from pynpxpipe.core.config import load_pipeline_config, load_sorting_config

        pipeline_path = output_dir / "used_pipeline.yaml"
        if pipeline_path.exists():
            with contextlib.suppress(Exception):
                self._state.pipeline_config = load_pipeline_config(pipeline_path)

        sorting_path = output_dir / "used_sorting.yaml"
        if sorting_path.exists():
            with contextlib.suppress(Exception):
                self._state.sorting_config = load_sorting_config(sorting_path)

    # ------------------------------------------------------------------
    # Default implementation (production wiring)
    # ------------------------------------------------------------------

    @staticmethod
    def _default_load_session(output_dir: str) -> dict:
        """Load session via SessionManager and return as dict."""
        import json

        session_json = Path(output_dir) / "session.json"
        if not session_json.exists():
            raise FileNotFoundError(f"session.json not found in {output_dir}")
        try:
            return json.loads(session_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt session.json: {exc}") from exc
