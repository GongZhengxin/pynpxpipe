"""E3 provenance contract harness.

End-to-end validation that provenance metadata (pipeline config, merge log,
BHV condition → stim_name) round-trips through the writer into an NWB file
and can be recovered via ``pynwb.NWBHDF5IO``.

This file is shared by the three E3 tasks:

* ``E3.1 test_pipeline_config_roundtrip`` — writes ``PipelineConfig`` to scratch.
* ``E3.2 test_merged_from_populated``    — writes ``merged_from`` unit column.
* ``E3.3 test_stim_name_present``        — writes ``stim_name`` trial column.

Each task appends its own test_* to this module; helpers live at module level
so later waves can reuse them.

Runtime budget per test: <2s. Everything is synthetic numpy + a tmp_path NWB.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pynwb

from pynpxpipe.core.session import ProbeInfo, SessionManager, SubjectConfig
from pynpxpipe.io.nwb_writer import NWBWriter

# ── Synthetic-data knobs ────────────────────────────────────────────────

_N_SAMPLES = 82
_N_CHANNELS = 4


def _subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="MaoDan",
        description="E3 provenance harness subject",
        species="Macaca mulatta",
        sex="M",
        age="P4Y",
        weight="12kg",
    )


def _write_ap_meta(meta_path: Path) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(
        "typeThis=imec\nfileCreateTime=2024-01-15T14:30:00\nimSampRate=30000.0\n",
        encoding="utf-8",
    )


def _make_probe(probe_id: str, tmp_path: Path, target_area: str) -> ProbeInfo:
    meta = tmp_path / f"{probe_id}.ap.meta"
    _write_ap_meta(meta)
    positions = [(float(i * 16), float(i * 20)) for i in range(_N_CHANNELS)]
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=meta.parent / f"{probe_id}.ap.bin",
        ap_meta=meta,
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=_N_CHANNELS,
        serial_number=f"SN_{probe_id}",
        probe_type="NP1010",
        channel_positions=positions,
        target_area=target_area,
    )


def _make_analyzer(n_units: int = 1) -> MagicMock:
    """Minimal SortingAnalyzer stub for NWB writer tests."""
    unit_ids = [f"u{i}" for i in range(n_units)]

    sorting = MagicMock()
    sorting.get_unit_ids.return_value = unit_ids
    sorting.get_unit_spike_train.return_value = np.array([0.1, 0.2, 0.5], dtype=np.float64)
    sorting.get_property.return_value = None

    templates_data = np.zeros((n_units, _N_SAMPLES, _N_CHANNELS), dtype=np.float32)
    templates = MagicMock()
    templates.get_templates.return_value = templates_data

    locs = MagicMock()
    locs.get_data.return_value = np.zeros((n_units, 3), dtype=np.float64)

    available = {"waveforms", "templates", "unit_locations"}

    def has_ext(name: str) -> bool:
        return name in available

    def get_ext(name: str) -> MagicMock:
        return {"waveforms": templates, "templates": templates, "unit_locations": locs}[name]

    analyzer = MagicMock()
    analyzer.sorting = sorting
    analyzer.has_extension.side_effect = has_ext
    analyzer.get_extension.side_effect = get_ext
    return analyzer


def _make_session(tmp_path: Path) -> tuple:
    """Build a session with one probe and return (session, probe, writer_path)."""
    session_dir = tmp_path / "Run_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "task.bhv2"
    bhv_file.write_bytes(b"\x00" * 16)

    session = SessionManager.create(
        session_dir,
        bhv_file,
        _subject(),
        tmp_path / "out",
        experiment="nsd1w",
        probe_plan={"imec0": "MSB"},
        date="240115",
    )
    probe = _make_probe("imec0", tmp_path / "probe0", "MSB")
    session.probes = [probe]
    out_path = tmp_path / f"{session.session_id.canonical()}.nwb"
    return session, probe, out_path


def test_pipeline_config_roundtrip(tmp_path: Path) -> None:
    """E3.1: PipelineConfig survives write→read via scratch['pipeline_config'].

    Build a minimal session, attach a real ``PipelineConfig`` dataclass, run
    ``add_pipeline_metadata``, write, then re-open and assert the decoded
    payload equals ``dataclasses.asdict(config)`` (after Path/Enum
    stringification via ``default=str``).
    """
    import dataclasses

    from pynpxpipe.core.config import PipelineConfig

    session, _probe, out_path = _make_session(tmp_path)
    config = PipelineConfig()

    writer = NWBWriter(session, out_path)
    writer.create_file()
    writer.add_pipeline_metadata(config)
    writer.write()

    with pynwb.NWBHDF5IO(str(out_path), mode="r") as io:
        nwbfile = io.read()
        raw = nwbfile.scratch["pipeline_config"].data
        payload = raw if isinstance(raw, str) else raw[()]
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        decoded = json.loads(payload)

    expected = json.loads(json.dumps(dataclasses.asdict(config), default=str))
    assert decoded == expected


def test_merged_from_populated(tmp_path: Path) -> None:
    """E3.2: merge_log.json drives ``units.merged_from`` column end-to-end.

    Write a fake ``merged/imec0/merge_log.json`` with one merge entry
    (``new_id=5, merged_ids=[5,7,9]``), export, reopen and assert the unit
    row whose ks_id is 5 carries the list, while other rows have ``[]``.
    """
    session, probe, out_path = _make_session(tmp_path)

    merge_dir = session.output_dir / "03_merged" / probe.probe_id
    merge_dir.mkdir(parents=True, exist_ok=True)
    (merge_dir / "merge_log.json").write_text(
        json.dumps({"merges": [{"new_id": 5, "merged_ids": [5, 7, 9]}]}),
        encoding="utf-8",
    )

    # Analyzer reports ks_ids [1, 3, 5, 7, 9]; row with ks_id 5 should be
    # populated.  Use integer unit ids so the NWB row id survives the
    # _as_int fallback in add_probe_data.
    n_units = 5
    unit_ids = [1, 3, 5, 7, 9]

    sorting = MagicMock()
    sorting.get_unit_ids.return_value = unit_ids
    sorting.get_unit_spike_train.return_value = np.array([0.1, 0.2, 0.5], dtype=np.float64)
    sorting.get_property.return_value = None
    templates = MagicMock()
    templates.get_templates.return_value = np.zeros(
        (n_units, _N_SAMPLES, _N_CHANNELS), dtype=np.float32
    )
    locs = MagicMock()
    locs.get_data.return_value = np.zeros((n_units, 3), dtype=np.float64)
    available = {"waveforms", "templates", "unit_locations"}
    analyzer = MagicMock()
    analyzer.sorting = sorting
    analyzer.has_extension.side_effect = lambda n: n in available
    analyzer.get_extension.side_effect = lambda n: {
        "waveforms": templates,
        "templates": templates,
        "unit_locations": locs,
    }[n]

    writer = NWBWriter(session, out_path)
    writer.create_file()
    writer.add_probe_data(probe, analyzer)
    writer.write()

    with pynwb.NWBHDF5IO(str(out_path), mode="r") as io:
        nwbfile = io.read()
        assert "merged_from" in nwbfile.units.colnames
        # Key by the ks_id column (authoritative Kilosort cluster id)
        # rather than the NWB row id so the assertion does not depend on
        # NWBFile's auto-assigned sequential ids.
        n_rows = len(nwbfile.units["ks_id"][:])
        ks_ids = [int(nwbfile.units["ks_id"][i]) for i in range(n_rows)]
        merged_col = [nwbfile.units["merged_from"][i] for i in range(n_rows)]

    merged_lists = [[int(x) for x in row] for row in merged_col]
    by_ksid = dict(zip(ks_ids, merged_lists, strict=False))
    assert by_ksid.get(5) == [5, 7, 9], f"expected [5,7,9] for ks_id=5, got {by_ksid}"
    for kid, row in by_ksid.items():
        if kid != 5:
            assert row == [], f"ks_id={kid} expected [], got {row}"


def test_stim_name_present(tmp_path: Path) -> None:
    """E3.3: stim_index → trials.stim_name round-trip via stim_map.

    Build a tiny 3-onset session (stim_index = [1, 2, 1]), call
    ``add_trials`` with an explicit fake stim_map, write the NWB, and
    re-open to assert the three rows carry their resolved stimulus file
    names.
    """
    session, probe, out_path = _make_session(tmp_path)

    writer = NWBWriter(session, out_path)
    writer.create_file()
    writer.add_probe_data(probe, _make_analyzer(n_units=1))

    behavior_events = pd.DataFrame(
        {
            "trial_id": [0, 1, 2],
            "onset_nidq_s": [0.0, 1.0, 2.0],
            "stim_onset_nidq_s": [0.1, 1.1, 2.1],
            "stim_onset_imec_s": [
                json.dumps({"imec0": 0.11}),
                json.dumps({"imec0": 1.13}),
                json.dumps({"imec0": 2.14}),
            ],
            "condition_id": [1, 2, 1],
            "stim_index": [1, 2, 1],
            "trial_valid": [True, True, True],
            "onset_time_ms": [150.0, 150.0, 150.0],
            "offset_time_ms": [150.0, 150.0, 150.0],
        }
    )
    writer.add_trials(
        behavior_events,
        stim_map={1: "face_01.png", 2: "obj_03.png"},
    )
    writer.write()

    assert out_path.exists()

    with pynwb.NWBHDF5IO(str(out_path), mode="r") as io:
        nwbfile = io.read()
        colnames = nwbfile.trials.colnames
        assert "stim_name" in colnames, f"stim_name missing; have: {colnames}"
        stim_names = [nwbfile.trials["stim_name"][i] for i in range(3)]

    # Bytes-vs-str tolerant decode: pynwb can return either depending on
    # backend settings. Normalise before comparing.
    def _as_str(v: object) -> str:
        return v.decode("utf-8") if isinstance(v, bytes) else str(v)

    stim_names_str = [_as_str(v) for v in stim_names]
    assert stim_names_str[0] == "face_01.png"
    assert stim_names_str[1] == "obj_03.png"
    assert stim_names_str[2] == "face_01.png"


def test_stim_name_column_absent_when_map_missing(tmp_path: Path) -> None:
    """E3.3 negative path: ``stim_map=None`` → no stim_name column declared.

    Per the redesigned contract, when no tsv is resolvable the writer
    omits the stim_name column entirely (rather than populating with
    empty strings) so downstream consumers can distinguish "lookup
    skipped" from "lookup ran but returned empty".
    """
    session, probe, out_path = _make_session(tmp_path)

    writer = NWBWriter(session, out_path)
    writer.create_file()
    writer.add_probe_data(probe, _make_analyzer(n_units=1))

    behavior_events = pd.DataFrame(
        {
            "trial_id": [0, 1],
            "onset_nidq_s": [0.0, 1.0],
            "stim_onset_nidq_s": [0.1, 1.1],
            "stim_onset_imec_s": [
                json.dumps({"imec0": 0.11}),
                json.dumps({"imec0": 1.13}),
            ],
            "condition_id": [1, 2],
            "stim_index": [1, 2],
            "trial_valid": [True, True],
            "onset_time_ms": [150.0, 150.0],
            "offset_time_ms": [150.0, 150.0],
        }
    )
    writer.add_trials(behavior_events, stim_map=None)
    writer.write()

    with pynwb.NWBHDF5IO(str(out_path), mode="r") as io:
        nwbfile = io.read()
        assert "stim_name" not in nwbfile.trials.colnames
