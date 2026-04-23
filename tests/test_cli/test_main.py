"""Tests for cli/main.py — pynpxpipe CLI.

Groups:
  A. run command                — success, error handling, stages option, required options
  B. status command             — output format for completed/pending/failed stages
  C. reset-stage cmd            — checkpoint deletion, --yes flag, confirmation prompt
  D. Architecture               — click not imported in business layer, no sys.exit in business layer
  E. verify-safe-to-delete cmd  — E2.3 exit codes + path listing
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
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


# ---------------------------------------------------------------------------
# Group E — verify-safe-to-delete command (E2.3)
# ---------------------------------------------------------------------------


def _write_minimal_nwb(nwb_path: Path) -> None:
    """Create a tiny readable NWB file for verify-safe-to-delete tests."""
    import pynwb

    nwb_path.parent.mkdir(parents=True, exist_ok=True)
    nwbfile = pynwb.NWBFile(
        session_description="verify-safe test",
        identifier=str(uuid.uuid4()),
        session_start_time=datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC),
    )
    with pynwb.NWBHDF5IO(str(nwb_path), "w") as io:
        io.write(nwbfile)


def _make_verify_fixture(
    tmp_path: Path,
    *,
    with_verified_at: bool = True,
    with_nwb: bool = True,
) -> tuple[Path, Path]:
    """Build a session_dir with the files verify-safe-to-delete consumes.

    Returns (output_dir, nwb_path).
    """
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "checkpoints").mkdir()

    # Stand up a SpikeGLX-shaped raw-source dir so _collect_raw_files has
    # something to enumerate. Only the session.json structure matters here.
    raw_dir = tmp_path / "raw_g0"
    raw_dir.mkdir()
    ap_bin = raw_dir / "imec0" / "imec0.ap.bin"
    ap_meta = raw_dir / "imec0" / "imec0.ap.meta"
    ap_bin.parent.mkdir()
    ap_bin.write_bytes(b"\x00" * 16)
    ap_meta.write_text("typeThis=imec\n", encoding="utf-8")
    nidq_bin = raw_dir / "run.nidq.bin"
    nidq_meta = raw_dir / "run.nidq.meta"
    nidq_bin.write_bytes(b"\x00" * 16)
    nidq_meta.write_text("typeThis=nidq\n", encoding="utf-8")

    session_json = {
        "session_dir": str(raw_dir),
        "output_dir": str(output_dir),
        "bhv_file": str(tmp_path / "task.bhv2"),
        "subject": {
            "subject_id": "TestMon",
            "description": "verify-safe test",
            "species": "Macaca mulatta",
            "sex": "M",
            "age": "P3Y",
            "weight": "10kg",
        },
        "session_id": {
            "date": "260417",
            "subject": "TestMon",
            "experiment": "nsd1w",
            "region": "V4",
        },
        "probe_plan": {"imec0": "V4"},
        "probes": [
            {
                "probe_id": "imec0",
                "ap_bin": str(ap_bin),
                "ap_meta": str(ap_meta),
                "lf_bin": None,
                "lf_meta": None,
                "sample_rate": 30000.0,
                "n_channels": 384,
                "probe_type": "NP1010",
                "serial_number": "SN0",
                "target_area": "V4",
            }
        ],
        "checkpoint": {},
    }
    (output_dir / "session.json").write_text(json.dumps(session_json), encoding="utf-8")

    nwb_path = output_dir / "260417_TestMon_nsd1w_V4.nwb"
    if with_nwb:
        _write_minimal_nwb(nwb_path)

    cp = {
        "stage": "export",
        "status": "completed",
        "nwb_path": str(nwb_path),
    }
    if with_verified_at:
        cp["raw_data_verified_at"] = "2026-04-17T10:00:00+00:00"
        cp["verify_policy"] = "full"
    (output_dir / "checkpoints" / "export.json").write_text(
        json.dumps(cp), encoding="utf-8"
    )

    return output_dir, nwb_path


class TestVerifySafeToDeleteCommand:
    """E2.3: verify-safe-to-delete CLI — exit codes + printed bin paths."""

    def test_verify_safe_exits_zero_when_safe(self, tmp_path: Path) -> None:
        """All prerequisites present → exit 0."""
        output_dir, _ = _make_verify_fixture(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["verify-safe-to-delete", str(output_dir)])

        assert result.exit_code == 0, result.output

    def test_verify_safe_exits_nonzero_missing_verified_at(self, tmp_path: Path) -> None:
        """export.json lacks raw_data_verified_at → exit != 0 + reason mentions 'verified'."""
        output_dir, _ = _make_verify_fixture(tmp_path, with_verified_at=False)
        runner = CliRunner()
        result = runner.invoke(cli, ["verify-safe-to-delete", str(output_dir)])

        assert result.exit_code != 0
        # click.echo to err=True lands in result.output under mix_stderr=True (default).
        assert "verified" in result.output.lower()

    def test_verify_safe_exits_nonzero_missing_nwb(self, tmp_path: Path) -> None:
        """export.json valid but NWB absent → exit != 0 + message mentions NWB."""
        output_dir, nwb_path = _make_verify_fixture(tmp_path, with_nwb=False)
        # Ensure the NWB really isn't there.
        assert not nwb_path.exists()
        runner = CliRunner()
        result = runner.invoke(cli, ["verify-safe-to-delete", str(output_dir)])

        assert result.exit_code != 0
        assert "NWB" in result.output or "nwb" in result.output

    def test_verify_safe_prints_bin_paths_on_success(self, tmp_path: Path) -> None:
        """Happy path → stdout lists at least one .bin path."""
        output_dir, _ = _make_verify_fixture(tmp_path)
        runner = CliRunner()
        result = runner.invoke(cli, ["verify-safe-to-delete", str(output_dir)])

        assert result.exit_code == 0, result.output
        assert ".bin" in result.output
        assert "Safe to delete" in result.output

    def test_verify_safe_refuses_empty_raw_file_list(self, tmp_path: Path) -> None:
        """NWB verified but no raw bins locatable → exit != 0, refuse empty list.

        This guards the "I can't tell you what's safe" case: checkpoint says
        verified and NWB opens cleanly, but session.json is unreadable (or
        the bins have already been removed), so we cannot name a single file
        to reclaim. The honest answer is to fail, not print an empty list.
        """
        from pynpxpipe.pipelines.verify import EXIT_NO_RAW_FILES_FOUND

        output_dir, _ = _make_verify_fixture(tmp_path)
        # Corrupt session.json so SessionManager.load fails → empty file list.
        (output_dir / "session.json").write_text("not valid json", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["verify-safe-to-delete", str(output_dir)])

        assert result.exit_code == EXIT_NO_RAW_FILES_FOUND
        assert "no raw" in result.output.lower() or "empty" in result.output.lower()
