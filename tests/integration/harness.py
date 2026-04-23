"""Integration harness: run pipeline stages against real data.

Usage:
    uv run python tests/integration/harness.py --status
    uv run python tests/integration/harness.py --stages discover preprocess
    uv run python tests/integration/harness.py --reset sort --stages sort --sort-seconds 120
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import sys
import traceback
from pathlib import Path

import spikeinterface.core as si
import spikeinterface.sorters as ss

from pynpxpipe.core.checkpoint import CheckpointManager
from pynpxpipe.core.config import load_pipeline_config, load_sorting_config, load_subject_config
from pynpxpipe.core.session import SessionManager
from pynpxpipe.pipelines.runner import PipelineRunner, STAGE_ORDER

# ── Constants ────────────────────────────────────────────────────────
DATA_DIR = Path(r"F:\#Datasets\demo_rawdata")
SUBJECT_YAML = Path(r"F:\tools\pynpxpipe\monkeys\MaoDan.yaml")
OUTPUT_DIR = DATA_DIR  # co-located, matching existing session.json

# ── Helpers ──────────────────────────────────────────────────────────


def print_progress(message: str, fraction: float) -> None:
    print(f"  [{fraction:>4.0%}] {message}", flush=True)


def print_status(runner: PipelineRunner) -> None:
    status = runner.get_status()
    print("\n  Stage Status")
    print("  " + "-" * 40)
    for stage in STAGE_ORDER:
        s = status.get(stage, "unknown")
        icon = {"completed": "+", "pending": "-", "failed": "!"}
        marker = icon.get(s, "~")
        print(f"  [{marker}] {stage:<16} {s}")
    print()


def run_sort_sliced(session, sorting_cfg, sort_seconds: float) -> None:
    """Run KS4 on a time-sliced recording (first N seconds only)."""
    probe = session.probes[0]
    probe_id = probe.probe_id
    zarr_path = session.output_dir / "01_preprocessed" / f"{probe_id}.zarr"

    print(f"  Loading preprocessed Zarr: {zarr_path}")
    recording = si.load(zarr_path)
    end_frame = int(sort_seconds * recording.get_sampling_frequency())
    total_frames = recording.get_num_frames()
    if end_frame > total_frames:
        end_frame = total_frames
    recording = recording.frame_slice(0, end_frame)
    duration = end_frame / recording.get_sampling_frequency()
    print(f"  Sliced to {duration:.1f}s ({end_frame} frames of {total_frames})")

    sorter_output = session.output_dir / "02_sorter_output_KS4" / probe_id
    params = dataclasses.asdict(sorting_cfg.sorter.params)
    print(f"  Running {sorting_cfg.sorter.name} ...")

    sorting = ss.run_sorter(
        sorting_cfg.sorter.name,
        recording,
        folder=sorter_output,
        remove_existing_folder=True,
        **params,
    )
    n_units = len(sorting.get_unit_ids())
    print(f"  Sort complete: {n_units} units found")

    save_path = session.output_dir / "02_sorted" / probe_id
    sorting.save(folder=save_path, overwrite=True)

    # Write checkpoint so downstream stages see sort as done
    cp = CheckpointManager(session.output_dir)
    cp.mark_complete(
        "sort",
        {
            "probe_id": probe_id,
            "mode": "local",
            "sorter_name": sorting_cfg.sorter.name,
            "n_units": n_units,
            "output_path": str(save_path),
        },
        probe_id=probe_id,
    )
    cp.mark_complete(
        "sort",
        {
            "probe_ids": [probe_id],
            "mode": "local",
        },
    )

    del sorting, recording
    gc.collect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Integration harness for pynpxpipe")
    parser.add_argument("--stages", nargs="+", choices=STAGE_ORDER, help="Stages to run")
    parser.add_argument(
        "--reset", nargs="+", choices=STAGE_ORDER, help="Clear checkpoints before run"
    )
    parser.add_argument(
        "--sort-seconds", type=float, default=None, help="Time-slice sort (seconds)"
    )
    parser.add_argument("--status", action="store_true", help="Print stage status and exit")
    args = parser.parse_args()

    # 1. Load configs
    subject = load_subject_config(SUBJECT_YAML)
    pipeline_cfg = load_pipeline_config(None)
    sorting_cfg = load_sorting_config(None)

    # 2. Load or create session
    session_json = OUTPUT_DIR / "session.json"
    if session_json.exists():
        session = SessionManager.load(OUTPUT_DIR)
        print(f"  Loaded session: {len(session.probes)} probe(s)")
    else:
        session = SessionManager.from_data_dir(
            DATA_DIR,
            subject,
            OUTPUT_DIR,
            experiment="nsd1w",
            probe_plan={"imec0": "V4"},
            date="240101",
        )
        print(f"  Created new session")

    # 3. Build runner
    runner = PipelineRunner(session, pipeline_cfg, sorting_cfg, progress_callback=print_progress)

    # 4. Status only
    if args.status:
        print_status(runner)
        return

    # 5. Reset checkpoints
    if args.reset:
        cp = CheckpointManager(OUTPUT_DIR)
        for stage_name in args.reset:
            cp.clear(stage_name)
            for probe in session.probes:
                cp.clear(stage_name, probe.probe_id)
            print(f"  Reset checkpoint: {stage_name}")

    # 6. Determine stages to run
    stages = args.stages or list(STAGE_ORDER)

    # 7. Run each stage with error capture
    for stage_name in [s for s in STAGE_ORDER if s in stages]:
        print(f"\n{'=' * 60}")
        print(f"  STAGE: {stage_name}")
        print(f"{'=' * 60}")

        try:
            if stage_name == "sort" and args.sort_seconds:
                run_sort_sliced(session, sorting_cfg, args.sort_seconds)
            else:
                runner.run_stage(stage_name)
            print(f"  === STAGE OK: {stage_name} ===")
        except Exception:
            print(f"\n  === STAGE FAILED: {stage_name} ===")
            traceback.print_exc()
            print(f"\n  Stopping pipeline at failed stage: {stage_name}")
            sys.exit(1)

    print(f"\n  All requested stages completed successfully.")
    print_status(runner)


if __name__ == "__main__":
    main()
