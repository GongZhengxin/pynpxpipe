"""ui/recent_sessions.py — Recently opened output directories (ui_redesign.md §8.3).

Stored at ``<project root>/.pynpxpipe/recent_sessions.json`` (git-ignored), newest
first. Entries whose directory is gone are kept until the user removes them.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class RecentEntry:
    """One remembered session output directory.

    Attributes:
        output_dir: Session output root.
        name: Display name (the directory name).
        subject_id: Animal from session.json, "" if unknown.
        probe_ids: Probes from session.json's probe_plan.
        last_opened: Epoch seconds when last loaded or run.
    """

    output_dir: str
    name: str
    subject_id: str
    probe_ids: list[str] = field(default_factory=list)
    last_opened: float = 0.0


RECENT_PATH_ENV = "PYNPXPIPE_RECENT_SESSIONS"


def default_recent_path() -> Path:
    """``<project root>/.pynpxpipe/recent_sessions.json``, or ``$PYNPXPIPE_RECENT_SESSIONS``."""
    override = os.environ.get(RECENT_PATH_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / ".pynpxpipe" / "recent_sessions.json"


def _same_dir(a: str | Path, b: str | Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def load_recent(path: Path) -> list[RecentEntry]:
    """Read the store; a missing or unreadable file yields an empty list."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return [RecentEntry(**item) for item in raw]
    except (OSError, ValueError, TypeError):
        return []


def _save(path: Path, entries: list[RecentEntry]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps([asdict(e) for e in entries], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp, path)


def remember(path: Path, entry: RecentEntry, *, max_entries: int, now: float) -> None:
    """Put *entry* first (replacing the same directory) and keep at most *max_entries*.

    Args:
        path: Store file.
        entry: Entry to record; its ``last_opened`` is set to *now*.
        max_entries: List size limit (ui.recent_sessions_max).
        now: Epoch seconds.
    """
    entry.last_opened = now
    rest = [e for e in load_recent(path) if not _same_dir(e.output_dir, entry.output_dir)]
    _save(path, [entry, *rest][:max_entries])


def forget(path: Path, output_dir: str | Path) -> None:
    """Remove *output_dir* from the store."""
    _save(path, [e for e in load_recent(path) if not _same_dir(e.output_dir, output_dir)])


def entry_from_output(output_dir: Path, *, now: float) -> RecentEntry:
    """Build an entry from ``session.json`` (subject and probes), tolerating its absence.

    Args:
        output_dir: Session output root.
        now: Epoch seconds for ``last_opened``.
    """
    output_dir = Path(output_dir)
    subject_id, probe_ids = "", []
    try:
        data = json.loads((output_dir / "session.json").read_text(encoding="utf-8"))
        subject_id = (data.get("subject") or {}).get("subject_id", "") or ""
        probe_ids = sorted((data.get("probe_plan") or {}).keys())
    except (OSError, ValueError, AttributeError):
        pass
    return RecentEntry(str(output_dir), output_dir.name, subject_id, probe_ids, now)
