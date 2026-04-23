"""CLI thin-shell entry point for pynpxpipe.

This module is the ONLY place where click is imported. All business logic
lives in core/, io/, stages/, and pipelines/. The CLI simply parses arguments
and delegates to PipelineRunner.

No print() calls for business information — click's echo is used only for
CLI-specific messages (help text, immediate error feedback).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from pynpxpipe.core.checkpoint import CheckpointManager
from pynpxpipe.core.config import load_pipeline_config, load_sorting_config, load_subject_config
from pynpxpipe.core.errors import PynpxpipeError
from pynpxpipe.core.session import SessionManager
from pynpxpipe.pipelines.runner import STAGE_ORDER, PipelineRunner

_PER_PROBE_STAGES = {"preprocess", "sort", "curate", "postprocess"}


class _CliProgressBar:
    """Tqdm-based progress sink for PipelineRunner.progress_callback.

    Renders one bar per stage (stage boundary detected from the ``stage:msg``
    prefix). Writes to stderr so stdout stays clean for scripting, and so
    Phase 3's long append/verify messages appear inline with the structlog
    stderr stream the UI log viewer also captures.
    """

    def __init__(self) -> None:
        from tqdm import tqdm as _tqdm

        self._tqdm = _tqdm
        self._bar = None
        self._current_stage: str | None = None

    def __call__(self, message: str, fraction: float) -> None:
        stage, _, human = message.partition(":")
        if stage != self._current_stage:
            self._close()
            self._bar = self._tqdm(
                total=100,
                desc=f"[{stage}]",
                leave=True,
                dynamic_ncols=True,
            )
            self._current_stage = stage
        pct = max(0, min(100, int(fraction * 100)))
        # tqdm's update() is cumulative; set n directly and refresh.
        assert self._bar is not None
        self._bar.n = pct
        postfix = human.strip()[:80] if human else ""
        if postfix:
            self._bar.set_postfix_str(postfix, refresh=False)
        self._bar.refresh()

    def _close(self) -> None:
        if self._bar is not None:
            try:
                self._bar.n = self._bar.total
                self._bar.refresh()
            except Exception:  # noqa: BLE001
                pass
            self._bar.close()
            self._bar = None

    def close(self) -> None:
        self._close()


@click.group()
@click.version_option()
def cli() -> None:
    """pynpxpipe — Neural electrophysiology preprocessing pipeline.

    Process SpikeGLX recordings through the full pipeline:
    discover → preprocess → sort → synchronize → curate → postprocess → export
    """


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("bhv_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--subject",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to the subject YAML file (e.g. monkeys/MaoDan.yaml).",
)
@click.option(
    "--output-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for processed data.",
)
@click.option(
    "--pipeline-config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("config/pipeline.yaml"),
    show_default=True,
    help="Path to pipeline.yaml configuration file.",
)
@click.option(
    "--sorting-config",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=Path("config/sorting.yaml"),
    show_default=True,
    help="Path to sorting.yaml configuration file.",
)
@click.option(
    "--stages",
    multiple=True,
    type=click.Choice(STAGE_ORDER),
    help="Run only specific stages (can be repeated). Default: all stages.",
)
def run(
    session_dir: Path,
    bhv_file: Path,
    subject: Path,
    output_dir: Path,
    pipeline_config: Path,
    sorting_config: Path,
    stages: tuple[str, ...],
) -> None:
    """Run the pipeline for SESSION_DIR with behavioral file BHV_FILE.

    SESSION_DIR: Root directory of the SpikeGLX recording.\n
    BHV_FILE: Path to the MonkeyLogic .bhv2 behavioral file.
    """
    try:
        subject_config = load_subject_config(subject)
        session = SessionManager.create(
            session_dir=session_dir,
            bhv_file=bhv_file,
            subject=subject_config,
            output_dir=output_dir,
        )
        pipeline_cfg = load_pipeline_config(pipeline_config)
        sorting_cfg = load_sorting_config(sorting_config)
        progress = _CliProgressBar()
        try:
            runner = PipelineRunner(session, pipeline_cfg, sorting_cfg, progress_callback=progress)
            runner.run(stages=list(stages) if stages else None)
        finally:
            progress.close()
        click.echo(f"Pipeline complete. Output: {output_dir}")
        click.echo("✅ Safe to exit — NWB file written and verified.")
    except PynpxpipeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(2)


@cli.command()
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def status(output_dir: Path) -> None:
    """Show the pipeline status for an existing output directory.

    OUTPUT_DIR: The output directory of a previous or in-progress pipeline run.
    """
    session_info_path = output_dir / "session_info.json"
    probe_ids: list[str] = []
    if session_info_path.exists():
        try:
            session_info = json.loads(session_info_path.read_text(encoding="utf-8"))
            probe_ids = session_info.get("probe_ids", [])
        except Exception:  # noqa: BLE001
            pass

    cp_dir = output_dir / "checkpoints"
    stage_statuses: dict[str, str] = {}
    for stage_name in STAGE_ORDER:
        stage_statuses[stage_name] = _get_stage_status(cp_dir, stage_name, probe_ids)

    click.echo(f"Pipeline status: {output_dir}\n")
    for stage_name, status_str in stage_statuses.items():
        if status_str == "completed":
            icon = "✓"
        elif status_str == "failed":
            icon = "✗"
        else:
            icon = "-"
        click.echo(f"  {stage_name:<15}{icon} {status_str}")


@cli.command()
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("stage", type=click.Choice(STAGE_ORDER))
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
def reset_stage(output_dir: Path, stage: str, yes: bool) -> None:
    """Delete the checkpoint for STAGE to force it to re-run.

    OUTPUT_DIR: The session output directory.\n
    STAGE: Name of the stage to reset.
    """
    if not yes:
        click.confirm(
            f"Reset stage '{stage}' (will delete {stage} checkpoint and per-probe checkpoints)?",
            abort=True,
        )

    checkpoint_manager = CheckpointManager(output_dir)
    checkpoint_manager.clear(stage)

    if stage in _PER_PROBE_STAGES:
        cp_dir = output_dir / "checkpoints"
        for probe_cp in cp_dir.glob(f"{stage}_*.json"):
            probe_cp.unlink(missing_ok=True)

    click.echo("Reset complete.")


@cli.command("verify-safe-to-delete")
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def verify_safe_to_delete(session_dir: Path) -> None:
    """Report whether the raw SpikeGLX bins for SESSION_DIR can be deleted.

    Exit code 0 means the export checkpoint carries ``raw_data_verified_at``
    AND the NWB opens cleanly — the raw .bin/.meta files are redundant. Any
    other exit code indicates the check failed (see ``pipelines/verify.py``
    for the full code table).

    SESSION_DIR: Pipeline output directory with checkpoints/export.json.
    """
    from pynpxpipe.pipelines.verify import verify_safe_to_delete as _verify

    result = _verify(session_dir)
    if result.safe:
        click.echo("Safe to delete:")
        for path in result.deletable:
            click.echo(f"  {path}")
        sys.exit(result.exit_code)
    else:
        click.echo(f"ERROR: {result.reason}", err=True)
        sys.exit(result.exit_code)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_stage_status(cp_dir: Path, stage_name: str, probe_ids: list[str]) -> str:
    """Compute the display status for one stage from checkpoint files."""
    stage_cp = cp_dir / f"{stage_name}.json"
    if stage_cp.exists():
        try:
            data = json.loads(stage_cp.read_text(encoding="utf-8"))
            return data.get("status", "pending")
        except Exception:  # noqa: BLE001
            pass

    if stage_name not in _PER_PROBE_STAGES or not probe_ids:
        return "pending"

    n_probes = len(probe_ids)
    completed = 0
    for probe_id in probe_ids:
        probe_cp = cp_dir / f"{stage_name}_{probe_id}.json"
        if probe_cp.exists():
            try:
                data = json.loads(probe_cp.read_text(encoding="utf-8"))
                if data.get("status") == "completed":
                    completed += 1
                elif data.get("status") == "failed":
                    return "failed"
            except Exception:  # noqa: BLE001
                pass

    if completed == 0:
        return "pending"
    if completed == n_probes:
        return "completed"
    return f"partial ({completed}/{n_probes} probes)"
