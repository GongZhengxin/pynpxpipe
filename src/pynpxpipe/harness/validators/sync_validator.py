"""Validator for the synchronize stage."""

from __future__ import annotations

import json
from pathlib import Path

from pynpxpipe.harness.preflight import ValidationItem

_MAX_RESIDUAL_MS: float = 0.5


class SyncValidator:
    def validate(self, output_dir: Path) -> list[ValidationItem]:
        items: list[ValidationItem] = []
        cp_path = output_dir / "checkpoints" / "synchronize.json"
        if not cp_path.exists():
            items.append(ValidationItem("sync_checkpoint", "fail", "synchronize.json not found"))
            return items

        cp = json.loads(cp_path.read_text(encoding="utf-8"))
        residual_ms = cp.get("max_residual_ms")
        if residual_ms is not None:
            if residual_ms <= _MAX_RESIDUAL_MS:
                items.append(
                    ValidationItem(
                        "alignment_residual",
                        "pass",
                        f"Max alignment residual {residual_ms:.4f}ms <= {_MAX_RESIDUAL_MS}ms",
                    )
                )
            else:
                items.append(
                    ValidationItem(
                        "alignment_residual",
                        "fail",
                        f"Alignment residual {residual_ms:.4f}ms > {_MAX_RESIDUAL_MS}ms threshold",
                    )
                )

        trial_count = cp.get("trial_count")
        bhv2_count = cp.get("bhv2_trial_count")
        if trial_count is not None and bhv2_count is not None:
            if trial_count == bhv2_count:
                items.append(
                    ValidationItem(
                        "trial_count_match", "pass", f"Trial count matches BHV2: {trial_count}"
                    )
                )
            else:
                items.append(
                    ValidationItem(
                        "trial_count_match",
                        "warn",
                        f"Trial count mismatch: pipeline={trial_count}, BHV2={bhv2_count}",
                    )
                )

        return items
