"""Pipeline orchestration: stage sequencing, checkpoint-aware runner."""

from pynpxpipe.pipelines.constants import STAGE_ORDER

__all__ = ["STAGE_ORDER"]


def get_runner():
    """Lazy import of PipelineRunner to avoid heavy dependency chain at import time."""
    from pynpxpipe.pipelines.runner import PipelineRunner

    return PipelineRunner
