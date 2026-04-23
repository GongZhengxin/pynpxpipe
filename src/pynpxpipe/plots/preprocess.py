"""Preprocess-stage diagnostic plots in Nature journal style.

Emits up to three PNG figures per probe into
``{output_dir}/01_01_preprocessed/{probe_id}/figures/``:

1. ``bad_channels.png``             — bad vs good channels on probe layout.
2. ``traces_cmr_beforeafter.png``   — raw vs post-CMR traces, 8 channels.
3. ``motion_displacement.png``      — optional motion-correction heatmap.

Public surface is :func:`emit_all`; individual ``_plot_*`` helpers are
private. Each plot is wrapped in ``try/except`` so a single failure logs a
warning but never aborts the preprocess stage or the remaining figures.

matplotlib is imported defensively so that a core environment without the
``[plots]`` extra can still import this module — :func:`emit_all` simply
returns an empty list in that case.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from pynpxpipe.plots.style import PALETTE, figure_size, savefig

try:
    import matplotlib.pyplot as plt  # type: ignore[import-not-found]

    _HAS_MPL = True
except ImportError:  # pragma: no cover - environment-dependent
    plt = None  # type: ignore[assignment]
    _HAS_MPL = False

if TYPE_CHECKING:
    pass


_LOG = logging.getLogger(__name__)

# Traces plot config
_N_TRACE_CHANNELS = 8
_TRACE_Y_GAIN = 1.0  # per-channel y-offset multiplier (times channel std)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def emit_all(
    recording_raw: Any,
    recording_processed: Any,
    bad_channel_ids: list,
    probe_id: str,
    output_dir: Path,
    *,
    session_label: str | None = None,
    trace_sample_t0_s: float = 1.0,
    trace_duration_s: float = 0.5,
    motion_info: dict | None = None,
) -> list[Path]:
    """Emit all preprocess-stage diagnostic PNG figures for a single probe.

    Args:
        recording_raw: SpikeInterface ``BaseRecording`` for the unprocessed
            (or pre-CMR) probe. Used by the traces plot to render the "Before"
            trace panel.
        recording_processed: SpikeInterface ``BaseRecording`` after CMR. Used
            as the "After" trace panel and for channel-location lookup when
            ``recording_raw.get_channel_locations()`` fails.
        bad_channel_ids: List of channel ids flagged by
            ``detect_bad_channels``. May be empty.
        probe_id: Probe identifier used in figure titles (e.g. ``"imec0"``).
        output_dir: Directory into which PNGs are written (created if needed).
        session_label: Optional session tag, currently unused but accepted to
            keep call-sites symmetric with other ``emit_all`` hooks.
        trace_sample_t0_s: Start time (seconds) for the traces-before/after
            snippet.
        trace_duration_s: Duration (seconds) of the traces snippet.
        motion_info: Optional dict with keys ``"temporal_bins"``,
            ``"displacement"`` and ``"spatial_bins"`` — only present if
            motion correction was applied.

    Returns:
        List of paths for figures that were written successfully. An empty
        list is returned when matplotlib is unavailable.
    """
    if not _HAS_MPL:
        _LOG.warning("matplotlib not available; skipping preprocess plots")
        return []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []

    # --- 1. Bad channels ----------------------------------------------------
    try:
        out = _plot_bad_channels(
            recording_raw=recording_raw,
            recording_processed=recording_processed,
            bad_channel_ids=bad_channel_ids,
            probe_id=probe_id,
            output_dir=output_dir,
        )
        if out is not None:
            paths.append(out)
    except Exception as exc:  # noqa: BLE001 - diagnostic plot; never raise
        _LOG.warning("preprocess plot bad_channels failed: %s", exc)

    # --- 2. Traces before / after CMR --------------------------------------
    try:
        out = _plot_traces_before_after(
            recording_raw=recording_raw,
            recording_processed=recording_processed,
            probe_id=probe_id,
            output_dir=output_dir,
            trace_sample_t0_s=trace_sample_t0_s,
            trace_duration_s=trace_duration_s,
        )
        if out is not None:
            paths.append(out)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("preprocess plot traces_cmr_beforeafter failed: %s", exc)

    # --- 3. Motion displacement (optional) ---------------------------------
    if motion_info is not None:
        try:
            out = _plot_motion_displacement(
                motion_info=motion_info,
                probe_id=probe_id,
                output_dir=output_dir,
            )
            if out is not None:
                paths.append(out)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("preprocess plot motion_displacement failed: %s", exc)

    return paths


# ---------------------------------------------------------------------------
# Individual plots
# ---------------------------------------------------------------------------


def _plot_bad_channels(
    *,
    recording_raw: Any,
    recording_processed: Any,
    bad_channel_ids: list,
    probe_id: str,
    output_dir: Path,
) -> Path | None:
    """Render the bad-channels figure.

    Tries probe-layout scatter first (via ``get_channel_locations``). Falls
    back to a bar chart indexed by channel when locations are unavailable.
    """
    assert plt is not None

    locations = None
    try:
        locations = np.asarray(recording_raw.get_channel_locations())
    except Exception:
        try:
            locations = np.asarray(recording_processed.get_channel_locations())
        except Exception:
            locations = None

    n_bad = len(list(bad_channel_ids))
    fig, ax = plt.subplots(figsize=figure_size(cols=1, height_ratio=1.2))

    # Try to resolve channel ids (for scatter coloring).
    try:
        all_ids = list(recording_raw.channel_ids)
    except Exception:
        try:
            all_ids = list(recording_raw.get_channel_ids())
        except Exception:
            all_ids = []

    bad_set = {str(cid) for cid in bad_channel_ids}

    if locations is not None and locations.ndim == 2 and locations.shape[1] >= 2:
        xs = locations[:, 0]
        ys = locations[:, 1]
        if all_ids and len(all_ids) == len(xs):
            is_bad = np.array([str(cid) in bad_set for cid in all_ids], dtype=bool)
        else:
            # Fallback: treat first n_bad rows as bad (visual is approximate).
            is_bad = np.zeros(len(xs), dtype=bool)
            is_bad[:n_bad] = True
        ax.scatter(
            xs[~is_bad],
            ys[~is_bad],
            s=14,
            c=PALETTE["black"],
            label=f"good (n={(~is_bad).sum()})",
        )
        if is_bad.any():
            ax.scatter(
                xs[is_bad],
                ys[is_bad],
                s=18,
                c=PALETTE["vermilion"],
                label=f"bad (n={is_bad.sum()})",
            )
        ax.set_xlabel("x (μm)")
        ax.set_ylabel("y (μm)")
        ax.legend(loc="best", frameon=False)
    else:
        # Fallback bar chart: bad channel count per channel index.
        n_channels = 0
        try:
            n_channels = int(recording_raw.get_num_channels())
        except Exception:
            n_channels = max(n_bad, 1)
        idx = np.arange(n_channels)
        vals = np.zeros(n_channels, dtype=int)
        if all_ids and len(all_ids) == n_channels:
            for i, cid in enumerate(all_ids):
                if str(cid) in bad_set:
                    vals[i] = 1
        else:
            vals[:n_bad] = 1
        ax.bar(idx, vals, color=PALETTE["vermilion"], width=1.0)
        ax.set_xlabel("channel index")
        ax.set_ylabel("bad flag")
        ax.set_ylim(0, 1.2)

    title = f"Bad channels | {probe_id} | n_bad={n_bad}"
    return savefig(fig, output_dir / "bad_channels.png", title=title)


def _get_trace_snippet(
    recording: Any,
    t0_s: float,
    dur_s: float,
    channel_indices: np.ndarray,
) -> tuple[np.ndarray, float] | None:
    """Fetch a ``(n_samples, n_selected)`` trace snippet.

    Returns ``(traces, fs)`` on success, or ``None`` if fetching fails.
    """
    try:
        fs = float(recording.get_sampling_frequency())
        t0_samples = int(t0_s * fs)
        t1_samples = int((t0_s + dur_s) * fs)
        traces = np.asarray(
            recording.get_traces(
                start_frame=t0_samples,
                end_frame=t1_samples,
            )
        )
        if traces.ndim != 2:
            return None
        # Select subset of channels by index.
        valid = channel_indices[channel_indices < traces.shape[1]]
        if valid.size == 0:
            return None
        return traces[:, valid], fs
    except Exception as exc:
        _LOG.warning("get_traces failed: %s", exc)
        return None


def _draw_trace_panel(
    ax: Any,
    traces: np.ndarray,
    fs: float,
    color: str,
    panel_title: str,
) -> None:
    """Stack-plot ``traces`` on ``ax`` with a constant y-offset per channel."""
    n_samples, n_ch = traces.shape
    t_ms = np.arange(n_samples) / fs * 1000.0

    # Per-channel y-offset — use a generous fixed offset based on overall std.
    std = float(np.std(traces)) if traces.size else 1.0
    offset_step = max(std * 6.0, 1.0)

    for i in range(n_ch):
        ax.plot(t_ms, traces[:, i] + i * offset_step, color=color, linewidth=0.7)
    ax.set_xlabel("time (ms)")
    ax.set_ylabel("channel (offset)")
    ax.set_title(panel_title, fontsize=10)
    ax.set_yticks([])


def _plot_traces_before_after(
    *,
    recording_raw: Any,
    recording_processed: Any,
    probe_id: str,
    output_dir: Path,
    trace_sample_t0_s: float,
    trace_duration_s: float,
) -> Path | None:
    """Render the before/after-CMR traces figure.

    Picks ``_N_TRACE_CHANNELS`` evenly spaced channels via the processed
    recording's channel count, then tries to extract a matching snippet from
    both recordings. If the raw snippet cannot be fetched, degrades to a
    single-axis fallback with just the processed trace.
    """
    assert plt is not None

    try:
        n_ch = int(recording_processed.get_num_channels())
    except Exception:
        try:
            n_ch = int(recording_raw.get_num_channels())
        except Exception:
            n_ch = _N_TRACE_CHANNELS

    if n_ch < 1:
        _LOG.warning("no channels available for traces plot")
        return None

    k = min(_N_TRACE_CHANNELS, n_ch)
    channel_indices = np.linspace(0, n_ch - 1, k).astype(int)

    snippet_raw = _get_trace_snippet(
        recording_raw, trace_sample_t0_s, trace_duration_s, channel_indices
    )
    snippet_proc = _get_trace_snippet(
        recording_processed, trace_sample_t0_s, trace_duration_s, channel_indices
    )

    if snippet_proc is None and snippet_raw is None:
        _LOG.warning("both get_traces calls failed; skipping traces plot")
        return None

    title = f"Traces before/after CMR | {probe_id}"

    if snippet_raw is None or snippet_proc is None:
        # Degraded: single-axis fallback with whichever we have.
        traces, fs = snippet_proc if snippet_proc is not None else snippet_raw
        color = PALETTE["blue"] if snippet_proc is not None else PALETTE["black"]
        panel = "After CMR" if snippet_proc is not None else "Before CMR"
        fig, ax = plt.subplots(figsize=figure_size(cols=2, height_ratio=0.7))
        _draw_trace_panel(ax, traces, fs, color, panel)
        return savefig(fig, output_dir / "traces_cmr_beforeafter.png", title=title)

    traces_raw, fs_raw = snippet_raw
    traces_proc, fs_proc = snippet_proc

    fig, (ax_top, ax_bot) = plt.subplots(
        2, 1, figsize=figure_size(cols=2, height_ratio=0.7), sharex=True
    )
    _draw_trace_panel(ax_top, traces_raw, fs_raw, PALETTE["black"], "Before CMR")
    _draw_trace_panel(ax_bot, traces_proc, fs_proc, PALETTE["blue"], "After CMR")

    return savefig(fig, output_dir / "traces_cmr_beforeafter.png", title=title)


def _plot_motion_displacement(
    *,
    motion_info: dict,
    probe_id: str,
    output_dir: Path,
) -> Path | None:
    """Render the motion-correction displacement heatmap.

    Expects ``motion_info`` to expose ``"displacement"`` (ndarray) and ideally
    ``"temporal_bins"``, ``"spatial_bins"``. Displacement is shown as a
    red-blue diverging image centered at zero.
    """
    assert plt is not None

    disp = np.asarray(motion_info.get("displacement"))
    if disp.size == 0:
        _LOG.warning("motion_info['displacement'] is empty")
        return None

    # Normalize to 2D: (n_time, n_spatial).
    if disp.ndim == 1:
        disp2d = disp[:, np.newaxis]
    elif disp.ndim == 2:
        disp2d = disp
    else:
        _LOG.warning("unexpected displacement ndim=%d", disp.ndim)
        return None

    t_bins = motion_info.get("temporal_bins")
    s_bins = motion_info.get("spatial_bins")

    fig, ax = plt.subplots(figsize=figure_size(cols=2, height_ratio=0.6))

    vmax = float(np.nanmax(np.abs(disp2d))) if disp2d.size else 1.0
    if vmax == 0:
        vmax = 1.0

    # Image: x = time, y = space. imshow wants (n_rows, n_cols) with origin
    # in the top-left; put space on y by transposing so rows = spatial bins.
    img = disp2d.T  # shape (n_spatial, n_time)

    if t_bins is not None and s_bins is not None:
        t_arr = np.asarray(t_bins)
        s_arr = np.asarray(s_bins)
        extent = (
            float(t_arr[0]),
            float(t_arr[-1]),
            float(s_arr[0]),
            float(s_arr[-1]),
        )
        im = ax.imshow(
            img,
            cmap="RdBu_r",
            vmin=-vmax,
            vmax=vmax,
            aspect="auto",
            origin="lower",
            extent=extent,
        )
    else:
        im = ax.imshow(
            img,
            cmap="RdBu_r",
            vmin=-vmax,
            vmax=vmax,
            aspect="auto",
            origin="lower",
        )

    ax.set_xlabel("time (s)")
    ax.set_ylabel("depth (μm)")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("displacement (μm)")

    title = f"Motion displacement | {probe_id}"
    return savefig(fig, output_dir / "motion_displacement.png", title=title)
