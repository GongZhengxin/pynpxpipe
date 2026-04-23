"""Compare representational similarity matrices between two pipelines.

Window: [60, 220] ms post-stim onset. Mean FR per image → RSM (Pearson across
units) → correlate lower-triangle elements between ref and pynpxpipe.
"""

from __future__ import annotations

import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from scipy import sparse


_OURS_ROOT = Path(os.environ.get("PYNPX_OURS_ROOT", r"F:/#Datasets/demo_rawdata/processed_pynpxpipe"))
_OUT_DIR_OVERRIDE = os.environ.get("PYNPX_DIAG_OUT")

REF_DIR = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv")
OURS_DIR = _OURS_ROOT / "07_derivatives"
REF_STEM = "241026_MaoDan_WordLocalizer_MLO"
OURS_STEM = "241029_MaoDan_WordLOC_MLO"


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


def _mean_fr_per_image(
    raster: np.ndarray,
    trial_df: pd.DataFrame,
    pre_ms: int,
    win_lo_ms: int,
    win_hi_ms: int,
    only_valid: bool,
) -> pd.DataFrame:
    lo = pre_ms + win_lo_ms
    hi = pre_ms + win_hi_ms
    win_dur_s = (win_hi_ms - win_lo_ms) / 1000.0
    counts = raster[:, :, lo:hi].sum(axis=2)  # (units, trials)
    fr = counts.astype(np.float64) / win_dur_s  # Hz
    df = pd.DataFrame(fr.T)  # rows=trials, cols=units
    df["stim_index"] = trial_df["stim_index"].values
    if only_valid:
        valid = trial_df["fix_success"].astype(bool).values
        df = df.loc[valid]
    mean_fr = df.groupby("stim_index").mean()
    return mean_fr  # rows=images, cols=units


def _rsm(mean_fr: pd.DataFrame) -> np.ndarray:
    # Pearson correlation across units → image-image RSM
    arr = mean_fr.values  # (n_images, n_units)
    # drop units with zero variance (constant FR across images)
    var = arr.std(axis=0)
    keep = var > 0
    arr = arr[:, keep]
    rsm = np.corrcoef(arr)
    return rsm


def _lower_tri(m: np.ndarray) -> np.ndarray:
    return m[np.tril_indices_from(m, k=-1)]


def main() -> None:
    ref_raster, ref_meta = _load_raster(REF_DIR / f"TrialRaster_{REF_STEM}.h5")
    ours_raster, ours_meta = _load_raster(OURS_DIR / f"TrialRaster_{OURS_STEM}.h5")
    ref_trials = pd.read_csv(REF_DIR / f"TrialRecord_{REF_STEM}.csv")
    ours_trials = pd.read_csv(OURS_DIR / f"TrialRecord_{OURS_STEM}.csv")

    ref_pre = _pre_onset_ms(ref_meta)
    ours_pre = _pre_onset_ms(ours_meta)
    print(f"ref  raster: {ref_raster.shape}  pre={ref_pre} ms")
    print(f"ours raster: {ours_raster.shape}  pre={ours_pre} ms")
    print(f"ref  fix_success dtype: {ref_trials.fix_success.dtype}")
    print(f"ours fix_success dtype: {ours_trials.fix_success.dtype}")
    assert (ref_trials.stim_index.values == ours_trials.stim_index.values).all(), (
        "stim_index mismatch between two pipelines"
    )

    for only_valid in (False, True):
        label = "all trials" if not only_valid else "fix_success only"
        ref_fr = _mean_fr_per_image(
            ref_raster, ref_trials, ref_pre, 60, 220, only_valid=only_valid
        )
        ours_fr = _mean_fr_per_image(
            ours_raster, ours_trials, ours_pre, 60, 220, only_valid=only_valid
        )
        assert (ref_fr.index == ours_fr.index).all(), "image index mismatch"
        print(
            f"\n[{label}] images={len(ref_fr)}  "
            f"ref_units={ref_fr.shape[1]}  ours_units={ours_fr.shape[1]}"
        )

        ref_rsm = _rsm(ref_fr)
        ours_rsm = _rsm(ours_fr)

        ref_lo = _lower_tri(ref_rsm)
        ours_lo = _lower_tri(ours_rsm)
        assert ref_lo.shape == ours_lo.shape

        # valid mask (both finite)
        valid = np.isfinite(ref_lo) & np.isfinite(ours_lo)
        r_pearson = np.corrcoef(ref_lo[valid], ours_lo[valid])[0, 1]
        # Spearman via rankdata
        from scipy.stats import spearmanr

        r_spearman, _ = spearmanr(ref_lo[valid], ours_lo[valid])
        print(
            f"  lower-tri size = {ref_lo.size} ({int(valid.sum())} finite); "
            f"pearson={r_pearson:.4f}  spearman={r_spearman:.4f}"
        )
        print(
            f"  ref_rsm range=[{ref_rsm[np.isfinite(ref_rsm)].min():.3f}, "
            f"{ref_rsm[np.isfinite(ref_rsm)].max():.3f}]"
        )
        print(
            f"  ours_rsm range=[{ours_rsm[np.isfinite(ours_rsm)].min():.3f}, "
            f"{ours_rsm[np.isfinite(ours_rsm)].max():.3f}]"
        )


if __name__ == "__main__":
    main()
