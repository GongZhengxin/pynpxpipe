"""Tests for pynpxpipe.core.torch_env.resolve_device — the CUDA guard matrix."""

from __future__ import annotations

import pytest

from pynpxpipe.core.torch_env import TorchEnvError, resolve_device


class TestResolveDeviceCPU:
    def test_cpu_always_returns_cpu_no_gpu(self):
        assert resolve_device("cpu", has_physical_gpu=False, cuda_available=False) == "cpu"

    def test_cpu_always_returns_cpu_with_gpu(self):
        """Even if a GPU is present, explicit 'cpu' wins."""
        assert resolve_device("cpu", has_physical_gpu=True, cuda_available=True) == "cpu"


class TestResolveDeviceAuto:
    def test_auto_no_gpu_returns_cpu(self):
        assert resolve_device("auto", has_physical_gpu=False, cuda_available=False) == "cpu"

    def test_auto_gpu_and_cuda_returns_cuda(self):
        assert resolve_device("auto", has_physical_gpu=True, cuda_available=True) == "cuda"

    def test_auto_gpu_but_cpu_torch_warns_and_falls_back(self):
        """The canonical 'torch is CPU build, GPU is present' scenario.

        With 'auto' this is a soft failure: warn + cpu. Only 'cuda' raises.
        """
        with pytest.warns(UserWarning, match="CPU-only build"):
            result = resolve_device("auto", has_physical_gpu=True, cuda_available=False)
        assert result == "cpu"


class TestResolveDeviceCuda:
    def test_cuda_gpu_and_cuda_returns_cuda(self):
        assert resolve_device("cuda", has_physical_gpu=True, cuda_available=True) == "cuda"

    def test_cuda_no_gpu_raises(self):
        """User asked for cuda on a machine with no GPU — misconfiguration."""
        with pytest.raises(TorchEnvError, match="no NVIDIA GPU"):
            resolve_device("cuda", has_physical_gpu=False, cuda_available=False)

    def test_cuda_gpu_but_cpu_torch_raises(self):
        """The exact silent-failure mode the redesign fixes."""
        with pytest.raises(TorchEnvError, match="CPU-only build"):
            resolve_device("cuda", has_physical_gpu=True, cuda_available=False)

    def test_cuda_error_message_includes_remediation(self):
        """Error must tell the user how to fix it in one line."""
        with pytest.raises(TorchEnvError) as exc_info:
            resolve_device("cuda", has_physical_gpu=True, cuda_available=False)
        assert "install_sort_stack.py" in str(exc_info.value)


class TestResolveDeviceInvalid:
    def test_bad_requested_value_raises_valueerror(self):
        with pytest.raises(ValueError, match="Invalid torch_device"):
            resolve_device("gpu", has_physical_gpu=True, cuda_available=True)

    def test_empty_string_raises_valueerror(self):
        with pytest.raises(ValueError):
            resolve_device("", has_physical_gpu=False, cuda_available=False)


class TestIsCudaTorchAvailable:
    """is_cuda_torch_available should not crash even if torch is absent."""

    def test_returns_bool(self):
        from pynpxpipe.core.torch_env import is_cuda_torch_available

        assert isinstance(is_cuda_torch_available(), bool)
