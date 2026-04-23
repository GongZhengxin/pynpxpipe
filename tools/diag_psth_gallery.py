"""VII.E - matched-pair PSTH gallery (Nature format).

For each sampled pair (3 high/mid/low cosine matched + 3 unmatched), overlay:
  - ref top-1 preferred stim PSTH    (blue solid)
  - ref mean across all stims        (blue dashed)
  - ours top-1 preferred stim PSTH   (orange solid)
  - ours mean across all stims       (orange dashed)

PSTH = spikes / (bin_s * n_trials), 10 ms bin, window [-50, +300] ms relative
to stimulus onset.  The [60, 220] ms window is lightly shaded.

Preferred stim is per-pipeline (so ref's top-1 and ours' top-1 may be
different stimuli — that's the point of the comparison).

Output:
  diag/psth_gallery.png (600 dpi)
  diag/psth_gallery.svg
"""

from __future__ import annotations

from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REF_RASTER = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv/TrialRaster_241026_MaoDan_WordLocalizer_MLO.h5")
REF_RECORD = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv/TrialRecord_241026_MaoDan_WordLocalizer_MLO.csv")
REF_UNITPROP = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv/UnitProp_241026_MaoDan_WordLocalizer_MLO.csv")
OURS_RASTER = Path(r"F:/#Datasets/demo_rawdata/processed_pynpxpipe/07_derivatives/TrialRaster_241029_MaoDan_WordLOC_MLO.h5")
OURS_RECORD = Path(r"F:/#Datasets/demo_rawdata/processed_pynpxpipe/07_derivatives/TrialRecord_241029_MaoDan_WordLOC_MLO.csv")
OURS_UNITPROP = Path(r"F:/#Datasets/demo_rawdata/processed_pynpxpipe/07_derivatives/UnitProp_241029_MaoDan_WordLOC_MLO.csv")
PAIRING_CSV = Path("diag/unit_pairing.csv")
OUT_DIR = Path("diag")

SEED = 2
PSTH_BIN_MS = 10.0
SHADE_START_MS = 60.0
SHADE_END_MS = 220.0


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


def _load_raster(path: Path) -> tuple[np.ndarray, dict]:
    with h5py.File(path, "r") as f:
        shape = tuple(int(s) for s in f.attrs["original_shape"])
        mattrs = dict(f["metadata"].attrs)
        pre = float(mattrs.get("pre_onset_ms", mattrs.get("pre_onset")))
        post = float(mattrs.get("post_onset_ms", mattrs.get("post_onset")))
        bin_ms = float(mattrs.get("bin_size_ms", 1.0))
        storage = f.attrs.get("storage_format", "")
        if isinstance(storage, bytes):
            storage = storage.decode("utf-8", "ignore")
        if storage == "sparse":
            row = f["row"][:]
            col = f["col"][:]
            data = f["data"][:]
            n_u, n_tr, n_tb = shape
            dense = np.zeros((n_u * n_tr, n_tb), dtype=np.uint8)
            dense[row, col] = data
            raster = dense.reshape(n_u, n_tr, n_tb)
        else:
            raster = f["raster"][:]
    return raster, {"bin_size_ms": bin_ms, "pre_onset_ms": pre, "post_onset_ms": post}


def _rebin_psth(raster: np.ndarray, good_trials: np.ndarray,
                bin_ms: float, target_bin_ms: float) -> np.ndarray:
    """Return (n_u, n_good_tr, n_coarse_bins) spike counts, coarser time bins."""
    rebin = int(round(target_bin_ms / bin_ms))
    n_u, _, n_tb = raster.shape
    n_coarse = n_tb // rebin
    r = raster[:, good_trials, : n_coarse * rebin]
    coarse = r.reshape(n_u, len(good_trials), n_coarse, rebin).sum(axis=3)
    return coarse


def _times_ms(meta: dict, n_coarse: int) -> np.ndarray:
    """Edge-to-center times relative to stim onset for coarse PSTH bins."""
    edges = np.arange(n_coarse + 1) * PSTH_BIN_MS - meta["pre_onset_ms"]
    return 0.5 * (edges[:-1] + edges[1:])


def _prefer_and_mean_psth(
    unit_row: int, coarse: np.ndarray, stim_col_of_trial: np.ndarray,
    n_stims: int, win_bins: tuple[int, int],
) -> tuple[np.ndarray, np.ndarray, int, float]:
    """Return (pref_psth, mean_psth, pref_stim_col, pref_fr_hz) for one unit."""
    per_stim_psth = np.zeros((n_stims, coarse.shape[2]))
    per_stim_fr = np.zeros(n_stims)
    b0, b1 = win_bins
    win_dur_s = (b1 - b0) * PSTH_BIN_MS / 1000.0
    for s_col in range(n_stims):
        mask = stim_col_of_trial == s_col
        if not mask.any():
            continue
        # PSTH in spikes / (bin_s * n_trials) -> Hz.
        trials_sub = coarse[unit_row, mask, :]
        per_stim_psth[s_col] = trials_sub.mean(axis=0) / (PSTH_BIN_MS / 1000.0)
        per_stim_fr[s_col] = trials_sub[:, b0:b1].sum() / max(mask.sum(), 1) / win_dur_s
    pref_col = int(np.argmax(per_stim_fr))
    mean_psth = per_stim_psth.mean(axis=0)
    return per_stim_psth[pref_col], mean_psth, pref_col, float(per_stim_fr[pref_col])


def _select_samples(pairing: pd.DataFrame,
                    rng: np.random.Generator) -> dict[str, list]:
    matched = pairing[pairing["matched"]].sort_values("cos", ascending=False)

    def _pick(df, n):
        if len(df) <= n:
            return df.index.tolist()
        return rng.choice(df.index.values, size=n, replace=False).tolist()

    high = matched[matched["cos"] >= 0.97]
    mid = matched[(matched["cos"] >= 0.85) & (matched["cos"] < 0.97)]
    low = matched[(matched["cos"] >= 0.60) & (matched["cos"] < 0.85)]
    unmatched = pairing[~pairing["matched"]]

    return {
        "high_match": _pick(high, 3),
        "mid_match": _pick(mid, 3),
        "low_match": _pick(low, 3),
        "unmatched": _pick(unmatched, 3),
    }


def main() -> None:
    _nature_rc()
    OUT_DIR.mkdir(exist_ok=True)

    print("loading rasters...")
    ref_r, ref_meta = _load_raster(REF_RASTER)
    ours_r, ours_meta = _load_raster(OURS_RASTER)
    ref_trials = pd.read_csv(REF_RECORD)
    ours_trials = pd.read_csv(OURS_RECORD)
    ref_up = pd.read_csv(REF_UNITPROP)
    ours_up = pd.read_csv(OURS_UNITPROP)
    pairing = pd.read_csv(PAIRING_CSV)

    # Good trials + stim columns.
    ref_good = np.where(ref_trials["fix_success"].astype(bool).to_numpy())[0]
    ours_good = np.where(ours_trials["fix_success"].astype(bool).to_numpy())[0]
    ref_stim = ref_trials.loc[ref_good, "stim_index"].to_numpy()
    ours_stim = ours_trials.loc[ours_good, "stim_index"].to_numpy()
    ref_stim_cols = np.unique(ref_stim)
    ours_stim_cols = np.unique(ours_stim)
    ref_stim_map = {s: i for i, s in enumerate(ref_stim_cols)}
    ours_stim_map = {s: i for i, s in enumerate(ours_stim_cols)}
    ref_stim_col_of = np.array([ref_stim_map[s] for s in ref_stim])
    ours_stim_col_of = np.array([ours_stim_map[s] for s in ours_stim])

    ref_coarse = _rebin_psth(ref_r, ref_good, ref_meta["bin_size_ms"], PSTH_BIN_MS)
    ours_coarse = _rebin_psth(ours_r, ours_good, ours_meta["bin_size_ms"], PSTH_BIN_MS)
    # Shape (n_u, n_gt, n_coarse). Times relative to onset.
    ref_times = _times_ms(ref_meta, ref_coarse.shape[2])
    ours_times = _times_ms(ours_meta, ours_coarse.shape[2])
    # Window bin bounds on coarse timebase.
    ref_b0 = int(round((ref_meta["pre_onset_ms"] + SHADE_START_MS) / PSTH_BIN_MS))
    ref_b1 = int(round((ref_meta["pre_onset_ms"] + SHADE_END_MS) / PSTH_BIN_MS))
    ours_b0 = int(round((ours_meta["pre_onset_ms"] + SHADE_START_MS) / PSTH_BIN_MS))
    ours_b1 = int(round((ours_meta["pre_onset_ms"] + SHADE_END_MS) / PSTH_BIN_MS))

    ref_id2row = {int(u): i for i, u in enumerate(ref_up["ks_id"])}
    ours_id2row = {int(u): i for i, u in enumerate(ours_up["ks_id"])}

    rng = np.random.default_rng(SEED)
    samples = _select_samples(pairing, rng)
    groups = [("high_match", "matched (cos>=0.97)"),
              ("mid_match", "matched (0.85-0.97)"),
              ("low_match", "matched (0.60-0.85)"),
              ("unmatched", "unmatched (sim<0.60)")]

    fig, axes = plt.subplots(4, 3, figsize=(8.5, 8.0), constrained_layout=True)
    for row_i, (key, group_label) in enumerate(groups):
        idxs = samples[key]
        for col_i in range(3):
            ax = axes[row_i, col_i]
            if col_i >= len(idxs):
                ax.axis("off")
                continue
            rec = pairing.loc[idxs[col_i]]
            ks_r = int(rec["ks_id_ref"])
            ks_o = int(rec["ks_id_ours"])
            ref_row = ref_id2row.get(ks_r)
            ours_row = ours_id2row.get(ks_o)

            plotted_any = False
            if ref_row is not None:
                pref_psth, mean_psth, pref_col, pref_fr = _prefer_and_mean_psth(
                    ref_row, ref_coarse, ref_stim_col_of,
                    len(ref_stim_cols), (ref_b0, ref_b1),
                )
                ax.plot(ref_times, pref_psth, color="tab:blue", lw=0.9,
                        label=f"ref pref s={int(ref_stim_cols[pref_col])} "
                              f"({pref_fr:.1f} Hz)")
                ax.plot(ref_times, mean_psth, color="tab:blue", lw=0.7, ls="--",
                        alpha=0.7, label="ref mean")
                plotted_any = True
            if ours_row is not None:
                pref_psth, mean_psth, pref_col, pref_fr = _prefer_and_mean_psth(
                    ours_row, ours_coarse, ours_stim_col_of,
                    len(ours_stim_cols), (ours_b0, ours_b1),
                )
                ax.plot(ours_times, pref_psth, color="tab:orange", lw=0.9,
                        label=f"ours pref s={int(ours_stim_cols[pref_col])} "
                              f"({pref_fr:.1f} Hz)")
                ax.plot(ours_times, mean_psth, color="tab:orange", lw=0.7,
                        ls="--", alpha=0.7, label="ours mean")
                plotted_any = True
            if not plotted_any:
                ax.axis("off")
                continue

            ax.axvspan(SHADE_START_MS, SHADE_END_MS, color="grey", alpha=0.08,
                       zorder=0)
            ax.axvline(0, color="k", lw=0.4, alpha=0.5)
            cos = float(rec.get("cos", np.nan))
            dxy = float(rec.get("d_xy", np.nan))
            title = f"ref={ks_r} ours={ks_o}\ncos={cos:.2f} dxy={dxy:.1f}"
            ax.set_title(title, fontsize=5.5, pad=2)
            ax.set_xlim(-50, 300)
            ax.legend(fontsize=4.5, frameon=False, loc="upper right",
                      handlelength=1.4, handletextpad=0.3)
            for spine in ("top", "right"):
                ax.spines[spine].set_visible(False)
            if col_i == 0:
                ax.set_ylabel(f"{group_label}\nFR (Hz)", fontsize=5.5)
            if row_i == 3:
                ax.set_xlabel("time from stim onset (ms)", fontsize=5.5)

    fig.suptitle(
        f"VII.E matched-pair PSTH gallery (10 ms bin, shade = [{SHADE_START_MS:.0f}, "
        f"{SHADE_END_MS:.0f}] ms rate window)",
        fontsize=7,
    )
    out_png = OUT_DIR / "psth_gallery.png"
    out_svg = OUT_DIR / "psth_gallery.svg"
    fig.savefig(out_png)
    fig.savefig(out_svg)
    print(f"wrote {out_png}")
    print(f"wrote {out_svg}")


if __name__ == "__main__":
    main()
