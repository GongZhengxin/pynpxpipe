"""VII.C2 - matched-pair spatial distribution using UnitProp-CSV positions.

Companion to ``diag_pair_spatial.py`` (which reads positions from the SI
analyzer). This script reads ``unitpos`` straight from the per-side
``UnitProp_*.csv`` files, exposing the algorithmic gap:

- REF UnitProp (MATLAB pipeline) stores Bombcell ``ksPeakChan_xy`` — the peak
  channel's xy contact position (discrete x ∈ {0, 103} on NPX 1.0).
- OURS UnitProp (pynpxpipe) stores SI ``monopolar_triangulation`` output —
  continuous coordinates.

The matching itself still comes from ``diag/unit_pairing.csv`` (analyzer-based
Hungarian), so the connector lines will highlight how far apart the same
physical neuron is placed when each pipeline uses its own position algorithm.

Output:
  diag/pair_spatial_unitprop.png (600 dpi)
  diag/pair_spatial_unitprop.svg
"""

from __future__ import annotations

import ast
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import spikeinterface as si

REF_ANALYZER = Path(r"F:/#Datasets/demo_rawdata/processed_good/SI/analyzer")
OURS_ANALYZER = Path(r"F:/#Datasets/demo_rawdata/processed_pynpxpipe/06_postprocessed/imec0")
REF_UNITPROP = Path(
    r"F:/#Datasets/demo_rawdata/processed_good/deriv/UnitProp_241026_MaoDan_WordLocalizer_MLO.csv"
)
OURS_UNITPROP = Path(
    r"F:/#Datasets/demo_rawdata/processed_pynpxpipe/07_derivatives/UnitProp_241029_MaoDan_WordLOC_MLO.csv"
)
OUT_DIR = Path("diag")
SEED = 1
JITTER_UM = 8.0

SIZE_MIN = 12.0
SIZE_MAX = 40.0

REF_EDGE = "#1f77b4"
OURS_FILL = "#ff7f0e"
REF_ONLY_FILL = "#aaccee"
OURS_ONLY_FILL = "#ffcc99"
MATCH_LINE = "#555555"


def _nature_rc() -> None:
    plt.rcParams.update({
        "font.family": "Arial",
        "font.size": 6,
        "axes.linewidth": 0.4,
        "xtick.major.width": 0.4,
        "ytick.major.width": 0.4,
        "xtick.labelsize": 5,
        "ytick.labelsize": 5,
        "lines.linewidth": 0.4,
        "savefig.dpi": 600,
        "savefig.bbox": "tight",
    })


def _parse_unitpos_col(unitpos_series: pd.Series) -> np.ndarray:
    """Parse string ``unitpos`` column (e.g. '[0.0, 54.79]' or '[ 0. 67.6]')."""
    xs: list[float] = []
    ys: list[float] = []
    for raw in unitpos_series:
        s = str(raw).strip()
        # MATLAB writes numpy-like '[ 0.       31.75]' without commas; try
        # literal_eval first, then fall back to splitting on whitespace.
        try:
            v = ast.literal_eval(s)
            x, y = float(v[0]), float(v[1])
        except (ValueError, SyntaxError):
            inner = s.strip("[]").replace(",", " ").split()
            x, y = float(inner[0]), float(inner[1])
        xs.append(x)
        ys.append(y)
    return np.column_stack([xs, ys])


def _firing_rate(analyzer: si.SortingAnalyzer) -> dict[int, float]:
    sorting = analyzer.sorting
    dur_s = float(analyzer.get_total_duration())
    out: dict[int, float] = {}
    for uid in sorting.unit_ids:
        n = len(sorting.get_unit_spike_train(uid))
        out[int(uid)] = n / dur_s if dur_s > 0 else 0.0
    return out


def _log_size(fr: np.ndarray, vmax: float) -> np.ndarray:
    s = np.log1p(np.asarray(fr))
    norm = s / max(np.log1p(vmax), 1e-9)
    return SIZE_MIN + (SIZE_MAX - SIZE_MIN) * np.clip(norm, 0, 1)


def main() -> None:
    _nature_rc()
    OUT_DIR.mkdir(exist_ok=True)
    pairing = pd.read_csv(OUT_DIR / "unit_pairing.csv")

    print("Reading UnitProp CSVs...")
    ref_up = pd.read_csv(REF_UNITPROP)
    ours_up = pd.read_csv(OURS_UNITPROP)
    ref_locs = _parse_unitpos_col(ref_up["unitpos"])
    ours_locs = _parse_unitpos_col(ours_up["unitpos"])
    ref_ids = ref_up["ks_id"].to_numpy(dtype=int)
    ours_ids = ours_up["ks_id"].to_numpy(dtype=int)
    print(f"ref UnitProp: {len(ref_ids)} units  "
          f"x-range [{ref_locs[:, 0].min():.2f}, {ref_locs[:, 0].max():.2f}]  "
          f"unique x count={len(np.unique(np.round(ref_locs[:, 0], 1)))}")
    print(f"ours UnitProp: {len(ours_ids)} units  "
          f"x-range [{ours_locs[:, 0].min():.2f}, {ours_locs[:, 0].max():.2f}]  "
          f"unique x count={len(np.unique(np.round(ours_locs[:, 0], 1)))}")

    ref_id2row = {int(u): i for i, u in enumerate(ref_ids)}
    ours_id2row = {int(u): i for i, u in enumerate(ours_ids)}

    print("Loading analyzers for firing rate...")
    ref_a = si.load_sorting_analyzer(folder=str(REF_ANALYZER), load_extensions=False)
    ours_a = si.load_sorting_analyzer(folder=str(OURS_ANALYZER), load_extensions=False)
    ref_fr_map = _firing_rate(ref_a)
    ours_fr_map = _firing_rate(ours_a)
    vmax = max(max(ref_fr_map.values()), max(ours_fr_map.values()))
    ref_fr = np.array([ref_fr_map.get(int(k), 0.0) for k in ref_ids])
    ours_fr = np.array([ours_fr_map.get(int(k), 0.0) for k in ours_ids])
    ref_size = _log_size(ref_fr, vmax)
    ours_size = _log_size(ours_fr, vmax)

    rng = np.random.default_rng(SEED)
    matched = pairing[pairing["matched"]].copy()
    matched["ref_row"] = matched["ks_id_ref"].map(ref_id2row)
    matched["ours_row"] = matched["ks_id_ours"].map(ours_id2row)
    matched = matched.dropna(subset=["ref_row", "ours_row"]).copy()
    matched[["ref_row", "ours_row"]] = matched[["ref_row", "ours_row"]].astype(int)
    matched["jitter"] = rng.uniform(-JITTER_UM, JITTER_UM, size=len(matched))
    print(f"matched pairs that exist in both UnitProp CSVs: {len(matched)}")

    # Compute median unitprop-based d_xy for the caption
    d_csv = np.hypot(
        ours_locs[matched["ours_row"].values, 0]
        - ref_locs[matched["ref_row"].values, 0],
        ours_locs[matched["ours_row"].values, 1]
        - ref_locs[matched["ref_row"].values, 1],
    )

    fig, ax = plt.subplots(figsize=(4.0, 7.2))

    # Background probe contacts
    try:
        probe = ref_a.get_probe()
        contacts = probe.contact_positions
        ax.scatter(contacts[:, 0], contacts[:, 1], s=0.6,
                   color="grey", alpha=0.18, marker=".", edgecolors="none",
                   zorder=0)
    except Exception as exc:
        print(f"Could not draw probe grid: {exc}")

    matched_ref_rows = set()
    matched_ours_rows = set()
    for _, rec in matched.iterrows():
        rr = int(rec["ref_row"])
        orw = int(rec["ours_row"])
        jit = rec["jitter"]
        xr, yr = ref_locs[rr, 0] + jit, ref_locs[rr, 1]
        xo, yo = ours_locs[orw, 0] + jit, ours_locs[orw, 1]
        ax.plot([xr, xo], [yr, yo],
                color=MATCH_LINE, lw=0.6, alpha=0.85, zorder=1)
        ax.scatter(xr, yr, s=ref_size[rr],
                   facecolors="none", edgecolors=REF_EDGE,
                   linewidth=0.7, zorder=3)
        ax.scatter(xo, yo, s=ours_size[orw],
                   color=OURS_FILL, edgecolors="none", alpha=0.9, zorder=4)
        matched_ref_rows.add(rr)
        matched_ours_rows.add(orw)

    for i, (x, y) in enumerate(ref_locs):
        if i in matched_ref_rows:
            continue
        ax.scatter(x, y, s=ref_size[i],
                   facecolors=REF_ONLY_FILL, edgecolors=REF_EDGE,
                   linewidth=0.5, alpha=0.85, zorder=2)
    for i, (x, y) in enumerate(ours_locs):
        if i in matched_ours_rows:
            continue
        ax.scatter(x, y, s=ours_size[i],
                   color=OURS_ONLY_FILL, edgecolors="none",
                   alpha=0.85, zorder=2)

    ax.set_xlabel("x (µm)  [from UnitProp CSV]")
    ax.set_ylabel("depth (µm)  [from UnitProp CSV]")
    ax.set_title(
        f"VII.C2 matched-pair spatial distribution — UnitProp CSV source\n"
        f"REF: Bombcell ksPeakChan_xy (discrete)   "
        f"OURS: SI monopolar (continuous)\n"
        f"filled=ours  open=ref  matched={len(matched)}  "
        f"median CSV d_xy = {np.median(d_csv):.1f} µm "
        f"(vs {pairing.loc[pairing['matched'], 'd_xy'].median():.1f} µm "
        f"in analyzer space)",
        fontsize=5.5,
    )
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], marker="o", color="none",
               markerfacecolor="none", markeredgecolor=REF_EDGE,
               markersize=6, markeredgewidth=0.7, label="ref (matched)"),
        Line2D([0], [0], marker="o", color="none",
               markerfacecolor=OURS_FILL, markeredgecolor="none",
               markersize=6, label="ours (matched)"),
        Line2D([0], [0], marker="o", color="none",
               markerfacecolor=REF_ONLY_FILL, markeredgecolor=REF_EDGE,
               markersize=6, markeredgewidth=0.5, label="ref_only"),
        Line2D([0], [0], marker="o", color="none",
               markerfacecolor=OURS_ONLY_FILL, markeredgecolor="none",
               markersize=6, label="ours_only"),
    ]
    ax.legend(handles=handles, loc="upper right",
              fontsize=5, labelspacing=0.5, handletextpad=0.3,
              borderpad=0.4, frameon=False)

    fig.tight_layout()
    out_png = OUT_DIR / "pair_spatial_unitprop.png"
    out_svg = OUT_DIR / "pair_spatial_unitprop.svg"
    fig.savefig(out_png)
    fig.savefig(out_svg)
    print(f"wrote {out_png}")
    print(f"wrote {out_svg}")


if __name__ == "__main__":
    main()
