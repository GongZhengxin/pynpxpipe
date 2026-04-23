"""Tests for pynpxpipe.plots.postprocess — Postprocess diagnostic plots."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from pathlib import Path
from unittest.mock import MagicMock

import matplotlib as mpl
import numpy as np
import pandas as pd
import pytest
from PIL import Image

from pynpxpipe.plots.postprocess import emit_all
from pynpxpipe.plots.style import apply_nature_style

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rc():
    mpl.rcdefaults()
    apply_nature_style()
    yield
    mpl.rcdefaults()


@pytest.fixture
def rng() -> np.random.Generator:
    return np.random.default_rng(42)


def _make_analyzer(n_units: int, rng: np.random.Generator, fs: float = 30000.0) -> MagicMock:
    """Build a mock SortingAnalyzer with unit_locations + spike trains."""
    unit_ids = list(range(n_units))
    locations = rng.standard_normal((n_units, 2)) * 50.0

    mock_ext = MagicMock()
    mock_ext.get_data.return_value = locations

    mock_sorting = MagicMock()
    mock_sorting.get_unit_ids.return_value = unit_ids
    mock_sorting.get_sampling_frequency.return_value = fs

    def _spike_train(uid, segment_index=0):  # noqa: ARG001
        # 500 random spikes across 60 seconds
        return np.sort(rng.integers(0, int(fs * 60), size=500))

    mock_sorting.get_unit_spike_train.side_effect = _spike_train

    mock = MagicMock()
    mock.sorting = mock_sorting
    mock.get_extension.return_value = mock_ext
    return mock


def _make_unit_scores(n_units: int, rng: np.random.Generator) -> dict:
    scores: dict[str, dict] = {}
    for i in range(n_units):
        scores[str(i)] = {
            "slay_score": float(rng.random()),
            "is_visual": bool(i % 2 == 0),
        }
    return scores


def _make_behavior_events_df(n_trials: int = 20, include_stim_index: bool = True):
    data = {
        "trial_id": list(range(n_trials)),
        "stim_onset_nidq_s": [float(i) for i in range(n_trials)],
        "stim_onset_imec_s": ["{}"] * n_trials,
        "trial_valid": [1.0] * n_trials,
        "onset_time_ms": [100.0] * n_trials,
        "offset_time_ms": [200.0] * n_trials,
    }
    if include_stim_index:
        data["stim_index"] = [i % 5 for i in range(n_trials)]
    return pd.DataFrame(data)


@pytest.fixture
def stim_onset_times() -> np.ndarray:
    return np.arange(10) * 1.0  # 10 stim onsets, 1s apart


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_emit_all_returns_paths(
    tmp_path: Path, rng: np.random.Generator, stim_onset_times: np.ndarray
) -> None:
    """emit_all returns a non-empty list of Path objects that all exist."""
    analyzer = _make_analyzer(12, rng)
    unit_scores = _make_unit_scores(12, rng)
    events = _make_behavior_events_df()

    paths = emit_all(
        analyzer=analyzer,
        unit_scores=unit_scores,
        behavior_events_df=events,
        stim_onset_times=stim_onset_times,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    assert len(paths) >= 4  # all 5 expected, but tolerate missing stim_coverage
    for p in paths:
        assert isinstance(p, Path)
        assert p.exists()
        assert p.stat().st_size > 0


def test_unit_locations_png_valid(
    tmp_path: Path, rng: np.random.Generator, stim_onset_times: np.ndarray
) -> None:
    """unit_locations.png is written and readable by PIL."""
    analyzer = _make_analyzer(8, rng)
    unit_scores = _make_unit_scores(8, rng)
    events = _make_behavior_events_df()

    emit_all(
        analyzer=analyzer,
        unit_scores=unit_scores,
        behavior_events_df=events,
        stim_onset_times=stim_onset_times,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    path = tmp_path / "unit_locations.png"
    assert path.exists()
    with Image.open(path) as img:
        assert img.size[0] > 100
        assert img.size[1] > 100


def test_slay_distribution_png_valid(
    tmp_path: Path, rng: np.random.Generator, stim_onset_times: np.ndarray
) -> None:
    """slay_distribution.png is written with finite scores."""
    analyzer = _make_analyzer(10, rng)
    unit_scores = _make_unit_scores(10, rng)
    events = _make_behavior_events_df()

    emit_all(
        analyzer=analyzer,
        unit_scores=unit_scores,
        behavior_events_df=events,
        stim_onset_times=stim_onset_times,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    path = tmp_path / "slay_distribution.png"
    assert path.exists()
    with Image.open(path) as img:
        img.verify()


def test_stim_coverage_requires_stim_index(
    tmp_path: Path, rng: np.random.Generator, stim_onset_times: np.ndarray
) -> None:
    """Missing stim_index column → stim_coverage plot skipped, others still written."""
    analyzer = _make_analyzer(10, rng)
    unit_scores = _make_unit_scores(10, rng)
    events = _make_behavior_events_df(include_stim_index=False)

    paths = emit_all(
        analyzer=analyzer,
        unit_scores=unit_scores,
        behavior_events_df=events,
        stim_onset_times=stim_onset_times,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    names = {p.name for p in paths}
    assert "stim_coverage.png" not in names
    assert "unit_locations.png" in names
    assert "slay_distribution.png" in names
    assert "psth_top_units.png" in names
    assert "raster_top_units.png" in names


def test_psth_top_units_with_fewer_than_9_units(
    tmp_path: Path, rng: np.random.Generator, stim_onset_times: np.ndarray
) -> None:
    """Only 3 units → 3x3 grid still generated, empty slots have hidden spines."""
    analyzer = _make_analyzer(3, rng)
    unit_scores = _make_unit_scores(3, rng)
    events = _make_behavior_events_df()

    paths = emit_all(
        analyzer=analyzer,
        unit_scores=unit_scores,
        behavior_events_df=events,
        stim_onset_times=stim_onset_times,
        probe_id="imec0",
        output_dir=tmp_path,
        top_n=9,
    )

    psth = tmp_path / "psth_top_units.png"
    assert psth in paths
    assert psth.exists()
    with Image.open(psth) as img:
        img.verify()


def test_raster_top_units_png_valid(
    tmp_path: Path, rng: np.random.Generator, stim_onset_times: np.ndarray
) -> None:
    """raster_top_units.png is written and opens."""
    analyzer = _make_analyzer(9, rng)
    unit_scores = _make_unit_scores(9, rng)
    events = _make_behavior_events_df()

    emit_all(
        analyzer=analyzer,
        unit_scores=unit_scores,
        behavior_events_df=events,
        stim_onset_times=stim_onset_times,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    path = tmp_path / "raster_top_units.png"
    assert path.exists()
    with Image.open(path) as img:
        img.verify()


def test_emit_all_handles_empty_unit_scores(
    tmp_path: Path, rng: np.random.Generator, stim_onset_times: np.ndarray
) -> None:
    """unit_scores={} → emit_all returns a subset of paths without crashing.

    With no scores, slay_distribution is skipped (no finite scores) but
    unit_locations / stim_coverage / psth / raster still render.
    """
    analyzer = _make_analyzer(4, rng)
    events = _make_behavior_events_df()

    paths = emit_all(
        analyzer=analyzer,
        unit_scores={},
        behavior_events_df=events,
        stim_onset_times=stim_onset_times,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    names = {p.name for p in paths}
    assert "slay_distribution.png" not in names
    # others should still succeed
    assert "unit_locations.png" in names
    assert "stim_coverage.png" in names


def test_all_pngs_open_with_pil(
    tmp_path: Path, rng: np.random.Generator, stim_onset_times: np.ndarray
) -> None:
    """Every returned PNG can be opened and verified by PIL."""
    analyzer = _make_analyzer(12, rng)
    unit_scores = _make_unit_scores(12, rng)
    events = _make_behavior_events_df()

    paths = emit_all(
        analyzer=analyzer,
        unit_scores=unit_scores,
        behavior_events_df=events,
        stim_onset_times=stim_onset_times,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    assert len(paths) == 5
    expected = {
        "unit_locations.png",
        "slay_distribution.png",
        "stim_coverage.png",
        "psth_top_units.png",
        "raster_top_units.png",
    }
    assert {p.name for p in paths} == expected
    for p in paths:
        with Image.open(p) as img:
            img.verify()
