"""Validator for the preprocess stage."""

from __future__ import annotations

from pathlib import Path

from pynpxpipe.harness.preflight import ValidationItem


class PreprocessValidator:
    def validate(self, output_dir: Path, probe_ids: list[str]) -> list[ValidationItem]:
        items: list[ValidationItem] = []
        for probe_id in probe_ids:
            zarr_path = output_dir / "preprocessed" / probe_id
            if zarr_path.exists() and any(zarr_path.iterdir()):
                items.append(
                    ValidationItem(
                        f"zarr_output_exists_{probe_id}",
                        "pass",
                        f"Zarr directory non-empty: {zarr_path}",
                    )
                )
            else:
                items.append(
                    ValidationItem(
                        f"zarr_output_exists_{probe_id}",
                        "fail",
                        f"Zarr output missing or empty: {zarr_path}",
                    )
                )
        return items
