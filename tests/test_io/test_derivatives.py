"""Unit tests for pynpxpipe.io.derivatives.

Exercises the four public helpers:

- ``spike_times_to_raster``    — builds (n_units, n_trials, n_timebins) uint8.
- ``save_raster_h5``            — dense / sparse HDF5 writer with metadata.
- ``export_unit_prop``          — 5-col UnitProp CSV (id/ks_id/unitpos/unittype/unittype_string).
- ``export_trial_record``       — 6-col TrialRecord CSV (id/start/stop/stim_index/stim_name/fix_success).
- ``resolve_post_onset_ms``     — scans BHV2 VariableChanges, picks max.
"""

from __future__ import annotations

import ast
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from pynpxpipe.io.derivatives import (
    export_trial_record,
    export_unit_prop,
    resolve_post_onset_ms,
    save_raster_h5,
    spike_times_to_raster,
)

# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────


def _unit_df(spike_times_list: list[list[float]]) -> pd.DataFrame:
    """Build a minimal units DataFrame with a ``spike_times`` column of object arrays."""
    return pd.DataFrame(
        {"spike_times": [np.asarray(st, dtype=np.float64) for st in spike_times_list]}
    )


def _trial_df(start_times: list[float]) -> pd.DataFrame:
    """Build a minimal trials DataFrame with a ``start_time`` column (seconds)."""
    return pd.DataFrame({"start_time": list(start_times)})


# ────────────────────────────────────────────────────────────────────────
# spike_times_to_raster
# ────────────────────────────────────────────────────────────────────────


class TestSpikeTimesToRaster:
    def test_shape(self):
        units = _unit_df([[], [], []])  # 3 units, no spikes
        trials = _trial_df([1.0, 2.0])  # 2 trials
        r = spike_times_to_raster(units, trials, pre_onset=50, post_onset=300, bin_size=1)
        assert r.shape == (3, 2, 350)

    def test_dtype_uint8(self):
        units = _unit_df([[]])
        trials = _trial_df([0.0])
        r = spike_times_to_raster(units, trials, pre_onset=10, post_onset=10, bin_size=1)
        assert r.dtype == np.uint8

    def test_empty_spikes_all_zero(self):
        units = _unit_df([[], []])
        trials = _trial_df([1.0, 2.0])
        r = spike_times_to_raster(units, trials, pre_onset=50, post_onset=50, bin_size=1)
        assert r.sum() == 0

    def test_spike_inside_window(self):
        # trial starts at t=1.0s; spike at 1.100s; pre_onset=50ms -> window starts at 0.950s
        # relative offset = 1.100 - 0.950 = 0.150s -> bin index 150
        units = _unit_df([[1.100]])
        trials = _trial_df([1.0])
        r = spike_times_to_raster(units, trials, pre_onset=50, post_onset=300, bin_size=1)
        assert r[0, 0, 150] == 1
        assert r[0, 0, :].sum() == 1

    def test_spike_outside_window(self):
        # trial start=1.0s, post_onset=100ms; spike at 1.500s is way past
        units = _unit_df([[1.500]])
        trials = _trial_df([1.0])
        r = spike_times_to_raster(units, trials, pre_onset=50, post_onset=100, bin_size=1)
        assert r.sum() == 0

    def test_saturation_clip_uint8(self):
        # 300 spikes at the exact same time → bincount = 300; uint8 clips at 255
        spikes = [1.100] * 300
        units = _unit_df([spikes])
        trials = _trial_df([1.0])
        r = spike_times_to_raster(units, trials, pre_onset=50, post_onset=300, bin_size=1)
        assert r[0, 0, 150] == 255

    def test_bin_size_10ms(self):
        units = _unit_df([[]])
        trials = _trial_df([0.0])
        r = spike_times_to_raster(units, trials, pre_onset=50, post_onset=50, bin_size=10)
        assert r.shape[-1] == 10  # (50+50)/10 = 10 bins


# ────────────────────────────────────────────────────────────────────────
# save_raster_h5
# ────────────────────────────────────────────────────────────────────────


class TestSaveRasterH5:
    def test_appends_h5_extension(self, tmp_path):
        raster = np.ones((1, 1, 5), dtype=np.uint8)
        out = tmp_path / "foo"  # no extension
        stats = save_raster_h5(str(out), raster)
        assert stats["filepath"].endswith(".h5")
        assert Path(stats["filepath"]).exists()

    def test_dense_when_low_sparsity(self, tmp_path):
        raster = np.ones((2, 2, 4), dtype=np.uint8)  # sparsity == 0
        stats = save_raster_h5(str(tmp_path / "dense.h5"), raster)
        assert stats["storage_format"] == "dense"
        with h5py.File(stats["filepath"], "r") as f:
            assert "raster" in f
            assert "data" not in f

    def test_sparse_when_high_sparsity(self, tmp_path):
        raster = np.zeros((2, 2, 10), dtype=np.uint8)
        raster[0, 0, 0] = 1  # sparsity ≈ 0.975
        stats = save_raster_h5(str(tmp_path / "sparse.h5"), raster)
        assert stats["storage_format"] == "sparse"
        with h5py.File(stats["filepath"], "r") as f:
            assert "data" in f and "row" in f and "col" in f
            assert "raster" not in f

    def test_metadata_written(self, tmp_path):
        raster = np.ones((1, 1, 3), dtype=np.uint8)
        stats = save_raster_h5(
            str(tmp_path / "meta.h5"),
            raster,
            metadata={"pre_onset_ms": 50, "session_id": "SID"},
        )
        with h5py.File(stats["filepath"], "r") as f:
            assert f["metadata"].attrs["pre_onset_ms"] == 50
            assert f["metadata"].attrs["session_id"] == "SID"

    def test_stats_dict_keys(self, tmp_path):
        stats = save_raster_h5(str(tmp_path / "s.h5"), np.zeros((1, 1, 2), dtype=np.uint8))
        for key in (
            "filepath",
            "storage_format",
            "original_size_mb",
            "file_size_mb",
            "compression_ratio",
            "sparsity",
            "shape",
        ):
            assert key in stats


# ────────────────────────────────────────────────────────────────────────
# export_unit_prop / export_trial_record
# ────────────────────────────────────────────────────────────────────────


def _unit_prop_source(
    n: int = 3,
    unittype_strings: list[str] | None = None,
) -> pd.DataFrame:
    """Synthetic units DataFrame matching upstream NWB units.to_dataframe() shape."""
    if unittype_strings is None:
        pool = ["SUA", "MUA", "NON-SOMA"]
        unittype_strings = [pool[i % len(pool)] for i in range(n)]
    return pd.DataFrame(
        {
            "ks_id": [10 + i for i in range(n)],
            "unit_location": [
                np.array([float(i) * 1.5, float(i) * 20.0, float(i) * 0.1]) for i in range(n)
            ],
            "unittype_string": unittype_strings,
            "spike_times": [np.array([0.1 * i]) for i in range(n)],
            "waveform_mean": [np.zeros(3) for _ in range(n)],
        }
    )


class TestExportUnitProp:
    def test_projects_five_columns_in_order(self, tmp_path):
        df = _unit_prop_source(n=3)
        out = tmp_path / "u.csv"
        export_unit_prop(df, out)
        loaded = pd.read_csv(out)
        assert list(loaded.columns) == ["id", "ks_id", "unitpos", "unittype", "unittype_string"]

    def test_id_is_row_index(self, tmp_path):
        df = _unit_prop_source(n=4)
        out = tmp_path / "u_id.csv"
        export_unit_prop(df, out)
        loaded = pd.read_csv(out)
        assert list(loaded["id"]) == list(range(len(df)))

    def test_unitpos_is_2d(self, tmp_path):
        df = _unit_prop_source(n=3)
        out = tmp_path / "u_pos.csv"
        export_unit_prop(df, out)
        loaded = pd.read_csv(out)
        # unitpos is serialized as a python-list literal "[x, y]" in the CSV cell.
        for cell in loaded["unitpos"]:
            parsed = ast.literal_eval(cell)
            assert len(parsed) == 2
            for v in parsed:
                assert isinstance(v, int | float)
        # Cross-check: values come from unit_location columns 0 and 1.
        expected = [list(loc[:2]) for loc in df["unit_location"]]
        actual = [list(ast.literal_eval(c)) for c in loaded["unitpos"]]
        assert actual == [[float(v) for v in row] for row in expected]

    def test_unittype_enum(self, tmp_path):
        df = _unit_prop_source(
            n=4,
            unittype_strings=["SUA", "MUA", "NON-SOMA", "GIBBERISH"],
        )
        out = tmp_path / "u_enum.csv"
        export_unit_prop(df, out)
        loaded = pd.read_csv(out)
        # SUA→1, MUA→2, NON-SOMA→3, unknown→0 (documented fallback).
        assert list(loaded["unittype"]) == [1, 2, 3, 0]
        # String column preserved verbatim.
        assert list(loaded["unittype_string"]) == ["SUA", "MUA", "NON-SOMA", "GIBBERISH"]


class TestExportTrialRecord:
    def test_projects_six_columns(self, tmp_path):
        df = pd.DataFrame(
            {
                "start_time": [0.0, 1.0],
                "stop_time": [0.5, 1.5],
                "trial_id": [1, 2],
                "condition_id": [1, 1],
                "stim_index": [0, 1],
                "stim_name": ["a.png", "b.png"],
                "trial_valid": [True, False],
                # Internal columns that must be dropped from CSV:
                "stim_onset_nidq_s_diag": [0.1, 1.1],
                "onset_time_ms": [100, 120],
                "stim_onset_imec_s": [0.101, 1.102],
            }
        )
        out = tmp_path / "t.csv"
        export_trial_record(df, out)
        loaded = pd.read_csv(out)
        assert list(loaded.columns) == [
            "id",
            "start_time",
            "stop_time",
            "stim_index",
            "stim_name",
            "fix_success",
        ]
        assert len(loaded) == 2
        # fix_success values equal source trial_valid values.
        assert list(loaded["fix_success"]) == [True, False]

    def test_id_is_row_index(self, tmp_path):
        df = pd.DataFrame(
            {
                "start_time": [0.0, 1.0, 2.0],
                "stop_time": [0.5, 1.5, 2.5],
                "stim_index": [0, 1, 2],
                "stim_name": ["a", "b", "c"],
                "trial_valid": [True, True, False],
            }
        )
        out = tmp_path / "t_id.csv"
        export_trial_record(df, out)
        loaded = pd.read_csv(out)
        assert list(loaded["id"]) == list(range(len(df)))

    def test_missing_stim_name_falls_back_to_empty_string(self, tmp_path):
        """When stim_map was not resolvable upstream, NWB trials lacks stim_name.

        export_trial_record must still write the file with an empty stim_name
        column rather than raising KeyError — mirrors the contract documented
        in stages/export.py:227 ('should yield an empty stim_name column
        without aborting the rest of export').
        """
        df = pd.DataFrame(
            {
                "start_time": [0.0, 1.0],
                "stop_time": [0.5, 1.5],
                "stim_index": [0, 1],
                # NB: no 'stim_name' column
                "trial_valid": [True, False],
            }
        )
        out = tmp_path / "t_no_stim_name.csv"
        export_trial_record(df, out)
        loaded = pd.read_csv(out, dtype={"stim_name": str}, keep_default_na=False)
        assert list(loaded.columns) == [
            "id",
            "start_time",
            "stop_time",
            "stim_index",
            "stim_name",
            "fix_success",
        ]
        assert list(loaded["stim_name"]) == ["", ""]

    def test_missing_stim_index_falls_back_too(self, tmp_path):
        """Same contract for stim_index — defensive: if both columns missing, still write."""
        df = pd.DataFrame(
            {
                "start_time": [0.0],
                "stop_time": [0.5],
                "trial_valid": [True],
            }
        )
        out = tmp_path / "t_no_stim_either.csv"
        export_trial_record(df, out)
        loaded = pd.read_csv(out, keep_default_na=False)
        assert len(loaded) == 1
        assert str(loaded["stim_name"].iloc[0]) == ""


# ────────────────────────────────────────────────────────────────────────
# resolve_post_onset_ms
# ────────────────────────────────────────────────────────────────────────


class _FakeTrial:
    def __init__(self, vc: dict):
        self.variable_changes = vc


class _FakeParser:
    def __init__(self, trials: list[_FakeTrial] | None = None, raise_on_parse: bool = False):
        self._trials = trials or []
        self._raise = raise_on_parse

    def parse(self):
        if self._raise:
            raise RuntimeError("boom")
        return self._trials


class TestResolvePostOnsetMs:
    def test_max_across_trials(self):
        trials = [
            _FakeTrial({"onset_time": 100, "offset_time": 200}),  # 300
            _FakeTrial({"onset_time": 150, "offset_time": 250}),  # 400 ← max
            _FakeTrial({"onset_time": 50, "offset_time": 50}),  # 100
        ]
        assert resolve_post_onset_ms(_FakeParser(trials)) == 400.0

    def test_fallback_when_parse_raises(self):
        assert resolve_post_onset_ms(_FakeParser(raise_on_parse=True)) == 800.0

    def test_fallback_when_all_trials_missing_fields(self):
        trials = [_FakeTrial({}), _FakeTrial({"fixation_window": 5.0})]
        assert resolve_post_onset_ms(_FakeParser(trials)) == 800.0

    def test_skips_partial_trials(self):
        trials = [
            _FakeTrial({"onset_time": 100}),  # missing offset_time — skip
            _FakeTrial({"onset_time": 200, "offset_time": 100}),  # 300
        ]
        assert resolve_post_onset_ms(_FakeParser(trials)) == 300.0


# ────────────────────────────────────────────────────────────────────────
# split_units_by_probe
# ────────────────────────────────────────────────────────────────────────


class TestSplitUnitsByProbe:
    def test_uses_probe_id_column_when_present(self):
        from pynpxpipe.io.derivatives import split_units_by_probe

        df = pd.DataFrame(
            {
                "probe_id": ["imec0", "imec0", "imec1"],
                "ks_id": [10, 11, 20],
            }
        )
        out = split_units_by_probe(df)
        assert set(out.keys()) == {"imec0", "imec1"}
        assert len(out["imec0"]) == 2
        assert len(out["imec1"]) == 1

    def test_falls_back_to_electrode_group_name(self):
        from pynpxpipe.io.derivatives import split_units_by_probe

        df = pd.DataFrame(
            {
                "electrode_group_name": ["imec0", "imec1", "imec1"],
                "ks_id": [1, 2, 3],
            }
        )
        out = split_units_by_probe(df)
        assert set(out.keys()) == {"imec0", "imec1"}
        assert len(out["imec1"]) == 2

    def test_prefers_probe_id_over_electrode_group_name(self):
        from pynpxpipe.io.derivatives import split_units_by_probe

        df = pd.DataFrame(
            {
                "probe_id": ["A", "A", "B"],
                "electrode_group_name": ["X", "Y", "Z"],
            }
        )
        out = split_units_by_probe(df)
        assert set(out.keys()) == {"A", "B"}

    def test_raises_when_neither_column_present(self):
        from pynpxpipe.io.derivatives import split_units_by_probe

        df = pd.DataFrame({"ks_id": [1, 2, 3]})
        try:
            split_units_by_probe(df)
        except RuntimeError as exc:
            msg = str(exc)
            assert "probe_id" in msg
            assert "electrode_group_name" in msg
        else:  # pragma: no cover
            raise AssertionError("expected RuntimeError")

    def test_empty_dataframe_returns_empty_dict(self):
        from pynpxpipe.io.derivatives import split_units_by_probe

        # Even empty df, the contract requires the columns to be declared.
        df = pd.DataFrame({"probe_id": pd.Series(dtype=object), "ks_id": pd.Series(dtype=int)})
        assert split_units_by_probe(df) == {}

    def test_preserves_row_order_within_probe(self):
        from pynpxpipe.io.derivatives import split_units_by_probe

        df = pd.DataFrame(
            {
                "probe_id": ["imec0", "imec1", "imec0", "imec1"],
                "ks_id": [10, 20, 11, 21],
            }
        )
        out = split_units_by_probe(df)
        assert list(out["imec0"]["ks_id"]) == [10, 11]
        assert list(out["imec1"]["ks_id"]) == [20, 21]


# ────────────────────────────────────────────────────────────────────────
# export_phase2_derivatives — multi-probe orchestrator
# ────────────────────────────────────────────────────────────────────────


def _write_minimal_nwb_with_units_and_trials(
    nwb_path: Path,
    *,
    n_units_per_probe: dict[str, int],
    n_trials: int = 3,
    session_id: str | None = "TEST_SES_v4-it",
) -> Path:
    """Construct a tiny NWB file with a units table containing probe_id +
    spike_times, plus a minimal trials table. Used to drive
    export_phase2_derivatives end-to-end without mocking pynwb."""
    from datetime import UTC, datetime

    import pynwb

    nwb_path.parent.mkdir(parents=True, exist_ok=True)
    nwbfile = pynwb.NWBFile(
        session_description="phase2 helper test",
        identifier="phase2-test",
        session_start_time=datetime(2026, 4, 29, 10, 0, 0, tzinfo=UTC),
        session_id=session_id,
    )
    # trials
    nwbfile.add_trial_column(name="trial_valid", description="pass/fail")
    nwbfile.add_trial_column(name="stim_index", description="stim id")
    for i in range(n_trials):
        nwbfile.add_trial(
            start_time=float(i), stop_time=float(i) + 0.5, trial_valid=True, stim_index=i
        )

    # units (require probe_id + standard NWB cols). NWB cannot serialise an
    # empty units table because it can't infer column dtypes — only declare
    # columns + add rows when at least one unit is requested. The
    # zero-units case exercises the ``nwbfile.units is None`` branch in
    # export_phase2_derivatives.
    total_units = sum(n_units_per_probe.values())
    if total_units > 0:
        nwbfile.add_unit_column(name="probe_id", description="probe identifier")
        nwbfile.add_unit_column(name="ks_id", description="kilosort id")
        nwbfile.add_unit_column(name="unit_location", description="xyz µm")
        nwbfile.add_unit_column(name="unittype_string", description="SUA/MUA/...")
        ks = 0
        for probe, n_units in n_units_per_probe.items():
            for _ in range(n_units):
                nwbfile.add_unit(
                    spike_times=np.array([0.05, 0.10, 0.15], dtype=np.float64),
                    probe_id=probe,
                    ks_id=ks,
                    unit_location=np.array([0.0, ks * 10.0, 0.0]),
                    unittype_string="SUA",
                )
                ks += 1

    with pynwb.NWBHDF5IO(str(nwb_path), "w") as io:
        io.write(nwbfile)
    return nwb_path


class TestExportPhase2Derivatives:
    def test_writes_one_trial_record_per_session(self, tmp_path):
        from pynpxpipe.io.derivatives import export_phase2_derivatives

        nwb = _write_minimal_nwb_with_units_and_trials(
            tmp_path / "x.nwb",
            n_units_per_probe={"imec0": 2, "imec1": 1},
        )
        out_dir = tmp_path / "07_derivatives"
        export_phase2_derivatives(nwb, out_dir, post_onset_ms=200.0)
        records = list(out_dir.glob("TrialRecord_*.csv"))
        assert len(records) == 1

    def test_writes_per_probe_unit_prop(self, tmp_path):
        from pynpxpipe.io.derivatives import export_phase2_derivatives

        nwb = _write_minimal_nwb_with_units_and_trials(
            tmp_path / "x.nwb",
            n_units_per_probe={"imec0": 2, "imec1": 1},
        )
        out_dir = tmp_path / "07_derivatives"
        export_phase2_derivatives(nwb, out_dir, post_onset_ms=200.0)
        names = sorted(p.name for p in out_dir.glob("UnitProp_*.csv"))
        assert any("_imec0.csv" in n for n in names)
        assert any("_imec1.csv" in n for n in names)
        assert len(names) == 2

    def test_writes_per_probe_trial_raster(self, tmp_path):
        from pynpxpipe.io.derivatives import export_phase2_derivatives

        nwb = _write_minimal_nwb_with_units_and_trials(
            tmp_path / "x.nwb",
            n_units_per_probe={"imec0": 2, "imec1": 1},
        )
        out_dir = tmp_path / "07_derivatives"
        export_phase2_derivatives(nwb, out_dir, post_onset_ms=200.0)
        names = sorted(p.name for p in out_dir.glob("TrialRaster_*.h5"))
        assert any("_imec0.h5" in n for n in names)
        assert any("_imec1.h5" in n for n in names)
        assert len(names) == 2

    def test_skips_probe_with_zero_units_after_split(self, tmp_path):
        """Empty probe contributes nothing — no UnitProp/TrialRaster file with
        that probe_id suffix."""
        from pynpxpipe.io.derivatives import export_phase2_derivatives

        nwb = _write_minimal_nwb_with_units_and_trials(
            tmp_path / "x.nwb",
            n_units_per_probe={"imec0": 2},  # only one probe present
        )
        out_dir = tmp_path / "07_derivatives"
        export_phase2_derivatives(nwb, out_dir, post_onset_ms=200.0)
        unit_props = list(out_dir.glob("UnitProp_*.csv"))
        rasters = list(out_dir.glob("TrialRaster_*.h5"))
        assert len(unit_props) == 1
        assert "_imec0.csv" in unit_props[0].name
        assert len(rasters) == 1
        assert "_imec0.h5" in rasters[0].name

    def test_session_id_falls_back_to_nwb_stem_when_attr_missing(self, tmp_path):
        from pynpxpipe.io.derivatives import export_phase2_derivatives

        nwb_path = tmp_path / "fallback_stem.nwb"
        _write_minimal_nwb_with_units_and_trials(
            nwb_path,
            n_units_per_probe={"imec0": 1},
            session_id=None,
        )
        out_dir = tmp_path / "07_derivatives"
        export_phase2_derivatives(nwb_path, out_dir, post_onset_ms=200.0)
        assert (out_dir / "TrialRecord_fallback_stem.csv").exists()
        assert (out_dir / "UnitProp_fallback_stem_imec0.csv").exists()

    def test_returns_out_dir(self, tmp_path):
        from pynpxpipe.io.derivatives import export_phase2_derivatives

        nwb = _write_minimal_nwb_with_units_and_trials(
            tmp_path / "x.nwb",
            n_units_per_probe={"imec0": 1},
        )
        out_dir = tmp_path / "07_derivatives"
        result = export_phase2_derivatives(nwb, out_dir, post_onset_ms=200.0)
        assert result == out_dir

    def test_skips_raster_when_units_empty(self, tmp_path):
        """An NWB with no units must still write TrialRecord, no Raster files."""
        from pynpxpipe.io.derivatives import export_phase2_derivatives

        nwb = _write_minimal_nwb_with_units_and_trials(
            tmp_path / "no_units.nwb",
            n_units_per_probe={},  # zero units
        )
        out_dir = tmp_path / "07_derivatives"
        export_phase2_derivatives(nwb, out_dir, post_onset_ms=200.0)
        assert list(out_dir.glob("TrialRecord_*.csv"))
        assert not list(out_dir.glob("TrialRaster_*.h5"))
        assert not list(out_dir.glob("UnitProp_*.csv"))
