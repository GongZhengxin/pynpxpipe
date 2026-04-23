"""VI.1 — RDM stability ablation across trial_frac x unit_count.

Goal: determine whether the "shared-subset RDM 0.34 < FULL 0.77" result from
V.8 is driven by unit-count (my prior claim) or something else. We scan the
two axes independently under three conditions and check internal consistency:

  - ref_split  : within-reference split-half reliability
  - ours_split : within-pynpxpipe split-half reliability
  - cross      : cross-pipeline Pearson on lower-tri RDM (independent unit
                 bootstrap each side; NOT shared physical neurons -- that
                 is V.8.3's job)

If ref_split @ unit_count=133 approaches ours_split @ unit_count=259 and
both approach cross @ shared-133, the unit-count explanation is confirmed.
Otherwise, V.7/V.8 need reinterpretation.

Output:
  diag/rdm_ablation.csv  : one row per (seed, trial_frac, unit_count, condition)
  diag/rdm_ablation_summary.txt

Usage:
  uv run python tools/diag_rdm_ablation.py                # all units
  uv run python tools/diag_rdm_ablation.py --filter-noise # VI.2 : exclude unittype==3
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
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
WIN_LO_MS = 60
WIN_HI_MS = 220

TRIAL_FRACS = (0.50, 0.75, 1.00)
UNIT_COUNTS = (33, 66, 100, 133, 170, 220, None)  # None => full
N_SEEDS = 10
ONLY_VALID = True  # fix_success only; matches V.3 main setting


@dataclass
class PipelineBundle:
    tag: str
    counts: np.ndarray  # (n_units, n_trials) spike counts in window
    trial_df: pd.DataFrame
    unit_keep_mask: np.ndarray  # boolean (n_units,)

    @property
    def n_units_total(self) -> int:
        return int(self.unit_keep_mask.sum())


def _load_raster(h5_path: Path) -> tuple[np.ndarray, dict]:
    with h5py.File(h5_path, "r") as f:
        shape = tuple(f.attrs["original_shape"].tolist())
        n_units, n_trials, n_timebins = shape
        if f.attrs["storage_format"] == "sparse":
            row = f["row"][:]
            col = f["col"][:]
            data = f["data"][:]
            coo = sparse.coo_matrix(
                (data, (row, col)), shape=(n_units * n_trials, n_timebins)
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
    lo = pre_ms + WIN_LO_MS
    hi = pre_ms + WIN_HI_MS
    return raster[:, :, lo:hi].sum(axis=2)


def _load_bundle(tag: str, deriv_dir: Path, stem: str, filter_noise: bool) -> PipelineBundle:
    raster, meta = _load_raster(deriv_dir / f"TrialRaster_{stem}.h5")
    trial_df = pd.read_csv(deriv_dir / f"TrialRecord_{stem}.csv")
    pre = _pre_onset_ms(meta)
    counts = _window_counts(raster, pre)
    unit_prop = pd.read_csv(deriv_dir / f"UnitProp_{stem}.csv")
    assert len(unit_prop) == counts.shape[0], (
        f"{tag}: UnitProp rows {len(unit_prop)} != raster units {counts.shape[0]}"
    )
    if filter_noise:
        keep = unit_prop["unittype"].isin([1, 2]).values
    else:
        keep = np.ones(len(unit_prop), dtype=bool)
    return PipelineBundle(tag=tag, counts=counts, trial_df=trial_df, unit_keep_mask=keep)


def _select_trial_subset(
    trial_df: pd.DataFrame, frac: float, only_valid: bool, rng: np.random.Generator
) -> np.ndarray:
    """Return trial-row indices to keep, preserving stim_index balance.

    For each stim_index, keep ceil(frac * n_trials_for_stim) randomly chosen
    trials. Drop trials with fix_success==0 when only_valid=True.
    """
    mask = np.ones(len(trial_df), dtype=bool)
    if only_valid:
        mask &= trial_df["fix_success"].astype(bool).values
    df = trial_df[mask].copy()
    df["_row"] = np.arange(len(trial_df))[mask]
    keep_rows: list[int] = []
    for _stim, grp in df.groupby("stim_index"):
        pool = grp["_row"].values
        n_keep = max(2, int(np.ceil(frac * len(pool))))
        n_keep = min(n_keep, len(pool))
        if n_keep < len(pool):
            chosen = rng.choice(pool, size=n_keep, replace=False)
        else:
            chosen = pool
        keep_rows.extend(chosen.tolist())
    return np.sort(np.asarray(keep_rows, dtype=int))


def _mean_fr_per_stim(
    counts: np.ndarray, trial_rows: np.ndarray, stim_indices: np.ndarray
) -> pd.DataFrame:
    """Return (n_images, n_units) mean firing rate dataframe indexed by stim_index."""
    win_dur_s = (WIN_HI_MS - WIN_LO_MS) / 1000.0
    sub = counts[:, trial_rows]  # (n_units, n_sub_trials)
    fr = sub.astype(np.float64) / win_dur_s
    df = pd.DataFrame(fr.T)  # rows=trials, cols=unit_idx
    df["stim_index"] = stim_indices[trial_rows]
    return df.groupby("stim_index").mean()


def _rdm_lower_tri(mean_fr: pd.DataFrame) -> np.ndarray:
    arr = mean_fr.values
    std = arr.std(axis=0)
    keep = std > 0
    if keep.sum() < 2:
        return np.array([])
    arr = arr[:, keep]
    rdm = np.corrcoef(arr)
    return rdm[np.tril_indices_from(rdm, k=-1)]


def _split_trials(trial_rows: np.ndarray, stim_indices: np.ndarray, rng: np.random.Generator
                  ) -> tuple[np.ndarray, np.ndarray]:
    """Split trial_rows into two halves stratified by stim_index."""
    rows_a: list[int] = []
    rows_b: list[int] = []
    df = pd.DataFrame({"row": trial_rows, "stim": stim_indices[trial_rows]})
    for _stim, grp in df.groupby("stim"):
        pool = grp["row"].values
        perm = rng.permutation(len(pool))
        rows_a.extend(pool[perm[::2]].tolist())
        rows_b.extend(pool[perm[1::2]].tolist())
    return np.sort(np.asarray(rows_a, dtype=int)), np.sort(np.asarray(rows_b, dtype=int))


def _bootstrap_units(keep_mask: np.ndarray, k: int | None, rng: np.random.Generator) -> np.ndarray:
    pool = np.where(keep_mask)[0]
    if k is None or k >= len(pool):
        return pool
    return np.sort(rng.choice(pool, size=k, replace=False))


def _lower_tri_pearson(a: np.ndarray, b: np.ndarray) -> tuple[float, int]:
    if a.size == 0 or b.size == 0:
        return float("nan"), 0
    if a.size != b.size:
        return float("nan"), 0
    valid = np.isfinite(a) & np.isfinite(b)
    if valid.sum() < 3:
        return float("nan"), int(valid.sum())
    r = float(np.corrcoef(a[valid], b[valid])[0, 1])
    return r, int(valid.sum())


def _split_half_correlation(
    bundle: PipelineBundle, unit_idx: np.ndarray,
    trial_rows: np.ndarray, rng: np.random.Generator,
) -> tuple[float, int]:
    rows_a, rows_b = _split_trials(trial_rows, bundle.trial_df["stim_index"].values, rng)
    if len(rows_a) < 2 or len(rows_b) < 2:
        return float("nan"), 0
    counts_sub = bundle.counts[unit_idx]
    mean_a = _mean_fr_per_stim(counts_sub, rows_a, bundle.trial_df["stim_index"].values)
    mean_b = _mean_fr_per_stim(counts_sub, rows_b, bundle.trial_df["stim_index"].values)
    common = mean_a.index.intersection(mean_b.index)
    if len(common) < 5:
        return float("nan"), 0
    lo_a = _rdm_lower_tri(mean_a.loc[common])
    lo_b = _rdm_lower_tri(mean_b.loc[common])
    return _lower_tri_pearson(lo_a, lo_b)


def _cross_correlation(
    ref: PipelineBundle, ours: PipelineBundle,
    ref_unit_idx: np.ndarray, ours_unit_idx: np.ndarray,
    ref_rows: np.ndarray, ours_rows: np.ndarray,
) -> tuple[float, int]:
    mean_ref = _mean_fr_per_stim(
        ref.counts[ref_unit_idx], ref_rows, ref.trial_df["stim_index"].values,
    )
    mean_ours = _mean_fr_per_stim(
        ours.counts[ours_unit_idx], ours_rows, ours.trial_df["stim_index"].values,
    )
    common = mean_ref.index.intersection(mean_ours.index)
    if len(common) < 5:
        return float("nan"), 0
    lo_ref = _rdm_lower_tri(mean_ref.loc[common])
    lo_ours = _rdm_lower_tri(mean_ours.loc[common])
    return _lower_tri_pearson(lo_ref, lo_ours)


def run(filter_noise: bool, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    ref = _load_bundle("ref", REF_DIR, REF_STEM, filter_noise)
    ours = _load_bundle("ours", OURS_DIR, OURS_STEM, filter_noise)
    tag = "filtered_sua_mua" if filter_noise else "all_units"
    print(
        f"[{tag}] ref units {ref.n_units_total}/{ref.counts.shape[0]}, "
        f"ours units {ours.n_units_total}/{ours.counts.shape[0]}"
    )

    rows: list[dict] = []
    for seed in range(N_SEEDS):
        rng = np.random.default_rng(seed)
        for trial_frac in TRIAL_FRACS:
            ref_trial_rows = _select_trial_subset(
                ref.trial_df, trial_frac, ONLY_VALID, np.random.default_rng(seed * 7919 + 1),
            )
            ours_trial_rows = _select_trial_subset(
                ours.trial_df, trial_frac, ONLY_VALID, np.random.default_rng(seed * 7919 + 2),
            )
            for u_count in UNIT_COUNTS:
                ref_unit_idx = _bootstrap_units(
                    ref.unit_keep_mask, u_count, np.random.default_rng(seed * 6151 + 3),
                )
                ours_unit_idx = _bootstrap_units(
                    ours.unit_keep_mask, u_count, np.random.default_rng(seed * 6151 + 4),
                )

                r_ref, n_ref = _split_half_correlation(
                    ref, ref_unit_idx, ref_trial_rows, np.random.default_rng(seed * 521 + 5),
                )
                r_ours, n_ours = _split_half_correlation(
                    ours, ours_unit_idx, ours_trial_rows, np.random.default_rng(seed * 521 + 6),
                )
                r_cross, n_cross = _cross_correlation(
                    ref, ours, ref_unit_idx, ours_unit_idx, ref_trial_rows, ours_trial_rows,
                )

                row = dict(
                    seed=seed, trial_frac=trial_frac,
                    unit_count=(u_count if u_count is not None else -1),
                    ref_unit_count=len(ref_unit_idx), ours_unit_count=len(ours_unit_idx),
                    filter_noise=filter_noise,
                )
                rows.append({**row, "condition": "ref_split",  "pearson": r_ref,   "pairs": n_ref})
                rows.append({**row, "condition": "ours_split", "pearson": r_ours,  "pairs": n_ours})
                rows.append({**row, "condition": "cross",      "pearson": r_cross, "pairs": n_cross})

        print(f"  seed {seed + 1}/{N_SEEDS} done")

    df = pd.DataFrame(rows)
    suffix = "_filtered" if filter_noise else ""
    csv_path = out_dir / f"rdm_ablation{suffix}.csv"
    df.to_csv(csv_path, index=False)
    print(f"wrote {csv_path}")

    summary = df.groupby(["trial_frac", "unit_count", "condition"]).agg(
        pearson_mean=("pearson", "mean"),
        pearson_std=("pearson", "std"),
        n_seeds=("pearson", "count"),
    ).reset_index()
    summary_path = out_dir / f"rdm_ablation{suffix}_summary.csv"
    summary.to_csv(summary_path, index=False)
    print(f"wrote {summary_path}")

    print("\n-- Summary (mean +- std across seeds) --")
    print(f"condition order: ref_split / ours_split / cross\n")
    for trial_frac in TRIAL_FRACS:
        print(f"trial_frac={trial_frac:.2f}")
        sub = summary[summary["trial_frac"] == trial_frac]
        for u in UNIT_COUNTS:
            u_val = u if u is not None else -1
            row_ref = sub[(sub["unit_count"] == u_val) & (sub["condition"] == "ref_split")]
            row_ours = sub[(sub["unit_count"] == u_val) & (sub["condition"] == "ours_split")]
            row_cross = sub[(sub["unit_count"] == u_val) & (sub["condition"] == "cross")]
            tag_u = "FULL" if u is None else str(u)
            print(
                f"  n_units={tag_u:>4}  "
                f"ref={row_ref.iloc[0]['pearson_mean']:+.3f}+-{row_ref.iloc[0]['pearson_std']:.3f}  "
                f"ours={row_ours.iloc[0]['pearson_mean']:+.3f}+-{row_ours.iloc[0]['pearson_std']:.3f}  "
                f"cross={row_cross.iloc[0]['pearson_mean']:+.3f}+-{row_cross.iloc[0]['pearson_std']:.3f}"
            )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--filter-noise", action="store_true",
                   help="Exclude unittype==3 (NOISE/NON-SOMA) units (VI.2)")
    p.add_argument("--out", default=(_OUT_DIR_OVERRIDE or "diag"),
                   help="Output directory (default: $PYNPX_DIAG_OUT or diag/)")
    args = p.parse_args()
    run(filter_noise=args.filter_noise, out_dir=Path(args.out))


if __name__ == "__main__":
    main()
