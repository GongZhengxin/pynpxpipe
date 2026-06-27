"""Tests for io/nwb_reader.py — NWB input inspection for rerun workflows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from pynwb import NWBHDF5IO, NWBFile, TimeSeries
from pynwb.ecephys import ElectricalSeries

from pynpxpipe.core.errors import NWBInputError
from pynpxpipe.io.nwb_reader import NWBLoader


def _write_tiny_nwb(
    path: Path,
    *,
    include_probe_id: bool = True,
    ap_probe_ids: tuple[str, ...] = ("imec0",),
) -> Path:
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
    for probe_id in ap_probe_ids:
        nwbfile.add_acquisition(
            TimeSeries(
                name=f"ElectricalSeriesAP_{probe_id}",
                data=np.zeros((4, 2), dtype=np.int16),
                unit="uV",
                rate=1000.0 if probe_id == "imec0" else 2000.0,
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


def _write_raw_electrical_series_nwb(
    path: Path,
    *,
    probe_ids: tuple[str, ...] = ("imec0", "imec1"),
    inter_sample_shift: dict[str, list[float]] | None = None,
) -> Path:
    """Write a tiny NWB with loadable per-probe ElectricalSeriesAP streams.

    When ``inter_sample_shift`` maps a probe_id to per-channel shift values, an
    ``inter_sample_shift`` electrode column is written (mirrors the writer
    fix in nwb_writer.md §9 so the reader can restore phase_shift metadata).
    """
    nwbfile = NWBFile(
        session_description="tiny raw fixture",
        identifier="tiny-raw-fixture",
        session_start_time=datetime(2024, 1, 1),
        session_id="240101_Test_nsd1w_V4",
    )
    nwbfile.add_electrode_column("probe_id", "Probe identifier")
    if inter_sample_shift is not None:
        nwbfile.add_electrode_column("inter_sample_shift", "Per-channel ADC sample shift")
    electrode_offset = 0
    for probe_id in probe_ids:
        device = nwbfile.create_device(f"{probe_id}_device")
        group = nwbfile.create_electrode_group(
            f"{probe_id}_group",
            description=f"{probe_id} electrodes",
            location="V4",
            device=device,
        )
        electrode_indices = []
        for channel in range(2):
            row_id = electrode_offset + channel
            extra = (
                {"inter_sample_shift": float(inter_sample_shift[probe_id][channel])}
                if inter_sample_shift is not None
                else {}
            )
            nwbfile.add_electrode(
                id=row_id,
                x=float(channel),
                y=float(channel * 20),
                z=0.0,
                imp=np.nan,
                location="V4",
                filtering="none",
                group=group,
                probe_id=probe_id,
                **extra,
            )
            electrode_indices.append(row_id)
        electrode_offset += 2
        region = nwbfile.create_electrode_table_region(
            electrode_indices,
            f"AP electrodes for {probe_id}",
        )
        data = np.arange(20, dtype=np.int16).reshape(10, 2) + electrode_indices[0] * 100
        nwbfile.add_acquisition(
            ElectricalSeries(
                name=f"ElectricalSeriesAP_{probe_id}",
                data=data,
                electrodes=region,
                starting_time=0.0,
                rate=1000.0 if probe_id == "imec0" else 2000.0,
                conversion=1e-6,
                description=f"Raw AP recording for {probe_id}",
            )
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


def test_require_raw_capability_accepts_electrical_series(tmp_path: Path) -> None:
    """Raw rerun capability accepts loadable AP ElectricalSeries streams."""
    nwb_path = _write_raw_electrical_series_nwb(tmp_path / "input.nwb")

    NWBLoader(nwb_path).require_capabilities("raw")


def test_require_raw_capability_reports_missing_ap(tmp_path: Path) -> None:
    """Raw rerun capability reports missing AP streams clearly."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb", ap_probe_ids=())

    with pytest.raises(NWBInputError, match="ElectricalSeriesAP"):
        NWBLoader(nwb_path).require_capabilities("raw")


def test_missing_file_raises_nwb_input_error(tmp_path: Path) -> None:
    """Missing paths are reported as NWBInputError."""
    with pytest.raises(NWBInputError, match="not found"):
        NWBLoader(tmp_path / "missing.nwb").inspect()


def test_load_sortings_splits_by_probe(tmp_path: Path) -> None:
    """load_sortings() returns one SpikeInterface sorting bundle per probe."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb")

    bundles = NWBLoader(nwb_path).load_sortings(sampling_frequency=1000.0)

    assert set(bundles) == {"imec0", "imec1"}
    assert list(bundles["imec0"].sorting.get_unit_ids()) == [11]
    assert list(bundles["imec1"].sorting.get_unit_ids()) == [12]


def test_load_sortings_roundtrips_spike_times(tmp_path: Path) -> None:
    """SpikeInterface return_times=True approximately recovers NWB spike_times."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb")

    bundles = NWBLoader(nwb_path).load_sortings(sampling_frequency=1000.0)
    spike_times = bundles["imec0"].sorting.get_unit_spike_train(11, return_times=True)

    assert np.allclose(spike_times, np.array([0.1, 0.2, 0.3]))


def test_load_sortings_preserves_unit_properties(tmp_path: Path) -> None:
    """Unit metadata columns become SpikeInterface sorting properties."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb")

    bundles = NWBLoader(nwb_path).load_sortings(sampling_frequency=1000.0)

    assert bundles["imec0"].sorting.get_property("unittype_string").tolist() == ["SUA"]
    assert bundles["imec1"].sorting.get_property("is_visual").tolist() == [False]


def test_load_sortings_infers_sampling_frequency_from_ap_stream(tmp_path: Path) -> None:
    """When no sampling_frequency is passed, AP acquisition rate is used per probe."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb", ap_probe_ids=("imec0", "imec1"))

    bundles = NWBLoader(nwb_path).load_sortings()

    assert bundles["imec0"].sampling_frequency == 1000.0
    assert bundles["imec1"].sampling_frequency == 2000.0


def test_load_sortings_requires_sampling_frequency_without_ap(tmp_path: Path) -> None:
    """A bare /units table is not enough to convert seconds to sample indices."""
    nwb_path = _write_tiny_nwb(tmp_path / "input.nwb", ap_probe_ids=())

    with pytest.raises(NWBInputError, match="sampling_frequency"):
        NWBLoader(nwb_path).load_sortings()


def test_load_recordings_returns_per_probe_ap_recordings(tmp_path: Path) -> None:
    """load_recordings() exposes AP ElectricalSeries as SpikeInterface recordings."""
    nwb_path = _write_raw_electrical_series_nwb(tmp_path / "input.nwb")

    bundles = NWBLoader(nwb_path).load_recordings(load_channel_properties=False)

    assert set(bundles) == {"imec0", "imec1"}
    assert bundles["imec0"].series_path == "acquisition/ElectricalSeriesAP_imec0"
    assert bundles["imec0"].sampling_frequency == 1000.0
    assert bundles["imec1"].sampling_frequency == 2000.0
    assert bundles["imec0"].recording.get_num_channels() == 2
    assert bundles["imec0"].recording.get_num_samples() == 10
    traces = bundles["imec0"].recording.get_traces(start_frame=0, end_frame=3)
    assert traces.tolist() == [[0, 1], [2, 3], [4, 5]]


def test_load_recordings_restores_channel_locations(tmp_path: Path) -> None:
    """ElectricalSeries electrode x/y coordinates become SI channel locations."""
    nwb_path = _write_raw_electrical_series_nwb(tmp_path / "input.nwb", probe_ids=("imec0",))

    bundles = NWBLoader(nwb_path).load_recordings()

    locations = bundles["imec0"].recording.get_channel_locations()
    assert np.allclose(locations, np.array([[0.0, 0.0], [1.0, 20.0]]))


def test_load_recordings_requires_matching_stream(tmp_path: Path) -> None:
    """A clear error is raised when the requested raw stream family is absent."""
    nwb_path = _write_raw_electrical_series_nwb(tmp_path / "input.nwb")

    with pytest.raises(NWBInputError, match="ElectricalSeriesLF"):
        NWBLoader(nwb_path).load_recordings(stream_type="lf")


def test_load_recordings_restores_inter_sample_shift(tmp_path: Path) -> None:
    """nwb_reader.md §10: an inter_sample_shift electrode column becomes a
    recording property so _preprocess_raw_recording applies phase_shift."""
    nwb_path = _write_raw_electrical_series_nwb(
        tmp_path / "input.nwb",
        probe_ids=("imec0", "imec1"),
        inter_sample_shift={"imec0": [0.0, 0.5], "imec1": [0.1, 0.6]},
    )

    bundles = NWBLoader(nwb_path).load_recordings(stream_type="ap")

    shift0 = bundles["imec0"].recording.get_property("inter_sample_shift")
    shift1 = bundles["imec1"].recording.get_property("inter_sample_shift")
    assert shift0 is not None
    assert np.allclose(shift0, [0.0, 0.5])
    assert np.allclose(shift1, [0.1, 0.6])
    assert len(shift0) == bundles["imec0"].recording.get_num_channels()


def test_load_recordings_without_shift_column_no_raise(tmp_path: Path) -> None:
    """Old NWBs lacking the inter_sample_shift column still load (no raise);
    the property is simply absent (phase_shift then skipped, current behavior)."""
    nwb_path = _write_raw_electrical_series_nwb(tmp_path / "input.nwb", probe_ids=("imec0",))

    bundles = NWBLoader(nwb_path).load_recordings(stream_type="ap")

    assert bundles["imec0"].recording.get_property("inter_sample_shift") is None
