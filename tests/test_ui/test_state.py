"""Tests for ui/state.py — AppState and ProgressBridge.

Groups:
  A. AppState defaults    — param fields initialised with correct default values
  B. ProgressBridge._update — directly sets current_stage + stage_progress on AppState
  C. ProgressBridge.callback — delegates to pn.state.execute with the right lambda
  D. Thread safety        — callback invoked from background thread updates state
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest  # noqa: F401 (used via pytest.raises and pytest.approx)

# ---------------------------------------------------------------------------
# A. AppState defaults
# ---------------------------------------------------------------------------


def test_app_state_default_run_status():
    """AppState.run_status starts as 'idle'."""
    from pynpxpipe.ui.state import AppState

    state = AppState()
    assert state.run_status == "idle"


def test_app_state_default_selected_stages():
    """AppState.selected_stages starts as empty list."""
    from pynpxpipe.ui.state import AppState

    state = AppState()
    assert state.selected_stages == []


def test_app_state_default_progress_fields():
    """AppState.current_stage, stage_progress, stage_statuses all start empty/zero."""
    from pynpxpipe.ui.state import AppState

    state = AppState()
    assert state.current_stage == ""
    assert state.stage_progress == 0.0
    assert state.stage_statuses == {}


def test_app_state_default_error_message():
    """AppState.error_message starts as empty string."""
    from pynpxpipe.ui.state import AppState

    state = AppState()
    assert state.error_message == ""


def test_app_state_default_paths_are_none():
    """AppState path fields (session_dir, bhv_file, output_dir) default to None."""
    from pynpxpipe.ui.state import AppState

    state = AppState()
    assert state.session_dir is None
    assert state.bhv_file is None
    assert state.output_dir is None


def test_app_state_run_status_rejects_invalid():
    """AppState.run_status only accepts the four defined values."""
    from pynpxpipe.ui.state import AppState

    state = AppState()
    with pytest.raises(ValueError):
        state.run_status = "not_a_valid_status"


# ---------------------------------------------------------------------------
# B. ProgressBridge._update
# ---------------------------------------------------------------------------


def test_progress_bridge_update_sets_current_stage():
    """_update writes message to state.current_stage."""
    from pynpxpipe.ui.state import AppState, ProgressBridge

    state = AppState()
    bridge = ProgressBridge(state)
    bridge._update("preprocess", 0.5)
    assert state.current_stage == "preprocess"


def test_progress_bridge_update_sets_stage_progress():
    """_update writes fraction to state.stage_progress."""
    from pynpxpipe.ui.state import AppState, ProgressBridge

    state = AppState()
    bridge = ProgressBridge(state)
    bridge._update("sort", 0.75)
    assert state.stage_progress == pytest.approx(0.75)


def test_progress_bridge_update_clamps_fraction_high():
    """_update with fraction > 1.0 raises param ValueError."""
    from pynpxpipe.ui.state import AppState, ProgressBridge

    state = AppState()
    bridge = ProgressBridge(state)
    with pytest.raises(ValueError):
        bridge._update("sort", 1.5)


# ---------------------------------------------------------------------------
# C. ProgressBridge.callback — delegates to pn.state.execute
# ---------------------------------------------------------------------------


def test_progress_bridge_callback_calls_pn_execute():
    """callback() calls pn.state.execute with a callable."""
    from pynpxpipe.ui.state import AppState, ProgressBridge

    state = AppState()
    bridge = ProgressBridge(state)

    mock_pn = MagicMock()
    with patch.dict("sys.modules", {"panel": mock_pn}):
        bridge.callback("discover", 0.3)

    mock_pn.state.execute.assert_called_once()
    called_lambda = mock_pn.state.execute.call_args[0][0]
    assert callable(called_lambda)


def test_progress_bridge_callback_lambda_updates_state():
    """The lambda passed to pn.state.execute actually updates state when called."""
    from pynpxpipe.ui.state import AppState, ProgressBridge

    state = AppState()
    bridge = ProgressBridge(state)

    captured_fn = None

    def capture_execute(fn):
        nonlocal captured_fn
        captured_fn = fn

    mock_pn = MagicMock()
    mock_pn.state.execute.side_effect = capture_execute

    with patch.dict("sys.modules", {"panel": mock_pn}):
        bridge.callback("curate", 0.9)

    assert captured_fn is not None
    captured_fn()  # simulate Panel executing it on the UI thread
    assert state.current_stage == "curate"
    assert state.stage_progress == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# D. Thread safety
# ---------------------------------------------------------------------------


def test_progress_bridge_callback_from_background_thread():
    """callback can be invoked from a non-main thread without raising."""
    from pynpxpipe.ui.state import AppState, ProgressBridge

    state = AppState()
    bridge = ProgressBridge(state)
    errors: list[Exception] = []

    def mock_execute(fn):
        fn()  # execute synchronously for test

    mock_pn = MagicMock()
    mock_pn.state.execute.side_effect = mock_execute

    def worker():
        try:
            with patch.dict("sys.modules", {"panel": mock_pn}):
                bridge.callback("export", 1.0)
        except Exception as exc:
            errors.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=3)

    assert not errors, f"Background thread raised: {errors[0]}"
    assert state.current_stage == "export"
    assert state.stage_progress == pytest.approx(1.0)
