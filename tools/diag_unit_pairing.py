"""Pair units between two pipelines via template cosine + spatial distance.

For each ref unit / ours unit pair, compute:
  sim = alpha * cos(template_ref, template_ours) + beta * exp(-d_xy / d_scale)

Run scipy Hungarian to pick a 1:1 pairing that maximizes total similarity.
Units with sim < match_thr after pairing are declared unmatched.

Outputs (under ``diag/``):
  - unit_pairing.csv   (ks_id_ref, ks_id_ours, cos, d_xy, sim, matched)
  - unit_pairing_summary.txt  (counts, sub-RSM correlations)

V.8.3: re-run the RSM correlation restricted to the matched-pair subset on
both sides, to quantify how much of the cross-pipeline 0.77 is "same units,
differently responding" vs "different unit populations".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
import spikeinterface as si
from scipy import sparse
from scipy.optimize import linear_sum_assignment
from scipy.stats import spearmanr

_OURS_ROOT = Path(os.environ.get("PYNPX_OURS_ROOT", r"F:/#Datasets/demo_rawdata/processed_pynpxpipe"))
_OUT_DIR_OVERRIDE = os.environ.get("PYNPX_DIAG_OUT")

REF_ANALYZER = Path(r"F:/#Datasets/demo_rawdata/processed_good/SI/analyzer")
OURS_ANALYZER = _OURS_ROOT / "06_postprocessed" / "imec0"
REF_DERIV = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv")
OURS_DERIV = _OURS_ROOT / "07_derivatives"
REF_STEM = "241026_MaoDan_WordLocalizer_MLO"
OURS_STEM = "241029_MaoDan_WordLOC_MLO"

ALPHA = 0.7          # weight on template cosine
BETA = 0.3           # weight on spatial proximity
D_SCALE_UM = 100.0   # characteristic length for exp(-d / d_scale)
MATCH_THR = 0.60     # combined similarity threshold for "matched"

WIN_LO_MS = 60
WIN_HI_MS = 220
OUT_DIR = Path(_OUT_DIR_OVERRIDE) if _OUT_DIR_OVERRIDE else Path("diag")


@dataclass
class AnalyzerBundle:
    unit_ids: np.ndarray       # (n_units,) int
    templates: np.ndarray      # (n_units, n_samples, n_channels), averaged, dense
    locations: np.ndarray      # (n_units, 2) xy µm
    ms_before: float
    ms_after: float
    fs: float


def _load_bundle(folder: Path) -> AnalyzerBundle:
    analyzer = si.load_sorting_analyzer(folder=str(folder), load_extensions=True)
    unit_ids = np.asarray(analyzer.unit_ids)
    templates_ext = analyzer.get_extension("templates")
    if templates_ext is None:
        raise RuntimeError(f"templates extension missing in {folder}")
    avg = np.asarray(templates_ext.get_data(operator="average"))
    params = templates_ext.params
    ms_before = float(params["ms_before"])
    ms_after = float(params["ms_after"])
    fs = float(analyzer.sampling_frequency)
    loc_ext = analyzer.get_extension("unit_locations")
    if loc_ext is None:
        raise RuntimeError(f"unit_locations extension missing in {folder}")
    locations = np.asarray(loc_ext.get_data())[:, :2]
    return AnalyzerBundle(
        unit_ids=unit_ids,
        templates=avg,
        locations=locations,
        ms_before=ms_before,
        ms_after=ms_after,
        fs=fs,
    )


def _align_templates(
    a: AnalyzerBundle, b: AnalyzerBundle
) -> tuple[np.ndarray, np.ndarray]:
    """Crop both bundles to the common [-ms_before, +ms_after] window around peak.

    Peak index in each template = round(ms_before * fs). Returns aligned
    (a_crop, b_crop) each with shape (n_units, n_common_samples, n_channels).
    """
    if not np.isclose(a.fs, b.fs, rtol=1e-5):
        raise RuntimeError(f"sampling frequencies differ: {a.fs} vs {b.fs}")
    fs = a.fs
    common_before = min(a.ms_before, b.ms_before)
    common_after = min(a.ms_after, b.ms_after)
    n_before = int(round(common_before * fs / 1000.0))
    n_after = int(round(common_after * fs / 1000.0))
    length = n_before + n_after

    def _crop(bundle: AnalyzerBundle) -> np.ndarray:
        peak_idx = int(round(bundle.ms_before * fs / 1000.0))
        start = peak_idx - n_before
        return bundle.templates[:, start : start + length, :]

    return _crop(a), _crop(b)


def _pairwise_cosine(templates_a: np.ndarray, templates_b: np.ndarray) -> np.ndarray:
    """Cosine similarity between flattened (samples × channels) templates."""
    flat_a = templates_a.reshape(templates_a.shape[0], -1)
    flat_b = templates_b.reshape(templates_b.shape[0], -1)
    norm_a = np.linalg.norm(flat_a, axis=1, keepdims=True)
    norm_b = np.linalg.norm(flat_b, axis=1, keepdims=True)
    norm_a = np.where(norm_a == 0, 1.0, norm_a)
    norm_b = np.where(norm_b == 0, 1.0, norm_b)
    return (flat_a / norm_a) @ (flat_b / norm_b).T


def _pairwise_distance(loc_a: np.ndarray, loc_b: np.ndarray) -> np.ndarray:
    diff = loc_a[:, None, :] - loc_b[None, :, :]
    return np.linalg.norm(diff, axis=2)


def _hungarian_pair(sim: np.ndarray) -> list[tuple[int, int, float]]:
    """Return list of (row, col, sim) for the optimal assignment (max total sim)."""
    # linear_sum_assignment minimizes; negate for maximization.
    rows, cols = linear_sum_assignment(-sim)
    return [(int(r), int(c), float(sim[r, c])) for r, c in zip(rows, cols)]


def _load_raster(h5_path: Path) -> tuple[np.ndarray, dict, np.ndarray]:
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
        if "unit_ids" in f:
            unit_ids = f["unit_ids"][:]
        elif "ks_ids" in f:
            unit_ids = f["ks_ids"][:]
        else:
            unit_ids = np.arange(n_units)
    return raster, meta, np.asarray(unit_ids)


def _pre_onset_ms(meta: dict) -> int:
    if "pre_onset_ms" in meta:
        return int(meta["pre_onset_ms"])
    return int(meta["pre_onset"])


def _mean_fr_per_image(
    raster: np.ndarray,
    trial_df: pd.DataFrame,
    pre_ms: int,
    only_valid: bool,
) -> pd.DataFrame:
    lo = pre_ms + WIN_LO_MS
    hi = pre_ms + WIN_HI_MS
    win_dur_s = (WIN_HI_MS - WIN_LO_MS) / 1000.0
    counts = raster[:, :, lo:hi].sum(axis=2)
    fr = counts.astype(np.float64) / win_dur_s
    df = pd.DataFrame(fr.T)
    df["stim_index"] = trial_df["stim_index"].values
    if only_valid:
        valid = trial_df["fix_success"].astype(bool).values
        df = df.loc[valid]
    return df.groupby("stim_index").mean()


def _rsm_corr(
    ref_mean: pd.DataFrame,
    ours_mean: pd.DataFrame,
) -> tuple[float, float, int]:
    assert (ref_mean.index == ours_mean.index).all()

    def _build(m: pd.DataFrame) -> np.ndarray:
        arr = m.values
        var = arr.std(axis=0)
        keep = var > 0
        return np.corrcoef(arr[:, keep])

    rsm_r = _build(ref_mean)
    rsm_o = _build(ours_mean)
    lo_r = rsm_r[np.tril_indices_from(rsm_r, k=-1)]
    lo_o = rsm_o[np.tril_indices_from(rsm_o, k=-1)]
    valid = np.isfinite(lo_r) & np.isfinite(lo_o)
    pearson = float(np.corrcoef(lo_r[valid], lo_o[valid])[0, 1])
    spearman = float(spearmanr(lo_r[valid], lo_o[valid])[0])
    return pearson, spearman, int(valid.sum())


def _filter_by_unit_ids(
    raster: np.ndarray,
    raster_unit_ids: np.ndarray,
    keep_unit_ids: np.ndarray,
) -> np.ndarray:
    """Return raster rows corresponding to keep_unit_ids (in that order)."""
    id_to_row = {int(uid): idx for idx, uid in enumerate(raster_unit_ids)}
    rows = [id_to_row[int(k)] for k in keep_unit_ids if int(k) in id_to_row]
    return raster[rows]


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True, parents=True)

    print("Loading analyzers (this can take a few seconds)...")
    ref = _load_bundle(REF_ANALYZER)
    ours = _load_bundle(OURS_ANALYZER)
    print(
        f"  ref : {len(ref.unit_ids)} units, template shape "
        f"{ref.templates.shape}, locations {ref.locations.shape}"
    )
    print(
        f"  ours: {len(ours.unit_ids)} units, template shape "
        f"{ours.templates.shape}, locations {ours.locations.shape}"
    )

    ref_tpl, ours_tpl = _align_templates(ref, ours)
    print(
        f"aligned templates: ref {ref_tpl.shape}, ours {ours_tpl.shape} "
        f"(common ms_before={min(ref.ms_before, ours.ms_before)}, "
        f"ms_after={min(ref.ms_after, ours.ms_after)})"
    )
    cos = _pairwise_cosine(ref_tpl, ours_tpl)
    dist = _pairwise_distance(ref.locations, ours.locations)
    prox = np.exp(-dist / D_SCALE_UM)
    sim = ALPHA * cos + BETA * prox
    print(
        f"sim stats: min={sim.min():.3f}  max={sim.max():.3f}  "
        f"median={np.median(sim):.3f}"
    )

    pairs = _hungarian_pair(sim)
    # Build per-row records for CSV
    records: list[dict[str, float | int | bool]] = []
    for r, c, s in pairs:
        records.append(
            {
                "ks_id_ref": int(ref.unit_ids[r]),
                "ks_id_ours": int(ours.unit_ids[c]),
                "cos": float(cos[r, c]),
                "d_xy": float(dist[r, c]),
                "sim": s,
                "matched": bool(s >= MATCH_THR),
            }
        )
    df = pd.DataFrame.from_records(records).sort_values("sim", ascending=False)
    df.to_csv(OUT_DIR / "unit_pairing.csv", index=False)
    print(f"wrote {OUT_DIR / 'unit_pairing.csv'}")

    n_matched = int(df["matched"].sum())
    n_ref_only = int(len(ref.unit_ids) - n_matched)
    n_ours_only = int(len(ours.unit_ids) - n_matched)
    print(f"matched={n_matched}  ref_only={n_ref_only}  ours_only={n_ours_only}")
    print(
        f"cos_sim among matched: median={df.loc[df['matched'], 'cos'].median():.3f}"
        f"  d_xy median={df.loc[df['matched'], 'd_xy'].median():.1f} um"
    )

    # --- Sub-RSM on matched subset -------------------------------------------------
    ref_raster, ref_meta, ref_raster_ids = _load_raster(
        REF_DERIV / f"TrialRaster_{REF_STEM}.h5"
    )
    ours_raster, ours_meta, ours_raster_ids = _load_raster(
        OURS_DERIV / f"TrialRaster_{OURS_STEM}.h5"
    )
    ref_trials = pd.read_csv(REF_DERIV / f"TrialRecord_{REF_STEM}.csv")
    ours_trials = pd.read_csv(OURS_DERIV / f"TrialRecord_{OURS_STEM}.csv")
    ref_pre = _pre_onset_ms(ref_meta)
    ours_pre = _pre_onset_ms(ours_meta)

    matched_df = df.loc[df["matched"]].copy()
    # Keep only pairs where BOTH units survived curation into the raster,
    # so the RSM on each side is computed from the exact same set of pairs.
    ref_ids_set = set(int(x) for x in ref_raster_ids)
    ours_ids_set = set(int(x) for x in ours_raster_ids)
    mask = matched_df["ks_id_ref"].isin(ref_ids_set) & matched_df[
        "ks_id_ours"
    ].isin(ours_ids_set)
    both_in_raster = matched_df.loc[mask]
    ref_matched_ids = both_in_raster["ks_id_ref"].to_numpy()
    ours_matched_ids = both_in_raster["ks_id_ours"].to_numpy()

    ref_sub = _filter_by_unit_ids(ref_raster, ref_raster_ids, ref_matched_ids)
    ours_sub = _filter_by_unit_ids(ours_raster, ours_raster_ids, ours_matched_ids)
    print(
        f"matched & both-in-raster: {len(both_in_raster)}/{len(matched_df)} pairs"
        f"  (ref_sub={ref_sub.shape[0]}, ours_sub={ours_sub.shape[0]})"
    )

    summary_lines: list[str] = []
    summary_lines.append(
        f"Pairing: matched={n_matched}, ref_only={n_ref_only}, ours_only={n_ours_only}"
    )
    summary_lines.append(
        f"cos_sim median among matched={df.loc[df['matched'], 'cos'].median():.3f}, "
        f"d_xy median={df.loc[df['matched'], 'd_xy'].median():.1f} um"
    )
    summary_lines.append(
        f"matched-and-both-in-raster: {len(both_in_raster)}/{len(matched_df)} pairs"
    )

    print("\nRSM correlation (matched subset only):")
    summary_lines.append("\nRSM correlation (matched subset, both-in-raster):")
    for only_valid in (False, True):
        label = "all trials" if not only_valid else "fix_success only"
        ref_fr = _mean_fr_per_image(ref_sub, ref_trials, ref_pre, only_valid)
        ours_fr = _mean_fr_per_image(ours_sub, ours_trials, ours_pre, only_valid)
        p, s, n = _rsm_corr(ref_fr, ours_fr)
        line = f"  [{label}] pearson={p:.4f} spearman={s:.4f} pairs={n}"
        print(line)
        summary_lines.append(line)

    print("\nRSM correlation (FULL sets, for reference):")
    summary_lines.append("\nRSM correlation (FULL sets, for reference):")
    for only_valid in (False, True):
        label = "all trials" if not only_valid else "fix_success only"
        ref_fr = _mean_fr_per_image(ref_raster, ref_trials, ref_pre, only_valid)
        ours_fr = _mean_fr_per_image(ours_raster, ours_trials, ours_pre, only_valid)
        p, s, n = _rsm_corr(ref_fr, ours_fr)
        line = f"  [{label}] pearson={p:.4f} spearman={s:.4f} pairs={n}"
        print(line)
        summary_lines.append(line)

    (OUT_DIR / "unit_pairing_summary.txt").write_text(
        "\n".join(summary_lines), encoding="utf-8"
    )
    print(f"\nwrote {OUT_DIR / 'unit_pairing_summary.txt'}")


if __name__ == "__main__":
    main()
