"""Preflight checks and shared result types for the harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

CheckStatus = Literal["pass", "warn", "fail"]
FixTier = Literal["GREEN", "YELLOW", "RED"]


@dataclass
class CheckResult:
    """Result of a single preflight check."""

    category: str
    name: str
    status: CheckStatus
    message: str
    auto_fixable: bool = False
    fix_tier: FixTier | None = None
    fix_description: str = ""


@dataclass
class ValidationItem:
    """A single assertion result within a stage validator."""

    check: str
    status: CheckStatus
    detail: str


@dataclass
class ErrorClassification:
    """Classified error from a failed pipeline stage."""

    error_class: str
    message: str
    traceback: str
    suggestion: str
    auto_fixable: bool
    fix_tier: FixTier
    fix_applied: bool = False
    fix_detail: str = ""


@dataclass
class StageResult:
    """Validation result for a single pipeline stage."""

    name: str
    status: str  # "passed" | "failed" | "skipped"
    duration_s: float
    validations: list[ValidationItem] = field(default_factory=list)
    error: ErrorClassification | None = None
