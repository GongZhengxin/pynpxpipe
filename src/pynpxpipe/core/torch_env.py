"""torch_env.py — Runtime CUDA/torch consistency check.

pynpxpipe deliberately does NOT declare ``torch`` or ``kilosort`` in
``pyproject.toml``. They are installed by ``tools/install_sort_stack.py``
once and then left alone by ``uv sync``. See that script for the why.

This module provides the stage-side runtime check: given the user's
configured ``torch_device`` and the detected GPU state, decide what to do.

Behavior matrix:

    torch_device | physical GPU | torch.cuda.is_available() | action
    ------------ | ------------ | ------------------------- | ---------------------------
    cpu          | any          | any                       | → "cpu"
    auto         | no           | any                       | → "cpu"
    auto         | yes          | True                      | → "cuda"
    auto         | yes          | False                     | WARN + → "cpu"   (torch is CPU build)
    cuda         | no           | any                       | raise (misconfiguration)
    cuda         | yes          | True                      | → "cuda"
    cuda         | yes          | False                     | raise (torch is CPU build)

The "warn and fall back" branch only fires for ``auto``. When the user
explicitly asks for ``cuda`` and torch is a CPU build, we raise — this is
exactly the silent-failure mode that motivated the redesign.
"""

from __future__ import annotations

import importlib
import warnings

__all__ = [
    "TorchEnvError",
    "resolve_device",
    "is_cuda_torch_available",
]


class TorchEnvError(RuntimeError):
    """Raised when the requested torch device is incompatible with the env."""


_REMEDIATION = (
    "Install a CUDA build of torch with: "
    "`uv run python tools/install_sort_stack.py` "
    "(see getting_started.md § GPU setup for details)."
)


def is_cuda_torch_available() -> bool:
    """Return True iff torch is importable AND ``torch.cuda.is_available()``.

    Imported lazily so that this module can be imported on machines without
    torch installed (e.g. CI running non-sort tests).
    """
    try:
        torch = importlib.import_module("torch")
    except ImportError:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001 — any torch startup failure counts as "no cuda"
        return False


def resolve_device(
    requested: str,
    has_physical_gpu: bool,
    *,
    cuda_available: bool | None = None,
) -> str:
    """Resolve the configured ``torch_device`` to an actual device string.

    Args:
        requested: Value of ``config.sorting.sorter.params.torch_device``.
            Must be one of ``{"auto", "cuda", "cpu"}``.
        has_physical_gpu: Whether nvidia-smi / pynvml detected a physical GPU.
            Typically ``ResourceDetector.detect().primary_gpu is not None``.
        cuda_available: If provided, used instead of calling
            ``torch.cuda.is_available()``. Exposed for tests; production calls
            leave it as None.

    Returns:
        ``"cuda"`` or ``"cpu"``.

    Raises:
        TorchEnvError: If ``requested == "cuda"`` but either the machine has
            no GPU or torch is a CPU build. The message always includes the
            remediation command so the user can fix it in one copy-paste.
        ValueError: If ``requested`` is not one of the three legal values.
    """
    if requested not in {"auto", "cuda", "cpu"}:
        raise ValueError(f"Invalid torch_device={requested!r}; expected 'auto', 'cuda', or 'cpu'")

    if requested == "cpu":
        return "cpu"

    if cuda_available is None:
        cuda_available = is_cuda_torch_available()

    if requested == "cuda":
        if not has_physical_gpu:
            raise TorchEnvError(
                "torch_device='cuda' was requested but no NVIDIA GPU was detected. "
                "Set torch_device='cpu' (or 'auto') in sorting.yaml, or run on a "
                "machine with a CUDA GPU."
            )
        if not cuda_available:
            raise TorchEnvError(
                "torch_device='cuda' was requested and a GPU is present, but the "
                "installed torch is a CPU-only build. " + _REMEDIATION
            )
        return "cuda"

    # requested == "auto"
    if not has_physical_gpu:
        return "cpu"
    if not cuda_available:
        warnings.warn(
            "torch_device='auto' and a GPU is present, but torch is a CPU-only "
            "build; falling back to cpu. " + _REMEDIATION,
            UserWarning,
            stacklevel=2,
        )
        return "cpu"
    return "cuda"
