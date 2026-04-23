"""Postprocess-stage diagnostic plots.

Nature-style PNG emitters invoked by ``PostprocessStage`` at the end of
each probe's postprocessing. Every plot is wrapped in ``try/except`` so
that a failure in one plot does not block the others or the main pipeline.

Public entry:
    :func:`emit_all` — returns a list of successfully-written PNG paths.
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt

    _HAS_MPL = True
except ImportError:  # pragma: no cover - matplotlib guarded at call-site
    _HAS_MPL = False

from pynpxpipe.plots.style import PALETTE, figure_size, savefig

if TYPE_CHECKING:
    from spikeinterface.core import SortingAnalyzer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def emit_all(
    analyzer: SortingAnalyzer,
    unit_scores: dict[str, dict[str, Any]],
    behavior_events_df: pd.DataFrame,
    stim_onset_times: np.ndarray,
    probe_id: str,
    output_dir: Path,
    *,
    session_label: str | None = None,
    top_n: int = 9,
    psth_pre_s: float = 0.1,
    psth_post_s: float = 0.4,
    psth_bin_ms: float = 10.0,
) -> list[Path]:
    """Render all postprocess diagnostic PNGs.

    Args:
        analyzer: SpikeInterface ``SortingAnalyzer`` with extensions already
            computed (``random_spikes``, ``waveforms``, ``templates``,
            ``unit_locations``, ``template_similarity``).
        unit_scores: Mapping ``{str(uid): {"slay_score": float|None,
            "is_visual": bool}}``.
        behavior_events_df: Trial-level events DataFrame from synchronize.
        stim_onset_times: IMEC-clock stimulus onset times (seconds) for
            this probe. NaNs are filtered before PSTH/raster windowing.
        probe_id: Probe identifier used in titles and filenames.
        output_dir: Target directory; created if missing.
        session_label: Optional session id woven into titles.
        top_n: Number of units plotted in PSTH / raster grids.
        psth_pre_s: Pre-stimulus window (seconds).
        psth_post_s: Post-stimulus window (seconds).
        psth_bin_ms: PSTH bin width (milliseconds).

    Returns:
        List of paths successfully written. Missing matplotlib or per-plot
        exceptions simply shrink the returned list (warnings logged).
    """
    if not _HAS_MPL:
        logger.warning("matplotlib not installed; skipping postprocess plots")
        return []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    _suffix = f" | {session_label}" if session_label else ""

    # -------- unit_locations --------
    try:
        path = _plot_unit_locations(
            analyzer, unit_scores, probe_id, output_dir, title_suffix=_suffix
        )
        if path is not None:
            written.append(path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("unit_locations plot failed: %s", exc)

    # -------- slay_distribution --------
    try:
        path = _plot_slay_distribution(unit_scores, probe_id, output_dir, title_suffix=_suffix)
        if path is not None:
            written.append(path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("slay_distribution plot failed: %s", exc)

    # -------- stim_coverage --------
    try:
        path = _plot_stim_coverage(behavior_events_df, probe_id, output_dir, title_suffix=_suffix)
        if path is not None:
            written.append(path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("stim_coverage plot failed: %s", exc)

    # -------- psth_top_units & raster_top_units (share top-unit selection) --------
    top_uids = _select_top_units(analyzer, unit_scores, top_n=top_n)
    fs = _safe_fs(analyzer)
    valid_onsets = (
        stim_onset_times[~np.isnan(stim_onset_times)]
        if stim_onset_times is not None
        else np.array([], dtype=float)
    )

    try:
        path = _plot_psth_top_units(
            analyzer,
            unit_scores,
            top_uids,
            valid_onsets,
            fs=fs,
            probe_id=probe_id,
            output_dir=output_dir,
            top_n=top_n,
            pre_s=psth_pre_s,
            post_s=psth_post_s,
            bin_ms=psth_bin_ms,
            title_suffix=_suffix,
        )
        if path is not None:
            written.append(path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("psth_top_units plot failed: %s", exc)

    try:
        path = _plot_raster_top_units(
            analyzer,
            unit_scores,
            top_uids,
            valid_onsets,
            fs=fs,
            probe_id=probe_id,
            output_dir=output_dir,
            top_n=top_n,
            pre_s=psth_pre_s,
            post_s=psth_post_s,
            title_suffix=_suffix,
        )
        if path is not None:
            written.append(path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("raster_top_units plot failed: %s", exc)

    return written


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_fs(analyzer: SortingAnalyzer) -> float:
    """Read sampling frequency from analyzer; default to 30 kHz on failure."""
    try:
        return float(analyzer.sorting.get_sampling_frequency())
    except Exception:
        return 30000.0


def _select_top_units(
    analyzer: SortingAnalyzer,
    unit_scores: dict[str, dict[str, Any]],
    *,
    top_n: int,
) -> list:
    """Pick up to ``top_n`` unit ids ranked by SLAY score.

    Visual (is_visual=True) units are preferred; if fewer than ``top_n``
    visual units have a finite SLAY score, the remainder is padded from
    the remaining units (still ranked by SLAY).
    """
    try:
        unit_ids = list(analyzer.sorting.get_unit_ids())
    except Exception:
        return []

    def _score(uid: Any) -> float:
        entry = unit_scores.get(str(uid), {}) or {}
        s = entry.get("slay_score")
        if s is None:
            return float("-inf")
        try:
            sf = float(s)
        except (TypeError, ValueError):
            return float("-inf")
        return sf if not math.isnan(sf) else float("-inf")

    def _is_visual(uid: Any) -> bool:
        entry = unit_scores.get(str(uid), {}) or {}
        return bool(entry.get("is_visual", False))

    visual = sorted([u for u in unit_ids if _is_visual(u)], key=_score, reverse=True)
    if len(visual) >= top_n:
        return visual[:top_n]

    # Pad with remaining units ranked by SLAY
    remaining = sorted([u for u in unit_ids if u not in visual], key=_score, reverse=True)
    return (visual + remaining)[:top_n]


def _get_spike_times_s(analyzer: SortingAnalyzer, uid: Any, fs: float) -> np.ndarray:
    """Return spike times in seconds for ``uid`` from segment 0."""
    try:
        samples = analyzer.sorting.get_unit_spike_train(uid, segment_index=0)
    except Exception:
        return np.array([], dtype=float)
    return (
        np.asarray(samples, dtype=float) / float(fs) if fs > 0 else np.asarray(samples, dtype=float)
    )


# ---------------------------------------------------------------------------
# Individual plots
# ---------------------------------------------------------------------------


def _plot_unit_locations(
    analyzer: SortingAnalyzer,
    unit_scores: dict[str, dict[str, Any]],
    probe_id: str,
    output_dir: Path,
    *,
    title_suffix: str = "",
) -> Path | None:
    """Scatter of unit (x, y) locations coloured by is_visual."""
    try:
        ext = analyzer.get_extension("unit_locations")
        locations = np.asarray(ext.get_data())
    except Exception as exc:
        logger.warning("unit_locations extension unavailable: %s", exc)
        return None

    if locations.ndim != 2 or locations.shape[0] == 0:
        logger.warning("unit_locations empty or malformed (shape=%s)", locations.shape)
        return None

    xy = locations[:, :2]
    try:
        unit_ids = list(analyzer.sorting.get_unit_ids())
    except Exception:
        unit_ids = list(range(len(xy)))

    colors = []
    for uid in unit_ids[: len(xy)]:
        entry = unit_scores.get(str(uid), {}) or {}
        is_vis = bool(entry.get("is_visual", False))
        colors.append(PALETTE["blue"] if is_vis else PALETTE["black"])
    # Pad if unit_ids shorter than xy for any reason
    while len(colors) < len(xy):
        colors.append(PALETTE["black"])

    fig, ax = plt.subplots(figsize=figure_size(cols=1, height_ratio=1.2))
    ax.scatter(xy[:, 0], xy[:, 1], s=20, c=colors, edgecolors="none")
    ax.set_xlabel("x (\u03bcm)")
    ax.set_ylabel("depth (\u03bcm)")

    title = f"Unit locations | {probe_id} | n_units={len(xy)}{title_suffix}"
    out = output_dir / "unit_locations.png"
    return savefig(fig, out, title=title)


def _plot_slay_distribution(
    unit_scores: dict[str, dict[str, Any]],
    probe_id: str,
    output_dir: Path,
    *,
    title_suffix: str = "",
) -> Path | None:
    """Histogram of SLAY scores (None entries dropped)."""
    finite_scores: list[float] = []
    for entry in (unit_scores or {}).values():
        if not isinstance(entry, dict):
            continue
        s = entry.get("slay_score")
        if s is None:
            continue
        try:
            sf = float(s)
        except (TypeError, ValueError):
            continue
        if not math.isnan(sf):
            finite_scores.append(sf)

    if not finite_scores:
        logger.info("no finite SLAY scores; skipping slay_distribution plot")
        return None

    fig, ax = plt.subplots(figsize=figure_size(cols=1))
    ax.hist(finite_scores, bins=20, color=PALETTE["sky"], edgecolor=PALETTE["black"])
    mean_val = float(np.mean(finite_scores))
    ax.axvline(
        mean_val,
        color=PALETTE["vermilion"],
        linestyle="--",
        linewidth=1.0,
        label=f"mean = {mean_val:.3f}",
    )
    ax.set_xlabel("SLAY score")
    ax.set_ylabel("unit count")
    ax.legend(loc="best", frameon=False)

    title = f"SLAY score distribution | {probe_id}{title_suffix}"
    out = output_dir / "slay_distribution.png"
    return savefig(fig, out, title=title)


def _plot_stim_coverage(
    behavior_events_df: pd.DataFrame,
    probe_id: str,
    output_dir: Path,
    *,
    title_suffix: str = "",
) -> Path | None:
    """Bar plot of valid trial count per stim_index (MATLAB #15)."""
    if behavior_events_df is None or len(behavior_events_df) == 0:
        logger.info("behavior_events_df empty; skipping stim_coverage plot")
        return None

    if "stim_index" not in behavior_events_df.columns:
        logger.info("stim_index column missing; skipping stim_coverage plot")
        return None

    df = behavior_events_df
    if "trial_valid" in df.columns:
        valid_mask = (df["trial_valid"].fillna(1) > 0) | df["trial_valid"].isna()
        df = df[valid_mask]

    counts = df["stim_index"].dropna().value_counts().sort_index()
    if len(counts) == 0:
        logger.info("no stim_index values after filtering; skipping stim_coverage plot")
        return None

    fig, ax = plt.subplots(figsize=figure_size(cols=1))
    ax.bar(
        np.arange(len(counts)),
        counts.values,
        color=PALETTE["orange"],
        edgecolor=PALETTE["black"],
        linewidth=0.5,
    )
    ax.set_xlabel("stim_index")
    ax.set_ylabel("valid trial count")

    # Keep tick labels readable for large numbers of stimuli
    if len(counts) <= 20:
        ax.set_xticks(np.arange(len(counts)))
        ax.set_xticklabels([str(x) for x in counts.index], rotation=0)
    else:
        # sparser ticks
        step = max(1, len(counts) // 10)
        idxs = np.arange(0, len(counts), step)
        ax.set_xticks(idxs)
        ax.set_xticklabels([str(counts.index[i]) for i in idxs], rotation=45)

    title = f"Stimulus coverage | {probe_id} | n_images={len(counts)}{title_suffix}"
    out = output_dir / "stim_coverage.png"
    return savefig(fig, out, title=title)


def _prepare_grid_axes(top_n: int) -> tuple[Any, Any, int, int]:
    """Create a square-ish grid that fits ``top_n`` plots. Returns fig, axes, nrows, ncols."""
    ncols = int(math.ceil(math.sqrt(top_n)))
    nrows = int(math.ceil(top_n / ncols))
    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=figure_size(cols=2, height_ratio=0.9),
        squeeze=False,
    )
    return fig, axes, nrows, ncols


def _hide_axis(ax: Any) -> None:
    """Hide spines and ticks on an empty subplot."""
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])


def _plot_psth_top_units(
    analyzer: SortingAnalyzer,
    unit_scores: dict[str, dict[str, Any]],
    top_uids: list,
    valid_onsets: np.ndarray,
    *,
    fs: float,
    probe_id: str,
    output_dir: Path,
    top_n: int,
    pre_s: float,
    post_s: float,
    bin_ms: float,
    title_suffix: str = "",
) -> Path | None:
    """3x3 grid of PSTHs for the top units."""
    fig, axes, nrows, ncols = _prepare_grid_axes(top_n)
    window_s = pre_s + post_s
    n_bins = max(1, int(round(window_s * 1000.0 / bin_ms)))
    bin_edges = np.linspace(-pre_s, post_s, n_bins + 1)
    bin_centers_ms = (bin_edges[:-1] + bin_edges[1:]) * 500.0  # to ms, center
    bin_width_s = window_s / n_bins

    n_trials = int(len(valid_onsets))

    for slot in range(nrows * ncols):
        r, c = divmod(slot, ncols)
        ax = axes[r][c]
        if slot >= len(top_uids):
            _hide_axis(ax)
            continue

        uid = top_uids[slot]
        spike_times_s = _get_spike_times_s(analyzer, uid, fs)

        counts = np.zeros(n_bins, dtype=float)
        if n_trials > 0 and len(spike_times_s) > 0:
            for onset in valid_onsets:
                w_start = onset - pre_s
                w_end = onset + post_s
                mask = (spike_times_s >= w_start) & (spike_times_s < w_end)
                rel = spike_times_s[mask] - onset
                if rel.size > 0:
                    h, _ = np.histogram(rel, bins=bin_edges)
                    counts += h

        # Convert to firing rate (Hz)
        denom = max(1, n_trials) * max(bin_width_s, 1e-12)
        rates = counts / denom

        ax.bar(
            bin_centers_ms,
            rates,
            width=bin_ms * 0.9,
            color=PALETTE["blue"],
            edgecolor="none",
        )
        ax.axvline(0.0, color=PALETTE["vermilion"], linestyle="--", linewidth=0.8)

        entry = unit_scores.get(str(uid), {}) or {}
        s_raw = entry.get("slay_score")
        try:
            s_val = float(s_raw) if s_raw is not None else float("nan")
        except (TypeError, ValueError):
            s_val = float("nan")
        s_str = "nan" if math.isnan(s_val) else f"{s_val:.2f}"
        ax.set_title(f"unit {uid} | SLAY={s_str}", fontsize=10)

        # Labels only on left column / bottom row to reduce clutter
        if c == 0:
            ax.set_ylabel("rate (Hz)")
        if r == nrows - 1:
            ax.set_xlabel("time from stim onset (ms)")

    title = f"PSTH (top {top_n} SLAY units) | {probe_id}{title_suffix}"
    out = output_dir / "psth_top_units.png"
    return savefig(fig, out, title=title)


def _plot_raster_top_units(
    analyzer: SortingAnalyzer,
    unit_scores: dict[str, dict[str, Any]],
    top_uids: list,
    valid_onsets: np.ndarray,
    *,
    fs: float,
    probe_id: str,
    output_dir: Path,
    top_n: int,
    pre_s: float,
    post_s: float,
    title_suffix: str = "",
) -> Path | None:
    """3x3 grid of spike rasters (trial on y, time on x) for top units."""
    fig, axes, nrows, ncols = _prepare_grid_axes(top_n)
    n_trials = int(len(valid_onsets))

    for slot in range(nrows * ncols):
        r, c = divmod(slot, ncols)
        ax = axes[r][c]
        if slot >= len(top_uids):
            _hide_axis(ax)
            continue

        uid = top_uids[slot]
        spike_times_s = _get_spike_times_s(analyzer, uid, fs)

        xs: list[float] = []
        ys: list[int] = []
        if n_trials > 0 and len(spike_times_s) > 0:
            for trial_idx, onset in enumerate(valid_onsets):
                w_start = onset - pre_s
                w_end = onset + post_s
                mask = (spike_times_s >= w_start) & (spike_times_s < w_end)
                rel_ms = (spike_times_s[mask] - onset) * 1000.0
                if rel_ms.size > 0:
                    xs.extend(rel_ms.tolist())
                    ys.extend([trial_idx] * rel_ms.size)

        if xs:
            ax.scatter(xs, ys, s=1, c=PALETTE["black"], marker="|")
        ax.axvline(0.0, color=PALETTE["vermilion"], linestyle="--", linewidth=0.8)
        ax.set_xlim(-pre_s * 1000.0, post_s * 1000.0)
        if n_trials > 0:
            ax.set_ylim(-0.5, n_trials - 0.5)

        entry = unit_scores.get(str(uid), {}) or {}
        s_raw = entry.get("slay_score")
        try:
            s_val = float(s_raw) if s_raw is not None else float("nan")
        except (TypeError, ValueError):
            s_val = float("nan")
        s_str = "nan" if math.isnan(s_val) else f"{s_val:.2f}"
        ax.set_title(f"unit {uid} | SLAY={s_str}", fontsize=10)

        if c == 0:
            ax.set_ylabel("trial")
        if r == nrows - 1:
            ax.set_xlabel("time from stim onset (ms)")

    title = f"Spike raster (top {top_n} SLAY units) | {probe_id}{title_suffix}"
    out = output_dir / "raster_top_units.png"
    return savefig(fig, out, title=title)
