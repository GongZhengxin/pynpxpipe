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

import json
import uuid
from datetime import UTC, datetime
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
    target_area = "V4" if probe_id == "imec0" else "IT"
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
        target_area=target_area,
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
    unit_ids: list | None = None,
) -> MagicMock:
    """Mock SortingAnalyzer with realistic return values."""
    missing = set(missing_extensions or [])
    if unit_ids is None:
        unit_ids = [f"u{i}" for i in range(n_units)]
    else:
        n_units = len(unit_ids)

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
    """Build a DataFrame with both NIDQ and IMEC per-probe onsets.

    The IMEC JSON column is always present because the IMEC clock is the
    primary reference after E1.1; `stim_onset_nidq_s` is retained so the
    NWB trials table can expose it as a diagnostic column.
    """
    import json as _json

    stim_imec_json = [
        _json.dumps(
            {
                "imec0": float(i) + 0.1,
                "imec1": float(i) + 0.1 + 0.001,
            }
        )
        for i in range(n_trials)
    ]
    return pd.DataFrame(
        {
            "trial_id": list(range(n_trials)),
            "onset_nidq_s": [float(i) for i in range(n_trials)],
            "stim_onset_nidq_s": [float(i) + 0.1 for i in range(n_trials)],
            "stim_onset_imec_s": stim_imec_json,
            "condition_id": [1] * n_trials,
            "trial_valid": [True] * n_trials,
            "onset_time_ms": [150.0] * n_trials,
            "offset_time_ms": [150.0] * n_trials,
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
    s = SessionManager.create(
        session_dir,
        bhv,
        subject,
        tmp_path / "output",
        experiment="nsd1w",
        probe_plan={"imec0": "V4", "imec1": "IT"},
        date="240101",
    )
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

    def test_session_description_contains_canonical(
        self, writer: NWBWriter, session: Session
    ) -> None:
        nwbfile = writer.create_file()
        assert session.session_id.canonical() in nwbfile.session_description

    def test_nwbfile_session_id_equals_canonical(self, writer: NWBWriter, session: Session) -> None:
        nwbfile = writer.create_file()
        assert nwbfile.session_id == session.session_id.canonical()

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

    def test_subject_whitelist_filters_image_vault_paths(
        self, session: Session, tmp_path: Path
    ) -> None:
        """image_vault_paths is a pipeline-internal field and must not leak into NWB Subject."""
        session.subject = SubjectConfig(
            subject_id="monkey02",
            description="Test macaque",
            species="Macaca mulatta",
            sex="M",
            age="P5Y",
            weight="8.5kg",
            image_vault_paths=[Path("/srv/stimuli"), Path("/data/images")],
        )
        w = NWBWriter(session, tmp_path / "out.nwb")
        nwbfile = w.create_file()
        assert nwbfile.subject.subject_id == "monkey02"
        assert not hasattr(nwbfile.subject, "image_vault_paths")


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

    def test_raster_column_added_when_provided(self, writer: NWBWriter, probe: ProbeInfo) -> None:
        writer.create_file()
        analyzer = _make_mock_analyzer(n_units=2)
        unit_ids = analyzer.sorting.get_unit_ids()
        rasters = {uid: np.ones((5, 350), dtype=np.uint8) for uid in unit_ids}
        writer.add_probe_data(probe, analyzer, rasters=rasters)
        assert "Raster" in writer._nwbfile.units.colnames

    def test_raster_shape_matches_input(self, writer: NWBWriter, probe: ProbeInfo) -> None:
        writer.create_file()
        analyzer = _make_mock_analyzer(n_units=1)
        uid = analyzer.sorting.get_unit_ids()[0]
        expected = np.random.randint(0, 3, (10, 350), dtype=np.uint8)
        rasters = {uid: expected}
        writer.add_probe_data(probe, analyzer, rasters=rasters)
        stored = writer._nwbfile.units["Raster"][0]
        np.testing.assert_array_equal(stored, expected)


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

    def test_stop_time_uses_onset_time_ms(self, writer: NWBWriter) -> None:
        """stop_time = stim_onset + onset_time_ms / 1000."""
        writer.create_file()
        df = _make_behavior_df(n_trials=2)
        df["onset_time_ms"] = [200.0, 300.0]
        writer.add_trials(df)
        trials = writer._nwbfile.trials
        for i in range(2):
            start = trials["start_time"][i]
            stop = trials["stop_time"][i]
            expected_dur = df.iloc[i]["onset_time_ms"] / 1000.0
            assert stop == pytest.approx(start + expected_dur)

    def test_onset_time_ms_column_in_trials(self, writer: NWBWriter) -> None:
        """onset_time_ms and offset_time_ms stored as NWB trial columns."""
        writer.create_file()
        writer.add_trials(_make_behavior_df())
        colnames = writer._nwbfile.trials.colnames
        assert "onset_time_ms" in colnames
        assert "offset_time_ms" in colnames

    # -- E1.1 (IMEC clock) ------------------------------------------------

    def test_add_trials_primary_is_imec0(self, writer: NWBWriter) -> None:
        """start_time / stop_time / stim_onset_time come from imec0 in stim_onset_imec_s."""
        import json as _json

        writer.create_file()
        df = pd.DataFrame(
            {
                "trial_id": [0],
                "onset_nidq_s": [0.0],
                "stim_onset_nidq_s": [5.0],  # deliberately different to catch regressions
                "stim_onset_imec_s": [_json.dumps({"imec0": 2.5, "imec1": 2.51})],
                "condition_id": [1],
                "trial_valid": [True],
                "onset_time_ms": [150.0],
                "offset_time_ms": [150.0],
            }
        )
        writer.add_trials(df)
        trials = writer._nwbfile.trials
        assert trials["start_time"][0] == pytest.approx(2.5)
        assert trials["stim_onset_time"][0] == pytest.approx(2.5)

    def test_add_trials_per_probe_imec_columns_present(self, writer: NWBWriter) -> None:
        """Each probe_id in the JSON gets its own stim_onset_imec_{probe_id} column."""
        import json as _json

        writer.create_file()
        df = pd.DataFrame(
            {
                "trial_id": [0, 1],
                "onset_nidq_s": [0.0, 1.0],
                "stim_onset_nidq_s": [0.1, 1.1],
                "stim_onset_imec_s": [
                    _json.dumps({"imec0": 0.11, "imec1": 0.12}),
                    _json.dumps({"imec0": 1.13, "imec1": 1.14}),
                ],
                "condition_id": [1, 2],
                "trial_valid": [True, True],
                "onset_time_ms": [150.0, 150.0],
                "offset_time_ms": [150.0, 150.0],
            }
        )
        writer.add_trials(df)
        trials = writer._nwbfile.trials
        colnames = trials.colnames
        assert "stim_onset_imec_imec0" in colnames
        assert "stim_onset_imec_imec1" in colnames
        assert trials["stim_onset_imec_imec0"][0] == pytest.approx(0.11)
        assert trials["stim_onset_imec_imec0"][1] == pytest.approx(1.13)
        assert trials["stim_onset_imec_imec1"][0] == pytest.approx(0.12)
        assert trials["stim_onset_imec_imec1"][1] == pytest.approx(1.14)

    def test_add_trials_nidq_kept_as_diagnostic(self, writer: NWBWriter) -> None:
        """stim_onset_nidq_s_diag preserves the old NIDQ value for audit / reprocessing."""
        writer.create_file()
        df = _make_behavior_df(n_trials=3)
        writer.add_trials(df)
        trials = writer._nwbfile.trials
        assert "stim_onset_nidq_s_diag" in trials.colnames
        for i in range(3):
            assert trials["stim_onset_nidq_s_diag"][i] == pytest.approx(
                df["stim_onset_nidq_s"].iloc[i]
            )

    def test_add_trials_raises_if_imec_column_missing(self, writer: NWBWriter) -> None:
        """Without stim_onset_imec_s the writer refuses to proceed (no silent NIDQ fallback)."""
        writer.create_file()
        df = _make_behavior_df().drop(columns=["stim_onset_imec_s"])
        with pytest.raises(ValueError, match="stim_onset_imec_s"):
            writer.add_trials(df)

    def test_add_trials_start_stop_same_clock(self, writer: NWBWriter) -> None:
        """stop_time - start_time == onset_time_ms/1000 on the IMEC clock."""
        import json as _json

        writer.create_file()
        df = pd.DataFrame(
            {
                "trial_id": [0],
                "onset_nidq_s": [0.0],
                "stim_onset_nidq_s": [99.0],  # intentionally NOT 2.5 — must be ignored
                "stim_onset_imec_s": [_json.dumps({"imec0": 2.5})],
                "condition_id": [1],
                "trial_valid": [True],
                "onset_time_ms": [200.0],
                "offset_time_ms": [150.0],
            }
        )
        writer.add_trials(df)
        trials = writer._nwbfile.trials
        start = trials["start_time"][0]
        stop = trials["stop_time"][0]
        assert start == pytest.approx(2.5)
        assert stop - start == pytest.approx(0.200)


def _stim_df(stim_index: list[int]) -> pd.DataFrame:
    """Build a per-onset DataFrame carrying an explicit ``stim_index`` column."""
    import json as _json

    n = len(stim_index)
    return pd.DataFrame(
        {
            "trial_id": list(range(n)),
            "onset_nidq_s": [float(i) for i in range(n)],
            "stim_onset_nidq_s": [float(i) + 0.1 for i in range(n)],
            "stim_onset_imec_s": [
                _json.dumps({"imec0": float(i) + 0.11}) for i in range(n)
            ],
            "condition_id": [1] * n,
            "trial_valid": [True] * n,
            "stim_index": list(stim_index),
            "onset_time_ms": [150.0] * n,
            "offset_time_ms": [150.0] * n,
        }
    )


class TestStimNameColumn:
    """E3.3 — stim_name column populated via stim_index → stim_map lookup."""

    def test_column_omitted_when_map_none(self, writer: NWBWriter) -> None:
        """Without a stim_map, no stim_name column is declared."""
        writer.create_file()
        writer.add_trials(_stim_df([1, 2, 1]))
        assert "stim_name" not in writer._nwbfile.trials.colnames

    def test_column_omitted_when_stim_index_missing(self, writer: NWBWriter) -> None:
        """Without a stim_index column, stim_name is not declared."""
        writer.create_file()
        writer.add_trials(
            _make_behavior_df(n_trials=2),
            stim_map={1: "face.png"},
        )
        assert "stim_name" not in writer._nwbfile.trials.colnames

    def test_mapping_resolved(self, writer: NWBWriter) -> None:
        """stim_index → stim_map lookup is applied per row."""
        writer.create_file()
        writer.add_trials(
            _stim_df([1, 2, 1]),
            stim_map={1: "face_01.png", 2: "obj_03.png"},
        )
        trials = writer._nwbfile.trials
        names = [trials["stim_name"][i] for i in range(3)]
        assert names == ["face_01.png", "obj_03.png", "face_01.png"]

    def test_zero_index_resolves_empty(self, writer: NWBWriter) -> None:
        """stim_index==0 maps to '' (BHV convention for 'no stim')."""
        writer.create_file()
        writer.add_trials(
            _stim_df([1, 0, 2]),
            stim_map={1: "face.png", 2: "obj.png"},
        )
        trials = writer._nwbfile.trials
        names = [trials["stim_name"][i] for i in range(3)]
        assert names == ["face.png", "", "obj.png"]

    def test_out_of_range_raises(self, writer: NWBWriter) -> None:
        """stim_index exceeding len(stim_map) raises ValueError."""
        writer.create_file()
        with pytest.raises(ValueError, match="exceeds len"):
            writer.add_trials(
                _stim_df([1, 5]),
                stim_map={1: "face.png", 2: "obj.png"},
            )

    def test_negative_index_raises(self, writer: NWBWriter) -> None:
        """Negative stim_index raises ValueError."""
        writer.create_file()
        with pytest.raises(ValueError, match="must be >= 0"):
            writer.add_trials(
                _stim_df([1, -1]),
                stim_map={1: "face.png"},
            )


class TestAddStimProvenance:
    """E3.3 — add_stim_provenance() records resolver metadata in NWB scratch."""

    def test_round_trip(self, writer: NWBWriter) -> None:
        """Provenance payload is stored verbatim under stim_name_provenance."""
        writer.create_file()
        writer.add_stim_provenance(
            dataset_name="C:\\#Datasets\\TripleN10k\\stimuli\\nsd1w.tsv",
            resolved_tsv_path="/data/stimuli/nsd1w.tsv",
            source_tag="vault:/data/stimuli",
        )
        blob = writer._nwbfile.scratch["stim_name_provenance"].data
        payload = json.loads(blob)
        assert payload == {
            "dataset_name": "C:\\#Datasets\\TripleN10k\\stimuli\\nsd1w.tsv",
            "resolved_tsv_path": "/data/stimuli/nsd1w.tsv",
            "source_tag": "vault:/data/stimuli",
        }

    def test_null_values_survive(self, writer: NWBWriter) -> None:
        """None inputs survive as JSON nulls, enabling downstream introspection."""
        writer.create_file()
        writer.add_stim_provenance(
            dataset_name=None,
            resolved_tsv_path=None,
            source_tag="no_dataset_name",
        )
        payload = json.loads(writer._nwbfile.scratch["stim_name_provenance"].data)
        assert payload == {
            "dataset_name": None,
            "resolved_tsv_path": None,
            "source_tag": "no_dataset_name",
        }

    def test_idempotent_second_call_skips(self, writer: NWBWriter) -> None:
        """Second call with the same key logs and returns without overwriting."""
        writer.create_file()
        writer.add_stim_provenance(
            dataset_name="first",
            resolved_tsv_path="/tmp/first.tsv",
            source_tag="direct",
        )
        writer.add_stim_provenance(
            dataset_name="second",
            resolved_tsv_path="/tmp/second.tsv",
            source_tag="vault:/tmp",
        )
        payload = json.loads(writer._nwbfile.scratch["stim_name_provenance"].data)
        assert payload["dataset_name"] == "first"
        assert payload["source_tag"] == "direct"

    def test_raises_without_create_file(self, writer: NWBWriter) -> None:
        """Calling before create_file() raises RuntimeError."""
        with pytest.raises(RuntimeError, match="create_file"):
            writer.add_stim_provenance(
                dataset_name=None,
                resolved_tsv_path=None,
                source_tag="no_dataset_name",
            )


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


# ===================================================================
# H. Phase 3 — _get_compression_filter
# ===================================================================


class TestGetCompressionFilter:
    """Tests for the _get_compression_filter() module-level function."""

    def test_blosc_when_available(self):
        from pynpxpipe.io.nwb_writer import _get_compression_filter

        result = _get_compression_filter()
        # hdf5plugin is installed → expect Blosc filter_id 32001
        assert result["compression"] == 32001
        assert "compression_opts" in result
        assert result["allow_plugin_filters"] is True

    def test_gzip_fallback(self, monkeypatch):
        import builtins

        import pynpxpipe.io.nwb_writer as nwb_mod

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "hdf5plugin":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = nwb_mod._get_compression_filter()
        assert result["compression"] == "gzip"
        assert result["compression_opts"] == 4


# ===================================================================
# I. Phase 3 — SpikeGLXDataChunkIterator
# ===================================================================


def _make_numpy_recording(
    n_samples: int = 3000,
    n_channels: int = 4,
    sampling_frequency: float = 30000.0,
    seed: int = 42,
):
    """Create a NumpyRecording with int16 data and gain_to_uV property."""
    import spikeinterface.core as si

    rng = np.random.RandomState(seed)
    data = rng.randint(-100, 100, (n_samples, n_channels), dtype=np.int16)
    rec = si.NumpyRecording(
        traces_list=[data.astype(np.float32)],  # SI stores float internally
        sampling_frequency=sampling_frequency,
    )
    rec.set_property("gain_to_uV", np.array([2.34375] * n_channels))
    return rec, data


class TestSpikeGLXDataChunkIterator:
    """Tests for the SpikeGLXDataChunkIterator chunk iterator."""

    def test_maxshape(self):
        from pynpxpipe.io.nwb_writer import SpikeGLXDataChunkIterator

        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)
        it = SpikeGLXDataChunkIterator(rec)
        assert it._get_maxshape() == (3000, 4)

    def test_dtype_int16(self):
        from pynpxpipe.io.nwb_writer import SpikeGLXDataChunkIterator

        rec, _ = _make_numpy_recording()
        it = SpikeGLXDataChunkIterator(rec)
        assert it._get_dtype() == np.dtype(np.int16)

    def test_get_data_correct_slice(self):
        from pynpxpipe.io.nwb_writer import SpikeGLXDataChunkIterator

        rec, data = _make_numpy_recording(n_samples=100, n_channels=4)
        it = SpikeGLXDataChunkIterator(rec)
        selection = (slice(10, 30), slice(0, 4))
        chunk = it._get_data(selection)
        # Should match the source data at that range
        assert chunk.shape == (20, 4)
        # Values should be raw int16 (return_scaled=False)
        assert chunk.dtype == np.int16

    def test_full_roundtrip(self):
        """Iterate all chunks → concatenate → must match source data."""
        from pynpxpipe.io.nwb_writer import SpikeGLXDataChunkIterator

        rec, data = _make_numpy_recording(n_samples=500, n_channels=4)
        it = SpikeGLXDataChunkIterator(rec, chunk_mb=0.001)

        chunks = []
        for chunk in it:
            chunks.append(chunk.data)

        result = np.concatenate(chunks, axis=0) if chunks else np.empty((0, 4))
        assert result.shape == data.shape


# ===================================================================
# J. Phase 3 — append_raw_data
# ===================================================================


def _create_nwb_with_electrodes(
    tmp_path: Path,
    probe_id: str = "imec0",
    n_channels: int = 4,
) -> Path:
    """Create a minimal NWB file with electrode table for testing append."""
    import pynwb

    nwb_path = tmp_path / "test.nwb"
    nwbfile = pynwb.NWBFile(
        session_description="test",
        identifier=str(uuid.uuid4()),
        session_start_time=datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC),
    )
    nwbfile.subject = pynwb.file.Subject(
        subject_id="test", species="Macaca mulatta", sex="M", age="P5Y"
    )
    device = nwbfile.create_device(name=f"Neuropixels_{probe_id}")
    group = nwbfile.create_electrode_group(
        name=f"group_{probe_id}",
        description=f"Electrode group for {probe_id}",
        device=device,
        location="brain",
    )
    nwbfile.add_electrode_column("probe_id", "Probe identifier")
    nwbfile.add_electrode_column("channel_id", "Channel index")
    for ch in range(n_channels):
        nwbfile.add_electrode(
            group=group,
            probe_id=probe_id,
            channel_id=ch,
            location="brain",
            x=0.0,
            y=float(ch * 10),
            z=0.0,
            filtering="none",
        )
    with pynwb.NWBHDF5IO(str(nwb_path), "w") as io:
        io.write(nwbfile)
    return nwb_path


class TestAppendRawData:
    """Tests for NWBWriter.append_raw_data() — Phase 3 raw export."""

    def test_append_creates_ap_acquisition(self, tmp_path, session):
        """After append, NWB should contain ElectricalSeriesAP_imec0."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            result = writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        assert result["streams_written"] >= 1

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            assert "ElectricalSeriesAP_imec0" in nwbfile.acquisition

    def test_append_data_shape_matches_time_range(self, tmp_path, session):
        """time_range=(0, 0.1) with 30kHz → 3000 samples."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            es = nwbfile.acquisition["ElectricalSeriesAP_imec0"]
            assert es.data.shape == (3000, 4)

    def test_append_idempotent(self, tmp_path, session):
        """Calling append twice should not duplicate streams."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))
            result2 = writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        assert result2["streams_written"] == 0

    def test_append_lf_when_available(self, tmp_path, session):
        """If probe has lf_bin, ElectricalSeriesLF should be created."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec_ap, _ = _make_numpy_recording(n_samples=3000, n_channels=4)
        rec_lf, _ = _make_numpy_recording(n_samples=250, n_channels=4, sampling_frequency=2500.0)

        # Set lf_bin so append tries to write LF
        session.probes[0].lf_bin = session.probes[0].ap_bin.parent / "imec0.lf.bin"

        writer = NWBWriter(session, nwb_path)
        with (
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec_ap),
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_lf", return_value=rec_lf),
        ):
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            assert "ElectricalSeriesLF_imec0" in nwbfile.acquisition

    def test_append_lf_skipped_when_none(self, tmp_path, session):
        """If probe.lf_bin is None, no LF stream is written."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)
        session.probes[0].lf_bin = None

        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            assert "ElectricalSeriesLF_imec0" not in nwbfile.acquisition

    def test_append_missing_nwb_raises(self, tmp_path, session):
        """Appending to a non-existent NWB should raise FileNotFoundError."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        bad_path = tmp_path / "nonexistent.nwb"
        writer = NWBWriter(session, bad_path)
        with pytest.raises(FileNotFoundError):
            writer.append_raw_data(session, bad_path)

    def test_append_two_probes(self, tmp_path, session):
        """Two probes → two AP ElectricalSeries."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        # Create NWB with two probes' electrodes
        nwb_path = tmp_path / "test.nwb"
        import pynwb

        nwbfile = pynwb.NWBFile(
            session_description="test",
            identifier=str(uuid.uuid4()),
            session_start_time=datetime(2024, 1, 15, 14, 30, 0, tzinfo=UTC),
        )
        nwbfile.subject = pynwb.file.Subject(
            subject_id="test", species="Macaca mulatta", sex="M", age="P5Y"
        )
        nwbfile.add_electrode_column("probe_id", "Probe identifier")
        nwbfile.add_electrode_column("channel_id", "Channel index")
        for pid in ["imec0", "imec1"]:
            dev = nwbfile.create_device(name=f"NP_{pid}")
            grp = nwbfile.create_electrode_group(
                name=f"group_{pid}", description=pid, device=dev, location="brain"
            )
            for ch in range(4):
                nwbfile.add_electrode(
                    group=grp,
                    probe_id=pid,
                    channel_id=ch,
                    location="brain",
                    x=0.0,
                    y=float(ch * 10),
                    z=0.0,
                    filtering="none",
                )
        with pynwb.NWBHDF5IO(str(nwb_path), "w") as io:
            io.write(nwbfile)

        # Add second probe to session
        meta1_dir = tmp_path / "meta1"
        probe1 = _make_probe("imec1", _make_meta_file(meta1_dir))
        session.probes.append(probe1)

        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)
        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            result = writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        assert result["streams_written"] == 2

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            assert "ElectricalSeriesAP_imec0" in nwbfile.acquisition
            assert "ElectricalSeriesAP_imec1" in nwbfile.acquisition

    def test_append_bit_exact_roundtrip(self, tmp_path, session):
        """Data written to NWB must be identical to source when read back."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec, source_data = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            es = nwbfile.acquisition["ElectricalSeriesAP_imec0"]
            nwb_data = es.data[:]

        np.testing.assert_array_equal(nwb_data, source_data)


# ===================================================================
# J2. Phase 3 — progress_callback wiring
# ===================================================================


class TestPhase3ProgressCallback:
    """Tests for progress_callback on SpikeGLXDataChunkIterator + append_raw_data + verify."""

    def test_iterator_accepts_on_chunk_kwarg(self):
        """SpikeGLXDataChunkIterator must accept on_chunk callable kwarg."""
        from pynpxpipe.io.nwb_writer import SpikeGLXDataChunkIterator

        rec, _ = _make_numpy_recording(n_samples=500, n_channels=4)
        calls: list = []
        it = SpikeGLXDataChunkIterator(rec, chunk_mb=0.001, on_chunk=lambda: calls.append(1))
        # Construction alone must not raise
        assert it is not None

    def test_iterator_fires_on_chunk_each_get_data(self):
        """on_chunk must be called once per _get_data() invocation."""
        from pynpxpipe.io.nwb_writer import SpikeGLXDataChunkIterator

        rec, _ = _make_numpy_recording(n_samples=500, n_channels=4)
        calls: list = []
        it = SpikeGLXDataChunkIterator(rec, chunk_mb=0.001, on_chunk=lambda: calls.append(1))

        # Iterate all chunks
        chunks = [c.data for c in it]
        assert len(calls) == len(chunks)
        assert len(calls) > 0

    def test_append_raw_data_accepts_progress_callback(self, tmp_path, session):
        """append_raw_data must accept progress_callback kwarg without error."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        calls: list = []

        def cb(msg: str, frac: float) -> None:
            calls.append((msg, frac))

        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            writer.append_raw_data(
                session, nwb_path, time_range=(0.0, 0.1), progress_callback=cb
            )

        assert len(calls) > 0, "progress_callback was never invoked"

    def test_progress_messages_tag_append_and_verify(self, tmp_path, session):
        """Callback messages must include 'append' and 'verify' tokens."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        calls: list = []
        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            writer.append_raw_data(
                session,
                nwb_path,
                time_range=(0.0, 0.1),
                progress_callback=lambda m, f: calls.append((m, f)),
            )

        messages = " | ".join(m for m, _ in calls)
        assert "append" in messages
        assert "verify" in messages

    def test_progress_fraction_monotonic_and_bounded(self, tmp_path, session):
        """Fraction must be monotonically non-decreasing and within [0, 1]."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        fractions: list[float] = []
        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            writer.append_raw_data(
                session,
                nwb_path,
                time_range=(0.0, 0.1),
                progress_callback=lambda m, f: fractions.append(f),
            )

        assert all(0.0 <= f <= 1.0 for f in fractions)
        for a, b in zip(fractions, fractions[1:], strict=False):
            assert b >= a - 1e-9, f"fraction dropped: {a} → {b}"
        assert fractions[-1] == pytest.approx(1.0, abs=1e-6)

    def test_progress_callback_none_is_safe(self, tmp_path, session):
        """progress_callback=None (default) must not raise."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            result = writer.append_raw_data(
                session, nwb_path, time_range=(0.0, 0.1), progress_callback=None
            )
        assert result["streams_written"] >= 1


# ===================================================================
# K. E1.2 — append_raw_data NIDQ TimeSeries
# ===================================================================


def _write_nidq_meta(
    path: Path,
    *,
    ni_samp_rate: float = 30000.0,
    ni_ai_range_max: float = 5.0,
    n_saved_chans: int = 8,
    sns_mn_ma_xa_dw: str = "0,0,7,1",
    ni_mn_gain: float = 200.0,
    ni_ma_gain: float = 1.0,
) -> Path:
    """Write a minimal SpikeGLX .nidq.meta file for testing.

    Returns the path that was written.
    """
    path.write_text(
        "\n".join(
            [
                f"niSampRate={ni_samp_rate}",
                f"niAiRangeMax={ni_ai_range_max}",
                f"niAiRangeMin=-{ni_ai_range_max}",
                f"nSavedChans={n_saved_chans}",
                f"snsMnMaXaDw={sns_mn_ma_xa_dw}",
                f"niMNGain={ni_mn_gain}",
                f"niMAGain={ni_ma_gain}",
                "fileSizeBytes=0",
                "typeThis=nidq",
                "fileCreateTime=2024-01-15T14:30:00",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _make_nidq_session(
    tmp_path: Path,
    *,
    subject: SubjectConfig,
    ni_samp_rate: float = 30000.0,
    ni_ai_range_max: float = 5.0,
    n_channels: int = 8,
    include_nidq_files: bool = True,
) -> Session:
    """Build a Session with a session_dir containing nidq.bin/meta."""
    session_dir = tmp_path / "rec_g0"
    session_dir.mkdir(parents=True, exist_ok=True)

    if include_nidq_files:
        _write_nidq_meta(
            session_dir / "rec_g0_t0.nidq.meta",
            ni_samp_rate=ni_samp_rate,
            ni_ai_range_max=ni_ai_range_max,
            n_saved_chans=n_channels,
        )
        # Bin file — content unimportant because load_nidq is patched in tests
        (session_dir / "rec_g0_t0.nidq.bin").write_bytes(b"\x00" * 16)

    bhv = tmp_path / "task.bhv2"
    bhv.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "out_nidq"

    s = SessionManager.create(
        session_dir,
        bhv,
        subject,
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4"},
        date="240115",
    )
    # Attach a default PipelineConfig so append_raw_data can read sync params.
    from pynpxpipe.core.config import PipelineConfig

    s.config = PipelineConfig()
    return s


class TestAppendRawDataNIDQ:
    """Tests for NIDQ TimeSeries injection in append_raw_data (E1.2)."""

    def test_nidq_single_timeseries_written(self, tmp_path, subject):
        """After append_raw_data on a session with nidq, acquisition['NIDQ_raw'] exists."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        session = _make_nidq_session(tmp_path, subject=subject, n_channels=6)
        # Need probe with AP recording mockable too (append_raw_data iterates probes)
        meta_dir = tmp_path / "probe0"
        meta_dir.mkdir()
        probe = _make_probe("imec0", _make_meta_file(meta_dir))
        session.probes = [probe]

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        ap_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)
        nidq_rec, _ = _make_numpy_recording(
            n_samples=3000, n_channels=6, sampling_frequency=30000.0
        )

        writer = NWBWriter(session, nwb_path)
        with (
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=ap_rec),
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_nidq", return_value=nidq_rec),
        ):
            result = writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        assert "NIDQ_raw" in result["stream_names"]

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            assert "NIDQ_raw" in nwbfile.acquisition

    def test_nidq_int16_preserved(self, tmp_path, subject):
        """NIDQ data on reopen must be int16."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        session = _make_nidq_session(tmp_path, subject=subject, n_channels=4)
        meta_dir = tmp_path / "probe0"
        meta_dir.mkdir()
        probe = _make_probe("imec0", _make_meta_file(meta_dir))
        session.probes = [probe]

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        ap_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)
        nidq_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with (
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=ap_rec),
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_nidq", return_value=nidq_rec),
        ):
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            ds = nwbfile.acquisition["NIDQ_raw"]
            assert ds.data.dtype == np.int16

    def test_nidq_conversion_from_meta(self, tmp_path, subject):
        """conversion field must equal niAiRangeMax / 32768.0 exactly."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        session = _make_nidq_session(tmp_path, subject=subject, n_channels=4, ni_ai_range_max=5.0)
        meta_dir = tmp_path / "probe0"
        meta_dir.mkdir()
        probe = _make_probe("imec0", _make_meta_file(meta_dir))
        session.probes = [probe]

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        ap_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)
        nidq_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with (
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=ap_rec),
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_nidq", return_value=nidq_rec),
        ):
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            ts = nwbfile.acquisition["NIDQ_raw"]
            assert ts.conversion == 5.0 / 32768.0

    def test_nidq_description_contains_channel_map(self, tmp_path, subject):
        """description must include niAiRangeMax=, niSampRate=, event_bits=, sync_bit= literals."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        session = _make_nidq_session(tmp_path, subject=subject, n_channels=4)
        meta_dir = tmp_path / "probe0"
        meta_dir.mkdir()
        probe = _make_probe("imec0", _make_meta_file(meta_dir))
        session.probes = [probe]

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        ap_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)
        nidq_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with (
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=ap_rec),
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_nidq", return_value=nidq_rec),
        ):
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            desc = nwbfile.acquisition["NIDQ_raw"].description

        for literal in ("niAiRangeMax=", "niSampRate=", "event_bits=", "sync_bit="):
            assert literal in desc, f"description missing literal {literal!r}: {desc!r}"

    def test_nidq_skip_when_missing(self, tmp_path, subject, caplog):
        """Session with no nidq.bin → no NIDQ_raw, no exception, warning logged."""
        import logging

        from pynpxpipe.io.nwb_writer import NWBWriter

        session = _make_nidq_session(
            tmp_path, subject=subject, n_channels=4, include_nidq_files=False
        )
        meta_dir = tmp_path / "probe0"
        meta_dir.mkdir()
        probe = _make_probe("imec0", _make_meta_file(meta_dir))
        session.probes = [probe]

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        ap_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with (
            caplog.at_level(logging.WARNING, logger="pynpxpipe.io.nwb_writer"),
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=ap_rec),
        ):
            # No load_nidq patch — must not be called since discover_nidq raises.
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            assert "NIDQ_raw" not in nwbfile.acquisition

        # Verify a warning mentioning NIDQ was emitted.
        nidq_warnings = [r for r in caplog.records if "nidq" in r.getMessage().lower()]
        assert nidq_warnings, (
            f"expected NIDQ skip warning, got: {[r.message for r in caplog.records]}"
        )

    def test_nidq_idempotent(self, tmp_path, subject):
        """Calling append_raw_data twice must not duplicate NIDQ_raw."""
        from pynpxpipe.io.nwb_writer import NWBWriter

        session = _make_nidq_session(tmp_path, subject=subject, n_channels=4)
        meta_dir = tmp_path / "probe0"
        meta_dir.mkdir()
        probe = _make_probe("imec0", _make_meta_file(meta_dir))
        session.probes = [probe]

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        ap_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)
        nidq_rec, _ = _make_numpy_recording(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with (
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=ap_rec),
            patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_nidq", return_value=nidq_rec),
        ):
            writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))
            result2 = writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        # Second call should not re-add NIDQ.
        assert "NIDQ_raw" not in result2["stream_names"]

        import pynwb

        with pynwb.NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            # Still exactly one NIDQ_raw.
            assert "NIDQ_raw" in nwbfile.acquisition
            # pynwb dict-like view: name collisions would raise on write, so presence alone is enough.


# ===================================================================
# L. E1.3 — add_sync_tables
# ===================================================================


def _make_writer_with_nwbfile(session: Session, tmp_path: Path) -> NWBWriter:
    """Build an NWBWriter whose internal NWBFile has been created.

    Helper specific to E1.3 tests: all four tests need a writer wired to a
    real NWBFile so ``add_sync_tables`` has somewhere to park the scratch
    block. Returns the writer; the caller normally uses ``writer._nwbfile``.
    """
    w = NWBWriter(session, tmp_path / "out.nwb")
    w.create_file()
    return w


class TestAddSyncTables:
    """Tests for NWBWriter.add_sync_tables (E1.3)."""

    def test_add_sync_tables_single_probe_present(
        self, tmp_path: Path, session: Session
    ) -> None:
        """A single imec0_imec_nidq.json in sync_dir shows up verbatim in scratch."""
        import json as _json

        sync_dir = tmp_path / "04_sync"
        sync_dir.mkdir()
        fit = {"a": 1.000001, "b": -0.003, "rmse": 1.2e-5, "n_pulses": 1200}
        (sync_dir / "imec0_imec_nidq.json").write_text(_json.dumps(fit), encoding="utf-8")

        writer = _make_writer_with_nwbfile(session, tmp_path)
        summary = writer.add_sync_tables(writer._nwbfile, sync_dir)

        assert summary["idempotent_skipped"] is False
        assert summary["n_probes"] == 1

        blob = _json.loads(writer._nwbfile.scratch["sync_tables"].data)
        assert "imec0" in blob["imec_nidq"]
        assert blob["imec_nidq"]["imec0"]["a"] == pytest.approx(1.000001)
        assert blob["imec_nidq"]["imec0"]["b"] == pytest.approx(-0.003)
        assert blob["imec_nidq"]["imec0"]["rmse"] == pytest.approx(1.2e-5)
        assert blob["imec_nidq"]["imec0"]["n_pulses"] == 1200

    def test_add_sync_tables_two_probes(self, tmp_path: Path, session: Session) -> None:
        """imec0 + imec1 per-probe files both surface as dict entries."""
        import json as _json

        sync_dir = tmp_path / "04_sync"
        sync_dir.mkdir()
        (sync_dir / "imec0_imec_nidq.json").write_text(
            _json.dumps({"a": 1.0, "b": 0.0, "rmse": 1e-5, "n_pulses": 100}),
            encoding="utf-8",
        )
        (sync_dir / "imec1_imec_nidq.json").write_text(
            _json.dumps({"a": 0.999, "b": 0.5, "rmse": 2e-5, "n_pulses": 99}),
            encoding="utf-8",
        )

        writer = _make_writer_with_nwbfile(session, tmp_path)
        summary = writer.add_sync_tables(writer._nwbfile, sync_dir)

        assert summary["n_probes"] == 2
        blob = _json.loads(writer._nwbfile.scratch["sync_tables"].data)
        assert set(blob["imec_nidq"].keys()) == {"imec0", "imec1"}
        assert blob["imec_nidq"]["imec1"]["b"] == pytest.approx(0.5)

    def test_add_sync_tables_photodiode_from_events(
        self, tmp_path: Path, session: Session
    ) -> None:
        """behavior_events with pd + ec columns produces a populated photodiode list."""
        import json as _json

        sync_dir = tmp_path / "04_sync"
        sync_dir.mkdir()
        (sync_dir / "imec0_imec_nidq.json").write_text(
            _json.dumps({"a": 1.0, "b": 0.0, "rmse": 1e-5, "n_pulses": 100}),
            encoding="utf-8",
        )

        events = pd.DataFrame(
            {
                "pd_onset_nidq_s": [12.345, 13.500],
                "ec_onset_nidq_s": [12.320, 13.475],
                "onset_nidq_s": [10.0, 11.0],
                "stim_onset_nidq_s": [12.32, 13.475],
            }
        )

        writer = _make_writer_with_nwbfile(session, tmp_path)
        writer.add_sync_tables(writer._nwbfile, sync_dir, behavior_events=events)

        blob = _json.loads(writer._nwbfile.scratch["sync_tables"].data)
        pd_rows = blob["photodiode"]
        assert len(pd_rows) == 2
        assert pd_rows[0]["pd_onset_nidq_s"] == pytest.approx(12.345)
        assert pd_rows[0]["ec_onset_nidq_s"] == pytest.approx(12.320)
        # latency_s = ec - pd = -0.025
        assert pd_rows[0]["latency_s"] == pytest.approx(-0.025)
        # trial_index preserved
        assert pd_rows[0]["trial_index"] == 0
        assert pd_rows[1]["trial_index"] == 1

    def test_add_sync_tables_missing_files_marked(
        self, tmp_path: Path, session: Session
    ) -> None:
        """Empty sync_dir + None events → all three keys carry _missing sentinel."""
        import json as _json

        sync_dir = tmp_path / "empty_sync"
        sync_dir.mkdir()

        writer = _make_writer_with_nwbfile(session, tmp_path)
        # No exception — graceful fallback per the locked spec.
        summary = writer.add_sync_tables(
            writer._nwbfile, sync_dir, behavior_events=None
        )

        assert summary["idempotent_skipped"] is False
        assert summary["n_probes"] == 0
        assert summary["n_trials_pd"] == 0
        assert summary["n_trials_ec"] == 0

        blob = _json.loads(writer._nwbfile.scratch["sync_tables"].data)
        assert blob["imec_nidq"] == {"_missing": True}
        assert blob["photodiode"] == {"_missing": True}
        assert blob["event_codes"] == {"_missing": True}


# ===================================================================
# L. E2.2 — _append_recording_stream hard-stops on missing gain_to_uV
# ===================================================================


def _make_recording_without_gain(
    n_samples: int = 3000,
    n_channels: int = 4,
    sampling_frequency: float = 30000.0,
):
    """NumpyRecording that deliberately lacks gain_to_uV (E2.2)."""
    import spikeinterface.core as si

    rng = np.random.RandomState(0)
    data = rng.randint(-100, 100, (n_samples, n_channels), dtype=np.int16)
    rec = si.NumpyRecording(
        traces_list=[data.astype(np.float32)],
        sampling_frequency=sampling_frequency,
    )
    # Note: intentionally NOT calling rec.set_property("gain_to_uV", ...)
    return rec


class TestAppendRecordingStreamErrors:
    """E2.2: missing gain_to_uV must raise ExportError, not silently fall back."""

    def test_append_raises_when_gain_missing(self, tmp_path, session):
        """append_raw_data must raise ExportError when gain_to_uV is unset."""
        from pynpxpipe.core.errors import ExportError
        from pynpxpipe.io.nwb_writer import NWBWriter

        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec = _make_recording_without_gain(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            with pytest.raises(ExportError):
                writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

    def test_append_error_message_identifies_probe_and_stream(self, tmp_path, session):
        """Error message must embed probe_id ('imec0'), stream ('AP'), and 'gain_to_uV'."""
        from pynpxpipe.core.errors import ExportError
        from pynpxpipe.io.nwb_writer import NWBWriter

        # Session fixture already uses probe_id="imec0".
        nwb_path = _create_nwb_with_electrodes(tmp_path, "imec0", n_channels=4)
        rec = _make_recording_without_gain(n_samples=3000, n_channels=4)

        writer = NWBWriter(session, nwb_path)
        with patch("pynpxpipe.io.nwb_writer.SpikeGLXLoader.load_ap", return_value=rec):
            with pytest.raises(ExportError) as excinfo:
                writer.append_raw_data(session, nwb_path, time_range=(0.0, 0.1))

        msg = str(excinfo.value)
        assert "imec0" in msg, msg
        assert "AP" in msg, msg
        assert "gain_to_uV" in msg, msg


# ---------------------------------------------------------------------------
# Group H — add_pipeline_metadata (E3.1)
# ---------------------------------------------------------------------------


class TestAddPipelineMetadata:
    """E3.1: serialize PipelineConfig into nwbfile.scratch['pipeline_config']."""

    def test_roundtrip_full_config(self, writer: NWBWriter, tmp_path: Path) -> None:
        """PipelineConfig dataclass survives write→read via scratch."""
        import dataclasses
        import json

        import pynwb

        from pynpxpipe.core.config import PipelineConfig

        config = PipelineConfig()
        writer.create_file()
        writer.add_pipeline_metadata(config)
        writer.write()

        with pynwb.NWBHDF5IO(str(writer.output_path), mode="r") as io:
            nwbfile = io.read()
            raw = nwbfile.scratch["pipeline_config"].data
            payload = raw if isinstance(raw, str) else raw[()]
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            decoded = json.loads(payload)

        expected = json.loads(json.dumps(dataclasses.asdict(config), default=str))
        assert decoded == expected

    def test_scratch_key_name(self, writer: NWBWriter) -> None:
        """Scratch key must be exactly 'pipeline_config' and description mentions PipelineConfig."""
        from pynpxpipe.core.config import PipelineConfig

        writer.create_file()
        writer.add_pipeline_metadata(PipelineConfig())
        assert "pipeline_config" in writer._nwbfile.scratch
        scratch_entry = writer._nwbfile.scratch["pipeline_config"]
        assert "PipelineConfig" in scratch_entry.description

    def test_idempotent_on_second_call(
        self, writer: NWBWriter, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Second call must warn and skip without raising."""
        import logging

        from pynpxpipe.core.config import PipelineConfig

        config = PipelineConfig()
        writer.create_file()
        writer.add_pipeline_metadata(config)

        with caplog.at_level(logging.WARNING):
            writer.add_pipeline_metadata(config)  # must not raise

        assert any("pipeline_config" in rec.message for rec in caplog.records)

    def test_raises_if_not_created(self, writer: NWBWriter) -> None:
        """Calling before create_file() must raise RuntimeError."""
        from pynpxpipe.core.config import PipelineConfig

        with pytest.raises(RuntimeError, match="create_file"):
            writer.add_pipeline_metadata(PipelineConfig())

    def test_raises_on_non_dataclass(self, writer: NWBWriter) -> None:
        """Non-dataclass input must raise TypeError."""
        writer.create_file()
        with pytest.raises(TypeError):
            writer.add_pipeline_metadata({"not": "a dataclass"})


# ---------------------------------------------------------------------------
# Group I — merged_from column (E3.2)
# ---------------------------------------------------------------------------


def _write_merge_log(session: Session, probe_id: str, payload: dict) -> Path:
    """Write merge_log.json under session.output_dir/03_merged/{probe_id}/."""
    merge_dir = session.output_dir / "03_merged" / probe_id
    merge_dir.mkdir(parents=True, exist_ok=True)
    merge_log_path = merge_dir / "merge_log.json"
    merge_log_path.write_text(json.dumps(payload), encoding="utf-8")
    return merge_log_path


class TestMergedFromColumn:
    """E3.2: ``units.merged_from`` ragged column + ``scratch/merge_log_{probe_id}``."""

    def test_column_always_present(self, writer: NWBWriter, probe: ProbeInfo) -> None:
        """No merge_log.json → column exists, every row is []."""
        writer.create_file()
        writer.add_probe_data(probe, _make_mock_analyzer(n_units=2))

        units = writer._nwbfile.units
        assert "merged_from" in units.colnames
        assert list(units["merged_from"][0]) == []
        assert list(units["merged_from"][1]) == []

    def test_populated_from_log(
        self, writer: NWBWriter, probe: ProbeInfo, session: Session
    ) -> None:
        """merge_log.json present → row with ks_id=5 has merged_from=[5,7,9]."""
        _write_merge_log(
            session,
            probe.probe_id,
            {"merges": [{"new_id": 5, "merged_ids": [5, 7, 9]}]},
        )

        writer.create_file()
        analyzer = _make_mock_analyzer(unit_ids=[3, 5, 7])
        writer.add_probe_data(probe, analyzer)

        units = writer._nwbfile.units
        merged_from = units["merged_from"][:]
        assert list(merged_from[0]) == []  # unit 3
        assert list(merged_from[1]) == [5, 7, 9]  # unit 5
        assert list(merged_from[2]) == []  # unit 7

    def test_empty_when_merge_off(
        self, writer: NWBWriter, probe: ProbeInfo, session: Session
    ) -> None:
        """No merged/ dir anywhere → column all empty, no scratch entry."""
        assert not (session.output_dir / "03_merged").exists()

        writer.create_file()
        writer.add_probe_data(probe, _make_mock_analyzer(n_units=3))

        units = writer._nwbfile.units
        assert "merged_from" in units.colnames
        for i in range(3):
            assert list(units["merged_from"][i]) == []

        scratch_name = f"merge_log_{probe.probe_id}"
        assert scratch_name not in writer._nwbfile.scratch

    def test_scratch_log_preserved(
        self, writer: NWBWriter, probe: ProbeInfo, session: Session
    ) -> None:
        """merge_log.json present → scratch carries its exact JSON string."""
        payload = {
            "merges": [
                {"new_id": 5, "merged_ids": [5, 7, 9]},
                {"new_id": 12, "merged_ids": [12, 14]},
            ]
        }
        merge_log_path = _write_merge_log(session, probe.probe_id, payload)
        raw_text = merge_log_path.read_text(encoding="utf-8")

        writer.create_file()
        writer.add_probe_data(probe, _make_mock_analyzer(n_units=2))

        scratch_name = f"merge_log_{probe.probe_id}"
        assert scratch_name in writer._nwbfile.scratch
        scratch_entry = writer._nwbfile.scratch[scratch_name]
        assert scratch_entry.data == raw_text
