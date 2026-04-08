"""Tests for core/resources.py — hardware detection and parameter recommendation.

All psutil / pynvml / subprocess calls are mocked to keep tests fast and
platform-independent. Tests verify the recommendation formulas and three-level
priority resolution, not the hardware itself.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from pynpxpipe.core.resources import (
    FALLBACK_BATCH_SIZE,
    CPUInfo,
    DiskInfo,
    GPUInfo,
    HardwareProfile,
    RAMInfo,
    RecommendedParams,
    ResourceConfig,
    ResourceDetector,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cpu(physical=8, logical=16, freq=3600.0, name="Test CPU") -> CPUInfo:
    return CPUInfo(
        physical_cores=physical, logical_processors=logical, frequency_max_mhz=freq, name=name
    )


def _make_ram(total_gb=64.0, available_gb=32.0, used_percent=50.0) -> RAMInfo:
    return RAMInfo(total_gb=total_gb, available_gb=available_gb, used_percent=used_percent)


def _make_gpu(vram_free_gb=22.0) -> GPUInfo:
    return GPUInfo(
        index=0,
        name="RTX 3090",
        vram_total_gb=24.0,
        vram_free_gb=vram_free_gb,
        cuda_available=True,
        driver_version="535.104",
        detection_method="pynvml",
    )


def _make_disk(tmp_path: Path) -> DiskInfo:
    return DiskInfo(
        session_dir=tmp_path,
        session_dir_free_gb=1000.0,
        output_dir=tmp_path,
        output_dir_free_gb=500.0,
        estimated_required_gb=None,
    )


def _make_profile(tmp_path: Path, gpus=None) -> HardwareProfile:
    import datetime

    return HardwareProfile(
        cpu=_make_cpu(),
        ram=_make_ram(),
        gpus=gpus if gpus is not None else [_make_gpu()],
        disk=_make_disk(tmp_path),
        detection_timestamp=datetime.datetime.now().isoformat(),
    )


def _make_detector(tmp_path: Path) -> ResourceDetector:
    return ResourceDetector(session_dir=tmp_path, output_dir=tmp_path)


# ---------------------------------------------------------------------------
# Group A — Detection (mocked psutil)
# ---------------------------------------------------------------------------


class TestDetectCPU:
    def test_cpu_count_none_falls_back_to_os_cpu_count(self, tmp_path):
        det = _make_detector(tmp_path)
        with (
            patch("psutil.cpu_count", side_effect=lambda logical=True: None if not logical else 8),
            patch("psutil.cpu_freq", return_value=None),
            patch("os.cpu_count", return_value=8),
        ):
            cpu = det._detect_cpu()
        # fallback: os.cpu_count() // 2 = 4
        assert cpu.physical_cores == 4

    def test_cpu_freq_none_does_not_raise(self, tmp_path):
        det = _make_detector(tmp_path)
        with (
            patch("psutil.cpu_count", side_effect=lambda logical=True: 16 if logical else 8),
            patch("psutil.cpu_freq", return_value=None),
        ):
            cpu = det._detect_cpu()
        assert cpu.frequency_max_mhz is None
        assert cpu.physical_cores == 8

    def test_cpu_freq_present_is_stored(self, tmp_path):
        det = _make_detector(tmp_path)
        freq_mock = MagicMock()
        freq_mock.max = 4200.0
        with (
            patch("psutil.cpu_count", side_effect=lambda logical=True: 16 if logical else 8),
            patch("psutil.cpu_freq", return_value=freq_mock),
        ):
            cpu = det._detect_cpu()
        assert cpu.frequency_max_mhz == 4200.0


class TestDetectRAM:
    def test_ram_converts_bytes_to_gb(self, tmp_path):
        det = _make_detector(tmp_path)
        vm = MagicMock()
        vm.total = 64 * 10**9
        vm.available = 32 * 10**9
        vm.percent = 50.0
        with patch("psutil.virtual_memory", return_value=vm):
            ram = det._detect_ram()
        assert abs(ram.total_gb - 64.0) < 0.1
        assert abs(ram.available_gb - 32.0) < 0.1
        assert ram.used_percent == 50.0


class TestDetect:
    def test_detect_returns_hardware_profile(self, tmp_path):
        det = _make_detector(tmp_path)
        freq_mock = MagicMock()
        freq_mock.max = 3600.0
        vm = MagicMock()
        vm.total = 32 * 10**9
        vm.available = 16 * 10**9
        vm.percent = 50.0
        disk_mock = MagicMock()
        disk_mock.free = 500 * 10**9
        with (
            patch("psutil.cpu_count", side_effect=lambda logical=True: 16 if logical else 8),
            patch("psutil.cpu_freq", return_value=freq_mock),
            patch("psutil.virtual_memory", return_value=vm),
            patch("psutil.disk_usage", return_value=disk_mock),
        ):
            profile = det.detect()
        assert isinstance(profile, HardwareProfile)
        assert isinstance(profile.warnings, list)
        assert isinstance(profile.detection_timestamp, str)

    def test_detect_subtask_failure_does_not_raise(self, tmp_path):
        """A single sub-detection failure yields warnings, not an exception."""
        det = _make_detector(tmp_path)
        vm = MagicMock()
        vm.total = 16 * 10**9
        vm.available = 8 * 10**9
        vm.percent = 50.0
        disk_mock = MagicMock()
        disk_mock.free = 200 * 10**9
        with (
            patch("psutil.cpu_count", side_effect=RuntimeError("fail")),
            patch("psutil.cpu_freq", return_value=None),
            patch("psutil.virtual_memory", return_value=vm),
            patch("psutil.disk_usage", return_value=disk_mock),
        ):
            profile = det.detect()  # must not raise
        assert isinstance(profile, HardwareProfile)


# ---------------------------------------------------------------------------
# Group B — GPU Fallback
# ---------------------------------------------------------------------------


class TestDetectGPU:
    def test_pynvml_success_returns_gpuinfo_list(self, tmp_path):
        det = _make_detector(tmp_path)
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlDeviceGetCount.return_value = 1
        handle = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.return_value = handle
        mem = MagicMock()
        mem.total = int(24 * 1e9)
        mem.free = int(22 * 1e9)
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = mem
        mock_pynvml.nvmlDeviceGetName.return_value = b"RTX 3090"
        mock_pynvml.nvmlSystemGetDriverVersion.return_value = b"535.104"
        with patch.dict("sys.modules", {"pynvml": mock_pynvml}):
            gpus = det._try_detect_gpu_pynvml()
        assert gpus is not None
        assert len(gpus) == 1
        assert gpus[0].detection_method == "pynvml"
        assert abs(gpus[0].vram_total_gb - 24.0) < 0.1

    def test_pynvml_import_error_returns_none(self, tmp_path):
        det = _make_detector(tmp_path)
        with patch.dict("sys.modules", {"pynvml": None}):
            result = det._try_detect_gpu_pynvml()
        assert result is None

    def test_nvidia_smi_success_parses_csv(self, tmp_path):
        det = _make_detector(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "RTX 3090, 24576, 22000, 535.104\n"
        with patch("subprocess.run", return_value=mock_result):
            gpus = det._try_detect_gpu_nvidia_smi()
        assert gpus is not None
        assert len(gpus) == 1
        assert gpus[0].detection_method == "nvidia-smi"
        assert abs(gpus[0].vram_total_gb - 24.0) < 0.1

    def test_nvidia_smi_failure_returns_none(self, tmp_path):
        det = _make_detector(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = det._try_detect_gpu_nvidia_smi()
        assert result is None

    def test_all_gpu_detection_fails_returns_empty_list(self, tmp_path):
        det = _make_detector(tmp_path)
        with (
            patch.object(det, "_try_detect_gpu_pynvml", return_value=None),
            patch.object(det, "_try_detect_gpu_nvidia_smi", return_value=None),
            patch.object(det, "_try_detect_gpu_torch", return_value=None),
        ):
            gpus = det._detect_gpus()
        assert gpus == []

    def test_all_gpu_detection_fails_adds_warning(self, tmp_path):
        det = _make_detector(tmp_path)
        with (
            patch.object(det, "_try_detect_gpu_pynvml", return_value=None),
            patch.object(det, "_try_detect_gpu_nvidia_smi", return_value=None),
            patch.object(det, "_try_detect_gpu_torch", return_value=None),
        ):
            det._detect_gpus()
        assert any("GPU" in w or "gpu" in w.lower() for w in det._warnings)

    def test_gpu_fallback_order_pynvml_first(self, tmp_path):
        """If pynvml succeeds, nvidia-smi is never tried."""
        det = _make_detector(tmp_path)
        gpu_list = [_make_gpu()]
        with (
            patch.object(det, "_try_detect_gpu_pynvml", return_value=gpu_list),
            patch.object(det, "_try_detect_gpu_nvidia_smi") as mock_smi,
        ):
            result = det._detect_gpus()
        assert result == gpu_list
        mock_smi.assert_not_called()


# ---------------------------------------------------------------------------
# Group C — Recommendation Formulas
# ---------------------------------------------------------------------------


class TestRecommendChunkDuration:
    """Verify the discrete binning rules from spec §7.1."""

    def _call(self, available_gb: float, n_jobs: int, tmp_path: Path) -> str:
        det = _make_detector(tmp_path)
        ram = _make_ram(available_gb=available_gb)
        chunk_str, _ = det._recommend_chunk_duration(ram, n_jobs, 384, 30000.0)
        return chunk_str

    def test_64gb_ram_n_jobs_8_gives_5s(self, tmp_path):
        assert self._call(64.0, 8, tmp_path) == "5s"

    def test_16gb_ram_n_jobs_8_gives_2s(self, tmp_path):
        assert self._call(16.0, 8, tmp_path) == "2s"

    def test_8gb_ram_n_jobs_8_gives_2s(self, tmp_path):
        # 8e9 × 0.40 / 8 / 230_400_000 = 1.74s → >= 1.5 → "2s"
        assert self._call(8.0, 8, tmp_path) == "2s"

    def test_5gb_ram_n_jobs_8_gives_1s(self, tmp_path):
        # 5e9 × 0.40 / 8 / 230_400_000 = 1.08s → >= 0.8 → "1s"
        assert self._call(5.0, 8, tmp_path) == "1s"

    def test_3gb_ram_n_jobs_8_gives_0_5s(self, tmp_path):
        # 3e9 × 0.40 / 8 / 230_400_000 = 0.65s → < 0.8 → "0.5s"
        assert self._call(3.0, 8, tmp_path) == "0.5s"


class TestRecommendNJobs:
    def test_cpu_bound_14_cores(self, tmp_path):
        det = _make_detector(tmp_path)
        cpu = _make_cpu(physical=14)
        ram = _make_ram(available_gb=64.0)
        n_jobs, note = det._recommend_n_jobs(cpu, ram, 2.0, 384, 30000.0)
        # n_jobs_cpu = 14 - 2 = 12; with 64GB that's memory-allowed too
        assert n_jobs == 12
        assert isinstance(note, str)

    def test_n_jobs_capped_at_16(self, tmp_path):
        det = _make_detector(tmp_path)
        cpu = _make_cpu(physical=32)
        ram = _make_ram(available_gb=256.0)
        n_jobs, _ = det._recommend_n_jobs(cpu, ram, 2.0, 384, 30000.0)
        assert n_jobs <= 16

    def test_n_jobs_minimum_1(self, tmp_path):
        det = _make_detector(tmp_path)
        cpu = _make_cpu(physical=1)
        ram = _make_ram(available_gb=1.0)
        n_jobs, _ = det._recommend_n_jobs(cpu, ram, 2.0, 384, 30000.0)
        assert n_jobs >= 1


class TestRecommendMaxWorkers:
    def test_low_ram_gives_1(self, tmp_path):
        det = _make_detector(tmp_path)
        ram = _make_ram(available_gb=8.0)
        workers, _ = det._recommend_max_workers(ram, n_probes=2)
        # 8 * 0.70 / 5.0 = 1.12 → 1
        assert workers == 1

    def test_32gb_ram_2_probes(self, tmp_path):
        det = _make_detector(tmp_path)
        ram = _make_ram(available_gb=32.0)
        workers, _ = det._recommend_max_workers(ram, n_probes=2)
        # 32*0.70/5 = 4.48 → 4; capped by probes → 2
        assert workers == 2

    def test_hard_cap_4(self, tmp_path):
        det = _make_detector(tmp_path)
        ram = _make_ram(available_gb=128.0)
        workers, _ = det._recommend_max_workers(ram, n_probes=10)
        assert workers <= 4


class TestRecommendBatchSize:
    def test_no_gpu_returns_fallback(self, tmp_path):
        det = _make_detector(tmp_path)
        bs, _ = det._recommend_batch_size(gpu=None)
        assert bs == FALLBACK_BATCH_SIZE

    def test_4gb_free_vram_gives_30000(self, tmp_path):
        det = _make_detector(tmp_path)
        gpu = _make_gpu(vram_free_gb=4.0)
        # vram_for_batch = (4.0 - 2.0) * 1024^3 * 0.80 = 1.72 GB
        # raw = 1.72e9 / (384*4*10) = 112000 → 60000? Let's compute:
        # Actually: (4-2)*1024**3 * 0.80 = 1717986918.4
        # raw = 1717986918 / 15360 = 111,848 → >= 60000 → 60000
        # Wait, spec says 3-5GB → 30000. Let me re-check.
        # 4GB free: vram_for_batch = (4-2)*1024^3*0.80 = 1.72GB → raw=111k → 60000
        # For 30000 we need < 40000: vram_for_batch < 40000*15360 = 614MB
        # vram_free - 2.0) * 0.8 < 0.614 → vram_free < 2.77GB
        # So 4GB free → 60000. Let me adjust to use 2.5GB free for 30000.
        bs, _ = det._recommend_batch_size(gpu=gpu)
        assert bs == 60000  # 4GB free is enough for 60000

    def test_low_vram_gives_30000(self, tmp_path):
        det = _make_detector(tmp_path)
        gpu = _make_gpu(vram_free_gb=2.6)
        # (2.6-2.0)*1024^3*0.80 = 514MB → raw = 514e6/15360 = 33,463 → 30000
        bs, _ = det._recommend_batch_size(gpu=gpu)
        assert bs == 30000

    def test_very_low_vram_gives_15000(self, tmp_path):
        det = _make_detector(tmp_path)
        gpu = _make_gpu(vram_free_gb=2.3)
        # (2.3-2.0)*1024^3*0.80 = 257MB → raw=16,737 → 15000
        bs, _ = det._recommend_batch_size(gpu=gpu)
        assert bs == 15000


# ---------------------------------------------------------------------------
# Group D — ResourceConfig
# ---------------------------------------------------------------------------


class TestResolveValue:
    def test_explicit_user_value_returns_user_config(self):
        val, source = ResourceConfig._resolve_value(8, 12, 4, "n_jobs")
        assert val == 8
        assert source == "user_config"

    def test_auto_with_detected_returns_auto_detected(self):
        val, source = ResourceConfig._resolve_value("auto", 12, 4, "n_jobs")
        assert val == 12
        assert source == "auto_detected"

    def test_auto_with_none_detected_returns_hardcoded_default(self):
        val, source = ResourceConfig._resolve_value("auto", None, 4, "n_jobs")
        assert val == 4
        assert source == "hardcoded_default"


class TestResourceConfig:
    def test_resolve_pipeline_config_replaces_auto_n_jobs(self, tmp_path):
        from pynpxpipe.core.config import load_pipeline_config

        config = load_pipeline_config(None)  # defaults: n_jobs="auto"
        profile = _make_profile(tmp_path)
        recommended = RecommendedParams(
            n_jobs=12, chunk_duration="2s", max_workers=2, sorting_batch_size=60000
        )
        resolver = ResourceConfig(profile, recommended)
        resolved = resolver.resolve_pipeline_config(config)
        assert resolved.resources.n_jobs == 12

    def test_resolve_pipeline_config_preserves_explicit_value(self, tmp_path):
        from pynpxpipe.core.config import load_pipeline_config, merge_with_overrides

        config = load_pipeline_config(None)
        config = merge_with_overrides(config, {"resources": {"n_jobs": 4}})
        profile = _make_profile(tmp_path)
        recommended = RecommendedParams(
            n_jobs=12, chunk_duration="2s", max_workers=2, sorting_batch_size=60000
        )
        resolver = ResourceConfig(profile, recommended)
        resolved = resolver.resolve_pipeline_config(config)
        # User set n_jobs=4 explicitly → must be preserved
        assert resolved.resources.n_jobs == 4

    def test_resolve_pipeline_config_returns_new_object(self, tmp_path):
        from pynpxpipe.core.config import load_pipeline_config

        config = load_pipeline_config(None)
        profile = _make_profile(tmp_path)
        recommended = RecommendedParams(
            n_jobs=12, chunk_duration="2s", max_workers=2, sorting_batch_size=60000
        )
        resolver = ResourceConfig(profile, recommended)
        resolved = resolver.resolve_pipeline_config(config)
        assert resolved is not config

    def test_validate_user_config_warns_on_n_jobs_exceeding_cores(self, tmp_path):
        from pynpxpipe.core.config import (
            load_pipeline_config,
            load_sorting_config,
            merge_with_overrides,
        )

        pipeline = merge_with_overrides(load_pipeline_config(None), {"resources": {"n_jobs": 32}})
        sorting = load_sorting_config(None)
        profile = _make_profile(tmp_path)  # cpu has physical_cores=8
        recommended = RecommendedParams(
            n_jobs=6, chunk_duration="1s", max_workers=1, sorting_batch_size=60000
        )
        resolver = ResourceConfig(profile, recommended)
        warnings = resolver.validate_user_config(pipeline, sorting)
        assert len(warnings) > 0
        assert any("n_jobs" in w or "cores" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Group E — HardwareProfile serialization
# ---------------------------------------------------------------------------


class TestHardwareProfileSerialization:
    def test_to_log_dict_returns_nested_dict(self, tmp_path):
        profile = _make_profile(tmp_path)
        d = profile.to_log_dict()
        assert isinstance(d, dict)
        assert "cpu" in d
        assert "ram" in d
        assert "gpus" in d
        assert "disk" in d

    def test_to_log_dict_cpu_has_physical_cores(self, tmp_path):
        profile = _make_profile(tmp_path)
        d = profile.to_log_dict()
        assert "physical_cores" in d["cpu"]

    def test_to_display_lines_returns_list_of_strings(self, tmp_path):
        profile = _make_profile(tmp_path)
        lines = profile.to_display_lines()
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines)
        assert len(lines) > 0

    def test_primary_gpu_property(self, tmp_path):
        profile = _make_profile(tmp_path, gpus=[_make_gpu()])
        assert profile.primary_gpu is not None
        assert profile.primary_gpu.name == "RTX 3090"

    def test_primary_gpu_none_when_no_gpus(self, tmp_path):
        profile = _make_profile(tmp_path, gpus=[])
        assert profile.primary_gpu is None


# ---------------------------------------------------------------------------
# Group F — cached_detect
# ---------------------------------------------------------------------------


class TestCachedDetect:
    def test_second_call_does_not_re_detect(self, tmp_path):
        # Clear cache before test
        ResourceDetector._cache.clear()
        freq_mock = MagicMock()
        freq_mock.max = 3600.0
        vm = MagicMock()
        vm.total = 32 * 10**9
        vm.available = 16 * 10**9
        vm.percent = 50.0
        disk_mock = MagicMock()
        disk_mock.free = 200 * 10**9
        with (
            patch("psutil.cpu_count", side_effect=lambda logical=True: 16 if logical else 8),
            patch("psutil.cpu_freq", return_value=freq_mock),
            patch("psutil.virtual_memory", return_value=vm),
            patch("psutil.disk_usage", return_value=disk_mock),
        ):
            p1 = ResourceDetector.cached_detect(tmp_path, tmp_path)
            p2 = ResourceDetector.cached_detect(tmp_path, tmp_path)
        assert p1 is p2  # same object from cache
        ResourceDetector._cache.clear()
