"""Read checkpoint status without preparing a run or touching its outputs."""

from __future__ import annotations

import json
from pathlib import Path

from pynpxpipe.pipelines.constants import PER_PROBE_STAGES, STAGE_ORDER


def _status(path: Path) -> str | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get("status", "pending") if isinstance(data, dict) else None


def read_pipeline_status(output_dir: Path, probe_ids: list[str]) -> dict[str, str]:
    """Summarize stage and per-probe checkpoints from a saved output directory."""
    checkpoints = output_dir / "checkpoints"
    result = {}
    for stage in STAGE_ORDER:
        status = _status(checkpoints / f"{stage}.json")
        if status is None and stage in PER_PROBE_STAGES and probe_ids:
            probes = [_status(checkpoints / f"{stage}_{pid}.json") for pid in probe_ids]
            count = probes.count("completed")
            if "failed" in probes:
                status = "failed"
            elif count == len(probes):
                status = "completed"
            elif count:
                status = f"partial ({count}/{len(probes)} probes)"
        result[stage] = status or "pending"
    return result
