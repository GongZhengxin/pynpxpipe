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

        # Support both checkpoint formats:
        #   - "probes": [{"probe_id": ..., "sample_rate": ...}]  (list of dicts)
        #   - "probe_ids": ["imec0", ...]  (list of strings, actual format)
        probes = cp.get("probes", [])
        probe_ids_list = cp.get("probe_ids", [])
        if probes:
            ids = [p["probe_id"] for p in probes]
        elif probe_ids_list:
            ids = probe_ids_list
        else:
            ids = []

        if ids:
            items.append(
                ValidationItem("probes_found", "pass", f"{len(ids)} probes: {', '.join(ids)}")
            )
        else:
            items.append(
                ValidationItem("probes_found", "fail", "No probes found in discover checkpoint")
            )

        # Sample rate check: only possible with the "probes" dict format
        if probes:
            missing_sr = [p["probe_id"] for p in probes if not p.get("sample_rate")]
            if missing_sr:
                items.append(
                    ValidationItem("meta_parsed", "warn", f"Missing sample_rate for: {missing_sr}")
                )
            else:
                sr_info = ", ".join(f"{p['probe_id']}={p.get('sample_rate')}Hz" for p in probes)
                items.append(ValidationItem("meta_parsed", "pass", f"Sample rates: {sr_info}"))
        else:
            n_probes = cp.get("n_probes", len(ids))
            items.append(
                ValidationItem(
                    "meta_parsed",
                    "pass",
                    f"Discover found {n_probes} probe(s) (no per-probe SR in checkpoint)",
                )
            )

        return items
