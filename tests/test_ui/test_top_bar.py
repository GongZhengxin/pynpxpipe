"""Tests for ui/components/top_bar.py — header shell (ui_redesign.md §4.3 P1-1)."""

from __future__ import annotations

import panel as pn

from pynpxpipe.ui.router import Router
from pynpxpipe.ui.state import AppState


def _bar(machine_text: str = "GPU RTX 4090 · 24 GB · RAM 40% · 磁盘 1.2 TB 可用"):
    from pynpxpipe.ui.components.top_bar import TopBar

    state, router = AppState(), Router()
    return state, router, TopBar(state, router, machine_fn=lambda: machine_text)


def test_nav_buttons_route_to_views():
    _, router, bar = _bar()
    assert [b.name for b in bar.nav_buttons.values()] == ["Sessions", "新建", "帮助"]
    bar.nav_buttons["new"].clicks += 1
    assert router.view == "new"
    bar.nav_buttons["help"].clicks += 1
    assert router.view == "help"
    bar.nav_buttons["sessions"].clicks += 1
    assert router.view == "sessions"


def test_active_view_button_is_highlighted():
    _, router, bar = _bar()
    router.go("new")
    assert bar.nav_buttons["new"].button_type == "primary"
    assert bar.nav_buttons["sessions"].button_type == "light"


def test_machine_status_is_shown_and_refreshable():
    text = ["GPU A · RAM 10%"]
    from pynpxpipe.ui.components.top_bar import TopBar

    bar = TopBar(AppState(), Router(), machine_fn=lambda: text[0])
    assert "GPU A" in bar.machine.object
    text[0] = "GPU A · RAM 90%"
    bar.refresh_machine()
    assert "RAM 90%" in bar.machine.object


def test_machine_probe_failure_hides_status():
    from pynpxpipe.ui.components.top_bar import TopBar

    def broken():
        raise OSError("no nvidia-smi")

    bar = TopBar(AppState(), Router(), machine_fn=broken)
    assert bar.machine.visible is False


def test_status_badge_follows_run_status():
    state, _, bar = _bar()
    assert "空闲" in bar.status_badge.object
    state.error_message = "RuntimeError: boom\nmore"
    state.run_status = "failed"
    assert "失败" in bar.status_badge.object and "boom" in bar.status_badge.object


def test_machine_text_formats_profile():
    from types import SimpleNamespace

    from pynpxpipe.ui.components.top_bar import machine_status_text

    gpu = SimpleNamespace(name="NVIDIA GeForce RTX 4090", vram_total_gb=24.0)
    text = machine_status_text(gpu, ram_percent=71.0, disk_free_gb=1228.8)
    assert text == "RTX 4090 · 24 GB · RAM 71% · 磁盘 1.2 TB 可用"
    assert machine_status_text(None, ram_percent=5.0, disk_free_gb=80.0) == (
        "无 GPU · RAM 5% · 磁盘 80 GB 可用"
    )


def test_panel_contains_logo_nav_machine_and_badge():
    _, _, bar = _bar()
    layout = bar.panel()
    assert isinstance(layout, pn.Row)
    objs = list(layout.select(pn.pane.HTML)) + list(layout.select(pn.widgets.Button))
    assert bar.status_badge in objs and bar.machine in objs


def test_default_machine_probe_runs_on_this_machine():
    """Exercise the real ResourceDetector path (no fake), as the served page does."""
    from pynpxpipe.ui.components.top_bar import _default_machine_text

    text = _default_machine_text()
    assert "RAM" in text and "可用" in text
