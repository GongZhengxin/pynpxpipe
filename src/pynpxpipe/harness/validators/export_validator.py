"""Validator for the export stage."""

from __future__ import annotations

import json
from pathlib import Path

from pynpxpipe.harness.preflight import ValidationItem


class ExportValidator:
    def validate(self, output_dir: Path) -> list[ValidationItem]:
        cp_path = output_dir / "checkpoints" / "export.json"
        if not cp_path.exists():
            return [ValidationItem("export_checkpoint", "fail", "export.json not found")]

        cp = json.loads(cp_path.read_text(encoding="utf-8"))
        nwb_path = Path(cp.get("nwb_path", "")) if cp.get("nwb_path") else None
        if nwb_path and nwb_path.exists() and nwb_path.stat().st_size > 0:
            return [ValidationItem("nwb_file_exists", "pass", f"NWB file exists: {nwb_path}")]
        return [
            ValidationItem(
                "nwb_file_exists",
                "fail",
                f"NWB file missing or empty: {cp.get('nwb_path', '')}",
            )
        ]
