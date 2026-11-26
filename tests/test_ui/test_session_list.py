"""Tests for ui/components/session_list.py — home page (ui_redesign.md §4.3 P1-2, §8.3)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import panel as pn
import pytest

from pynpxpipe.pipelines.constants import PER_PROBE_STAGES, STAGE_ORDER
from pynpxpipe.pipelines.run_state import (
    RunState,
    mark_task_window_pending,
    write_run_state,
)
from pynpxpipe.ui.recent_sessions import RecentEntry, remember
from pynpxpipe.ui.router import Router
from pynpxpipe.ui.settings import UISettings

NOW = 1_000_000.0


def _make_output(root: Path, name: str, done: list[str], failed: str | None = None) -> Path:
    out = root / name
    cp = out / "checkpoints"
    cp.mkdir(parents=True)
    (out / "session.json").write_text(
        json.dumps({"subject": {"subject_id": "MaoDan"}, "probe_plan": {"imec0": "V4"}}),
        encoding="utf-8",
    )
    for stage in done:
        (cp / f"{stage}.json").write_text('{"status": "completed"}', encoding="utf-8")
        if stage in PER_PROBE_STAGES:
            (cp / f"{stage}_imec0.json").write_text('{"status": "completed"}', encoding="utf-8")
    if failed:
        (cp / f"{failed}_imec0.json").write_text('{"status": "failed"}', encoding="utf-8")
    return out


@pytest.fixture
def setup(tmp_path):
    store = tmp_path / "recent.json"
    outs = {
        "exported": _make_output(tmp_path, "exported", [s for s in STAGE_ORDER if s != "merge"]),
        "failed": _make_output(
            tmp_path, "failed", ["discover", "synchronize", "select_segments", "preprocess"], "sort"
        ),
        "waiting": _make_output(
            tmp_path, "waiting", ["discover", "synchronize", "select_segments"]
        ),
        "running": _make_output(tmp_path, "running", ["discover", "synchronize"]),
    }
    mark_task_window_pending(outs["waiting"])
    write_run_state(
        outs["running"],
        RunState("r", os.getpid(), NOW - 10, NOW - 1, ["select_segments"], "select_segments",
                 None, 0.4, "running", ""),
    )  # fmt: skip
    # remember() puts the latest call first, so record oldest first.
    remember(
        store,
        RecentEntry(str(tmp_path / "gone"), "gone", "XiaoHei", ["imec0"], 0.0),
        max_entries=20,
        now=NOW - 100,
    )
    for i, (name, out) in reversed(list(enumerate(outs.items()))):
        entry = RecentEntry(str(out), name, "MaoDan", ["imec0"], 0.0)
        remember(store, entry, max_entries=20, now=NOW - i)

    opened = []
    router = Router()
    from pynpxpipe.ui.components.session_list import SessionList

    view = SessionList(
        router,
        recent_path=store,
        settings=UISettings(),
        open_fn=opened.append,
        now_fn=lambda: NOW,
    )
    return view, router, opened, outs, store


def _row(view, name):
    return next(r for r in view.rows if r.entry.name == name)


def test_rows_follow_recent_order(setup):
    view, *_ = setup
    assert [r.entry.name for r in view.rows] == ["exported", "failed", "waiting", "running", "gone"]


def test_status_per_row(setup):
    view, *_ = setup
    assert _row(view, "exported").kind == "done"
    assert _row(view, "exported").status == "已导出 NWB"
    assert _row(view, "failed").kind == "fail"
    assert "sort 失败" in _row(view, "failed").status
    assert _row(view, "waiting").kind == "wait"
    assert _row(view, "running").kind == "run"
    assert "select_segments" in _row(view, "running").status
    assert _row(view, "gone").kind == "missing"


def test_stage_strip_colours(setup):
    view, *_ = setup
    exported = dict(zip(STAGE_ORDER, _row(view, "exported").stages, strict=True))
    assert exported["merge"] == "skipped" and exported["export"] == "done"
    failed = dict(zip(STAGE_ORDER, _row(view, "failed").stages, strict=True))
    assert failed["sort"] == "failed" and failed["curate"] == "pending"
    waiting = dict(zip(STAGE_ORDER, _row(view, "waiting").stages, strict=True))
    assert waiting["select_segments"] == "waiting"
    running = dict(zip(STAGE_ORDER, _row(view, "running").stages, strict=True))
    assert running["select_segments"] == "running"


def test_counts(setup):
    view, *_ = setup
    assert view.counts == {"running": 1, "waiting": 1, "failed": 1, "exported": 1}
    text = str(view.counts_pane.object)
    for label in ("运行中", "待你确认", "失败", "已导出 NWB"):
        assert label in text


@pytest.mark.parametrize(
    ("name", "view_name", "stage"),
    [("waiting", "task_window", ""), ("failed", "session", "sort"), ("exported", "session", "")],
)
def test_open_routes_by_status(setup, name, view_name, stage):
    view, router, opened, outs, _ = setup
    view.open(_row(view, name))
    assert opened == [str(outs[name])]
    assert (router.view, router.output_dir, router.stage) == (view_name, str(outs[name]), stage)


def test_row_buttons_open_and_remove(setup):
    view, router, opened, outs, store = setup
    buttons = [b for b in view.list_pane.select(pn.widgets.Button) if b.name == "打开"]
    assert len(buttons) == 4
    buttons[1].clicks += 1
    assert opened == [str(outs["failed"])]
    remove = [b for b in view.list_pane.select(pn.widgets.Button) if b.name == "移除"]
    assert len(remove) == 1
    remove[0].clicks += 1
    assert "gone" not in [r.entry.name for r in view.rows]


def test_search_filters_rows(setup):
    view, *_ = setup
    view.search.value = "wait"
    texts = " ".join(str(p.object) for p in view.list_pane.select(pn.pane.HTML))
    assert "waiting" in texts and "exported" not in texts


def test_new_button_routes_to_wizard(setup):
    view, router, *_ = setup
    view.new_btn.clicks += 1
    assert router.view == "new"


def test_open_existing_directory_remembers_it(setup, tmp_path):
    view, router, opened, _, store = setup
    other = _make_output(tmp_path, "other", ["discover"])
    view.open_input.value = str(other)
    view.open_btn.clicks += 1
    assert opened[-1] == str(other)
    assert router.view == "session"
    assert view.rows[0].entry.name == "other"


def test_open_missing_directory_shows_error(setup, tmp_path):
    view, router, opened, *_ = setup
    view.open_input.value = str(tmp_path / "nope")
    view.open_btn.clicks += 1
    assert opened == [] and view.message.visible
    assert router.view == "sessions"


def test_relative_time():
    from pynpxpipe.ui.components.session_list import relative_time

    assert relative_time(NOW - 30, NOW) == "刚刚"
    assert relative_time(NOW - 600, NOW) == "10 分钟前"
    assert relative_time(NOW - 7200, NOW) == "2 小时前"
    assert relative_time(NOW - 86400 * 1.5, NOW) == "昨天"
    assert relative_time(NOW - 86400 * 3, NOW) == "3 天前"


def test_remember_output_moves_session_to_top(setup):
    view, _, _, outs, _ = setup
    view.remember_output(outs["running"])
    assert view.rows[0].entry.name == "running"


def test_app_remembers_loaded_and_started_sessions(tmp_path, monkeypatch):
    from pynpxpipe.ui.app import create_app
    from pynpxpipe.ui.components.session_list import SessionList

    seen = []
    monkeypatch.setattr(SessionList, "remember_output", lambda self, d: seen.append(str(d)))
    app = create_app()
    state = app._pynpx_state
    state.output_dir = str(tmp_path)
    state.run_status = "running"
    assert seen == [str(tmp_path)]
