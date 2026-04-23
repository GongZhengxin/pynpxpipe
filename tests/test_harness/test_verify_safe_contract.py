"""Verify-safe-to-delete contract harness (E2.3).

End-to-end check of the three branches of the ``pynpxpipe
verify-safe-to-delete`` CLI:

- Branch A — happy path: export.json carries ``raw_data_verified_at`` and the
  NWB opens cleanly → exit 0 + "Safe to delete" in stdout.
- Branch B — missing verified_at: delete the field, re-run → exit != 0.
- Branch C — corrupt NWB: truncate the file to 10 bytes → exit != 0.

We use click's ``CliRunner.invoke`` (not subprocess) to keep wall time <1s;
both are acceptable per the task spec.

Runtime budget: <3s total.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pynwb
from click.testing import CliRunner

from pynpxpipe.cli.main import cli


def _write_minimal_nwb(nwb_path: Path) -> None:
    """Write the smallest valid NWB file that NWBHDF5IO can re-open."""
    nwb_path.parent.mkdir(parents=True, exist_ok=True)
    nwbfile = pynwb.NWBFile(
        session_description="verify-safe harness",
        identifier=str(uuid.uuid4()),
        session_start_time=datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC),
    )
    with pynwb.NWBHDF5IO(str(nwb_path), "w") as io:
        io.write(nwbfile)


def _build_session(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Stand up (output_dir, nwb_path, export_checkpoint_path) on disk."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "checkpoints").mkdir()

    raw_dir = tmp_path / "raw_g0"
    (raw_dir / "imec0").mkdir(parents=True)
    ap_bin = raw_dir / "imec0" / "imec0.ap.bin"
    ap_meta = raw_dir / "imec0" / "imec0.ap.meta"
    ap_bin.write_bytes(b"\x00" * 16)
    ap_meta.write_text("typeThis=imec\n", encoding="utf-8")
    (raw_dir / "run.nidq.bin").write_bytes(b"\x00" * 16)
    (raw_dir / "run.nidq.meta").write_text("typeThis=nidq\n", encoding="utf-8")

    (output_dir / "session.json").write_text(
        json.dumps(
            {
                "session_dir": str(raw_dir),
                "output_dir": str(output_dir),
                "bhv_file": str(tmp_path / "task.bhv2"),
                "subject": {
                    "subject_id": "TestMon",
                    "description": "harness",
                    "species": "Macaca mulatta",
                    "sex": "M",
                    "age": "P3Y",
                    "weight": "10kg",
                },
                "session_id": {
                    "date": "260417",
                    "subject": "TestMon",
                    "experiment": "nsd1w",
                    "region": "V4",
                },
                "probe_plan": {"imec0": "V4"},
                "probes": [
                    {
                        "probe_id": "imec0",
                        "ap_bin": str(ap_bin),
                        "ap_meta": str(ap_meta),
                        "lf_bin": None,
                        "lf_meta": None,
                        "sample_rate": 30000.0,
                        "n_channels": 384,
                        "probe_type": "NP1010",
                        "serial_number": "SN0",
                        "target_area": "V4",
                    }
                ],
                "checkpoint": {},
            }
        ),
        encoding="utf-8",
    )

    nwb_path = output_dir / "260417_TestMon_nsd1w_V4.nwb"
    _write_minimal_nwb(nwb_path)

    cp_path = output_dir / "checkpoints" / "export.json"
    cp_path.write_text(
        json.dumps(
            {
                "stage": "export",
                "status": "completed",
                "nwb_path": str(nwb_path),
                "raw_data_verified_at": "2026-04-17T10:00:00+00:00",
                "verify_policy": "full",
            }
        ),
        encoding="utf-8",
    )
    return output_dir, nwb_path, cp_path


class TestVerifySafeContract:
    """End-to-end contract: three branches of pynpxpipe verify-safe-to-delete."""

    def test_three_branches(self, tmp_path: Path) -> None:
        t0 = time.perf_counter()
        runner = CliRunner()
        output_dir, nwb_path, cp_path = _build_session(tmp_path)

        # ── Branch A: all prerequisites present → exit 0 + "Safe to delete"
        result_a = runner.invoke(cli, ["verify-safe-to-delete", str(output_dir)])
        assert result_a.exit_code == 0, result_a.output
        assert "Safe to delete" in result_a.output

        # ── Branch B: strip raw_data_verified_at, re-run → non-zero
        cp_data = json.loads(cp_path.read_text(encoding="utf-8"))
        cp_data.pop("raw_data_verified_at", None)
        cp_path.write_text(json.dumps(cp_data), encoding="utf-8")
        result_b = runner.invoke(cli, ["verify-safe-to-delete", str(output_dir)])
        assert result_b.exit_code != 0

        # Restore verified_at before the NWB-corruption branch so we isolate
        # the failure mode under test.
        cp_data["raw_data_verified_at"] = "2026-04-17T10:00:00+00:00"
        cp_path.write_text(json.dumps(cp_data), encoding="utf-8")

        # ── Branch C: truncate NWB to 10 bytes → NWBHDF5IO fails → non-zero
        nwb_path.write_bytes(b"\x00" * 10)
        result_c = runner.invoke(cli, ["verify-safe-to-delete", str(output_dir)])
        assert result_c.exit_code != 0

        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, f"harness ran in {elapsed:.2f}s — over 3s budget"
