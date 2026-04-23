"""Curate-stage diagnostic plots.

Three Nature-style PNGs are emitted per probe:

1. ``quality_metrics_dist.png``  — 2x2 histograms of the four QMs.
2. ``unittype_pie.png``          — SUA/MUA/NON-SOMA/NOISE breakdown.
3. ``waveforms_by_unittype.png`` — 2x2 template-waveform overlays.

The public entry point is :func:`emit_all`; it wraps each individual plot in
a try/except so one failing figure never aborts the other two. matplotlib is
imported lazily at the top guarded by ``try/except`` so simply importing
:mod:`pynpxpipe.plots` in an environment without the ``[plots]`` extra does
not explode.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import matplotlib.pyplot as plt
    import numpy as np

    _HAS_MPL = True
except ImportError:  # pragma: no cover - environment-dependent
    _HAS_MPL = False

from pynpxpipe.plots.style import UNITTYPE_COLORS, figure_size, savefig

if TYPE_CHECKING:
    import pandas as pd


_LOG = logging.getLogger(__name__)

# The four unittypes rendered across pies / waveform panels (reading order).
_UNITTYPE_ORDER: tuple[str, ...] = ("SUA", "MUA", "NON-SOMA", "NOISE")

# Metric column names used for the quality-metric distribution plot.
_METRIC_COLUMNS: tuple[str, ...] = (
    "isi_violations_ratio",
    "amplitude_cutoff",
    "presence_ratio",
    "snr",
)


def emit_all(
    analyzer: Any,
    qm: pd.DataFrame,
    unittype_map: dict,
    probe_id: str,
    output_dir: Path,
    *,
    session_label: str | None = None,
    max_waveforms_per_type: int = 50,
) -> list[Path]:
    """Emit the three curate-stage diagnostic figures for a single probe.

    Args:
        analyzer: SpikeInterface ``SortingAnalyzer`` with ``templates`` and
            ``waveforms`` extensions computed. Used only for the waveform
            plot — the other two figures do not touch it.
        qm: Quality-metrics DataFrame indexed by ``unit_id`` with the four
            float columns listed in :data:`_METRIC_COLUMNS`.
        unittype_map: Full ``{unit_id: "SUA"|"MUA"|"NON-SOMA"|"NOISE"}``
            mapping *including* NOISE units (pre-curation distribution).
        probe_id: Probe identifier used in figure titles (e.g. ``"imec0"``).
        output_dir: Directory to write PNGs to. Created if missing.
        session_label: Optional session tag, currently unused but accepted
            to keep call-sites symmetric with other ``emit_all`` hooks.
        max_waveforms_per_type: Upper bound on individual waveform traces
            overlaid per sub-panel (mean line is always rendered).

    Returns:
        List of paths for figures that were written successfully. An empty
        list is returned when matplotlib is unavailable.
    """
    if not _HAS_MPL:
        _LOG.warning("matplotlib not available; skipping curate plots")
        return []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []

    for name, func in (
        ("quality_metrics_dist", _plot_quality_metrics_dist),
        ("unittype_pie", _plot_unittype_pie),
        ("waveforms_by_unittype", _plot_waveforms_by_unittype),
    ):
        try:
            out_path = func(
                analyzer=analyzer,
                qm=qm,
                unittype_map=unittype_map,
                probe_id=probe_id,
                output_dir=output_dir,
                max_waveforms_per_type=max_waveforms_per_type,
            )
            if out_path is not None:
                paths.append(out_path)
        except Exception as exc:  # noqa: BLE001 - diagnostic plot; never raise
            _LOG.warning("curate plot %s failed: %s", name, exc)

    return paths


# ---------------------------------------------------------------------------
# Private plotters
# ---------------------------------------------------------------------------


def _plot_quality_metrics_dist(
    *,
    qm: pd.DataFrame,
    probe_id: str,
    output_dir: Path,
    **_: Any,
) -> Path:
    """Render the 2x2 histogram grid of the four quality metrics."""
    fig, axes = plt.subplots(2, 2, figsize=figure_size(cols=2, height_ratio=0.8))
    axes_flat = axes.flatten()

    for ax, metric in zip(axes_flat, _METRIC_COLUMNS, strict=True):
        if metric in qm.columns:
            values = qm[metric].to_numpy(dtype=float, copy=False)
            values = values[~np.isnan(values)]
        else:
            values = np.array([], dtype=float)

        if values.size > 0:
            ax.hist(values, bins=min(30, max(5, values.size)), color="#4477AA", edgecolor="white")
        else:
            ax.text(
                0.5,
                0.5,
                "No data",
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=10,
                color="#888888",
            )
        ax.set_title(metric)
        ax.set_xlabel(metric)
        ax.set_ylabel("count")

    title = f"Quality metrics | {probe_id} | n_units={len(qm)}"
    return savefig(fig, output_dir / "quality_metrics_dist.png", title=title)


def _plot_unittype_pie(
    *,
    unittype_map: dict,
    probe_id: str,
    output_dir: Path,
    **_: Any,
) -> Path:
    """Render the unit-type pie chart with percent + absolute count labels."""
    counts: dict[str, int] = dict.fromkeys(_UNITTYPE_ORDER, 0)
    for utype in unittype_map.values():
        key = str(utype)
        counts[key] = counts.get(key, 0) + 1

    labels = [utype for utype in _UNITTYPE_ORDER if counts.get(utype, 0) > 0]
    sizes = [counts[utype] for utype in labels]
    colors = [UNITTYPE_COLORS.get(utype, "#888888") for utype in labels]

    fig, ax = plt.subplots(figsize=figure_size(cols=1, height_ratio=1.0))

    if sum(sizes) == 0:
        ax.text(0.5, 0.5, "No units", transform=ax.transAxes, ha="center", va="center")
        ax.set_axis_off()
    else:
        total = sum(sizes)

        def _autopct(pct: float, total_ref: int = total) -> str:
            absolute = int(round(pct * total_ref / 100.0))
            return f"{pct:.1f}%\n(n={absolute})"

        ax.pie(
            sizes,
            labels=labels,
            colors=colors,
            autopct=_autopct,
            startangle=90,
            wedgeprops={"linewidth": 0.8, "edgecolor": "white"},
        )
        ax.set_aspect("equal")

    title = f"Unit classification | {probe_id}"
    return savefig(fig, output_dir / "unittype_pie.png", title=title)


def _plot_waveforms_by_unittype(
    *,
    analyzer: Any,
    unittype_map: dict,
    probe_id: str,
    output_dir: Path,
    max_waveforms_per_type: int,
    **_: Any,
) -> Path | None:
    """Render the 2x2 template-waveform overlay, one panel per unittype."""
    templates_ext = analyzer.get_extension("templates")
    if templates_ext is None:
        _LOG.warning("templates extension unavailable; skipping waveform plot")
        return None

    templates = np.asarray(templates_ext.get_data())
    # Expected shape: (n_units, n_samples, n_channels)
    if templates.ndim != 3:
        _LOG.warning("unexpected template shape %s; skipping waveform plot", templates.shape)
        return None

    unit_ids = list(analyzer.sorting.get_unit_ids())
    n_units, n_samples, _n_channels = templates.shape
    if len(unit_ids) != n_units:
        _LOG.warning(
            "unit count mismatch between sorting (%d) and templates (%d)",
            len(unit_ids),
            n_units,
        )

    # Peak-channel trace per unit (max |amplitude| at the middle sample).
    mid = n_samples // 2
    peak_channels = np.argmax(np.abs(templates[:, mid, :]), axis=1)
    peak_waveforms = np.stack([templates[i, :, peak_channels[i]] for i in range(n_units)], axis=0)

    # Try to determine a time axis in ms if sampling rate is available.
    x_axis: np.ndarray
    x_label: str
    try:
        fs = float(analyzer.sorting.get_sampling_frequency())
        if fs > 0:
            x_axis = (np.arange(n_samples) - mid) / fs * 1000.0
            x_label = "time (ms)"
        else:
            x_axis = np.arange(n_samples)
            x_label = "sample"
    except Exception:  # noqa: BLE001 - any failure → fall back to sample index
        x_axis = np.arange(n_samples)
        x_label = "sample"

    # Build ordered lists of peak waveforms grouped by unittype.
    by_type: dict[str, list[np.ndarray]] = {utype: [] for utype in _UNITTYPE_ORDER}  # noqa: C420
    for idx, uid in enumerate(unit_ids):
        utype = unittype_map.get(uid)
        if utype in by_type:
            by_type[utype].append(peak_waveforms[idx])

    fig, axes = plt.subplots(2, 2, figsize=figure_size(cols=2, height_ratio=0.8))
    axes_flat = axes.flatten()

    for ax, utype in zip(axes_flat, _UNITTYPE_ORDER, strict=True):
        waveforms = by_type[utype]
        count = len(waveforms)
        color = UNITTYPE_COLORS.get(utype, "#888888")

        if count == 0:
            ax.text(
                0.5,
                0.5,
                "No units",
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=10,
                color="#888888",
            )
            for spine in ax.spines.values():
                spine.set_visible(False)
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_title(f"{utype} (n=0)")
            continue

        to_plot = waveforms[: max(1, int(max_waveforms_per_type))]
        for wf in to_plot:
            ax.plot(x_axis, wf, color=color, alpha=0.25, linewidth=0.6)

        mean_wf = np.mean(np.stack(waveforms, axis=0), axis=0)
        ax.plot(x_axis, mean_wf, color=color, linewidth=1.5)
        ax.set_title(f"{utype} (n={count})")
        ax.set_xlabel(x_label)
        ax.set_ylabel("amplitude (\u03bcV)")

    title = f"Template waveforms by unittype | {probe_id}"
    return savefig(fig, output_dir / "waveforms_by_unittype.png", title=title)
