"""Validator for the curate stage."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from pynpxpipe.harness.preflight import ValidationItem


class CurateValidator:
    def validate(
        self,
        output_dir: Path,
        probe_ids: list[str],
        config_thresholds: dict[str, float],
    ) -> list[ValidationItem]:
        items: list[ValidationItem] = []
        for probe_id in probe_ids:
            cp_path = output_dir / "checkpoints" / f"curate_{probe_id}.json"
            metrics_path = output_dir / "curated" / probe_id / "quality_metrics.csv"

            if metrics_path.exists():
                items.append(
                    ValidationItem(f"quality_metrics_exists_{probe_id}", "pass", str(metrics_path))
                )
                with metrics_path.open(encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    cols = reader.fieldnames or []
                if "amplitude_cutoff" in cols:
                    items.append(
                        ValidationItem(
                            f"amplitude_cutoff_column_exists_{probe_id}",
                            "pass",
                            "amplitude_cutoff column present in quality_metrics.csv",
                        )
                    )
                else:
                    items.append(
                        ValidationItem(
                            f"amplitude_cutoff_column_exists_{probe_id}",
                            "fail",
                            "amplitude_cutoff column missing — curate.py may not compute it",
                        )
                    )
            else:
                items.append(
                    ValidationItem(
                        f"quality_metrics_exists_{probe_id}",
                        "fail",
                        f"quality_metrics.csv not found: {metrics_path}",
                    )
                )

            if cp_path.exists():
                cp = json.loads(cp_path.read_text(encoding="utf-8"))
                n_good = cp.get("n_units_after", cp.get("n_good", 0))
                n_total = cp.get("n_units_before", cp.get("n_total", 0))
                if n_good > 0:
                    items.append(
                        ValidationItem(
                            f"good_units_found_{probe_id}",
                            "pass",
                            f"{n_good}/{n_total} units passed thresholds",
                        )
                    )
                else:
                    items.append(
                        ValidationItem(
                            f"good_units_found_{probe_id}",
                            "fail",
                            f"0/{n_total} units passed thresholds — check threshold settings",
                        )
                    )

        return items
