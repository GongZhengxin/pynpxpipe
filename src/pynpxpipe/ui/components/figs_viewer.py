"""ui/components/figs_viewer.py — Browse pipeline-generated figures.

Scans the session output directory for PNG files (sync diagnostic plots,
curate/postprocess figures, etc.) and presents them as a filterable
thumbnail gallery. Clicking a thumbnail opens the full-resolution image
in a modal-style pane.

The scan function is injected so unit tests can run without touching the
filesystem. In production it recursively globs ``{output_dir}/**/*.png``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import panel as pn

from pynpxpipe.ui.state import AppState


class FigsViewer:
    """Thumbnail gallery for pipeline output figures.

    Args:
        state: Shared AppState instance.
        scan_fn: Callable(output_dir) -> list[Path]. Returns the list of
            PNG paths to display. Defaults to recursive glob.
    """

    def __init__(
        self,
        state: AppState,
        scan_fn: Callable[[str], list[Path]] | None = None,
    ) -> None:
        self._state = state
        self._scan_fn = scan_fn or self._default_scan

        # Populated by load_figures()
        self.figure_paths: list[Path] = []

        # ── Widgets ──
        self.message_pane = pn.pane.Str(
            "Set output directory and click Refresh to browse figures.",
            styles={"font-size": "13px"},
        )
        self.refresh_btn = pn.widgets.Button(
            name="Refresh Figures",
            button_type="primary",
        )
        self.refresh_btn.on_click(self._on_refresh_click)

        self.filter_input = pn.widgets.TextInput(
            name="Filter",
            placeholder="Substring filter (e.g. 'residual', 'sync')",
        )
        self.filter_input.param.watch(lambda _e: self._apply_filter(), "value")

        self.gallery_container = pn.FlexBox(
            sizing_mode="stretch_width",
            align_items="flex-start",
            flex_wrap="wrap",
        )

        # Modal preview (hidden until a thumbnail is clicked)
        self.preview_pane = pn.pane.PNG(
            None,
            sizing_mode="stretch_width",
            max_height=800,
        )
        self.preview_caption = pn.pane.Str("", styles={"font-weight": "bold"})
        self.preview_close_btn = pn.widgets.Button(
            name="Close Preview",
            button_type="default",
            width=140,
        )
        self.preview_close_btn.on_click(self._on_close_preview)
        self.preview_container = pn.Column(
            self.preview_close_btn,
            self.preview_caption,
            self.preview_pane,
            visible=False,
            sizing_mode="stretch_width",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_figures(self) -> None:
        """Rescan the output directory and rebuild the thumbnail gallery."""
        output_dir = self._state.output_dir
        if not output_dir:
            self.message_pane.object = "No output directory set."
            self.figure_paths = []
            self.gallery_container.clear()
            return

        try:
            paths = list(self._scan_fn(output_dir))
        except Exception as exc:  # noqa: BLE001
            self.message_pane.object = f"Failed to scan figures: {exc}"
            self.figure_paths = []
            self.gallery_container.clear()
            return

        self.figure_paths = paths

        if not paths:
            self.message_pane.object = "No figure (.png) files found under this output directory."
            self.gallery_container.clear()
            return

        self.message_pane.object = f"Found {len(paths)} figure(s)."
        self._build_gallery()

    def panel(self) -> pn.viewable.Viewable:
        """Return the Panel layout for this component."""
        return pn.Column(
            pn.pane.Markdown("## Figures"),
            pn.Row(self.refresh_btn, self.filter_input),
            self.message_pane,
            self.preview_container,
            self.gallery_container,
            sizing_mode="stretch_width",
        )

    # ------------------------------------------------------------------
    # Gallery construction
    # ------------------------------------------------------------------

    def _build_gallery(self) -> None:
        """Create a thumbnail card per figure path."""
        self.gallery_container.clear()
        for path in self.figure_paths:
            self.gallery_container.append(self._make_thumbnail(path))
        self._apply_filter()

    def _make_thumbnail(self, path: Path) -> pn.viewable.Viewable:
        """Build a single thumbnail card (label + image + open button)."""
        label = pn.pane.Str(
            path.name,
            styles={"font-size": "11px", "overflow": "hidden"},
        )
        thumb = pn.pane.PNG(
            str(path),
            width=240,
            height=180,
        )
        open_btn = pn.widgets.Button(
            name="Enlarge",
            button_type="light",
            width=100,
        )
        open_btn.on_click(lambda _e, p=path: self._on_open_click(p))

        card = pn.Column(
            label,
            thumb,
            open_btn,
            width=260,
            margin=(6, 6),
        )
        # Attach the source path so the filter can identify each card.
        card._pynpx_fig_name = path.name
        return card

    def _apply_filter(self) -> None:
        """Hide gallery entries whose filename does not match the filter."""
        needle = (self.filter_input.value or "").strip().lower()
        for item in self.gallery_container:
            name = getattr(item, "_pynpx_fig_name", "")
            if needle and needle not in name.lower():
                item.visible = False
            else:
                item.visible = True

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_refresh_click(self, event) -> None:
        self.load_figures()

    def _on_open_click(self, path: Path) -> None:
        self.preview_pane.object = str(path)
        self.preview_caption.object = path.name
        self.preview_container.visible = True

    def _on_close_preview(self, event) -> None:
        self.preview_container.visible = False
        self.preview_pane.object = None
        self.preview_caption.object = ""

    # ------------------------------------------------------------------
    # Default scanner (production wiring)
    # ------------------------------------------------------------------

    @staticmethod
    def _default_scan(output_dir: str) -> list[Path]:
        """Recursively glob for PNG files under output_dir."""
        root = Path(output_dir)
        if not root.exists():
            return []
        return sorted(root.rglob("*.png"))
