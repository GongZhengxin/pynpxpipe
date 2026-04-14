"""Tests for ui/components/figs_viewer.py — Browse pipeline-generated figures.

FigsViewer scans the session output directory for PNG files (sync diagnostic
plots, curate/postprocess figures, etc.) and presents them in a thumbnail
gallery with click-to-enlarge. The scan function is injectable so the test
suite does not depend on the pipeline actually having run.
"""

from __future__ import annotations

from pathlib import Path

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
def fake_output_dir(tmp_path: Path) -> Path:
    """Create an output_dir with a few PNG figures under sync/figures."""
    figures_dir = tmp_path / "sync" / "figures"
    figures_dir.mkdir(parents=True)
    # Minimal 1x1 PNG header bytes (valid enough for file scanning).
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8"
        b"\x0f\x00\x00\x01\x01\x00\x01\x5c\xcd\xff\x69\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    for name in (
        "01_nidq_ap_sync_scatter.png",
        "02_residual_hist.png",
        "03_event_code_match.png",
    ):
        (figures_dir / name).write_bytes(png_bytes)
    return tmp_path


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestFigsViewerConstruction:
    def test_creates_panel_layout(self, state):
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        view = FigsViewer(state)
        layout = view.panel()
        assert isinstance(layout, pn.viewable.Viewable)

    def test_initial_state_no_output_dir(self, state):
        """When output_dir is not set, show a placeholder message."""
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        view = FigsViewer(state)
        view.panel()
        assert view.message_pane.object != ""

    def test_has_refresh_button(self, state):
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        view = FigsViewer(state)
        assert isinstance(view.refresh_btn, pn.widgets.Button)


# ---------------------------------------------------------------------------
# Figure scanning
# ---------------------------------------------------------------------------


class TestFigureScanning:
    def test_scan_finds_all_png_files(self, state, fake_output_dir):
        """load_figures() should discover every PNG under output_dir."""
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        state.output_dir = str(fake_output_dir)
        view = FigsViewer(state)
        view.load_figures()

        assert len(view.figure_paths) == 3
        names = {p.name for p in view.figure_paths}
        assert names == {
            "01_nidq_ap_sync_scatter.png",
            "02_residual_hist.png",
            "03_event_code_match.png",
        }

    def test_scan_uses_injected_scan_fn(self, state, tmp_path):
        """Custom scan_fn bypasses filesystem for deterministic tests."""
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        fake_paths = [
            tmp_path / "a.png",
            tmp_path / "sub" / "b.png",
        ]
        view = FigsViewer(state, scan_fn=lambda output_dir: list(fake_paths))
        state.output_dir = str(tmp_path)
        view.load_figures()

        assert view.figure_paths == fake_paths

    def test_scan_recurses_into_subdirs(self, state, tmp_path):
        """Default scanner recurses (sync/figures, curate/plots, etc.)."""
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        (tmp_path / "sync" / "figures").mkdir(parents=True)
        (tmp_path / "postprocess" / "plots").mkdir(parents=True)
        (tmp_path / "sync" / "figures" / "a.png").write_bytes(b"\x89PNG")
        (tmp_path / "postprocess" / "plots" / "b.png").write_bytes(b"\x89PNG")

        state.output_dir = str(tmp_path)
        view = FigsViewer(state)
        view.load_figures()

        names = {p.name for p in view.figure_paths}
        assert names == {"a.png", "b.png"}

    def test_scan_empty_dir_shows_message(self, state, tmp_path):
        """Output dir with no PNGs should display an informational message."""
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        state.output_dir = str(tmp_path)
        view = FigsViewer(state)
        view.load_figures()

        assert view.figure_paths == []
        assert "no figure" in view.message_pane.object.lower()

    def test_scan_no_output_dir_shows_message(self, state):
        """Loading with empty output_dir should produce an error message."""
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        view = FigsViewer(state)
        view.load_figures()

        assert "output" in view.message_pane.object.lower()

    def test_scan_ignores_non_png(self, state, tmp_path):
        """Non-PNG files must not appear in figure_paths."""
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        (tmp_path / "sync").mkdir()
        (tmp_path / "sync" / "ok.png").write_bytes(b"\x89PNG")
        (tmp_path / "sync" / "skip.txt").write_text("no")
        (tmp_path / "sync" / "skip.jpg").write_bytes(b"\xff\xd8")

        state.output_dir = str(tmp_path)
        view = FigsViewer(state)
        view.load_figures()

        names = {p.name for p in view.figure_paths}
        assert names == {"ok.png"}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestFigureRendering:
    def test_gallery_has_one_entry_per_png(self, state, fake_output_dir):
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        state.output_dir = str(fake_output_dir)
        view = FigsViewer(state)
        view.load_figures()

        assert len(view.gallery_container) == 3

    def test_filter_substring_narrows_gallery(self, state, fake_output_dir):
        """Entering a filter substring should hide non-matching thumbnails."""
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        state.output_dir = str(fake_output_dir)
        view = FigsViewer(state)
        view.load_figures()

        view.filter_input.value = "residual"
        view._apply_filter()

        visible = [item for item in view.gallery_container if getattr(item, "visible", True)]
        assert len(visible) == 1

    def test_filter_empty_shows_all(self, state, fake_output_dir):
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        state.output_dir = str(fake_output_dir)
        view = FigsViewer(state)
        view.load_figures()

        view.filter_input.value = ""
        view._apply_filter()

        visible = [item for item in view.gallery_container if getattr(item, "visible", True)]
        assert len(visible) == 3


# ---------------------------------------------------------------------------
# Refresh button wiring
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_refresh_button_triggers_scan(self, state, tmp_path):
        from pynpxpipe.ui.components.figs_viewer import FigsViewer

        calls = {"n": 0}

        def counting_scan(output_dir):
            calls["n"] += 1
            return []

        state.output_dir = str(tmp_path)
        view = FigsViewer(state, scan_fn=counting_scan)
        view._on_refresh_click(None)

        assert calls["n"] == 1
