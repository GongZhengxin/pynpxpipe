"""NIDQ export contract harness (E1.2).

End-to-end validation that a synthetic NIDQ recording survives a full round
trip through ``NWBWriter.append_raw_data`` with bit-exact int16 preservation,
correct ``conversion``/``rate``/``unit`` scalars, and a ``description`` that
carries the NIDQ channel layout and sync bit metadata downstream readers need
to decode the digital word without reparsing the original SpikeGLX .meta.

Runtime budget: <3s. No real SpikeGLX binary, no GPU, no network.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pynwb
import pytest
import spikeinterface.core as si

from pynpxpipe.core.config import PipelineConfig
from pynpxpipe.core.session import (
    ProbeInfo,
    Session,
    SessionManager,
    SubjectConfig,
)
from pynpxpipe.io.nwb_writer import NWBWriter

# ── Fixtures ─────────────────────────────────────────────────────────────


def _subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="MaoDan",
        description="NIDQ contract harness",
        species="Macaca mulatta",
        sex="M",
        age="P4Y",
        weight="12kg",
    )


_NIDQ_SAMP_RATE = 30000.0
_NIDQ_N_CHANNELS = 8
_NIDQ_N_SAMPLES = int(_NIDQ_SAMP_RATE * 1.0)  # 1 second
_NI_AI_RANGE_MAX = 5.0


def _write_nidq_meta(path: Path) -> None:
    """Write a minimal but realistic SpikeGLX .nidq.meta."""
    path.write_text(
        "\n".join(
            [
                f"niSampRate={_NIDQ_SAMP_RATE}",
                f"niAiRangeMax={_NI_AI_RANGE_MAX}",
                f"niAiRangeMin=-{_NI_AI_RANGE_MAX}",
                f"nSavedChans={_NIDQ_N_CHANNELS}",
                "snsMnMaXaDw=0,0,7,1",
                "niMNGain=200",
                "niMAGain=1",
                "fileSizeBytes=0",
                "typeThis=nidq",
                "fileCreateTime=2024-01-15T14:30:00",
            ]
        ),
        encoding="utf-8",
    )


def _make_synthetic_nidq_array() -> np.ndarray:
    """Synthetic int16 NIDQ array with a known, verifiable pattern."""
    total = _NIDQ_N_SAMPLES * _NIDQ_N_CHANNELS
    return (np.arange(total) % 1000).astype(np.int16).reshape(_NIDQ_N_SAMPLES, _NIDQ_N_CHANNELS)


def _make_session(tmp_path: Path) -> tuple[Session, np.ndarray]:
    """Build a Session with a session_dir housing nidq.bin/meta and a probe placeholder."""
    session_dir = tmp_path / "rec_g0"
    session_dir.mkdir()

    nidq_bin = session_dir / "rec_g0_t0.nidq.bin"
    source = _make_synthetic_nidq_array()
    nidq_bin.write_bytes(source.tobytes(order="C"))
    _write_nidq_meta(session_dir / "rec_g0_t0.nidq.meta")

    # Probe AP meta (needed by NWBWriter.create_file to derive session_start_time).
    probe_dir = tmp_path / "probe0"
    probe_dir.mkdir()
    ap_meta = probe_dir / "imec0.ap.meta"
    ap_meta.write_text(
        "fileCreateTime=2024-01-15T14:30:00\nimSampRate=30000\nnSavedChans=4\n",
        encoding="utf-8",
    )

    bhv = tmp_path / "task.bhv2"
    bhv.write_bytes(b"\x00" * 16)

    output_dir = tmp_path / "out"
    s = SessionManager.create(
        session_dir,
        bhv,
        _subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4"},
        date="240115",
    )
    s.config = PipelineConfig()

    # Minimal probe carrying target_area so downstream invariants hold.
    probe = ProbeInfo(
        probe_id="imec0",
        ap_bin=probe_dir / "imec0.ap.bin",
        ap_meta=ap_meta,
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=4,
        serial_number="SN001",
        probe_type="NP1010",
        target_area="V4",
        channel_positions=[(float(i * 16), float(i * 20)) for i in range(4)],
    )
    s.probes = [probe]
    return s, source


def _make_numpy_recording_int16(data: np.ndarray, sampling_frequency: float) -> si.BaseRecording:
    """Wrap an int16 array as a SpikeInterface NumpyRecording with gain_to_uV."""
    rec = si.NumpyRecording(
        traces_list=[data.astype(np.float32)],
        sampling_frequency=sampling_frequency,
    )
    rec.set_property("gain_to_uV", np.array([1.0] * data.shape[1]))
    return rec


def _make_nwb_with_imec0_electrodes(nwb_path: Path) -> None:
    """Minimal pre-existing NWB file so append_raw_data has an AP stream to iterate."""
    nwbfile = pynwb.NWBFile(
        session_description="harness",
        identifier=str(uuid.uuid4()),
        session_start_time=datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC),
    )
    nwbfile.subject = pynwb.file.Subject(
        subject_id="MaoDan", species="Macaca mulatta", sex="M", age="P4Y"
    )
    dev = nwbfile.create_device(name="NP_imec0")
    grp = nwbfile.create_electrode_group(
        name="group_imec0", description="imec0", device=dev, location="V4"
    )
    nwbfile.add_electrode_column("probe_id", "Probe identifier")
    nwbfile.add_electrode_column("channel_id", "Channel index")
    for ch in range(4):
        nwbfile.add_electrode(
            group=grp,
            probe_id="imec0",
            channel_id=ch,
            location="V4",
            x=0.0,
            y=float(ch * 10),
            z=0.0,
            filtering="none",
        )
    with pynwb.NWBHDF5IO(str(nwb_path), "w") as io:
        io.write(nwbfile)


# ── Contract test ────────────────────────────────────────────────────────


class TestNIDQExportContract:
    """Full roundtrip: synthetic nidq.bin → append_raw_data → NWB → bit-exact reopen."""

    def test_roundtrip_bit_exact(self, tmp_path: Path) -> None:
        t0 = time.perf_counter()

        session, source = _make_session(tmp_path)

        nwb_path = tmp_path / "out.nwb"
        _make_nwb_with_imec0_electrodes(nwb_path)

        # Lazy AP / NIDQ recordings — real load_ap/load_nidq go through SI's
        # SpikeGLX reader, which requires a carefully formed binary; here we
        # exercise the NIDQ code path with in-memory NumpyRecording substitutes.
        ap_rec = _make_numpy_recording_int16(
            np.zeros((3000, 4), dtype=np.int16),
            sampling_frequency=30000.0,
        )
        nidq_rec = _make_numpy_recording_int16(source, sampling_frequency=_NIDQ_SAMP_RATE)

        from unittest.mock import patch

        writer = NWBWriter(session, nwb_path)
        with (
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=ap_rec),
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_nidq", return_value=nidq_rec),
        ):
            result = writer.append_raw_data(session, nwb_path)

        assert "NIDQ_raw" in result["stream_names"]

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            ts = nwbfile.acquisition["NIDQ_raw"]
            nwb_data = ts.data[:]

            # Bit-exact full-array match.
            assert np.array_equal(nwb_data, source)
            assert nwb_data.dtype == np.int16

            # Scalar metadata.
            assert ts.conversion == pytest.approx(_NI_AI_RANGE_MAX / 32768.0)
            assert ts.rate == pytest.approx(_NIDQ_SAMP_RATE)
            assert ts.unit == "V"
            assert ts.starting_time == pytest.approx(0.0)

            # Description must carry decoding hints downstream readers need.
            for literal in ("niAiRangeMax=", "niSampRate=", "event_bits=", "sync_bit="):
                assert literal in ts.description, (
                    f"missing literal {literal!r} in NIDQ description: {ts.description!r}"
                )

        elapsed = time.perf_counter() - t0
        assert elapsed < 3.0, f"harness exceeded 3s budget: {elapsed:.3f}s"
