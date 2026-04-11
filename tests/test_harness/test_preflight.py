# tests/test_harness/test_preflight.py
from pathlib import Path
from unittest.mock import patch

from pynpxpipe.harness.preflight import PreflightChecker


def _make_session_dir(tmp_path: Path, with_imec: bool = True, with_nidq: bool = True) -> Path:
    sdir = tmp_path / "session_g0"
    sdir.mkdir()
    if with_imec:
        imec_dir = sdir / "session_g0_imec0"
        imec_dir.mkdir()
        (imec_dir / "session_g0_imec0.ap.bin").write_bytes(b"\x00" * 1024)
        (imec_dir / "session_g0_imec0.ap.meta").write_text(
            "imSampRate=30000\nnSavedChans=385\nfileSizeBytes=1024\n", encoding="utf-8"
        )
    if with_nidq:
        (sdir / "session_g0.nidq.bin").write_bytes(b"\x00" * 512)
        (sdir / "session_g0.nidq.meta").write_text("niSampRate=25000\n", encoding="utf-8")
    return sdir


def test_check_session_dir_structure_pass(tmp_path: Path) -> None:
    session_dir = _make_session_dir(tmp_path)
    checker = PreflightChecker(session_dir=session_dir, output_dir=tmp_path / "out")
    results = checker.check_data_integrity()
    statuses = {r.name: r.status for r in results}
    assert statuses["session_ap_files"] == "pass"
    assert statuses["nidq_files"] == "pass"


def test_check_session_dir_missing_ap_bin(tmp_path: Path) -> None:
    session_dir = _make_session_dir(tmp_path, with_imec=False)
    checker = PreflightChecker(session_dir=session_dir, output_dir=tmp_path / "out")
    results = checker.check_data_integrity()
    statuses = {r.name: r.status for r in results}
    assert statuses["session_ap_files"] == "fail"


def test_check_environment_cuda_vs_config_fail(tmp_path: Path) -> None:
    checker = PreflightChecker(session_dir=tmp_path / "s", output_dir=tmp_path / "out")
    with patch("pynpxpipe.harness.preflight.ResourceDetector") as mock_rd:
        mock_rd.return_value.detect.return_value.primary_gpu = None  # no GPU
        result = checker.check_cuda_vs_config(torch_device="cuda")
    assert result.status == "fail"
    assert result.auto_fixable is True
    assert result.fix_tier == "GREEN"


def test_check_environment_cuda_vs_config_pass_auto(tmp_path: Path) -> None:
    checker = PreflightChecker(session_dir=tmp_path / "s", output_dir=tmp_path / "out")
    with patch("pynpxpipe.harness.preflight.ResourceDetector") as mock_rd:
        mock_rd.return_value.detect.return_value.primary_gpu = None
        result = checker.check_cuda_vs_config(torch_device="auto")
    assert result.status == "pass"


def test_check_spikeinterface_version_pass(tmp_path: Path) -> None:
    checker = PreflightChecker(session_dir=tmp_path / "s", output_dir=tmp_path / "out")
    with patch("pynpxpipe.harness.preflight.si") as mock_si:
        mock_si.__version__ = "0.104.0"
        result = checker.check_spikeinterface_version()
    assert result.status == "pass"


def test_check_spikeinterface_version_fail(tmp_path: Path) -> None:
    checker = PreflightChecker(session_dir=tmp_path / "s", output_dir=tmp_path / "out")
    with patch("pynpxpipe.harness.preflight.si") as mock_si:
        mock_si.__version__ = "0.103.5"
        result = checker.check_spikeinterface_version()
    assert result.status == "fail"


def test_check_motion_nblocks_mutual_exclusion_fail(tmp_path: Path) -> None:
    checker = PreflightChecker(session_dir=tmp_path / "s", output_dir=tmp_path / "out")
    result = checker.check_motion_nblocks_exclusion(run_motion_correction=True, nblocks=15)
    assert result.status == "fail"
    assert result.auto_fixable is True
    assert result.fix_tier == "GREEN"


def test_check_amplitude_cutoff_config_consistency(tmp_path: Path) -> None:
    """After Task 3 fixes curate.py, this should PASS."""
    checker = PreflightChecker(session_dir=tmp_path / "s", output_dir=tmp_path / "out")
    result = checker.check_amplitude_cutoff_used()
    assert result.status == "pass"
