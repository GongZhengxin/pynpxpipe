"""CLI thin-shell entry point for pynpxpipe.

This module is the ONLY place where click is imported. All business logic
lives in core/, io/, stages/, and pipelines/. The CLI simply parses arguments
and delegates to PipelineRunner.

No print() calls for business information — click's echo is used only for
CLI-specific messages (help text, immediate error feedback).
"""

from __future__ import annotations

from pathlib import Path

import click

from pynpxpipe.core.config import load_pipeline_config, load_sorting_config, load_subject_config
from pynpxpipe.core.session import SessionManager
from pynpxpipe.pipelines.runner import PipelineRunner, STAGE_ORDER


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
    raise NotImplementedError("TODO")


@cli.command()
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def status(output_dir: Path) -> None:
    """Show the pipeline status for an existing output directory.

    OUTPUT_DIR: The output directory of a previous or in-progress pipeline run.
    """
    raise NotImplementedError("TODO")


@cli.command()
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("stage", type=click.Choice(STAGE_ORDER))
def reset_stage(output_dir: Path, stage: str) -> None:
    """Delete the checkpoint for STAGE to force it to re-run.

    OUTPUT_DIR: The session output directory.\n
    STAGE: Name of the stage to reset.
    """
    raise NotImplementedError("TODO")
