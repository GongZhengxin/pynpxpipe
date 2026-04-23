"""Tests for pynpxpipe.plots.style — Nature style rc-params + helpers."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

import matplotlib as mpl
import matplotlib.pyplot as plt
import pytest
from PIL import Image

from pynpxpipe.plots.style import (
    PALETTE,
    UNITTYPE_COLORS,
    apply_nature_style,
    figure_size,
    savefig,
)


@pytest.fixture(autouse=True)
def _reset_rc():
    mpl.rcdefaults()
    apply_nature_style()
    yield
    mpl.rcdefaults()


def test_apply_nature_style_sets_fonts():
    assert mpl.rcParams["font.family"][0] == "Arial"
    assert mpl.rcParams["axes.titlesize"] == 12
    assert mpl.rcParams["axes.labelsize"] == 11
    assert mpl.rcParams["xtick.labelsize"] == 10
    assert mpl.rcParams["ytick.labelsize"] == 10


def test_apply_nature_style_bold_title():
    assert mpl.rcParams["axes.titleweight"] == "bold"
    assert mpl.rcParams["figure.titleweight"] == "bold"


def test_apply_nature_style_hides_top_right_spines():
    assert mpl.rcParams["axes.spines.top"] is False
    assert mpl.rcParams["axes.spines.right"] is False


def test_apply_nature_style_no_grid():
    assert mpl.rcParams["axes.grid"] is False


def test_apply_nature_style_savefig_dpi():
    assert mpl.rcParams["savefig.dpi"] == 300


def test_palette_has_all_okabe_ito():
    expected = {"black", "orange", "sky", "green", "yellow", "blue", "vermilion", "purple"}
    assert set(PALETTE.keys()) == expected


def test_palette_values_are_hex():
    for name, hex_code in PALETTE.items():
        assert hex_code.startswith("#"), name
        assert len(hex_code) == 7, name


def test_unittype_colors_complete():
    assert set(UNITTYPE_COLORS.keys()) == {"SUA", "MUA", "NON-SOMA", "NOISE"}
    assert UNITTYPE_COLORS["SUA"] == PALETTE["green"]
    assert UNITTYPE_COLORS["MUA"] == PALETTE["orange"]
    assert UNITTYPE_COLORS["NON-SOMA"] == PALETTE["purple"]


def test_figure_size_single_column():
    w, h = figure_size(cols=1)
    assert abs(w - 89.0 / 25.4) < 1e-6
    assert abs(h - w * 0.75) < 1e-6


def test_figure_size_double_column():
    w, h = figure_size(cols=2, height_ratio=0.5)
    assert abs(w - 183.0 / 25.4) < 1e-6
    assert abs(h - w * 0.5) < 1e-6


def test_figure_size_invalid_cols():
    with pytest.raises(ValueError):
        figure_size(cols=3)


def test_savefig_writes_png(tmp_path):
    fig, ax = plt.subplots(figsize=figure_size(cols=1))
    ax.plot([0, 1], [0, 1])
    out = savefig(fig, tmp_path / "plot.png", title="Test Title")
    assert out == tmp_path / "plot.png"
    assert out.exists()
    assert out.stat().st_size > 0


def test_savefig_creates_parent_dirs(tmp_path):
    fig, ax = plt.subplots()
    ax.plot([1, 2, 3])
    nested = tmp_path / "deep" / "nested" / "dir" / "f.png"
    out = savefig(fig, nested)
    assert out.exists()


def test_savefig_png_is_valid_image(tmp_path):
    fig, ax = plt.subplots(figsize=figure_size(cols=1))
    ax.plot([0, 1, 2], [0, 1, 0])
    out = savefig(fig, tmp_path / "valid.png")
    with Image.open(out) as img:
        assert img.format == "PNG"
        assert img.size[0] > 100  # non-degenerate image


def test_savefig_dpi_override(tmp_path):
    fig, ax = plt.subplots(figsize=(2, 2))
    ax.plot([0, 1])
    out = savefig(fig, tmp_path / "lowdpi.png", dpi=72)
    with Image.open(out) as img:
        # 2 inches × 72 dpi = ~144 px wide (give slack for bbox='tight')
        assert 100 <= img.size[0] <= 200


def test_savefig_closes_figure(tmp_path):
    fig, ax = plt.subplots()
    ax.plot([1, 2])
    n_open_before = len(plt.get_fignums())
    savefig(fig, tmp_path / "close.png")
    assert len(plt.get_fignums()) == n_open_before - 1
