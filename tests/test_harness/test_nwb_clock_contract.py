"""E1.1 NWB clock contract harness.

End-to-end validation that `units.spike_times` and `trials.start_time` share
one clock after the E1.1 fix. Prior to this fix `add_trials` anchored to
NIDQ seconds while `add_probe_data` wrote IMEC seconds into
`units.spike_times` — downstream analysis code silently mis-aligned spikes
and stimuli. This harness wires a tiny synthetic 2-probe session through
the full writer path and reopens the NWB from disk to assert the contract.

Invariants asserted:
    A. `units.spike_times[0]` equals the mocked analyzer's IMEC-seconds
       spike train.
    B. `trials.start_time[0]` equals the imec0 value parsed from the
       behavior_events DataFrame's `stim_onset_imec_s` JSON.
    C. `trials.start_time[0]` is NOT equal to the NIDQ diagnostic column
       — confirming the two timebases are distinguishable and we wrote the
       IMEC one.

Runtime budget: <3s. Everything is in-memory numpy + a tmp_path NWB.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pynwb
import pytest

from pynpxpipe.core.session import ProbeInfo, SessionManager, SubjectConfig
from pynpxpipe.io.nwb_writer import NWBWriter

# ── Synthetic-data knobs ────────────────────────────────────────────────

_N_SAMPLES = 82
_N_CHANNELS = 4
_SPIKE_TIMES_IMEC = np.array([1.0, 1.5, 2.0], dtype=np.float64)
_STIM_ONSET_IMEC0 = 2.5
_STIM_ONSET_IMEC1 = 2.51
_STIM_ONSET_NIDQ = 5.0  # deliberately NOT equal to either IMEC value


def _subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="MaoDan",
        description="E1.1 harness subject",
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
    positions = [(float(i * 16), float(i * 20)) for i in range(_N_CHANNELS)]
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=meta.parent / f"{probe_id}.ap.bin",
        ap_meta=meta,
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=_N_CHANNELS,
        serial_number=f"SN_{probe_id}",
        probe_type="NP1010",
        channel_positions=positions,
        target_area=target_area,
    )


def _make_analyzer(n_units: int = 1) -> MagicMock:
    """Mock SortingAnalyzer: 1 unit with known IMEC-second spike times."""
    unit_ids = [f"u{i}" for i in range(n_units)]

    sorting = MagicMock()
    sorting.get_unit_ids.return_value = unit_ids
    # Every unit gets the same known spike train — deliberate: the assertion
    # only cares about unit 0.
    sorting.get_unit_spike_train.return_value = _SPIKE_TIMES_IMEC
    sorting.get_property.return_value = None  # no unittype_string override

    templates_data = np.zeros((n_units, _N_SAMPLES, _N_CHANNELS), dtype=np.float32)
    templates = MagicMock()
    templates.get_templates.return_value = templates_data

    locs = MagicMock()
    locs.get_data.return_value = np.zeros((n_units, 3), dtype=np.float64)

    available = {"waveforms", "templates", "unit_locations"}

    def has_ext(name: str) -> bool:
        return name in available

    def get_ext(name: str) -> MagicMock:
        return {"waveforms": templates, "templates": templates, "unit_locations": locs}[name]

    analyzer = MagicMock()
    analyzer.sorting = sorting
    analyzer.has_extension.side_effect = has_ext
    analyzer.get_extension.side_effect = get_ext
    return analyzer


def _make_behavior_df() -> pd.DataFrame:
    """Single trial with distinct NIDQ and per-probe IMEC onset values."""
    return pd.DataFrame(
        {
            "trial_id": [0],
            "onset_nidq_s": [0.0],
            "stim_onset_nidq_s": [_STIM_ONSET_NIDQ],
            "stim_onset_imec_s": [
                json.dumps({"imec0": _STIM_ONSET_IMEC0, "imec1": _STIM_ONSET_IMEC1})
            ],
            "condition_id": [1],
            "trial_valid": [True],
            "onset_time_ms": [150.0],
            "offset_time_ms": [150.0],
        }
    )


class TestNWBClockContract:
    """End-to-end: spike_times and trials.start_time share the IMEC clock."""

    def test_units_and_trials_share_imec_clock(self, tmp_path: Path) -> None:
        """Full-pipeline assertion: A + B + C from the module docstring."""
        # 1. Build a canonical session through the public factory so session_id
        #    goes through the same code path as production.
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
            probe_plan={"imec0": "MSB", "imec1": "V4"},
            date="240115",
        )
        probe0 = _make_probe("imec0", tmp_path / "probe0", "MSB")
        probe1 = _make_probe("imec1", tmp_path / "probe1", "V4")
        session.probes = [probe0, probe1]

        # 2. Write the NWB: create → per-probe add_probe_data → add_trials → write.
        out_path = tmp_path / f"{session.session_id.canonical()}.nwb"
        writer = NWBWriter(session, out_path)
        writer.create_file()
        writer.add_probe_data(probe0, _make_analyzer(n_units=1))
        writer.add_probe_data(probe1, _make_analyzer(n_units=1))
        writer.add_trials(_make_behavior_df())
        writer.write()

        assert out_path.exists()

        # 3. Re-open from disk — fresh HDF5 handle, no shared Python objects.
        with pynwb.NWBHDF5IO(str(out_path), mode="r") as io:
            nwbfile = io.read()
            spike_times_0 = np.asarray(nwbfile.units["spike_times"][0])
            start_time_0 = float(nwbfile.trials["start_time"][0])
            stop_time_0 = float(nwbfile.trials["stop_time"][0])
            stim_onset_0 = float(nwbfile.trials["stim_onset_time"][0])
            nidq_diag_0 = float(nwbfile.trials["stim_onset_nidq_s_diag"][0])
            imec0_col_0 = float(nwbfile.trials["stim_onset_imec_imec0"][0])
            imec1_col_0 = float(nwbfile.trials["stim_onset_imec_imec1"][0])

        # --- Assertion A: units.spike_times is IMEC seconds (from mocked analyzer) ---
        np.testing.assert_array_equal(spike_times_0, _SPIKE_TIMES_IMEC)

        # --- Assertion B: trials.start_time is the imec0 JSON value ---
        assert start_time_0 == pytest.approx(_STIM_ONSET_IMEC0)
        assert stim_onset_0 == pytest.approx(_STIM_ONSET_IMEC0)

        # --- Assertion C: same clock — the IMEC-side design, NOT NIDQ ---
        # If the two were on the NIDQ clock the diagnostic column would
        # equal start_time; if they were truly shared we'd find start_time
        # inside the [min, max] range of spike_times on the same timebase.
        assert start_time_0 != pytest.approx(nidq_diag_0)  # clocks distinguishable
        assert nidq_diag_0 == pytest.approx(_STIM_ONSET_NIDQ)  # diag verbatim
        # IMEC timebase sanity: spike_times are all within seconds of
        # start_time (they are 1.0-2.5s apart in this toy data), whereas
        # the NIDQ value is much further away (5.0).
        assert abs(start_time_0 - float(np.mean(spike_times_0))) < abs(
            nidq_diag_0 - float(np.mean(spike_times_0))
        )

        # Per-probe columns preserved verbatim.
        assert imec0_col_0 == pytest.approx(_STIM_ONSET_IMEC0)
        assert imec1_col_0 == pytest.approx(_STIM_ONSET_IMEC1)

        # stop_time uses onset_time_ms on the IMEC clock.
        assert stop_time_0 - start_time_0 == pytest.approx(0.150)
