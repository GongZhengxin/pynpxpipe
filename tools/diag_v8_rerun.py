"""VI.1b - correct V.8.3 shared-subset RDM using UnitProp.csv for ks_id -> row mapping.

V.8.3 bug: TrialRaster_*.h5 does not store unit_ids/ks_ids; _load_raster() in
diag_unit_pairing.py fell back to np.arange(n_units), so subsequent ks_id-based
filtering collapsed into "ks_id value < n_raster_units". The 133 pairs claimed
as "same physical neurons surviving curation" were actually whatever matched
pair happened to have ks_id numerically under the raster size.

Correct approach: UnitProp_*.csv has both `id` (= raster row index) and `ks_id`
(= Kilosort cluster id used in analyzer.unit_ids), so we can resolve the ks_id
from the pairing CSV back to raster rows unambiguously.
"""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from scipy import sparse

REF_DERIV = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv")
OURS_DERIV = Path(r"F:/#Datasets/demo_rawdata/processed_pynpxpipe/07_derivatives")
REF_STEM = "241026_MaoDan_WordLocalizer_MLO"
OURS_STEM = "241029_MaoDan_WordLOC_MLO"
OUT_DIR = Path("diag")
WIN_LO_MS = 60
WIN_HI_MS = 220


def _load_raster(h5_path: Path) -> tuple[np.ndarray, dict]:
    with h5py.File(h5_path, "r") as f:
        shape = tuple(f.attrs["original_shape"].tolist())
        n_units, n_trials, n_timebins = shape
        if f.attrs["storage_format"] == "sparse":
            row = f["row"][:]; col = f["col"][:]; data = f["data"][:]
            coo = sparse.coo_matrix(
                (data, (row, col)), shape=(n_units * n_trials, n_timebins)
            )
            raster = coo.toarray().reshape(n_units, n_trials, n_timebins)
        else:
            raster = f["raster"][:]
        meta = dict(f["metadata"].attrs)
    return raster, meta


def _pre_onset(meta: dict) -> int:
    return int(meta.get("pre_onset_ms", meta.get("pre_onset", 0)))


def _mean_fr(raster: np.ndarray, trial_df: pd.DataFrame,
             pre_ms: int, only_valid: bool) -> pd.DataFrame:
    lo = pre_ms + WIN_LO_MS
    hi = pre_ms + WIN_HI_MS
    win_dur_s = (WIN_HI_MS - WIN_LO_MS) / 1000.0
    counts = raster[:, :, lo:hi].sum(axis=2)
    fr = counts.astype(np.float64) / win_dur_s
    df = pd.DataFrame(fr.T)
    df["stim_index"] = trial_df["stim_index"].values
    if only_valid:
        df = df.loc[trial_df["fix_success"].astype(bool).values]
    return df.groupby("stim_index").mean()


def _rdm_lowertri(m: pd.DataFrame) -> np.ndarray:
    arr = m.values
    keep = arr.std(axis=0) > 0
    rdm = np.corrcoef(arr[:, keep])
    return rdm[np.tril_indices_from(rdm, k=-1)]


def _corr(a: np.ndarray, b: np.ndarray) -> tuple[float, int]:
    valid = np.isfinite(a) & np.isfinite(b)
    if valid.sum() < 3:
        return float("nan"), int(valid.sum())
    return float(np.corrcoef(a[valid], b[valid])[0, 1]), int(valid.sum())


def main() -> None:
    print("Loading derivatives...")
    ref_raster, ref_meta = _load_raster(REF_DERIV / f"TrialRaster_{REF_STEM}.h5")
    ours_raster, ours_meta = _load_raster(OURS_DERIV / f"TrialRaster_{OURS_STEM}.h5")
    ref_trials = pd.read_csv(REF_DERIV / f"TrialRecord_{REF_STEM}.csv")
    ours_trials = pd.read_csv(OURS_DERIV / f"TrialRecord_{OURS_STEM}.csv")
    ref_prop = pd.read_csv(REF_DERIV / f"UnitProp_{REF_STEM}.csv")
    ours_prop = pd.read_csv(OURS_DERIV / f"UnitProp_{OURS_STEM}.csv")
    pairing = pd.read_csv(OUT_DIR / "unit_pairing.csv")
    ref_pre = _pre_onset(ref_meta)
    ours_pre = _pre_onset(ours_meta)

    print(
        f"ref raster {ref_raster.shape[0]} units, UnitProp {len(ref_prop)} rows "
        f"(ks_id max {int(ref_prop['ks_id'].max())})"
    )
    print(
        f"ours raster {ours_raster.shape[0]} units, UnitProp {len(ours_prop)} rows "
        f"(ks_id max {int(ours_prop['ks_id'].max())})"
    )
    print(
        f"pairing csv: {len(pairing)} rows, matched={int(pairing['matched'].sum())}"
    )

    # Build ks_id -> row index maps from UnitProp.csv
    ref_ks2row = dict(zip(ref_prop["ks_id"].astype(int), ref_prop["id"].astype(int)))
    ours_ks2row = dict(zip(ours_prop["ks_id"].astype(int), ours_prop["id"].astype(int)))

    matched = pairing.loc[pairing["matched"]].copy()
    matched["ref_row"] = matched["ks_id_ref"].map(ref_ks2row)
    matched["ours_row"] = matched["ks_id_ours"].map(ours_ks2row)
    both_ok = matched.dropna(subset=["ref_row", "ours_row"]).copy()
    both_ok[["ref_row", "ours_row"]] = both_ok[["ref_row", "ours_row"]].astype(int)
    n_pairs = len(both_ok)
    print(
        f"matched pairs with both units surviving in deriv raster "
        f"(corrected via UnitProp): {n_pairs}/{len(matched)}"
    )

    ref_rows = both_ok["ref_row"].to_numpy()
    ours_rows = both_ok["ours_row"].to_numpy()
    print(f"ref_rows unique={len(np.unique(ref_rows))}, "
          f"ours_rows unique={len(np.unique(ours_rows))}")

    ref_sub = ref_raster[ref_rows]
    ours_sub = ours_raster[ours_rows]
    print(f"ref_sub {ref_sub.shape}, ours_sub {ours_sub.shape}")

    lines: list[str] = []
    lines.append(
        f"V.8.3 corrected (use UnitProp.csv ks_id->row map): "
        f"matched-in-raster = {n_pairs} pairs"
    )
    for only_valid in (False, True):
        tag = "all trials" if not only_valid else "fix_success only"
        ref_fr = _mean_fr(ref_sub, ref_trials, ref_pre, only_valid)
        ours_fr = _mean_fr(ours_sub, ours_trials, ours_pre, only_valid)
        assert (ref_fr.index == ours_fr.index).all()
        lo_r = _rdm_lowertri(ref_fr)
        lo_o = _rdm_lowertri(ours_fr)
        pear, n = _corr(lo_r, lo_o)
        line = f"  shared-{n_pairs} [{tag}]: pearson={pear:.4f} pairs={n}"
        print(line)
        lines.append(line)

    # For calibration: FULL RDM
    print("\nFULL (for reference):")
    lines.append("\nFULL (for reference):")
    for only_valid in (False, True):
        tag = "all trials" if not only_valid else "fix_success only"
        ref_fr = _mean_fr(ref_raster, ref_trials, ref_pre, only_valid)
        ours_fr = _mean_fr(ours_raster, ours_trials, ours_pre, only_valid)
        lo_r = _rdm_lowertri(ref_fr)
        lo_o = _rdm_lowertri(ours_fr)
        pear, n = _corr(lo_r, lo_o)
        line = f"  FULL [{tag}]: pearson={pear:.4f} pairs={n}"
        print(line)
        lines.append(line)

    (OUT_DIR / "v8_shared_subset_corrected.txt").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(f"\nwrote {OUT_DIR / 'v8_shared_subset_corrected.txt'}")


if __name__ == "__main__":
    main()
