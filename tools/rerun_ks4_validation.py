"""tools/rerun_ks4_validation.py — IV.10: rerun KS4 on existing preprocessed Zarr.

Validates the pinned-KS4-params fix (docs/todo.md §IV.8) by re-running Kilosort4
on an already-preprocessed Zarr without touching the main pipeline outputs.

Does NOT overwrite 04_sorting/ or 02_sorted/. All artifacts land under
{output_dir}/diag/ks4_rerun_{timestamp}/ .

Usage:
    uv run python tools/rerun_ks4_validation.py \
        --session-dir "F:/#Datasets/demo_rawdata/NPX_MD241029_exp_g0" \
        --output-dir "F:/#Datasets/demo_rawdata/processed_pynpxpipe" \
        --probe-id imec0 \
        --target 387

Exit code 0 on successful sort (regardless of unit count match).
Exit code 1 on setup failure (missing Zarr, missing GPU, etc.).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rerun KS4 with pinned params for IV.10 validation.")
    parser.add_argument("--session-dir", required=True, type=Path, help="SpikeGLX recording root (for ResourceDetector).")
    parser.add_argument("--output-dir", required=True, type=Path, help="Pynpxpipe output dir (contains 01_preprocessed/).")
    parser.add_argument("--probe-id", default="imec0", help="Probe id (default imec0).")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config" / "sorting.yaml",
        help="Path to sorting.yaml (default: repo config/sorting.yaml).",
    )
    parser.add_argument("--target", type=int, default=387, help="Reference unit count (for delta report).")
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    output_dir = args.output_dir.resolve()
    zarr_path = output_dir / "01_preprocessed" / f"{args.probe_id}.zarr"
    if not zarr_path.exists():
        print(f"ERROR: Zarr not found at {zarr_path}", file=sys.stderr)
        return 1
    if not args.config.exists():
        print(f"ERROR: sorting.yaml not found at {args.config}", file=sys.stderr)
        return 1

    import spikeinterface.core as si
    import spikeinterface.sorters as ss

    from pynpxpipe.core.config import load_sorting_config
    from pynpxpipe.core.resources import ResourceDetector
    from pynpxpipe.core.torch_env import resolve_device

    sorting_config = load_sorting_config(args.config)

    # Resolve batch_size: "auto" → ResourceDetector recommendation (mirrors runner.py)
    detector = ResourceDetector(session_dir, output_dir)
    profile = detector.detect()
    if sorting_config.sorter.params.batch_size == "auto":
        rec = detector.recommend(profile, probes=None)
        sorting_config.sorter.params.batch_size = rec.sorting_batch_size

    params = dataclasses.asdict(sorting_config.sorter.params)

    # Resolve torch_device: "auto"/"cuda" → actual device string
    requested_device = params.get("torch_device", "auto")
    if requested_device in {"auto", "cuda"}:
        params["torch_device"] = resolve_device(
            requested_device,
            has_physical_gpu=profile.primary_gpu is not None,
        )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    diag_root = output_dir / "diag" / f"ks4_rerun_{timestamp}"
    sorter_output = diag_root / "sorter_output"
    diag_root.mkdir(parents=True, exist_ok=True)

    recording = si.load(zarr_path)
    n_ch = recording.get_num_channels()
    dur_s = recording.get_duration()

    config_snapshot = {
        "script": "tools/rerun_ks4_validation.py",
        "timestamp": timestamp,
        "session_dir": str(session_dir),
        "output_dir": str(output_dir),
        "zarr_input": str(zarr_path),
        "config_path": str(args.config),
        "sorter_output": str(sorter_output),
        "recording": {
            "n_channels": n_ch,
            "duration_s": round(dur_s, 2),
            "sample_rate_hz": float(recording.get_sampling_frequency()),
        },
        "sorter_name": sorting_config.sorter.name,
        "ks_params_resolved": params,
        "target_units": args.target,
    }
    (diag_root / "pre_run_config.json").write_text(
        json.dumps(config_snapshot, indent=2), encoding="utf-8"
    )

    print("=" * 70)
    print("IV.10 KS4 validation rerun")
    print("=" * 70)
    print(f"  Input Zarr      : {zarr_path}")
    print(f"  Recording       : {n_ch} ch, {dur_s/60:.1f} min")
    print(f"  Sorter          : {sorting_config.sorter.name}")
    print(f"  Resolved params : {params}")
    print(f"  Output          : {diag_root}")
    print(f"  Reference target: {args.target} units")
    print("=" * 70)
    print()

    t0 = time.time()
    try:
        sorting = ss.run_sorter(
            sorting_config.sorter.name,
            recording,
            folder=sorter_output,
            remove_existing_folder=True,
            verbose=True,
            **params,
        )
    except Exception as exc:
        elapsed = time.time() - t0
        err_summary = {
            **config_snapshot,
            "status": "FAILED",
            "duration_s": round(elapsed, 1),
            "error": f"{type(exc).__name__}: {exc}",
        }
        (diag_root / "summary.json").write_text(
            json.dumps(err_summary, indent=2), encoding="utf-8"
        )
        print(f"\nFAILED after {elapsed/60:.1f} min: {exc}", file=sys.stderr)
        raise

    elapsed = time.time() - t0
    n_units = len(sorting.unit_ids)
    delta_pct = round(100 * (n_units - args.target) / args.target, 1) if args.target else None

    summary = {
        **config_snapshot,
        "status": "OK",
        "duration_s": round(elapsed, 1),
        "n_units": n_units,
        "delta_vs_target_pct": delta_pct,
    }
    (diag_root / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    saved_sorting = diag_root / "sorting"
    sorting.save(folder=saved_sorting, overwrite=True)

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Duration        : {elapsed/60:.1f} min")
    print(f"  Units found     : {n_units}")
    print(f"  Reference target: {args.target}")
    if delta_pct is not None:
        sign = "+" if delta_pct >= 0 else ""
        print(f"  Delta           : {sign}{delta_pct}%")
    print(f"  Sorting saved   : {saved_sorting}")
    print(f"  Summary JSON    : {diag_root / 'summary.json'}")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
