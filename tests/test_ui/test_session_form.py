"""Tests for ui/components/session_form.py — SID S3 NWB filename fields.

Groups:
  A. experiment input  — widget present, bound to state.experiment
  B. recording_date input + Detect Date button — triggers SpikeGLXLoader.read_recording_date
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import panel as pn

from pynpxpipe.ui.state import AppState


def _write_meta(path: Path, create_time: str = "2025-10-24T14:30:00") -> None:
    path.write_text(
        f"fileCreateTime={create_time}\nimSampRate=30000.0\nnSavedChans=385\n",
        encoding="utf-8",
    )


class TestSessionFormNWBFields:
    def test_session_form_has_experiment_input(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        assert isinstance(form.experiment_input, pn.widgets.TextInput)

    def test_experiment_input_updates_state(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        form.experiment_input.value = "nsd1w"
        assert state.experiment == "nsd1w"

    def test_session_form_has_recording_date_input(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        assert isinstance(form.recording_date_input, pn.widgets.TextInput)

    def test_recording_date_input_updates_state(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        form.recording_date_input.value = "251024"
        assert state.recording_date == "251024"

    def test_detect_date_button_exists(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        assert isinstance(form.detect_date_btn, pn.widgets.Button)

    def test_detect_date_button_calls_read_recording_date(self, tmp_path: Path):
        """Click Detect Date with a valid session_dir -> SpikeGLXLoader is invoked."""
        from pynpxpipe.ui.components.session_form import SessionForm

        gate_dir = tmp_path / "run_g0"
        gate_dir.mkdir()
        meta = gate_dir / "run_g0_t0.imec0.ap.meta"
        _write_meta(meta)

        state = AppState()
        state.session_dir = gate_dir
        form = SessionForm(state)

        with patch(
            "pynpxpipe.io.spikeglx.SpikeGLXLoader.read_recording_date",
            return_value="251024",
        ) as mock_read:
            form._on_detect_date_click(None)

        mock_read.assert_called_once()
        called_path = Path(mock_read.call_args[0][0])
        assert called_path == meta

    def test_detect_date_button_writes_recording_date_to_state(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        gate_dir = tmp_path / "run_g0"
        gate_dir.mkdir()
        meta = gate_dir / "run_g0_t0.imec0.ap.meta"
        _write_meta(meta)

        state = AppState()
        state.session_dir = gate_dir
        form = SessionForm(state)

        with patch(
            "pynpxpipe.io.spikeglx.SpikeGLXLoader.read_recording_date",
            return_value="251024",
        ):
            form._on_detect_date_click(None)

        assert state.recording_date == "251024"
        assert form.recording_date_input.value == "251024"

    def test_detect_date_button_warns_when_no_meta(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        gate_dir = tmp_path / "run_g0"
        gate_dir.mkdir()

        state = AppState()
        state.session_dir = gate_dir
        form = SessionForm(state)
        form._on_detect_date_click(None)

        assert form.detect_date_alert.visible is True
        assert "No *.ap.meta" in str(form.detect_date_alert.object)
        assert state.recording_date == ""
