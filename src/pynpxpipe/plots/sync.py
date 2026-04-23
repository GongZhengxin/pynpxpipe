"""Synchronize-stage diagnostic plots in Nature journal style.

Emits PNG figures covering the MATLAB reference pipeline output (plots #1-#13
from ``docs/ground_truth/step3_output_analysis.md`` Part 2) plus light
extensions where needed.

All public surface is :func:`emit_all`. Individual ``_plot_*`` helpers are
private implementation details; each is wrapped in a ``try/except`` inside
:func:`emit_all` so that a single failing plot never aborts the rest of the
diagnostic batch.

matplotlib is imported defensively at module load time so that a core
environment without the ``[plots]`` extra can still import this module
(only :func:`emit_all` raises :class:`RuntimeError` on invocation when
matplotlib is missing).
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from pynpxpipe.plots.style import PALETTE, figure_size, savefig

try:
    import matplotlib.pyplot as plt  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only without matplotlib
    plt = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from pynpxpipe.io.sync.bhv_nidq_align import TrialAlignment
    from pynpxpipe.io.sync.imec_nidq_align import SyncResult
    from pynpxpipe.io.sync.photodiode_calibrate import CalibratedOnsets

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def emit_all(
    sync_results: dict[str, SyncResult],
    ap_sync_times_map: dict[str, np.ndarray],
    nidq_sync_times: np.ndarray,
    trial_alignment: TrialAlignment,
    calibrated: CalibratedOnsets,
    output_dir: Path,
    *,
    pd_signal: np.ndarray | None = None,
    nidq_sample_rate: float | None = None,
    voltage_range: float = 5.0,
    monitor_delay_ms: float = 0.0,
    pre_ms: float = 10.0,
    post_ms: float = 100.0,
    session_label: str | None = None,
    eye_points: np.ndarray | None = None,
) -> list[Path]:
    """Emit all synchronize-stage diagnostic PNG figures.

    Each individual plot is wrapped in try/except so a single failure logs
    a warning but does not prevent the remaining plots from being produced.

    Args:
        sync_results: Mapping of probe_id to the IMEC↔NIDQ linear fit.
        ap_sync_times_map: Mapping of probe_id to rising-edge times extracted
            from the AP sync channel (seconds, IMEC clock).
        nidq_sync_times: Rising-edge times on the NIDQ sync channel (seconds).
        trial_alignment: BHV2↔NIDQ alignment result with per-stimulus event
            table.
        calibrated: Photodiode-calibrated stimulus onset times and quality flags.
        output_dir: Directory into which PNGs are written (created if needed).
        pd_signal: Optional raw NIDQ photodiode int16 samples; enables plots
            #6-#10, #12, #13.
        nidq_sample_rate: Sampling rate of ``pd_signal`` (Hz); required if
            ``pd_signal`` is provided.
        voltage_range: NIDQ analog range (V) for int16 → voltage conversion.
        monitor_delay_ms: Additional monitor delay applied in calibration
            (annotated only; not re-applied here).
        pre_ms: Pre-onset window size (ms) for photodiode rasters.
        post_ms: Post-onset window size (ms) for photodiode rasters.
        session_label: Optional prefix appended to figure titles.
        eye_points: Optional ``(N, 2)`` array of gaze samples in degrees used
            for ``eye_density.png``; when ``None`` the plot is skipped.

    Returns:
        List of paths that were successfully written (may be shorter than the
        theoretical maximum if some plots were skipped or errored).

    Raises:
        RuntimeError: If matplotlib is not installed.
    """
    if plt is None:
        raise RuntimeError(
            "matplotlib is required for pynpxpipe.plots.sync.emit_all — "
            "install the [plots] extra (e.g. `uv sync --extra plots`)."
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    # --- Per-probe interval + residual plots (MATLAB #1, #2, #3) ---
    for probe_id, sr in sync_results.items():
        ap_times = ap_sync_times_map.get(probe_id, np.array([]))
        _safe_plot(
            written,
            _plot_sync_intervals,
            probe_id=probe_id,
            ap_sync_times=ap_times,
            nidq_sync_times=nidq_sync_times,
            sync_result=sr,
            output_dir=output_dir,
            session_label=session_label,
        )
        _safe_plot(
            written,
            _plot_sync_residuals,
            probe_id=probe_id,
            ap_sync_times=ap_times,
            nidq_sync_times=nidq_sync_times,
            sync_result=sr,
            output_dir=output_dir,
            session_label=session_label,
        )

    # --- Stim events per trial histogram (MATLAB #4 approximation) ---
    _safe_plot(
        written,
        _plot_stim_events_per_trial,
        trial_alignment=trial_alignment,
        output_dir=output_dir,
        session_label=session_label,
    )

    # --- Eye density (MATLAB #5) ---
    if eye_points is not None:
        _safe_plot(
            written,
            _plot_eye_density,
            eye_points=eye_points,
            output_dir=output_dir,
            session_label=session_label,
        )

    # --- Photodiode family (MATLAB #6-#13) — requires pd_signal + sample rate ---
    # The trigger-aligned matrix feeds the raster / before-calibration plots
    # (PD step appears at t≈+latency). The after-calibration plot is built
    # separately by `_plot_photodiode_after_calibration`, which re-slices
    # the raw signal around `calibrated.stim_onset_nidq_s` — matching MATLAB
    # step #10 L220-225 and keeping the two families from double-correcting
    # (docs/todo.md V.6).
    if pd_signal is not None and nidq_sample_rate is not None:
        trigger_onsets_s = trial_alignment.trial_events_df["stim_onset_nidq_s"].to_numpy(
            dtype=np.float64
        )
        try:
            raw_matrix, time_ms, polarity_corrected = _build_pd_trial_matrix(
                pd_signal=pd_signal,
                nidq_sample_rate=nidq_sample_rate,
                voltage_range=voltage_range,
                stim_onset_nidq_s=trigger_onsets_s,
                pre_ms=pre_ms,
                post_ms=post_ms,
                align_to="trigger",
            )
        except Exception as exc:
            logger.warning("photodiode trial matrix extraction failed: %s", exc)
            raw_matrix = time_ms = polarity_corrected = None

        if raw_matrix is not None and time_ms is not None:
            _safe_plot(
                written,
                _plot_photodiode_imshow,
                matrix=raw_matrix,
                time_ms=time_ms,
                title_stub="Photodiode raw z-score",
                filename="photodiode_raw.png",
                output_dir=output_dir,
                session_label=session_label,
            )
            diff_matrix = np.diff(raw_matrix, axis=1)
            _safe_plot(
                written,
                _plot_photodiode_imshow,
                matrix=diff_matrix,
                time_ms=time_ms[1:],
                title_stub="Photodiode diff",
                filename="photodiode_diff.png",
                output_dir=output_dir,
                session_label=session_label,
            )
            _safe_plot(
                written,
                _plot_photodiode_imshow,
                matrix=np.abs(diff_matrix),
                time_ms=time_ms[1:],
                title_stub="Photodiode |diff|",
                filename="photodiode_diff_abs.png",
                output_dir=output_dir,
                session_label=session_label,
            )
            if polarity_corrected is not None:
                _safe_plot(
                    written,
                    _plot_photodiode_imshow,
                    matrix=polarity_corrected,
                    time_ms=time_ms,
                    title_stub="Photodiode polarity corrected",
                    filename="photodiode_polarity_corrected.png",
                    output_dir=output_dir,
                    session_label=session_label,
                )
            # Mean±std shaded bands (MATLAB #10, #12, #13)
            _safe_plot(
                written,
                _plot_photodiode_band,
                matrix=raw_matrix,
                time_ms=time_ms,
                title_stub="Photodiode before calibration",
                filename="photodiode_before_calibration.png",
                output_dir=output_dir,
                session_label=session_label,
            )
            _safe_plot(
                written,
                _plot_photodiode_after_calibration,
                pd_signal=pd_signal,
                nidq_sample_rate=nidq_sample_rate,
                voltage_range=voltage_range,
                calibrated_onsets_nidq_s=calibrated.stim_onset_nidq_s,
                pre_ms=pre_ms,
                post_ms=post_ms,
                output_dir=output_dir,
                session_label=session_label,
            )
            _safe_plot(
                written,
                _plot_photodiode_valid_only,
                matrix=raw_matrix,
                time_ms=time_ms,
                quality_flags=calibrated.quality_flags,
                output_dir=output_dir,
                session_label=session_label,
            )

    # --- Onset latency histogram (MATLAB #11) — works without pd_signal ---
    _safe_plot(
        written,
        _plot_onset_latency_hist,
        onset_latency_ms=calibrated.onset_latency_ms,
        monitor_delay_ms=monitor_delay_ms,
        output_dir=output_dir,
        session_label=session_label,
    )

    return written


# ---------------------------------------------------------------------------
# Internal safety wrapper
# ---------------------------------------------------------------------------


def _safe_plot(written: list[Path], fn: Any, **kwargs: Any) -> None:
    """Invoke ``fn(**kwargs)``; on exception log a warning and continue.

    Successful invocations append a :class:`Path` (or list of paths) to the
    ``written`` accumulator.
    """
    try:
        result = fn(**kwargs)
    except Exception as exc:
        logger.warning("sync plot %s failed: %s", getattr(fn, "__name__", "?"), exc)
        return
    if result is None:
        return
    if isinstance(result, (list, tuple)):
        for item in result:
            if isinstance(item, Path):
                written.append(item)
    elif isinstance(result, Path):
        written.append(result)


def _fmt_title(stub: str, session_label: str | None) -> str:
    return f"{session_label} | {stub}" if session_label else stub


# ---------------------------------------------------------------------------
# Plot #1 + #2: sync intervals (per-probe, two stacked axes)
# ---------------------------------------------------------------------------


def _plot_sync_intervals(
    probe_id: str,
    ap_sync_times: np.ndarray,
    nidq_sync_times: np.ndarray,
    sync_result: SyncResult,
    output_dir: Path,
    session_label: str | None,
) -> Path:
    """Plot sync-pulse intervals for one probe (AP and NIDQ, stacked)."""
    if ap_sync_times is None or len(ap_sync_times) < 2:
        raise ValueError(f"ap_sync_times too short for probe {probe_id}")
    if nidq_sync_times is None or len(nidq_sync_times) < 2:
        raise ValueError("nidq_sync_times too short")

    ap_dt_ms = np.diff(np.asarray(ap_sync_times)) * 1000.0
    nidq_dt_ms = np.diff(np.asarray(nidq_sync_times)) * 1000.0

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=figure_size(cols=2, height_ratio=0.45), sharex=False
    )
    ax1.plot(ap_dt_ms, color=PALETTE["blue"], linewidth=1.0)
    ax1.axhline(1000.0, color=PALETTE["black"], linewidth=0.6, linestyle="--", alpha=0.6)
    ax1.set_ylabel("pulse interval (ms)")
    ax1.set_title(f"AP sync intervals — {probe_id}", loc="left")

    ax2.plot(nidq_dt_ms, color=PALETTE["vermilion"], linewidth=1.0)
    ax2.axhline(1000.0, color=PALETTE["black"], linewidth=0.6, linestyle="--", alpha=0.6)
    ax2.set_xlabel("pulse index")
    ax2.set_ylabel("pulse interval (ms)")
    ax2.set_title("NIDQ sync intervals", loc="left")

    title = _fmt_title(
        f"Sync intervals | {probe_id} | n_repaired={sync_result.n_repaired}",
        session_label,
    )
    return savefig(fig, output_dir / f"sync_intervals_{probe_id}.png", title=title)


# ---------------------------------------------------------------------------
# Plot #3: residuals
# ---------------------------------------------------------------------------


def _plot_sync_residuals(
    probe_id: str,
    ap_sync_times: np.ndarray,
    nidq_sync_times: np.ndarray,
    sync_result: SyncResult,
    output_dir: Path,
    session_label: str | None,
) -> Path:
    """Plot per-pulse residuals after linear fit for one probe."""
    ap = np.asarray(ap_sync_times, dtype=np.float64)
    nq = np.asarray(nidq_sync_times, dtype=np.float64)
    n = min(len(ap), len(nq))
    if n == 0:
        raise ValueError("no sync pulses to compute residuals")
    predicted = sync_result.a * ap[:n] + sync_result.b
    residual_ms = (nq[:n] - predicted) * 1000.0

    fig, ax = plt.subplots(figsize=figure_size(cols=1, height_ratio=0.6))
    ax.plot(residual_ms, color=PALETTE["blue"], linewidth=1.0)
    ax.axhline(0.0, color=PALETTE["black"], linewidth=0.6, alpha=0.5)
    ax.set_ylim(-10.0, 10.0)
    ax.set_xlabel("pulse index")
    ax.set_ylabel("residual (ms)")

    title = _fmt_title(
        f"IMEC↔NIDQ residuals | {probe_id} | RMS={sync_result.residual_ms:.3f} ms",
        session_label,
    )
    return savefig(fig, output_dir / f"sync_residuals_{probe_id}.png", title=title)


# ---------------------------------------------------------------------------
# Plot #4: stim events per trial histogram
# ---------------------------------------------------------------------------


def _plot_stim_events_per_trial(
    trial_alignment: TrialAlignment,
    output_dir: Path,
    session_label: str | None,
) -> Path:
    """Plot histogram of stimulus-event counts per BHV2 trial_id."""
    df = trial_alignment.trial_events_df
    if df is None or len(df) == 0 or "trial_id" not in df.columns:
        raise ValueError("trial_events_df missing trial_id column")
    counts = df.groupby("trial_id").size().to_numpy()

    fig, ax = plt.subplots(figsize=figure_size(cols=1, height_ratio=0.7))
    max_c = int(counts.max()) if len(counts) else 1
    bins = np.arange(0.5, max_c + 1.5, 1.0)
    ax.hist(counts, bins=bins, color=PALETTE["blue"], edgecolor="white", linewidth=0.5)
    ax.set_xlabel("stim events per trial")
    ax.set_ylabel("count")

    title = _fmt_title("Stim events per trial", session_label)
    return savefig(fig, output_dir / "stim_events_per_trial.png", title=title)


# ---------------------------------------------------------------------------
# Plot #5: eye density
# ---------------------------------------------------------------------------


def _plot_eye_density(
    eye_points: np.ndarray,
    output_dir: Path,
    session_label: str | None,
) -> Path:
    """Plot 2D gaze density heat-map in degrees of visual angle."""
    arr = np.asarray(eye_points)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("eye_points must have shape (N, 2)")

    fig, ax = plt.subplots(figsize=figure_size(cols=1, height_ratio=1.0))
    h, xedges, yedges = np.histogram2d(
        arr[:, 0], arr[:, 1], bins=40, range=[[-8.0, 8.0], [-8.0, 8.0]]
    )
    im = ax.imshow(
        h.T,
        origin="lower",
        extent=(xedges[0], xedges[-1], yedges[0], yedges[-1]),
        aspect="equal",
        cmap="magma",
    )
    ax.set_xlabel("x (deg)")
    ax.set_ylabel("y (deg)")
    fig.colorbar(im, ax=ax, label="samples")

    title = _fmt_title("Eye position density", session_label)
    return savefig(fig, output_dir / "eye_density.png", title=title)


# ---------------------------------------------------------------------------
# Photodiode trial matrix construction
# ---------------------------------------------------------------------------


def _build_pd_trial_matrix(
    pd_signal: np.ndarray,
    nidq_sample_rate: float,
    voltage_range: float,
    stim_onset_nidq_s: np.ndarray,
    pre_ms: float,
    post_ms: float,
    align_to: Literal["trigger", "calibrated"] = "trigger",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract per-trial photodiode windows, z-scored + polarity-corrected.

    The ``align_to`` argument documents the semantics of the incoming
    ``stim_onset_nidq_s`` array. The internal math is identical either way
    — windows are always centered on the given onset. The distinction matters
    for downstream plotting:

    * ``"trigger"`` (default): onsets are NIDQ trigger times (event-code 64
      rising edges). The PD brightness transition appears at
      ``t ≈ +latency_ms`` in the extracted matrix. This is the correct input
      for :func:`_plot_photodiode_after_calibration`, which reverses the
      per-trial latency shift to bring the transition back to ``t=0``.
    * ``"calibrated"``: onsets are already calibrated PD-bright times. The
      transition is near ``t=0`` (modulo ``monitor_delay``). Passing this to
      ``_plot_photodiode_after_calibration`` would double-shift and produce
      a spurious baseline trough — see docs/todo.md V.6 for the incident.

    Returns:
        raw_matrix: ``(n_trials, n_timepoints)`` z-scored voltage matrix.
        time_ms: ``(n_timepoints,)`` time axis in milliseconds relative to onset.
        polarity_corrected: ``raw_matrix`` with per-trial sign flipped when the
            mean of the differenced trace is negative (cf. MATLAB polarity
            step).
    """
    _ = align_to  # documentation-only; internal logic is identical
    pd_v = np.asarray(pd_signal, dtype=np.float64) * voltage_range / 32767.0
    sr = float(nidq_sample_rate)
    pre_samples = int(round(pre_ms / 1000.0 * sr))
    post_samples = int(round(post_ms / 1000.0 * sr))
    n_total = pre_samples + post_samples
    time_ms = np.linspace(-pre_ms, post_ms, n_total, endpoint=False)

    n_trials = int(len(stim_onset_nidq_s))
    rows: list[np.ndarray] = []
    for t_s in stim_onset_nidq_s:
        if not np.isfinite(t_s):
            rows.append(np.full(n_total, np.nan))
            continue
        center = int(round(float(t_s) * sr))
        start = center - pre_samples
        stop = center + post_samples
        if start < 0 or stop > len(pd_v):
            rows.append(np.full(n_total, np.nan))
            continue
        seg = pd_v[start:stop]
        mean = np.nanmean(seg)
        std = np.nanstd(seg)
        if std < 1e-12:
            rows.append(np.full(n_total, np.nan))
            continue
        rows.append((seg - mean) / std)

    if not rows:
        raise ValueError("no valid photodiode trial windows")
    raw_matrix = np.vstack(rows) if n_trials else np.empty((0, n_total))

    # Polarity correction: flip rows where mean(diff) < 0.
    polarity = raw_matrix.copy()
    for i in range(polarity.shape[0]):
        row = polarity[i]
        if np.all(np.isnan(row)):
            continue
        dsign = np.nanmean(np.diff(row))
        if dsign < 0:
            polarity[i] = -row

    return raw_matrix, time_ms, polarity


# ---------------------------------------------------------------------------
# Plots #6-#9: photodiode rasters
# ---------------------------------------------------------------------------


def _plot_photodiode_imshow(
    matrix: np.ndarray,
    time_ms: np.ndarray,
    title_stub: str,
    filename: str,
    output_dir: Path,
    session_label: str | None,
) -> Path:
    """Imshow a ``(n_trials, n_timepoints)`` trial matrix with a diverging cmap."""
    if matrix is None or matrix.size == 0:
        raise ValueError(f"{filename}: empty matrix")
    n_trials = matrix.shape[0]
    fig, ax = plt.subplots(figsize=figure_size(cols=1, height_ratio=1.0))
    finite = matrix[np.isfinite(matrix)]
    vmax = float(np.nanmax(np.abs(finite))) if finite.size else 1.0
    if vmax == 0.0 or not np.isfinite(vmax):
        vmax = 1.0
    im = ax.imshow(
        matrix,
        aspect="auto",
        extent=(float(time_ms[0]), float(time_ms[-1]), n_trials, 0),
        cmap="RdBu_r",
        vmin=-vmax,
        vmax=vmax,
        interpolation="nearest",
    )
    ax.axvline(0.0, color=PALETTE["black"], linewidth=0.6, linestyle="--", alpha=0.7)
    ax.set_xlabel("time re stim onset (ms)")
    ax.set_ylabel("trial")
    fig.colorbar(im, ax=ax, label="z-score")

    title = _fmt_title(title_stub, session_label)
    return savefig(fig, output_dir / filename, title=title)


# ---------------------------------------------------------------------------
# Plot #10 / #12 / #13: mean±std bands
# ---------------------------------------------------------------------------


def _plot_photodiode_band(
    matrix: np.ndarray,
    time_ms: np.ndarray,
    title_stub: str,
    filename: str,
    output_dir: Path,
    session_label: str | None,
) -> Path:
    """Plot mean±std shaded band across trials of a photodiode matrix."""
    if matrix is None or matrix.size == 0:
        raise ValueError(f"{filename}: empty matrix")
    with warnings.catch_warnings():
        # Suppress "Mean of empty slice" when a full column is NaN — we still
        # want the plot even if a few time-columns lack valid trials.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        mean = np.nanmean(matrix, axis=0)
        std = np.nanstd(matrix, axis=0)
    fig, ax = plt.subplots(figsize=figure_size(cols=1, height_ratio=0.7))
    ax.plot(time_ms, mean, color=PALETTE["blue"], linewidth=1.2)
    ax.fill_between(time_ms, mean - std, mean + std, color=PALETTE["blue"], alpha=0.25)
    ax.axvline(0.0, color=PALETTE["black"], linewidth=0.6, linestyle="--", alpha=0.7)
    ax.set_xlabel("time re stim onset (ms)")
    ax.set_ylabel("z-score")

    title = _fmt_title(title_stub, session_label)
    return savefig(fig, output_dir / filename, title=title)


def _realign_by_latency(
    matrix: np.ndarray,
    time_ms: np.ndarray,
    onset_latency_ms: np.ndarray,
) -> np.ndarray:
    """Realign a trigger-aligned PD matrix so each trial's PD transition lands at t=0.

    Requires ``matrix`` to be trigger-aligned (i.e. PD transition appears at
    ``t ≈ +lat[i]`` in row ``i``). Each row is interpolated onto a grid
    shifted by ``-lat[i]`` so that the post-shift transition is at ``t=0``.

    Semantically: ``aligned[i][j] = matrix[i] evaluated at time_ms[j] + lat[i]``.
    That is, sample ``row`` at the later time ``time_ms + lat`` and store the
    result at ``time_ms``. Trials whose latency is non-finite pass through
    unchanged.
    """
    lat = np.asarray(onset_latency_ms, dtype=np.float64)
    n_trials = matrix.shape[0]
    aligned = np.full_like(matrix, np.nan)
    for i in range(n_trials):
        if i >= len(lat) or not np.isfinite(lat[i]):
            aligned[i] = matrix[i]
            continue
        row = matrix[i]
        if np.all(np.isnan(row)):
            continue
        # Treat row as samples at time_ms - lat[i], then query at time_ms →
        # equivalent to aligned[i][j] = row at time_ms[j] + lat[i].
        shifted_time = time_ms - lat[i]
        aligned[i] = np.interp(
            time_ms,
            shifted_time,
            row,
            left=np.nan,
            right=np.nan,
        )
    return aligned


def _plot_photodiode_after_calibration(
    pd_signal: np.ndarray,
    nidq_sample_rate: float,
    voltage_range: float,
    calibrated_onsets_nidq_s: np.ndarray,
    pre_ms: float,
    post_ms: float,
    output_dir: Path,
    session_label: str | None,
) -> Path:
    """Mean±std band after **recomputing** the PD trial matrix around calibrated onsets.

    Mirrors MATLAB ``Load_Data_function.m:220-225``: re-slices the raw NIDQ
    photodiode signal around each trial's calibrated (PD-bright) onset,
    then re-runs per-trial z-score + polarity correction before averaging.
    This produces the characteristic shape of MATLAB's "After time
    calibration" figure — clearly negative baseline for ``t < 0`` rising to
    a positive plateau for ``t > 0`` — because every window is pre-registered
    on the PD bright edge rather than on the digital trigger.

    The earlier implementation only time-shifted a trigger-aligned matrix
    via :func:`_realign_by_latency`, which preserved the original z-score
    values and therefore drew a shape that did not match the MATLAB
    reference figure.
    """
    _, time_ms, polarity = _build_pd_trial_matrix(
        pd_signal=pd_signal,
        nidq_sample_rate=nidq_sample_rate,
        voltage_range=voltage_range,
        stim_onset_nidq_s=calibrated_onsets_nidq_s,
        pre_ms=pre_ms,
        post_ms=post_ms,
        align_to="calibrated",
    )
    return _plot_photodiode_band(
        matrix=polarity,
        time_ms=time_ms,
        title_stub="Photodiode after calibration",
        filename="photodiode_after_calibration.png",
        output_dir=output_dir,
        session_label=session_label,
    )


def _plot_photodiode_valid_only(
    matrix: np.ndarray,
    time_ms: np.ndarray,
    quality_flags: np.ndarray,
    output_dir: Path,
    session_label: str | None,
) -> Path:
    """Plot mean±std band restricted to trials with ``quality_flag == 0``."""
    flags = np.asarray(quality_flags)
    if matrix is None or matrix.size == 0:
        raise ValueError("valid_only: empty matrix")
    mask = flags == 0
    if mask.sum() == 0:
        raise ValueError("valid_only: no good trials")
    subset = matrix[: len(flags)][mask]
    return _plot_photodiode_band(
        matrix=subset,
        time_ms=time_ms,
        title_stub=f"Photodiode valid trials only (n={int(mask.sum())})",
        filename="photodiode_valid_only.png",
        output_dir=output_dir,
        session_label=session_label,
    )


# ---------------------------------------------------------------------------
# Plot #11: onset latency histogram
# ---------------------------------------------------------------------------


def _plot_onset_latency_hist(
    onset_latency_ms: np.ndarray,
    monitor_delay_ms: float,
    output_dir: Path,
    session_label: str | None,
) -> Path:
    """Plot histogram of per-trial photodiode onset latency (ms)."""
    lat = np.asarray(onset_latency_ms, dtype=np.float64)
    lat = lat[np.isfinite(lat)]
    if lat.size == 0:
        raise ValueError("no finite onset latencies")

    fig, ax = plt.subplots(figsize=figure_size(cols=1, height_ratio=0.7))
    ax.hist(lat, bins=30, color=PALETTE["blue"], edgecolor="white", linewidth=0.5)
    ax.axvline(
        float(np.nanmin(lat)),
        color=PALETTE["vermilion"],
        linewidth=0.9,
        linestyle="--",
        label=f"min={np.nanmin(lat):.2f}",
    )
    ax.axvline(
        float(np.nanmax(lat)),
        color=PALETTE["vermilion"],
        linewidth=0.9,
        linestyle="--",
        label=f"max={np.nanmax(lat):.2f}",
    )
    ax.set_xlabel("onset latency (ms)")
    ax.set_ylabel("count")
    ax.legend(loc="best", frameon=False)

    title = _fmt_title(
        f"Onset latency distribution (monitor_delay={monitor_delay_ms:.1f} ms)",
        session_label,
    )
    return savefig(fig, output_dir / "onset_latency_hist.png", title=title)
