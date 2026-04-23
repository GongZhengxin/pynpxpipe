"""Tests for stage validators."""

from __future__ import annotations

import json
from pathlib import Path

from pynpxpipe.harness.validators import VALIDATORS


def _make_output_dir(tmp_path: Path) -> Path:
    out = tmp_path / "output"
    (out / "checkpoints").mkdir(parents=True)
    return out


# ── discover ──────────────────────────────────────────────────────────


def test_discover_validator_pass(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    cp = {
        "stage": "discover",
        "status": "completed",
        "probes": [{"probe_id": "imec0", "sample_rate": 30000.0, "n_channels": 385}],
    }
    (out / "checkpoints" / "discover.json").write_text(json.dumps(cp), encoding="utf-8")

    validator = VALIDATORS["discover"]
    items = validator.validate(output_dir=out, session_probes=["imec0"])
    statuses = {v.check: v.status for v in items}
    assert statuses["probes_found"] == "pass"
    assert statuses["meta_parsed"] == "pass"


def test_discover_validator_no_probes_fail(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    cp = {"stage": "discover", "status": "completed", "probes": []}
    (out / "checkpoints" / "discover.json").write_text(json.dumps(cp), encoding="utf-8")

    validator = VALIDATORS["discover"]
    items = validator.validate(output_dir=out, session_probes=[])
    statuses = {v.check: v.status for v in items}
    assert statuses["probes_found"] == "fail"


# ── sort ──────────────────────────────────────────────────────────────


def test_sort_validator_pass(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    sorting_dir = out / "sorting" / "imec0"
    sorting_dir.mkdir(parents=True)
    (sorting_dir / "spike_times.npy").write_bytes(b"\x00" * 8)

    cp = {"stage": "sort", "status": "completed", "probe_id": "imec0", "n_units": 42}
    (out / "checkpoints" / "sort_imec0.json").write_text(json.dumps(cp), encoding="utf-8")

    validator = VALIDATORS["sort"]
    items = validator.validate(output_dir=out, probe_ids=["imec0"])
    statuses = {v.check: v.status for v in items}
    assert statuses["sorting_output_exists_imec0"] == "pass"
    assert statuses["units_found_imec0"] == "pass"


def test_sort_validator_zero_units_warn(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    sorting_dir = out / "sorting" / "imec0"
    sorting_dir.mkdir(parents=True)

    cp = {"stage": "sort", "status": "completed", "probe_id": "imec0", "n_units": 0}
    (out / "checkpoints" / "sort_imec0.json").write_text(json.dumps(cp), encoding="utf-8")

    validator = VALIDATORS["sort"]
    items = validator.validate(output_dir=out, probe_ids=["imec0"])
    statuses = {v.check: v.status for v in items}
    assert statuses["units_found_imec0"] == "warn"


# ── curate ─────────────────────────────────────────────────────────────


def test_curate_validator_pass(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    curate_dir = out / "05_curated" / "imec0"
    curate_dir.mkdir(parents=True)
    (curate_dir / "quality_metrics.csv").write_text(
        "unit_id,isi_violations_ratio,presence_ratio,snr,amplitude_cutoff\n"
        "unit0,0.01,0.95,2.0,0.05\n",
        encoding="utf-8",
    )
    cp = {
        "stage": "curate",
        "status": "completed",
        "probe_id": "imec0",
        "n_good": 1,
        "n_total": 1,
        "thresholds": {
            "isi_violation_ratio_max": 2.0,
            "amplitude_cutoff_max": 0.5,
            "presence_ratio_min": 0.5,
            "snr_min": 0.3,
        },
    }
    (out / "checkpoints" / "curate_imec0.json").write_text(json.dumps(cp), encoding="utf-8")

    validator = VALIDATORS["curate"]
    items = validator.validate(
        output_dir=out,
        probe_ids=["imec0"],
        config_thresholds={
            "isi_violation_ratio_max": 2.0,
            "amplitude_cutoff_max": 0.5,
            "presence_ratio_min": 0.5,
            "snr_min": 0.3,
        },
    )
    statuses = {v.check: v.status for v in items}
    assert statuses["quality_metrics_exists_imec0"] == "pass"
    assert statuses["good_units_found_imec0"] == "pass"
    assert statuses["amplitude_cutoff_column_exists_imec0"] == "pass"


def test_curate_validator_zero_units_fail(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    curate_dir = out / "05_curated" / "imec0"
    curate_dir.mkdir(parents=True)
    (curate_dir / "quality_metrics.csv").write_text(
        "unit_id,isi_violations_ratio,presence_ratio,snr,amplitude_cutoff\n",
        encoding="utf-8",
    )
    cp = {
        "stage": "curate",
        "status": "completed",
        "probe_id": "imec0",
        "n_good": 0,
        "n_total": 47,
        "thresholds": {
            "isi_violation_ratio_max": 2.0,
            "amplitude_cutoff_max": 0.5,
            "presence_ratio_min": 0.5,
            "snr_min": 0.3,
        },
    }
    (out / "checkpoints" / "curate_imec0.json").write_text(json.dumps(cp), encoding="utf-8")

    validator = VALIDATORS["curate"]
    items = validator.validate(
        output_dir=out,
        probe_ids=["imec0"],
        config_thresholds={
            "isi_violation_ratio_max": 2.0,
            "amplitude_cutoff_max": 0.5,
            "presence_ratio_min": 0.5,
            "snr_min": 0.3,
        },
    )
    statuses = {v.check: v.status for v in items}
    assert statuses["good_units_found_imec0"] == "fail"


# ── export ─────────────────────────────────────────────────────────────


def test_export_validator_pass(tmp_path: Path) -> None:
    out = _make_output_dir(tmp_path)
    nwb_dir = out / "nwb"
    nwb_dir.mkdir()
    (nwb_dir / "session.nwb").write_bytes(b"\x00" * 1024)

    cp = {"stage": "export", "status": "completed", "nwb_path": str(nwb_dir / "session.nwb")}
    (out / "checkpoints" / "export.json").write_text(json.dumps(cp), encoding="utf-8")

    validator = VALIDATORS["export"]
    items = validator.validate(output_dir=out)
    statuses = {v.check: v.status for v in items}
    assert statuses["nwb_file_exists"] == "pass"
