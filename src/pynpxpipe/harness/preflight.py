"""Preflight checks and shared result types for the harness."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import spikeinterface as si

from pynpxpipe.core.resources import ResourceDetector

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


class PreflightChecker:
    """Runs pre-pipeline environment, config, and data checks."""

    _MIN_DISK_GB: float = 50.0
    _MIN_SI_VERSION: tuple[int, int] = (0, 104)

    def __init__(self, session_dir: Path, output_dir: Path) -> None:
        self._session_dir = session_dir
        self._output_dir = output_dir

    # ── Environment checks ──────────────────────────────────────────────

    def check_cuda_vs_config(self, torch_device: str) -> CheckResult:
        """Fail if torch_device='cuda' but no GPU is detected."""
        if torch_device != "cuda":
            return CheckResult(
                category="environment",
                name="cuda_vs_config",
                status="pass",
                message=f"torch_device='{torch_device}' — no GPU requirement",
            )
        detector = ResourceDetector(self._session_dir, self._output_dir)
        profile = detector.detect()
        if profile.primary_gpu is not None:
            return CheckResult(
                category="environment",
                name="cuda_vs_config",
                status="pass",
                message=f"GPU detected ({profile.primary_gpu.name}), torch_device='cuda' OK",
            )
        return CheckResult(
            category="environment",
            name="cuda_vs_config",
            status="fail",
            message="torch_device='cuda' but no CUDA GPU detected",
            auto_fixable=True,
            fix_tier="GREEN",
            fix_description="Set torch_device to 'auto' in sorting config",
        )

    def check_spikeinterface_version(self) -> CheckResult:
        """Fail if spikeinterface < 0.104."""
        version_str: str = getattr(si, "__version__", "0.0.0")
        parts = version_str.split(".")
        try:
            major, minor = int(parts[0]), int(parts[1])
        except (IndexError, ValueError):
            major, minor = 0, 0
        if (major, minor) >= self._MIN_SI_VERSION:
            return CheckResult(
                category="environment",
                name="spikeinterface_version",
                status="pass",
                message=f"SpikeInterface {version_str} >= 0.104 OK",
            )
        return CheckResult(
            category="environment",
            name="spikeinterface_version",
            status="fail",
            message=f"SpikeInterface {version_str} < 0.104 required",
        )

    def check_disk_space(self) -> CheckResult:
        """Warn if less than 50 GB free on output drive."""
        usage = shutil.disk_usage(self._output_dir.anchor)
        free_gb = usage.free / (1024**3)
        if free_gb >= self._MIN_DISK_GB:
            return CheckResult(
                category="environment",
                name="disk_space",
                status="pass",
                message=f"{free_gb:.1f} GB free on output drive",
            )
        return CheckResult(
            category="environment",
            name="disk_space",
            status="warn",
            message=f"Only {free_gb:.1f} GB free — recommend >= {self._MIN_DISK_GB} GB",
        )

    # ── Config consistency checks ────────────────────────────────────────

    def check_motion_nblocks_exclusion(
        self, run_motion_correction: bool, nblocks: int
    ) -> CheckResult:
        """Fail if both motion correction and KS4 nblocks > 0 are enabled."""
        if run_motion_correction and nblocks > 0:
            return CheckResult(
                category="config",
                name="motion_nblocks_mutual_exclusion",
                status="fail",
                message=(
                    f"run_motion_correction=True and nblocks={nblocks} are mutually exclusive. "
                    "Double-correction degrades sorting quality."
                ),
                auto_fixable=True,
                fix_tier="GREEN",
                fix_description="Disable run_motion_correction (KS4 nblocks handles drift)",
            )
        return CheckResult(
            category="config",
            name="motion_nblocks_mutual_exclusion",
            status="pass",
            message="Motion correction and nblocks are not both active",
        )

    def check_amplitude_cutoff_used(self) -> CheckResult:
        """Check that curate.py actually computes amplitude_cutoff."""
        curate_path = Path(__file__).parents[1] / "stages" / "curate.py"
        if not curate_path.exists():
            return CheckResult(
                category="config",
                name="amplitude_cutoff_computed",
                status="warn",
                message=f"Cannot check: {curate_path} not found",
            )
        source = curate_path.read_text(encoding="utf-8")
        if '"amplitude_cutoff"' in source or "'amplitude_cutoff'" in source:
            return CheckResult(
                category="config",
                name="amplitude_cutoff_computed",
                status="pass",
                message="amplitude_cutoff is computed in curate.py",
            )
        return CheckResult(
            category="config",
            name="amplitude_cutoff_computed",
            status="fail",
            message="amplitude_cutoff_max is in CurationConfig but curate.py never computes it",
            auto_fixable=True,
            fix_tier="YELLOW",
            fix_description="Add 'amplitude_cutoff' to metric_names and keep_mask in curate.py",
        )

    def check_curation_threshold_ranges(
        self,
        isi_max: float,
        amp_cutoff_max: float,
        presence_min: float,
        snr_min: float,
    ) -> CheckResult:
        """Warn if any ratio threshold is outside 0–1 range."""
        issues = []
        for name, val in [
            ("isi_violation_ratio_max", isi_max),
            ("amplitude_cutoff_max", amp_cutoff_max),
            ("presence_ratio_min", presence_min),
        ]:
            if not 0.0 <= val <= 1.0:
                issues.append(f"{name}={val} outside 0–1")
        if issues:
            return CheckResult(
                category="config",
                name="curation_threshold_ranges",
                status="warn",
                message="; ".join(issues),
            )
        return CheckResult(
            category="config",
            name="curation_threshold_ranges",
            status="pass",
            message="All curation thresholds in valid ranges",
        )

    # ── Data integrity checks ────────────────────────────────────────────

    def check_data_integrity(self) -> list[CheckResult]:
        """Check SpikeGLX session directory structure."""
        results: list[CheckResult] = []

        ap_bins = list(self._session_dir.rglob("*.ap.bin"))
        ap_metas = list(self._session_dir.rglob("*.ap.meta"))
        if ap_bins and ap_metas:
            results.append(
                CheckResult(
                    category="data",
                    name="session_ap_files",
                    status="pass",
                    message=f"Found {len(ap_bins)} .ap.bin file(s)",
                )
            )
        else:
            missing = []
            if not ap_bins:
                missing.append(".ap.bin")
            if not ap_metas:
                missing.append(".ap.meta")
            results.append(
                CheckResult(
                    category="data",
                    name="session_ap_files",
                    status="fail",
                    message=f"Missing files in session_dir: {', '.join(missing)}",
                )
            )

        nidq_bins = list(self._session_dir.rglob("*.nidq.bin"))
        nidq_metas = list(self._session_dir.rglob("*.nidq.meta"))
        if nidq_bins and nidq_metas:
            results.append(
                CheckResult(
                    category="data",
                    name="nidq_files",
                    status="pass",
                    message=f"Found {len(nidq_bins)} .nidq.bin file(s)",
                )
            )
        else:
            results.append(
                CheckResult(
                    category="data",
                    name="nidq_files",
                    status="fail",
                    message="Missing .nidq.bin or .nidq.meta in session_dir",
                )
            )

        return results
