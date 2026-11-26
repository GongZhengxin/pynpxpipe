"""Maps exceptions and heuristics to structured error classifications."""

from __future__ import annotations

from dataclasses import dataclass

from pynpxpipe.harness.preflight import ErrorClassification, FixTier

# A memory error raised from motion estimation (DREDge) — fixed by coarser time bins.
_MEMORY_MARKERS = ("MemoryError", "Unable to allocate", "ArrayMemoryError")
_MOTION_MARKERS = ("dredge", "motion")


@dataclass
class _Pattern:
    patterns: list[str]
    error_class: str
    fix_tier: FixTier
    auto_fixable: bool
    suggestion: str


_MOTION_OOM = _Pattern(
    patterns=list(_MEMORY_MARKERS),  # only consulted together with a motion marker
    error_class="motion_oom",
    fix_tier="GREEN",
    auto_fixable=True,
    suggestion="Double preprocess.motion_correction.bin_s to shrink DREDge's memory peak",
)

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
        combined = type(exc).__name__ + ": " + exc_str + traceback_str

        lowered = combined.lower()
        motion_oom = any(m in lowered for m in _MOTION_MARKERS)
        candidates = [_MOTION_OOM, *_PATTERNS] if motion_oom else _PATTERNS

        for pattern in candidates:
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
    def suggest_changes(
        classification: ErrorClassification,
        pipeline_config,
        sorting_config,
        *,
        min_batch_size: int,
    ) -> tuple[tuple[str, object], ...]:
        """Concrete parameter changes for a known, fixable failure (ui_redesign §8.6).

        Args:
            classification: Result of :meth:`classify`.
            pipeline_config: Current PipelineConfig (or None).
            sorting_config: Current SortingConfig (or None).
            min_batch_size: Floor for a reduced Kilosort batch_size (ui.min_batch_size).

        Returns:
            ``(("dotted.key", new_value), ...)``; empty when no concrete change applies.
        """
        if classification.error_class == "cuda_oom" and sorting_config is not None:
            current = sorting_config.sorter.params.batch_size
            if isinstance(current, bool) or not isinstance(current, int):
                return ()  # "auto": nothing concrete to lower
            proposed = max(min_batch_size, (current * 2) // 3)
            return (("sorter.params.batch_size", proposed),) if proposed < current else ()
        if classification.error_class == "motion_oom" and pipeline_config is not None:
            bin_s = pipeline_config.preprocess.motion_correction.bin_s
            if isinstance(bin_s, int | float) and not isinstance(bin_s, bool):
                return (("preprocess.motion_correction.bin_s", bin_s * 2),)
        return ()

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
