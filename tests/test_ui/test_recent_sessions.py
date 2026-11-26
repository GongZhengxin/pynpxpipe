"""Tests for ui/recent_sessions.py — recent output directories (ui_redesign.md §8.3)."""

from __future__ import annotations

import json
from pathlib import Path

from pynpxpipe.ui.recent_sessions import (
    RecentEntry,
    entry_from_output,
    forget,
    load_recent,
    remember,
)


def _entry(path: Path, name: str = "s") -> RecentEntry:
    return RecentEntry(str(path), name, "MaoDan", ["imec0"], 0.0)


def test_missing_or_corrupt_store_is_empty(tmp_path):
    store = tmp_path / ".pynpxpipe" / "recent_sessions.json"
    assert load_recent(store) == []
    store.parent.mkdir()
    store.write_text("[not json", encoding="utf-8")
    assert load_recent(store) == []


def test_remember_puts_newest_first_and_dedupes(tmp_path):
    store = tmp_path / "recent.json"
    a, b = tmp_path / "a", tmp_path / "b"
    remember(store, _entry(a, "a"), max_entries=5, now=1.0)
    remember(store, _entry(b, "b"), max_entries=5, now=2.0)
    remember(store, _entry(a, "a2"), max_entries=5, now=3.0)
    entries = load_recent(store)
    assert [e.name for e in entries] == ["a2", "b"]
    assert entries[0].last_opened == 3.0


def test_remember_truncates_to_max(tmp_path):
    store = tmp_path / "recent.json"
    for i in range(4):
        remember(store, _entry(tmp_path / str(i), str(i)), max_entries=3, now=float(i))
    assert [e.name for e in load_recent(store)] == ["3", "2", "1"]


def test_forget_removes_entry(tmp_path):
    store = tmp_path / "recent.json"
    remember(store, _entry(tmp_path / "a", "a"), max_entries=5, now=1.0)
    forget(store, tmp_path / "a")
    assert load_recent(store) == []


def test_entry_from_output_reads_session_json(tmp_path):
    out = tmp_path / "251024_MaoDan_nsd1w_V4"
    out.mkdir()
    (out / "session.json").write_text(
        json.dumps(
            {
                "subject": {"subject_id": "MaoDan"},
                "probe_plan": {"imec0": "V4", "imec1": "IT"},
            }
        ),
        encoding="utf-8",
    )
    entry = entry_from_output(out, now=5.0)
    assert entry == RecentEntry(str(out), out.name, "MaoDan", ["imec0", "imec1"], 5.0)


def test_entry_from_output_without_session_json(tmp_path):
    entry = entry_from_output(tmp_path, now=1.0)
    assert (entry.subject_id, entry.probe_ids) == ("", [])


def test_default_store_is_under_project_and_gitignored(monkeypatch):
    from pynpxpipe.ui.recent_sessions import RECENT_PATH_ENV, default_recent_path

    monkeypatch.delenv(RECENT_PATH_ENV)
    path = default_recent_path()

    root = Path(__file__).resolve().parents[2]
    assert path == root / ".pynpxpipe" / "recent_sessions.json"
    assert ".pynpxpipe/" in (root / ".gitignore").read_text(encoding="utf-8").splitlines()


def test_env_var_overrides_store(monkeypatch, tmp_path):
    from pynpxpipe.ui.recent_sessions import RECENT_PATH_ENV, default_recent_path

    monkeypatch.setenv(RECENT_PATH_ENV, str(tmp_path / "x.json"))
    assert default_recent_path() == tmp_path / "x.json"
