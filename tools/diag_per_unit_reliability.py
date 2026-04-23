"""VII.D - per-unit split-half reliability + selectivity (Nature format).

Evaluate whether ours' lower RSM split-half (0.27 vs 0.33 for ref) comes from
(a) unit-level noisier trial-to-trial responses, (b) different composition
(more NOISE/MUA), or (c) matched-pair drift.

Inputs
  - processed_good/deriv/TrialRaster_*.h5         (REF, sparse COO)
  - processed_good/deriv/TrialRecord_*.csv        (REF stim_index / fix_success)
  - processed_good/deriv/UnitProp_*.csv           (REF ks_id, unittype)
  - processed_pynpxpipe/07_derivatives/...        (OURS equivalents)
  - diag/unit_pairing.csv                         (cross-pipeline matched pairs)

Per-unit metrics
  1. splithalf_fr_pearson - 5-seed average.  For each stim_index, randomly
     split its trials into two halves; compute a per-stim mean FR in the
     [60, 220] ms window for each half; Pearson across the two per-stim
     vectors.  Spearman-Brown corrected.
  2. splithalf_psth_pearson - same idea but correlation is across PSTH
     timebins (10 ms bin, full post-onset window).
  3. selectivity - Lurie style (max_stim_FR - mean_stim_FR) /
     (max_stim_FR + mean_stim_FR) on per-stim mean FR in window.
  4. n_spikes_total, n_active_trials (trials with >=1 spike in window)
  5. snr - mean(FR) / std(FR) across trials in window.

Outputs
  diag/per_unit_reliability.csv
  diag/per_unit_reliability_hist.png/svg
  diag/matched_pair_reliability_scatter.png/svg
  diag/per_unit_reliability_summary.txt
"""

from __future__ import annotations

import os
from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

_OURS_ROOT = Path(os.environ.get("PYNPX_OURS_ROOT", r"F:/#Datasets/demo_rawdata/processed_pynpxpipe"))
_OUT_DIR_OVERRIDE = os.environ.get("PYNPX_DIAG_OUT")

REF_RASTER = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv/TrialRaster_241026_MaoDan_WordLocalizer_MLO.h5")
REF_RECORD = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv/TrialRecord_241026_MaoDan_WordLocalizer_MLO.csv")
REF_UNITPROP = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv/UnitProp_241026_MaoDan_WordLocalizer_MLO.csv")
OURS_RASTER = _OURS_ROOT / "07_derivatives" / "TrialRaster_241029_MaoDan_WordLOC_MLO.h5"
OURS_RECORD = _OURS_ROOT / "07_derivatives" / "TrialRecord_241029_MaoDan_WordLOC_MLO.csv"
OURS_UNITPROP = _OURS_ROOT / "07_derivatives" / "UnitProp_241029_MaoDan_WordLOC_MLO.csv"
PAIRING_CSV = (Path(_OUT_DIR_OVERRIDE) if _OUT_DIR_OVERRIDE else Path("diag")) / "unit_pairing.csv"
OUT_DIR = Path(_OUT_DIR_OVERRIDE) if _OUT_DIR_OVERRIDE else Path("diag")

# Analysis window (ms relative to stim onset) for rate / selectivity / SNR.
WIN_START_MS = 60.0
WIN_END_MS = 220.0
PSTH_BIN_MS = 10.0       # coarser bin for PSTH split-half reliability
N_SEEDS = 5

REF_COLOR = "#1f77b4"
OURS_COLOR = "#ff7f0e"

UNITTYPE_TO_STRING = {0: "unknown", 1: "SUA", 2: "MUA", 3: "NOISE"}


def _nature_rc() -> None:
    plt.rcParams.update({
        "font.family": "Arial",
        "font.size": 6,
        "axes.linewidth": 0.4,
        "xtick.major.width": 0.4,
        "ytick.major.width": 0.4,
        "xtick.labelsize": 5,
        "ytick.labelsize": 5,
        "savefig.dpi": 600,
        "savefig.bbox": "tight",
    })


def _load_raster(path: Path) -> tuple[np.ndarray, dict]:
    """Load sparse-COO raster into dense (n_units, n_trials, n_timebins)."""
    with h5py.File(path, "r") as f:
        shape = tuple(int(s) for s in f.attrs["original_shape"])
        mattrs = dict(f["metadata"].attrs)
        # REF (MATLAB) writes pre_onset / post_onset as int ms, no bin_size.
        # OURS writes pre_onset_ms / post_onset_ms / bin_size_ms as float.
        pre = mattrs.get("pre_onset_ms", mattrs.get("pre_onset"))
        post = mattrs.get("post_onset_ms", mattrs.get("post_onset"))
        bin_ms = mattrs.get("bin_size_ms", 1.0)
        meta = {
            "bin_size_ms": float(bin_ms),
            "pre_onset_ms": float(pre),
            "post_onset_ms": float(post),
        }
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
    return raster, meta


def _spearman_brown(r: float) -> float:
    if not np.isfinite(r):
        return np.nan
    if r <= -1.0:
        return np.nan
    return 2.0 * r / (1.0 + r)


def _compute_per_unit(
    raster: np.ndarray,
    trials_df: pd.DataFrame,
    meta: dict,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Return per-unit metric DataFrame (index = raster row)."""
    n_u, n_tr, n_tb = raster.shape
    bin_ms = meta["bin_size_ms"]
    pre = meta["pre_onset_ms"]

    # Use only successful trials.
    fix_ok = trials_df["fix_success"].astype(bool).to_numpy()
    good_trials = np.where(fix_ok)[0]
    if len(good_trials) == 0:
        raise RuntimeError("no successful trials")
    stim_idx = trials_df.loc[good_trials, "stim_index"].to_numpy()

    # Rate-window bin bounds (inclusive start, exclusive end).
    b0 = int(round((pre + WIN_START_MS) / bin_ms))
    b1 = int(round((pre + WIN_END_MS) / bin_ms))
    win_dur_s = (WIN_END_MS - WIN_START_MS) / 1000.0

    # Per-trial spike count in window, shape (n_u, n_good_tr).
    win = raster[:, good_trials, b0:b1].astype(np.float64)
    spike_cnt_win = win.sum(axis=2)
    fr_win = spike_cnt_win / win_dur_s

    # Active trials: >=1 spike in window.
    n_active = (spike_cnt_win >= 1).sum(axis=1)
    # Total spikes across whole raster (all trials, all bins).
    n_spikes = raster.sum(axis=(1, 2))
    # SNR = mean/std across trials within window.
    mu = fr_win.mean(axis=1)
    sd = fr_win.std(axis=1, ddof=0)
    snr = np.divide(mu, sd, out=np.full_like(mu, np.nan), where=sd > 0)

    # Per-stim mean FR (for selectivity + split-half).
    unique_stims = np.unique(stim_idx)
    n_stims = len(unique_stims)
    stim_to_col = {s: i for i, s in enumerate(unique_stims)}
    stim_col_of_trial = np.array([stim_to_col[s] for s in stim_idx])

    # selectivity: (max - mean) / (max + mean) on per-stim mean FR.
    sel = np.zeros(n_u)
    for u in range(n_u):
        per_stim = np.zeros(n_stims)
        for s_col in range(n_stims):
            mask = stim_col_of_trial == s_col
            per_stim[s_col] = fr_win[u, mask].mean() if mask.any() else 0.0
        max_v = per_stim.max()
        mean_v = per_stim.mean()
        denom = max_v + mean_v
        sel[u] = (max_v - mean_v) / denom if denom > 1e-9 else 0.0

    # Split-half FR Pearson (5 seeds, Spearman-Brown corrected).
    sh_fr = np.full(n_u, np.nan)
    seed_vals = np.zeros((n_u, N_SEEDS))
    for s_i in range(N_SEEDS):
        # For each stim, shuffle its trials' column indices; assign halves.
        half_a_mask = np.zeros(len(good_trials), dtype=bool)
        for s_col in range(n_stims):
            ids = np.where(stim_col_of_trial == s_col)[0]
            if len(ids) < 2:
                continue
            rng.shuffle(ids)
            half_a_mask[ids[: len(ids) // 2]] = True
        half_b_mask = ~half_a_mask & (stim_col_of_trial >= 0)
        # Per-unit per-stim mean FR on each half.
        per_stim_a = np.full((n_u, n_stims), np.nan)
        per_stim_b = np.full((n_u, n_stims), np.nan)
        for s_col in range(n_stims):
            mask_a = half_a_mask & (stim_col_of_trial == s_col)
            mask_b = half_b_mask & (stim_col_of_trial == s_col)
            if mask_a.any():
                per_stim_a[:, s_col] = fr_win[:, mask_a].mean(axis=1)
            if mask_b.any():
                per_stim_b[:, s_col] = fr_win[:, mask_b].mean(axis=1)
        both = ~np.isnan(per_stim_a) & ~np.isnan(per_stim_b)
        for u in range(n_u):
            m = both[u]
            if m.sum() < 5:
                continue
            a = per_stim_a[u, m]
            b = per_stim_b[u, m]
            if a.std() < 1e-9 or b.std() < 1e-9:
                continue
            r, _ = stats.pearsonr(a, b)
            seed_vals[u, s_i] = _spearman_brown(r)
    sh_fr = np.nanmean(np.where(seed_vals == 0, np.nan, seed_vals), axis=1)

    # Split-half PSTH Pearson (one split, coarser bin).
    rebin = int(round(PSTH_BIN_MS / bin_ms))
    n_post_bins = n_tb - int(round(pre / bin_ms))
    n_post_coarse = n_post_bins // rebin
    post_start = int(round(pre / bin_ms))
    post_raster = raster[:, good_trials, post_start : post_start + n_post_coarse * rebin]
    post_coarse = post_raster.reshape(n_u, len(good_trials), n_post_coarse, rebin).sum(axis=3)

    rng_psth = np.random.default_rng(rng.integers(2**31 - 1))
    idx = np.arange(len(good_trials))
    rng_psth.shuffle(idx)
    half_a = idx[: len(idx) // 2]
    half_b = idx[len(idx) // 2 :]
    psth_a = post_coarse[:, half_a, :].mean(axis=1)
    psth_b = post_coarse[:, half_b, :].mean(axis=1)
    sh_psth = np.full(n_u, np.nan)
    for u in range(n_u):
        if psth_a[u].std() < 1e-9 or psth_b[u].std() < 1e-9:
            continue
        r, _ = stats.pearsonr(psth_a[u], psth_b[u])
        sh_psth[u] = _spearman_brown(r)

    df = pd.DataFrame({
        "n_spikes_total": n_spikes.astype(int),
        "n_active_trials": n_active.astype(int),
        "splithalf_fr_pearson": sh_fr,
        "splithalf_psth_pearson": sh_psth,
        "selectivity": sel,
        "snr": snr,
    })
    return df


def _assemble_pipeline(
    raster_path: Path, record_path: Path, unitprop_path: Path, label: str, seed: int,
) -> pd.DataFrame:
    print(f"\n[{label}] loading raster {raster_path.name}")
    raster, meta = _load_raster(raster_path)
    print(f"  raster shape {raster.shape}  bin {meta['bin_size_ms']} ms "
          f"pre {meta['pre_onset_ms']} ms post {meta['post_onset_ms']} ms")
    trials_df = pd.read_csv(record_path)
    unit_df = pd.read_csv(unitprop_path)
    assert raster.shape[0] == len(unit_df), \
        f"{label} raster rows {raster.shape[0]} != UnitProp {len(unit_df)}"
    rng = np.random.default_rng(seed)
    metrics = _compute_per_unit(raster, trials_df, meta, rng)
    metrics.insert(0, "pipeline", label)
    metrics.insert(1, "ks_id", unit_df["ks_id"].astype(int).to_numpy())
    metrics.insert(2, "unittype", unit_df.get("unittype", pd.Series(np.zeros(len(unit_df), dtype=int))).astype(int).to_numpy())
    metrics.insert(3, "unittype_string", metrics["unittype"].map(UNITTYPE_TO_STRING))
    return metrics


def _hist_overlay(ax, ref_vals, ours_vals, title: str, xlabel: str) -> None:
    data_ref = ref_vals[np.isfinite(ref_vals)]
    data_ours = ours_vals[np.isfinite(ours_vals)]
    if len(data_ref) == 0 and len(data_ours) == 0:
        ax.axis("off")
        ax.set_title(title, fontsize=5.5)
        return
    combined = np.concatenate([data_ref, data_ours])
    bins = np.linspace(combined.min(), combined.max(), 30)
    ax.hist(data_ref, bins=bins, color=REF_COLOR, alpha=0.55,
            label=f"ref n={len(data_ref)}", density=True)
    ax.hist(data_ours, bins=bins, color=OURS_COLOR, alpha=0.55,
            label=f"ours n={len(data_ours)}", density=True)
    ks_p = np.nan
    if len(data_ref) >= 3 and len(data_ours) >= 3:
        _, ks_p = stats.ks_2samp(data_ref, data_ours)
    ax.set_title(f"{title}\nKS p={ks_p:.2e}" if np.isfinite(ks_p) else title, fontsize=5.5)
    ax.set_xlabel(xlabel, fontsize=5.5)
    ax.set_ylabel("density", fontsize=5.5)
    ax.legend(fontsize=5, frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def _hist_grid(df: pd.DataFrame, out_png: Path, out_svg: Path) -> None:
    metrics = [
        ("splithalf_fr_pearson", "split-half FR (Spearman-Brown)"),
        ("selectivity", "selectivity (Lurie)"),
        ("snr", "SNR"),
    ]
    groups = ["SUA", "MUA", "ALL"]
    fig, axes = plt.subplots(len(metrics), len(groups), figsize=(8.0, 6.5))
    for r_i, (col, xlabel) in enumerate(metrics):
        for c_i, g in enumerate(groups):
            ax = axes[r_i, c_i]
            if g == "ALL":
                ref = df[(df["pipeline"] == "ref")][col].to_numpy()
                ours = df[(df["pipeline"] == "ours")][col].to_numpy()
            else:
                ref = df[(df["pipeline"] == "ref") & (df["unittype_string"] == g)][col].to_numpy()
                ours = df[(df["pipeline"] == "ours") & (df["unittype_string"] == g)][col].to_numpy()
            _hist_overlay(ax, ref, ours, f"{g}", xlabel)
    fig.suptitle("per-unit reliability / selectivity  (ref vs ours, by unittype)",
                 fontsize=7)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(out_png)
    fig.savefig(out_svg)
    plt.close(fig)
    print(f"wrote {out_png}")
    print(f"wrote {out_svg}")


def _scatter_matched(df: pd.DataFrame, pairing: pd.DataFrame,
                     out_png: Path, out_svg: Path) -> None:
    matched = pairing[pairing["matched"]].copy()
    ref_df = df[df["pipeline"] == "ref"].set_index("ks_id")
    ours_df = df[df["pipeline"] == "ours"].set_index("ks_id")
    matched = matched[matched["ks_id_ref"].isin(ref_df.index) &
                      matched["ks_id_ours"].isin(ours_df.index)].copy()
    matched["ref_sh"] = matched["ks_id_ref"].map(ref_df["splithalf_fr_pearson"])
    matched["ours_sh"] = matched["ks_id_ours"].map(ours_df["splithalf_fr_pearson"])
    matched["ours_ut"] = matched["ks_id_ours"].map(ours_df["unittype_string"])
    both = matched.dropna(subset=["ref_sh", "ours_sh"]).copy()

    sizes = 8 + 30 * np.clip(both["cos"].to_numpy(), 0, 1)
    color_map = {"SUA": "#1f77b4", "MUA": "#2ca02c", "NOISE": "#d62728",
                 "unknown": "#888888"}
    colors = [color_map.get(u, "#888888") for u in both["ours_ut"]]

    r_val, r_p = np.nan, np.nan
    if len(both) >= 3:
        r_val, r_p = stats.pearsonr(both["ref_sh"], both["ours_sh"])

    fig, ax = plt.subplots(figsize=(4.2, 4.2))
    ax.scatter(both["ref_sh"], both["ours_sh"], s=sizes, c=colors,
               edgecolors="none", alpha=0.8)
    lo = min(both["ref_sh"].min(), both["ours_sh"].min()) - 0.05
    hi = max(both["ref_sh"].max(), both["ours_sh"].max()) + 0.05
    ax.plot([lo, hi], [lo, hi], color="grey", lw=0.5, ls="--")
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel("ref split-half FR")
    ax.set_ylabel("ours split-half FR")
    ax.set_title(
        f"matched-pair reliability  n={len(both)}\nPearson r={r_val:.2f}  p={r_p:.2e}",
        fontsize=6,
    )
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    from matplotlib.lines import Line2D
    handles = [Line2D([0], [0], marker="o", color="none", markerfacecolor=v,
                      markeredgecolor="none", markersize=6, label=k)
               for k, v in color_map.items() if k in set(both["ours_ut"])]
    handles.append(Line2D([0], [0], color="grey", lw=0.5, ls="--",
                          label="identity"))
    ax.legend(handles=handles, loc="lower right", fontsize=5, frameon=False)
    fig.tight_layout()
    fig.savefig(out_png)
    fig.savefig(out_svg)
    plt.close(fig)
    print(f"wrote {out_png}")
    print(f"wrote {out_svg}")


def _summary(df: pd.DataFrame, pairing: pd.DataFrame, out_txt: Path) -> None:
    lines: list[str] = []
    lines.append("# per_unit_reliability_summary")
    for col in ("splithalf_fr_pearson", "splithalf_psth_pearson",
                "selectivity", "snr"):
        lines.append(f"\n## {col}")
        for pipeline in ("ref", "ours"):
            for g in ("ALL", "SUA", "MUA", "NOISE"):
                if g == "ALL":
                    v = df[df["pipeline"] == pipeline][col].dropna()
                else:
                    v = df[(df["pipeline"] == pipeline) &
                           (df["unittype_string"] == g)][col].dropna()
                if len(v) == 0:
                    continue
                lines.append(
                    f"  {pipeline:5s} {g:7s} n={len(v):4d}  "
                    f"median={v.median():.3f}  p25={v.quantile(0.25):.3f}  "
                    f"p75={v.quantile(0.75):.3f}"
                )
        # KS ref vs ours (ALL).
        ref = df[df["pipeline"] == "ref"][col].dropna()
        ours = df[df["pipeline"] == "ours"][col].dropna()
        if len(ref) >= 3 and len(ours) >= 3:
            _, ks_p = stats.ks_2samp(ref, ours)
            lines.append(f"  KS ref-vs-ours (ALL): p={ks_p:.3e}")
        ref_s = df[(df["pipeline"] == "ref") & (df["unittype_string"] == "SUA")][col].dropna()
        ours_s = df[(df["pipeline"] == "ours") & (df["unittype_string"] == "SUA")][col].dropna()
        if len(ref_s) >= 3 and len(ours_s) >= 3:
            _, ks_p = stats.ks_2samp(ref_s, ours_s)
            lines.append(f"  KS ref-vs-ours (SUA only): p={ks_p:.3e}")

    matched = pairing[pairing["matched"]]
    ref_df = df[df["pipeline"] == "ref"].set_index("ks_id")
    ours_df = df[df["pipeline"] == "ours"].set_index("ks_id")
    matched = matched[matched["ks_id_ref"].isin(ref_df.index) &
                      matched["ks_id_ours"].isin(ours_df.index)]
    rs = matched["ks_id_ref"].map(ref_df["splithalf_fr_pearson"])
    os = matched["ks_id_ours"].map(ours_df["splithalf_fr_pearson"])
    mask = np.isfinite(rs) & np.isfinite(os)
    if mask.sum() >= 3:
        r_val, r_p = stats.pearsonr(rs[mask], os[mask])
        lines.append(f"\n## matched-pair reliability correlation")
        lines.append(f"  n={int(mask.sum())}  Pearson r={r_val:.3f}  p={r_p:.3e}")

    out_txt.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_txt}")


def main() -> None:
    _nature_rc()
    OUT_DIR.mkdir(exist_ok=True)

    ref_df = _assemble_pipeline(REF_RASTER, REF_RECORD, REF_UNITPROP, "ref", seed=7)
    ours_df = _assemble_pipeline(OURS_RASTER, OURS_RECORD, OURS_UNITPROP, "ours", seed=13)
    df = pd.concat([ref_df, ours_df], ignore_index=True)
    out_csv = OUT_DIR / "per_unit_reliability.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nwrote {out_csv}  (rows={len(df)})")

    pairing = pd.read_csv(PAIRING_CSV)
    _hist_grid(df, OUT_DIR / "per_unit_reliability_hist.png",
               OUT_DIR / "per_unit_reliability_hist.svg")
    _scatter_matched(df, pairing,
                     OUT_DIR / "matched_pair_reliability_scatter.png",
                     OUT_DIR / "matched_pair_reliability_scatter.svg")
    _summary(df, pairing, OUT_DIR / "per_unit_reliability_summary.txt")


if __name__ == "__main__":
    main()
