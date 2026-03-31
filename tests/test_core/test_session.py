"""Tests for core/session.py — Session dataclass, SessionManager lifecycle.

Groups:
  A. Dataclasses (SubjectConfig, ProbeInfo, Session log_path)
  B. SessionManager.from_data_dir() — auto-discovery
  C. SessionManager.create() — explicit path control
  D. SessionManager.save() — serialization
  E. SessionManager.load() — deserialization
  F. Roundtrip — create → save → load equivalence
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from pynpxpipe.core.session import (
    ProbeInfo,
    Session,
    SessionManager,
    SubjectConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="MaoDan",
        description="good monkey",
        species="Macaca mulatta",
        sex="M",
        age="P4Y",
        weight="12.8kg",
    )


def _make_probe(tmp_path: Path, probe_id: str = "imec0") -> ProbeInfo:
    ap_bin = tmp_path / f"probe_{probe_id}" / "xxx.ap.bin"
    ap_bin.parent.mkdir(parents=True, exist_ok=True)
    ap_bin.touch()
    ap_meta = ap_bin.with_suffix(".meta")
    ap_meta.touch()
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=ap_bin,
        ap_meta=ap_meta,
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=384,
        probe_type="NP1010",
        serial_number="123456",
    )


def _make_data_dir(tmp_path: Path, name: str = "MaoDan_20240101") -> tuple[Path, Path, Path]:
    """Create a fake SpikeGLX data directory.

    Returns: (data_dir, session_dir, bhv_file)
    """
    data_dir = tmp_path / name
    data_dir.mkdir()
    session_dir = data_dir / f"{name}_g0"
    session_dir.mkdir()
    (session_dir / f"{name}_g0_imec0").mkdir()
    bhv_file = data_dir / f"{name}.bhv2"
    bhv_file.touch()
    return data_dir, session_dir, bhv_file


# ---------------------------------------------------------------------------
# Group A — Dataclasses
# ---------------------------------------------------------------------------

class TestSubjectConfig:
    def test_all_fields_stored(self):
        sub = _make_subject()
        assert sub.subject_id == "MaoDan"
        assert sub.description == "good monkey"
        assert sub.species == "Macaca mulatta"
        assert sub.sex == "M"
        assert sub.age == "P4Y"
        assert sub.weight == "12.8kg"

    def test_missing_field_raises_type_error(self):
        with pytest.raises(TypeError):
            SubjectConfig(subject_id="MaoDan")  # missing required fields


class TestProbeInfo:
    def test_channel_positions_defaults_to_none(self, tmp_path):
        probe = _make_probe(tmp_path)
        assert probe.channel_positions is None

    def test_lf_bin_defaults_to_none(self, tmp_path):
        probe = _make_probe(tmp_path)
        assert probe.lf_bin is None

    def test_required_fields_stored(self, tmp_path):
        probe = _make_probe(tmp_path)
        assert probe.probe_id == "imec0"
        assert probe.sample_rate == 30000.0
        assert probe.n_channels == 384
        assert probe.probe_type == "NP1010"


class TestSessionLogPath:
    def test_log_path_set_by_post_init(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        session = Session(
            session_dir=session_dir,
            output_dir=output_dir,
            subject=_make_subject(),
            bhv_file=bhv_file,
        )
        expected = output_dir / "logs" / f"pynpxpipe_{session_dir.name}.log"
        assert session.log_path == expected

    def test_log_path_uses_session_dir_name(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path, name="SubjectX_20250101")
        output_dir = tmp_path / "output"
        session = Session(
            session_dir=session_dir,
            output_dir=output_dir,
            subject=_make_subject(),
            bhv_file=bhv_file,
        )
        assert "SubjectX_20250101_g0" in session.log_path.name

    def test_log_path_not_accepted_as_constructor_arg(self, tmp_path):
        """log_path is field(init=False); passing it should raise TypeError."""
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        with pytest.raises(TypeError):
            Session(
                session_dir=session_dir,
                output_dir=tmp_path / "output",
                subject=_make_subject(),
                bhv_file=bhv_file,
                log_path=tmp_path / "custom.log",  # should not be accepted
            )


# ---------------------------------------------------------------------------
# Group B — from_data_dir()
# ---------------------------------------------------------------------------

class TestFromDataDir:
    def test_discovers_session_dir_and_bhv_file(self, tmp_path):
        data_dir, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        session = SessionManager.from_data_dir(data_dir, _make_subject(), output_dir)
        assert session.session_dir == session_dir
        assert session.bhv_file == bhv_file

    def test_data_dir_not_exist_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            SessionManager.from_data_dir(
                tmp_path / "nonexistent", _make_subject(), tmp_path / "output"
            )

    def test_no_gate_dir_raises_file_not_found(self, tmp_path):
        data_dir = tmp_path / "no_gate"
        data_dir.mkdir()
        (data_dir / "session.bhv2").touch()
        with pytest.raises(FileNotFoundError):
            SessionManager.from_data_dir(data_dir, _make_subject(), tmp_path / "output")

    def test_no_bhv2_file_raises_file_not_found(self, tmp_path):
        data_dir = tmp_path / "no_bhv"
        data_dir.mkdir()
        (data_dir / "session_g0").mkdir()
        with pytest.raises(FileNotFoundError):
            SessionManager.from_data_dir(data_dir, _make_subject(), tmp_path / "output")

    def test_multiple_gates_takes_first_alphabetically(self, tmp_path):
        data_dir = tmp_path / "multi_gate"
        data_dir.mkdir()
        (data_dir / "sess_g0").mkdir()
        (data_dir / "sess_g1").mkdir()
        (data_dir / "sess.bhv2").touch()
        session = SessionManager.from_data_dir(data_dir, _make_subject(), tmp_path / "out")
        assert session.session_dir.name == "sess_g0"

    def test_multiple_gates_emits_warning(self, tmp_path, caplog):
        data_dir = tmp_path / "multi_gate2"
        data_dir.mkdir()
        (data_dir / "sess_g0").mkdir()
        (data_dir / "sess_g1").mkdir()
        (data_dir / "sess.bhv2").touch()
        with caplog.at_level(logging.WARNING):
            SessionManager.from_data_dir(data_dir, _make_subject(), tmp_path / "out2")
        assert any(r.levelno >= logging.WARNING for r in caplog.records)


# ---------------------------------------------------------------------------
# Group C — create()
# ---------------------------------------------------------------------------

class TestCreate:
    def test_creates_checkpoints_and_logs_dirs(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        assert (output_dir / "checkpoints").is_dir()
        assert (output_dir / "logs").is_dir()

    def test_writes_session_json(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        assert (output_dir / "session.json").exists()

    def test_returns_session_with_empty_probes_and_checkpoint(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        session = SessionManager.create(session_dir, bhv_file, _make_subject(), tmp_path / "out")
        assert session.probes == []
        assert session.checkpoint == {}

    def test_session_dir_not_exist_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            SessionManager.create(
                tmp_path / "no_such_dir",
                tmp_path / "x.bhv2",
                _make_subject(),
                tmp_path / "out",
            )

    def test_bhv_file_not_exist_raises(self, tmp_path):
        _, session_dir, _ = _make_data_dir(tmp_path)
        with pytest.raises(FileNotFoundError):
            SessionManager.create(
                session_dir,
                tmp_path / "no_such.bhv2",
                _make_subject(),
                tmp_path / "out",
            )

    def test_output_dir_created_if_missing(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        nested = tmp_path / "deep" / "nested" / "output"
        assert not nested.exists()
        SessionManager.create(session_dir, bhv_file, _make_subject(), nested)
        assert nested.is_dir()


# ---------------------------------------------------------------------------
# Group D — save()
# ---------------------------------------------------------------------------

class TestSave:
    def test_paths_serialized_as_strings(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        data = json.loads((output_dir / "session.json").read_text(encoding="utf-8"))
        assert isinstance(data["session_dir"], str)
        assert isinstance(data["bhv_file"], str)

    def test_log_path_not_in_json(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        data = json.loads((output_dir / "session.json").read_text(encoding="utf-8"))
        assert "log_path" not in data

    def test_none_lf_bin_serialized_as_null(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        session = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        session.probes.append(_make_probe(tmp_path, "imec0"))
        SessionManager.save(session)
        data = json.loads((output_dir / "session.json").read_text(encoding="utf-8"))
        assert data["probes"][0]["lf_bin"] is None

    def test_channel_positions_serialized_as_list_of_lists(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        session = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        probe = _make_probe(tmp_path, "imec0")
        probe.channel_positions = [(0.0, 0.0), (16.0, 20.0)]
        session.probes.append(probe)
        SessionManager.save(session)
        data = json.loads((output_dir / "session.json").read_text(encoding="utf-8"))
        assert data["probes"][0]["channel_positions"] == [[0.0, 0.0], [16.0, 20.0]]


# ---------------------------------------------------------------------------
# Group E — load()
# ---------------------------------------------------------------------------

class TestLoad:
    def test_restores_subject_fields(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        loaded = SessionManager.load(output_dir)
        assert loaded.subject.subject_id == "MaoDan"
        assert loaded.subject.species == "Macaca mulatta"

    def test_restores_path_fields(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        original = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        loaded = SessionManager.load(output_dir)
        assert loaded.session_dir == original.session_dir
        assert loaded.output_dir == original.output_dir
        assert loaded.bhv_file == original.bhv_file

    def test_log_path_reconstructed(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        original = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        loaded = SessionManager.load(output_dir)
        assert loaded.log_path == original.log_path

    def test_missing_session_json_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            SessionManager.load(tmp_path / "no_session")

    def test_corrupt_json_raises_value_error(self, tmp_path):
        output_dir = tmp_path / "corrupt"
        output_dir.mkdir()
        (output_dir / "session.json").write_text("not valid json {{{", encoding="utf-8")
        with pytest.raises(ValueError):
            SessionManager.load(output_dir)

    def test_missing_required_key_raises_value_error(self, tmp_path):
        output_dir = tmp_path / "incomplete"
        output_dir.mkdir()
        (output_dir / "session.json").write_text(
            json.dumps({"session_dir": "/some/path"}), encoding="utf-8"
        )
        with pytest.raises(ValueError):
            SessionManager.load(output_dir)


# ---------------------------------------------------------------------------
# Group F — Roundtrip
# ---------------------------------------------------------------------------

class TestRoundtrip:
    def test_create_save_load_equivalent(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        original = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        original.probes.append(_make_probe(tmp_path, "imec0"))
        original.checkpoint["discover"] = True
        SessionManager.save(original)

        loaded = SessionManager.load(output_dir)
        assert len(loaded.probes) == 1
        assert loaded.probes[0].probe_id == "imec0"
        assert loaded.probes[0].sample_rate == 30000.0
        assert loaded.probes[0].lf_bin is None
        assert loaded.checkpoint == {"discover": True}

    def test_roundtrip_preserves_channel_positions(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        session = SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        probe = _make_probe(tmp_path, "imec0")
        probe.channel_positions = [(0.0, 0.0), (16.0, 20.0)]
        session.probes.append(probe)
        SessionManager.save(session)

        loaded = SessionManager.load(output_dir)
        assert loaded.probes[0].channel_positions == [(0.0, 0.0), (16.0, 20.0)]

    def test_roundtrip_preserves_subject_all_fields(self, tmp_path):
        _, session_dir, bhv_file = _make_data_dir(tmp_path)
        output_dir = tmp_path / "output"
        SessionManager.create(session_dir, bhv_file, _make_subject(), output_dir)
        loaded = SessionManager.load(output_dir)
        s = loaded.subject
        assert s.subject_id == "MaoDan"
        assert s.description == "good monkey"
        assert s.species == "Macaca mulatta"
        assert s.sex == "M"
        assert s.age == "P4Y"
        assert s.weight == "12.8kg"
