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

import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil

from pynpxpipe.core.logging import get_logger

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

# Memory per second per job: 384ch × 30kHz × float32 × 5 pipeline copies
_BYTES_PER_SEC_PER_JOB_DEFAULT: int = 384 * 30_000 * 4 * 5  # 230_400_000

# Kilosort4 VRAM constants
_VRAM_OVERHEAD_GB: float = 2.0
_BYTES_PER_SAMPLE_VRAM: int = 384 * 4 * 10  # 15_360

# Per-probe peak memory estimate for parallel processing
_PER_PROBE_PEAK_GB: float = 5.0


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
        return {
            "cpu": {
                "physical_cores": self.cpu.physical_cores,
                "logical_processors": self.cpu.logical_processors,
                "frequency_max_mhz": self.cpu.frequency_max_mhz,
                "name": self.cpu.name,
            },
            "ram": {
                "total_gb": round(self.ram.total_gb, 1),
                "available_gb": round(self.ram.available_gb, 1),
                "used_percent": round(self.ram.used_percent, 1),
            },
            "gpus": [
                {
                    "index": g.index,
                    "name": g.name,
                    "vram_total_gb": round(g.vram_total_gb, 1),
                    "vram_free_gb": round(g.vram_free_gb, 1),
                    "cuda_available": g.cuda_available,
                    "driver_version": g.driver_version,
                    "detection_method": g.detection_method,
                }
                for g in self.gpus
            ],
            "disk": {
                "session_dir": str(self.disk.session_dir),
                "session_dir_free_gb": round(self.disk.session_dir_free_gb, 1),
                "output_dir": str(self.disk.output_dir),
                "output_dir_free_gb": round(self.disk.output_dir_free_gb, 1),
                "estimated_required_gb": self.disk.estimated_required_gb,
            },
            "warnings": self.warnings,
        }

    def to_display_lines(self) -> list[str]:
        """Format the profile as human-readable lines for CLI display.

        Returns a list of strings, each representing one display line.
        The CLI layer joins these with newlines and wraps in a box.
        No ANSI codes — the CLI layer applies any styling.

        Returns:
            List of display line strings.
        """
        sep = "─" * 49
        lines = [
            sep,
            "  pynpxpipe resource check",
            sep,
            f"  CPU   │ {self.cpu.name}",
        ]
        freq = f"  @  {self.cpu.frequency_max_mhz/1000:.1f} GHz" if self.cpu.frequency_max_mhz else ""
        cores_str = f"{self.cpu.physical_cores or '?'} physical cores ({self.cpu.logical_processors} logical)"
        lines.append(f"        │ {cores_str}{freq}")
        lines.append(f"  RAM   │ {self.ram.total_gb:.1f} GB total  │  {self.ram.available_gb:.1f} GB available")
        if self.gpus:
            g = self.gpus[0]
            lines.append(f"  GPU   │ {g.name}  │  {g.vram_total_gb:.1f} GB VRAM  │  {g.vram_free_gb:.1f} GB free")
        else:
            lines.append("  GPU   │ No CUDA GPU detected")
        lines.append(f"  Disk  │ output → {self.disk.output_dir}  │  {self.disk.output_dir_free_gb:.0f} GB free")
        lines.append(sep)
        for w in self.warnings:
            lines.append(f"  ⚠  {w}")
        return lines


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

    _cache: dict[tuple[str, str], HardwareProfile] = {}

    def __init__(self, session_dir: Path, output_dir: Path) -> None:
        """Initialize the detector with the session and output directories.

        Args:
            session_dir: SpikeGLX session directory (needed for disk space check).
            output_dir: Pipeline output directory (needed for write-side disk check).
        """
        self._session_dir = session_dir
        self._output_dir = output_dir
        self._warnings: list[str] = []
        self._logger = get_logger(__name__)

    def detect(self) -> HardwareProfile:
        """Run all hardware detection sub-steps and return a HardwareProfile.

        Each sub-step (CPU, RAM, GPU, disk) is wrapped in a try/except.
        Partial failures populate the corresponding field with a safe default
        and add a warning to HardwareProfile.warnings.

        Returns:
            HardwareProfile with all available hardware information populated.
        """
        self._warnings = []

        try:
            cpu = self._detect_cpu()
        except Exception as e:
            self._warnings.append(f"CPU detection failed: {e}")
            cpu = CPUInfo(physical_cores=None, logical_processors=1,
                          frequency_max_mhz=None, name="unknown")

        try:
            ram = self._detect_ram()
        except Exception as e:
            self._warnings.append(f"RAM detection failed: {e}")
            ram = RAMInfo(total_gb=8.0, available_gb=4.0, used_percent=50.0)

        try:
            gpus = self._detect_gpus()
        except Exception as e:
            self._warnings.append(f"GPU detection failed: {e}")
            gpus = []

        try:
            disk = self._detect_disk()
        except Exception as e:
            self._warnings.append(f"Disk detection failed: {e}")
            disk = DiskInfo(
                session_dir=self._session_dir, session_dir_free_gb=0.0,
                output_dir=self._output_dir, output_dir_free_gb=0.0,
                estimated_required_gb=None,
            )

        return HardwareProfile(
            cpu=cpu,
            ram=ram,
            gpus=gpus,
            disk=disk,
            detection_timestamp=datetime.now().isoformat(),
            warnings=list(self._warnings),
        )

    def recommend(
        self,
        profile: HardwareProfile,
        probes: list[ProbeInfo] | None = None,
    ) -> RecommendedParams:
        """Compute recommended parameter values from a HardwareProfile.

        Args:
            profile: HardwareProfile from detect().
            probes: List of ProbeInfo objects. If None, conservative defaults assumed.

        Returns:
            RecommendedParams with computed values and human-readable notes.
        """
        n_channels = probes[0].n_channels if probes else 384
        sample_rate = probes[0].sample_rate if probes else 30_000.0
        n_probes = len(probes) if probes else 1

        chunk_str, chunk_note = self._recommend_chunk_duration(
            profile.ram, FALLBACK_N_JOBS, n_channels, sample_rate
        )
        chunk_s = float(chunk_str[:-1])

        n_jobs, jobs_note = self._recommend_n_jobs(
            profile.cpu, profile.ram, chunk_s, n_channels, sample_rate
        )

        max_workers, workers_note = self._recommend_max_workers(profile.ram, n_probes)
        batch_size, batch_note = self._recommend_batch_size(profile.primary_gpu)

        return RecommendedParams(
            n_jobs=n_jobs,
            chunk_duration=chunk_str,
            max_workers=max_workers,
            sorting_batch_size=batch_size,
            notes=[chunk_note, jobs_note, workers_note, batch_note],
        )

    @classmethod
    def cached_detect(cls, session_dir: Path, output_dir: Path) -> HardwareProfile:
        """Return a cached HardwareProfile, running detection only on first call.

        Args:
            session_dir: SpikeGLX session directory.
            output_dir: Pipeline output directory.

        Returns:
            Cached or freshly detected HardwareProfile.
        """
        key = (str(session_dir), str(output_dir))
        if key not in cls._cache:
            cls._cache[key] = cls(session_dir, output_dir).detect()
        return cls._cache[key]

    # ------------------------------------------------------------------
    # Private detection sub-steps
    # ------------------------------------------------------------------

    def _detect_cpu(self) -> CPUInfo:
        """Detect CPU hardware information using psutil and platform."""
        physical_cores = psutil.cpu_count(logical=False)
        if physical_cores is None:
            cpu_count = os.cpu_count()
            physical_cores = max(1, (cpu_count or 2) // 2)

        logical_processors = psutil.cpu_count(logical=True) or 1

        try:
            freq = psutil.cpu_freq()
            frequency_max_mhz = freq.max if freq else None
        except Exception:
            frequency_max_mhz = None

        name = platform.processor() or "unknown"
        return CPUInfo(
            physical_cores=physical_cores,
            logical_processors=logical_processors,
            frequency_max_mhz=frequency_max_mhz,
            name=name,
        )

    def _detect_ram(self) -> RAMInfo:
        """Detect RAM information using psutil.virtual_memory()."""
        mem = psutil.virtual_memory()
        return RAMInfo(
            total_gb=mem.total / 1e9,
            available_gb=mem.available / 1e9,
            used_percent=mem.percent,
        )

    def _detect_gpus(self) -> list[GPUInfo]:
        """Detect NVIDIA GPUs using a three-level fallback strategy."""
        result = self._try_detect_gpu_pynvml()
        if result is not None:
            return result

        result = self._try_detect_gpu_nvidia_smi()
        if result is not None:
            return result

        result = self._try_detect_gpu_torch()
        if result is not None:
            return result

        self._warnings.append("No CUDA GPU detected; sorting will use CPU mode")
        return []

    def _detect_disk(self) -> DiskInfo:
        """Detect available disk space on session_dir and output_dir volumes."""
        try:
            session_usage = psutil.disk_usage(str(self._session_dir))
            session_free_gb = session_usage.free / 1e9
        except Exception:
            session_free_gb = 0.0

        try:
            output_usage = psutil.disk_usage(str(self._output_dir))
            output_free_gb = output_usage.free / 1e9
        except Exception:
            output_free_gb = 0.0

        try:
            raw_ap_size_bytes = sum(
                p.stat().st_size for p in self._session_dir.rglob("*.ap.bin")
                if p.is_file()
            )
            raw_ap_gb = raw_ap_size_bytes / 1e9
            n_probes = max(1, len(list(self._session_dir.glob("imec*"))))
            estimated_gb = (raw_ap_gb * 0.4 + 2.0 + raw_ap_gb * 0.05) * n_probes
        except Exception:
            estimated_gb = None

        if estimated_gb and output_free_gb < estimated_gb * 1.2:
            self._warnings.append(
                f"Low disk space: need ~{estimated_gb:.0f} GB, only {output_free_gb:.0f} GB free"
            )

        return DiskInfo(
            session_dir=self._session_dir,
            session_dir_free_gb=session_free_gb,
            output_dir=self._output_dir,
            output_dir_free_gb=output_free_gb,
            estimated_required_gb=estimated_gb,
        )

    def _try_detect_gpu_pynvml(self) -> list[GPUInfo] | None:
        """Attempt GPU detection via pynvml (nvidia-ml-py)."""
        try:
            import pynvml  # type: ignore[import]
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            gpus = []
            for i in range(count):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                name = pynvml.nvmlDeviceGetName(h)
                if isinstance(name, bytes):
                    name = name.decode()
                driver = pynvml.nvmlSystemGetDriverVersion()
                if isinstance(driver, bytes):
                    driver = driver.decode()
                gpus.append(GPUInfo(
                    index=i, name=name,
                    vram_total_gb=mem.total / 1e9,
                    vram_free_gb=mem.free / 1e9,
                    cuda_available=True,
                    driver_version=driver,
                    detection_method="pynvml",
                ))
            pynvml.nvmlShutdown()
            return gpus
        except Exception:
            return None

    def _try_detect_gpu_nvidia_smi(self) -> list[GPUInfo] | None:
        """Attempt GPU detection via nvidia-smi subprocess."""
        try:
            result = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=name,memory.total,memory.free,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode != 0:
                return None
            gpus = []
            for i, line in enumerate(result.stdout.strip().splitlines()):
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 4:
                    continue
                name, total_mib, free_mib, driver = parts[0], parts[1], parts[2], parts[3]
                gpus.append(GPUInfo(
                    index=i, name=name,
                    vram_total_gb=float(total_mib) / 1024,
                    vram_free_gb=float(free_mib) / 1024,
                    cuda_available=True,
                    driver_version=driver,
                    detection_method="nvidia-smi",
                ))
            return gpus
        except Exception:
            return None

    def _try_detect_gpu_torch(self) -> list[GPUInfo] | None:
        """Attempt GPU detection via torch.cuda (last resort)."""
        try:
            import torch  # type: ignore[import]
            if not torch.cuda.is_available():
                return None
            gpus = []
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                free, total = torch.cuda.mem_get_info(i)
                gpus.append(GPUInfo(
                    index=i, name=props.name,
                    vram_total_gb=total / 1e9,
                    vram_free_gb=free / 1e9,
                    cuda_available=True,
                    driver_version=None,
                    detection_method="torch",
                ))
            return gpus
        except Exception:
            return None

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
        """Compute recommended n_jobs from CPU and RAM constraints."""
        physical = cpu.physical_cores or max(1, (os.cpu_count() or 2) // 2)
        n_jobs_cpu = max(1, physical - 2)

        bytes_per_sec = n_channels * sample_rate * 4 * 5
        memory_per_job = bytes_per_sec * chunk_duration_s
        available_bytes = ram.available_gb * 1e9
        n_jobs_mem = max(1, int(available_bytes * 0.60 / memory_per_job))

        n_jobs = min(n_jobs_cpu, n_jobs_mem, 16)

        if n_jobs_cpu <= n_jobs_mem:
            note = f"n_jobs: CPU-bound ({physical} physical cores → {n_jobs})"
        else:
            note = f"n_jobs: RAM-bound ({ram.available_gb:.1f} GB available → {n_jobs})"

        return n_jobs, note

    def _recommend_chunk_duration(
        self,
        ram: RAMInfo,
        n_jobs_estimate: int,
        n_channels: int,
        sample_rate: float,
    ) -> tuple[str, str]:
        """Compute recommended chunk_duration from available RAM."""
        bytes_per_sec = n_channels * sample_rate * 4 * 5
        available_bytes = ram.available_gb * 1e9
        memory_budget = available_bytes * 0.40
        bytes_per_chunk = memory_budget / max(1, n_jobs_estimate)
        chunk_raw_s = bytes_per_chunk / bytes_per_sec
        chunk_raw_s = max(0.5, min(5.0, chunk_raw_s))

        if chunk_raw_s >= 4.0:
            chunk_str = "5s"
        elif chunk_raw_s >= 1.5:
            chunk_str = "2s"
        elif chunk_raw_s >= 0.8:
            chunk_str = "1s"
        else:
            chunk_str = "0.5s"

        note = f"chunk_duration: RAM-bound ({ram.available_gb:.1f} GB available → {chunk_str})"
        return chunk_str, note

    def _recommend_max_workers(
        self,
        ram: RAMInfo,
        n_probes: int,
    ) -> tuple[int, str]:
        """Compute recommended max_workers for parallel probe processing."""
        max_by_memory = max(1, int(ram.available_gb * 0.70 / _PER_PROBE_PEAK_GB))
        max_workers = min(max_by_memory, n_probes, 4)
        note = f"max_workers: {max_workers} (RAM: {ram.available_gb:.1f} GB, probes: {n_probes})"
        return max_workers, note

    def _recommend_batch_size(self, gpu: GPUInfo | None) -> tuple[int, str]:
        """Compute recommended Kilosort4 batch_size from available VRAM."""
        if gpu is None:
            return FALLBACK_BATCH_SIZE, "batch_size: no GPU detected, using default (CPU mode)"

        vram_for_batch = max(0.0, gpu.vram_free_gb - _VRAM_OVERHEAD_GB) * (1024**3) * 0.80
        batch_raw = int(vram_for_batch / _BYTES_PER_SAMPLE_VRAM)

        if batch_raw >= 60_000:
            batch_size = 60_000
        elif batch_raw >= 40_000:
            batch_size = 40_000
        elif batch_raw >= 30_000:
            batch_size = 30_000
        elif batch_raw >= 15_000:
            batch_size = 15_000
        else:
            batch_size = FALLBACK_BATCH_SIZE

        note = f"batch_size: {batch_size} (VRAM free: {gpu.vram_free_gb:.1f} GB)"
        return batch_size, note


# ---------------------------------------------------------------------------
# Configuration resolver (three-level priority chain)
# ---------------------------------------------------------------------------


class ResourceConfig:
    """Resolves 'auto' values in pipeline and sorting configs using detected resources.

    Implements the three-level priority chain:
        user config (explicit) > auto-detected > hardcoded fallback
    """

    def __init__(
        self,
        profile: HardwareProfile,
        recommended: RecommendedParams,
    ) -> None:
        """Initialize the resolver with detection results."""
        self._profile = profile
        self._recommended = recommended
        self._logger = get_logger(__name__)

    def resolve_pipeline_config(
        self,
        config: PipelineConfig,
    ) -> PipelineConfig:
        """Return a new PipelineConfig with all 'auto' values replaced by resolved values."""
        import dataclasses

        # Resolve resources sub-config
        res = config.resources
        n_jobs_val, _ = self._resolve_value(
            res.n_jobs, self._recommended.n_jobs, FALLBACK_N_JOBS, "resources.n_jobs"
        )
        chunk_val, _ = self._resolve_value(
            res.chunk_duration, self._recommended.chunk_duration,
            FALLBACK_CHUNK_DURATION, "resources.chunk_duration"
        )
        # max_memory kept as-is (info only)
        new_resources = dataclasses.replace(
            res, n_jobs=n_jobs_val, chunk_duration=chunk_val
        )

        # Resolve parallel sub-config
        par = config.parallel
        workers_val, _ = self._resolve_value(
            par.max_workers, self._recommended.max_workers,
            FALLBACK_MAX_WORKERS, "parallel.max_workers"
        )
        new_parallel = dataclasses.replace(par, max_workers=workers_val)

        return dataclasses.replace(config, resources=new_resources, parallel=new_parallel)

    def resolve_sorting_config(
        self,
        config: SortingConfig,
    ) -> SortingConfig:
        """Return a new SortingConfig with 'auto' batch_size replaced by resolved value."""
        import dataclasses

        params = config.sorter.params
        batch_val, _ = self._resolve_value(
            params.batch_size, self._recommended.sorting_batch_size,
            FALLBACK_BATCH_SIZE, "sorter.params.batch_size"
        )
        new_params = dataclasses.replace(params, batch_size=batch_val)
        new_sorter = dataclasses.replace(config.sorter, params=new_params)
        return dataclasses.replace(config, sorter=new_sorter)

    def validate_user_config(
        self,
        config: PipelineConfig,
        sorting_config: SortingConfig,
    ) -> list[str]:
        """Check user-explicit config values against detected hardware limits."""
        warnings: list[str] = []
        physical = self._profile.cpu.physical_cores

        # n_jobs vs physical cores
        n_jobs = config.resources.n_jobs
        if isinstance(n_jobs, int) and physical is not None and n_jobs > physical:
            warnings.append(
                f"n_jobs={n_jobs} set in config, but only {physical} physical cores detected. "
                "This may cause CPU oversubscription."
            )

        # batch_size vs VRAM
        gpu = self._profile.primary_gpu
        batch = sorting_config.sorter.params.batch_size
        if isinstance(batch, int) and gpu is not None:
            vram_safe = max(0.0, gpu.vram_free_gb - _VRAM_OVERHEAD_GB) * (1024**3) * 0.80
            safe_max = int(vram_safe / _BYTES_PER_SAMPLE_VRAM)
            if batch > safe_max and safe_max > 0:
                warnings.append(
                    f"sorting.params.batch_size={batch} set in config, but GPU has only "
                    f"{gpu.vram_free_gb:.1f} GB VRAM free. Kilosort4 may OOM."
                )

        return warnings

    @staticmethod
    def _resolve_value(
        config_value: int | str,
        detected_value: int | str | None,
        fallback: int | str,
        field_name: str,
    ) -> tuple[int | str, str]:
        """Apply the three-level priority resolution for a single config field."""
        if config_value != "auto":
            return config_value, "user_config"
        if detected_value is not None:
            return detected_value, "auto_detected"
        return fallback, "hardcoded_default"
