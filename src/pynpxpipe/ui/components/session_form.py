"""ui/components/session_form.py — Session path configuration panel.

Supports two modes:
- Simple mode (default): single data_dir auto-discovers session_dir + bhv_file.
- Advanced mode: manual entry of session_dir, bhv_file, and output_dir.
"""

from __future__ import annotations

import re
from pathlib import Path

import panel as pn

from pynpxpipe.ui.components.browsable_input import BrowsableInput
from pynpxpipe.ui.state import AppState


def _discover_paths(data_dir: Path) -> tuple[Path | None, Path | None, str]:
    """Discover gate directory and BHV2 file in *data_dir*.

    Returns:
        (gate_dir, bhv_file, status_message)
    """
    if not data_dir.exists():
        return None, None, f"Path does not exist: {data_dir}"

    gate_dirs = sorted(p for p in data_dir.iterdir() if p.is_dir() and re.search(r"_g\d+$", p.name))
    bhv_files = sorted(data_dir.glob("*.bhv2"))

    errors: list[str] = []
    if not gate_dirs:
        errors.append("No *_g[0-9] gate directory found")
    if not bhv_files:
        errors.append("No *.bhv2 file found")

    if errors:
        return (
            gate_dirs[0] if gate_dirs else None,
            bhv_files[0] if bhv_files else None,
            " | ".join(errors),
        )

    return (
        gate_dirs[0],
        bhv_files[0],
        f"Found: {gate_dirs[0].name} | {bhv_files[0].name}",
    )


class SessionForm:
    """Session path inputs with simple/advanced mode toggle.

    Simple mode (default): single data_dir BrowsableInput with auto-discovery.
    Advanced mode: three BrowsableInputs for session_dir, bhv_file, output_dir.
    """

    def __init__(self, state: AppState) -> None:
        self._state = state
        self.validation_message: str = ""
        self.discovery_status: str = ""

        # ── Mode toggle ──
        self.advanced_toggle = pn.widgets.Toggle(name="Advanced Mode", value=False)

        # ── Simple mode widget ──
        self.data_dir_input = BrowsableInput(
            name="Data Directory",
            placeholder="/path/to/experiment_folder",
            file_pattern="*",
            only_files=False,
        )

        # ── Advanced mode widgets (hidden by default) ──
        self.session_dir_input = BrowsableInput(
            name="Session Directory",
            placeholder="/path/to/session_root",
            file_pattern="*",
            only_files=False,
        )
        self.bhv_file_input = BrowsableInput(
            name="BHV2 File",
            placeholder="/path/to/recording.bhv2",
            file_pattern="*.bhv2",
            only_files=True,
        )

        # ── Shared widget ──
        self.output_dir_input = BrowsableInput(
            name="Output Directory",
            placeholder="/path/to/output",
            file_pattern="*",
            only_files=False,
        )

        # ── NWB filename fields (SID S3) ──
        self.experiment_input = pn.widgets.TextInput(
            name="Experiment",
            placeholder="e.g. nsd1w",
            value=state.experiment,
        )
        self.recording_date_input = pn.widgets.TextInput(
            name="Recording Date (YYMMDD)",
            placeholder="251024",
            value=state.recording_date,
        )
        self.detect_date_btn = pn.widgets.Button(
            name="Detect Date",
            button_type="default",
        )
        self.detect_date_alert = pn.pane.Alert(
            "", alert_type="warning", visible=False, sizing_mode="stretch_width"
        )

        # Hide advanced inputs initially
        self.session_dir_input.visible = False
        self.bhv_file_input.visible = False

        # ── Watchers ──
        self.advanced_toggle.param.watch(self._on_mode_change, "value")
        self.data_dir_input.text_input.param.watch(self._on_data_dir, "value")
        self.session_dir_input.text_input.param.watch(self._on_session_dir, "value")
        self.bhv_file_input.text_input.param.watch(self._on_bhv_file, "value")
        self.output_dir_input.text_input.param.watch(self._on_output_dir, "value")
        self.experiment_input.param.watch(self._on_experiment, "value")
        self.recording_date_input.param.watch(self._on_recording_date, "value")
        self.detect_date_btn.on_click(self._on_detect_date_click)
        state.param.watch(self._on_state_experiment, "experiment")
        state.param.watch(self._on_state_recording_date, "recording_date")

    # ── Mode switching ──

    def _on_mode_change(self, event) -> None:
        advanced = event.new
        self.data_dir_input.visible = not advanced
        self.session_dir_input.visible = advanced
        self.bhv_file_input.visible = advanced

        if advanced:
            # Simple → Advanced: fill advanced fields with discovered values
            if self._state.session_dir is not None:
                self.session_dir_input.value = str(self._state.session_dir)
            if self._state.bhv_file is not None:
                self.bhv_file_input.value = str(self._state.bhv_file)
        else:
            # Advanced → Simple: infer data_dir from session_dir parent
            if self.session_dir_input.value:
                parent = str(Path(self.session_dir_input.value).parent)
                self.data_dir_input.value = parent

    # ── Simple mode: auto-discovery ──

    def _on_data_dir(self, event) -> None:
        val: str = event.new or ""
        if not val:
            self.discovery_status = ""
            self._state.session_dir = None
            self._state.bhv_file = None
            return

        data_dir = Path(val)
        gate_dir, bhv_file, status = _discover_paths(data_dir)
        self.discovery_status = status

        self._state.session_dir = gate_dir
        self._state.bhv_file = bhv_file

    # ── Advanced mode watchers ──

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

    # ── NWB filename fields (SID S3) ──

    def _on_experiment(self, event) -> None:
        self._state.experiment = event.new or ""

    def _on_recording_date(self, event) -> None:
        self._state.recording_date = event.new or ""

    def _on_state_experiment(self, event) -> None:
        if self.experiment_input.value != event.new:
            self.experiment_input.value = event.new

    def _on_state_recording_date(self, event) -> None:
        if self.recording_date_input.value != event.new:
            self.recording_date_input.value = event.new

    def _find_ap_meta(self) -> Path | None:
        """Return the first *.ap.meta under session_dir, or None."""
        if self._state.session_dir is None:
            return None
        root = Path(self._state.session_dir)
        if not root.exists():
            return None
        metas = sorted(root.rglob("*.ap.meta"))
        return metas[0] if metas else None

    def _on_detect_date_click(self, event) -> None:
        from pynpxpipe.io.spikeglx import SpikeGLXLoader

        meta_path = self._find_ap_meta()
        if meta_path is None:
            self.detect_date_alert.object = (
                "No *.ap.meta found under the session directory. "
                "Select a valid data directory first."
            )
            self.detect_date_alert.alert_type = "warning"
            self.detect_date_alert.visible = True
            return
        try:
            yymmdd = SpikeGLXLoader.read_recording_date(meta_path)
        except Exception as exc:  # noqa: BLE001
            self.detect_date_alert.object = f"Failed to read recording date: {exc}"
            self.detect_date_alert.alert_type = "danger"
            self.detect_date_alert.visible = True
            return
        self._state.recording_date = yymmdd
        self.recording_date_input.value = yymmdd
        self.detect_date_alert.object = f"Detected recording date: {yymmdd}"
        self.detect_date_alert.alert_type = "success"
        self.detect_date_alert.visible = True

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("### Session Paths"),
            self.advanced_toggle,
            self.data_dir_input.panel(),
            self.session_dir_input.panel(),
            self.bhv_file_input.panel(),
            self.output_dir_input.panel(),
            self.experiment_input,
            pn.Row(self.recording_date_input, self.detect_date_btn),
            self.detect_date_alert,
        )
