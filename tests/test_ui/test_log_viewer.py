"""Tests for LogViewer filters (ui_redesign.md §4.3 P1-5)."""

from __future__ import annotations

from pynpxpipe.ui.components.log_viewer import LogViewer


def _viewer() -> LogViewer:
    v = LogViewer()
    for line in (
        "04:09:47 [WARNING] preprocess imec1 3 channels flagged dead",
        "04:10:02 [INFO] sort imec0 done",
        "04:12:02 [WARNING] sort imec1 GPU memory 76%",
        "04:12:31 [ERROR] sort imec1 CUDA out of memory",
        "04:13:00 [INFO] curate start",
    ):
        v.append(line)
    return v


def test_counts_in_level_labels():
    v = _viewer()
    v.refresh()
    assert list(v.level.options) == ["全部", "警告 2", "错误 1"]


def test_level_filter():
    v = _viewer()
    v.level.value = "error"
    v.refresh()
    assert "CUDA out of memory" in v.display.object
    assert "flagged dead" not in v.display.object
    v.level.value = "warn"
    v.refresh()
    assert "flagged dead" in v.display.object and "curate start" not in v.display.object


def test_stage_only_and_search():
    v = _viewer()
    v.current_stage = "sort"
    v.stage_only.value = True
    v.refresh()
    assert "sort imec0 done" in v.display.object and "preprocess" not in v.display.object
    v.search.value = "imec1"
    v.refresh()
    assert "GPU memory" in v.display.object and "imec0 done" not in v.display.object


def test_autoscroll_toggle():
    v = _viewer()
    v.refresh()
    assert "scrollTop" in v.display.object
    v.autoscroll.value = False
    v.refresh()
    assert "scrollTop" not in v.display.object


def test_filter_widgets_are_in_panel():
    import panel as pn

    v = _viewer()
    widgets = list(v.panel().select(pn.widgets.Widget))
    for w in (v.level, v.stage_only, v.search, v.autoscroll):
        assert w in widgets
