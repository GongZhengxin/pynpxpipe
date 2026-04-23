"""Tests for stages/discover.py — DiscoverStage.

Groups:
  A. Normal flow       — probes populated, JSON/checkpoint written, ordering, lf_found
  B. Checkpoint skip   — already-complete checkpoint causes immediate return
  C. Error handling    — bad probe list, missing NIDQ, bad BHV2 magic/missing file, failed checkpoint
  D. Progress callback — fraction 0.0 and 1.0 reported
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pynpxpipe.core.errors import DiscoverError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.stages.discover import BHV2_MAGIC, DiscoverStage

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


def _make_probe(probe_id: str, base: Path, has_lf: bool = True) -> ProbeInfo:
    """Return a ProbeInfo with dummy file paths (no real files created)."""
    ap_bin = base / f"{probe_id}.ap.bin"
    ap_meta = base / f"{probe_id}.ap.meta"
    lf_bin = base / f"{probe_id}.lf.bin" if has_lf else None
    lf_meta = base / f"{probe_id}.lf.meta" if has_lf else None
    target_area = "V4" if probe_id == "imec0" else "IT"
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=ap_bin,
        ap_meta=ap_meta,
        lf_bin=lf_bin,
        lf_meta=lf_meta,
        sample_rate=30000.0,
        n_channels=385,
        serial_number="test_sn",
        probe_type="NP1010",
        target_area=target_area,
    )


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Session with a valid BHV2 magic file and output directory."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(BHV2_MAGIC + b"\x00" * 50)
    output_dir = tmp_path / "output"
    return SessionManager.create(
        session_dir,
        bhv_file,
        _make_subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4", "imec1": "IT"},
        date="240101",
    )


@pytest.fixture
def two_probes(tmp_path: Path) -> list[ProbeInfo]:
    return [
        _make_probe("imec0", tmp_path, has_lf=True),
        _make_probe("imec1", tmp_path, has_lf=True),
    ]


def _fake_nidq(session: Session) -> tuple[Path, Path]:
    return (
        session.session_dir / "session.nidq.bin",
        session.session_dir / "session.nidq.meta",
    )


def _patch_discovery(mock_cls, probes, warnings=None, nidq=None):
    """Configure the mocked SpikeGLXDiscovery instance."""
    mock = mock_cls.return_value
    mock.discover_probes.return_value = probes
    mock.validate_probe.return_value = warnings if warnings is not None else []
    if nidq is not None:
        mock.discover_nidq.return_value = nidq
    return mock


# ---------------------------------------------------------------------------
# Group A — Normal flow
# ---------------------------------------------------------------------------


class TestNormalFlow:
    def test_run_populates_session_probes(self, session, two_probes):
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, two_probes, nidq=_fake_nidq(session))
            DiscoverStage(session).run()

        assert len(session.probes) == 2
        assert session.probes[0].probe_id == "imec0"
        assert session.probes[1].probe_id == "imec1"

    def test_run_writes_session_info_json(self, session, two_probes):
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, two_probes, nidq=_fake_nidq(session))
            DiscoverStage(session).run()

        info_path = session.output_dir / "session_info.json"
        assert info_path.exists()
        data = json.loads(info_path.read_text(encoding="utf-8"))
        assert data["n_probes"] == 2
        assert "probe_ids" in data
        assert "nidq_found" in data
        assert "lf_found" in data
        assert "warnings" in data

    def test_run_writes_completed_checkpoint(self, session, two_probes):
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, two_probes, nidq=_fake_nidq(session))
            DiscoverStage(session).run()

        cp = session.output_dir / "checkpoints" / "discover.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "completed"

    def test_session_info_json_probe_ids_sorted(self, session, tmp_path):
        # Probes given in reverse order — output must be sorted
        probes = [
            _make_probe("imec1", tmp_path, has_lf=True),
            _make_probe("imec0", tmp_path, has_lf=True),
        ]
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, probes, nidq=_fake_nidq(session))
            DiscoverStage(session).run()

        data = json.loads((session.output_dir / "session_info.json").read_text(encoding="utf-8"))
        assert data["probe_ids"] == ["imec0", "imec1"]

    def test_session_info_json_nidq_found_true(self, session, two_probes):
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, two_probes, nidq=_fake_nidq(session))
            DiscoverStage(session).run()

        data = json.loads((session.output_dir / "session_info.json").read_text(encoding="utf-8"))
        assert data["nidq_found"] is True

    def test_lf_found_false_does_not_raise(self, session, tmp_path):
        probes_no_lf = [_make_probe("imec0", tmp_path, has_lf=False)]
        session.probe_plan = {"imec0": "V4"}  # single-probe plan to match
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, probes_no_lf, nidq=_fake_nidq(session))
            DiscoverStage(session).run()  # Must not raise

        data = json.loads((session.output_dir / "session_info.json").read_text(encoding="utf-8"))
        assert data["lf_found"] is False

    def test_probe_warnings_included_in_output(self, session, two_probes):
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(
                mock_cls,
                two_probes,
                warnings=["ap.bin size mismatch: expected 1000 bytes, got 999 bytes"],
                nidq=_fake_nidq(session),
            )
            DiscoverStage(session).run()

        data = json.loads((session.output_dir / "session_info.json").read_text(encoding="utf-8"))
        assert len(data["warnings"]) > 0


# ---------------------------------------------------------------------------
# Group B — Checkpoint skip
# ---------------------------------------------------------------------------


class TestCheckpointSkip:
    def _write_completed_checkpoint(self, session: Session) -> None:
        cp = session.output_dir / "checkpoints" / "discover.json"
        cp.write_text(
            json.dumps({"stage": "discover", "status": "completed"}),
            encoding="utf-8",
        )

    def test_run_skips_if_checkpoint_complete(self, session, two_probes):
        self._write_completed_checkpoint(session)
        session.probes = two_probes  # pre-populated so restore is a no-op
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            DiscoverStage(session).run()
            mock_cls.assert_not_called()

    def test_run_still_returns_none_on_skip(self, session, two_probes):
        self._write_completed_checkpoint(session)
        session.probes = two_probes
        result = DiscoverStage(session).run()
        assert result is None


# ---------------------------------------------------------------------------
# Group C — Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_no_probes_found_raises_discover_error(self, session):
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, [])
            with pytest.raises(DiscoverError, match="No IMEC probes"):
                DiscoverStage(session).run()

    def test_nidq_not_found_raises_discover_error(self, session, two_probes):
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            mock = _patch_discovery(mock_cls, two_probes)
            mock.discover_nidq.side_effect = DiscoverError("No .nidq.bin file found")
            with pytest.raises(DiscoverError, match="(?i)nidq"):
                DiscoverStage(session).run()

    def test_bhv2_wrong_magic_raises_discover_error(self, session, two_probes):
        # Overwrite BHV2 file with wrong magic bytes
        session.bhv_file.write_bytes(b"\x00" * 21)
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, two_probes, nidq=_fake_nidq(session))
            with pytest.raises(DiscoverError, match="(?i)bhv2"):
                DiscoverStage(session).run()

    def test_bhv2_not_found_raises_discover_error(self, session, two_probes):
        session.bhv_file.unlink()
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, two_probes, nidq=_fake_nidq(session))
            with pytest.raises(DiscoverError):
                DiscoverStage(session).run()

    def test_failed_checkpoint_written_on_error(self, session):
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, [])
            with pytest.raises(DiscoverError):
                DiscoverStage(session).run()

        cp = session.output_dir / "checkpoints" / "discover.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "failed"


# ---------------------------------------------------------------------------
# Group D — Progress callback
# ---------------------------------------------------------------------------


class TestProgressCallback:
    def _run_with_callback(self, session, two_probes) -> list[tuple[str, float]]:
        calls: list[tuple[str, float]] = []
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, two_probes, nidq=_fake_nidq(session))
            DiscoverStage(session, progress_callback=lambda m, f: calls.append((m, f))).run()
        return calls

    def test_progress_callback_called_at_start(self, session, two_probes):
        calls = self._run_with_callback(session, two_probes)
        fractions = [f for _, f in calls]
        assert 0.0 in fractions

    def test_progress_callback_called_at_end(self, session, two_probes):
        calls = self._run_with_callback(session, two_probes)
        fractions = [f for _, f in calls]
        assert 1.0 in fractions


# ---------------------------------------------------------------------------
# Group E — probe_plan validation + target_area injection (S2)
# ---------------------------------------------------------------------------


def _make_probe_placeholder(probe_id: str, base: Path) -> ProbeInfo:
    """Return a ProbeInfo with target_area='' as SpikeGLXDiscovery yields it."""
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=base / f"{probe_id}.ap.bin",
        ap_meta=base / f"{probe_id}.ap.meta",
        lf_bin=base / f"{probe_id}.lf.bin",
        lf_meta=base / f"{probe_id}.lf.meta",
        sample_rate=30000.0,
        n_channels=385,
        serial_number="sn",
        probe_type="NP1010",
        target_area="",
    )


class TestProbePlanValidation:
    def test_empty_probe_plan_raises(self, session):
        session.probe_plan = {}
        with pytest.raises(DiscoverError, match="probe_plan is empty"):
            DiscoverStage(session).run()

    def test_target_area_injected_from_probe_plan(self, session, tmp_path):
        """DiscoverStage must overwrite target_area with probe_plan values."""
        from pynpxpipe.core.errors import ProbeDeclarationMismatchError  # noqa: F401

        placeholders = [
            _make_probe_placeholder("imec0", tmp_path),
            _make_probe_placeholder("imec1", tmp_path),
        ]
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, placeholders, nidq=_fake_nidq(session))
            DiscoverStage(session).run()

        assert session.probes[0].target_area == "V4"
        assert session.probes[1].target_area == "IT"

    def test_declared_not_on_disk_raises_mismatch(self, session, tmp_path):
        from pynpxpipe.core.errors import ProbeDeclarationMismatchError

        only_imec0 = [_make_probe_placeholder("imec0", tmp_path)]
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, only_imec0, nidq=_fake_nidq(session))
            with pytest.raises(ProbeDeclarationMismatchError) as exc_info:
                DiscoverStage(session).run()
        assert exc_info.value.missing_on_disk == {"imec1"}

    def test_extra_on_disk_raises_mismatch(self, session, tmp_path):
        from pynpxpipe.core.errors import ProbeDeclarationMismatchError

        session.probe_plan = {"imec0": "V4"}
        two = [
            _make_probe_placeholder("imec0", tmp_path),
            _make_probe_placeholder("imec1", tmp_path),
        ]
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, two, nidq=_fake_nidq(session))
            with pytest.raises(ProbeDeclarationMismatchError) as exc_info:
                DiscoverStage(session).run()
        assert exc_info.value.unexpected_on_disk == {"imec1"}

    def test_session_info_json_contains_target_areas(self, session, tmp_path):
        placeholders = [
            _make_probe_placeholder("imec0", tmp_path),
            _make_probe_placeholder("imec1", tmp_path),
        ]
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            _patch_discovery(mock_cls, placeholders, nidq=_fake_nidq(session))
            DiscoverStage(session).run()

        data = json.loads((session.output_dir / "session_info.json").read_text(encoding="utf-8"))
        assert data["probe_target_areas"] == {"imec0": "V4", "imec1": "IT"}
