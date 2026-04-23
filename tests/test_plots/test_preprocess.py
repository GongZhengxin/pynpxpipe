"""Tests for ``pynpxpipe.plots.preprocess.emit_all``.

Exercises the three diagnostic figures (bad_channels, traces before/after
CMR, motion displacement) against a fake SpikeInterface recording surface
built from ``unittest.mock.MagicMock`` so the test suite does not require
any real Zarr or .bin file.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

from pynpxpipe.plots.preprocess import emit_all

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_recording(
    *,
    n_channels: int = 32,
    fs: float = 30000.0,
    seed: int = 0,
    with_locations: bool = True,
    traces_fail: bool = False,
) -> MagicMock:
    """Return a mock recording with ``get_traces``/``get_channel_locations``.

    The mock is built once per test to keep values deterministic.
    """
    rec = MagicMock()
    rng = np.random.default_rng(seed)

    rec.get_sampling_frequency.return_value = fs
    rec.get_num_channels.return_value = n_channels
    rec.channel_ids = [f"AP{i}" for i in range(n_channels)]
    rec.get_channel_ids.return_value = list(rec.channel_ids)

    if with_locations:
        rec.get_channel_locations.return_value = rng.uniform(0, 100, size=(n_channels, 2))
    else:
        rec.get_channel_locations.side_effect = RuntimeError("no locations")

    if traces_fail:
        rec.get_traces.side_effect = RuntimeError("lazy load failure")
    else:

        def _get_traces(start_frame: int = 0, end_frame: int = 0, **_kw):
            n = max(1, int(end_frame) - int(start_frame))
            return rng.standard_normal((n, n_channels)) * 50.0

        rec.get_traces.side_effect = _get_traces

    return rec


@pytest.fixture
def recording_raw() -> MagicMock:
    return _make_recording(seed=0)


@pytest.fixture
def recording_processed() -> MagicMock:
    return _make_recording(seed=1)


@pytest.fixture
def bad_ids(recording_raw: MagicMock) -> list[str]:
    # First three channels flagged as bad.
    return [
        recording_raw.channel_ids[0],
        recording_raw.channel_ids[1],
        recording_raw.channel_ids[2],
    ]


@pytest.fixture
def motion_info() -> dict:
    rng = np.random.default_rng(42)
    n_time, n_space = 20, 8
    return {
        "temporal_bins": np.linspace(0, 100, n_time),
        "spatial_bins": np.linspace(0, 3840, n_space),
        "displacement": rng.standard_normal((n_time, n_space)) * 5.0,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_emit_all_returns_paths(
    tmp_path: Path,
    recording_raw: MagicMock,
    recording_processed: MagicMock,
    bad_ids: list[str],
) -> None:
    """Without motion_info, emit_all returns two paths that all exist."""
    paths = emit_all(
        recording_raw=recording_raw,
        recording_processed=recording_processed,
        bad_channel_ids=bad_ids,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    assert len(paths) == 2
    for path in paths:
        assert path.exists()
        assert path.stat().st_size > 0


def test_emit_all_with_motion_info(
    tmp_path: Path,
    recording_raw: MagicMock,
    recording_processed: MagicMock,
    bad_ids: list[str],
    motion_info: dict,
) -> None:
    """With motion_info, emit_all returns three paths."""
    paths = emit_all(
        recording_raw=recording_raw,
        recording_processed=recording_processed,
        bad_channel_ids=bad_ids,
        probe_id="imec0",
        output_dir=tmp_path,
        motion_info=motion_info,
    )

    assert len(paths) == 3
    names = {p.name for p in paths}
    assert names == {
        "bad_channels.png",
        "traces_cmr_beforeafter.png",
        "motion_displacement.png",
    }


def test_bad_channels_png_valid(
    tmp_path: Path,
    recording_raw: MagicMock,
    recording_processed: MagicMock,
    bad_ids: list[str],
) -> None:
    """bad_channels.png opens as a valid PNG of reasonable size."""
    emit_all(
        recording_raw=recording_raw,
        recording_processed=recording_processed,
        bad_channel_ids=bad_ids,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    png = tmp_path / "bad_channels.png"
    assert png.exists()
    with Image.open(png) as img:
        assert img.format == "PNG"
        assert img.size[0] > 100


def test_traces_png_valid(
    tmp_path: Path,
    recording_raw: MagicMock,
    recording_processed: MagicMock,
    bad_ids: list[str],
) -> None:
    """traces_cmr_beforeafter.png opens as a valid PNG of reasonable size."""
    emit_all(
        recording_raw=recording_raw,
        recording_processed=recording_processed,
        bad_channel_ids=bad_ids,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    png = tmp_path / "traces_cmr_beforeafter.png"
    assert png.exists()
    with Image.open(png) as img:
        assert img.format == "PNG"
        assert img.size[0] > 100


def test_motion_displacement_png_valid(
    tmp_path: Path,
    recording_raw: MagicMock,
    recording_processed: MagicMock,
    bad_ids: list[str],
    motion_info: dict,
) -> None:
    """motion_displacement.png opens as a valid PNG when motion_info is given."""
    emit_all(
        recording_raw=recording_raw,
        recording_processed=recording_processed,
        bad_channel_ids=bad_ids,
        probe_id="imec0",
        output_dir=tmp_path,
        motion_info=motion_info,
    )

    png = tmp_path / "motion_displacement.png"
    assert png.exists()
    with Image.open(png) as img:
        assert img.format == "PNG"
        assert img.size[0] > 100


def test_emit_all_handles_empty_bad_channels(
    tmp_path: Path,
    recording_raw: MagicMock,
    recording_processed: MagicMock,
) -> None:
    """Empty bad_channel_ids still produces both baseline plots."""
    paths = emit_all(
        recording_raw=recording_raw,
        recording_processed=recording_processed,
        bad_channel_ids=[],
        probe_id="imec0",
        output_dir=tmp_path,
    )

    assert len(paths) == 2
    assert (tmp_path / "bad_channels.png").exists()
    assert (tmp_path / "traces_cmr_beforeafter.png").exists()


def test_pngs_open_with_pil(
    tmp_path: Path,
    recording_raw: MagicMock,
    recording_processed: MagicMock,
    bad_ids: list[str],
    motion_info: dict,
) -> None:
    """Every returned path is a valid PNG readable by Pillow."""
    paths = emit_all(
        recording_raw=recording_raw,
        recording_processed=recording_processed,
        bad_channel_ids=bad_ids,
        probe_id="imec0",
        output_dir=tmp_path,
        motion_info=motion_info,
    )

    for path in paths:
        with Image.open(path) as img:
            assert img.format == "PNG"
            assert img.size[0] > 0 and img.size[1] > 0


def test_emit_all_falls_back_when_raw_traces_fail(
    tmp_path: Path,
    recording_processed: MagicMock,
    bad_ids: list[str],
) -> None:
    """If recording_raw.get_traces raises, the traces plot still produces."""
    recording_raw = _make_recording(traces_fail=True)

    paths = emit_all(
        recording_raw=recording_raw,
        recording_processed=recording_processed,
        bad_channel_ids=bad_ids,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    # bad_channels still generated (uses locations, not traces).
    names = {p.name for p in paths}
    assert "bad_channels.png" in names
    # traces plot either produced in fallback mode or skipped cleanly.
    traces_path = tmp_path / "traces_cmr_beforeafter.png"
    if traces_path.exists():
        with Image.open(traces_path) as img:
            assert img.format == "PNG"


def test_emit_all_bar_chart_fallback_when_no_locations(
    tmp_path: Path,
    recording_processed: MagicMock,
    bad_ids: list[str],
) -> None:
    """When get_channel_locations raises, bad_channels.png falls back to a bar chart."""
    raw_no_loc = _make_recording(with_locations=False)
    # Also disable on processed so scatter fallback to processed fails too.
    processed_no_loc = _make_recording(seed=2, with_locations=False)

    paths = emit_all(
        recording_raw=raw_no_loc,
        recording_processed=processed_no_loc,
        bad_channel_ids=bad_ids,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    assert (tmp_path / "bad_channels.png").exists()
    assert any(p.name == "bad_channels.png" for p in paths)


def test_emit_all_creates_output_dir(
    tmp_path: Path,
    recording_raw: MagicMock,
    recording_processed: MagicMock,
) -> None:
    """emit_all creates ``output_dir`` if it does not already exist."""
    figures_dir = tmp_path / "nested" / "path" / "figures"

    paths = emit_all(
        recording_raw=recording_raw,
        recording_processed=recording_processed,
        bad_channel_ids=[],
        probe_id="imec0",
        output_dir=figures_dir,
    )

    assert figures_dir.is_dir()
    assert len(paths) == 2
