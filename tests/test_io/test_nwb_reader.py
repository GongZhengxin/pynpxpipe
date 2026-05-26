"""Tests for io/nwb_reader.py — NWB input inspection for rerun workflows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from pynwb import NWBHDF5IO, NWBFile, TimeSeries

from pynpxpipe.core.errors import NWBInputError
from pynpxpipe.io.nwb_reader import NWBLoader


def _write_tiny_nwb(path: Path, *, include_probe_id: bool = True) -> Path:
    """Write a minimal pynpxpipe-like NWB fixture."""
    nwbfile = NWBFile(
        session_description="tiny pynpxpipe fixture",
        identifier="tiny-fixture",
        session_start_time=datetime(2024, 1, 1),
        session_id="240101_Test_nsd1w_V4",
    )
    if include_probe_id:
        nwbfile.add_unit_column("probe_id", "Probe identifier")
    nwbfile.add_unit_column("unittype_string", "Unit type")
    nwbfile.add_unit_column("is_visual", "Visual response flag")
    nwbfile.add_unit_column("slay_score", "SLAY score")
    nwbfile.add_unit(
        id=11,
        spike_times=np.array([0.1, 0.2, 0.3]),
        **({"probe_id": "imec0"} if include_probe_id else {}),
        unittype_string="SUA",
        is_visual=True,
        slay_score=0.8,
    )
    nwbfile.add_unit(
        id=12,
        spike_times=np.array([0.4, 0.5]),
        **({"probe_id": "imec1"} if include_probe_id else {}),
        unittype_string="MUA",
        is_visual=False,
        slay_score=0.2,
    )
    nwbfile.add_trial(start_time=0.0, stop_time=1.0)
    nwbfile.add_acquisition(
        TimeSeries(
            name="ElectricalSeriesAP_imec0",
            data=np.zeros((4, 2), dtype=np.int16),
            unit="uV",
            rate=30000.0,
        )
    )
    nwbfile.add_acquisition(
        TimeSeries(
            name="NIDQ_raw",
            data=np.zeros((4, 1), dtype=np.int16),
            unit="V",
            rate=25000.0,
        )
    )
    nwbfile.add_scratch(
        json.dumps({"imec_nidq": {"imec0": {"a": 1.0, "b": 0.0}}}),
        name="sync_tables",
        description="sync tables JSON",
    )

    with NWBHDF5IO(path, "w") as io:
        io.write(nwbfile)
    return path


def test_inspect_basic_pynpxpipe_nwb(tmp_path: Path) -> None:
    """inspect() summarizes session id, units, trials, and probe ids."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb")

    summary = NWBLoader(nwb_path).inspect()

    assert summary.session_id == "240101_Test_nsd1w_V4"
    assert summary.n_units == 2
    assert summary.n_trials == 1
    assert summary.probe_ids == ("imec0", "imec1")
    assert summary.has_units is True
    assert summary.has_trials is True
    assert summary.has_sync_tables is True


def test_inspect_detects_raw_streams(tmp_path: Path) -> None:
    """inspect() records AP and NIDQ acquisition availability without loading raw arrays."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb")

    summary = NWBLoader(nwb_path).inspect()

    assert summary.raw_ap_streams == {"imec0": "ElectricalSeriesAP_imec0"}
    assert summary.has_nidq_raw is True


def test_load_units_returns_dataframe(tmp_path: Path) -> None:
    """load_units() exposes NWB row ids and ragged spike_times as arrays."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb")

    units = NWBLoader(nwb_path).load_units()

    assert list(units["unit_id"]) == [11, 12]
    assert list(units["probe_id"]) == ["imec0", "imec1"]
    assert isinstance(units.loc[0, "spike_times"], np.ndarray)
    assert np.allclose(units.loc[0, "spike_times"], np.array([0.1, 0.2, 0.3]))


def test_load_units_requires_probe_id(tmp_path: Path) -> None:
    """probe_id is mandatory because rerun workflows are multi-probe aware."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb", include_probe_id=False)

    with pytest.raises(NWBInputError, match="probe_id"):
        NWBLoader(nwb_path).load_units()


def test_require_rewrite_units_capability(tmp_path: Path) -> None:
    """rewrite-units requires units, probe_id, and spike_times."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb")

    NWBLoader(nwb_path).require_capabilities("rewrite-units")


def test_require_raw_capability_reports_missing_ap(tmp_path: Path) -> None:
    """Raw rerun capability reports missing AP streams clearly."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb")

    with pytest.raises(NWBInputError, match="not implemented"):
        NWBLoader(nwb_path).require_capabilities("raw")


def test_missing_file_raises_nwb_input_error(tmp_path: Path) -> None:
    """Missing paths are reported as NWBInputError."""
    with pytest.raises(NWBInputError, match="not found"):
        NWBLoader(tmp_path / "missing.nwb").inspect()
