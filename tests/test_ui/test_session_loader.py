"""Tests for ui/components/session_loader.py — Session restore from output_dir."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import panel as pn
import pytest

from pynpxpipe.ui.state import AppState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def state():
    return AppState()


@pytest.fixture()
def session_json_data():
    """Return a minimal session.json dict."""
    return {
        "session_dir": "C:/data/monkey_g0",
        "output_dir": "C:/output/session1",
        "bhv_file": "C:/data/task.bhv2",
        "subject": {
            "subject_id": "monkey1",
            "species": "Macaca mulatta",
            "sex": "M",
            "age": "P3Y",
            "weight": "10kg",
            "description": "",
        },
        "probes": [],
        "checkpoint": {},
    }


@pytest.fixture()
def output_dir_with_session(tmp_path, session_json_data):
    """Create a tmp output dir with a valid session.json."""
    session_file = tmp_path / "session.json"
    session_file.write_text(json.dumps(session_json_data), encoding="utf-8")
    (tmp_path / "checkpoints").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSessionLoaderConstruction:
    def test_creates_panel_layout(self, state):
        from pynpxpipe.ui.components.session_loader import SessionLoader

        loader = SessionLoader(state)
        layout = loader.panel()
        assert isinstance(layout, pn.viewable.Viewable)

    def test_has_output_dir_input_and_load_button(self, state):
        from pynpxpipe.ui.components.session_loader import SessionLoader

        loader = SessionLoader(state)
        assert hasattr(loader, "dir_input")
        assert hasattr(loader, "load_btn")


# ---------------------------------------------------------------------------
# Load session
# ---------------------------------------------------------------------------


class TestLoadSession:
    def test_load_fills_state_fields(self, state, output_dir_with_session, session_json_data):
        """Loading a session should fill AppState with session data."""
        from pynpxpipe.ui.components.session_loader import SessionLoader

        loader = SessionLoader(state, load_session_fn=self._make_load_fn(session_json_data))
        loader.dir_input.value = str(output_dir_with_session)
        loader._on_load_click(None)

        assert state.session_dir is not None
        assert state.bhv_file is not None
        assert state.output_dir == str(output_dir_with_session)
        assert state.subject_config is not None

    def test_load_fills_subject_config(self, state, output_dir_with_session, session_json_data):
        """Subject fields should be populated from session.json."""
        from pynpxpipe.ui.components.session_loader import SessionLoader

        loader = SessionLoader(state, load_session_fn=self._make_load_fn(session_json_data))
        loader.dir_input.value = str(output_dir_with_session)
        loader._on_load_click(None)

        subject = state.subject_config
        assert subject["subject_id"] == "monkey1"
        assert subject["species"] == "Macaca mulatta"

    def test_load_shows_success_message(self, state, output_dir_with_session, session_json_data):
        """After successful load, show a success message."""
        from pynpxpipe.ui.components.session_loader import SessionLoader

        loader = SessionLoader(state, load_session_fn=self._make_load_fn(session_json_data))
        loader.dir_input.value = str(output_dir_with_session)
        loader._on_load_click(None)

        assert "loaded" in loader.message_pane.object.lower()

    def test_load_with_empty_dir_shows_error(self, state):
        """Loading with empty dir input should show error."""
        from pynpxpipe.ui.components.session_loader import SessionLoader

        loader = SessionLoader(state)
        loader.dir_input.value = ""
        loader._on_load_click(None)

        assert loader.message_pane.object != ""
        assert "directory" in loader.message_pane.object.lower()

    def test_load_with_missing_session_json_shows_error(self, state, tmp_path):
        """Loading from a dir without session.json should show error."""
        from pynpxpipe.ui.components.session_loader import SessionLoader

        def failing_load(output_dir):
            raise FileNotFoundError("session.json not found")

        loader = SessionLoader(state, load_session_fn=failing_load)
        loader.dir_input.value = str(tmp_path)
        loader._on_load_click(None)

        assert "not found" in loader.message_pane.object.lower()

    def test_load_with_corrupt_json_shows_error(self, state, tmp_path):
        """Loading corrupt session.json should show error."""
        from pynpxpipe.ui.components.session_loader import SessionLoader

        def corrupt_load(output_dir):
            raise ValueError("Corrupt session.json")

        loader = SessionLoader(state, load_session_fn=corrupt_load)
        loader.dir_input.value = str(tmp_path)
        loader._on_load_click(None)

        assert "corrupt" in loader.message_pane.object.lower()

    # Helper
    @staticmethod
    def _make_load_fn(session_data):
        """Create a load function that returns a mock session from dict data."""

        def load_fn(output_dir):
            return session_data

        return load_fn


# ---------------------------------------------------------------------------
# Integration with StatusView
# ---------------------------------------------------------------------------


class TestSessionLoaderStatusIntegration:
    def test_load_triggers_status_display(self, state, output_dir_with_session, session_json_data):
        """After loading a session, status_view should be available if provided."""
        from pynpxpipe.ui.components.session_loader import SessionLoader

        status_callback = MagicMock()
        loader = SessionLoader(
            state,
            load_session_fn=TestLoadSession._make_load_fn(session_json_data),
            on_session_loaded=status_callback,
        )
        loader.dir_input.value = str(output_dir_with_session)
        loader._on_load_click(None)

        status_callback.assert_called_once()

    def test_load_sets_output_dir_in_state(self, state, output_dir_with_session, session_json_data):
        """output_dir in state should match the loaded directory."""
        from pynpxpipe.ui.components.session_loader import SessionLoader

        loader = SessionLoader(
            state,
            load_session_fn=TestLoadSession._make_load_fn(session_json_data),
        )
        loader.dir_input.value = str(output_dir_with_session)
        loader._on_load_click(None)

        assert state.output_dir == str(output_dir_with_session)


# ---------------------------------------------------------------------------
# SID S3 — restore NWB filename fields
# ---------------------------------------------------------------------------


class TestSessionLoaderNWBFieldRestore:
    """SessionLoader must restore experiment / recording_date / probe_plan from session.json."""

    @staticmethod
    def _canonical_payload() -> dict:
        return {
            "session_dir": "C:/data/monkey_g0",
            "output_dir": "C:/output/session1",
            "bhv_file": "C:/data/task.bhv2",
            "subject": {
                "subject_id": "MaoDan",
                "species": "Macaca mulatta",
                "sex": "M",
                "age": "P4Y",
                "weight": "12kg",
                "description": "",
            },
            "session_id": {
                "date": "251024",
                "subject": "MaoDan",
                "experiment": "nsd1w",
                "region": "MSB-V4",
            },
            "probe_plan": {"imec0": "MSB", "imec1": "V4"},
            "probes": [],
            "checkpoint": {},
        }

    def test_load_restores_experiment(self, tmp_path):
        from pynpxpipe.ui.components.session_loader import SessionLoader

        state = AppState()
        payload = self._canonical_payload()
        loader = SessionLoader(state, load_session_fn=lambda _p: payload)
        loader.dir_input.value = str(tmp_path)
        loader._on_load_click(None)
        assert state.experiment == "nsd1w"

    def test_load_restores_recording_date(self, tmp_path):
        from pynpxpipe.ui.components.session_loader import SessionLoader

        state = AppState()
        payload = self._canonical_payload()
        loader = SessionLoader(state, load_session_fn=lambda _p: payload)
        loader.dir_input.value = str(tmp_path)
        loader._on_load_click(None)
        assert state.recording_date == "251024"

    def test_load_restores_probe_plan(self, tmp_path):
        from pynpxpipe.ui.components.session_loader import SessionLoader

        state = AppState()
        payload = self._canonical_payload()
        loader = SessionLoader(state, load_session_fn=lambda _p: payload)
        loader.dir_input.value = str(tmp_path)
        loader._on_load_click(None)
        assert state.probe_plan == {"imec0": "MSB", "imec1": "V4"}

    def test_load_warns_when_session_json_lacks_nwb_metadata(self, tmp_path):
        """Legacy session.json (no session_id / probe_plan) should keep state defaults and warn."""
        from pynpxpipe.ui.components.session_loader import SessionLoader

        legacy = {
            "session_dir": "C:/data/legacy_g0",
            "output_dir": "C:/output/legacy",
            "bhv_file": "C:/data/task.bhv2",
            "subject": {
                "subject_id": "LegacyMonkey",
                "species": "Macaca mulatta",
                "sex": "M",
                "age": "P4Y",
                "weight": "12kg",
                "description": "",
            },
            "probes": [],
            "checkpoint": {},
        }
        state = AppState()
        loader = SessionLoader(state, load_session_fn=lambda _p: legacy)
        loader.dir_input.value = str(tmp_path)
        loader._on_load_click(None)

        assert "NWB filename metadata" in loader.message_pane.object
