"""Tests for ui/app.py — entry point and spike prototype.

Groups:
  A. Importability   — main() and create_app() are importable without errors
  B. create_app()    — returns a Panel servable object
  C. Mock pipeline   — spike test: ProgressBridge + threading pathway works end-to-end
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# A. Importability
# ---------------------------------------------------------------------------


def test_app_main_importable():
    """main() can be imported from pynpxpipe.ui.app without raising."""
    from pynpxpipe.ui.app import main  # noqa: F401


def test_app_create_app_importable():
    """create_app() can be imported and called."""
    from pynpxpipe.ui.app import create_app  # noqa: F401


# ---------------------------------------------------------------------------
# B. create_app() returns a Panel object
# ---------------------------------------------------------------------------


def test_create_app_returns_panel_viewable():
    """create_app() returns an object that Panel can serve (has .servable or is a pn.viewable)."""
    import panel as pn

    from pynpxpipe.ui.app import create_app

    app = create_app()
    # Panel viewable objects have a .servable() method or are subclasses of Viewable
    assert isinstance(app, pn.viewable.Viewable)


def test_create_app_has_run_button():
    """The app layout contains a widget with 'Run' in its name or label."""
    import panel as pn

    from pynpxpipe.ui.app import create_app

    app = create_app()

    # Walk the object tree looking for a Button with name/label containing 'Run'
    def _find_buttons(obj):
        found = []
        if isinstance(obj, pn.widgets.Button):
            found.append(obj)
        if hasattr(obj, "objects"):
            for child in obj.objects:
                found.extend(_find_buttons(child))
        return found

    buttons = _find_buttons(app)
    labels = [b.name for b in buttons]
    assert any("Run" in lbl or "run" in lbl.lower() for lbl in labels), (
        f"No Run button found among: {labels}"
    )


def test_create_app_has_progress_bar():
    """The app layout contains a Progress widget."""
    import panel as pn

    from pynpxpipe.ui.app import create_app

    app = create_app()

    def _find_progress(obj):
        found = []
        if isinstance(obj, pn.indicators.Progress):
            found.append(obj)
        if hasattr(obj, "objects"):
            for child in obj.objects:
                found.extend(_find_progress(child))
        return found

    progress_widgets = _find_progress(app)
    assert len(progress_widgets) >= 1, "No Progress widget found in app layout"


# ---------------------------------------------------------------------------
# C. Mock pipeline — threading + ProgressBridge pathway
# ---------------------------------------------------------------------------


def test_mock_pipeline_run_updates_state():
    """Spike test: ProgressBridge.callback called from thread updates AppState via mock pn.execute."""
    from pynpxpipe.ui.state import AppState, ProgressBridge

    state = AppState()
    bridge = ProgressBridge(state)
    results: list[tuple[str, float]] = []

    def sync_execute(fn):
        fn()  # simulate Panel executing on UI thread

    mock_pn = MagicMock()
    mock_pn.state.execute.side_effect = sync_execute

    def mock_pipeline(callback):
        """Simulates a pipeline that reports 3 progress updates."""
        for stage, frac in [("discover", 0.0), ("discover", 1.0), ("preprocess", 0.5)]:
            with patch.dict("sys.modules", {"panel": mock_pn}):
                callback(stage, frac)
            results.append((state.current_stage, state.stage_progress))

    t = threading.Thread(target=mock_pipeline, args=(bridge.callback,))
    t.start()
    t.join(timeout=5)

    assert len(results) == 3
    assert results[0] == ("discover", 0.0)
    assert results[1] == ("discover", 1.0)
    assert results[2][0] == "preprocess"
