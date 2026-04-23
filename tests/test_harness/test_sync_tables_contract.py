"""Contract: sync_tables scratch block survives NWB roundtrip and carries
enough info to reproduce imec↔nidq alignment.

End-to-end validation that the JSON payload written by E1.3's
``NWBWriter.add_sync_tables`` survives writing to disk via NWBHDF5IO and
reopening, with all three sections (imec_nidq fits, photodiode-calibrated
onsets, event-code triples) recoverable by a downstream consumer who has
only the .nwb file — no SpikeGLX bins, no sync/ directory.

Runtime budget: <3s. Pure numpy + tmp_path.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pynwb

from pynpxpipe.core.session import (
    ProbeInfo,
    SessionManager,
    SubjectConfig,
)
from pynpxpipe.io.nwb_writer import NWBWriter


def _subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="MaoDan",
        description="sync_tables contract harness subject",
        species="Macaca mulatta",
        sex="M",
        age="P4Y",
        weight="12kg",
    )


def _write_ap_meta(meta_path: Path) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        "typeThis=imec\nfileCreateTime=2024-01-15T14:30:00\nimSampRate=30000.0\n",
        encoding="utf-8",
    )


def _make_probe(probe_id: str, tmp_path: Path, target_area: str) -> ProbeInfo:
    meta = tmp_path / f"{probe_id}.ap.meta"
    _write_ap_meta(meta)
    positions = [(float(i * 16), float(i * 20)) for i in range(4)]
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=meta.parent / f"{probe_id}.ap.bin",
        ap_meta=meta,
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=4,
        serial_number=f"SN_{probe_id}",
        probe_type="NP1010",
        channel_positions=positions,
        target_area=target_area,
    )


class TestSyncTablesContract:
    """Disk-roundtrip contract for the E1.3 sync_tables scratch block."""

    def test_roundtrip_reconstructs_imec_nidq(self, tmp_path: Path) -> None:
        """Write → close → reopen → parse JSON → assert A..E hold."""
        t0 = time.perf_counter()

        # 1. Build a minimal real Session — single probe imec0.
        session_dir = tmp_path / "Run_g0"
        session_dir.mkdir()
        bhv_file = tmp_path / "task.bhv2"
        bhv_file.write_bytes(b"\x00" * 16)

        session = SessionManager.create(
            session_dir,
            bhv_file,
            _subject(),
            tmp_path / "out",
            experiment="nsd1w",
            probe_plan={"imec0": "MSB"},
            date="240115",
        )
        probe0 = _make_probe("imec0", tmp_path / "probe0", "MSB")
        session.probes = [probe0]

        # 2. Write the per-probe IMEC↔NIDQ linear fit JSON.
        sync_dir = tmp_path / "04_sync"
        sync_dir.mkdir()
        fit = {"a": 1.00001, "b": -0.5, "rmse": 1e-5, "n_pulses": 100}
        (sync_dir / "imec0_imec_nidq.json").write_text(json.dumps(fit), encoding="utf-8")

        # 3. Build a tiny behavior_events DataFrame (3 trials) with PD + EC
        #    onsets and the canonical stim_onset columns.
        n_trials = 3
        ec = np.array([12.320, 13.475, 14.600])
        pd_onsets = np.array([12.345, 13.500, 14.625])
        events = pd.DataFrame(
            {
                "trial_id": list(range(n_trials)),
                "onset_nidq_s": [10.0, 11.0, 12.0],
                "stim_onset_nidq_s": ec,
                "stim_onset_imec_s": [
                    json.dumps({"imec0": float(t - fit["b"]) / fit["a"]}) for t in ec
                ],
                "condition_id": [1] * n_trials,
                "trial_valid": [True] * n_trials,
                "onset_time_ms": [150.0] * n_trials,
                "offset_time_ms": [150.0] * n_trials,
                "pd_onset_nidq_s": pd_onsets,
                "ec_onset_nidq_s": ec,
            }
        )

        # 4. Build NWB: create → add_trials → add_sync_tables → write.
        out_path = tmp_path / f"{session.session_id.canonical()}.nwb"
        writer = NWBWriter(session, out_path)
        writer.create_file()
        writer.add_trials(events)
        summary = writer.add_sync_tables(
            writer._nwbfile, sync_dir, behavior_events=events
        )
        assert summary["idempotent_skipped"] is False
        writer.write()

        assert out_path.exists()

        # 5. Re-open from disk — fresh HDF5 handle, no shared Python objects.
        with pynwb.NWBHDF5IO(str(out_path), mode="r") as io:
            nwbfile = io.read()
            raw = nwbfile.scratch["sync_tables"].data
            # ScratchData.data may expose as bytes/str — handle both.
            if hasattr(raw, "__getitem__") and not isinstance(raw, (str, bytes)):
                try:
                    raw = raw[()]
                except Exception:
                    raw = raw[:]
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            blob = json.loads(raw)

        # --- Assertion A: imec_nidq.imec0.a preserved ---
        assert np.isclose(blob["imec_nidq"]["imec0"]["a"], 1.00001)

        # --- Assertion B: imec_nidq.imec0.b preserved ---
        assert np.isclose(blob["imec_nidq"]["imec0"]["b"], -0.5)

        # --- Assertion C: photodiode list has 3 entries with correct latency ---
        pd_rows = blob["photodiode"]
        assert len(pd_rows) == n_trials
        for i, row in enumerate(pd_rows):
            expected_latency = float(ec[i]) - float(pd_onsets[i])
            assert np.isclose(row["latency_s"], expected_latency), (
                f"latency mismatch at trial {i}: got {row['latency_s']}, "
                f"expected {expected_latency}"
            )

        # --- Assertion D: event_codes list preserves stim_onset_nidq_s ---
        ec_rows = blob["event_codes"]
        assert len(ec_rows) == n_trials
        for i, row in enumerate(ec_rows):
            assert np.isclose(row["stim_onset_nidq_s"], float(ec[i]))

        # --- Assertion E: wall time under budget ---
        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, f"harness ran in {elapsed:.2f}s — over budget"
