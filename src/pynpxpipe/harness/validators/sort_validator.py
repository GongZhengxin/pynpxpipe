"""Validator for the sort stage."""

from __future__ import annotations

import json
from pathlib import Path

from pynpxpipe.harness.preflight import ValidationItem


class SortValidator:
    def validate(self, output_dir: Path, probe_ids: list[str]) -> list[ValidationItem]:
        items: list[ValidationItem] = []
        for probe_id in probe_ids:
            cp_path = output_dir / "checkpoints" / f"sort_{probe_id}.json"
            sorting_dir = output_dir / "sorting" / probe_id

            if sorting_dir.exists() and any(sorting_dir.iterdir()):
                items.append(
                    ValidationItem(
                        f"sorting_output_exists_{probe_id}",
                        "pass",
                        f"Sorting dir exists: {sorting_dir}",
                    )
                )
            else:
                items.append(
                    ValidationItem(
                        f"sorting_output_exists_{probe_id}",
                        "fail",
                        f"Sorting output missing or empty: {sorting_dir}",
                    )
                )

            if cp_path.exists():
                cp = json.loads(cp_path.read_text(encoding="utf-8"))
                n_units = cp.get("n_units", -1)
                if n_units > 0:
                    items.append(
                        ValidationItem(
                            f"units_found_{probe_id}", "pass", f"{n_units} units for {probe_id}"
                        )
                    )
                elif n_units == 0:
                    items.append(
                        ValidationItem(
                            f"units_found_{probe_id}",
                            "warn",
                            f"0 units after sorting {probe_id} — check sorter params or recording quality",
                        )
                    )
            else:
                items.append(
                    ValidationItem(
                        f"units_found_{probe_id}", "warn", f"No sort checkpoint for {probe_id}"
                    )
                )

        return items
