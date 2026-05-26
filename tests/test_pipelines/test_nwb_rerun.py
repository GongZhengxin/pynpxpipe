"""Tests for pipelines/nwb_rerun.py — copy-on-write NWB rerun workflows."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pynwb import NWBHDF5IO, NWBFile

from pynpxpipe.core.errors import NWBInputError, NWBRerunError
from pynpxpipe.pipelines.nwb_rerun import rerun_from_nwb


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_units_nwb(path: Path) -> Path:
    nwbfile = NWBFile(
        session_description="tiny rerun fixture",
        identifier="tiny-rerun-fixture",
        session_start_time=datetime(2024, 1, 1),
        session_id="240101_Test_nsd1w_V4",
    )
    nwbfile.add_unit_column("probe_id", "Probe identifier")
    nwbfile.add_unit_column("unittype_string", "Unit type")
    nwbfile.add_unit_column("is_visual", "Visual response flag")
    nwbfile.add_unit_column("slay_score", "SLAY score")
    nwbfile.add_unit(
        id=1,
        spike_times=np.array([0.1, 0.2]),
        probe_id="imec0",
        unittype_string="SUA",
        is_visual=True,
        slay_score=0.9,
    )
    nwbfile.add_unit(
        id=2,
        spike_times=np.array([0.3, 0.4]),
        probe_id="imec0",
        unittype_string="MUA",
        is_visual=False,
        slay_score=0.1,
    )
    with NWBHDF5IO(path, "w") as io:
        io.write(nwbfile)
    return path


def _write_postprocess_nwb(
    path: Path,
    *,
    probe_id: str = "imec0",
    include_trials: bool = True,
) -> Path:
    """Write an NWB fixture where unit 1 has a reliable onset response."""
    nwbfile = NWBFile(
        session_description="tiny postprocess rerun fixture",
        identifier="tiny-postprocess-rerun-fixture",
        session_start_time=datetime(2024, 1, 1),
        session_id="240101_Test_nsd1w_V4",
    )
    reference_onsets = np.arange(1.0, 11.0)
    probe_onsets = reference_onsets if probe_id == "imec0" else reference_onsets + 0.25
    responsive_spikes = np.sort(np.concatenate([probe_onsets + 0.023, probe_onsets + 0.067]))

    nwbfile.add_unit_column("probe_id", "Probe identifier")
    nwbfile.add_unit_column("unittype_string", "Unit type")
    nwbfile.add_unit_column("is_visual", "Visual response flag")
    nwbfile.add_unit_column("slay_score", "SLAY score")
    nwbfile.add_unit(
        id=1,
        spike_times=responsive_spikes,
        probe_id=probe_id,
        unittype_string="SUA",
        is_visual=False,
        slay_score=0.0,
    )
    nwbfile.add_unit(
        id=2,
        spike_times=np.array([], dtype=float),
        probe_id=probe_id,
        unittype_string="MUA",
        is_visual=True,
        slay_score=0.5,
    )

    if include_trials:
        nwbfile.add_trial_column("stim_onset_time", "Reference-probe onset time")
        nwbfile.add_trial_column("trial_valid", "Whether the trial is valid")
        nwbfile.add_trial_column(
            f"stim_onset_imec_{probe_id}",
            f"Stimulus onset time for {probe_id}",
        )
        if probe_id != "imec0":
            nwbfile.add_trial_column(
                "stim_onset_imec_imec0",
                "Stimulus onset time for imec0",
            )
        for reference_onset, probe_onset in zip(reference_onsets, probe_onsets, strict=True):
            kwargs = {
                "start_time": float(reference_onset),
                "stop_time": float(reference_onset + 0.35),
                "stim_onset_time": float(reference_onset),
                "trial_valid": True,
                f"stim_onset_imec_{probe_id}": float(probe_onset),
            }
            if probe_id != "imec0":
                kwargs["stim_onset_imec_imec0"] = float(reference_onset)
            nwbfile.add_trial(**kwargs)

    with NWBHDF5IO(path, "w") as io:
        io.write(nwbfile)
    return path


def _read_units(path: Path) -> pd.DataFrame:
    with NWBHDF5IO(path, "r") as io:
        nwbfile = io.read()
        return nwbfile.units.to_dataframe().reset_index(names="unit_id")


def test_rewrite_units_creates_copy_and_preserves_input(tmp_path: Path) -> None:
    """rewrite-units writes a new NWB and leaves the input bytes untouched."""
    input_nwb = _write_units_nwb(tmp_path / "input.nwb")
    before_hash = _sha256(input_nwb)
    updates = tmp_path / "updates.csv"
    updates.write_text("unit_id,unittype_string\n1,MUA\n", encoding="utf-8")

    result = rerun_from_nwb(input_nwb, tmp_path / "out", unit_updates=updates)

    assert result.output_nwb.exists()
    assert result.output_nwb != input_nwb
    assert _sha256(input_nwb) == before_hash


def test_rewrite_units_updates_unittype(tmp_path: Path) -> None:
    """Updated unit metadata is visible in the copied NWB."""
    input_nwb = _write_units_nwb(tmp_path / "input.nwb")
    updates = tmp_path / "updates.csv"
    updates.write_text("unit_id,unittype_string,is_visual\n1,MUA,false\n", encoding="utf-8")

    result = rerun_from_nwb(input_nwb, tmp_path / "out", unit_updates=updates)

    units = _read_units(result.output_nwb)
    row = units.loc[units["unit_id"] == 1].iloc[0]
    assert row["unittype_string"] == "MUA"
    assert bool(row["is_visual"]) is False


def test_rewrite_units_filters_keep_false(tmp_path: Path) -> None:
    """keep=False removes a unit from the output units table."""
    input_nwb = _write_units_nwb(tmp_path / "input.nwb")
    updates = tmp_path / "updates.csv"
    updates.write_text("unit_id,keep\n2,false\n", encoding="utf-8")

    result = rerun_from_nwb(input_nwb, tmp_path / "out", unit_updates=updates)

    units = _read_units(result.output_nwb)
    assert list(units["unit_id"]) == [1]
    assert result.n_units_before == 2
    assert result.n_units_after == 1


def test_rewrite_units_rejects_unknown_unit_id(tmp_path: Path) -> None:
    """Updates cannot target units absent from the input NWB."""
    input_nwb = _write_units_nwb(tmp_path / "input.nwb")
    updates = tmp_path / "updates.csv"
    updates.write_text("unit_id,unittype_string\n99,SUA\n", encoding="utf-8")

    with pytest.raises(NWBRerunError, match="Unknown unit_id"):
        rerun_from_nwb(input_nwb, tmp_path / "out", unit_updates=updates)


def test_rewrite_units_rejects_spike_times_update(tmp_path: Path) -> None:
    """PR1 deliberately forbids spike_times rewrites."""
    input_nwb = _write_units_nwb(tmp_path / "input.nwb")
    updates = tmp_path / "updates.csv"
    updates.write_text('unit_id,spike_times\n1,"[0.1]"\n', encoding="utf-8")

    with pytest.raises(NWBRerunError, match="spike_times"):
        rerun_from_nwb(input_nwb, tmp_path / "out", unit_updates=updates)


def test_rewrite_units_writes_checkpoint_and_report(tmp_path: Path) -> None:
    """Successful reruns emit machine-readable report and checkpoint files."""
    input_nwb = _write_units_nwb(tmp_path / "input.nwb")
    updates = tmp_path / "updates.csv"
    updates.write_text("unit_id,unittype_string\n1,MUA\n", encoding="utf-8")

    result = rerun_from_nwb(input_nwb, tmp_path / "out", unit_updates=updates)

    checkpoint = json.loads(result.checkpoint_path.read_text(encoding="utf-8"))
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert checkpoint["status"] == "completed"
    assert checkpoint["output_nwb"] == str(result.output_nwb)
    assert report["n_units_before"] == 2
    assert report["n_units_after"] == 2


def test_rewrite_units_report_in_scratch(tmp_path: Path) -> None:
    """The copied NWB carries rerun provenance in scratch."""
    input_nwb = _write_units_nwb(tmp_path / "input.nwb")
    updates = tmp_path / "updates.csv"
    updates.write_text("unit_id,unittype_string\n1,MUA\n", encoding="utf-8")

    result = rerun_from_nwb(input_nwb, tmp_path / "out", unit_updates=updates)

    with NWBHDF5IO(result.output_nwb, "r") as io:
        nwbfile = io.read()
        assert "nwb_rerun_report" in nwbfile.scratch


def test_auto_version_increments(tmp_path: Path) -> None:
    """A second rerun chooses v002 when v001 already exists."""
    input_nwb = _write_units_nwb(tmp_path / "input.nwb")
    updates = tmp_path / "updates.csv"
    updates.write_text("unit_id,unittype_string\n1,MUA\n", encoding="utf-8")

    first = rerun_from_nwb(input_nwb, tmp_path / "out", unit_updates=updates)
    second = rerun_from_nwb(input_nwb, tmp_path / "out", unit_updates=updates)

    assert first.output_nwb.name.endswith("_rerun_v001.nwb")
    assert second.output_nwb.name.endswith("_rerun_v002.nwb")


def test_postprocess_mode_recomputes_slay_and_is_visual(tmp_path: Path) -> None:
    """postprocess mode recomputes lightweight visual metrics from units + trials."""
    input_nwb = _write_postprocess_nwb(tmp_path / "input.nwb")

    result = rerun_from_nwb(input_nwb, tmp_path / "out", mode="postprocess")

    units = _read_units(result.output_nwb)
    responsive = units.loc[units["unit_id"] == 1].iloc[0]
    silent = units.loc[units["unit_id"] == 2].iloc[0]
    assert result.mode == "postprocess"
    assert responsive["slay_score"] == pytest.approx(1.0)
    assert bool(responsive["is_visual"]) is True
    assert pd.isna(silent["slay_score"])
    assert bool(silent["is_visual"]) is False


def test_postprocess_mode_uses_probe_specific_trial_column(tmp_path: Path) -> None:
    """Non-reference probes use stim_onset_imec_{probe_id}, not stim_onset_time."""
    input_nwb = _write_postprocess_nwb(tmp_path / "input.nwb", probe_id="imec1")

    result = rerun_from_nwb(input_nwb, tmp_path / "out", mode="postprocess")

    units = _read_units(result.output_nwb)
    row = units.loc[units["unit_id"] == 1].iloc[0]
    assert row["slay_score"] == pytest.approx(1.0)
    assert bool(row["is_visual"]) is True


def test_postprocess_mode_requires_trials(tmp_path: Path) -> None:
    """postprocess mode fails clearly when an NWB has units but no trials."""
    input_nwb = _write_postprocess_nwb(
        tmp_path / "input.nwb",
        include_trials=False,
    )

    with pytest.raises((NWBInputError, NWBRerunError), match="trials"):
        rerun_from_nwb(input_nwb, tmp_path / "out", mode="postprocess")
