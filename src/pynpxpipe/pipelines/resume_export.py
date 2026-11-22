"""Recover a segmented export without preparing or invalidating an upstream run."""

import json
from pathlib import Path

import pandas as pd

from pynpxpipe.core.checkpoint import CheckpointManager
from pynpxpipe.core.config import load_pipeline_config, load_sorting_config
from pynpxpipe.core.logging import setup_logging
from pynpxpipe.core.run_signature import input_signature
from pynpxpipe.core.segments import SegmentManifest
from pynpxpipe.core.session import SessionManager
from pynpxpipe.io.segmented_nwb import resolve_source_stimuli
from pynpxpipe.stages.export import ExportStage


def resume_export(
    output_dir: Path, vaults=(), *, recorded_vaults=(), check_only=False, progress_callback=None
) -> Path:
    """Check or export without calling PipelineRunner; return the NWB destination."""
    root = output_dir.resolve(strict=True)
    session = SessionManager.load(root)
    if root != session.output_dir.resolve():
        raise ValueError(f"Use the original output directory: {session.output_dir}")
    for name in ("used_pipeline.yaml", "used_sorting.yaml", "checkpoints/postprocess.json"):
        if not (root / name).is_file():
            raise ValueError(f"Cannot resume without {name}")
    session.config = load_pipeline_config(root / "used_pipeline.yaml")
    if not session.segmented or not session.probes:
        raise ValueError("resume-export requires a saved segmented session with discovered probes")
    manifest = SegmentManifest.load(root / "03_segments" / "segments.json")
    signature = json.loads((root / "input_signature.json").read_text(encoding="utf-8"))["signature"]
    configs = load_sorting_config(root / "used_sorting.yaml")
    if not signature or manifest.input_signature != signature:
        raise ValueError("Saved selection does not match input_signature.json")
    original_roots = session.subject.image_vault_paths
    if input_signature(session, session.config, configs) != signature:
        # Older session.json omitted the original vault roots from the subject.
        session.subject.image_vault_paths = list(recorded_vaults or vaults)
        if (
            not session.subject.image_vault_paths
            or input_signature(session, session.config, configs) != signature
        ):
            raise ValueError(
                "Inputs/config changed, or the old session omitted its vault roots. "
                "For an old session supply --recorded-vault for each original vault path in order."
            )
    session.subject.image_vault_paths = list(dict.fromkeys([*vaults, *original_roots]))
    session.input_signature = signature
    checkpoints = CheckpointManager(root)

    def require_postprocess(probe=None):
        cp = checkpoints.read("postprocess", probe) or {}
        if cp.get("status") != "completed" or cp.get("input_signature") != signature:
            raise ValueError(
                f"Missing matching completed postprocess checkpoint: {probe or 'session'}"
            )
        return cp

    require_postprocess()
    for probe in session.probes:
        cp = require_postprocess(probe.probe_id)
        analyzer = root / "06_postprocessed" / probe.probe_id / "recording_info"
        if cp["n_units"] and not analyzer.is_dir():
            raise ValueError(f"Missing postprocessed analyzer: {analyzer.parent}")
    export_cp = checkpoints.read("export") or {}
    path = root / f"{session.session_id.canonical()}.nwb"
    if (
        export_cp.get("status") == "completed"
        and export_cp.get("input_signature") == signature
        and not path.is_file()
    ):
        raise ValueError(f"Export marked complete but NWB is absent: {path}")
    if check_only:
        events = pd.read_parquet(root / "04_sync" / "behavior_events.parquet")
        resolve_source_stimuli(session, events)
        return path
    setup_logging(session.log_path)
    ExportStage(session, progress_callback=progress_callback).run()
    return path
