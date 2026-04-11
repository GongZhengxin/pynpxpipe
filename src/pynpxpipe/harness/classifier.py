"""Maps exceptions and heuristics to structured error classifications."""

from __future__ import annotations

from dataclasses import dataclass

from pynpxpipe.harness.preflight import ErrorClassification, FixTier


@dataclass
class _Pattern:
    patterns: list[str]
    error_class: str
    fix_tier: FixTier
    auto_fixable: bool
    suggestion: str


_PATTERNS: list[_Pattern] = [
    _Pattern(
        patterns=[
            "CUDA out of memory",
            "OutOfMemoryError",
            "torch.cuda.OutOfMemoryError",
        ],
        error_class="cuda_oom",
        fix_tier="GREEN",
        auto_fixable=True,
        suggestion="Reduce batch_size to the next lower tier (e.g. 60000 → 40000)",
    ),
    _Pattern(
        patterns=[
            "CUDA is not available",
            "no CUDA-capable device",
            "cuda is not available",
        ],
        error_class="cuda_unavailable",
        fix_tier="GREEN",
        auto_fixable=True,
        suggestion="Set torch_device to 'auto' or 'cpu' in sorting config",
    ),
    _Pattern(
        patterns=[
            "No module named 'kilosort'",
            "sorter not installed",
            "kilosort4 is not installed",
        ],
        error_class="sorter_not_found",
        fix_tier="RED",
        auto_fixable=False,
        suggestion="Install Kilosort4: uv add kilosort4",
    ),
    _Pattern(
        patterns=["No IMEC probe", "no probes found", "DiscoverError"],
        error_class="no_probes",
        fix_tier="RED",
        auto_fixable=False,
        suggestion="Check session_dir contains SpikeGLX gate folder with _imec* subdirectories",
    ),
    _Pattern(
        patterns=["SyncError", "alignment residual", "trial count mismatch"],
        error_class="sync_failure",
        fix_tier="RED",
        auto_fixable=False,
        suggestion="Inspect sync diagnostic plots; check event codes and BHV2 alignment",
    ),
]


class Classifier:
    """Classifies exceptions and heuristic conditions into structured results."""

    @staticmethod
    def classify(exc: Exception, traceback_str: str) -> ErrorClassification:
        """Match exception against known patterns; fallback to 'unknown'."""
        exc_str = str(exc)
        combined = exc_str + traceback_str

        for pattern in _PATTERNS:
            if any(p in combined for p in pattern.patterns):
                return ErrorClassification(
                    error_class=pattern.error_class,
                    message=exc_str,
                    traceback=traceback_str,
                    suggestion=pattern.suggestion,
                    auto_fixable=pattern.auto_fixable,
                    fix_tier=pattern.fix_tier,
                )

        return ErrorClassification(
            error_class="unknown",
            message=exc_str,
            traceback=traceback_str,
            suggestion="Inspect the full traceback in validation_report.json and the pipeline log",
            auto_fixable=False,
            fix_tier="RED",
        )

    @staticmethod
    def classify_zero_units(
        stage: str,
        n_total: int,
        per_threshold: dict[str, int],
        bottleneck: str,
    ) -> ErrorClassification:
        """Classify a zero-unit-after-filter condition for curation."""
        detail = ", ".join(f"{k}={v}" for k, v in per_threshold.items())
        suggestion = (
            f"Bottleneck: {bottleneck} — consider relaxing that threshold, "
            f"or verify sorting quality (total units before filter: {n_total})"
        )
        return ErrorClassification(
            error_class="zero_units_after_curation",
            message=f"{stage}: 0 units passed threshold filter (total={n_total}, per_threshold=[{detail}])",
            traceback="",
            suggestion=suggestion,
            auto_fixable=False,
            fix_tier="RED",
        )

    @staticmethod
    def classify_amplitude_cutoff_missing() -> ErrorClassification:
        """Classify the amplitude_cutoff_max config-but-not-computed bug."""
        return ErrorClassification(
            error_class="amplitude_cutoff_not_computed",
            message=(
                "CurationConfig.amplitude_cutoff_max is defined and shown in UI "
                "but curate.py never computes or applies it"
            ),
            traceback="",
            suggestion=(
                "Add 'amplitude_cutoff' to metric_names in curate.py and include "
                "amplitude_cutoff_max in the keep_mask filter"
            ),
            auto_fixable=True,
            fix_tier="YELLOW",
        )
