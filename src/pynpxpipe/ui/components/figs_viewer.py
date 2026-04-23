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

        # Gallery is a Column of per-stage Cards; each Card holds a FlexBox of
        # thumbnail widgets. Grouping preserves filter ergonomics for pipelines
        # that emit dozens of figures across sync / curated / postprocessed.
        self.gallery_container = pn.Column(
            sizing_mode="stretch_width",
        )
        # Flat registry of thumbnail widgets across all groups, used by
        # ``_apply_filter`` and unit tests to iterate regardless of grouping.
        self._thumbnails: list[pn.viewable.Viewable] = []

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
        """Group thumbnails by stage (top-level output dir) into collapsible Cards."""
        self.gallery_container.clear()
        self._thumbnails = []

        output_root = Path(self._state.output_dir) if self._state.output_dir else None

        # Group paths by stage — the first path component under output_dir.
        groups: dict[str, list[Path]] = {}
        for path in self.figure_paths:
            group_key = self._group_key(path, output_root)
            groups.setdefault(group_key, []).append(path)

        for group_key in sorted(groups):
            group_paths = groups[group_key]
            group_flex = pn.FlexBox(
                sizing_mode="stretch_width",
                align_items="flex-start",
                flex_wrap="wrap",
            )
            for path in group_paths:
                thumb = self._make_thumbnail(path)
                self._thumbnails.append(thumb)
                group_flex.append(thumb)

            card = pn.Card(
                group_flex,
                title=f"{group_key} ({len(group_paths)} figures)",
                collapsible=True,
                collapsed=False,
                sizing_mode="stretch_width",
                margin=(4, 0),
            )
            # Tag the card so tests can introspect grouping without drilling
            # into Panel's Card internals.
            card._pynpx_group_key = group_key
            card._pynpx_flex = group_flex
            self.gallery_container.append(card)

        self._apply_filter()

    @staticmethod
    def _group_key(path: Path, output_root: Path | None) -> str:
        """Return the stage group name for a figure path.

        Uses the first component of the relative path under ``output_root``
        (e.g. ``04_sync``, ``05_curated``, ``06_postprocessed``,
        ``01_preprocessed``). Falls back to the immediate parent directory
        name when the path is not rooted under ``output_root``.
        """
        if output_root is not None:
            try:
                relative = path.relative_to(output_root)
                if relative.parts:
                    return relative.parts[0]
            except ValueError:
                pass
        return path.parent.name or "figures"

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
        """Hide gallery entries whose filename does not match the filter.

        Works across grouped thumbnails (Cards containing FlexBoxes). A Card
        with zero visible thumbnails is itself hidden to avoid empty cards
        cluttering the layout.
        """
        needle = (self.filter_input.value or "").strip().lower()

        # Update every thumbnail's visibility.
        for thumb in self._thumbnails:
            name = getattr(thumb, "_pynpx_fig_name", "")
            if needle and needle not in name.lower():
                thumb.visible = False
            else:
                thumb.visible = True

        # Hide cards whose entire thumbnail set is filtered out.
        for card in self.gallery_container:
            flex = getattr(card, "_pynpx_flex", None)
            if flex is None:
                continue
            any_visible = any(getattr(thumb, "visible", True) for thumb in flex)
            card.visible = any_visible

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
