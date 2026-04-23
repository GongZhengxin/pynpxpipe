"""Within-pipeline split-half RSM reliability — the data-level noise ceiling.

For each pipeline (reference + pynpxpipe):
  1. load raster h5 + TrialRecord csv;
  2. for each stim_index, split trials odd/even;
  3. compute mean FR per image in window [60, 220] ms → (n_images, n_units) each;
  4. Pearson RSM across units (image × image) for each half;
  5. lower-tri correlation between RSM_A and RSM_B → split-half reliability.

Compared with the cross-pipeline 0.77 from `diag_rsm_compare.py`, this tells
us whether that number is close to the within-pipeline ceiling (so little
room for sorting-level improvement) or far below it (so sorting differences
genuinely explain the gap).

Window, raster storage format, and FR convention mirror ``diag_rsm_compare.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import spearmanr

_OURS_ROOT = Path(os.environ.get("PYNPX_OURS_ROOT", r"F:/#Datasets/demo_rawdata/processed_pynpxpipe"))
_OUT_DIR_OVERRIDE = os.environ.get("PYNPX_DIAG_OUT")

REF_DIR = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv")
OURS_DIR = _OURS_ROOT / "07_derivatives"
REF_STEM = "241026_MaoDan_WordLocalizer_MLO"
OURS_STEM = "241029_MaoDan_WordLOC_MLO"
WIN_LO_MS = 60
WIN_HI_MS = 220


def _load_raster(h5_path: Path) -> tuple[np.ndarray, dict]:
    with h5py.File(h5_path, "r") as f:
        shape = tuple(f.attrs["original_shape"].tolist())
        n_units, n_trials, n_timebins = shape
        if f.attrs["storage_format"] == "sparse":
            row = f["row"][:]
            col = f["col"][:]
            data = f["data"][:]
            coo = sparse.coo_matrix(
                (data, (row, col)),
                shape=(n_units * n_trials, n_timebins),
            )
            raster = coo.toarray().reshape(n_units, n_trials, n_timebins)
        else:
            raster = f["raster"][:]
        meta = dict(f["metadata"].attrs)
    return raster, meta


def _pre_onset_ms(meta: dict) -> int:
    if "pre_onset_ms" in meta:
        return int(meta["pre_onset_ms"])
    return int(meta["pre_onset"])


def _window_counts(raster: np.ndarray, pre_ms: int) -> np.ndarray:
    """Return (units, trials) spike counts in [WIN_LO_MS, WIN_HI_MS] post-stim."""
    lo = pre_ms + WIN_LO_MS
    hi = pre_ms + WIN_HI_MS
    return raster[:, :, lo:hi].sum(axis=2)


def _split_half_mean_fr(
    counts: np.ndarray,
    trial_df: pd.DataFrame,
    only_valid: bool,
    seed: int = 0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split trials of each stim_index into two halves (deterministic interleave);
    return two mean-FR dataframes (rows=images, cols=units).

    "Interleave" means for each image, sort its trial indices and alternate
    half-A / half-B. This preserves balance even when per-image trial counts
    are odd (A gets the extra trial).
    """
    win_dur_s = (WIN_HI_MS - WIN_LO_MS) / 1000.0
    fr = counts.astype(np.float64) / win_dur_s  # (units, trials) Hz
    df = pd.DataFrame(fr.T)  # rows=trials, cols=units
    df["stim_index"] = trial_df["stim_index"].values
    df["_valid"] = trial_df["fix_success"].astype(bool).values
    df["_row"] = np.arange(len(df))
    if only_valid:
        df = df.loc[df["_valid"]]

    rng = np.random.default_rng(seed)
    half_labels = np.empty(len(df), dtype=np.int8)
    for stim, idx in df.groupby("stim_index").groups.items():
        pos = np.asarray(idx)
        perm = rng.permutation(len(pos))
        # Deterministic odd/even on the shuffled order, so different seeds
        # yield different partitions while still balanced.
        labels = np.zeros(len(pos), dtype=np.int8)
        labels[perm[::2]] = 0
        labels[perm[1::2]] = 1
        half_labels[np.searchsorted(df["_row"].values, pos)] = labels
    df["_half"] = half_labels

    unit_cols = [c for c in df.columns if isinstance(c, int)]
    gA = df[df["_half"] == 0].groupby("stim_index")[unit_cols].mean()
    gB = df[df["_half"] == 1].groupby("stim_index")[unit_cols].mean()
    common = gA.index.intersection(gB.index)
    return gA.loc[common], gB.loc[common]


def _rsm(mean_fr: pd.DataFrame) -> np.ndarray:
    arr = mean_fr.values
    var = arr.std(axis=0)
    keep = var > 0
    arr = arr[:, keep]
    return np.corrcoef(arr)


def _lower_tri(m: np.ndarray) -> np.ndarray:
    return m[np.tril_indices_from(m, k=-1)]


def _split_half_reliability(
    raster: np.ndarray,
    trial_df: pd.DataFrame,
    pre_ms: int,
    only_valid: bool,
    seed: int = 0,
) -> tuple[float, float, int]:
    counts = _window_counts(raster, pre_ms)
    mean_A, mean_B = _split_half_mean_fr(counts, trial_df, only_valid, seed=seed)
    rsm_A = _rsm(mean_A)
    rsm_B = _rsm(mean_B)
    lo_A = _lower_tri(rsm_A)
    lo_B = _lower_tri(rsm_B)
    valid = np.isfinite(lo_A) & np.isfinite(lo_B)
    pearson = float(np.corrcoef(lo_A[valid], lo_B[valid])[0, 1])
    spearman = float(spearmanr(lo_A[valid], lo_B[valid])[0])
    return pearson, spearman, int(valid.sum())


def main() -> None:
    ref_raster, ref_meta = _load_raster(REF_DIR / f"TrialRaster_{REF_STEM}.h5")
    ours_raster, ours_meta = _load_raster(OURS_DIR / f"TrialRaster_{OURS_STEM}.h5")
    ref_trials = pd.read_csv(REF_DIR / f"TrialRecord_{REF_STEM}.csv")
    ours_trials = pd.read_csv(OURS_DIR / f"TrialRecord_{OURS_STEM}.csv")
    ref_pre = _pre_onset_ms(ref_meta)
    ours_pre = _pre_onset_ms(ours_meta)

    print(
        f"window = [{WIN_LO_MS}, {WIN_HI_MS}] ms post-onset; "
        f"FR units: Hz; RSM axis: units (Pearson across units)."
    )
    print(f"ref  raster: {ref_raster.shape}  pre={ref_pre} ms  units={ref_raster.shape[0]}")
    print(
        f"ours raster: {ours_raster.shape}  pre={ours_pre} ms  "
        f"units={ours_raster.shape[0]}"
    )

    n_seeds = 5
    for only_valid in (False, True):
        label = "all trials" if not only_valid else "fix_success only"
        print(f"\n[{label}]")
        for tag, raster, trial_df, pre in (
            ("ref ", ref_raster, ref_trials, ref_pre),
            ("ours", ours_raster, ours_trials, ours_pre),
        ):
            pearsons = []
            spearmans = []
            pair_counts = []
            for seed in range(n_seeds):
                p, s, n = _split_half_reliability(raster, trial_df, pre, only_valid, seed)
                pearsons.append(p)
                spearmans.append(s)
                pair_counts.append(n)
            p_arr = np.array(pearsons)
            s_arr = np.array(spearmans)
            print(
                f"  {tag} split-half (n_seeds={n_seeds}, pairs≈{pair_counts[0]}): "
                f"pearson={p_arr.mean():.4f} ± {p_arr.std(ddof=1):.4f}  "
                f"spearman={s_arr.mean():.4f} ± {s_arr.std(ddof=1):.4f}"
            )

    print("\n-- Interpretation --")
    print(
        "If within-pipeline split-half approx cross-pipeline 0.77 -> 0.77 is near"
        " ceiling; sorting/pipeline differences are not the main source of RSM variance."
    )
    print(
        "If within-pipeline split-half >> 0.77 (e.g. 0.92) -> sorting-specific"
        " noise explains most of the cross-pipeline gap."
    )


if __name__ == "__main__":
    main()
