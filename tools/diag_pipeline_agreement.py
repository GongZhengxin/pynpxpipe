"""VI.5 - Pipeline agreement metrics on matched pairs.

Metric A: per-pair per-image FR Pearson correlation (using raster + stim labels).
Metric B: per-pair spike-train F1 at +-1 ms (~30 samples @ 30 kHz) using
          sorting.get_unit_spike_train() frame indices (both pipelines share
          the same sample basis).
Metric C: Recall / Precision of pipeline pairing, overall + split by unittype.

Outputs:
  diag/pipeline_agreement.csv        (per-pair A + B + unit metadata)
  diag/pipeline_agreement_summary.txt
  diag/pipeline_agreement_hist.png
"""

from __future__ import annotations

import os
from pathlib import Path

import h5py
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import spikeinterface as si
from scipy import sparse

_OURS_ROOT = Path(os.environ.get("PYNPX_OURS_ROOT", r"F:/#Datasets/demo_rawdata/processed_pynpxpipe"))
_OUT_DIR_OVERRIDE = os.environ.get("PYNPX_DIAG_OUT")

REF_ANALYZER = Path(r"F:/#Datasets/demo_rawdata/processed_good/SI/analyzer")
OURS_ANALYZER = _OURS_ROOT / "06_postprocessed" / "imec0"
REF_DERIV = Path(r"F:/#Datasets/demo_rawdata/processed_good/deriv")
OURS_DERIV = _OURS_ROOT / "07_derivatives"
REF_STEM = "241026_MaoDan_WordLocalizer_MLO"
OURS_STEM = "241029_MaoDan_WordLOC_MLO"
OUT_DIR = Path(_OUT_DIR_OVERRIDE) if _OUT_DIR_OVERRIDE else Path("diag")
F1_TOL_SAMPLES = 30  # ~1 ms @ 30 kHz
WIN_LO_MS = 60
WIN_HI_MS = 220


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


def _load_raster(h5_path: Path) -> tuple[np.ndarray, dict]:
    with h5py.File(h5_path, "r") as f:
        shape = tuple(f.attrs["original_shape"].tolist())
        n_units, n_trials, n_timebins = shape
        if f.attrs["storage_format"] == "sparse":
            row = f["row"][:]; col = f["col"][:]; data = f["data"][:]
            coo = sparse.coo_matrix(
                (data, (row, col)), shape=(n_units * n_trials, n_timebins),
            )
            raster = coo.toarray().reshape(n_units, n_trials, n_timebins)
        else:
            raster = f["raster"][:]
        meta = dict(f["metadata"].attrs)
    return raster, meta


def _pre_onset(meta: dict) -> int:
    return int(meta.get("pre_onset_ms", meta.get("pre_onset", 0)))


def _window_counts(raster: np.ndarray, pre_ms: int) -> np.ndarray:
    lo = pre_ms + WIN_LO_MS
    hi = pre_ms + WIN_HI_MS
    return raster[:, :, lo:hi].sum(axis=2)


def _mean_fr_per_image(counts: np.ndarray, trial_df: pd.DataFrame,
                      only_valid: bool) -> pd.DataFrame:
    """(n_units, n_trials) counts -> (n_images, n_units) mean FR (Hz)."""
    win_dur_s = (WIN_HI_MS - WIN_LO_MS) / 1000.0
    fr = counts.astype(np.float64) / win_dur_s
    df = pd.DataFrame(fr.T)
    df["stim_index"] = trial_df["stim_index"].values
    if only_valid:
        df = df.loc[trial_df["fix_success"].astype(bool).values]
    return df.groupby("stim_index").mean()


def _spike_f1(frames_a: np.ndarray, frames_b: np.ndarray, tol: int
              ) -> tuple[float, float, float, int, int, int]:
    """Greedy nearest-match within +-tol samples; return precision/recall/F1/TP/FP/FN.

    Assumes both sorted ascending.
    """
    a = np.sort(frames_a); b = np.sort(frames_b)
    used_b = np.zeros(len(b), dtype=bool)
    tp = 0
    j_lo = 0
    for fa in a:
        # advance j_lo to first b >= fa - tol
        while j_lo < len(b) and b[j_lo] < fa - tol:
            j_lo += 1
        # find the closest unused b in [fa-tol, fa+tol]
        j = j_lo
        best = -1
        best_d = tol + 1
        while j < len(b) and b[j] <= fa + tol:
            if not used_b[j]:
                d = abs(int(b[j]) - int(fa))
                if d < best_d:
                    best = j
                    best_d = d
            j += 1
        if best >= 0:
            used_b[best] = True
            tp += 1
    fp = len(a) - tp
    fn = len(b) - tp
    prec = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    rec = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else float("nan")
    return prec, rec, f1, tp, fp, fn


def main() -> None:
    _nature_rc()
    OUT_DIR.mkdir(exist_ok=True)

    print("Loading analyzers...")
    ref_a = si.load_sorting_analyzer(folder=str(REF_ANALYZER), load_extensions=True)
    ours_a = si.load_sorting_analyzer(folder=str(OURS_ANALYZER), load_extensions=True)
    ref_ids = np.asarray(ref_a.unit_ids)
    ours_ids = np.asarray(ours_a.unit_ids)

    print("Loading rasters + trial records + unit prop...")
    ref_raster, ref_meta = _load_raster(REF_DERIV / f"TrialRaster_{REF_STEM}.h5")
    ours_raster, ours_meta = _load_raster(OURS_DERIV / f"TrialRaster_{OURS_STEM}.h5")
    ref_trials = pd.read_csv(REF_DERIV / f"TrialRecord_{REF_STEM}.csv")
    ours_trials = pd.read_csv(OURS_DERIV / f"TrialRecord_{OURS_STEM}.csv")
    ref_prop = pd.read_csv(REF_DERIV / f"UnitProp_{REF_STEM}.csv")
    ours_prop = pd.read_csv(OURS_DERIV / f"UnitProp_{OURS_STEM}.csv")
    pairing = pd.read_csv(OUT_DIR / "unit_pairing.csv")

    ref_ks2row = dict(zip(ref_prop["ks_id"].astype(int), ref_prop["id"].astype(int)))
    ours_ks2row = dict(zip(ours_prop["ks_id"].astype(int), ours_prop["id"].astype(int)))
    ref_ks2unittype = dict(
        zip(ref_prop["ks_id"].astype(int), ref_prop["unittype"].astype(int))
    )
    ours_ks2unittype = dict(
        zip(ours_prop["ks_id"].astype(int), ours_prop["unittype"].astype(int))
    )

    ref_counts = _window_counts(ref_raster, _pre_onset(ref_meta))
    ours_counts = _window_counts(ours_raster, _pre_onset(ours_meta))

    ref_fr_img = _mean_fr_per_image(ref_counts, ref_trials, only_valid=True)
    ours_fr_img = _mean_fr_per_image(ours_counts, ours_trials, only_valid=True)
    common_stims = ref_fr_img.index.intersection(ours_fr_img.index)
    ref_fr_img = ref_fr_img.loc[common_stims]
    ours_fr_img = ours_fr_img.loc[common_stims]
    print(f"common stims: {len(common_stims)}")

    matched = pairing[pairing["matched"]].copy()
    print(f"matched pairs in analyzer space: {len(matched)}")

    records: list[dict] = []
    for _, rec in matched.iterrows():
        ks_ref = int(rec["ks_id_ref"])
        ks_ours = int(rec["ks_id_ours"])
        ref_row = ref_ks2row.get(ks_ref)
        ours_row = ours_ks2row.get(ks_ours)
        ref_ut = ref_ks2unittype.get(ks_ref)
        ours_ut = ours_ks2unittype.get(ks_ours)

        # Metric A: per-image FR Pearson (requires both units in raster)
        metric_A = float("nan")
        if ref_row is not None and ours_row is not None:
            r_vec = ref_fr_img[ref_row].values
            o_vec = ours_fr_img[ours_row].values
            if r_vec.std() > 0 and o_vec.std() > 0:
                metric_A = float(np.corrcoef(r_vec, o_vec)[0, 1])

        # Metric B: spike-frame F1
        r_spikes = ref_a.sorting.get_unit_spike_train(ks_ref)
        o_spikes = ours_a.sorting.get_unit_spike_train(ks_ours)
        prec, rec_, f1, tp, fp, fn = _spike_f1(r_spikes, o_spikes, F1_TOL_SAMPLES)

        records.append({
            "ks_id_ref": ks_ref, "ks_id_ours": ks_ours,
            "cos": float(rec["cos"]), "d_xy": float(rec["d_xy"]),
            "sim": float(rec["sim"]),
            "ref_row": ref_row, "ours_row": ours_row,
            "ref_unittype": ref_ut, "ours_unittype": ours_ut,
            "n_spikes_ref": int(len(r_spikes)), "n_spikes_ours": int(len(o_spikes)),
            "metric_A_pearson_fr": metric_A,
            "metric_B_precision": prec,
            "metric_B_recall": rec_,
            "metric_B_f1": f1,
            "B_tp": tp, "B_fp": fp, "B_fn": fn,
        })

    df = pd.DataFrame(records)
    df.to_csv(OUT_DIR / "pipeline_agreement.csv", index=False)
    print(f"wrote {OUT_DIR / 'pipeline_agreement.csv'}")

    # Summary
    lines: list[str] = []
    lines.append(f"VI.5 pipeline agreement on {len(df)} matched pairs")
    lines.append(f"tolerance = {F1_TOL_SAMPLES} samples (~{F1_TOL_SAMPLES/30:.2f} ms)")

    def _q(vals: pd.Series, q: float) -> float:
        v = vals.dropna()
        return float(np.nanquantile(v, q)) if len(v) else float("nan")

    lines.append("\n[A] per-pair per-image FR Pearson:")
    lines.append(
        f"  median={_q(df['metric_A_pearson_fr'], 0.5):.3f}  "
        f"P25={_q(df['metric_A_pearson_fr'], 0.25):.3f}  "
        f"P75={_q(df['metric_A_pearson_fr'], 0.75):.3f}"
    )
    a_valid = df["metric_A_pearson_fr"].dropna()
    lines.append(f"  %>0.5: {(a_valid > 0.5).mean() * 100:.1f}%  "
                 f"%>0.8: {(a_valid > 0.8).mean() * 100:.1f}%  "
                 f"n_valid: {len(a_valid)}")

    lines.append("\n[B] per-pair spike-train F1 (+-1 ms):")
    b_valid = df["metric_B_f1"].dropna()
    lines.append(
        f"  median_F1={_q(df['metric_B_f1'], 0.5):.3f}  "
        f"P25={_q(df['metric_B_f1'], 0.25):.3f}  "
        f"P75={_q(df['metric_B_f1'], 0.75):.3f}"
    )
    lines.append(f"  %F1>0.5: {(b_valid > 0.5).mean() * 100:.1f}%  "
                 f"%F1>0.8: {(b_valid > 0.8).mean() * 100:.1f}%  "
                 f"%F1<0.2: {(b_valid < 0.2).mean() * 100:.1f}%  "
                 f"n={len(b_valid)}")
    lines.append(
        f"  median precision={_q(df['metric_B_precision'], 0.5):.3f}  "
        f"median recall={_q(df['metric_B_recall'], 0.5):.3f}"
    )

    lines.append("\n[C] Recall / Precision:")
    n_matched = int(pairing["matched"].sum())
    n_ref = len(ref_ids); n_ours = len(ours_ids)
    lines.append(
        f"  overall: matched={n_matched}  ref_total={n_ref}  ours_total={n_ours}  "
        f"recall(ref-covered)={n_matched/n_ref*100:.1f}%  "
        f"precision(ours-matched)={n_matched/n_ours*100:.1f}%"
    )
    unittype_names = {1: "SUA", 2: "MUA", 3: "NOISE", 0: "UNKNOWN"}
    lines.append("\n  by unittype (join via UnitProp when possible):")
    for ut in (1, 2, 3, 0):
        ref_mask = ref_prop["unittype"] == ut
        ours_mask = ours_prop["unittype"] == ut
        n_ref_ut = int(ref_mask.sum())
        n_ours_ut = int(ours_mask.sum())
        # matched-for-this-unittype: need both sides unittype same
        both_ut = df[(df["ref_unittype"] == ut) & (df["ours_unittype"] == ut)]
        n_matched_ut = len(both_ut)
        lines.append(
            f"    {unittype_names[ut]:>8s}: ref={n_ref_ut:3d}  ours={n_ours_ut:3d}  "
            f"both-matched={n_matched_ut:3d}"
        )

    (OUT_DIR / "pipeline_agreement_summary.txt").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    print(f"wrote {OUT_DIR / 'pipeline_agreement_summary.txt'}")
    print("\n".join(lines))

    # Histogram figure
    fig, axes = plt.subplots(1, 2, figsize=(6.0, 2.3))
    ax = axes[0]
    ax.hist(a_valid, bins=np.linspace(-0.2, 1.0, 30),
            color="tab:blue", edgecolor="white", linewidth=0.4)
    ax.axvline(a_valid.median(), color="k", ls="--", lw=0.5)
    ax.set_xlabel("metric A: per-image FR Pearson")
    ax.set_ylabel("# matched pairs")
    ax.set_title(f"A: median={a_valid.median():.2f}  n={len(a_valid)}")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    ax = axes[1]
    ax.hist(b_valid, bins=np.linspace(0, 1.0, 30),
            color="tab:orange", edgecolor="white", linewidth=0.4)
    ax.axvline(b_valid.median(), color="k", ls="--", lw=0.5)
    ax.set_xlabel("metric B: spike F1 (+-1 ms)")
    ax.set_ylabel("# matched pairs")
    ax.set_title(f"B: median={b_valid.median():.2f}  n={len(b_valid)}")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    fig.tight_layout()
    fig.savefig(OUT_DIR / "pipeline_agreement_hist.png")
    fig.savefig(OUT_DIR / "pipeline_agreement_hist.svg")
    print(f"wrote {OUT_DIR / 'pipeline_agreement_hist.png'}")


if __name__ == "__main__":
    main()
