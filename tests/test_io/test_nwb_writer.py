"""Tests for io/nwb_writer.py — NWBWriter.

Groups:
  A. __init__         — stores fields, _nwbfile is None
  B. create_file      — NWBFile created, fields correct, validation errors
  C. add_probe_data   — electrodes, units, slay_score, two probes, errors
  D. add_trials       — trials table, errors
  E. add_lfp          — always NotImplementedError
  F. write            — parent dir, file written, readable, errors
  G. Integration      — create → add_probe×2 → add_trials → write → read
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.io.nwb_writer import NWBWriter

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_N_SAMPLES = 82
_N_CHANNELS = 4


def _make_subject(
    subject_id: str = "monkey01",
    species: str = "Macaca mulatta",
    sex: str = "M",
    age: str = "P5Y",
) -> SubjectConfig:
    return SubjectConfig(
        subject_id=subject_id,
        description="Test macaque",
        species=species,
        sex=sex,
        age=age,
        weight="8.5kg",
    )


def _make_probe(
    probe_id: str,
    ap_meta: Path,
    n_ch: int = _N_CHANNELS,
) -> ProbeInfo:
    positions = [(float(i * 16), float(i * 20)) for i in range(n_ch)]
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=ap_meta.parent / f"{probe_id}.ap.bin",
        ap_meta=ap_meta,
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=n_ch,
        serial_number="SN001",
        probe_type="NP1010",
        channel_positions=positions,
    )


def _make_meta_file(path: Path, create_time: str = "2024-01-15T14:30:00") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    meta = path / "imec0.ap.meta"
    meta.write_text(
        f"typeThis=imec\nfileCreateTime={create_time}\nniSampRate=30000\n",
        encoding="utf-8",
    )
    return meta


def _make_mock_analyzer(
    n_units: int = 2,
    n_samples: int = _N_SAMPLES,
    n_channels: int = _N_CHANNELS,
    include_slay: bool = False,
    missing_extensions: list[str] | None = None,
) -> MagicMock:
    """Mock SortingAnalyzer with realistic return values."""
    missing = set(missing_extensions or [])
    unit_ids = [f"u{i}" for i in range(n_units)]

    mock_sorting = MagicMock()
    mock_sorting.get_unit_ids.return_value = unit_ids
    mock_sorting.get_unit_spike_train.return_value = np.array([0.1, 0.2, 0.5])

    # Templates: (n_units, n_samples, n_channels) — used for both mean and std
    templates_data = np.random.randn(n_units, n_samples, n_channels).astype(np.float32)
    mock_templates = MagicMock()
    mock_templates.get_templates.return_value = templates_data

    # Unit locations: (n_units, 3)
    locations = np.column_stack(
        [
            np.arange(n_units, dtype=float),
            np.zeros(n_units),
            np.zeros(n_units),
        ]
    )
    mock_locs = MagicMock()
    mock_locs.get_data.return_value = locations

    # Quality metrics DataFrame
    qm_cols: dict[str, list] = {
        "isi_violation_ratio": [0.05] * n_units,
        "amplitude_cutoff": [0.05] * n_units,
        "presence_ratio": [0.95] * n_units,
        "snr": [1.0] * n_units,
    }
    if include_slay:
        qm_cols["slay_score"] = [0.8] * n_units
    qm_df = pd.DataFrame(qm_cols, index=unit_ids)
    mock_qm = MagicMock()
    mock_qm.get_data.return_value = qm_df

    all_extensions = {"waveforms", "templates", "unit_locations", "quality_metrics"}
    available = all_extensions - missing

    def has_extension(name: str) -> bool:
        return name in available

    def get_extension(name: str) -> MagicMock:
        if name not in available:
            raise KeyError(f"Extension {name!r} not computed")
        return {
            "templates": mock_templates,
            "waveforms": mock_templates,
            "unit_locations": mock_locs,
            "quality_metrics": mock_qm,
        }[name]

    mock_analyzer = MagicMock()
    mock_analyzer.sorting = mock_sorting
    mock_analyzer.has_extension.side_effect = has_extension
    mock_analyzer.get_extension.side_effect = get_extension

    return mock_analyzer


def _make_behavior_df(n_trials: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trial_id": list(range(n_trials)),
            "onset_nidq_s": [float(i) for i in range(n_trials)],
            "stim_onset_nidq_s": [float(i) + 0.1 for i in range(n_trials)],
            "condition_id": [1] * n_trials,
            "trial_valid": [True] * n_trials,
        }
    )


@pytest.fixture
def meta_path(tmp_path: Path) -> Path:
    return _make_meta_file(tmp_path)


@pytest.fixture
def probe(tmp_path: Path, meta_path: Path) -> ProbeInfo:
    return _make_probe("imec0", meta_path)


@pytest.fixture
def subject() -> SubjectConfig:
    return _make_subject()


@pytest.fixture
def session(tmp_path: Path, probe: ProbeInfo, subject: SubjectConfig) -> Session:
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv = tmp_path / "test.bhv2"
    bhv.write_bytes(b"\x00" * 30)
    s = SessionManager.create(session_dir, bhv, subject, tmp_path / "output")
    s.probes = [probe]
    return s


@pytest.fixture
def writer(session: Session, tmp_path: Path) -> NWBWriter:
    return NWBWriter(session, tmp_path / "output.nwb")


# ---------------------------------------------------------------------------
# Group A — __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_nwbfile_is_none_on_init(self, writer: NWBWriter) -> None:
        assert writer._nwbfile is None

    def test_stores_output_path(self, writer: NWBWriter, tmp_path: Path) -> None:
        assert writer.output_path == tmp_path / "output.nwb"

    def test_stores_session(self, writer: NWBWriter, session: Session) -> None:
        assert writer.session is session


# ---------------------------------------------------------------------------
# Group B — create_file
# ---------------------------------------------------------------------------


class TestCreateFile:
    def test_returns_nwbfile_instance(self, writer: NWBWriter) -> None:
        import pynwb

        result = writer.create_file()
        assert isinstance(result, pynwb.NWBFile)

    def test_identifier_is_valid_uuid(self, writer: NWBWriter) -> None:
        nwbfile = writer.create_file()
        uuid.UUID(nwbfile.identifier)  # raises ValueError if not a valid UUID

    def test_session_description_contains_dir_name(
        self, writer: NWBWriter, session: Session
    ) -> None:
        nwbfile = writer.create_file()
        assert session.session_dir.name in nwbfile.session_description

    def test_subject_mapped_correctly(self, writer: NWBWriter, subject: SubjectConfig) -> None:
        nwbfile = writer.create_file()
        assert nwbfile.subject.subject_id == subject.subject_id
        assert nwbfile.subject.species == subject.species

    def test_session_start_time_is_aware_datetime(self, writer: NWBWriter) -> None:
        nwbfile = writer.create_file()
        assert nwbfile.session_start_time.tzinfo is not None

    def test_session_start_time_parsed_from_meta(self, writer: NWBWriter) -> None:
        nwbfile = writer.create_file()
        # meta has fileCreateTime=2024-01-15T14:30:00
        assert nwbfile.session_start_time.year == 2024
        assert nwbfile.session_start_time.month == 1
        assert nwbfile.session_start_time.day == 15

    def test_empty_subject_id_raises_value_error(self, session: Session, tmp_path: Path) -> None:
        session.subject = _make_subject(subject_id="")
        w = NWBWriter(session, tmp_path / "out.nwb")
        with pytest.raises(ValueError, match="subject_id"):
            w.create_file()

    def test_empty_species_raises_value_error(self, session: Session, tmp_path: Path) -> None:
        session.subject = _make_subject(species="")
        w = NWBWriter(session, tmp_path / "out.nwb")
        with pytest.raises(ValueError, match="species"):
            w.create_file()

    def test_empty_sex_raises_value_error(self, session: Session, tmp_path: Path) -> None:
        session.subject = _make_subject(sex="")
        w = NWBWriter(session, tmp_path / "out.nwb")
        with pytest.raises(ValueError, match="sex"):
            w.create_file()

    def test_empty_age_raises_value_error(self, session: Session, tmp_path: Path) -> None:
        session.subject = _make_subject(age="")
        w = NWBWriter(session, tmp_path / "out.nwb")
        with pytest.raises(ValueError, match="age"):
            w.create_file()


# ---------------------------------------------------------------------------
# Group C — add_probe_data
# ---------------------------------------------------------------------------


class TestAddProbeData:
    def test_electrode_group_created(self, writer: NWBWriter, probe: ProbeInfo) -> None:
        writer.create_file()
        writer.add_probe_data(probe, _make_mock_analyzer())
        assert probe.probe_id in writer._nwbfile.electrode_groups

    def test_units_contain_spike_times_and_probe_id(
        self, writer: NWBWriter, probe: ProbeInfo
    ) -> None:
        writer.create_file()
        writer.add_probe_data(probe, _make_mock_analyzer(n_units=2))
        units = writer._nwbfile.units
        assert units is not None
        assert "spike_times" in units.colnames
        assert "probe_id" in units.colnames

    def test_waveform_mean_is_2d_array(self, writer: NWBWriter, probe: ProbeInfo) -> None:
        writer.create_file()
        writer.add_probe_data(probe, _make_mock_analyzer(n_units=1))
        wf_data = writer._nwbfile.units["waveform_mean"].data
        # first unit's waveform should be (n_samples, n_channels)
        assert wf_data[0].shape == (_N_SAMPLES, _N_CHANNELS)

    def test_slay_score_is_nan_when_column_absent(
        self, writer: NWBWriter, probe: ProbeInfo
    ) -> None:
        writer.create_file()
        writer.add_probe_data(probe, _make_mock_analyzer(n_units=1, include_slay=False))
        slay_data = writer._nwbfile.units["slay_score"].data
        assert np.isnan(slay_data[0])

    def test_two_probes_both_electrode_groups_present(
        self,
        session: Session,
        tmp_path: Path,
    ) -> None:
        meta0 = _make_meta_file(tmp_path / "probe0")
        (tmp_path / "probe0").mkdir(exist_ok=True)
        meta1_dir = tmp_path / "probe1"
        meta1_dir.mkdir(exist_ok=True)
        meta1 = _make_meta_file(meta1_dir)

        probe0 = _make_probe("imec0", meta0)
        probe1 = _make_probe("imec1", meta1)
        session.probes = [probe0, probe1]

        w = NWBWriter(session, tmp_path / "out.nwb")
        w.create_file()
        w.add_probe_data(probe0, _make_mock_analyzer(n_units=2))
        w.add_probe_data(probe1, _make_mock_analyzer(n_units=3))

        assert "imec0" in w._nwbfile.electrode_groups
        assert "imec1" in w._nwbfile.electrode_groups
        assert len(w._nwbfile.units.id.data) == 5  # 2 + 3

    def test_add_probe_without_create_file_raises(
        self, session: Session, tmp_path: Path, probe: ProbeInfo
    ) -> None:
        w = NWBWriter(session, tmp_path / "out.nwb")
        with pytest.raises(RuntimeError, match="create_file"):
            w.add_probe_data(probe, _make_mock_analyzer())

    def test_missing_waveforms_raises_value_error(
        self, writer: NWBWriter, probe: ProbeInfo
    ) -> None:
        writer.create_file()
        bad_analyzer = _make_mock_analyzer(missing_extensions=["waveforms"])
        with pytest.raises(ValueError, match="waveforms"):
            writer.add_probe_data(probe, bad_analyzer)

    def test_missing_unit_locations_raises_value_error(
        self, writer: NWBWriter, probe: ProbeInfo
    ) -> None:
        writer.create_file()
        bad_analyzer = _make_mock_analyzer(missing_extensions=["unit_locations"])
        with pytest.raises(ValueError, match="unit_locations"):
            writer.add_probe_data(probe, bad_analyzer)


# ---------------------------------------------------------------------------
# Group D — add_trials
# ---------------------------------------------------------------------------


class TestAddTrials:
    def test_trials_table_has_correct_row_count(self, writer: NWBWriter) -> None:
        writer.create_file()
        writer.add_trials(_make_behavior_df(n_trials=3))
        trials = writer._nwbfile.trials
        assert trials is not None
        assert len(trials) == 3

    def test_trials_columns_present(self, writer: NWBWriter) -> None:
        writer.create_file()
        writer.add_trials(_make_behavior_df())
        colnames = writer._nwbfile.trials.colnames
        for col in ("stim_onset_time", "trial_id", "condition_id", "trial_valid"):
            assert col in colnames

    def test_add_trials_without_create_file_raises(self, session: Session, tmp_path: Path) -> None:
        w = NWBWriter(session, tmp_path / "out.nwb")
        with pytest.raises(RuntimeError, match="create_file"):
            w.add_trials(_make_behavior_df())

    def test_missing_trial_id_column_raises(self, writer: NWBWriter) -> None:
        writer.create_file()
        df = _make_behavior_df().drop(columns=["trial_id"])
        with pytest.raises(ValueError, match="trial_id"):
            writer.add_trials(df)

    def test_missing_onset_column_raises(self, writer: NWBWriter) -> None:
        writer.create_file()
        df = _make_behavior_df().drop(columns=["onset_nidq_s"])
        with pytest.raises(ValueError, match="onset_nidq_s"):
            writer.add_trials(df)


# ---------------------------------------------------------------------------
# Group E — add_lfp
# ---------------------------------------------------------------------------


class TestAddLfp:
    def test_always_raises_not_implemented(self, writer: NWBWriter, probe: ProbeInfo) -> None:
        lfp_data = np.zeros((1000, _N_CHANNELS))
        with pytest.raises(NotImplementedError, match="LFP"):
            writer.add_lfp(probe, lfp_data)


# ---------------------------------------------------------------------------
# Group F — write
# ---------------------------------------------------------------------------


class TestWrite:
    def test_creates_parent_directory(
        self, session: Session, probe: ProbeInfo, tmp_path: Path
    ) -> None:
        nested = tmp_path / "deep" / "nested" / "output.nwb"
        w = NWBWriter(session, nested)
        w.create_file()

        with patch("pynpxpipe.io.nwb_writer.NWBHDF5IO") as mock_io:
            mock_io.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_io.return_value.__exit__ = MagicMock(return_value=False)
            w.write()

        assert nested.parent.exists()

    def test_returns_output_path(self, writer: NWBWriter) -> None:
        writer.create_file()
        with patch("pynpxpipe.io.nwb_writer.NWBHDF5IO") as mock_io:
            mock_io.return_value.__enter__ = MagicMock(return_value=MagicMock())
            mock_io.return_value.__exit__ = MagicMock(return_value=False)
            result = writer.write()
        assert result == writer.output_path

    def test_write_without_create_file_raises(self, session: Session, tmp_path: Path) -> None:
        w = NWBWriter(session, tmp_path / "out.nwb")
        with pytest.raises(RuntimeError, match="create_file"):
            w.write()

    def test_written_file_is_readable(
        self, writer: NWBWriter, probe: ProbeInfo, tmp_path: Path
    ) -> None:
        """Integration: actual write to disk and read back."""
        import pynwb

        writer.create_file()
        writer.add_probe_data(probe, _make_mock_analyzer(n_units=1))
        writer.write()

        assert writer.output_path.exists()
        with pynwb.NWBHDF5IO(str(writer.output_path), mode="r") as io:
            nwbfile = io.read()
            assert nwbfile is not None


# ---------------------------------------------------------------------------
# Group G — Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_pipeline_two_probes(
        self,
        session: Session,
        tmp_path: Path,
    ) -> None:
        """create_file → add_probe×2 → add_trials → write → re-read.

        Verifies: 2 electrode groups, units from both probes, trials table.
        """
        import pynwb

        meta0_dir = tmp_path / "probe0"
        meta0_dir.mkdir(exist_ok=True)
        meta1_dir = tmp_path / "probe1"
        meta1_dir.mkdir(exist_ok=True)

        probe0 = _make_probe("imec0", _make_meta_file(meta0_dir))
        probe1 = _make_probe("imec1", _make_meta_file(meta1_dir))
        session.probes = [probe0, probe1]

        out_path = tmp_path / "session.nwb"
        w = NWBWriter(session, out_path)
        w.create_file()
        w.add_probe_data(probe0, _make_mock_analyzer(n_units=2))
        w.add_probe_data(probe1, _make_mock_analyzer(n_units=3))
        w.add_trials(_make_behavior_df(n_trials=5))
        w.write()

        assert out_path.exists()

        with pynwb.NWBHDF5IO(str(out_path), mode="r") as io:
            nwbfile = io.read()

        assert len(nwbfile.electrode_groups) == 2
        assert "imec0" in nwbfile.electrode_groups
        assert "imec1" in nwbfile.electrode_groups
        assert len(nwbfile.units) == 5
        assert len(nwbfile.trials) == 5
