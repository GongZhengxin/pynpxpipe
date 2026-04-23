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

    # ── NWB filename regularization (SID S3) ──
    experiment = param.String(default="", doc="Experiment name (user input, e.g. 'nsd1w')")
    recording_date = param.String(
        default="",
        doc="Recording date in YYMMDD. Populated by Detect Date or entered manually.",
    )
    probe_plan = param.Dict(
        default={"imec0": ""},
        doc="probe_id -> target_area declared by the user, managed by ProbeRegionEditor.",
    )

    # ── Runtime status ──
    run_status = param.Selector(
        default="idle",
        objects=["idle", "running", "completed", "failed"],
    )
    selected_stages = param.List(default=[], doc="Stage names to run")
    error_message = param.String(default="")
    safe_to_exit = param.Boolean(
        default=False,
        doc=(
            "True when the pipeline (including Phase 3 raw-data export + "
            "bit-exact verify) has completed successfully and the user can "
            "close the window without corrupting the NWB. Flipped to True "
            "by run_panel on successful PipelineRunner.run() return; reset "
            "to False before each new run."
        ),
    )

    # ── Progress (written by ProgressBridge) ──
    current_stage = param.String(default="")
    stage_progress = param.Number(default=0.0, bounds=(0.0, 1.0))
    stage_statuses = param.Dict(default={})  # {stage_name: "pending"|"running"|"completed"|...}

    @property
    def session_id(self):
        """Return a SessionID when all filename fields are populated, else None.

        Complete means: recording_date is 6 chars, subject_config.subject_id is
        non-empty, experiment is non-empty, and every target_area in probe_plan
        is a non-empty string.
        """
        from pynpxpipe.core.session import SessionID

        if not self.recording_date or len(self.recording_date) != 6:
            return None
        if self.subject_config is None or not getattr(self.subject_config, "subject_id", ""):
            return None
        if not self.experiment:
            return None
        if not self.probe_plan or any(not v for v in self.probe_plan.values()):
            return None
        return SessionID(
            date=self.recording_date,
            subject=self.subject_config.subject_id,
            experiment=self.experiment,
            region=SessionID.derive_region(dict(self.probe_plan)),
        )


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
        # message format: "stage_name:Human readable text"
        if ":" in message:
            stage_name, display_msg = message.split(":", 1)
        else:
            stage_name = message
            display_msg = message

        self._state.current_stage = stage_name
        self._state.stage_progress = fraction

        # Maintain stage_statuses dict
        statuses = dict(self._state.stage_statuses)
        if fraction >= 1.0:
            statuses[stage_name] = "completed"
        else:
            statuses[stage_name] = "running"
        self._state.stage_statuses = statuses
