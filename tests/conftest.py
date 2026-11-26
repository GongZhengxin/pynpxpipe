"""Shared pytest fixtures for pynpxpipe tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# MATLAB runtime path (required by matlab.engine on Windows)
# ---------------------------------------------------------------------------
MATLAB_RUNTIME = Path("C:/Program Files/MATLAB/R2024b/runtime/win64")

if MATLAB_RUNTIME.exists():
    os.environ["PATH"] = str(MATLAB_RUNTIME) + os.pathsep + os.environ.get("PATH", "")


# ---------------------------------------------------------------------------
# BHV2 test data
# ---------------------------------------------------------------------------
BHV2_FILE = Path(r"F:\#Datasets\demo_rawdata\241026_MaoDan_YJ_WordLOC.bhv2")

MLBHV2_DIR = Path(__file__).parent.parent / "legacy_reference" / "pyneuralpipe" / "Util"


def pytest_configure(config):
    config.addinivalue_line("markers", "matlab: tests that require a real MATLAB engine")
    config.addinivalue_line(
        "markers",
        "integration: tests that require real data files on disk",
    )


@pytest.fixture(scope="session")
def bhv2_file() -> Path:
    """Path to the real BHV2 test file."""
    if not BHV2_FILE.exists():
        pytest.skip(f"BHV2 test file not found: {BHV2_FILE}")
    return BHV2_FILE


@pytest.fixture(scope="session")
def matlab_engine():
    """Session-scoped real MATLAB engine. Starts once, reused across all tests."""
    if not MATLAB_RUNTIME.exists():
        pytest.skip(f"MATLAB runtime not found: {MATLAB_RUNTIME}")
    try:
        import matlab.engine

        eng = matlab.engine.start_matlab()
        eng.addpath(str(MLBHV2_DIR), nargout=0)
        yield eng
        eng.quit()
    except Exception as e:
        pytest.skip(f"Could not start MATLAB engine: {e}")


# ---------------------------------------------------------------------------
# Web UI: keep the developer's recent-sessions list out of tests
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_recent_sessions(tmp_path_factory, monkeypatch):
    """Point the UI's recent-sessions store (ui_redesign §8.3) at a temp file."""
    store = tmp_path_factory.mktemp("recent") / "recent_sessions.json"
    monkeypatch.setenv("PYNPXPIPE_RECENT_SESSIONS", str(store))
