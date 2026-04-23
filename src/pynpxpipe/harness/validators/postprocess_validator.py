"""Validator for the postprocess stage."""

from __future__ import annotations

from pathlib import Path

from pynpxpipe.harness.preflight import ValidationItem


class PostprocessValidator:
    def validate(self, output_dir: Path, probe_ids: list[str]) -> list[ValidationItem]:
        items: list[ValidationItem] = []
        for probe_id in probe_ids:
            templates_path = (
                output_dir
                / "06_postprocessed"
                / probe_id
                / "extensions"
                / "waveforms"
                / "templates.npy"
            )
            if templates_path.exists():
                items.append(
                    ValidationItem(
                        f"waveform_templates_exist_{probe_id}",
                        "pass",
                        f"Waveform templates computed: {templates_path}",
                    )
                )
            else:
                items.append(
                    ValidationItem(
                        f"waveform_templates_exist_{probe_id}",
                        "warn",
                        f"Waveform templates not found: {templates_path}",
                    )
                )
        return items
