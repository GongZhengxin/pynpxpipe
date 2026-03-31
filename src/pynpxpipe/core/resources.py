"""Automatic hardware resource detection and pipeline parameter recommendation.

Detects CPU, RAM, GPU, and disk capabilities, then recommends optimal values
for n_jobs, chunk_duration, max_workers, and sorting batch_size.

No UI dependencies: no print(), no click, no sys.exit().
All output goes through structlog. The CLI layer is responsible for
formatting and displaying the HardwareProfile to users.

Design principles:
- Each detection sub-step is independently try/except guarded.
- A single failed sub-detection (e.g., no GPU) never raises; it returns None/[].
- The three-level priority chain (user config > auto-detected > hardcoded default)
  is implemented in ResourceConfig.resolve_*() methods.
- Detection results are cached per-process to avoid repeated probing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pynpxpipe.core.config import PipelineConfig, SortingConfig
    from pynpxpipe.core.session import ProbeInfo


# ---------------------------------------------------------------------------
# Hardcoded fallback values (Priority 3 — used when auto-detection fails)
# ---------------------------------------------------------------------------

FALLBACK_N_JOBS: int = 4
FALLBACK_CHUNK_DURATION: str = "1s"
FALLBACK_MAX_WORKERS: int = 1
FALLBACK_BATCH_SIZE: int = 60000


# ---------------------------------------------------------------------------
# Data classes for detection results
# ---------------------------------------------------------------------------


@dataclass
class CPUInfo:
    """Detected CPU hardware information.

    Attributes:
        physical_cores: Number of physical CPU cores. None if detection failed.
        logical_processors: Number of logical processors (includes hyperthreading).
        frequency_max_mhz: Maximum CPU frequency in MHz. None if unavailable.
        name: CPU model name string.
    """

    physical_cores: int | None
    logical_processors: int
    frequency_max_mhz: float | None
    name: str


@dataclass
class RAMInfo:
    """Detected system RAM information.

    Attributes:
        total_gb: Total installed RAM in gigabytes.
        available_gb: Currently available RAM in gigabytes (includes reclaimable cache).
        used_percent: Current RAM usage as a percentage.
    """

    total_gb: float
    available_gb: float
    used_percent: float


@dataclass
class GPUInfo:
    """Detected information for a single GPU.

    Attributes:
        index: GPU device index (0-based).
        name: GPU model name.
        vram_total_gb: Total VRAM in gigabytes.
        vram_free_gb: Currently free VRAM in gigabytes.
        cuda_available: Whether CUDA is available for this GPU.
        driver_version: NVIDIA driver version string.
        detection_method: How the GPU was detected: "pynvml", "nvidia-smi", or "torch".
    """

    index: int
    name: str
    vram_total_gb: float
    vram_free_gb: float
    cuda_available: bool
    driver_version: str | None
    detection_method: str


@dataclass
class DiskInfo:
    """Detected disk space information.

    Attributes:
        session_dir: Path to the SpikeGLX session directory (read source).
        session_dir_free_gb: Free space on the volume containing session_dir.
        output_dir: Path to the pipeline output directory (write target).
        output_dir_free_gb: Free space on the volume containing output_dir.
        estimated_required_gb: Estimated total disk space needed for the pipeline run.
    """

    session_dir: Path
    session_dir_free_gb: float
    output_dir: Path
    output_dir_free_gb: float
    estimated_required_gb: float | None


@dataclass
class HardwareProfile:
    """Complete hardware detection results for the current machine.

    Produced by ResourceDetector.detect(). All fields are populated from
    best-effort detection; individual fields may be None if detection failed.

    Attributes:
        cpu: CPU information.
        ram: RAM information.
        gpus: List of detected GPUs (empty list = no CUDA GPU found).
        disk: Disk space information.
        detection_timestamp: ISO 8601 timestamp of when detection ran.
        warnings: List of non-fatal issues detected (e.g. low disk space).
    """

    cpu: CPUInfo
    ram: RAMInfo
    gpus: list[GPUInfo]
    disk: DiskInfo
    detection_timestamp: str
    warnings: list[str] = field(default_factory=list)

    @property
    def primary_gpu(self) -> GPUInfo | None:
        """Return the first detected GPU, or None if no GPU is available.

        Returns:
            The GPUInfo for device index 0, or None.
        """
        return self.gpus[0] if self.gpus else None

    def to_log_dict(self) -> dict:
        """Serialize the profile to a structured dict suitable for JSON logging.

        Returns:
            Nested dict with all hardware fields in a log-friendly format.
        """
        raise NotImplementedError("TODO")

    def to_display_lines(self) -> list[str]:
        """Format the profile as human-readable lines for CLI display.

        Returns a list of strings, each representing one display line.
        The CLI layer joins these with newlines and wraps in a box.
        No ANSI codes — the CLI layer applies any styling.

        Returns:
            List of display line strings.
        """
        raise NotImplementedError("TODO")


@dataclass
class RecommendedParams:
    """Auto-detected recommended parameter values for the pipeline.

    Produced by ResourceDetector.recommend(). All values are computed
    from the HardwareProfile and data characteristics, then clamped to
    safe practical ranges.

    Attributes:
        n_jobs: Recommended SpikeInterface internal parallel thread count.
        chunk_duration: Recommended chunk duration string (e.g. "2s").
        max_workers: Recommended multi-probe worker count for parallel mode.
        sorting_batch_size: Recommended Kilosort4 batch_size (NT parameter).
        notes: Human-readable reasoning notes for each recommendation.
    """

    n_jobs: int
    chunk_duration: str
    max_workers: int
    sorting_batch_size: int
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------


class ResourceDetector:
    """Detects hardware capabilities and recommends pipeline parameters.

    All detection sub-steps are independently guarded — a single failure
    (e.g., no NVIDIA drivers installed) does not prevent the rest from running.

    Usage::

        detector = ResourceDetector(session_dir, output_dir)
        profile = detector.detect()
        params = detector.recommend(profile, probes=session.probes)
    """

    def __init__(self, session_dir: Path, output_dir: Path) -> None:
        """Initialize the detector with the session and output directories.

        Args:
            session_dir: SpikeGLX session directory (needed for disk space check).
            output_dir: Pipeline output directory (needed for write-side disk check).
        """
        raise NotImplementedError("TODO")

    def detect(self) -> HardwareProfile:
        """Run all hardware detection sub-steps and return a HardwareProfile.

        Each sub-step (CPU, RAM, GPU, disk) is wrapped in a try/except.
        Partial failures populate the corresponding field with a safe default
        and add a warning to HardwareProfile.warnings.

        Returns:
            HardwareProfile with all available hardware information populated.
        """
        raise NotImplementedError("TODO")

    def recommend(
        self,
        profile: HardwareProfile,
        probes: list["ProbeInfo"] | None = None,
    ) -> RecommendedParams:
        """Compute recommended parameter values from a HardwareProfile.

        Applies the formulas documented in docs/resource_design.md:
        - chunk_duration: based on available RAM and n_jobs
        - n_jobs: min(physical_cores - 2, memory_constraint)
        - max_workers: based on available RAM / per_probe_memory_estimate
        - sorting_batch_size: based on free VRAM

        Args:
            profile: HardwareProfile from detect().
            probes: List of ProbeInfo objects (used for n_channels and sample_rate
                in memory calculations, and for capping max_workers). If None,
                conservative defaults (384ch, 30kHz) are assumed.

        Returns:
            RecommendedParams with computed values and human-readable notes.
        """
        raise NotImplementedError("TODO")

    @classmethod
    def cached_detect(cls, session_dir: Path, output_dir: Path) -> HardwareProfile:
        """Return a cached HardwareProfile, running detection only on first call.

        Caches per process. Subsequent calls with the same (session_dir, output_dir)
        return the cached result without re-probing hardware.

        Args:
            session_dir: SpikeGLX session directory.
            output_dir: Pipeline output directory.

        Returns:
            Cached or freshly detected HardwareProfile.
        """
        raise NotImplementedError("TODO")

    # ------------------------------------------------------------------
    # Private detection sub-steps
    # ------------------------------------------------------------------

    def _detect_cpu(self) -> CPUInfo:
        """Detect CPU hardware information using psutil and platform.

        On Windows, handles the case where psutil.cpu_count(logical=False)
        returns None (common in VMs and heterogeneous-core CPUs) by falling
        back to os.cpu_count() // 2.

        Returns:
            CPUInfo with best-available CPU metrics.
        """
        raise NotImplementedError("TODO")

    def _detect_ram(self) -> RAMInfo:
        """Detect RAM information using psutil.virtual_memory().

        Returns:
            RAMInfo with total_gb, available_gb, and used_percent.
        """
        raise NotImplementedError("TODO")

    def _detect_gpus(self) -> list[GPUInfo]:
        """Detect NVIDIA GPUs using a three-level fallback strategy.

        Detection order:
        1. pynvml (nvidia-ml-py) — lightest, most reliable
        2. nvidia-smi subprocess — no Python package needed
        3. torch.cuda — only if torch is already imported/installed

        Returns:
            List of GPUInfo for each detected CUDA-capable GPU.
            Returns an empty list (not None) if no GPU is found.
        """
        raise NotImplementedError("TODO")

    def _detect_disk(self) -> DiskInfo:
        """Detect available disk space on session_dir and output_dir volumes.

        Uses psutil.disk_usage(). Also computes an estimated space requirement
        based on the session directory size (if accessible).

        Returns:
            DiskInfo with free space and estimated requirements.
        """
        raise NotImplementedError("TODO")

    def _try_detect_gpu_pynvml(self) -> list[GPUInfo] | None:
        """Attempt GPU detection via pynvml (nvidia-ml-py).

        Args:
            (none — uses self.session_dir for context)

        Returns:
            List of GPUInfo if successful, None if pynvml is unavailable or fails.
        """
        raise NotImplementedError("TODO")

    def _try_detect_gpu_nvidia_smi(self) -> list[GPUInfo] | None:
        """Attempt GPU detection via ``nvidia-smi`` subprocess.

        Runs: ``nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version
               --format=csv,noheader,nounits``

        Returns:
            List of GPUInfo if successful, None if nvidia-smi is not found or fails.
        """
        raise NotImplementedError("TODO")

    def _try_detect_gpu_torch(self) -> list[GPUInfo] | None:
        """Attempt GPU detection via torch.cuda (last resort).

        Only called if both pynvml and nvidia-smi have failed. Requires
        PyTorch to already be installed; does not force an import if absent.

        Returns:
            List of GPUInfo if successful, None if torch is unavailable or no CUDA.
        """
        raise NotImplementedError("TODO")

    # ------------------------------------------------------------------
    # Private recommendation sub-computations
    # ------------------------------------------------------------------

    def _recommend_n_jobs(
        self,
        cpu: CPUInfo,
        ram: RAMInfo,
        chunk_duration_s: float,
        n_channels: int,
        sample_rate: float,
    ) -> tuple[int, str]:
        """Compute recommended n_jobs from CPU and RAM constraints.

        Applies the formula from docs/resource_design.md §2.3:
        n_jobs = min(physical_cores - 2, available_ram / memory_per_job)

        Args:
            cpu: Detected CPU information.
            ram: Detected RAM information.
            chunk_duration_s: Already-resolved chunk duration in seconds.
            n_channels: Probe channel count (from ProbeInfo.n_channels).
            sample_rate: Probe sample rate in Hz (from ProbeInfo.sample_rate).

        Returns:
            Tuple (n_jobs, note_string) where note_string explains the binding constraint.
        """
        raise NotImplementedError("TODO")

    def _recommend_chunk_duration(
        self,
        ram: RAMInfo,
        n_jobs_estimate: int,
        n_channels: int,
        sample_rate: float,
    ) -> tuple[str, str]:
        """Compute recommended chunk_duration from available RAM.

        Applies the formula from docs/resource_design.md §2.2.
        Returns a discrete human-friendly string ("0.5s", "1s", "2s", "5s").

        Args:
            ram: Detected RAM information.
            n_jobs_estimate: Estimated n_jobs (can use a default for initial pass).
            n_channels: Probe channel count.
            sample_rate: Probe sample rate in Hz.

        Returns:
            Tuple (chunk_str, note_string) where chunk_str is like "1s".
        """
        raise NotImplementedError("TODO")

    def _recommend_max_workers(
        self,
        ram: RAMInfo,
        n_probes: int,
    ) -> tuple[int, str]:
        """Compute recommended max_workers for parallel probe processing.

        Applies the formula from docs/resource_design.md §2.4.
        Hard cap: min(n_probes, memory_based_limit, 4).

        Args:
            ram: Detected RAM information.
            n_probes: Number of probes in the session.

        Returns:
            Tuple (max_workers, note_string).
        """
        raise NotImplementedError("TODO")

    def _recommend_batch_size(self, gpu: GPUInfo | None) -> tuple[int, str]:
        """Compute recommended Kilosort4 batch_size from available VRAM.

        Applies the formula from docs/resource_design.md §2.5.
        Returns the fallback default (60000) when no GPU is detected,
        with a note that CPU mode will be used.

        Args:
            gpu: Primary GPUInfo, or None if no GPU detected.

        Returns:
            Tuple (batch_size, note_string).
        """
        raise NotImplementedError("TODO")


# ---------------------------------------------------------------------------
# Configuration resolver (three-level priority chain)
# ---------------------------------------------------------------------------


class ResourceConfig:
    """Resolves 'auto' values in pipeline and sorting configs using detected resources.

    Implements the three-level priority chain:
        user config (explicit) > auto-detected > hardcoded fallback

    Usage::

        resolver = ResourceConfig(profile, recommended)
        resolved_pipeline = resolver.resolve_pipeline_config(pipeline_config)
        resolved_sorting  = resolver.resolve_sorting_config(sorting_config)
    """

    def __init__(
        self,
        profile: HardwareProfile,
        recommended: RecommendedParams,
    ) -> None:
        """Initialize the resolver with detection results.

        Args:
            profile: HardwareProfile from ResourceDetector.detect().
            recommended: RecommendedParams from ResourceDetector.recommend().
        """
        raise NotImplementedError("TODO")

    def resolve_pipeline_config(
        self,
        config: "PipelineConfig",
    ) -> "PipelineConfig":
        """Return a new PipelineConfig with all 'auto' values replaced by resolved values.

        Fields that are already explicit integers/strings are preserved unchanged.
        Fields that are 'auto' are filled from RecommendedParams.
        Fields that are 'auto' and recommendation failed use hardcoded fallbacks.

        Args:
            config: PipelineConfig which may contain 'auto' string values.

        Returns:
            A new PipelineConfig with all 'auto' values resolved to concrete types.
        """
        raise NotImplementedError("TODO")

    def resolve_sorting_config(
        self,
        config: "SortingConfig",
    ) -> "SortingConfig":
        """Return a new SortingConfig with 'auto' batch_size replaced by resolved value.

        Args:
            config: SortingConfig which may have batch_size='auto'.

        Returns:
            A new SortingConfig with batch_size resolved to a concrete integer.
        """
        raise NotImplementedError("TODO")

    def validate_user_config(
        self,
        config: "PipelineConfig",
        sorting_config: "SortingConfig",
    ) -> list[str]:
        """Check user-explicit config values against detected hardware limits.

        Does NOT modify config values — only emits warnings when user settings
        exceed detected capabilities (e.g., n_jobs > physical_cores,
        batch_size > VRAM-safe limit).

        Args:
            config: Resolved PipelineConfig (after resolve_pipeline_config()).
            sorting_config: Resolved SortingConfig (after resolve_sorting_config()).

        Returns:
            List of warning strings. Empty list means no issues detected.
        """
        raise NotImplementedError("TODO")

    @staticmethod
    def _resolve_value(
        config_value: int | str,
        detected_value: int | str | None,
        fallback: int | str,
        field_name: str,
    ) -> tuple[int | str, str]:
        """Apply the three-level priority resolution for a single config field.

        Args:
            config_value: Value from config file (int/str, or "auto").
            detected_value: Value from ResourceDetector (or None if detection failed).
            fallback: Hardcoded safe default value.
            field_name: Field name for logging the resolution source.

        Returns:
            Tuple (resolved_value, source) where source is one of:
            "user_config", "auto_detected", "hardcoded_default".
        """
        raise NotImplementedError("TODO")
