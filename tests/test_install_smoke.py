"""Dependency drift smoke tests — NOT mocked.

Most pipeline tests mock out `spikeinterface.sorters.run_sorter` and
`spikeinterface.preprocessing.correct_motion`, which means the test suite
passes green even when torch / kilosort are NOT actually installed. That
gap allowed a real production-bug to ship: after `uv sync` normalised the
venv to match `pyproject.toml`, the previously-dirty dev env lost torch
and kilosort, and the preprocess stage started failing at runtime with::

    Motion estimation failed. The dredge method require torch: pip install torch

These tests are the forcing function that protects against that drift.

**Current contract** (post GPU redesign, 2026-04): ``torch`` and ``kilosort``
are deliberately NOT listed in ``pyproject.toml`` — they are installed
out-of-band by ``tools/install_sort_stack.py`` so that ``uv sync`` cannot
revert a CUDA build to the pypi CPU wheel. That means these real-import
tests fail when a fresh clone has not yet run the installer. Fix it with::

    uv run python tools/install_sort_stack.py

    # From then on, use --inexact to preserve the sort stack:
    uv sync --inexact --extra ui --extra gpu --extra plots

If you actually want to run only discover/export (no sort, no motion
correction), deselect this file with::

    uv run pytest --deselect tests/test_install_smoke.py
"""

from __future__ import annotations

from pathlib import Path


def test_torch_is_importable() -> None:
    import torch

    assert torch.__version__, "torch must expose __version__"


def test_kilosort_is_importable() -> None:
    import kilosort

    assert kilosort.__version__, "kilosort must expose __version__"


def test_spikeinterface_motion_module_loads() -> None:
    from spikeinterface.sortingcomponents import motion

    assert hasattr(motion, "__name__")


def test_installer_script_exists() -> None:
    """Fresh clones must have the installer so users can bootstrap torch."""
    repo_root = Path(__file__).parent.parent
    assert (repo_root / "tools" / "install_sort_stack.py").exists(), (
        "tools/install_sort_stack.py missing — users cannot install torch/kilosort"
    )
    assert (repo_root / "tools" / "cuda_matrix.yaml").exists(), (
        "tools/cuda_matrix.yaml missing — installer cannot pick a wheel"
    )


def test_cuda_matrix_lists_kilosort() -> None:
    """The installer's companion_packages list must include kilosort.

    This replaces the old ``[sort]`` extra declaration check. kilosort is
    no longer in pyproject.toml; it's installed by ``install_sort_stack.py``
    reading from ``cuda_matrix.yaml``.
    """
    import yaml

    matrix_path = Path(__file__).parent.parent / "tools" / "cuda_matrix.yaml"
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    companions = matrix.get("companion_packages", [])
    names = " ".join(pkg["name"] for pkg in companions)
    assert "kilosort" in names, (
        "cuda_matrix.yaml companion_packages must list kilosort — without it the "
        "installer would ship torch without the sorter"
    )


def test_torch_and_kilosort_not_in_pyproject() -> None:
    """Structural invariant: neither torch nor kilosort may appear in pyproject.toml.

    If they do, ``uv sync`` will revert the user's CUDA build of torch back
    to the pypi CPU wheel, defeating the entire out-of-band install design.
    """
    import tomllib

    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))

    core_deps = " ".join(data["project"].get("dependencies", []))
    assert "torch" not in core_deps, (
        "torch must NOT be in [project.dependencies]; it belongs in "
        "tools/install_sort_stack.py so uv sync won't revert CUDA builds"
    )
    assert "kilosort" not in core_deps, "kilosort must NOT be in [project.dependencies]"

    extras = data["project"].get("optional-dependencies", {})
    for extra_name, extra_deps in extras.items():
        joined = " ".join(extra_deps)
        assert "torch" not in joined, f"torch leaked into [{extra_name}] extra"
        assert "kilosort" not in joined, f"kilosort leaked into [{extra_name}] extra"
