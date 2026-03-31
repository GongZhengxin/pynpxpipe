"""SpikeGLX data discovery and lazy loading.

Handles multi-probe SpikeGLX recording folders. No UI dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import spikeinterface.core as si
    from pynpxpipe.core.session import ProbeInfo


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
        raise NotImplementedError("TODO")

    def discover_probes(self) -> list[ProbeInfo]:
        """Scan session_dir for all imec{N} probe directories.

        Reads each probe's .ap.meta to extract sample_rate, n_channels, probe_type,
        and serial_number. Does NOT load .bin data.

        Returns:
            List of ProbeInfo objects sorted by probe index (imec0 first).

        Raises:
            DiscoverError: If no imec directories are found.
        """
        raise NotImplementedError("TODO")

    def validate_probe(self, probe: "ProbeInfo") -> list[str]:
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
        raise NotImplementedError("TODO")

    def discover_nidq(self) -> tuple[Path, Path]:
        """Locate the NIDQ .bin and .meta files in session_dir.

        Returns:
            Tuple of (nidq_bin_path, nidq_meta_path).

        Raises:
            DiscoverError: If NIDQ files are not found.
        """
        raise NotImplementedError("TODO")

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
        raise NotImplementedError("TODO")


class SpikeGLXLoader:
    """Loads SpikeGLX recordings as SpikeInterface lazy Recording objects.

    All returned Recording objects are lazy — no data is read into memory
    until explicitly requested via chunk-based iteration.
    """

    @staticmethod
    def load_ap(probe: "ProbeInfo") -> "si.BaseRecording":
        """Load the AP recording for a probe as a lazy SpikeInterface Recording.

        Uses ``spikeinterface.extractors.read_spikeglx()`` with the probe's
        ap_bin directory. The Recording object stores only file pointers.

        Args:
            probe: ProbeInfo with ap_bin and ap_meta paths populated.

        Returns:
            Lazy SpikeInterface BaseRecording for the AP stream.

        Raises:
            FileNotFoundError: If probe.ap_bin does not exist.
        """
        raise NotImplementedError("TODO")

    @staticmethod
    def load_nidq(nidq_bin: Path, nidq_meta: Path) -> "si.BaseRecording":
        """Load the NIDQ recording as a lazy SpikeInterface Recording.

        Args:
            nidq_bin: Path to the NIDQ .bin file.
            nidq_meta: Path to the NIDQ .meta file.

        Returns:
            Lazy SpikeInterface BaseRecording for the NIDQ stream.
        """
        raise NotImplementedError("TODO")

    @staticmethod
    def load_preprocessed(recording_path: Path) -> "si.BaseRecording":
        """Load a preprocessed Zarr recording from disk.

        Args:
            recording_path: Path to the Zarr directory written by preprocess stage.

        Returns:
            Lazy SpikeInterface BaseRecording (Zarr-backed).

        Raises:
            FileNotFoundError: If recording_path does not exist.
        """
        raise NotImplementedError("TODO")

    @staticmethod
    def extract_sync_edges(
        recording: "si.BaseRecording",
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
        raise NotImplementedError("TODO")
