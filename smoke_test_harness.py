"""
Smoke test harness for pynpxpipe.

Usage:
    python smoke_test_harness.py preflight --session-dir <path> --config config/pipeline.yaml \\
        --sorting-config config/sorting.yaml --output-dir <path>

    python smoke_test_harness.py validate --session-dir <path> --output-dir <path> \\
        [--stop-after sort] [--no-auto-fix] [--fix-tier GREEN]
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import click

from pynpxpipe.core.config import load_pipeline_config, load_sorting_config
from pynpxpipe.core.session import SessionManager
from pynpxpipe.harness.classifier import Classifier
from pynpxpipe.harness.fixers import Fixer
from pynpxpipe.harness.preflight import CheckResult, PreflightChecker, StageResult
from pynpxpipe.harness.reporter import Reporter
from pynpxpipe.harness.validators import VALIDATORS
from pynpxpipe.pipelines.runner import STAGE_ORDER, PipelineRunner

_BATCH_SIZE_TIERS = [60000, 40000, 30000, 20000]


@click.group()
def cli() -> None:
    """pynpxpipe developer debugging harness."""


@cli.command()
@click.option("--session-dir", required=True, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--config",
    "config_path",
    default="config/pipeline.yaml",
    type=click.Path(path_type=Path),
)
@click.option(
    "--sorting-config",
    "sorting_config_path",
    default="config/sorting.yaml",
    type=click.Path(path_type=Path),
)
@click.option("--output-dir", required=True, type=click.Path(path_type=Path))
@click.option(
    "--no-auto-fix", is_flag=True, default=False, help="Disable all auto-fixes (report only)"
)
@click.option(
    "--fix-tier",
    default="GREEN",
    type=click.Choice(["GREEN", "YELLOW"]),
    help="Max auto-fix tier",
)
def preflight(
    session_dir: Path,
    config_path: Path,
    sorting_config_path: Path,
    output_dir: Path,
    no_auto_fix: bool,
    fix_tier: str,
) -> None:
    """Run pre-pipeline environment, config, and data checks."""
    harness_dir = output_dir / ".harness"
    reporter = Reporter(harness_dir)
    fixer = Fixer()

    pipeline_config = load_pipeline_config(config_path)
    sorting_config = load_sorting_config(sorting_config_path)
    checker = PreflightChecker(session_dir=session_dir, output_dir=output_dir)

    results: list[CheckResult] = []
    auto_fix_records: list[dict] = []
    auto_fixed_count = 0

    # Environment checks
    cuda_result = checker.check_cuda_vs_config(
        torch_device=sorting_config.sorter.params.torch_device
    )
    if (
        cuda_result.status == "fail"
        and cuda_result.auto_fixable
        and not no_auto_fix
        and fix_tier in ("GREEN", "YELLOW")
    ):
        record = fixer.fix_torch_device(sorting_config_path, current="cuda", target="auto")
        auto_fix_records.append(record)
        auto_fixed_count += 1
        cuda_result.fix_description = f"AUTO-FIXED: {cuda_result.fix_description}"
    results.append(cuda_result)
    results.append(checker.check_spikeinterface_version())
    results.append(checker.check_disk_space())

    # Config checks
    run_motion = pipeline_config.preprocess.motion_correction.method is not None
    motion_result = checker.check_motion_nblocks_exclusion(
        run_motion_correction=run_motion,
        nblocks=sorting_config.sorter.params.nblocks,
    )
    if motion_result.status == "fail" and motion_result.auto_fixable and not no_auto_fix:
        record = fixer.fix_disable_motion_correction(config_path)
        auto_fix_records.append(record)
        auto_fixed_count += 1
    results.append(motion_result)

    amp_result = checker.check_amplitude_cutoff_used()
    results.append(amp_result)

    curation = pipeline_config.curation
    results.append(
        checker.check_curation_threshold_ranges(
            isi_max=curation.isi_violation_ratio_max,
            amp_cutoff_max=curation.amplitude_cutoff_max,
            presence_min=curation.presence_ratio_min,
            snr_min=curation.snr_min,
        )
    )

    # Data checks
    results.extend(checker.check_data_integrity())

    # Write reports
    reporter.write_preflight_report(results, auto_fixed_count=auto_fixed_count)
    if auto_fix_records:
        reporter.write_auto_fixes(auto_fix_records)

    # Print summary
    counts = {"pass": 0, "warn": 0, "fail": 0}
    for r in results:
        counts[r.status] += 1

    click.echo(f"\n{'=' * 60}")
    click.echo(f"Preflight: {counts['pass']} PASS, {counts['warn']} WARN, {counts['fail']} FAIL")
    if auto_fixed_count:
        click.echo(f"Auto-fixed: {auto_fixed_count} issues (see {harness_dir / 'auto_fixes.json'})")
    click.echo(f"Report: {harness_dir / 'preflight_report.json'}")
    click.echo(f"{'=' * 60}\n")

    if counts["fail"] > 0:
        sys.exit(1)


@cli.command()
@click.option("--session-dir", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", required=True, type=click.Path(path_type=Path))
@click.option(
    "--config",
    "config_path",
    default="config/pipeline.yaml",
    type=click.Path(path_type=Path),
)
@click.option(
    "--sorting-config",
    "sorting_config_path",
    default="config/sorting.yaml",
    type=click.Path(path_type=Path),
)
@click.option("--bhv-file", default=None, type=click.Path(path_type=Path))
@click.option(
    "--stop-after",
    default="export",
    type=click.Choice(STAGE_ORDER),
    help="Run and validate up to this stage (inclusive)",
)
@click.option("--no-auto-fix", is_flag=True, default=False)
@click.option("--fix-tier", default="GREEN", type=click.Choice(["GREEN", "YELLOW"]))
def validate(
    session_dir: Path,
    output_dir: Path,
    config_path: Path,
    sorting_config_path: Path,
    bhv_file: Path | None,
    stop_after: str,
    no_auto_fix: bool,
    fix_tier: str,
) -> None:
    """Run pipeline stages with real data and validate outputs after each stage."""
    harness_dir = output_dir / ".harness"
    reporter = Reporter(harness_dir)
    fixer = Fixer()

    pipeline_config = load_pipeline_config(config_path)
    sorting_config = load_sorting_config(sorting_config_path)

    # Load or create session
    session_json = output_dir / "session.json"
    if session_json.exists():
        session = SessionManager.load(output_dir)
    else:
        if bhv_file is None:
            click.echo("ERROR: --bhv-file required when no session.json exists", err=True)
            sys.exit(1)
        session = SessionManager.from_data_dir(
            data_dir=session_dir.parent,
            subject=_dummy_subject(),
            output_dir=output_dir,
        )

    # Determine stages to run
    stop_idx = STAGE_ORDER.index(stop_after)
    stages_to_run = STAGE_ORDER[: stop_idx + 1]

    # Run pipeline
    runner = PipelineRunner(
        session=session,
        pipeline_config=pipeline_config,
        sorting_config=sorting_config,
    )

    stage_results: list[StageResult] = []
    run_exception: Exception | None = None
    t0 = time.monotonic()

    try:
        runner.run(stages=stages_to_run)
    except Exception as exc:
        run_exception = exc

    total_elapsed = time.monotonic() - t0

    # Validate each stage
    probe_ids = [p.probe_id for p in session.probes]
    suggested: list[dict] = []
    auto_fix_records: list[dict] = []

    for stage_name in stages_to_run:
        cp_path = output_dir / "checkpoints" / f"{stage_name}.json"
        probe_cp_exists = any(
            (output_dir / "checkpoints" / f"{stage_name}_{pid}.json").exists() for pid in probe_ids
        )

        if not cp_path.exists() and not probe_cp_exists:
            stage_results.append(_make_skipped_result(stage_name))
            continue

        # Load checkpoint status
        cp_status = "completed"
        cp_error_msg = ""
        for probe_id in probe_ids if probe_ids else [None]:  # type: ignore[assignment]
            p = (
                output_dir
                / "checkpoints"
                / (f"{stage_name}_{probe_id}.json" if probe_id else f"{stage_name}.json")
            )
            if p.exists():
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("status") == "failed":
                    cp_status = "failed"
                    cp_error_msg = data.get("error", "")
                    break

        if cp_status == "completed":
            validations = _run_validator(stage_name, output_dir, probe_ids, pipeline_config)
            result = _make_passed_result(
                stage_name, total_elapsed / len(stages_to_run), validations
            )
            # Check for zero-unit curate condition
            for v in validations:
                if v.status == "fail" and "0/" in v.detail and stage_name == "curate":
                    suggested.append(
                        {
                            "title": f"Zero good units — {v.check}",
                            "stage": stage_name,
                            "detail": v.detail,
                            "suggestion": "Relax presence_ratio_min or snr_min thresholds",
                        }
                    )
        else:
            # Failed stage — classify the error
            tb_str = traceback.format_exc() if run_exception else cp_error_msg
            exc_for_classify = run_exception or RuntimeError(cp_error_msg)
            classification = Classifier.classify(exc_for_classify, traceback_str=tb_str)

            if classification.auto_fixable and not no_auto_fix:
                if classification.error_class == "cuda_oom" and fix_tier in ("GREEN", "YELLOW"):
                    current_bs = sorting_config.sorter.params.batch_size
                    if isinstance(current_bs, int):
                        target = next((t for t in _BATCH_SIZE_TIERS if t < current_bs), 20000)
                        record = fixer.fix_batch_size(sorting_config_path, current_bs, target)
                        auto_fix_records.append(record)
                        classification.fix_applied = True
                        classification.fix_detail = f"batch_size: {current_bs} → {target}"
                elif classification.error_class == "cuda_unavailable" and fix_tier in (
                    "GREEN",
                    "YELLOW",
                ):
                    record = fixer.fix_torch_device(sorting_config_path, "cuda", "auto")
                    auto_fix_records.append(record)
                    classification.fix_applied = True
                    classification.fix_detail = "torch_device: cuda → auto"
            else:
                suggested.append(
                    {
                        "title": f"{stage_name} failed: {classification.error_class}",
                        "stage": stage_name,
                        "detail": classification.message[:200],
                        "suggestion": classification.suggestion,
                    }
                )

            result = _make_failed_result(
                stage_name, total_elapsed / len(stages_to_run), classification
            )

        stage_results.append(result)

    reporter.write_validation_report(stage_results, stop_after=stop_after)
    if suggested:
        reporter.write_suggested_fixes(suggested)
    if auto_fix_records:
        reporter.write_auto_fixes(auto_fix_records)

    # Print summary
    n_pass = sum(1 for r in stage_results if r.status == "passed")
    n_fail = sum(1 for r in stage_results if r.status == "failed")
    n_skip = sum(1 for r in stage_results if r.status == "skipped")

    click.echo(f"\n{'=' * 60}")
    click.echo(f"Validation: {n_pass} passed, {n_fail} failed, {n_skip} skipped")
    if suggested:
        click.echo(f"Suggestions: {len(suggested)} items in {harness_dir / 'suggested_fixes.md'}")
    if auto_fix_records:
        click.echo(f"Auto-fixed: {len(auto_fix_records)} (see {harness_dir / 'auto_fixes.json'})")
    click.echo(f"Report: {harness_dir / 'validation_report.json'}")
    click.echo(f"{'=' * 60}\n")

    if n_fail > 0:
        sys.exit(1)


# ── helpers ─────────────────────────────────────────────────────────────────


def _run_validator(stage_name: str, output_dir: Path, probe_ids: list[str], pipeline_config):  # type: ignore[no-untyped-def]
    validator = VALIDATORS.get(stage_name)
    if validator is None:
        return []
    if stage_name == "discover":
        return validator.validate(output_dir=output_dir, session_probes=probe_ids)
    elif stage_name in ("preprocess", "sort", "postprocess"):
        return validator.validate(output_dir=output_dir, probe_ids=probe_ids)
    elif stage_name == "synchronize":
        return validator.validate(output_dir=output_dir)
    elif stage_name == "curate":
        curation = pipeline_config.curation
        return validator.validate(
            output_dir=output_dir,
            probe_ids=probe_ids,
            config_thresholds={
                "isi_violation_ratio_max": curation.isi_violation_ratio_max,
                "amplitude_cutoff_max": curation.amplitude_cutoff_max,
                "presence_ratio_min": curation.presence_ratio_min,
                "snr_min": curation.snr_min,
            },
        )
    elif stage_name == "export":
        return validator.validate(output_dir=output_dir)
    return []


def _make_skipped_result(stage_name: str) -> StageResult:
    return StageResult(name=stage_name, status="skipped", duration_s=0.0)


def _make_passed_result(stage_name: str, duration_s: float, validations) -> StageResult:  # type: ignore[no-untyped-def]
    return StageResult(
        name=stage_name, status="passed", duration_s=duration_s, validations=validations
    )


def _make_failed_result(stage_name: str, duration_s: float, classification) -> StageResult:  # type: ignore[no-untyped-def]
    return StageResult(
        name=stage_name, status="failed", duration_s=duration_s, error=classification
    )


def _dummy_subject():  # type: ignore[no-untyped-def]
    """Create a placeholder SubjectConfig for harness use when session.json doesn't exist."""
    from pynpxpipe.core.session import SubjectConfig

    return SubjectConfig(
        subject_id="harness_subject",
        description="Auto-created by harness",
        species="Macaca mulatta",
        sex="U",
        age="P0Y",
        weight="0kg",
    )


if __name__ == "__main__":
    cli()
