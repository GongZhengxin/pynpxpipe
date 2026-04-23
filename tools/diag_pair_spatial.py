"""VII.C1 - matched-pair spatial distribution (Nature format, v2).

Same idea as the v1 plot but:
  - larger filled/open circles (size 12-40 pt, scaled by log firing rate)
  - darker, more visible matched-pair connector lines
  - unmatched units keep normal size but use a cooler facecolor instead of
    fading alpha (so they don't disappear into the background)
  - larger per-pair x-jitter (8 µm) so paired ref/ours dots don't overlap

Positions come from ``SortingAnalyzer.get_extension("unit_locations")``
(i.e. SpikeInterface monopolar_triangulation on both sides). See VII.C2 for
the UnitProp-CSV-sourced companion plot.

Output:
  diag/pair_spatial.png (600 dpi)
  diag/pair_spatial.svg
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
SEED = 1
JITTER_UM = 8.0

SIZE_MIN = 12.0
SIZE_MAX = 40.0

REF_EDGE = "#1f77b4"
OURS_FILL = "#ff7f0e"
REF_ONLY_FILL = "#aaccee"   # cool faded blue for ref_only
OURS_ONLY_FILL = "#ffcc99"  # cool faded orange for ours_only
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


def _firing_rate(analyzer: si.SortingAnalyzer) -> np.ndarray:
    """Spikes / second per unit."""
    sorting = analyzer.sorting
    dur_s = float(analyzer.get_total_duration())
    rates = np.zeros(len(sorting.unit_ids))
    for i, uid in enumerate(sorting.unit_ids):
        n = len(sorting.get_unit_spike_train(uid))
        rates[i] = n / dur_s if dur_s > 0 else 0.0
    return rates


def _log_size(fr: np.ndarray) -> np.ndarray:
    """Map log(1+fr) -> [SIZE_MIN, SIZE_MAX]."""
    s = np.log1p(np.asarray(fr))
    if s.max() == s.min():
        return np.full_like(s, (SIZE_MIN + SIZE_MAX) / 2)
    return SIZE_MIN + (SIZE_MAX - SIZE_MIN) * (s - s.min()) / (s.max() - s.min())


def main() -> None:
    _nature_rc()
    OUT_DIR.mkdir(exist_ok=True)
    pairing = pd.read_csv(OUT_DIR / "unit_pairing.csv")

    print("Loading analyzers...")
    ref_a = si.load_sorting_analyzer(folder=str(REF_ANALYZER), load_extensions=True)
    ours_a = si.load_sorting_analyzer(folder=str(OURS_ANALYZER), load_extensions=True)
    ref_locs = np.asarray(ref_a.get_extension("unit_locations").get_data())[:, :2]
    ours_locs = np.asarray(ours_a.get_extension("unit_locations").get_data())[:, :2]
    ref_ids = np.asarray(ref_a.unit_ids)
    ours_ids = np.asarray(ours_a.unit_ids)

    print(f"ref {len(ref_ids)} locations; ours {len(ours_ids)} locations")
    ref_id2row = {int(u): i for i, u in enumerate(ref_ids)}
    ours_id2row = {int(u): i for i, u in enumerate(ours_ids)}

    print("Computing firing rates...")
    ref_fr = _firing_rate(ref_a)
    ours_fr = _firing_rate(ours_a)
    ref_size = _log_size(ref_fr)
    ours_size = _log_size(ours_fr)

    rng = np.random.default_rng(SEED)
    matched = pairing[pairing["matched"]].copy()
    matched["ref_row"] = matched["ks_id_ref"].map(ref_id2row)
    matched["ours_row"] = matched["ks_id_ours"].map(ours_id2row)
    matched = matched.dropna(subset=["ref_row", "ours_row"]).copy()
    matched[["ref_row", "ours_row"]] = matched[["ref_row", "ours_row"]].astype(int)
    matched["jitter"] = rng.uniform(-JITTER_UM, JITTER_UM, size=len(matched))
    print(f"matched pairs in analyzer space: {len(matched)}")

    fig, ax = plt.subplots(figsize=(4.0, 7.2))

    # Background: faint probe channel grid via contact positions.
    try:
        probe = ref_a.get_probe()
        contacts = probe.contact_positions
        ax.scatter(contacts[:, 0], contacts[:, 1], s=0.6,
                   color="grey", alpha=0.18, marker=".", edgecolors="none",
                   zorder=0)
    except Exception as exc:
        print(f"Could not draw probe grid: {exc}")

    # Matched: ref open + ours filled + connector line.
    matched_ref_rows = set()
    matched_ours_rows = set()
    for _, rec in matched.iterrows():
        rr = rec["ref_row"]
        orw = rec["ours_row"]
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

    # Unmatched ref units (light blue fill, still visible).
    for i, (x, y) in enumerate(ref_locs):
        if i in matched_ref_rows:
            continue
        ax.scatter(x, y, s=ref_size[i],
                   facecolors=REF_ONLY_FILL, edgecolors=REF_EDGE,
                   linewidth=0.5, alpha=0.85, zorder=2)
    # Unmatched ours units (light orange fill).
    for i, (x, y) in enumerate(ours_locs):
        if i in matched_ours_rows:
            continue
        ax.scatter(x, y, s=ours_size[i],
                   color=OURS_ONLY_FILL, edgecolors="none",
                   alpha=0.85, zorder=2)

    ax.set_xlabel("x (µm)")
    ax.set_ylabel("depth (µm)")
    ax.set_title(
        f"VII.C1 matched-pair spatial distribution (SI monopolar)\n"
        f"filled=ours (n={len(ours_ids)})  open=ref (n={len(ref_ids)})  "
        f"matched={len(matched)}  line=pair",
        fontsize=6,
    )
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    # Size legend (firing rate).
    from matplotlib.lines import Line2D
    handles = []
    for fr_demo in (0.5, 5.0, 30.0):
        s_norm = np.log1p(fr_demo) / max(np.log1p(max(ref_fr.max(), ours_fr.max())), 1e-9)
        s = SIZE_MIN + (SIZE_MAX - SIZE_MIN) * np.clip(s_norm, 0, 1)
        handles.append(
            Line2D([0], [0], marker="o", color="none",
                   markerfacecolor="grey", markeredgecolor="none",
                   markersize=np.sqrt(s), label=f"{fr_demo:g} Hz")
        )
    handles.extend([
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
    ])
    ax.legend(handles=handles, loc="upper right",
              fontsize=5, labelspacing=0.5, handletextpad=0.3,
              borderpad=0.4, frameon=False)

    fig.tight_layout()
    out_png = OUT_DIR / "pair_spatial.png"
    out_svg = OUT_DIR / "pair_spatial.svg"
    fig.savefig(out_png)
    fig.savefig(out_svg)
    print(f"wrote {out_png}")
    print(f"wrote {out_svg}")


if __name__ == "__main__":
    main()
