"""Pipeline constants shared by runner and UI layers.

This module intentionally imports NOTHING from stages/ or heavy libraries
(spikeinterface, pynwb, etc.) so that the UI can import STAGE_ORDER
without triggering the full scientific-stack import chain.
"""

from __future__ import annotations

STAGE_ORDER: list[str] = [
    "discover",
    "preprocess",
    "sort",
    "merge",
    "synchronize",
    "curate",
    "postprocess",
    "export",
]

# Stages that produce per-probe checkpoints
PER_PROBE_STAGES: frozenset[str] = frozenset(
    {"preprocess", "sort", "merge", "curate", "postprocess"}
)
