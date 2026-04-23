"""VII.B - matched-pair waveform gallery (Nature format).

Sample 9 matched pairs (3 high / 3 mid / 3 low cosine) + 3 unmatched, overlay
ref (blue, solid) and ours (orange, dashed) templates on the 5 channels that
are SPATIALLY CLOSEST to the peak channel. Neighbor selection is by Euclidean
distance in ``probe.contact_positions``, not by channel index, so the result
is correct on 2-column-staggered (NPX 1.0) and multi-shank (NPX 2.0) probes.

Output:
  diag/pair_waveforms.png (600 dpi)
  diag/pair_waveforms.svg
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import spikeinterface as si

REF_ANALYZER = Path(r"F:/#Datasets/demo_rawdata/processed_good/SI/analyzer")
OURS_ANALYZER = Path(r"F:/#Datasets/demo_rawdata/processed_pynpxpipe/06_postprocessed/imec0")
OUT_DIR = Path("diag")
SEED = 0
N_CHANNELS = 5  # spatially closest channels to peak (includes peak itself)


def _nature_rc() -> None:
    plt.rcParams.update({
        "font.family": "Arial",
        "font.size": 6,
        "axes.linewidth": 0.4,
        "xtick.major.width": 0.4,
        "ytick.major.width": 0.4,
        "xtick.labelsize": 5,
        "ytick.labelsize": 5,
        "lines.linewidth": 0.7,
        "savefig.dpi": 600,
        "savefig.bbox": "tight",
    })


def _crop_template(t: np.ndarray, ms_before: float, ms_after: float,
                   target_before: float, target_after: float, fs: float) -> np.ndarray:
    """Crop (n_samples, n_channels) to a common window around peak."""
    peak_idx = int(round(ms_before * fs / 1000.0))
    n_before = int(round(target_before * fs / 1000.0))
    n_after = int(round(target_after * fs / 1000.0))
    return t[peak_idx - n_before : peak_idx + n_after, :]


def _peak_channel(t: np.ndarray) -> int:
    """Return channel index with max peak-to-peak amplitude."""
    p2p = t.max(axis=0) - t.min(axis=0)
    return int(np.argmax(p2p))


def _spatial_neighbors(contacts: np.ndarray, peak_ch: int, n: int) -> list[int]:
    """Return indices of ``n`` channels spatially closest to ``peak_ch``."""
    dists = np.linalg.norm(contacts - contacts[peak_ch], axis=1)
    n = min(n, len(contacts))
    return [int(c) for c in np.argsort(dists)[:n]]


def _plot_waveform_pair(
    ax: plt.Axes,
    t_ref: np.ndarray | None,
    t_ours: np.ndarray | None,
    peak_ch: int,
    contacts: np.ndarray,
    times_ms: np.ndarray,
    title: str,
) -> None:
    """Plot spatially-nearest 5 channel traces stacked vertically by Y depth."""
    reference_t = t_ref if t_ref is not None else t_ours
    if reference_t is None:
        ax.axis("off")
        return

    neighbors = _spatial_neighbors(contacts, peak_ch, N_CHANNELS)
    # Sort so highest Y goes on top (consistent with depth-up-is-top convention).
    ys = contacts[neighbors, 1]
    order = np.argsort(-ys)
    channels = [neighbors[i] for i in order]
    n_ch = len(channels)

    # Vertical offset based on combined peak-to-peak amplitude.
    p2p_list: list[float] = []
    for ch in channels:
        if t_ref is not None:
            p2p_list.append(float(t_ref[:, ch].max() - t_ref[:, ch].min()))
        if t_ours is not None:
            p2p_list.append(float(t_ours[:, ch].max() - t_ours[:, ch].min()))
    sep = max(float(np.max(p2p_list)) * 1.5, 30.0)

    t_span = float(times_ms[-1] - times_ms[0])
    x_label_pad = t_span * 0.03
    x_label_pos = float(times_ms[-1]) + x_label_pad

    for i, ch in enumerate(channels):
        offset = (n_ch - 1 - i) * sep  # i=0 -> top
        if t_ref is not None:
            ax.plot(times_ms, t_ref[:, ch] + offset, color="tab:blue", lw=0.7)
        if t_ours is not None:
            ax.plot(times_ms, t_ours[:, ch] + offset, color="tab:orange",
                    lw=0.7, ls="--")
        ax.axhline(offset, color="grey", lw=0.3, alpha=0.5)
        x, y = contacts[ch]
        ax.text(
            x_label_pos, offset,
            f"ch{ch}\n({x:.0f},{y:.0f})",
            fontsize=4.5, va="center", ha="left", color="dimgrey",
        )

    # Scale bar bottom-left: 1 ms horizontal × 100 µV vertical.
    x0 = float(times_ms[0]) + t_span * 0.05
    y0 = -sep * 0.5
    ax.plot([x0, x0 + 1.0], [y0, y0], color="k", lw=1.0)
    ax.plot([x0, x0], [y0, y0 + 100.0], color="k", lw=1.0)
    ax.text(x0 + 0.5, y0 - sep * 0.18, "1 ms",
            ha="center", va="top", fontsize=4.5)
    ax.text(x0 - t_span * 0.025, y0 + 50.0, "100 µV",
            ha="right", va="center", fontsize=4.5, rotation=90)

    ax.set_title(title, fontsize=6, pad=2)
    ax.set_xlim(float(times_ms[0]), x_label_pos + t_span * 0.2)
    ax.set_ylim(y0 - sep * 0.5, (n_ch - 1) * sep + sep * 0.6)
    for spine in ("top", "right", "bottom", "left"):
        ax.spines[spine].set_visible(False)
    ax.set_xticks([])
    ax.set_yticks([])


def _select_samples(pairing: pd.DataFrame,
                    rng: np.random.Generator) -> dict[str, list]:
    matched = pairing[pairing["matched"]].sort_values("cos", ascending=False)

    def _pick(df: pd.DataFrame, n: int) -> list[int]:
        if len(df) <= n:
            return df.index.tolist()
        return rng.choice(df.index.values, size=n, replace=False).tolist()

    high = matched[matched["cos"] >= 0.97]
    mid = matched[(matched["cos"] >= 0.85) & (matched["cos"] < 0.97)]
    low = matched[(matched["cos"] >= 0.60) & (matched["cos"] < 0.85)]

    samples = {
        "high_match": _pick(high, 3),
        "mid_match": _pick(mid, 3),
        "low_match": _pick(low, 3),
    }

    unmatched = pairing[~pairing["matched"]]
    if len(unmatched) >= 3:
        samples["unmatched"] = _pick(unmatched, 3)
    else:
        samples["unmatched"] = unmatched.index.tolist()
    return samples


def main() -> None:
    _nature_rc()
    OUT_DIR.mkdir(exist_ok=True)
    pairing = pd.read_csv(OUT_DIR / "unit_pairing.csv")

    print("Loading analyzers...")
    ref_a = si.load_sorting_analyzer(folder=str(REF_ANALYZER), load_extensions=True)
    ours_a = si.load_sorting_analyzer(folder=str(OURS_ANALYZER), load_extensions=True)
    ref_tpl_all = ref_a.get_extension("templates").get_data(operator="average")
    ours_tpl_all = ours_a.get_extension("templates").get_data(operator="average")
    ref_unit_ids = np.asarray(ref_a.unit_ids)
    ours_unit_ids = np.asarray(ours_a.unit_ids)
    fs = float(ref_a.sampling_frequency)
    ref_params = ref_a.get_extension("templates").params
    ours_params = ours_a.get_extension("templates").params
    ref_ms_before = float(ref_params["ms_before"])
    ref_ms_after = float(ref_params["ms_after"])
    ours_ms_before = float(ours_params["ms_before"])
    ours_ms_after = float(ours_params["ms_after"])
    common_before = min(ref_ms_before, ours_ms_before)
    common_after = min(ref_ms_after, ours_ms_after)
    n_samples = int(round((common_before + common_after) * fs / 1000.0))
    times_ms = (np.arange(n_samples) - int(round(common_before * fs / 1000.0))) * 1000.0 / fs

    ref_probe = ref_a.get_probe()
    ours_probe = ours_a.get_probe()
    ref_contacts = np.asarray(ref_probe.contact_positions)
    ours_contacts = np.asarray(ours_probe.contact_positions)
    print(f"ref contacts shape {ref_contacts.shape}, ours {ours_contacts.shape}")
    print(f"common window [-{common_before:.1f}, +{common_after:.1f}] ms "
          f"-> {n_samples} samples")

    ref_id2row = {int(u): i for i, u in enumerate(ref_unit_ids)}
    ours_id2row = {int(u): i for i, u in enumerate(ours_unit_ids)}

    def _get_ref(ks_id: int) -> np.ndarray | None:
        row = ref_id2row.get(int(ks_id))
        if row is None:
            return None
        return _crop_template(ref_tpl_all[row], ref_ms_before, ref_ms_after,
                              common_before, common_after, fs)

    def _get_ours(ks_id: int) -> np.ndarray | None:
        row = ours_id2row.get(int(ks_id))
        if row is None:
            return None
        return _crop_template(ours_tpl_all[row], ours_ms_before, ours_ms_after,
                              common_before, common_after, fs)

    rng = np.random.default_rng(SEED)
    samples = _select_samples(pairing, rng)
    groups = [("high_match", "matched (cos>=0.97)"),
              ("mid_match", "matched (0.85-0.97)"),
              ("low_match", "matched (0.60-0.85)"),
              ("unmatched", "unmatched (sim<0.60)")]

    fig, axes = plt.subplots(4, 3, figsize=(8.0, 8.0), constrained_layout=True)
    for row_i, (key, group_label) in enumerate(groups):
        idxs = samples[key]
        for col_i in range(3):
            ax = axes[row_i, col_i]
            if col_i >= len(idxs):
                ax.axis("off")
                continue
            rec = pairing.loc[idxs[col_i]]
            t_ref = _get_ref(int(rec["ks_id_ref"]))
            t_ours = _get_ours(int(rec["ks_id_ours"]))
            if t_ref is None and t_ours is None:
                ax.axis("off")
                continue
            reference_t = t_ref if t_ref is not None else t_ours
            peak_ch = _peak_channel(reference_t)
            # Pick contacts consistent with which side the peak came from.
            contacts = ref_contacts if t_ref is not None else ours_contacts
            title = (
                f"ks_id ref={int(rec['ks_id_ref'])}  "
                f"ours={int(rec['ks_id_ours'])}\n"
                f"cos={rec['cos']:.2f}  dxy={rec['d_xy']:.1f} um  "
                f"sim={rec['sim']:.2f}"
            )
            _plot_waveform_pair(
                ax, t_ref, t_ours, peak_ch, contacts, times_ms, title,
            )
        axes[row_i, 0].set_ylabel(group_label, fontsize=6, labelpad=10)

    # Figure-level legend (ref blue solid vs ours orange dashed).
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], color="tab:blue", lw=0.9, label="ref"),
        Line2D([0], [0], color="tab:orange", lw=0.9, ls="--", label="ours"),
    ]
    fig.legend(handles=handles, loc="upper right", fontsize=6,
               bbox_to_anchor=(0.98, 0.995), frameon=False)

    fig.suptitle(
        f"VII.B matched-pair waveform gallery — 5 spatially-nearest channels, "
        f"window [-{common_before:.1f}, +{common_after:.1f}] ms around peak",
        fontsize=7,
    )
    out_png = OUT_DIR / "pair_waveforms.png"
    out_svg = OUT_DIR / "pair_waveforms.svg"
    fig.savefig(out_png)
    fig.savefig(out_svg)
    print(f"wrote {out_png}")
    print(f"wrote {out_svg}")


if __name__ == "__main__":
    main()
