"""Tests for ui/components/error_view.py — stage failure view (ui_redesign.md §4.3 P1-6)."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import panel as pn
import pytest

from pynpxpipe.core.config import SortingConfig
from pynpxpipe.ui.state import AppState


def _cp(out: Path, name: str, status: str, error: str = "") -> None:
    (out / "checkpoints").mkdir(parents=True, exist_ok=True)
    payload = {"status": status, **({"error": error} if error else {})}
    (out / "checkpoints" / f"{name}.json").write_text(json.dumps(payload), "utf-8")


def _log(out: Path, stage: str, probe: str | None, error: str, tb: str) -> None:
    (out / "logs").mkdir(parents=True, exist_ok=True)
    line = {
        "event": "stage_failed",
        "stage": stage,
        "probe_id": probe,
        "error": error,
        "traceback": tb,
    }
    (out / "logs" / "pynpxpipe_x.log").write_text(json.dumps(line) + "\n", "utf-8")


@pytest.fixture
def view():
    from pynpxpipe.ui.components.error_view import ErrorView

    state = AppState()
    base = SortingConfig()
    params = dataclasses.replace(base.sorter.params, batch_size=60000)
    state.sorting_config = dataclasses.replace(
        base, sorter=dataclasses.replace(base.sorter, params=params)
    )
    state.probe_plan = {"imec0": "V4", "imec1": "IT"}
    calls = {"apply": [], "params": 0, "help": 0}
    v = ErrorView(
        state,
        apply_fn=lambda changes, stage, probe: calls["apply"].append((changes, stage, probe)),
        open_params_fn=lambda: calls.__setitem__("params", calls["params"] + 1),
        help_fn=lambda: calls.__setitem__("help", calls["help"] + 1),
        min_batch_size=10000,
    )
    return v, calls


def test_cuda_oom_on_one_probe(view, tmp_path):
    v, calls = view
    _cp(tmp_path, "sort_imec0", "completed")
    _cp(tmp_path, "sort_imec1", "failed", "CUDA out of memory. Tried to allocate 2 GiB")
    _log(
        tmp_path,
        "sort",
        "imec1",
        "CUDA out of memory",
        'Traceback (most recent call last):\n  File "kilosort/run_kilosort.py"',
    )
    assert v.load(tmp_path, "sort") is True
    assert "imec1 的 sort 因 GPU 显存不足停止" in v.title.object
    assert "imec0 已完成，结果保留，不受影响" in v.title.object
    assert "batch_size" in v.advice.object and "60000 → 40000" in v.advice.object
    assert v.apply_btn.visible and v.apply_btn.name == "按建议修改并重跑 imec1"
    v.apply_btn.clicks += 1
    assert calls["apply"] == [((("sorter.params.batch_size", 40000),), "sort", "imec1")]
    assert "kilosort/run_kilosort.py" in v.traceback.object


def test_unknown_error_offers_only_text_and_help(view, tmp_path):
    v, calls = view
    _cp(tmp_path, "curate", "failed", "KeyError: 'snr'")
    assert v.load(tmp_path, "curate") is True
    assert "curate 出错" in v.title.object
    assert "KeyError" in v.advice.object
    assert not v.apply_btn.visible
    v.help_btn.clicks += 1
    v.params_btn.clicks += 1
    assert calls["help"] == 1 and calls["params"] == 1
    assert "日志中没有记录" in v.traceback.object


def test_no_failure_returns_false(view, tmp_path):
    v, _ = view
    _cp(tmp_path, "sort_imec0", "completed")
    assert v.load(tmp_path, "sort") is False


def test_panel_has_traceback_collapsed(view, tmp_path):
    v, _ = view
    _cp(tmp_path, "sort_imec1", "failed", "CUDA out of memory")
    v.load(tmp_path, "sort")
    cards = list(v.panel().select(pn.Card))
    assert any(c.collapsed and "完整报错" in c.title for c in cards)
