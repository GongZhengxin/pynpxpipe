"""ui/state.py — Global application state and progress bridge.

AppState: param.Parameterized holding all UI-shared reactive state.
ProgressBridge: thread-safe bridge from PipelineRunner.progress_callback to AppState.
"""

from __future__ import annotations

import param


class AppState(param.Parameterized):
    """Global application state shared by all UI components."""

    # ── Input paths ──
    session_dir = param.Path(
        default=None, check_exists=False, doc="SpikeGLX recording root directory"
    )
    bhv_file = param.Path(default=None, check_exists=False, doc="MonkeyLogic BHV2 file")
    output_dir = param.Path(default=None, check_exists=False, doc="Pipeline output root directory")
    subject_yaml = param.Path(
        default=None, check_exists=False, doc="Subject YAML file (optional pre-fill)"
    )

    # ── Config objects (populated by forms) ──
    pipeline_config = param.Parameter(default=None, doc="PipelineConfig dataclass instance")
    sorting_config = param.Parameter(default=None, doc="SortingConfig dataclass instance")
    subject_config = param.Parameter(default=None, doc="SubjectConfig dataclass instance")

    # ── Runtime status ──
    run_status = param.Selector(
        default="idle",
        objects=["idle", "running", "completed", "failed"],
    )
    selected_stages = param.List(default=[], doc="Stage names to run")
    error_message = param.String(default="")

    # ── Progress (written by ProgressBridge) ──
    current_stage = param.String(default="")
    stage_progress = param.Number(default=0.0, bounds=(0.0, 1.0))
    stage_statuses = param.Dict(default={})  # {stage_name: "pending"|"running"|"completed"|...}


class ProgressBridge:
    """Thread-safe bridge from PipelineRunner.progress_callback to AppState param attributes."""

    def __init__(self, state: AppState) -> None:
        self._state = state

    def callback(self, message: str, fraction: float) -> None:
        """Pass to PipelineRunner as progress_callback.

        Called from a background thread; schedules the update on the UI thread
        via pn.state.execute so param watches fire correctly.
        """
        import panel as pn

        pn.state.execute(lambda: self._update(message, fraction))

    def _update(self, message: str, fraction: float) -> None:
        self._state.current_stage = message
        self._state.stage_progress = fraction
