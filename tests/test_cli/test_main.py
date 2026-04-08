"""Tests for cli/main.py — pynpxpipe CLI.

Groups:
  A. run command       — success, error handling, stages option, required options
  B. status command    — output format for completed/pending/failed stages
  C. reset-stage cmd   — checkpoint deletion, --yes flag, confirmation prompt
  D. Architecture      — click not imported in business layer, no sys.exit in business layer
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from pynpxpipe.cli.main import cli
from pynpxpipe.core.errors import DiscoverError

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Return (session_dir, bhv_file, subject_yaml, output_dir)."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    subject_yaml = tmp_path / "subject.yaml"
    subject_yaml.write_text(
        "Subject:\n"
        "  subject_id: TestMon\n"
        "  description: test monkey\n"
        "  species: Macaca mulatta\n"
        "  sex: M\n"
        "  age: P3Y\n"
        "  weight: 10kg\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "output"
    return session_dir, bhv_file, subject_yaml, output_dir


def _make_config_files(tmp_path: Path) -> tuple[Path, Path]:
    """Create minimal pipeline.yaml and sorting.yaml."""
    pipeline_yaml = tmp_path / "pipeline.yaml"
    pipeline_yaml.write_text("{}\n", encoding="utf-8")
    sorting_yaml = tmp_path / "sorting.yaml"
    sorting_yaml.write_text("{}\n", encoding="utf-8")
    return pipeline_yaml, sorting_yaml


def _make_output_dir(tmp_path: Path, stage_statuses: dict | None = None) -> Path:
    """Create an output_dir with session_info.json and optional checkpoints."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    session_info = {"probe_ids": ["imec0", "imec1"]}
    (output_dir / "session_info.json").write_text(json.dumps(session_info), encoding="utf-8")
    if stage_statuses:
        cp_dir = output_dir / "checkpoints"
        cp_dir.mkdir()
        for stage, status in stage_statuses.items():
            (cp_dir / f"{stage}.json").write_text(
                json.dumps({"stage": stage, "status": status}), encoding="utf-8"
            )
    return output_dir


# ---------------------------------------------------------------------------
# Group A — run command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_run_success_exits_zero(self, tmp_path: Path) -> None:
        """Successful run exits with code 0."""
        session_dir, bhv_file, subject_yaml, output_dir = _make_files(tmp_path)
        pipeline_yaml, sorting_yaml = _make_config_files(tmp_path)

        runner = CliRunner()
        with (
            patch("pynpxpipe.cli.main.SessionManager") as mock_sm,
            patch("pynpxpipe.cli.main.load_pipeline_config") as mock_lpc,
            patch("pynpxpipe.cli.main.load_sorting_config") as mock_lsc,
            patch("pynpxpipe.cli.main.load_subject_config") as mock_lsub,
            patch("pynpxpipe.cli.main.PipelineRunner") as mock_runner_cls,
        ):
            mock_sm.create.return_value = MagicMock()
            mock_lpc.return_value = MagicMock()
            mock_lsc.return_value = MagicMock()
            mock_lsub.return_value = MagicMock()
            mock_runner_cls.return_value.run.return_value = None

            result = runner.invoke(
                cli,
                [
                    "run",
                    str(session_dir),
                    str(bhv_file),
                    "--subject",
                    str(subject_yaml),
                    "--output-dir",
                    str(output_dir),
                    "--pipeline-config",
                    str(pipeline_yaml),
                    "--sorting-config",
                    str(sorting_yaml),
                ],
            )

        assert result.exit_code == 0

    def test_run_outputs_complete_message(self, tmp_path: Path) -> None:
        """Output contains 'Pipeline complete' on success."""
        session_dir, bhv_file, subject_yaml, output_dir = _make_files(tmp_path)
        pipeline_yaml, sorting_yaml = _make_config_files(tmp_path)

        runner = CliRunner()
        with (
            patch("pynpxpipe.cli.main.SessionManager"),
            patch("pynpxpipe.cli.main.load_pipeline_config"),
            patch("pynpxpipe.cli.main.load_sorting_config"),
            patch("pynpxpipe.cli.main.load_subject_config"),
            patch("pynpxpipe.cli.main.PipelineRunner") as mock_runner_cls,
        ):
            mock_runner_cls.return_value.run.return_value = None

            result = runner.invoke(
                cli,
                [
                    "run",
                    str(session_dir),
                    str(bhv_file),
                    "--subject",
                    str(subject_yaml),
                    "--output-dir",
                    str(output_dir),
                    "--pipeline-config",
                    str(pipeline_yaml),
                    "--sorting-config",
                    str(sorting_yaml),
                ],
            )

        assert "Pipeline complete" in result.output

    def test_run_pynpxpipe_error_exits_one(self, tmp_path: Path) -> None:
        """PynpxpipeError from runner exits with code 1."""
        session_dir, bhv_file, subject_yaml, output_dir = _make_files(tmp_path)
        pipeline_yaml, sorting_yaml = _make_config_files(tmp_path)

        runner = CliRunner()
        with (
            patch("pynpxpipe.cli.main.SessionManager"),
            patch("pynpxpipe.cli.main.load_pipeline_config"),
            patch("pynpxpipe.cli.main.load_sorting_config"),
            patch("pynpxpipe.cli.main.load_subject_config"),
            patch("pynpxpipe.cli.main.PipelineRunner") as mock_runner_cls,
        ):
            mock_runner_cls.return_value.run.side_effect = DiscoverError("no probes")

            result = runner.invoke(
                cli,
                [
                    "run",
                    str(session_dir),
                    str(bhv_file),
                    "--subject",
                    str(subject_yaml),
                    "--output-dir",
                    str(output_dir),
                    "--pipeline-config",
                    str(pipeline_yaml),
                    "--sorting-config",
                    str(sorting_yaml),
                ],
            )

        assert result.exit_code == 1

    def test_run_unexpected_error_exits_two(self, tmp_path: Path) -> None:
        """Unexpected RuntimeError exits with code 2."""
        session_dir, bhv_file, subject_yaml, output_dir = _make_files(tmp_path)
        pipeline_yaml, sorting_yaml = _make_config_files(tmp_path)

        runner = CliRunner()
        with (
            patch("pynpxpipe.cli.main.SessionManager"),
            patch("pynpxpipe.cli.main.load_pipeline_config"),
            patch("pynpxpipe.cli.main.load_sorting_config"),
            patch("pynpxpipe.cli.main.load_subject_config"),
            patch("pynpxpipe.cli.main.PipelineRunner") as mock_runner_cls,
        ):
            mock_runner_cls.return_value.run.side_effect = RuntimeError("boom")

            result = runner.invoke(
                cli,
                [
                    "run",
                    str(session_dir),
                    str(bhv_file),
                    "--subject",
                    str(subject_yaml),
                    "--output-dir",
                    str(output_dir),
                    "--pipeline-config",
                    str(pipeline_yaml),
                    "--sorting-config",
                    str(sorting_yaml),
                ],
            )

        assert result.exit_code == 2

    def test_run_error_message_to_stderr(self, tmp_path: Path) -> None:
        """Error message appears in output (captured by CliRunner)."""
        session_dir, bhv_file, subject_yaml, output_dir = _make_files(tmp_path)
        pipeline_yaml, sorting_yaml = _make_config_files(tmp_path)

        runner = CliRunner()
        with (
            patch("pynpxpipe.cli.main.SessionManager"),
            patch("pynpxpipe.cli.main.load_pipeline_config"),
            patch("pynpxpipe.cli.main.load_sorting_config"),
            patch("pynpxpipe.cli.main.load_subject_config"),
            patch("pynpxpipe.cli.main.PipelineRunner") as mock_runner_cls,
        ):
            mock_runner_cls.return_value.run.side_effect = DiscoverError("no probes found")

            result = runner.invoke(
                cli,
                [
                    "run",
                    str(session_dir),
                    str(bhv_file),
                    "--subject",
                    str(subject_yaml),
                    "--output-dir",
                    str(output_dir),
                    "--pipeline-config",
                    str(pipeline_yaml),
                    "--sorting-config",
                    str(sorting_yaml),
                ],
            )

        assert "Error" in result.output or "no probes found" in result.output

    def test_run_stages_option_passed(self, tmp_path: Path) -> None:
        """--stages sort --stages curate → runner.run(stages=['sort','curate'])."""
        session_dir, bhv_file, subject_yaml, output_dir = _make_files(tmp_path)
        pipeline_yaml, sorting_yaml = _make_config_files(tmp_path)

        runner = CliRunner()
        with (
            patch("pynpxpipe.cli.main.SessionManager"),
            patch("pynpxpipe.cli.main.load_pipeline_config"),
            patch("pynpxpipe.cli.main.load_sorting_config"),
            patch("pynpxpipe.cli.main.load_subject_config"),
            patch("pynpxpipe.cli.main.PipelineRunner") as mock_runner_cls,
        ):
            mock_run = mock_runner_cls.return_value.run

            runner.invoke(
                cli,
                [
                    "run",
                    str(session_dir),
                    str(bhv_file),
                    "--subject",
                    str(subject_yaml),
                    "--output-dir",
                    str(output_dir),
                    "--pipeline-config",
                    str(pipeline_yaml),
                    "--sorting-config",
                    str(sorting_yaml),
                    "--stages",
                    "sort",
                    "--stages",
                    "curate",
                ],
            )

        mock_run.assert_called_once_with(stages=["sort", "curate"])

    def test_run_no_stages_passes_none(self, tmp_path: Path) -> None:
        """No --stages → runner.run(stages=None)."""
        session_dir, bhv_file, subject_yaml, output_dir = _make_files(tmp_path)
        pipeline_yaml, sorting_yaml = _make_config_files(tmp_path)

        runner = CliRunner()
        with (
            patch("pynpxpipe.cli.main.SessionManager"),
            patch("pynpxpipe.cli.main.load_pipeline_config"),
            patch("pynpxpipe.cli.main.load_sorting_config"),
            patch("pynpxpipe.cli.main.load_subject_config"),
            patch("pynpxpipe.cli.main.PipelineRunner") as mock_runner_cls,
        ):
            mock_run = mock_runner_cls.return_value.run

            runner.invoke(
                cli,
                [
                    "run",
                    str(session_dir),
                    str(bhv_file),
                    "--subject",
                    str(subject_yaml),
                    "--output-dir",
                    str(output_dir),
                    "--pipeline-config",
                    str(pipeline_yaml),
                    "--sorting-config",
                    str(sorting_yaml),
                ],
            )

        mock_run.assert_called_once_with(stages=None)

    def test_run_requires_subject(self, tmp_path: Path) -> None:
        """Missing --subject → non-zero exit code."""
        session_dir, bhv_file, _, output_dir = _make_files(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                str(session_dir),
                str(bhv_file),
                "--output-dir",
                str(output_dir),
            ],
        )

        assert result.exit_code != 0

    def test_run_requires_output_dir(self, tmp_path: Path) -> None:
        """Missing --output-dir → non-zero exit code."""
        session_dir, bhv_file, subject_yaml, _ = _make_files(tmp_path)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "run",
                str(session_dir),
                str(bhv_file),
                "--subject",
                str(subject_yaml),
            ],
        )

        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Group B — status command
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_status_shows_all_stages(self, tmp_path: Path) -> None:
        """Output contains all 7 stage names."""
        from pynpxpipe.pipelines.runner import STAGE_ORDER

        output_dir = _make_output_dir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", str(output_dir)])

        assert result.exit_code == 0
        for stage in STAGE_ORDER:
            assert stage in result.output

    def test_status_completed_shows_check(self, tmp_path: Path) -> None:
        """discover=completed → output contains '✓' or 'completed'."""
        output_dir = _make_output_dir(tmp_path, {"discover": "completed"})
        runner = CliRunner()
        result = runner.invoke(cli, ["status", str(output_dir)])

        assert "✓" in result.output or "completed" in result.output

    def test_status_pending_shows_dash(self, tmp_path: Path) -> None:
        """All pending → output contains 'pending' or '-'."""
        output_dir = _make_output_dir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["status", str(output_dir)])

        assert "pending" in result.output or "-" in result.output

    def test_status_failed_shows_x(self, tmp_path: Path) -> None:
        """synchronize=failed → output contains '✗' or 'failed'."""
        output_dir = _make_output_dir(tmp_path, {"synchronize": "failed"})
        runner = CliRunner()
        result = runner.invoke(cli, ["status", str(output_dir)])

        assert "✗" in result.output or "failed" in result.output


# ---------------------------------------------------------------------------
# Group C — reset-stage command
# ---------------------------------------------------------------------------


class TestResetStageCommand:
    def test_reset_stage_with_yes_skips_prompt(self, tmp_path: Path) -> None:
        """--yes flag completes without waiting for stdin."""
        output_dir = _make_output_dir(tmp_path)
        cp_dir = output_dir / "checkpoints"
        cp_dir.mkdir(exist_ok=True)
        checkpoint = cp_dir / "sort.json"
        checkpoint.write_text(
            json.dumps({"stage": "sort", "status": "completed"}), encoding="utf-8"
        )

        runner = CliRunner()
        result = runner.invoke(cli, ["reset-stage", str(output_dir), "sort", "--yes"])

        assert result.exit_code == 0
        assert "Reset complete" in result.output

    def test_reset_stage_deletes_stage_checkpoint(self, tmp_path: Path) -> None:
        """reset-stage sort --yes deletes checkpoints/sort.json."""
        output_dir = _make_output_dir(tmp_path)
        cp_dir = output_dir / "checkpoints"
        cp_dir.mkdir(exist_ok=True)
        checkpoint = cp_dir / "sort.json"
        checkpoint.write_text("{}", encoding="utf-8")

        runner = CliRunner()
        runner.invoke(cli, ["reset-stage", str(output_dir), "sort", "--yes"])

        assert not checkpoint.exists()

    def test_reset_stage_deletes_probe_checkpoints(self, tmp_path: Path) -> None:
        """reset-stage preprocess --yes deletes preprocess_imec0.json too."""
        output_dir = _make_output_dir(tmp_path)
        cp_dir = output_dir / "checkpoints"
        cp_dir.mkdir(exist_ok=True)
        stage_cp = cp_dir / "preprocess.json"
        stage_cp.write_text("{}", encoding="utf-8")
        probe_cp = cp_dir / "preprocess_imec0.json"
        probe_cp.write_text("{}", encoding="utf-8")

        runner = CliRunner()
        runner.invoke(cli, ["reset-stage", str(output_dir), "preprocess", "--yes"])

        assert not probe_cp.exists()

    def test_reset_single_checkpoint_stage(self, tmp_path: Path) -> None:
        """reset-stage discover --yes only deletes discover.json, no probe files."""
        output_dir = _make_output_dir(tmp_path)
        cp_dir = output_dir / "checkpoints"
        cp_dir.mkdir(exist_ok=True)
        stage_cp = cp_dir / "discover.json"
        stage_cp.write_text("{}", encoding="utf-8")
        # A file that should NOT be deleted
        other_cp = cp_dir / "preprocess_imec0.json"
        other_cp.write_text("{}", encoding="utf-8")

        runner = CliRunner()
        runner.invoke(cli, ["reset-stage", str(output_dir), "discover", "--yes"])

        assert not stage_cp.exists()
        assert other_cp.exists()

    def test_reset_confirms_without_yes(self, tmp_path: Path) -> None:
        """Without --yes, answering 'y' confirms and deletes checkpoint."""
        output_dir = _make_output_dir(tmp_path)
        cp_dir = output_dir / "checkpoints"
        cp_dir.mkdir(exist_ok=True)
        checkpoint = cp_dir / "sort.json"
        checkpoint.write_text("{}", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["reset-stage", str(output_dir), "sort"], input="y\n")

        assert result.exit_code == 0
        assert not checkpoint.exists()

    def test_reset_aborts_without_yes_and_n(self, tmp_path: Path) -> None:
        """Without --yes, answering 'n' aborts — checkpoint not deleted."""
        output_dir = _make_output_dir(tmp_path)
        cp_dir = output_dir / "checkpoints"
        cp_dir.mkdir(exist_ok=True)
        checkpoint = cp_dir / "sort.json"
        checkpoint.write_text("{}", encoding="utf-8")

        runner = CliRunner()
        runner.invoke(cli, ["reset-stage", str(output_dir), "sort"], input="n\n")

        assert checkpoint.exists()


# ---------------------------------------------------------------------------
# Group D — Architecture constraints
# ---------------------------------------------------------------------------


class TestArchitectureConstraints:
    def test_click_not_imported_in_business_layer(self) -> None:
        """click is not imported in core/, io/, stages/, or pipelines/ modules."""
        from pathlib import Path as P

        src_root = P(__file__).parents[2] / "src" / "pynpxpipe"
        business_dirs = ["core", "io", "stages", "pipelines"]
        violations = []
        for subdir in business_dirs:
            for py_file in (src_root / subdir).rglob("*.py"):
                text = py_file.read_text(encoding="utf-8")
                if "import click" in text:
                    violations.append(str(py_file))

        assert violations == [], f"click imported in business layer: {violations}"

    def test_sys_exit_not_in_business_layer(self) -> None:
        """sys.exit() is not called in core/, io/, stages/, or pipelines/."""
        import re
        from pathlib import Path as P

        src_root = P(__file__).parents[2] / "src" / "pynpxpipe"
        business_dirs = ["core", "io", "stages", "pipelines"]
        # Match actual calls like sys.exit(...) but not docstring mentions
        sys_exit_call = re.compile(r"^\s*sys\.exit\(", re.MULTILINE)
        violations = []
        for subdir in business_dirs:
            for py_file in (src_root / subdir).rglob("*.py"):
                text = py_file.read_text(encoding="utf-8")
                if sys_exit_call.search(text):
                    violations.append(str(py_file))

        assert violations == [], f"sys.exit() found in business layer: {violations}"
