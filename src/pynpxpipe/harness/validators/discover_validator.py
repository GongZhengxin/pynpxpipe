"""Validator for the discover stage."""

from __future__ import annotations

import json
from pathlib import Path

from pynpxpipe.harness.preflight import ValidationItem


class DiscoverValidator:
    def validate(self, output_dir: Path, session_probes: list[str]) -> list[ValidationItem]:
        items: list[ValidationItem] = []
        cp_path = output_dir / "checkpoints" / "discover.json"
        if not cp_path.exists():
            items.append(ValidationItem("discover_checkpoint", "fail", "discover.json not found"))
            return items

        cp = json.loads(cp_path.read_text(encoding="utf-8"))
        probes = cp.get("probes", [])
        if probes:
            ids = [p["probe_id"] for p in probes]
            items.append(
                ValidationItem("probes_found", "pass", f"{len(probes)} probes: {', '.join(ids)}")
            )
        else:
            items.append(
                ValidationItem("probes_found", "fail", "No probes found in discover checkpoint")
            )

        missing_sr = [p["probe_id"] for p in probes if not p.get("sample_rate")]
        if missing_sr:
            items.append(
                ValidationItem("meta_parsed", "warn", f"Missing sample_rate for: {missing_sr}")
            )
        else:
            sr_info = (
                ", ".join(f"{p['probe_id']}={p.get('sample_rate')}Hz" for p in probes)
                if probes
                else "no probes"
            )
            items.append(ValidationItem("meta_parsed", "pass", f"Sample rates: {sr_info}"))

        return items
