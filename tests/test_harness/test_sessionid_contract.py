"""SessionID contract harness.

End-to-end validation that code paths touching the canonical session identifier
(`{date}_{subject}_{experiment}_{region}`) stay wired together across sessions.

Scope:
- S1 (green): SessionID dataclass, SessionManager.create/load, ProbeInfo.target_area
  required, SpikeGLXLoader.read_recording_date.
- S2 (green): DiscoverStage injects target_area from probe_plan and rejects
  mismatches; ExportStage output path and NWBFile.session_id both equal
  canonical(); ExportStage rejects empty/"unknown" target_area.
- S3 (green): UI AppState.session_id property; SessionLoader restores
  experiment/recording_date/probe_plan; RunPanel pre-exec blocks missing fields.

Runtime budget: <30s. No network, no GPU, no real SpikeGLX binary.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from pynpxpipe.core.errors import ExportError, ProbeDeclarationMismatchError
from pynpxpipe.core.session import (
    ProbeInfo,
    Session,
    SessionID,
    SessionManager,
    SubjectConfig,
)
from pynpxpipe.io.nwb_writer import NWBWriter
from pynpxpipe.io.spikeglx import SpikeGLXLoader
from pynpxpipe.stages.discover import BHV2_MAGIC, DiscoverStage
from pynpxpipe.stages.export import ExportStage

# ── Fixtures ─────────────────────────────────────────────────────────────


def _subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="MaoDan",
        description="contract harness subject",
        species="Macaca mulatta",
        sex="M",
        age="P4Y",
        weight="12kg",
    )


def _write_ap_meta(path: Path, create_time: str) -> None:
    """Write a minimal SpikeGLX .ap.meta file with the given fileCreateTime."""
    path.write_text(
        f"fileCreateTime={create_time}\nimSampRate=30000.0\nnSavedChans=385\n",
        encoding="utf-8",
    )


_SENTINEL: dict[str, str] = {"imec0": "MSB", "imec1": "V4"}


def _make_session(
    tmp_path: Path,
    *,
    experiment: str = "nsd1w",
    probe_plan: dict[str, str] | None = None,
    date: str = "251024",
) -> Session:
    session_dir = tmp_path / "Run_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "task.bhv2"
    bhv_file.write_bytes(b"\x00" * 16)
    # Use `is None` so an explicit empty dict is forwarded (for validation tests).
    plan = _SENTINEL if probe_plan is None else probe_plan
    return SessionManager.create(
        session_dir,
        bhv_file,
        _subject(),
        tmp_path / "out",
        experiment=experiment,
        probe_plan=plan,
        date=date,
    )


# ── Group A — SessionID dataclass invariants ────────────────────────────


class TestSessionIDInvariants:
    def test_canonical_format(self) -> None:
        sid = SessionID(date="251024", subject="MaoDan", experiment="nsd1w", region="MSB-V4")
        assert sid.canonical() == "251024_MaoDan_nsd1w_MSB-V4"

    def test_frozen(self) -> None:
        sid = SessionID(date="251024", subject="MaoDan", experiment="nsd1w", region="V4")
        with pytest.raises(FrozenInstanceError):
            sid.date = "260101"  # type: ignore[misc]

    def test_to_dict_roundtrip(self) -> None:
        sid = SessionID(date="251024", subject="MaoDan", experiment="nsd1w", region="MSB-V4")
        assert SessionID(**sid.to_dict()) == sid

    def test_derive_region_sorted_by_probe_id(self) -> None:
        # Unsorted input must produce deterministic sorted output.
        assert SessionID.derive_region({"imec1": "V4", "imec0": "MSB"}) == "MSB-V4"

    def test_derive_region_single_probe(self) -> None:
        assert SessionID.derive_region({"imec0": "V4"}) == "V4"

    def test_derive_region_preserves_duplicates(self) -> None:
        assert SessionID.derive_region({"imec0": "V4", "imec1": "V4"}) == "V4-V4"

    def test_derive_region_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="probe_plan is empty"):
            SessionID.derive_region({})


# ── Group B — SessionManager.create validation ──────────────────────────


class TestCreateValidation:
    def test_happy_path_builds_canonical(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path)
        assert s.session_id.canonical() == "251024_MaoDan_nsd1w_MSB-V4"
        assert s.experiment == "nsd1w"
        assert s.probe_plan == {"imec0": "MSB", "imec1": "V4"}

    def test_empty_experiment_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="experiment"):
            _make_session(tmp_path, experiment="")

    def test_empty_probe_plan_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="probe_plan"):
            _make_session(tmp_path, probe_plan={})

    def test_bad_probe_key_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="imec"):
            _make_session(tmp_path, probe_plan={"probe0": "V4"})

    def test_bad_date_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="date"):
            _make_session(tmp_path, date="2025-10-24")


# ── Group C — Persistence roundtrip ─────────────────────────────────────


class TestPersistenceContract:
    def test_save_load_preserves_session_id(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path)
        SessionManager.save(s)
        loaded = SessionManager.load(s.output_dir)
        assert loaded.session_id == s.session_id
        assert loaded.session_id.canonical() == "251024_MaoDan_nsd1w_MSB-V4"

    def test_save_load_preserves_probe_plan(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, probe_plan={"imec0": "V4", "imec1": "IT", "imec2": "V1"})
        SessionManager.save(s)
        loaded = SessionManager.load(s.output_dir)
        assert loaded.probe_plan == {"imec0": "V4", "imec1": "IT", "imec2": "V1"}
        assert loaded.session_id.region == "V4-IT-V1"

    def test_save_load_preserves_probe_target_area(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path)
        s.probes = [
            ProbeInfo(
                probe_id="imec0",
                ap_bin=tmp_path / "imec0.ap.bin",
                ap_meta=tmp_path / "imec0.ap.meta",
                lf_bin=None,
                lf_meta=None,
                sample_rate=30000.0,
                n_channels=384,
                probe_type="NP1010",
                serial_number="SN001",
                target_area="MSB",
            )
        ]
        SessionManager.save(s)
        loaded = SessionManager.load(s.output_dir)
        assert loaded.probes[0].target_area == "MSB"


# ── Group D — read_recording_date ───────────────────────────────────────


class TestReadRecordingDateContract:
    def test_iso_t_separator(self, tmp_path: Path) -> None:
        meta = tmp_path / "run_g0_t0.imec0.ap.meta"
        _write_ap_meta(meta, "2025-10-24T14:30:00")
        assert SpikeGLXLoader.read_recording_date(meta) == "251024"

    def test_iso_space_separator(self, tmp_path: Path) -> None:
        meta = tmp_path / "run_g0_t0.imec0.ap.meta"
        _write_ap_meta(meta, "2025-10-24 14:30:00")
        assert SpikeGLXLoader.read_recording_date(meta) == "251024"

    def test_date_flows_into_session_id(self, tmp_path: Path) -> None:
        # End-to-end: meta → read_recording_date → SessionManager.create → canonical()
        meta = tmp_path / "run_g0_t0.imec0.ap.meta"
        _write_ap_meta(meta, "2024-01-15T09:00:00")
        yymmdd = SpikeGLXLoader.read_recording_date(meta)
        s = _make_session(tmp_path, date=yymmdd, probe_plan={"imec0": "V4"})
        assert s.session_id.canonical() == "240115_MaoDan_nsd1w_V4"


# ── Group E — Discover injects target_area from probe_plan (S2) ─────────


def _placeholder_probe(probe_id: str, base: Path) -> ProbeInfo:
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=base / f"{probe_id}.ap.bin",
        ap_meta=base / f"{probe_id}.ap.meta",
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=385,
        serial_number="sn",
        probe_type="NP1010",
        target_area="",  # placeholder — discover must overwrite
    )


class TestDiscoverInjectionContract:
    def _session_with_bhv(self, tmp_path: Path, probe_plan: dict[str, str]) -> Session:
        session_dir = tmp_path / "Run_g0"
        session_dir.mkdir()
        bhv_file = tmp_path / "task.bhv2"
        bhv_file.write_bytes(BHV2_MAGIC + b"\x00" * 50)
        return SessionManager.create(
            session_dir,
            bhv_file,
            _subject(),
            tmp_path / "out",
            experiment="nsd1w",
            probe_plan=probe_plan,
            date="251024",
        )

    def test_target_area_populated_after_discover(self, tmp_path: Path) -> None:
        s = self._session_with_bhv(tmp_path, {"imec0": "MSB", "imec1": "V4"})
        placeholders = [
            _placeholder_probe("imec0", tmp_path),
            _placeholder_probe("imec1", tmp_path),
        ]
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            mock = mock_cls.return_value
            mock.discover_probes.return_value = placeholders
            mock.validate_probe.return_value = []
            mock.discover_nidq.return_value = (tmp_path / "nidq.bin", tmp_path / "nidq.meta")
            DiscoverStage(s).run()

        assert s.probes[0].target_area == "MSB"
        assert s.probes[1].target_area == "V4"

    def test_mismatch_raises(self, tmp_path: Path) -> None:
        s = self._session_with_bhv(tmp_path, {"imec0": "MSB", "imec1": "V4"})
        only_imec0 = [_placeholder_probe("imec0", tmp_path)]
        with patch("pynpxpipe.stages.discover.SpikeGLXDiscovery") as mock_cls:
            mock = mock_cls.return_value
            mock.discover_probes.return_value = only_imec0
            mock.validate_probe.return_value = []
            mock.discover_nidq.return_value = (tmp_path / "nidq.bin", tmp_path / "nidq.meta")
            with pytest.raises(ProbeDeclarationMismatchError):
                DiscoverStage(s).run()


# ── Group F — NWB output uses canonical() (S2) ──────────────────────────


class TestNWBCanonicalContract:
    def test_export_output_path_equals_canonical_nwb(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, probe_plan={"imec0": "V4"})
        s.probes = [
            ProbeInfo(
                probe_id="imec0",
                ap_bin=tmp_path / "ap.bin",
                ap_meta=tmp_path / "ap.meta",
                lf_bin=None,
                lf_meta=None,
                sample_rate=30000.0,
                n_channels=384,
                serial_number="sn",
                probe_type="NP1010",
                target_area="V4",
            )
        ]
        stage = ExportStage.__new__(ExportStage)
        stage.session = s
        stage.STAGE_NAME = "export"
        assert stage._get_output_path().name == "251024_MaoDan_nsd1w_V4.nwb"

    def test_nwbfile_session_id_equals_canonical(self, tmp_path: Path) -> None:
        # Build a session with a real ap.meta so create_file can read fileCreateTime.
        meta_dir = tmp_path / "probes"
        meta_dir.mkdir()
        meta = meta_dir / "t0.imec0.ap.meta"
        _write_ap_meta(meta, "2025-10-24T14:30:00")

        s = _make_session(tmp_path, probe_plan={"imec0": "V4"})
        s.probes = [
            ProbeInfo(
                probe_id="imec0",
                ap_bin=meta.parent / "ap.bin",
                ap_meta=meta,
                lf_bin=None,
                lf_meta=None,
                sample_rate=30000.0,
                n_channels=384,
                serial_number="sn",
                probe_type="NP1010",
                target_area="V4",
            )
        ]
        writer = NWBWriter(s, tmp_path / "out.nwb")
        nwbfile = writer.create_file()
        assert nwbfile.session_id == s.session_id.canonical()
        assert s.session_id.canonical() in nwbfile.session_description

    def test_export_rejects_empty_target_area(self, tmp_path: Path) -> None:
        s = _make_session(tmp_path, probe_plan={"imec0": "V4"})
        s.probes = [
            ProbeInfo(
                probe_id="imec0",
                ap_bin=tmp_path / "ap.bin",
                ap_meta=tmp_path / "ap.meta",
                lf_bin=None,
                lf_meta=None,
                sample_rate=30000.0,
                n_channels=384,
                serial_number="sn",
                probe_type="NP1010",
                target_area="",
            )
        ]
        # Patch _is_complete to ensure the pre-flight check runs.
        with (
            patch.object(ExportStage, "_is_complete", return_value=False),
            pytest.raises(ExportError, match="target_area"),
        ):
            ExportStage(s).run()


# ── Group G — UI layer contracts (S3) ──────────────────────────────────


class TestUIContract:
    """End-to-end: AppState + SessionLoader + RunPanel obey the canonical pipeline."""

    def test_appstate_session_id_complete_matches_canonical(self) -> None:
        """Full-population AppState.session_id.canonical() equals the known string."""
        from pynpxpipe.ui.state import AppState

        state = AppState()
        state.subject_config = _subject()
        state.experiment = "nsd1w"
        state.recording_date = "251024"
        state.probe_plan = {"imec0": "MSB", "imec1": "V4"}
        sid = state.session_id
        assert sid is not None
        assert sid.canonical() == "251024_MaoDan_nsd1w_MSB-V4"

    def test_appstate_session_id_none_when_any_blank(self) -> None:
        """Any missing field keeps the property at None so RunPanel gating stays active."""
        from pynpxpipe.ui.state import AppState

        state = AppState()
        # subject only
        state.subject_config = _subject()
        assert state.session_id is None
        # + experiment
        state.experiment = "nsd1w"
        assert state.session_id is None
        # + date, but probe_plan still {"imec0": ""}
        state.recording_date = "251024"
        assert state.session_id is None
        # + region fills in the last blank
        state.probe_plan = {"imec0": "V4"}
        assert state.session_id is not None

    def test_session_loader_restores_nwb_fields_from_session_json(self, tmp_path: Path) -> None:
        """SessionLoader writes experiment/date/probe_plan from session.json into AppState."""
        from pynpxpipe.ui.components.session_loader import SessionLoader
        from pynpxpipe.ui.state import AppState

        # Build a canonical session.json by going through SessionManager.create + save.
        s = _make_session(tmp_path)
        SessionManager.save(s)

        state = AppState()
        loader = SessionLoader(state)
        loader.dir_input.value = str(s.output_dir)
        loader._on_load_click(None)

        assert state.experiment == s.session_id.experiment
        assert state.recording_date == s.session_id.date
        assert state.probe_plan == dict(s.probe_plan)
        # session_id property should now be populated.
        state.subject_config = s.subject
        assert state.session_id is not None
        assert state.session_id.canonical() == s.session_id.canonical()

    def test_run_panel_blocks_run_when_any_field_missing(self, tmp_path: Path) -> None:
        """If any NWB field is blank the background thread never starts."""
        from pynpxpipe.ui.components.run_panel import RunPanel
        from pynpxpipe.ui.state import AppState

        state = AppState()
        session_dir = tmp_path / "run_g0"
        session_dir.mkdir()
        state.session_dir = session_dir
        state.output_dir = tmp_path / "out"
        state.subject_config = _subject()
        state.experiment = ""  # missing
        state.recording_date = "251024"
        state.probe_plan = {"imec0": "V4"}

        called: list[bool] = []
        rp = RunPanel(state, pipeline_fn=lambda st, br: called.append(True))
        rp._on_run_click(None)
        assert rp._thread is None
        assert rp.validation_alert.visible is True
        assert called == []
