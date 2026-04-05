"""Session dataclass and lifecycle management.

This module defines the core data structures that flow through the entire pipeline.
No UI dependencies: no click, no print, no sys.exit.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

_log = logging.getLogger(__name__)

_REQUIRED_KEYS = {"session_dir", "output_dir", "bhv_file", "subject", "probes", "checkpoint"}


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
    sex: str  # "M" | "F" | "U" | "O"
    age: str  # ISO 8601 duration, e.g. "P4Y"
    weight: str  # with unit, e.g. "12.8kg"


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
    config: object = field(default_factory=dict)  # PipelineConfig instance, injected by SessionManager
    probes: list[ProbeInfo] = field(default_factory=list)
    checkpoint: dict = field(default_factory=dict)
    log_path: Path = field(init=False)

    def __post_init__(self) -> None:
        self.log_path = (
            self.output_dir / "logs" / f"pynpxpipe_{self.session_dir.name}.log"
        )


class SessionManager:
    """Creates, persists, and loads Session objects from disk.

    The session state (subject info, probes, checkpoint dict) is serialized to
    ``{output_dir}/session.json`` so that a pipeline run can be resumed after
    interruption.
    """

    @staticmethod
    def from_data_dir(
        data_dir: Path,
        subject: SubjectConfig,
        output_dir: Path,
    ) -> Session:
        """Create a Session by auto-discovering session_dir and bhv_file in data_dir.

        Discovers the SpikeGLX gate folder (first ``*_g[0-9]*/`` directory) and
        the BHV2 file (first ``*.bhv2`` file). Multiple matches emit a WARNING and
        the alphabetically first is used.

        Args:
            data_dir: Root directory containing the SpikeGLX gate folder and BHV2 file.
            subject: Animal subject metadata.
            output_dir: Directory for all processed outputs (created if absent).

        Returns:
            A freshly initialized Session.

        Raises:
            FileNotFoundError: If data_dir does not exist, or no gate folder / BHV2
                file is found within it.
        """
        if not data_dir.exists():
            raise FileNotFoundError(f"data_dir does not exist: {data_dir}")

        gate_dirs = sorted(p for p in data_dir.iterdir() if p.is_dir() and _is_gate_dir(p))
        if not gate_dirs:
            raise FileNotFoundError(
                f"No *_g[0-9] directory found in {data_dir}"
            )
        if len(gate_dirs) > 1:
            _log.warning(
                "Multiple gate directories found in %s: %s — using %s",
                data_dir,
                [p.name for p in gate_dirs],
                gate_dirs[0].name,
            )
        session_dir = gate_dirs[0]

        bhv_files = sorted(data_dir.glob("*.bhv2"))
        if not bhv_files:
            raise FileNotFoundError(f"No *.bhv2 file found in {data_dir}")
        if len(bhv_files) > 1:
            _log.warning(
                "Multiple .bhv2 files found in %s: %s — using %s",
                data_dir,
                [p.name for p in bhv_files],
                bhv_files[0].name,
            )
        bhv_file = bhv_files[0]

        return SessionManager.create(session_dir, bhv_file, subject, output_dir)

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
        if not session_dir.exists():
            raise FileNotFoundError(f"session_dir does not exist: {session_dir}")
        if not bhv_file.exists():
            raise FileNotFoundError(f"bhv_file does not exist: {bhv_file}")

        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "checkpoints").mkdir(exist_ok=True)
        (output_dir / "logs").mkdir(exist_ok=True)

        session = Session(
            session_dir=session_dir,
            output_dir=output_dir,
            subject=subject,
            bhv_file=bhv_file,
        )
        SessionManager.save(session)
        return session

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
        session_json = output_dir / "session.json"
        if not session_json.exists():
            raise FileNotFoundError(f"session.json not found in {output_dir}")

        try:
            data = json.loads(session_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Corrupt session.json: {exc}") from exc

        missing = _REQUIRED_KEYS - data.keys()
        if missing:
            raise ValueError(f"session.json missing required keys: {missing}")

        subject = SubjectConfig(**data["subject"])
        probes = [_probe_from_dict(p) for p in data["probes"]]

        return Session(
            session_dir=Path(data["session_dir"]),
            output_dir=Path(data["output_dir"]),
            subject=subject,
            bhv_file=Path(data["bhv_file"]),
            probes=probes,
            checkpoint=data["checkpoint"],
        )

    @staticmethod
    def save(session: Session) -> None:
        """Persist Session state to {output_dir}/session.json.

        Called automatically by each stage after updating session fields.

        Args:
            session: The session to serialize.

        Raises:
            OSError: If the file cannot be written.
        """
        data = {
            "session_dir": str(session.session_dir),
            "output_dir": str(session.output_dir),
            "bhv_file": str(session.bhv_file),
            "subject": {
                "subject_id": session.subject.subject_id,
                "description": session.subject.description,
                "species": session.subject.species,
                "sex": session.subject.sex,
                "age": session.subject.age,
                "weight": session.subject.weight,
            },
            "probes": [_probe_to_dict(p) for p in session.probes],
            "checkpoint": session.checkpoint,
        }
        (session.output_dir / "session.json").write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _is_gate_dir(path: Path) -> bool:
    """Return True if the directory name matches the SpikeGLX gate pattern *_g[0-9]*."""
    import re
    return bool(re.search(r"_g\d+$", path.name))


def _probe_to_dict(probe: ProbeInfo) -> dict:
    return {
        "probe_id": probe.probe_id,
        "ap_bin": str(probe.ap_bin),
        "ap_meta": str(probe.ap_meta),
        "lf_bin": str(probe.lf_bin) if probe.lf_bin is not None else None,
        "lf_meta": str(probe.lf_meta) if probe.lf_meta is not None else None,
        "sample_rate": probe.sample_rate,
        "n_channels": probe.n_channels,
        "probe_type": probe.probe_type,
        "serial_number": probe.serial_number,
        "channel_positions": (
            [list(pos) for pos in probe.channel_positions]
            if probe.channel_positions is not None
            else None
        ),
    }


def _probe_from_dict(d: dict) -> ProbeInfo:
    channel_positions = d.get("channel_positions")
    if channel_positions is not None:
        channel_positions = [tuple(pos) for pos in channel_positions]
    return ProbeInfo(
        probe_id=d["probe_id"],
        ap_bin=Path(d["ap_bin"]),
        ap_meta=Path(d["ap_meta"]),
        lf_bin=Path(d["lf_bin"]) if d.get("lf_bin") is not None else None,
        lf_meta=Path(d["lf_meta"]) if d.get("lf_meta") is not None else None,
        sample_rate=d["sample_rate"],
        n_channels=d["n_channels"],
        probe_type=d["probe_type"],
        serial_number=d["serial_number"],
        channel_positions=channel_positions,
    )
