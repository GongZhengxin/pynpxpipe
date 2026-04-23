"""Tests for stages/sort.py — SortStage.

Groups:
  A. Local mode     — run_sorter called, sorting saved, checkpoint written
  B. Import mode    — read_sorter_folder / read_phy called, checkpoint written
  C. Serial         — always serial, never parallel
  D. Checkpoint skip — per-probe and stage-level resume
  E. Error handling — run_sorter failure, unknown mode, failed checkpoint
  F. GC release     — gc.collect called after each probe
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from pynpxpipe.core.config import (
    ImportConfig,
    SorterConfig,
    SorterParams,
    SortingConfig,
)
from pynpxpipe.core.errors import SortError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.stages.sort import SortStage

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="test",
        description="desc",
        species="Macaca mulatta",
        sex="M",
        age="P3Y",
        weight="10kg",
    )


def _make_probe(probe_id: str, base: Path) -> ProbeInfo:
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=base / f"{probe_id}.ap.bin",
        ap_meta=base / f"{probe_id}.ap.meta",
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=384,
        serial_number="SN_TEST",
        probe_type="NP1010",
        target_area="V4" if probe_id == "imec0" else "IT",
    )


def _make_sorting_config(
    mode: str = "local",
    sorter_name: str = "kilosort4",
    nblocks: int = 0,
    import_format: str = "kilosort4",
    import_paths: dict[str, str] | None = None,
) -> SortingConfig:
    """Build a SortingConfig for testing with concrete (non-auto) param values."""
    return SortingConfig(
        mode=mode,
        sorter=SorterConfig(
            name=sorter_name,
            params=SorterParams(nblocks=nblocks, batch_size=1, n_jobs=1),
        ),
        import_cfg=ImportConfig(
            format=import_format,
            paths={k: Path(v) for k, v in (import_paths or {}).items()},
        ),
    )


def _make_mock_sorting(n_units: int = 3) -> MagicMock:
    mock = MagicMock()
    mock.get_unit_ids.return_value = list(range(n_units))
    return mock


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Session with two probes (imec0, imec1)."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(
        session_dir,
        bhv_file,
        _make_subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4", "imec1": "IT"},
        date="240101",
    )
    s.probes = [
        _make_probe("imec0", tmp_path),
        _make_probe("imec1", tmp_path),
    ]
    return s


@pytest.fixture
def single_session(tmp_path: Path) -> Session:
    """Session with one probe (imec0)."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(
        session_dir,
        bhv_file,
        _make_subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4"},
        date="240101",
    )
    s.probes = [_make_probe("imec0", tmp_path)]
    return s


def _write_completed_checkpoint(session: Session, stage: str, probe_id: str | None = None) -> None:
    filename = f"{stage}.json" if probe_id is None else f"{stage}_{probe_id}.json"
    cp_path = session.output_dir / "checkpoints" / filename
    cp_path.write_text(
        json.dumps({"stage": stage, "status": "completed"}),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Group A — Local mode
# ---------------------------------------------------------------------------


class TestLocalMode:
    def test_local_mode_calls_run_sorter(self, single_session: Session) -> None:
        """si.run_sorter is called with the configured sorter name."""
        sorting_cfg = _make_sorting_config(mode="local", sorter_name="kilosort4")
        mock_sorting = _make_mock_sorting()

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch("pynpxpipe.stages.sort.ss.run_sorter", return_value=mock_sorting) as mock_run,
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(single_session, sorting_cfg).run()

        assert mock_run.called
        assert mock_run.call_args.args[0] == "kilosort4"

    def test_local_mode_saves_sorting(self, single_session: Session) -> None:
        """sorting.save is called with a path containing 'sorted/imec0'."""
        sorting_cfg = _make_sorting_config(mode="local")
        mock_sorting = _make_mock_sorting()

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch("pynpxpipe.stages.sort.ss.run_sorter", return_value=mock_sorting),
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(single_session, sorting_cfg).run()

        folder = mock_sorting.save.call_args.kwargs.get("folder") or mock_sorting.save.call_args[
            1
        ].get("folder")
        assert folder is not None
        assert "02_sorted" in str(folder)
        assert "imec0" in str(folder)

    def test_local_mode_writes_probe_checkpoint(self, single_session: Session) -> None:
        """sort_imec0.json exists with status=completed after local sort."""
        sorting_cfg = _make_sorting_config(mode="local")

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch("pynpxpipe.stages.sort.ss.run_sorter", return_value=_make_mock_sorting()),
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(single_session, sorting_cfg).run()

        cp = single_session.output_dir / "checkpoints" / "sort_imec0.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "completed"

    def test_local_zero_units_logs_warning_not_error(self, single_session: Session) -> None:
        """Zero units from sorter is a WARNING, not an error — run() must not raise."""
        sorting_cfg = _make_sorting_config(mode="local")
        mock_sorting = _make_mock_sorting(n_units=0)

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch("pynpxpipe.stages.sort.ss.run_sorter", return_value=mock_sorting),
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(single_session, sorting_cfg).run()  # must not raise

        cp = single_session.output_dir / "checkpoints" / "sort_imec0.json"
        assert cp.exists()

    def test_sorter_params_passed_to_run_sorter(self, single_session: Session) -> None:
        """Sorter params (e.g. nblocks=5) are forwarded as kwargs to run_sorter."""
        sorting_cfg = _make_sorting_config(mode="local", nblocks=5)

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch(
                "pynpxpipe.stages.sort.ss.run_sorter", return_value=_make_mock_sorting()
            ) as mock_run,
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(single_session, sorting_cfg).run()

        kwargs = mock_run.call_args.kwargs
        assert kwargs.get("nblocks") == 5


# ---------------------------------------------------------------------------
# Group B — Import mode
# ---------------------------------------------------------------------------


class TestImportMode:
    def test_import_mode_calls_read_sorter_folder(
        self, single_session: Session, tmp_path: Path
    ) -> None:
        """si.read_sorter_folder is called with the import path when format='kilosort4'."""
        import_dir = tmp_path / "ks4_output"
        import_dir.mkdir()
        sorting_cfg = _make_sorting_config(
            mode="import",
            import_format="kilosort4",
            import_paths={"imec0": str(import_dir)},
        )
        mock_sorting = _make_mock_sorting()

        with (
            patch(
                "pynpxpipe.stages.sort.ss.read_sorter_folder", return_value=mock_sorting
            ) as mock_read,
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(single_session, sorting_cfg).run()

        mock_read.assert_called_once_with(import_dir)

    def test_import_mode_path_missing_raises(self, single_session: Session, tmp_path: Path) -> None:
        """SortError is raised when the import path does not exist."""
        missing = tmp_path / "nonexistent_ks4"
        sorting_cfg = _make_sorting_config(
            mode="import",
            import_format="kilosort4",
            import_paths={"imec0": str(missing)},
        )

        with pytest.raises(SortError, match="Import path not found"):
            SortStage(single_session, sorting_cfg).run()

    def test_import_phy_format(self, single_session: Session, tmp_path: Path) -> None:
        """si.read_phy is called when import format is 'phy'."""
        import_dir = tmp_path / "phy_output"
        import_dir.mkdir()
        sorting_cfg = _make_sorting_config(
            mode="import",
            import_format="phy",
            import_paths={"imec0": str(import_dir)},
        )
        mock_sorting = _make_mock_sorting()

        with (
            patch("pynpxpipe.stages.sort.se.read_phy", return_value=mock_sorting) as mock_phy,
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(single_session, sorting_cfg).run()

        mock_phy.assert_called_once_with(import_dir)

    def test_import_writes_checkpoint(self, single_session: Session, tmp_path: Path) -> None:
        """sort_imec0.json exists with status=completed after successful import."""
        import_dir = tmp_path / "ks4_output"
        import_dir.mkdir()
        sorting_cfg = _make_sorting_config(
            mode="import",
            import_format="kilosort4",
            import_paths={"imec0": str(import_dir)},
        )

        with (
            patch(
                "pynpxpipe.stages.sort.ss.read_sorter_folder",
                return_value=_make_mock_sorting(),
            ),
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(single_session, sorting_cfg).run()

        cp = single_session.output_dir / "checkpoints" / "sort_imec0.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Group C — Serial guarantee
# ---------------------------------------------------------------------------


class TestSerialGuarantee:
    def test_always_serial_even_if_parallel_enabled(self, session: Session) -> None:
        """Both probes are processed serially; SortStage never uses parallelism."""
        sorting_cfg = _make_sorting_config(mode="local")

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch(
                "pynpxpipe.stages.sort.ss.run_sorter", return_value=_make_mock_sorting()
            ) as mock_run,
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(session, sorting_cfg).run()

        # Exactly 2 serial calls — one per probe
        assert mock_run.call_count == 2
        cp0 = session.output_dir / "checkpoints" / "sort_imec0.json"
        cp1 = session.output_dir / "checkpoints" / "sort_imec1.json"
        assert cp0.exists()
        assert cp1.exists()


# ---------------------------------------------------------------------------
# Group D — Checkpoint skip
# ---------------------------------------------------------------------------


class TestCheckpointSkip:
    def test_skips_sorted_probe(self, session: Session) -> None:
        """si.run_sorter is NOT called for imec0 when its checkpoint is complete."""
        _write_completed_checkpoint(session, "sort", "imec0")
        sorting_cfg = _make_sorting_config(mode="local")

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch(
                "pynpxpipe.stages.sort.ss.run_sorter", return_value=_make_mock_sorting()
            ) as mock_run,
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(session, sorting_cfg).run()

        # Only imec1 was sorted
        assert mock_run.call_count == 1

    def test_processes_remaining_probe(self, session: Session) -> None:
        """imec1 is processed when imec0 already has a completed checkpoint."""
        _write_completed_checkpoint(session, "sort", "imec0")
        sorting_cfg = _make_sorting_config(mode="local")

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch("pynpxpipe.stages.sort.ss.run_sorter", return_value=_make_mock_sorting()),
            patch("pynpxpipe.stages.sort.gc"),
        ):
            SortStage(session, sorting_cfg).run()

        cp1 = session.output_dir / "checkpoints" / "sort_imec1.json"
        assert cp1.exists()
        data = json.loads(cp1.read_text(encoding="utf-8"))
        assert data["status"] == "completed"


# ---------------------------------------------------------------------------
# Group E — Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_run_sorter_failure_raises_sort_error(self, single_session: Session) -> None:
        """RuntimeError from si.run_sorter is wrapped and raised as SortError."""
        sorting_cfg = _make_sorting_config(mode="local")

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch(
                "pynpxpipe.stages.sort.ss.run_sorter",
                side_effect=RuntimeError("CUDA out of memory"),
            ),
            patch("pynpxpipe.stages.sort.gc"),
            pytest.raises(SortError, match="imec0"),
        ):
            SortStage(single_session, sorting_cfg).run()

    def test_failed_checkpoint_written_on_error(self, single_session: Session) -> None:
        """sort_imec0.json status=failed is written when run_sorter raises."""
        sorting_cfg = _make_sorting_config(mode="local")

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch(
                "pynpxpipe.stages.sort.ss.run_sorter",
                side_effect=RuntimeError("CUDA out of memory"),
            ),
            patch("pynpxpipe.stages.sort.gc"),
            pytest.raises(SortError),
        ):
            SortStage(single_session, sorting_cfg).run()

        cp = single_session.output_dir / "checkpoints" / "sort_imec0.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "failed"

    def test_unknown_mode_raises_sort_error(self, single_session: Session) -> None:
        """SortError('Unknown mode: ...') is raised immediately for invalid mode."""
        # Bypass SortingConfig validation by patching the config after construction
        sorting_cfg = _make_sorting_config(mode="local")
        sorting_cfg.mode = "invalid"  # bypass dataclass validation

        with pytest.raises(SortError, match="Unknown mode"):
            SortStage(single_session, sorting_cfg).run()


# ---------------------------------------------------------------------------
# Group F — GC release
# ---------------------------------------------------------------------------


class TestGcRelease:
    def test_gc_collect_called_after_sort(self, session: Session) -> None:
        """gc.collect() is called once per probe sorted."""
        sorting_cfg = _make_sorting_config(mode="local")

        with (
            patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
            patch("pynpxpipe.stages.sort.ss.run_sorter", return_value=_make_mock_sorting()),
            patch("pynpxpipe.stages.sort.gc") as mock_gc,
        ):
            SortStage(session, sorting_cfg).run()

        # 2 probes → gc.collect called at least 2 times
        assert mock_gc.collect.call_count >= 2


# ---------------------------------------------------------------------------
# Group G — CUDA guard + OOM retry
# ---------------------------------------------------------------------------


def _make_mock_sort_session(
    tmp_path: Path,
    torch_device: str = "auto",
    mode: str = "local",
    batch_size: int | str = "auto",
) -> Session:
    """Build a Session with one imec0 probe and a SortStage-compatible config.

    Mutates the session's sorting_config by constructing SortStage with it.
    Callers use `SortStage(session, _make_sorting_config(...))` directly instead.
    Returns a plain Session; the caller provides SortingConfig separately.
    """
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir(exist_ok=True)
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(
        session_dir,
        bhv_file,
        _make_subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4"},
        date="240101",
    )
    s.probes = [_make_probe("imec0", tmp_path)]
    # Store requested params on the session so callers can build SortingConfig
    s._test_torch_device = torch_device  # type: ignore[attr-defined]
    s._test_batch_size = batch_size  # type: ignore[attr-defined]
    s._test_mode = mode  # type: ignore[attr-defined]
    return s


def test_sort_raises_when_cuda_requested_but_no_gpu(tmp_path: Path) -> None:
    """torch_device='cuda' on a no-GPU machine must be a loud error, not a silent fallback.

    Silent fallback was the bug that kept hiding dependency problems — the user
    saw 'success' but actually ran CPU. New contract: explicit 'cuda' + no GPU
    raises TorchEnvError. Users without a GPU should set torch_device='cpu' or
    'auto' (the default).
    """
    from pynpxpipe.core.torch_env import TorchEnvError

    session = _make_mock_sort_session(tmp_path, torch_device="cuda", mode="local")
    sorting_cfg = _make_sorting_config(mode="local")
    sorting_cfg.sorter.params.torch_device = "cuda"

    with (
        patch("pynpxpipe.stages.sort.ResourceDetector") as mock_rd,
        patch("pynpxpipe.stages.sort.ss") as mock_ss,
        patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
    ):
        mock_rd.return_value.detect.return_value.primary_gpu = None  # no GPU

        with pytest.raises(TorchEnvError, match="no NVIDIA GPU"):
            SortStage(session, sorting_cfg)._sort_probe_local("imec0")

    # Sorter must never have been invoked.
    mock_ss.run_sorter.assert_not_called()


def test_sort_auto_falls_back_to_cpu_when_no_gpu(tmp_path: Path) -> None:
    """torch_device='auto' on a no-GPU machine silently uses cpu (no warn, no error)."""
    session = _make_mock_sort_session(tmp_path, torch_device="auto", mode="local")
    sorting_cfg = _make_sorting_config(mode="local")
    sorting_cfg.sorter.params.torch_device = "auto"

    with (
        patch("pynpxpipe.stages.sort.ResourceDetector") as mock_rd,
        patch("pynpxpipe.stages.sort.ss") as mock_ss,
        patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
    ):
        mock_rd.return_value.detect.return_value.primary_gpu = None
        mock_ss.run_sorter.return_value = _make_mock_sorting()

        SortStage(session, sorting_cfg)._sort_probe_local("imec0")

    assert mock_ss.run_sorter.call_args[1].get("torch_device") == "cpu"


def test_sort_retries_with_lower_batch_size_on_cuda_oom(tmp_path: Path) -> None:
    """On CUDA OOM, retry _sort_probe_local once with batch_size halved."""
    session = _make_mock_sort_session(tmp_path, torch_device="cuda", mode="local", batch_size=60000)
    sorting_cfg = _make_sorting_config(mode="local")
    sorting_cfg.sorter.params.batch_size = 60000

    oom_error = RuntimeError("CUDA out of memory. Tried to allocate 2.50 GiB")
    success_result = _make_mock_sorting()

    with (
        patch("pynpxpipe.stages.sort.ss") as mock_ss,
        patch("pynpxpipe.stages.sort.si.load", return_value=MagicMock()),
    ):
        mock_ss.run_sorter.side_effect = [oom_error, success_result]

        stage = SortStage(session, sorting_cfg)
        stage._sort_probe_local("imec0")  # should not raise

    assert mock_ss.run_sorter.call_count == 2
    first_call_params = mock_ss.run_sorter.call_args_list[0][1]
    second_call_params = mock_ss.run_sorter.call_args_list[1][1]
    assert second_call_params["batch_size"] < first_call_params["batch_size"]


# ---------------------------------------------------------------------------
# Regression guard — KS4 library-default drift
# ---------------------------------------------------------------------------


def test_ks4_critical_params_explicit():
    """Regression guard: four KS4 params must be explicitly pinned in sorting.yaml.

    KS4 upstream silently changed `cluster_downsampling` default from 1 (4.1.0-4.1.2)
    to 20 (4.1.3+), reducing yield ~29% vs the reference pipeline. We pin these four
    params so future library upgrades cannot silently regress unit yield. See
    docs/todo.md §IV.8 for the full audit trail and rationale.
    """
    yaml_path = Path(__file__).resolve().parents[2] / "config" / "sorting.yaml"
    cfg = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    params = cfg["sorter"]["params"]

    expected = {
        "Th_learned": 8.0,
        "Th_universal": 9.0,
        "cluster_downsampling": 1,
        "max_cluster_subset": 25000,
    }
    for key, value in expected.items():
        assert key in params, (
            f"sorting.yaml missing pinned KS4 param '{key}' — see docs/todo.md §IV.8"
        )
        assert params[key] == value, (
            f"sorting.yaml sorter.params.{key}={params[key]!r} but expected {value!r} "
            f"(pinned to prevent KS4 library-default regression; see docs/todo.md §IV.8)"
        )
