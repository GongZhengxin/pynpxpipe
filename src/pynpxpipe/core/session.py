"""Session dataclass and lifecycle management.

This module defines the core data structures that flow through the entire pipeline.
No UI dependencies: no click, no print, no sys.exit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SubjectConfig:
    """Animal subject metadata following DANDI archive standards.

    Attributes:
        subject_id: Unique identifier for the subject, required by DANDI.
        description: Free-form description of the subject.
        species: Species name in binomial nomenclature, required by DANDI.
        sex: Biological sex: "M" (male), "F" (female), "U" (unknown), "O" (other).
        age: Age in ISO 8601 duration format (e.g. "P4Y" for 4 years), required by DANDI.
        weight: Body weight including unit (e.g. "12.8kg").
    """

    subject_id: str
    description: str
    species: str
    sex: str       # "M" | "F" | "U" | "O"
    age: str       # ISO 8601 duration, e.g. "P4Y"
    weight: str    # with unit, e.g. "12.8kg"


@dataclass
class ProbeInfo:
    """Metadata for a single IMEC probe discovered by the discover stage.

    Attributes:
        probe_id: SpikeGLX probe identifier, e.g. "imec0", "imec1".
        ap_bin: Path to the AP .bin file.
        ap_meta: Path to the AP .meta file.
        lf_bin: Path to the LF .bin file, or None if not present.
        lf_meta: Path to the LF .meta file, or None if not present.
        sample_rate: AP sampling rate in Hz (read from meta).
        n_channels: Number of saved channels (read from meta).
        probe_type: Probe model/type string (read from meta, e.g. "NP1010").
        serial_number: Probe serial number (read from meta).
        channel_positions: Array of (x, y) channel positions in micrometers,
            shape (n_channels, 2). None until populated by discover stage.
    """

    probe_id: str
    ap_bin: Path
    ap_meta: Path
    lf_bin: Path | None
    lf_meta: Path | None
    sample_rate: float
    n_channels: int
    probe_type: str
    serial_number: str
    channel_positions: list[tuple[float, float]] | None = None


@dataclass
class Session:
    """Central state object passed through all pipeline stages.

    Attributes:
        session_dir: Root directory of the SpikeGLX recording.
        output_dir: Directory where all processed outputs are written.
        subject: Animal subject metadata loaded from monkeys/*.yaml.
        bhv_file: Path to the MonkeyLogic BHV2 behavioral data file.
        probes: List of IMEC probes, populated by the discover stage.
        checkpoint: Per-stage completion status, keyed by stage name.
        log_path: Path to the structured JSON Lines log file.
    """

    session_dir: Path
    output_dir: Path
    subject: SubjectConfig
    bhv_file: Path
    probes: list[ProbeInfo] = field(default_factory=list)
    checkpoint: dict = field(default_factory=dict)
    log_path: Path = field(init=False)

    def __post_init__(self) -> None:
        raise NotImplementedError("TODO")


class SessionManager:
    """Creates, persists, and loads Session objects from disk.

    The session state (subject info, probes, checkpoint dict) is serialized to
    ``{output_dir}/session.json`` so that a pipeline run can be resumed after
    interruption.
    """

    @staticmethod
    def create(
        session_dir: Path,
        bhv_file: Path,
        subject: SubjectConfig,
        output_dir: Path,
    ) -> Session:
        """Create a new Session and initialize the output directory structure.

        Args:
            session_dir: Root directory of the SpikeGLX recording.
            bhv_file: Path to the MonkeyLogic BHV2 file.
            subject: Animal subject metadata.
            output_dir: Directory for all processed outputs (created if absent).

        Returns:
            A freshly initialized Session with empty probes and checkpoint.

        Raises:
            FileNotFoundError: If session_dir or bhv_file does not exist.
            OSError: If output_dir cannot be created.
        """
        raise NotImplementedError("TODO")

    @staticmethod
    def load(output_dir: Path) -> Session:
        """Load a Session from a previously saved session.json.

        Args:
            output_dir: Output directory of an earlier pipeline run.

        Returns:
            Session with probes, checkpoint, and subject restored from disk.

        Raises:
            FileNotFoundError: If output_dir/session.json does not exist.
            ValueError: If session.json is corrupt or missing required fields.
        """
        raise NotImplementedError("TODO")

    @staticmethod
    def save(session: Session) -> None:
        """Persist Session state to {output_dir}/session.json.

        Called automatically by each stage after updating session fields.

        Args:
            session: The session to serialize.

        Raises:
            OSError: If the file cannot be written.
        """
        raise NotImplementedError("TODO")
