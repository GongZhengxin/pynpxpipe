"""ui/router.py — URL routing for the web UI (ui_redesign.md §4.3 P1-1).

The current view lives in the query string, ``?view=…&dir=…&stage=…``, so a
page refresh or a shared link reopens the same place.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlencode

import param

VIEWS: tuple[str, ...] = ("sessions", "new", "session", "task_window", "help")
DEFAULT_VIEW = "sessions"


def parse_query(search: str) -> dict[str, str]:
    """Parse ``?view=…&dir=…&stage=…`` into router fields.

    Args:
        search: The URL query string, with or without the leading ``?``.

    Returns:
        ``{"view", "output_dir", "stage"}``; an unknown view becomes the default.
    """
    query = parse_qs(search.lstrip("?"))
    view = (query.get("view") or [DEFAULT_VIEW])[0]
    return {
        "view": view if view in VIEWS else DEFAULT_VIEW,
        "output_dir": (query.get("dir") or [""])[0],
        "stage": (query.get("stage") or [""])[0],
    }


def build_query(view: str, output_dir: str, stage: str) -> str:
    """Inverse of :func:`parse_query`; empty values are omitted."""
    pairs = [("view", view), ("dir", output_dir), ("stage", stage)]
    return "?" + urlencode([(k, v) for k, v in pairs if v])


class Router(param.Parameterized):
    """Current view plus its session directory and stage, mirrored to the URL.

    Args:
        location: ``pn.state.location`` (anything with a ``search`` param), or
            None outside a served page.
    """

    view = param.Selector(default=DEFAULT_VIEW, objects=list(VIEWS))
    output_dir = param.String(default="")
    stage = param.String(default="")

    def __init__(self, location: param.Parameterized | None = None, **params) -> None:
        super().__init__(**params)
        self._location = location
        self._syncing = False
        if location is not None:
            self._from_search(location.search or "")
            location.param.watch(lambda event: self._from_search(event.new or ""), "search")

    def _from_search(self, search: str) -> None:
        if self._syncing:
            return
        fields = parse_query(search)
        self._syncing = True
        try:
            self.param.update(**fields)
        finally:
            self._syncing = False

    def go(self, view: str, *, output_dir: str | None = None, stage: str | None = None) -> None:
        """Switch view; session params are kept only when given or still relevant.

        Args:
            view: One of VIEWS.
            output_dir: Session output directory for session-scoped views.
            stage: Stage to focus in the session workspace.

        Raises:
            ValueError: If *view* is unknown.
        """
        if view not in VIEWS:
            raise ValueError(f"Unknown view: {view!r}")
        scoped = view in ("session", "task_window")
        self.param.update(
            view=view,
            output_dir=(output_dir if output_dir is not None else self.output_dir)
            if scoped
            else "",
            stage=(stage or "") if scoped else "",
        )
        if self._location is not None and not self._syncing:
            self._syncing = True
            try:
                self._location.search = build_query(self.view, self.output_dir, self.stage)
            finally:
                self._syncing = False
