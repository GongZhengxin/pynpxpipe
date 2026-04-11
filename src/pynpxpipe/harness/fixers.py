"""Applies GREEN and YELLOW auto-fixes; produces audit records."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


class Fixer:
    """Applies safe fixes and records them for the audit log."""

    def fix_torch_device(self, sorting_yaml: Path, current: str, target: str) -> dict[str, Any]:
        """Update torch_device in sorting.yaml. Returns an audit record."""
        content = yaml.safe_load(sorting_yaml.read_text(encoding="utf-8"))
        content["sorter"]["params"]["torch_device"] = target
        sorting_yaml.write_text(yaml.dump(content, default_flow_style=False), encoding="utf-8")
        return {
            "tier": "GREEN",
            "target": "config",
            "description": f"Set torch_device from '{current}' to '{target}' (GPU availability mismatch)",
            "file": str(sorting_yaml),
            "before": current,
            "after": target,
            "reversible": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def fix_batch_size(self, sorting_yaml: Path, current: int, target: int) -> dict[str, Any]:
        """Update batch_size in sorting.yaml. Returns an audit record."""
        content = yaml.safe_load(sorting_yaml.read_text(encoding="utf-8"))
        content["sorter"]["params"]["batch_size"] = target
        sorting_yaml.write_text(yaml.dump(content, default_flow_style=False), encoding="utf-8")
        return {
            "tier": "GREEN",
            "target": "config",
            "description": f"Reduced batch_size from {current} to {target} (estimated VRAM OOM)",
            "file": str(sorting_yaml),
            "before": current,
            "after": target,
            "reversible": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def fix_disable_motion_correction(self, pipeline_yaml: Path) -> dict[str, Any]:
        """Disable motion correction when nblocks > 0 (mutual exclusivity fix)."""
        content = yaml.safe_load(pipeline_yaml.read_text(encoding="utf-8"))
        preprocess = content.setdefault("preprocess", {})
        mc = preprocess.setdefault("motion_correction", {})
        before = mc.get("method", None)
        mc["method"] = None
        pipeline_yaml.write_text(yaml.dump(content, default_flow_style=False), encoding="utf-8")
        return {
            "tier": "GREEN",
            "target": "config",
            "description": "Disabled motion correction (mutually exclusive with KS4 nblocks > 0)",
            "file": str(pipeline_yaml),
            "before": f"motion_correction.method: {before!r}",
            "after": "motion_correction.method: null",
            "reversible": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def record_yellow_fix(
        self,
        description: str,
        file_path: Path,
        diff: str,
        rationale: str,
    ) -> dict[str, Any]:
        """Record a YELLOW source fix that was applied externally. Returns audit record."""
        return {
            "tier": "YELLOW",
            "target": "source",
            "description": description,
            "file": str(file_path),
            "diff": diff,
            "rationale": rationale,
            "reversible": True,
            "timestamp": datetime.now(UTC).isoformat(),
        }
