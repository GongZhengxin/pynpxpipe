"""Input/config signatures and reversible retirement of stale derived outputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pynpxpipe.core.config import PipelineConfig, SortingConfig
    from pynpxpipe.core.session import Session

# Version 2 anchors full trials to matching BHV/NIDQ events. Version 3 excludes
# stimulus-free trials from segmented selections and their downstream outputs.
_SIGNATURE_VERSION = 3


def input_signature(
    session: Session, pipeline_config: PipelineConfig, sorting_config: SortingConfig
) -> str:
    """Fingerprint pairing, source stats/metadata and scientifically relevant config."""
    sources = []
    for source in session.recording_sources:
        # Match the acquisition layout used by discovery. Recursive scans also
        # include sorter binaries and retired outputs when output_dir is nested.
        files = [source.bhv_file]
        for extension in ("meta", "bin"):
            files.extend(sorted(source.session_dir.glob(f"*.nidq.{extension}")))
            for stream in ("ap", "lf"):
                files.extend(sorted(source.session_dir.glob(f"*_imec*/*.{stream}.{extension}")))
        info = []
        for path in files:
            stat = path.stat()
            entry = [str(path.resolve()), stat.st_size, stat.st_mtime_ns]
            if path.suffix == ".meta":
                entry.append(hashlib.sha256(path.read_bytes()).hexdigest())
            info.append(entry)
        sources.append(
            {"source_id": source.source_id, "start_offset_s": source.start_offset_s, "files": info}
        )
    config = asdict(pipeline_config)
    config.pop("resources", None)
    config.pop("parallel", None)
    raw = {
        "version": _SIGNATURE_VERSION,
        "sources": sources,
        "config": config,
        "sorting": asdict(sorting_config),
        "subject": asdict(session.subject),
        "session_id": session.session_id.to_dict(),
        "probes": session.probe_plan,
    }
    return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()


def prepare_run(
    session: Session, pipeline_config: PipelineConfig, sorting_config: SortingConfig
) -> None:
    """Archive stale generated results before permitting checkpoint/cache reuse.

    Archives stay on the output volume. Original acquisitions are never moved.
    """
    marker = session.output_dir / "input_signature.json"
    if not session.segmented and not marker.exists():
        return
    signature = input_signature(session, pipeline_config, sorting_config)
    previous = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
    if previous.get("signature") != signature:
        root = session.output_dir.resolve()
        names = [
            "checkpoints",
            "sources",
            "session_info.json",
            "01_preprocessed",
            "02_sorted",
            "02_sorter_output_KS4",
            "03_merged",
            "03_segments",
            "04_sync",
            "05_curated",
            "06_postprocessed",
            "07_derivatives",
            "07_export",
            "08_nwb",
            f"{session.session_id.canonical()}.nwb",
        ]
        candidates = [(root / name).resolve() for name in names if (root / name).exists()]
        for path in candidates:
            if not path.is_relative_to(root):
                raise ValueError("Generated output escapes output_dir")
            for source in session.recording_sources:
                for original in (source.session_dir.resolve(), source.bhv_file.resolve()):
                    if original == path or original.is_relative_to(path):
                        raise ValueError(
                            "Output layout overlaps raw source files; choose a separate output directory"
                        )
        if candidates:
            archive = root / ".invalidated" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
            archive.mkdir(parents=True)
            for path in candidates:
                path.rename(archive / path.name)
        session.probes = []
        for source in session.recordings:
            source.probes = []
        session.checkpoint = {}
    marker.write_text(json.dumps({"signature": signature}), encoding="utf-8")
    session.input_signature = signature
