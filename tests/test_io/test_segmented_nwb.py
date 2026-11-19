"""Real NWB round-trip with discontinuous raw data and observation intervals."""

from datetime import UTC, datetime
from types import SimpleNamespace

import h5py
import numpy as np
import pandas as pd
import pytest
import spikeinterface.core as si
from pynwb import NWBHDF5IO, NWBFile, validate

from pynpxpipe.core.config import PipelineConfig
from pynpxpipe.core.segments import Segment, SegmentManifest
from pynpxpipe.io.nwb_reader import NWBLoader
from pynpxpipe.io.nwb_writer import NWBWriter
from pynpxpipe.io.segmented_nwb import add_segment_metadata, append_segmented_raw, series_name


@pytest.fixture
def segmented_nwb(tmp_path, monkeypatch):
    data = np.arange(4000, dtype=np.int16).reshape(2000, 2)
    raw = si.NumpyRecording(data, 1000)
    raw.set_channel_gains([2.0, 3.0])
    raw.set_channel_offsets([0.0, 0.0])
    raw.set_channel_locations([[0.0, 0.0], [0.0, 20.0]])
    monkeypatch.setattr("pynpxpipe.io.segmented_nwb.load_source_stream", lambda *a: raw)
    cfg = PipelineConfig()
    session = SimpleNamespace(config=cfg, output_dir=tmp_path)
    segments = [
        Segment("a", "imec0", 100, 600, 0, 1000, 1.0, 0.0),
        Segment("b", "imec0", 200, 700, 500, 1000, 1.001, 10.0),
        Segment("a", "nidq", 100, 600, 0, 1000, 1.0, 0.0, "nidq"),
    ]
    manifest = SegmentManifest(
        segments,
        0.1,
        [{"source_id": "a", "sync": {}}, {"source_id": "b", "sync": {}}],
        datetime.now(UTC).isoformat(),
    )
    path = tmp_path / "combined.nwb"
    nf = NWBFile("selected test", "test", datetime.now(UTC))
    device = nf.create_device("imec0")
    group = nf.create_electrode_group("imec0", "test", "V4", device)
    nf.add_electrode_column("probe_id", "probe")
    nf.add_electrode_column("channel_id", "channel")
    for channel in range(2):
        nf.add_electrode(
            x=0.0,
            y=float(channel * 20),
            z=0.0,
            location="V4",
            group=group,
            probe_id="imec0",
            channel_id=channel,
        )
    nf.add_unit_column("probe_id", "probe")
    nf.add_unit_column("ks_id", "shared sorter ID")
    nf.add_unit(
        id=5,
        probe_id="imec0",
        ks_id=7,
        spike_times=[0.2, 10.4004],
        obs_intervals=manifest.observation_intervals("imec0"),
    )
    (tmp_path / "04_sync").mkdir()
    pd.DataFrame(
        {
            "start_time": [0.2, 10.4004],
            "stop_time": [0.25, 10.45045],
            "source_id": ["a", "b"],
            "trial_id": [1, 1],
            "trial_key": ["a:1", "b:1"],
        }
    ).to_parquet(tmp_path / "04_sync" / "full_trials.parquet")
    writer = NWBWriter(session, path)
    writer._nwbfile = nf
    add_segment_metadata(writer, manifest)
    with NWBHDF5IO(path, "w") as io:
        io.write(nf)
    return session, path, manifest, data


def test_raw_roundtrip_clocks_unit_ids_and_idempotent_resume(segmented_nwb):
    session, path, manifest, data = segmented_nwb
    result = append_segmented_raw(session, path, manifest)
    assert result["streams_written"] == 3
    assert append_segmented_raw(session, path, manifest)["streams_written"] == 0
    with NWBHDF5IO(path, "r") as io:
        nf = io.read()
        for i, s in enumerate(manifest.segments):
            stream = nf.acquisition[series_name(s, i)]
            np.testing.assert_array_equal(stream.data[:], data[s.start_frame : s.stop_frame])
            assert stream.starting_time == pytest.approx(s.time(s.start_frame))
            assert stream.rate == pytest.approx(s.sample_rate / s.time_scale)
        np.testing.assert_allclose(nf.units["obs_intervals"][0], [[0.1, 0.5], [10.3003, 10.7007]])
        assert len(nf.intervals["full_trials"]) == 2
    assert validate(path=path) == []
    loader = NWBLoader(path)
    assert loader.inspect().probe_ids == ("imec0",)
    assert loader.inspect().has_nidq_raw
    recording = loader.load_recordings()["imec0"].recording
    assert recording.get_num_segments() == 2
    np.testing.assert_array_equal(recording.get_traces(segment_index=1), data[200:700])
    sorting = loader.load_sortings()["imec0"].sorting
    np.testing.assert_array_equal(sorting.get_unit_spike_train(5, segment_index=0), [100])
    np.testing.assert_array_equal(sorting.get_unit_spike_train(5, segment_index=1), [200])


def test_corrupt_block_repair_and_stale_manifest_rejection(segmented_nwb):
    session, path, manifest, _ = segmented_nwb
    append_segmented_raw(session, path, manifest)
    name = series_name(manifest.segments[0], 0)
    with h5py.File(path, "a") as handle:
        handle[f"acquisition/{name}/data"][0, 0] += 1
    session.config.export.repair_verify = "full"
    assert append_segmented_raw(session, path, manifest)["streams_repaired"] == 1
    changed = SegmentManifest(manifest.segments, 0.05)
    with pytest.raises(ValueError, match="signature"):
        append_segmented_raw(session, path, changed)


def test_raw_rerun_preserves_source_frames_real_times_and_observations(segmented_nwb, monkeypatch):
    from pynpxpipe.core.config import SortingConfig
    from pynpxpipe.pipelines.nwb_rerun import rerun_from_nwb

    session, path, manifest, _ = segmented_nwb
    append_segmented_raw(session, path, manifest)
    original = path.read_bytes()
    cfg = session.config
    cfg.preprocess.bandpass.freq_min = 100
    cfg.preprocess.bandpass.freq_max = 400
    cfg.preprocess.motion_correction.method = None
    monkeypatch.setattr(
        "pynpxpipe.pipelines.nwb_rerun.spp.detect_bad_channels", lambda *a, **k: ([], [])
    )

    def sorter(name, recording, **kwargs):
        assert recording.get_num_samples() == 1000
        return si.NumpySorting.from_unit_dict({7: np.array([100, 600])}, 1000)

    monkeypatch.setattr("pynpxpipe.pipelines.nwb_rerun.ss.run_sorter", sorter)
    result = rerun_from_nwb(
        path, path.parent / "rerun", mode="raw", pipeline_config=cfg, sorting_config=SortingConfig()
    )
    assert path.read_bytes() == original
    assert validate(path=result.output_nwb) == []
    with NWBHDF5IO(result.output_nwb, "r") as io:
        nf = io.read()
        np.testing.assert_allclose(nf.units["spike_times"][0], [0.2, 10.3003])
        np.testing.assert_allclose(
            nf.units["obs_intervals"][0], manifest.observation_intervals("imec0")
        )
    restored = NWBLoader(result.output_nwb).load_sortings()["imec0"].sorting
    np.testing.assert_array_equal(
        restored.get_unit_spike_train(restored.unit_ids[0], segment_index=1), [100]
    )


def test_zero_unit_probe_adds_electrodes_with_aligned_metadata(segmented_nwb):
    from pynpxpipe.io.segmented_nwb import ensure_raw_electrodes

    session, path, _, _ = segmented_nwb
    session.recording_sources = [SimpleNamespace(source_id="a")]
    probe = SimpleNamespace(
        probe_id="imec1", probe_type="NP1", serial_number="SN-2", target_area="IT"
    )
    writer = NWBWriter(session, path)
    nf = NWBFile("two probe test", "two-probe", datetime.now(UTC))
    writer._nwbfile = nf
    group = nf.create_electrode_group("imec0", "test", "V4", nf.create_device("imec0"))
    nf.add_electrode_column("probe_id", "Probe identifier")
    nf.add_electrode_column("channel_id", "Channel index within probe")
    for channel in range(2):
        nf.add_electrode(
            x=0.0,
            y=float(channel * 20),
            z=0.0,
            location="V4",
            group=group,
            probe_id="imec0",
            channel_id=channel,
        )
    ensure_raw_electrodes(writer, probe)
    assert list(nf.electrodes["probe_id"][:]) == ["imec0", "imec0", "imec1", "imec1"]
    assert len(nf.electrodes["inter_sample_shift"]) == 4
    destination = path.with_name("no-units.nwb")
    with NWBHDF5IO(destination, "w") as io:
        io.write(writer._nwbfile)
    assert validate(path=destination) == []
