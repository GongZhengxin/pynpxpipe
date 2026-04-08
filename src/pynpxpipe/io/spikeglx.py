"""SpikeGLX data discovery and lazy loading.

Handles multi-probe SpikeGLX recording folders. No UI dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import spikeinterface.core as si
import spikeinterface.extractors as se

from pynpxpipe.core.errors import DiscoverError
from pynpxpipe.core.session import ProbeInfo

if TYPE_CHECKING:
    pass


class SpikeGLXDiscovery:
    """Scans a SpikeGLX recording folder to discover all probes and validate data integrity.

    SpikeGLX recordings contain one subdirectory per probe (imec0, imec1, ...) and a
    top-level nidq directory. Each probe directory contains .ap.bin, .ap.meta, and
    optionally .lf.bin, .lf.meta files.
    """

    def __init__(self, session_dir: Path) -> None:
        """Initialize the discovery scanner.

        Args:
            session_dir: Root directory of the SpikeGLX recording session.

        Raises:
            FileNotFoundError: If session_dir does not exist.
        """
        if not session_dir.exists():
            raise FileNotFoundError(f"Session directory not found: {session_dir}")
        self.session_dir = session_dir

    def discover_probes(self) -> list[ProbeInfo]:
        """Scan session_dir for all imec{N} probe directories.

        Reads each probe's .ap.meta to extract sample_rate, n_channels, probe_type,
        and serial_number. Does NOT load .bin data.

        Returns:
            List of ProbeInfo objects sorted by probe index (imec0 first).

        Raises:
            DiscoverError: If no imec directories are found.
        """
        probes: list[tuple[int, ProbeInfo]] = []

        for candidate in self.session_dir.iterdir():
            if not candidate.is_dir():
                continue
            match = re.search(r"_imec(\d+)$", candidate.name)
            if match is None:
                continue
            probe_idx = int(match.group(1))

            meta_files = list(candidate.glob("*.ap.meta"))
            if not meta_files:
                continue
            meta_path = meta_files[0]
            meta = self.parse_meta(meta_path)

            # Infer bin path from meta filename (.ap.meta → .ap.bin)
            ap_bin = meta_path.parent / meta_path.name.replace(".ap.meta", ".ap.bin")

            # Optional LF files
            lf_meta_files = list(candidate.glob("*.lf.meta"))
            lf_meta = lf_meta_files[0] if lf_meta_files else None
            lf_bin: Path | None = None
            if lf_meta is not None:
                lf_bin_candidate = lf_meta.parent / lf_meta.name.replace(".lf.meta", ".lf.bin")
                lf_bin = lf_bin_candidate if lf_bin_candidate.exists() else None

            probe_id = f"imec{probe_idx}"
            probe = ProbeInfo(
                probe_id=probe_id,
                ap_bin=ap_bin,
                ap_meta=meta_path,
                lf_bin=lf_bin,
                lf_meta=lf_meta,
                sample_rate=float(meta.get("imSampRate", 0)),
                n_channels=int(meta.get("nSavedChans", 0)),
                serial_number=meta.get("imProbeSN", "unknown"),
                probe_type=meta.get("imProbeOpt", meta.get("imProbeType", "unknown")),
            )
            probes.append((probe_idx, probe))

        if not probes:
            raise DiscoverError(f"No imec probe directories found in {self.session_dir}")

        probes.sort(key=lambda t: t[0])
        return [p for _, p in probes]

    def validate_probe(self, probe: ProbeInfo) -> list[str]:
        """Validate data integrity for a single probe.

        Checks:
        - .ap.bin and .ap.meta exist
        - .ap.bin file size matches ``fileSizeBytes`` in .ap.meta
        - .ap.meta contains required fields (imSampRate, nSavedChans)

        Args:
            probe: ProbeInfo to validate.

        Returns:
            List of warning messages (empty list means validation passed).
        """
        warnings: list[str] = []

        if not probe.ap_bin.exists():
            warnings.append(f"ap.bin not found: {probe.ap_bin}")

        if not probe.ap_meta.exists():
            warnings.append(f"ap.meta not found: {probe.ap_meta}")
            return warnings  # Can't check further without meta

        meta = self.parse_meta(probe.ap_meta)

        # Size check (only if both bin exists and meta has fileSizeBytes)
        if probe.ap_bin.exists() and "fileSizeBytes" in meta:
            expected = int(meta["fileSizeBytes"])
            actual = probe.ap_bin.stat().st_size
            if actual != expected:
                warnings.append(
                    f"ap.bin size mismatch: expected {expected} bytes, got {actual} bytes"
                )

        # Required field checks
        for field in ("imSampRate", "nSavedChans"):
            if field not in meta:
                warnings.append(f"Required meta field missing: {field}")

        return warnings

    def discover_nidq(self) -> tuple[Path, Path]:
        """Locate the NIDQ .bin and .meta files in session_dir.

        Returns:
            Tuple of (nidq_bin_path, nidq_meta_path).

        Raises:
            DiscoverError: If NIDQ files are not found.
        """
        nidq_bins = list(self.session_dir.glob("*.nidq.bin"))
        if not nidq_bins:
            raise DiscoverError(f"No .nidq.bin file found in {self.session_dir}")

        nidq_bin = nidq_bins[0]
        nidq_meta = nidq_bin.parent / nidq_bin.name.replace(".nidq.bin", ".nidq.meta")
        if not nidq_meta.exists():
            raise DiscoverError(f"No .nidq.meta file found alongside {nidq_bin}")

        return nidq_bin, nidq_meta

    def parse_meta(self, meta_path: Path) -> dict[str, str]:
        """Parse a SpikeGLX .meta file into a key-value dict.

        Meta files are INI-like: ``key=value`` pairs, one per line.

        Args:
            meta_path: Path to the .meta file.

        Returns:
            Dict mapping field names to their string values.

        Raises:
            FileNotFoundError: If meta_path does not exist.
        """
        result: dict[str, str] = {}
        for line in meta_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip()
        return result


class SpikeGLXLoader:
    """Loads SpikeGLX recordings as SpikeInterface lazy Recording objects.

    All returned Recording objects are lazy — no data is read into memory
    until explicitly requested via chunk-based iteration.
    """

    @staticmethod
    def load_ap(probe: ProbeInfo) -> si.BaseRecording:
        """Load the AP recording for a probe as a lazy SpikeInterface Recording.

        Uses ``spikeinterface.extractors.read_spikeglx()`` with the probe's
        ap_bin directory. The Recording object stores only file pointers.

        Args:
            probe: ProbeInfo with ap_bin and ap_meta paths populated.

        Returns:
            Lazy SpikeInterface BaseRecording for the AP stream.
        """
        stream_name = f"{probe.probe_id}.ap"
        return se.read_spikeglx(
            probe.ap_bin.parent,
            stream_name=stream_name,
            load_sync_channel=True,
        )

    @staticmethod
    def load_nidq(nidq_bin: Path, nidq_meta: Path) -> si.BaseRecording:
        """Load the NIDQ recording as a lazy SpikeInterface Recording.

        Args:
            nidq_bin: Path to the NIDQ .bin file.
            nidq_meta: Path to the NIDQ .meta file.

        Returns:
            Lazy SpikeInterface BaseRecording for the NIDQ stream.
        """
        return se.read_spikeglx(nidq_bin.parent, stream_name="nidq")

    @staticmethod
    def load_preprocessed(recording_path: Path) -> si.BaseRecording:
        """Load a preprocessed Zarr recording from disk.

        Args:
            recording_path: Path to the Zarr directory written by preprocess stage.

        Returns:
            Lazy SpikeInterface BaseRecording (Zarr-backed).
        """
        return si.load(recording_path)

    @staticmethod
    def extract_sync_edges(
        recording: si.BaseRecording,
        sync_bit: int,
        sample_rate: float,
    ) -> list[float]:
        """Extract rising-edge times of the sync pulse from a digital channel.

        Reads the sync bit from the digital channel, computes rising edges via
        numpy.diff, and converts sample indices to seconds.

        Args:
            recording: A SpikeInterface Recording that has digital channels.
            sync_bit: Bit index of the sync pulse in the digital channel.
            sample_rate: Recording sample rate in Hz (read from meta, not hardcoded).

        Returns:
            List of sync pulse rising-edge times in seconds.
        """
        raw = recording.get_traces()
        digital = (raw.flatten().astype(np.uint16) >> sync_bit) & 1
        diff = np.diff(digital.astype(np.int8))
        rising_indices = np.where(diff == 1)[0] + 1
        return (rising_indices / sample_rate).tolist()
