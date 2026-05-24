#!/usr/bin/env python3
"""Export Phase 2.5 derivatives from an existing NWB file (per-probe).

Standalone CLI wrapper around :func:`pynpxpipe.io.derivatives.export_phase2_derivatives`.
Given a multi-probe NWB written by pynpxpipe, regenerate ``07_derivatives/``
without rerunning Phase 1 / Phase 3.

Outputs (under ``<out_root>/07_derivatives/``):
    TrialRecord_<session_id>.csv            — session-level (1 file)
    UnitProp_<session_id>_<probe_id>.csv    — per-probe (N files, N = #probes)
    TrialRaster_<session_id>_<probe_id>.h5  — per-probe (N files)

Usage:
    uv run python scripts/export_phase2_derivatives.py <nwb_path> [<out_root>]
        [--pre-onset-ms 50] [--post-onset-ms 300] [--bin-size-ms 1.0] [--n-jobs 1]

Notes:
    * ``out_root`` is the **parent** directory; the ``07_derivatives/`` folder
      is created beneath it. Defaults to ``nwb_path.parent``.
    * NWB ``units`` table is split by ``probe_id`` (fallback:
      ``electrode_group_name``). Spike times must already be aligned to a
      common time base (the synchronize stage's job).
    * Requires the pynpxpipe package on ``PYTHONPATH`` (``uv run`` handles this).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pynpxpipe.io.derivatives import export_phase2_derivatives


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export Phase 2.5 derivatives from an existing NWB file (per-probe).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("nwb_path", type=Path, help="Path to the input NWB file.")
    p.add_argument(
        "out_root",
        nargs="?",
        type=Path,
        default=None,
        help="Parent directory for 07_derivatives/. Defaults to NWB file's parent.",
    )
    p.add_argument("--pre-onset-ms", type=float, default=50.0)
    p.add_argument("--post-onset-ms", type=float, default=300.0)
    p.add_argument("--bin-size-ms", type=float, default=1.0)
    p.add_argument(
        "--n-jobs",
        type=int,
        default=1,
        help="joblib parallelism for raster (1 = serial, -1 = all cores).",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress tqdm progress bar in raster generation.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    out_root = args.out_root or args.nwb_path.parent
    derivatives_dir = out_root / "07_derivatives"
    try:
        export_phase2_derivatives(
            args.nwb_path,
            derivatives_dir,
            pre_onset_ms=args.pre_onset_ms,
            post_onset_ms=args.post_onset_ms,
            bin_size_ms=args.bin_size_ms,
            n_jobs=args.n_jobs,
            verbose=not args.quiet,
        )
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Derivatives written to {derivatives_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
