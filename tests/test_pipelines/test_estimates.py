"""Tests for pipelines/estimates.py — stage durations from past logs (ui_redesign.md §8.4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pynpxpipe.pipelines.estimates import (
    collect_stage_rates,
    estimate_stage_seconds,
    format_duration,
    meta_duration_s,
    recording_duration_s,
)


def _session(root: Path, name: str, duration_s: float, events: list[dict]) -> Path:
    out = root / name
    (out / "logs").mkdir(parents=True)
    (out / "03_segments").mkdir()
    (out / "03_segments" / "summary.json").write_text(
        json.dumps({"retained_duration_s": duration_s, "original_duration_s": duration_s * 2}),
        encoding="utf-8",
    )
    lines = [json.dumps({"event": "stage_start", "stage": "sort"}), "not json"]
    lines += [json.dumps({"event": "stage_complete", "status": "completed", **e}) for e in events]
    (out / "logs" / f"pynpxpipe_{name}.log").write_text("\n".join(lines), encoding="utf-8")
    return out


@pytest.fixture
def history(tmp_path):
    return [
        _session(
            tmp_path,
            f"s{i}",
            600.0,
            [
                {"stage": "sort", "probe_id": "imec0", "elapsed_s": 600.0 * k},
                {"stage": "sort", "probe_id": "imec1", "elapsed_s": 600.0 * k},
                {"stage": "synchronize", "probe_id": None, "elapsed_s": 60.0 * k},
            ],
        )
        for i, k in enumerate((1.0, 2.0, 3.0))
    ]


def test_rates_per_recording_second(history):
    rates = collect_stage_rates(history)
    assert sorted(rates["sort"]) == [1.0, 1.0, 2.0, 2.0, 3.0, 3.0]  # one sample per probe
    assert sorted(rates["synchronize"]) == [0.1, 0.2, 0.3]
    assert "preprocess" not in rates


def test_estimate_uses_median_and_scales_with_probes(history):
    rates = collect_stage_rates(history)
    assert estimate_stage_seconds(rates, "sort", duration_s=100, n_probes=2, min_samples=3) == 400.0
    assert estimate_stage_seconds(
        rates, "synchronize", duration_s=100, n_probes=2, min_samples=3
    ) == (pytest.approx(20.0))


def test_too_few_samples_gives_no_estimate(history):
    rates = collect_stage_rates(history[:1])
    assert (
        estimate_stage_seconds(rates, "synchronize", duration_s=100, n_probes=1, min_samples=3)
        is None
    )
    assert (
        estimate_stage_seconds(rates, "preprocess", duration_s=100, n_probes=1, min_samples=1)
        is None
    )


def test_missing_or_broken_sessions_are_skipped(tmp_path, history):
    broken = tmp_path / "broken"
    (broken / "logs").mkdir(parents=True)
    (broken / "logs" / "x.log").write_text(
        json.dumps({"event": "stage_complete", "stage": "sort", "elapsed_s": 5}), encoding="utf-8"
    )  # no duration information → ignored
    rates = collect_stage_rates([*history, broken, tmp_path / "missing"])
    assert len(rates["sort"]) == 6


def test_recording_duration_prefers_retained_then_meta(tmp_path):
    out = tmp_path / "o"
    (out / "03_segments").mkdir(parents=True)
    (out / "03_segments" / "summary.json").write_text(
        json.dumps({"retained_duration_s": 300.0, "original_duration_s": 900.0}), encoding="utf-8"
    )
    assert recording_duration_s(out) == 300.0

    meta = tmp_path / "a.ap.meta"
    meta.write_text("fileTimeSecs=3720.5\nimSampRate=30000\n", encoding="utf-8")
    other = tmp_path / "p"
    other.mkdir()
    (other / "session.json").write_text(
        json.dumps({"probes": [{"probe_id": "imec0", "ap_meta": str(meta)}]}), encoding="utf-8"
    )
    assert recording_duration_s(other) == 3720.5
    assert meta_duration_s(meta) == 3720.5
    assert recording_duration_s(tmp_path / "nothing") is None


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(20, "<1 min"), (60 * 35, "35 min"), (60 * 80, "1 h 20 min"), (3600 * 2, "2 h")],
)
def test_format_duration(seconds, text):
    assert format_duration(seconds) == text
