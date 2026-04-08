"""Tests for SpikeGLX discovery and loading (io/spikeglx.py).

Tests use temporary directories to simulate SpikeGLX recording layouts.
No real .bin data is read — only file existence and meta parsing are tested.
SpikeInterface load methods are tested with mocking.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from pynpxpipe.core.errors import DiscoverError
from pynpxpipe.core.session import ProbeInfo
from pynpxpipe.io.spikeglx import SpikeGLXDiscovery, SpikeGLXLoader

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_meta(path: Path, fields: dict[str, str]) -> None:
    """Write a minimal SpikeGLX .meta file."""
    path.write_text(
        "\n".join(f"{k}={v}" for k, v in fields.items()),
        encoding="utf-8",
    )


def _make_probe_dir(
    session_dir: Path,
    probe_idx: int,
    meta_fields: dict[str, str] | None = None,
    create_bin: bool = True,
    bin_size: int = 1024,
    create_lf: bool = False,
) -> Path:
    """Create a fake imec{N} directory with .ap.meta (and optionally .ap.bin)."""
    base = f"rec_g0_t0_imec{probe_idx}"
    probe_dir = session_dir / f"{base}"
    probe_dir.mkdir(parents=True, exist_ok=True)

    if meta_fields is None:
        meta_fields = {
            "imSampRate": "30000",
            "nSavedChans": "385",
            "imProbeSN": f"12345{probe_idx}",
            "imProbeOpt": "3",
            "fileSizeBytes": str(bin_size),
        }

    meta_path = probe_dir / f"{base}.ap.meta"
    _write_meta(meta_path, meta_fields)

    if create_bin:
        bin_path = probe_dir / f"{base}.ap.bin"
        bin_path.write_bytes(b"\x00" * bin_size)

    if create_lf:
        lf_meta = probe_dir / f"{base}.lf.meta"
        _write_meta(lf_meta, {"imSampRate": "2500", "nSavedChans": "385"})
        lf_bin = probe_dir / f"{base}.lf.bin"
        lf_bin.write_bytes(b"\x00" * 256)

    return probe_dir


def _make_nidq(session_dir: Path, create_meta: bool = True) -> tuple[Path, Path]:
    """Create fake nidq .bin and .meta files."""
    nidq_bin = session_dir / "rec_g0_t0.nidq.bin"
    nidq_bin.write_bytes(b"\x00" * 512)
    nidq_meta = session_dir / "rec_g0_t0.nidq.meta"
    if create_meta:
        _write_meta(nidq_meta, {"niSampRate": "25000", "nSavedChans": "4"})
    return nidq_bin, nidq_meta


# ---------------------------------------------------------------------------
# SpikeGLXDiscovery.__init__
# ---------------------------------------------------------------------------


class TestSpikeGLXDiscoveryInit:
    def test_init_existing_dir(self, tmp_path: Path) -> None:
        disc = SpikeGLXDiscovery(tmp_path)
        assert disc.session_dir == tmp_path

    def test_init_nonexistent_dir(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            SpikeGLXDiscovery(tmp_path / "does_not_exist")


# ---------------------------------------------------------------------------
# SpikeGLXDiscovery.discover_probes
# ---------------------------------------------------------------------------


class TestDiscoverProbes:
    def test_two_probes_sorted(self, tmp_path: Path) -> None:
        _make_probe_dir(tmp_path, 0)
        _make_probe_dir(tmp_path, 1)
        probes = SpikeGLXDiscovery(tmp_path).discover_probes()
        assert len(probes) == 2
        assert probes[0].probe_id == "imec0"
        assert probes[1].probe_id == "imec1"

    def test_single_probe(self, tmp_path: Path) -> None:
        _make_probe_dir(tmp_path, 0)
        probes = SpikeGLXDiscovery(tmp_path).discover_probes()
        assert len(probes) == 1
        assert probes[0].probe_id == "imec0"

    def test_meta_fields_mapped(self, tmp_path: Path) -> None:
        _make_probe_dir(tmp_path, 0)
        probe = SpikeGLXDiscovery(tmp_path).discover_probes()[0]
        assert probe.sample_rate == 30000.0
        assert probe.n_channels == 385
        assert probe.serial_number == "123450"
        assert probe.probe_type == "3"

    def test_missing_serial_number_defaults_unknown(self, tmp_path: Path) -> None:
        fields = {"imSampRate": "30000", "nSavedChans": "385", "fileSizeBytes": "1024"}
        _make_probe_dir(tmp_path, 0, meta_fields=fields)
        probe = SpikeGLXDiscovery(tmp_path).discover_probes()[0]
        assert probe.serial_number == "unknown"

    def test_no_imec_dirs_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DiscoverError):
            SpikeGLXDiscovery(tmp_path).discover_probes()

    def test_imec_dir_without_meta_is_skipped(self, tmp_path: Path) -> None:
        # imec0 has no .ap.meta — should be skipped
        probe_dir = tmp_path / "rec_g0_t0.imec0"
        probe_dir.mkdir()
        # imec1 is valid
        _make_probe_dir(tmp_path, 1)
        probes = SpikeGLXDiscovery(tmp_path).discover_probes()
        assert len(probes) == 1
        assert probes[0].probe_id == "imec1"

    def test_all_imec_dirs_missing_meta_raises(self, tmp_path: Path) -> None:
        probe_dir = tmp_path / "rec_g0_t0.imec0"
        probe_dir.mkdir()
        with pytest.raises(DiscoverError):
            SpikeGLXDiscovery(tmp_path).discover_probes()

    def test_non_contiguous_probe_indices(self, tmp_path: Path) -> None:
        _make_probe_dir(tmp_path, 0)
        _make_probe_dir(tmp_path, 2)
        probes = SpikeGLXDiscovery(tmp_path).discover_probes()
        assert len(probes) == 2
        assert probes[0].probe_id == "imec0"
        assert probes[1].probe_id == "imec2"

    def test_lf_paths_populated_when_present(self, tmp_path: Path) -> None:
        _make_probe_dir(tmp_path, 0, create_lf=True)
        probe = SpikeGLXDiscovery(tmp_path).discover_probes()[0]
        assert probe.lf_bin is not None
        assert probe.lf_meta is not None

    def test_lf_paths_none_when_absent(self, tmp_path: Path) -> None:
        _make_probe_dir(tmp_path, 0, create_lf=False)
        probe = SpikeGLXDiscovery(tmp_path).discover_probes()[0]
        assert probe.lf_bin is None
        assert probe.lf_meta is None


# ---------------------------------------------------------------------------
# SpikeGLXDiscovery.validate_probe
# ---------------------------------------------------------------------------


class TestValidateProbe:
    def _make_valid_probe(self, tmp_path: Path) -> ProbeInfo:
        _make_probe_dir(tmp_path, 0)
        return SpikeGLXDiscovery(tmp_path).discover_probes()[0]

    def test_valid_probe_no_warnings(self, tmp_path: Path) -> None:
        probe = self._make_valid_probe(tmp_path)
        warnings = SpikeGLXDiscovery(tmp_path).validate_probe(probe)
        assert warnings == []

    def test_missing_bin_warning(self, tmp_path: Path) -> None:
        _make_probe_dir(tmp_path, 0, create_bin=False)
        probe = SpikeGLXDiscovery(tmp_path).discover_probes()[0]
        warnings = SpikeGLXDiscovery(tmp_path).validate_probe(probe)
        assert any("bin" in w.lower() for w in warnings)

    def test_missing_meta_returns_warning(self, tmp_path: Path) -> None:
        probe = self._make_valid_probe(tmp_path)
        # Remove the meta file after discovery
        probe.ap_meta.unlink()
        warnings = SpikeGLXDiscovery(tmp_path).validate_probe(probe)
        assert any("meta" in w.lower() for w in warnings)

    def test_size_mismatch_warning(self, tmp_path: Path) -> None:
        # bin_size=1024 but meta says 9999
        fields = {
            "imSampRate": "30000",
            "nSavedChans": "385",
            "imProbeSN": "12345",
            "imProbeOpt": "3",
            "fileSizeBytes": "9999",
        }
        _make_probe_dir(tmp_path, 0, meta_fields=fields, bin_size=1024)
        probe = SpikeGLXDiscovery(tmp_path).discover_probes()[0]
        warnings = SpikeGLXDiscovery(tmp_path).validate_probe(probe)
        assert any("size" in w.lower() or "bytes" in w.lower() for w in warnings)

    def test_missing_filesizebytes_no_size_warning(self, tmp_path: Path) -> None:
        fields = {"imSampRate": "30000", "nSavedChans": "385", "fileSizeBytes": "1024"}
        _make_probe_dir(tmp_path, 0, meta_fields=fields, bin_size=1024)
        probe = SpikeGLXDiscovery(tmp_path).discover_probes()[0]
        # Now remove fileSizeBytes from meta
        meta_content = probe.ap_meta.read_text(encoding="utf-8")
        new_content = "\n".join(
            line for line in meta_content.splitlines() if not line.startswith("fileSizeBytes")
        )
        probe.ap_meta.write_text(new_content, encoding="utf-8")
        warnings = SpikeGLXDiscovery(tmp_path).validate_probe(probe)
        assert not any("size" in w.lower() or "bytes" in w.lower() for w in warnings)

    def test_missing_imsamprate_warning(self, tmp_path: Path) -> None:
        fields = {"nSavedChans": "385", "fileSizeBytes": "1024"}
        _make_probe_dir(tmp_path, 0, meta_fields=fields)
        # discover_probes will fail since imSampRate is missing, so build ProbeInfo manually
        probe_dir = tmp_path / "rec_g0_t0.imec0"
        ap_meta = probe_dir / "rec_g0_t0.imec0.ap.meta"
        ap_bin = probe_dir / "rec_g0_t0.imec0.ap.bin"
        probe = ProbeInfo(
            probe_id="imec0",
            ap_bin=ap_bin,
            ap_meta=ap_meta,
            lf_bin=None,
            lf_meta=None,
            sample_rate=0.0,
            n_channels=385,
            serial_number="unknown",
            probe_type="unknown",
        )
        warnings = SpikeGLXDiscovery(tmp_path).validate_probe(probe)
        assert any("imSampRate" in w or "samp" in w.lower() for w in warnings)

    def test_multiple_issues_all_reported(self, tmp_path: Path) -> None:
        # Create probe with missing bin AND size mismatch in meta
        fields = {
            "imSampRate": "30000",
            "nSavedChans": "385",
            "fileSizeBytes": "9999",
        }
        _make_probe_dir(tmp_path, 0, meta_fields=fields, create_bin=False)
        probe = SpikeGLXDiscovery(tmp_path).discover_probes()[0]
        warnings = SpikeGLXDiscovery(tmp_path).validate_probe(probe)
        # At minimum: bin missing warning
        assert len(warnings) >= 1
        # Should not raise
        assert isinstance(warnings, list)


# ---------------------------------------------------------------------------
# SpikeGLXDiscovery.discover_nidq
# ---------------------------------------------------------------------------


class TestDiscoverNidq:
    def test_nidq_found(self, tmp_path: Path) -> None:
        nidq_bin, nidq_meta = _make_nidq(tmp_path)
        result_bin, result_meta = SpikeGLXDiscovery(tmp_path).discover_nidq()
        assert result_bin == nidq_bin
        assert result_meta == nidq_meta

    def test_no_nidq_bin_raises(self, tmp_path: Path) -> None:
        with pytest.raises(DiscoverError):
            SpikeGLXDiscovery(tmp_path).discover_nidq()

    def test_nidq_bin_present_but_no_meta_raises(self, tmp_path: Path) -> None:
        _make_nidq(tmp_path, create_meta=False)
        with pytest.raises(DiscoverError):
            SpikeGLXDiscovery(tmp_path).discover_nidq()


# ---------------------------------------------------------------------------
# SpikeGLXDiscovery.parse_meta
# ---------------------------------------------------------------------------


class TestParseMeta:
    def test_standard_key_value(self, tmp_path: Path) -> None:
        meta = tmp_path / "test.ap.meta"
        _write_meta(meta, {"imSampRate": "30000", "nSavedChans": "385"})
        result = SpikeGLXDiscovery(tmp_path).parse_meta(meta)
        assert result == {"imSampRate": "30000", "nSavedChans": "385"}

    def test_skips_empty_lines_and_comments(self, tmp_path: Path) -> None:
        meta = tmp_path / "test.ap.meta"
        meta.write_text(
            "# comment line\n\nimSampRate=30000\n\n# another comment\nnSavedChans=385\n",
            encoding="utf-8",
        )
        result = SpikeGLXDiscovery(tmp_path).parse_meta(meta)
        assert result == {"imSampRate": "30000", "nSavedChans": "385"}

    def test_value_containing_equals(self, tmp_path: Path) -> None:
        meta = tmp_path / "test.ap.meta"
        meta.write_text("filePath=C:\\data\\session=01\\rec.bin\n", encoding="utf-8")
        result = SpikeGLXDiscovery(tmp_path).parse_meta(meta)
        assert result["filePath"] == "C:\\data\\session=01\\rec.bin"

    def test_empty_file(self, tmp_path: Path) -> None:
        meta = tmp_path / "empty.ap.meta"
        meta.write_text("", encoding="utf-8")
        result = SpikeGLXDiscovery(tmp_path).parse_meta(meta)
        assert result == {}

    def test_strips_whitespace(self, tmp_path: Path) -> None:
        meta = tmp_path / "test.ap.meta"
        meta.write_text("  imSampRate  =  30000  \n", encoding="utf-8")
        result = SpikeGLXDiscovery(tmp_path).parse_meta(meta)
        assert result["imSampRate"] == "30000"


# ---------------------------------------------------------------------------
# SpikeGLXLoader.load_ap / load_nidq / load_preprocessed
# ---------------------------------------------------------------------------


class TestSpikeGLXLoader:
    def test_load_ap_calls_read_spikeglx(self, tmp_path: Path) -> None:
        _make_probe_dir(tmp_path, 0)
        probe = SpikeGLXDiscovery(tmp_path).discover_probes()[0]
        mock_recording = MagicMock()
        with patch(
            "pynpxpipe.io.spikeglx.se.read_spikeglx", return_value=mock_recording
        ) as mock_fn:
            result = SpikeGLXLoader.load_ap(probe)
        mock_fn.assert_called_once()
        call_kwargs = mock_fn.call_args
        assert call_kwargs[1].get("stream_name") == "imec0.ap" or "imec0.ap" in str(call_kwargs)
        assert result is mock_recording

    def test_load_nidq_calls_read_spikeglx(self, tmp_path: Path) -> None:
        nidq_bin, nidq_meta = _make_nidq(tmp_path)
        mock_recording = MagicMock()
        with patch(
            "pynpxpipe.io.spikeglx.se.read_spikeglx", return_value=mock_recording
        ) as mock_fn:
            result = SpikeGLXLoader.load_nidq(nidq_bin, nidq_meta)
        mock_fn.assert_called_once()
        assert result is mock_recording

    def test_load_preprocessed_calls_load_extractor(self, tmp_path: Path) -> None:
        zarr_dir = tmp_path / "preprocessed"
        zarr_dir.mkdir()
        mock_recording = MagicMock()
        with patch("pynpxpipe.io.spikeglx.si.load", return_value=mock_recording) as mock_fn:
            result = SpikeGLXLoader.load_preprocessed(zarr_dir)
        mock_fn.assert_called_once_with(zarr_dir)
        assert result is mock_recording


# ---------------------------------------------------------------------------
# SpikeGLXLoader.extract_sync_edges
# ---------------------------------------------------------------------------


class TestExtractSyncEdges:
    def _make_recording(self, digital_data: np.ndarray) -> MagicMock:
        """Create a mock recording whose get_traces returns digital_data."""
        recording = MagicMock()
        recording.get_traces.return_value = digital_data.reshape(-1, 1)
        return recording

    def test_known_rising_edges(self) -> None:
        # Bit 0: signal is 0,0,1,1,0,0,1,1 → rising edges at sample 2 and 6
        signal = np.array([0, 0, 1, 1, 0, 0, 1, 1], dtype=np.uint16)
        recording = self._make_recording(signal)
        edges = SpikeGLXLoader.extract_sync_edges(recording, sync_bit=0, sample_rate=1.0)
        assert edges == pytest.approx([2.0, 6.0])

    def test_sync_bit_isolation(self) -> None:
        # Bit 1 is always 0; bit 0 has a rising edge at sample 3
        signal = np.array([0b00, 0b00, 0b00, 0b01, 0b01], dtype=np.uint16)
        recording = self._make_recording(signal)
        edges_bit0 = SpikeGLXLoader.extract_sync_edges(recording, sync_bit=0, sample_rate=1.0)
        edges_bit1 = SpikeGLXLoader.extract_sync_edges(recording, sync_bit=1, sample_rate=1.0)
        assert len(edges_bit0) == 1
        assert edges_bit1 == []

    def test_no_pulses_returns_empty(self) -> None:
        signal = np.zeros(100, dtype=np.uint16)
        recording = self._make_recording(signal)
        edges = SpikeGLXLoader.extract_sync_edges(recording, sync_bit=0, sample_rate=30000.0)
        assert edges == []

    def test_single_rising_edge(self) -> None:
        signal = np.array([0, 0, 1, 1, 1], dtype=np.uint16)
        recording = self._make_recording(signal)
        edges = SpikeGLXLoader.extract_sync_edges(recording, sync_bit=0, sample_rate=2.0)
        assert len(edges) == 1
        assert edges[0] == pytest.approx(1.0)  # sample 2 / rate 2.0

    def test_sample_rate_scaling(self) -> None:
        # Rising edge at sample index 30000; rate=30000 → 1.0 second
        signal = np.zeros(60001, dtype=np.uint16)
        signal[30000:] = 1
        recording = self._make_recording(signal)
        edges = SpikeGLXLoader.extract_sync_edges(recording, sync_bit=0, sample_rate=30000.0)
        assert len(edges) == 1
        assert edges[0] == pytest.approx(1.0)
