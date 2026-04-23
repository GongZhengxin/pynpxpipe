"""Tests for ``pynpxpipe.plots.curate.emit_all``."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from pynpxpipe.plots.curate import emit_all

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_qm(unit_ids: list[int]) -> pd.DataFrame:
    """Varied quality-metric DataFrame for the four canonical columns."""
    n = len(unit_ids)
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "isi_violations_ratio": rng.uniform(0.0, 0.3, size=n),
            "amplitude_cutoff": rng.uniform(0.0, 0.2, size=n),
            "presence_ratio": rng.uniform(0.5, 1.0, size=n),
            "snr": rng.uniform(0.5, 5.0, size=n),
        },
        index=unit_ids,
    )


def _make_analyzer(
    unit_ids: list[int],
    *,
    n_samples: int = 60,
    n_channels: int = 10,
    templates_raises: bool = False,
) -> MagicMock:
    analyzer = MagicMock()
    analyzer.sorting.get_unit_ids.return_value = list(unit_ids)
    analyzer.sorting.get_sampling_frequency.return_value = 30000.0

    if templates_raises:
        analyzer.get_extension.side_effect = RuntimeError("templates missing")
    else:
        rng = np.random.default_rng(1)
        templates = rng.standard_normal((len(unit_ids), n_samples, n_channels))
        ext = MagicMock()
        ext.get_data.return_value = templates
        analyzer.get_extension.return_value = ext

    return analyzer


@pytest.fixture
def unit_ids() -> list[int]:
    return list(range(12))


@pytest.fixture
def unittype_map(unit_ids: list[int]) -> dict[int, str]:
    # 4 SUA, 4 MUA, 2 NON-SOMA, 2 NOISE
    labels = ["SUA"] * 4 + ["MUA"] * 4 + ["NON-SOMA"] * 2 + ["NOISE"] * 2
    return dict(zip(unit_ids, labels, strict=True))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_emit_all_returns_paths(
    tmp_path: Path, unit_ids: list[int], unittype_map: dict[int, str]
) -> None:
    """emit_all returns three paths and all exist on disk."""
    analyzer = _make_analyzer(unit_ids)
    qm = _make_qm(unit_ids)

    paths = emit_all(
        analyzer=analyzer,
        qm=qm,
        unittype_map=unittype_map,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    assert len(paths) == 3
    for path in paths:
        assert path.exists()
        assert path.stat().st_size > 0


def test_quality_metrics_dist_png_valid(
    tmp_path: Path, unit_ids: list[int], unittype_map: dict[int, str]
) -> None:
    """quality_metrics_dist.png exists and opens as a valid PNG."""
    analyzer = _make_analyzer(unit_ids)
    qm = _make_qm(unit_ids)

    emit_all(
        analyzer=analyzer,
        qm=qm,
        unittype_map=unittype_map,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    png = tmp_path / "quality_metrics_dist.png"
    assert png.exists()
    with Image.open(png) as img:
        assert img.format == "PNG"
        assert img.size[0] > 100


def test_unittype_pie_png_valid(
    tmp_path: Path, unit_ids: list[int], unittype_map: dict[int, str]
) -> None:
    """unittype_pie.png exists and opens as a valid PNG."""
    analyzer = _make_analyzer(unit_ids)
    qm = _make_qm(unit_ids)

    emit_all(
        analyzer=analyzer,
        qm=qm,
        unittype_map=unittype_map,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    png = tmp_path / "unittype_pie.png"
    assert png.exists()
    with Image.open(png) as img:
        assert img.format == "PNG"
        assert img.size[0] > 100


def test_waveforms_by_unittype_with_all_types_present(
    tmp_path: Path, unit_ids: list[int], unittype_map: dict[int, str]
) -> None:
    """Waveform grid renders when every unittype has at least one unit."""
    analyzer = _make_analyzer(unit_ids)
    qm = _make_qm(unit_ids)

    emit_all(
        analyzer=analyzer,
        qm=qm,
        unittype_map=unittype_map,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    png = tmp_path / "waveforms_by_unittype.png"
    assert png.exists()
    with Image.open(png) as img:
        assert img.format == "PNG"


def test_waveforms_by_unittype_with_missing_type(tmp_path: Path) -> None:
    """If a unittype has no units, its panel still renders ('No units')."""
    unit_ids = list(range(6))
    # No NON-SOMA units present.
    unittype_map = {
        0: "SUA",
        1: "SUA",
        2: "MUA",
        3: "MUA",
        4: "NOISE",
        5: "NOISE",
    }
    analyzer = _make_analyzer(unit_ids)
    qm = _make_qm(unit_ids)

    paths = emit_all(
        analyzer=analyzer,
        qm=qm,
        unittype_map=unittype_map,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    # Three figures are still produced.
    assert len(paths) == 3
    png = tmp_path / "waveforms_by_unittype.png"
    assert png.exists()
    assert png.stat().st_size > 0


def test_emit_all_handles_analyzer_without_templates(
    tmp_path: Path, unit_ids: list[int], unittype_map: dict[int, str]
) -> None:
    """Waveform plot is skipped cleanly; other two still succeed."""
    analyzer = _make_analyzer(unit_ids, templates_raises=True)
    qm = _make_qm(unit_ids)

    paths = emit_all(
        analyzer=analyzer,
        qm=qm,
        unittype_map=unittype_map,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    # quality_metrics_dist + unittype_pie still written.
    assert (tmp_path / "quality_metrics_dist.png").exists()
    assert (tmp_path / "unittype_pie.png").exists()
    assert not (tmp_path / "waveforms_by_unittype.png").exists()
    assert len(paths) == 2


def test_output_filenames_match_spec(
    tmp_path: Path, unit_ids: list[int], unittype_map: dict[int, str]
) -> None:
    """The three exact filenames required by the spec are present."""
    analyzer = _make_analyzer(unit_ids)
    qm = _make_qm(unit_ids)

    emit_all(
        analyzer=analyzer,
        qm=qm,
        unittype_map=unittype_map,
        probe_id="imec0",
        output_dir=tmp_path,
    )

    written = {p.name for p in tmp_path.iterdir() if p.suffix == ".png"}
    assert "quality_metrics_dist.png" in written
    assert "unittype_pie.png" in written
    assert "waveforms_by_unittype.png" in written


def test_emit_all_creates_output_dir(
    tmp_path: Path, unit_ids: list[int], unittype_map: dict[int, str]
) -> None:
    """emit_all creates ``output_dir`` if it does not exist yet."""
    analyzer = _make_analyzer(unit_ids)
    qm = _make_qm(unit_ids)
    figures_dir = tmp_path / "does" / "not" / "exist"

    paths = emit_all(
        analyzer=analyzer,
        qm=qm,
        unittype_map=unittype_map,
        probe_id="imec0",
        output_dir=figures_dir,
    )

    assert figures_dir.is_dir()
    assert len(paths) == 3
