"""VI.1 + VI.2 plot: RDM pearson vs unit_count, 3 x trial_frac x 3 conditions.

Overlay filtered (SUA+MUA only) as dashed. Nature-style rcParams.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

DIAG = Path("diag")


def _nature_rc() -> None:
    plt.rcParams.update({
        "font.family": "Arial",
        "font.size": 7,
        "axes.linewidth": 0.6,
        "axes.labelsize": 7,
        "axes.titlesize": 7,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.labelsize": 6,
        "ytick.labelsize": 6,
        "legend.fontsize": 6,
        "legend.frameon": False,
        "lines.linewidth": 0.9,
        "lines.markersize": 3.2,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "savefig.dpi": 600,
        "savefig.bbox": "tight",
    })


def _summarize(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    agg = df.groupby(["trial_frac", "unit_count", "condition"]).agg(
        pearson_mean=("pearson", "mean"),
        pearson_std=("pearson", "std"),
    ).reset_index()
    # Use the actual fetched counts: -1 means "FULL"; replace with per-side max.
    return agg


def main() -> None:
    _nature_rc()
    df_all = _summarize(DIAG / "rdm_ablation.csv")
    df_flt = _summarize(DIAG / "rdm_ablation_filtered.csv")

    trial_fracs = [0.50, 0.75, 1.00]
    conditions = [
        ("ref_split", "tab:blue", "ref split-half"),
        ("ours_split", "tab:orange", "ours split-half"),
        ("cross", "tab:green", "cross-pipeline"),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.3), sharey=True)
    for ax, tfrac in zip(axes, trial_fracs):
        for cond, color, label in conditions:
            # all units
            sub = df_all[(df_all["trial_frac"] == tfrac) & (df_all["condition"] == cond)]
            sub = sub.sort_values("unit_count")
            x = sub["unit_count"].replace(-1, 300).values  # plot FULL near 300
            ax.errorbar(
                x, sub["pearson_mean"], yerr=sub["pearson_std"],
                color=color, marker="o", linestyle="-",
                label=f"{label} (all)", capsize=1.2, elinewidth=0.5,
            )
            # filtered
            sub2 = df_flt[(df_flt["trial_frac"] == tfrac) & (df_flt["condition"] == cond)]
            sub2 = sub2.sort_values("unit_count")
            x2 = sub2["unit_count"].replace(-1, 300).values
            ax.errorbar(
                x2, sub2["pearson_mean"], yerr=sub2["pearson_std"],
                color=color, marker="s", linestyle="--",
                label=f"{label} (SUA+MUA)", capsize=1.2, elinewidth=0.5,
            )

        ax.axhline(0, color="k", lw=0.4, alpha=0.4)
        ax.set_title(f"trial_frac = {tfrac:.2f}")
        ax.set_xlabel("unit count")
        ax.set_xscale("log")
        ax.set_xticks([33, 66, 100, 133, 170, 220, 300])
        ax.set_xticklabels(["33", "66", "100", "133", "170", "220", "FULL"])
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)

    axes[0].set_ylabel("lower-tri RDM Pearson")
    axes[0].set_ylim(-0.05, 0.90)
    axes[-1].legend(loc="lower right", ncol=1, handlelength=1.8)

    # Annotate V.3 / V.7 / V.8 reference points on the rightmost panel
    ax = axes[-1]
    ax.annotate(
        "V.3: 0.77\n(all units)", xy=(300, 0.77), xytext=(150, 0.82),
        fontsize=5, color="tab:green",
        arrowprops=dict(arrowstyle="->", color="tab:green", lw=0.4),
    )
    ax.annotate(
        "V.8.3 shared-133: 0.34\n(< random-133 cross = 0.45)",
        xy=(133, 0.45), xytext=(40, 0.55),
        fontsize=5, color="tab:red",
        arrowprops=dict(arrowstyle="->", color="tab:red", lw=0.4),
    )

    fig.suptitle(
        "VI.1/2 RDM stability vs unit count (3 trial_frac x 3 conditions; "
        "solid = all units, dashed = SUA+MUA only)",
        fontsize=7, y=1.02,
    )
    fig.tight_layout()

    out_png = DIAG / "rdm_vs_size.png"
    out_svg = DIAG / "rdm_vs_size.svg"
    fig.savefig(out_png)
    fig.savefig(out_svg)
    print(f"wrote {out_png}")
    print(f"wrote {out_svg}")


if __name__ == "__main__":
    main()
