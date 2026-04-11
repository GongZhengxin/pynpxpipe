# tests/test_harness/test_reporter.py
import json
from pathlib import Path

import pytest

from pynpxpipe.harness.preflight import (
    CheckResult,
    ErrorClassification,
    StageResult,
    ValidationItem,
)
from pynpxpipe.harness.reporter import Reporter


@pytest.fixture
def harness_dir(tmp_path: Path) -> Path:
    d = tmp_path / ".harness"
    d.mkdir()
    return d


def test_write_preflight_report_creates_json(harness_dir: Path) -> None:
    results = [
        CheckResult(
            category="environment",
            name="cuda_vs_config",
            status="fail",
            message="torch_device='cuda' but no GPU detected",
            auto_fixable=True,
            fix_tier="GREEN",
            fix_description="Set torch_device to 'auto'",
        )
    ]
    reporter = Reporter(harness_dir)
    reporter.write_preflight_report(results, auto_fixed_count=1)

    report_path = harness_dir / "preflight_report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["overall_status"] == "FAIL"
    assert data["summary"]["fail"] == 1
    assert data["summary"]["auto_fixed"] == 1
    assert len(data["checks"]) == 1
    assert data["checks"][0]["name"] == "cuda_vs_config"


def test_preflight_report_overall_status_pass(harness_dir: Path) -> None:
    results = [
        CheckResult(
            category="environment",
            name="spikeinterface_version",
            status="pass",
            message="SI 0.104.0 OK",
        ),
    ]
    reporter = Reporter(harness_dir)
    reporter.write_preflight_report(results, auto_fixed_count=0)
    data = json.loads((harness_dir / "preflight_report.json").read_text(encoding="utf-8"))
    assert data["overall_status"] == "PASS"


def test_preflight_report_overall_status_warn(harness_dir: Path) -> None:
    results = [
        CheckResult(
            category="environment", name="disk_space", status="warn", message="Only 40GB free"
        ),
    ]
    reporter = Reporter(harness_dir)
    reporter.write_preflight_report(results, auto_fixed_count=0)
    data = json.loads((harness_dir / "preflight_report.json").read_text(encoding="utf-8"))
    assert data["overall_status"] == "WARN"


def test_write_validation_report(harness_dir: Path) -> None:
    results = [
        StageResult(
            name="discover",
            status="passed",
            duration_s=3.2,
            validations=[
                ValidationItem(
                    check="probes_found", status="pass", detail="2 probes: imec0, imec1"
                ),
            ],
        ),
        StageResult(
            name="sort",
            status="failed",
            duration_s=1847.5,
            error=ErrorClassification(
                error_class="cuda_oom",
                message="CUDA out of memory",
                traceback="Traceback...",
                suggestion="Reduce batch_size to 40000",
                auto_fixable=True,
                fix_tier="GREEN",
                fix_applied=True,
                fix_detail="batch_size: 60000 → 40000",
            ),
        ),
    ]
    reporter = Reporter(harness_dir)
    reporter.write_validation_report(results, stop_after="sort")

    report_path = harness_dir / "validation_report.json"
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["stop_after"] == "sort"
    assert len(data["stages"]) == 2
    assert data["stages"][0]["status"] == "passed"
    assert data["stages"][1]["error"]["class"] == "cuda_oom"


def test_write_suggested_fixes_md(harness_dir: Path) -> None:
    reporter = Reporter(harness_dir)
    items = [
        {
            "title": "Curation yielded 0 good units for imec1",
            "stage": "curate",
            "detail": "presence_ratio_min=0.9 filters 44/47 units",
            "suggestion": "Lower presence_ratio_min to 0.5",
        }
    ]
    reporter.write_suggested_fixes(items)
    md_path = harness_dir / "suggested_fixes.md"
    assert md_path.exists()
    content = md_path.read_text(encoding="utf-8")
    assert "RED:" in content
    assert "imec1" in content
    assert "NOT auto-fixed" in content


def test_write_auto_fixes_json(harness_dir: Path) -> None:
    reporter = Reporter(harness_dir)
    fixes = [
        {
            "tier": "GREEN",
            "target": "config",
            "description": "Set torch_device to auto",
            "file": "config/sorting.yaml",
            "before": "torch_device: cuda",
            "after": "torch_device: auto",
            "reversible": True,
        }
    ]
    reporter.write_auto_fixes(fixes)
    af_path = harness_dir / "auto_fixes.json"
    assert af_path.exists()
    data = json.loads(af_path.read_text(encoding="utf-8"))
    assert len(data["fixes"]) == 1
    assert data["fixes"][0]["tier"] == "GREEN"
