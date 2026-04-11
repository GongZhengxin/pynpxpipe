"""Serializes harness results to JSON reports and markdown suggestions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pynpxpipe.harness.preflight import CheckResult, StageResult


class Reporter:
    """Writes harness output files to the .harness/ directory."""

    def __init__(self, harness_dir: Path) -> None:
        self._dir = harness_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def write_preflight_report(self, results: list[CheckResult], auto_fixed_count: int) -> None:
        """Write preflight_report.json with overall status and per-check results."""
        counts: dict[str, int] = {"pass": 0, "warn": 0, "fail": 0}
        for r in results:
            counts[r.status] += 1

        if counts["fail"] > 0:
            overall = "FAIL"
        elif counts["warn"] > 0:
            overall = "WARN"
        else:
            overall = "PASS"

        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "overall_status": overall,
            "checks": [
                {
                    "category": r.category,
                    "name": r.name,
                    "status": r.status.upper(),
                    "message": r.message,
                    "auto_fixable": r.auto_fixable,
                    "fix_tier": r.fix_tier,
                    "fix_description": r.fix_description,
                }
                for r in results
            ],
            "summary": {
                "total": len(results),
                "pass": counts["pass"],
                "warn": counts["warn"],
                "fail": counts["fail"],
                "auto_fixed": auto_fixed_count,
            },
        }
        path = self._dir / "preflight_report.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def write_validation_report(self, results: list[StageResult], stop_after: str) -> None:
        """Write validation_report.json with per-stage validation results."""
        stages = []
        for r in results:
            entry: dict[str, Any] = {
                "name": r.name,
                "status": r.status,
                "duration_s": r.duration_s,
                "validations": [
                    {"check": v.check, "status": v.status, "detail": v.detail}
                    for v in r.validations
                ],
            }
            if r.error is not None:
                entry["error"] = {
                    "class": r.error.error_class,
                    "message": r.error.message,
                    "traceback": r.error.traceback,
                    "suggestion": r.error.suggestion,
                    "auto_fixable": r.error.auto_fixable,
                    "fix_tier": r.error.fix_tier,
                    "fix_applied": r.error.fix_applied,
                    "fix_detail": r.error.fix_detail,
                }
            stages.append(entry)

        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "stop_after": stop_after,
            "stages": stages,
        }
        path = self._dir / "validation_report.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def write_suggested_fixes(self, items: list[dict[str, str]]) -> None:
        """Write suggested_fixes.md with RED-tier items requiring human judgment."""
        now = datetime.now(UTC).isoformat(timespec="minutes")
        lines = [f"# Suggested Fixes — {now}\n"]
        for item in items:
            lines.append(f"\n## RED: {item['title']}")
            lines.append(f"- **Stage**: {item['stage']}")
            lines.append(f"- **Detail**: {item['detail']}")
            lines.append(f"- **Suggestion**: {item['suggestion']}")
            lines.append("- **NOT auto-fixed**: Requires human judgment\n")
        path = self._dir / "suggested_fixes.md"
        path.write_text("\n".join(lines), encoding="utf-8")

    def write_auto_fixes(self, fixes: list[dict[str, Any]]) -> None:
        """Write auto_fixes.json with audit log of applied GREEN and YELLOW fixes."""
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "fixes": fixes,
        }
        path = self._dir / "auto_fixes.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
