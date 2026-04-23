"""Bombcell diagnostic plots — wraps ``spikeinterface.widgets`` (sw).

Three widget-backed PNGs are emitted per probe into
``{output_dir}/05_curated/{probe_id}/figures/``:

1. ``bombcell_unit_labels.png``         — ``sw.plot_unit_labels`` overlay.
2. ``bombcell_metric_histograms.png``   — ``sw.plot_metric_histograms``.
3. ``bombcell_labels_upset.png``        — ``sw.plot_bombcell_labels_upset``.

Fallback: if ``labels_df`` / ``thresholds`` are None (bombcell failed or
``use_bombcell=False``), only (1) is drawn using the manual
``unittype_map`` converted to a label ndarray — the other two require
bombcell thresholds and are skipped.

Each widget is wrapped in try/except so one failure never aborts the
others; optional matplotlib and ``spikeinterface.widgets`` imports are
gated so importing this module in a ``plots``-extra-free env is safe.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import matplotlib  # noqa: F401
    import numpy as np

    _HAS_MPL = True
except ImportError:  # pragma: no cover - environment-dependent
    _HAS_MPL = False

try:
    import spikeinterface.widgets as sw

    _HAS_SW = True
except ImportError:  # pragma: no cover - environment-dependent
    sw = None  # type: ignore[assignment]
    _HAS_SW = False

from pynpxpipe.plots.style import savefig

if TYPE_CHECKING:
    import pandas as pd


_LOG = logging.getLogger(__name__)

_UNIT_LABELS_YLIMS: tuple[float, float] = (-300.0, 100.0)
_METRIC_HIST_FIGSIZE: tuple[float, float] = (15.0, 10.0)


def emit_bombcell_plots(
    *,
    analyzer: Any,
    unittype_map: dict,
    labels_df: pd.DataFrame | None,
    thresholds: dict | None,
    probe_id: str,
    output_dir: Path,
) -> list[Path]:
    """Emit bombcell diagnostic PNGs for a single probe.

    Args:
        analyzer: SortingAnalyzer with waveforms/templates/quality_metrics
            extensions already computed. Passed through to the sw widgets
            unchanged.
        unittype_map: ``{unit_id: "SUA"|"MUA"|"NON-SOMA"|"NOISE"}`` for every
            unit in ``analyzer.sorting``. Used as the fallback label source
            when ``labels_df`` is None.
        labels_df: Raw DataFrame returned by
            ``spikeinterface.curation.bombcell_label_units`` — index is
            unit_id, column ``bombcell_label`` holds lowercased bombcell
            labels. None if bombcell failed or ``use_bombcell=False``.
        thresholds: Bombcell default thresholds dict (from
            ``bombcell_get_default_thresholds``). None when ``labels_df`` is
            None; required for the histogram + upset plots.
        probe_id: Probe identifier ("imec0"), used in figure titles.
        output_dir: Directory to write PNGs to. Created if missing.

    Returns:
        List of paths for figures that were written successfully. Empty
        when matplotlib/widgets are unavailable. One element on the
        fallback path (only ``bombcell_unit_labels.png``).
    """
    if not _HAS_MPL:
        _LOG.info("matplotlib not available; skipping bombcell plots")
        return []
    if not _HAS_SW:
        _LOG.info("spikeinterface.widgets not available; skipping bombcell plots")
        return []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    main_path = labels_df is not None and thresholds is not None
    unit_labels_array = _resolve_unit_labels(analyzer, labels_df, unittype_map)

    paths: list[Path] = []

    # 1. Unit labels waveform overlay (works on both paths).
    try:
        widget = sw.plot_unit_labels(
            analyzer,
            unit_labels_array,
            ylims=_UNIT_LABELS_YLIMS,
        )
        fig = _extract_figure(widget)
        if fig is not None:
            title = f"Bombcell unit labels | {probe_id}"
            paths.append(savefig(fig, output_dir / "bombcell_unit_labels.png", title=title))
    except Exception as exc:  # noqa: BLE001 - diagnostic plot; never raise
        _LOG.warning("bombcell plot_unit_labels failed: %s", exc, exc_info=True)

    # 2 + 3. Main path only: histograms + upset need bombcell thresholds.
    if main_path:
        # Pre-flight: plot_bombcell_labels_upset imports upsetplot internally
        # at call time. A missing upsetplot install would surface as a
        # runtime ImportError only once the widget is invoked — we call it
        # out up front so the pipeline log makes the root cause obvious
        # instead of burying it in an sw-internal traceback.
        try:
            import upsetplot  # noqa: F401
        except ImportError:
            _LOG.warning(
                "bombcell_labels_upset will be skipped: upsetplot is not installed "
                "(install the [plots] extra, e.g. `uv sync --inexact --extra plots`)"
            )

        try:
            widget = sw.plot_metric_histograms(
                analyzer,
                thresholds=thresholds,
                figsize=_METRIC_HIST_FIGSIZE,
            )
            fig = _extract_figure(widget)
            if fig is not None:
                title = f"Bombcell metric histograms | {probe_id}"
                paths.append(
                    savefig(
                        fig,
                        output_dir / "bombcell_metric_histograms.png",
                        title=title,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("bombcell plot_metric_histograms failed: %s", exc, exc_info=True)

        try:
            widget = sw.plot_bombcell_labels_upset(
                analyzer,
                unit_labels=unit_labels_array,
                thresholds=thresholds,
                unit_labels_to_plot=["noise", "mua"],
            )
            fig = _extract_figure(widget)
            if fig is not None:
                _sanitize_text_positions(fig)
                title = f"Bombcell labels upset | {probe_id}"
                paths.append(
                    savefig(
                        fig,
                        output_dir / "bombcell_labels_upset.png",
                        title=title,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("bombcell plot_bombcell_labels_upset failed: %s", exc, exc_info=True)
    else:
        _LOG.info(
            "bombcell histogram + upset plots skipped for %s: "
            "labels_df or thresholds missing (bombcell may have failed or use_bombcell=False)",
            probe_id,
        )

    return paths


def _resolve_unit_labels(
    analyzer: Any,
    labels_df: pd.DataFrame | None,
    unittype_map: dict,
) -> np.ndarray:
    """Return a 1-D label array aligned to ``analyzer.sorting.get_unit_ids()``.

    Main path: pull lowercase bombcell labels from ``labels_df``.
    Fallback: map our UNITTYPE strings back to bombcell vocabulary so the
    sw widget produces the expected 4-way split colours.
    """
    unit_ids = list(analyzer.sorting.get_unit_ids())

    if labels_df is not None and "bombcell_label" in labels_df.columns:
        series = labels_df["bombcell_label"]
        return np.asarray([str(series.get(uid, "noise")).lower() for uid in unit_ids])

    back_map = {
        "SUA": "good",
        "MUA": "mua",
        "NON-SOMA": "non_soma",
        "NOISE": "noise",
    }
    return np.asarray([back_map.get(unittype_map.get(uid, "NOISE"), "noise") for uid in unit_ids])


def _sanitize_text_positions(fig: Any) -> None:
    """Convert 1-element ndarray positions on ``Text`` artists to scalars.

    Works around ``upsetplot`` 0.9.0 + numpy ≥ 2 incompatibility: the
    library uses ``np.diff(ax.get_xlim())`` (shape ``(1,)``) as a text
    margin, producing ``Text`` artists whose ``x``/``y`` become 1-element
    ndarrays; matplotlib's renderer then calls ``float(array([v]))`` which
    numpy 2 rejects with ``TypeError: only 0-dimensional arrays can be
    converted to Python scalars``. Called only on the upset figure — other
    widget outputs don't exhibit this pattern.
    """
    from matplotlib.text import Text

    for text in fig.findobj(match=Text):
        x, y = text.get_position()
        nx = x.item() if isinstance(x, np.ndarray) and x.size == 1 else x
        ny = y.item() if isinstance(y, np.ndarray) and y.size == 1 else y
        if nx is not x or ny is not y:
            text.set_position((nx, ny))


def _extract_figure(widget: Any) -> Any:
    """Return the matplotlib Figure attached to an SI widget, if any.

    SI widgets expose their Figure via ``widget.figure`` after the backend
    has rendered. We prefer that attribute; fall back to ``widget.fig`` for
    older widgets; otherwise return None and let the caller skip savefig.
    """
    for attr in ("figure", "fig"):
        fig = getattr(widget, attr, None)
        if fig is not None:
            return fig
    return None
