"""Tests for ui/components/task_window_page.py (ui_redesign.md §4.3 P1-4)."""

from __future__ import annotations

import pandas as pd
import pytest

from pynpxpipe.core.config import PipelineConfig, TaskWindowConfig
from pynpxpipe.ui.components.task_timeline import SourceTimeline, TimelineData
from pynpxpipe.ui.state import AppState

SAVED = TaskWindowConfig(enabled=True, max_idle_s=10, padding_before_s=2, padding_after_s=2)
SUMMARY = {
    "n_sources": 1,
    "n_trials": 2,
    "n_empty_trials": 1,
    "max_sync_residual_ms": 0.012,
    "joint_sorting_compatible": True,
}


def _data() -> TimelineData:
    source = SourceTimeline("a", 0.0, 100.0, 100.0, 1.0, 0.0, 100.0, [(10, 11), (60, 61)], [])
    trials = pd.DataFrame(
        {
            "source_id": ["a", "a"],
            "trial_key": ["a:1", "a:2"],
            "start_time": [10.0, 60.0],
            "stop_time": [11.0, 61.0],
            "n_presentations": [1, 1],
        }
    )
    data = TimelineData([source], trials, [])
    data.saved = data.select(SAVED)
    return data


def _release(slider, value) -> None:
    """Simulate dragging a slider to *value* and letting go."""
    import param

    slider.value = value
    with param.edit_constant(slider):
        slider.value_throttled = value


@pytest.fixture
def page():
    import dataclasses

    from pynpxpipe.ui.components.task_window_page import TaskWindowPage

    state = AppState()
    state.pipeline_config = dataclasses.replace(PipelineConfig(), task_windows=SAVED)
    calls = {"apply": [], "confirm": 0, "later": 0}
    p = TaskWindowPage(
        state,
        apply_fn=calls["apply"].append,
        confirm_fn=lambda: calls.__setitem__("confirm", calls["confirm"] + 1),
        later_fn=lambda: calls.__setitem__("later", calls["later"] + 1),
        eta_fn=lambda kept_s: kept_s * 2,
    )
    p.show(_data(), SUMMARY, SAVED, paused_s=12 * 60)
    return p, calls


def test_metrics_and_paused_badge(page):
    p, _ = page
    text = p.metrics.object
    assert "0.012 ms" in text and "2" in text and "兼容" in text
    assert "空 trial" in text
    assert "等你确认 · 已暂停 12 min" in p.status.object


def test_sliders_start_at_saved_values(page):
    p, _ = page
    assert (p.idle.value, p.pre.value, p.post.value) == (10, 2, 2)
    # Spec range 30–600 s / 0–120 s, widened only to include the saved value.
    assert (p.idle.start, p.idle.end, p.idle.step) == (10, 600, 10)
    assert (p.pre.start, p.pre.end, p.pre.step) == (0, 120, 5)


def test_clean_state_offers_confirm_and_later(page):
    p, calls = page
    assert p.confirm_btn.visible and p.later_btn.visible
    assert not p.apply_btn.visible and not p.revert_btn.visible
    p.confirm_btn.clicks += 1
    p.later_btn.clicks += 1
    assert calls["confirm"] == 1 and calls["later"] == 1


def test_changing_a_slider_recomputes_and_offers_apply(page):
    p, calls = page
    _release(p.idle, 60)
    assert p.apply_btn.visible and p.revert_btn.visible and not p.confirm_btn.visible
    table = p.comparison.object
    assert "任务块" in table and "| 2 | 1 |" in table.replace(" ", " ")
    p.apply_btn.clicks += 1
    (cfg,) = calls["apply"]
    assert (cfg.max_idle_s, cfg.padding_before_s, cfg.padding_after_s) == (60, 2, 2)
    assert cfg.enabled is True


def test_revert_restores_saved_parameters(page):
    p, _ = page
    _release(p.idle, 60)
    p.revert_btn.clicks += 1
    assert p.idle.value == 10
    assert p.confirm_btn.visible


def test_gap_list_marks_cut_or_kept(page):
    p, _ = page
    assert "0.8 min 间隙 → 切开" in p.gaps.object
    _release(p.idle, 60)
    assert "0.8 min 间隙 → 保留" in p.gaps.object


def test_all_stimulus_trials_covered(page):
    p, _ = page
    assert "全部 2 个有刺激 trial 都在保留区内" in p.coverage.object
    assert p.coverage.alert_type == "success"


def test_missing_trials_are_flagged(page, monkeypatch):
    p, _ = page
    first_only = p._data.select(SAVED)[:1]
    monkeypatch.setattr(p._data, "select", lambda cfg: first_only)
    _release(p.pre, 5)
    assert p.coverage.alert_type == "danger"
    assert "a:2" in p.coverage.object


def test_sort_eta_uses_kept_duration(page):
    p, _ = page
    assert "预计 sort 用时" in p.comparison.object
    assert "min" in p.comparison.object


def test_unavailable_preview_shows_message():
    from pynpxpipe.ui.components.task_window_page import TaskWindowPage

    p = TaskWindowPage(AppState(), apply_fn=print, confirm_fn=print, later_fn=print)
    p.load("Z:/definitely/missing")
    assert p.message.visible and "任务时段预览" in p.message.object
