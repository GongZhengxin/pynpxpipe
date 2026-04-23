"""Nature journal style rc-params, palette, and figure helpers.

Importing :mod:`pynpxpipe.plots` calls :func:`apply_nature_style` once. Tests
that compare rcParams explicitly should invoke :func:`apply_nature_style`
inside a fixture to stay deterministic.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib as mpl
import matplotlib.pyplot as plt

if TYPE_CHECKING:
    from matplotlib.figure import Figure

# ---------------------------------------------------------------------------
# Okabe-Ito 8-color colorblind-safe palette.
# Reference: Okabe & Ito (2008), "Color Universal Design".
# ---------------------------------------------------------------------------

PALETTE: dict[str, str] = {
    "black": "#000000",
    "orange": "#E69F00",
    "sky": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermilion": "#D55E00",
    "purple": "#CC79A7",
}

# Semantic mapping locked across all stage plots.
UNITTYPE_COLORS: dict[str, str] = {
    "SUA": PALETTE["green"],
    "MUA": PALETTE["orange"],
    "NON-SOMA": PALETTE["purple"],
    "NOISE": "#888888",
}

# Single-column / double-column figure widths (mm → inch).
_MM_PER_IN = 25.4
_SINGLE_COL_MM = 89.0
_DOUBLE_COL_MM = 183.0


def apply_nature_style() -> None:
    """Install Nature rc-params on the default matplotlib runtime.

    Idempotent — safe to call multiple times. Also registers a 'nature'
    cycler so ``plt.plot(...)`` without explicit color picks the
    Okabe-Ito order.
    """
    rc = {
        # Fonts
        "font.family": ["Arial", "DejaVu Sans", "sans-serif"],
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "legend.fontsize": 10,
        "figure.titlesize": 12,
        "figure.titleweight": "bold",
        # Spines
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.linewidth": 0.8,
        # Ticks
        "xtick.major.width": 0.8,
        "ytick.major.width": 0.8,
        "xtick.minor.width": 0.5,
        "ytick.minor.width": 0.5,
        "xtick.direction": "out",
        "ytick.direction": "out",
        # Lines
        "lines.linewidth": 1.0,
        "lines.markersize": 4.0,
        # Background
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        # Grid
        "axes.grid": False,
        # Save
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
        # Color cycle
        "axes.prop_cycle": mpl.cycler(
            color=[
                PALETTE["blue"],
                PALETTE["orange"],
                PALETTE["green"],
                PALETTE["vermilion"],
                PALETTE["purple"],
                PALETTE["sky"],
                PALETTE["yellow"],
                PALETTE["black"],
            ]
        ),
    }
    mpl.rcParams.update(rc)


def figure_size(cols: int = 1, height_ratio: float = 0.75) -> tuple[float, float]:
    """Return ``(width_inches, height_inches)`` for a Nature-column figure.

    Args:
        cols: 1 for single-column (89 mm) or 2 for double-column (183 mm).
        height_ratio: Multiplier applied to width to derive height.
            ``0.75`` gives a classic 4:3 aspect; use ``0.5`` for banners.

    Raises:
        ValueError: If ``cols`` is not 1 or 2.
    """
    if cols == 1:
        width_in = _SINGLE_COL_MM / _MM_PER_IN
    elif cols == 2:
        width_in = _DOUBLE_COL_MM / _MM_PER_IN
    else:
        raise ValueError(f"cols must be 1 or 2, got {cols}")
    return (width_in, width_in * height_ratio)


def savefig(
    fig: Figure,
    path: Path | str,
    *,
    title: str | None = None,
    dpi: int = 300,
) -> Path:
    """Optionally set a suptitle, tight-layout, write PNG, then close the fig.

    Args:
        fig: matplotlib Figure object.
        path: Output path (parent dirs must exist, or will be created).
        title: Optional suptitle; rendered with ``figure.titleweight='bold'``.
        dpi: Raster resolution. Defaults to 300.

    Returns:
        The resolved :class:`pathlib.Path` written.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if title:
        fig.suptitle(title)

    try:
        fig.tight_layout()
    except Exception:
        # tight_layout occasionally complains about incompatible axes; the
        # savefig still works — log-free swallow is fine for diagnostic plots.
        pass

    fig.savefig(out, dpi=dpi)
    plt.close(fig)
    return out
