"""Resume-only runner for ablation experiments.

Usage:
    uv run python tools/run_ablation.py <output_dir> <pipeline_yaml> <sorting_yaml> <stage> [<stage> ...]

Loads an existing Session from `<output_dir>/session.json` (which must already
exist and point to <output_dir>), then invokes PipelineRunner on the given
stages. This bypasses the CLI's `SessionManager.create` path, which currently
requires experiment/probe_plan/date kwargs that the CLI does not collect.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from pynpxpipe.core.config import load_pipeline_config, load_sorting_config
from pynpxpipe.core.logging import setup_logging
from pynpxpipe.core.session import SessionManager
from pynpxpipe.pipelines.runner import PipelineRunner


def main() -> int:
    if len(sys.argv) < 5:
        print(__doc__, file=sys.stderr)
        return 2

    output_dir = Path(sys.argv[1])
    pipeline_yaml = Path(sys.argv[2])
    sorting_yaml = Path(sys.argv[3])
    stages = list(sys.argv[4:])

    session_json = output_dir / "session.json"
    if not session_json.exists():
        print(f"ERROR: missing {session_json}", file=sys.stderr)
        return 2

    session = SessionManager.load(output_dir)
    pipeline_cfg = load_pipeline_config(pipeline_yaml)
    sorting_cfg = load_sorting_config(sorting_yaml)

    setup_logging(session.log_path)
    # also mirror to stdout for console visibility
    stream = logging.StreamHandler(sys.stdout)
    stream.setLevel(logging.INFO)
    logging.getLogger().addHandler(stream)

    def progress(message: str, fraction: float) -> None:
        print(f"[{fraction*100:5.1f}%] {message}", flush=True)

    runner = PipelineRunner(session, pipeline_cfg, sorting_cfg, progress_callback=progress)
    runner.run(stages=stages)
    print(f"Pipeline complete. Output: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
