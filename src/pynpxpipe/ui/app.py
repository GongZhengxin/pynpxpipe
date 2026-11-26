"""ui/app.py — Entry point for the pynpxpipe Panel Web UI.

A5 production layout: FastListTemplate with sidebar navigation,
three content sections (Configure, Execute, Review), and error banner.

Usage:
    pynpxpipe-ui
    panel serve src/pynpxpipe/ui/app.py --show
"""

from __future__ import annotations

import contextlib
import io
import logging
import sys
import threading
from pathlib import Path

import panel as pn

from pynpxpipe.ui.components.chat_help import ChatHelp
from pynpxpipe.ui.components.error_view import ErrorView
from pynpxpipe.ui.components.figs_viewer import FigsViewer
from pynpxpipe.ui.components.log_viewer import LogViewer
from pynpxpipe.ui.components.pipeline_form import PipelineForm
from pynpxpipe.ui.components.preset_bar import PresetBar
from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor
from pynpxpipe.ui.components.progress_view import ProgressView
from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives
from pynpxpipe.ui.components.resume_export import ResumeExportPanel
from pynpxpipe.ui.components.run_panel import RunPanel
from pynpxpipe.ui.components.session_form import SessionForm
from pynpxpipe.ui.components.session_list import SessionList
from pynpxpipe.ui.components.session_loader import SessionLoader
from pynpxpipe.ui.components.sorting_form import SortingForm
from pynpxpipe.ui.components.stage_selector import StageSelector
from pynpxpipe.ui.components.status_view import StatusView
from pynpxpipe.ui.components.subject_form import SubjectForm
from pynpxpipe.ui.components.task_window_page import TaskWindowPage
from pynpxpipe.ui.components.top_bar import TopBar
from pynpxpipe.ui.components.wizard import ReviewStep, Wizard, WizardStep
from pynpxpipe.ui.components.workspace import Workspace
from pynpxpipe.ui.router import Router
from pynpxpipe.ui.run_manager import get_run_manager
from pynpxpipe.ui.settings import load_ui_settings
from pynpxpipe.ui.state import AppState, ProgressBridge


class _UILogHandler(logging.Handler):
    """Logging handler that feeds log records to a LogViewer widget.

    Schedules UI updates on the document that started the pipeline.
    """

    def __init__(self, log_viewer: LogViewer, bridge: ProgressBridge) -> None:
        super().__init__()
        self._log_viewer = log_viewer
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._bridge.dispatch(lambda: self._push(msg))
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def _push(self, msg: str) -> None:
        self._log_viewer.append(msg)
        self._log_viewer.refresh()


class _TeeStream(io.TextIOBase):
    """Wraps an output stream to also feed lines to LogViewer.

    Intercepts stdout/stderr writes so tqdm progress bars and print()
    output from SpikeInterface / Kilosort appear in the UI log panel.
    Only captures output from threads registered via activate().
    """

    def __init__(
        self, original: io.TextIOBase, log_viewer: LogViewer, bridge: ProgressBridge
    ) -> None:
        self._original = original
        self._log_viewer = log_viewer
        self._bridge = bridge
        self._active_threads: set[int] = set()
        self._lock = threading.Lock()

    def activate(self) -> None:
        """Register the current thread for capture."""
        with self._lock:
            self._active_threads.add(threading.get_ident())

    def deactivate(self) -> None:
        """Unregister the current thread from capture."""
        with self._lock:
            self._active_threads.discard(threading.get_ident())

    def write(self, s: str) -> int:
        result = self._original.write(s)
        with self._lock:
            active = threading.get_ident() in self._active_threads
        if active and s.strip("\r\n"):
            stripped = s.strip()
            is_overwrite = s.startswith("\r")
            with contextlib.suppress(Exception):
                self._bridge.dispatch(lambda: self._push(stripped, is_overwrite))
        return result

    def _push(self, text: str, overwrite: bool) -> None:
        if overwrite:
            self._log_viewer.replace_last(text)
        else:
            self._log_viewer.append(text)
        self._log_viewer.refresh()

    def flush(self) -> None:
        self._original.flush()

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    def fileno(self):
        return self._original.fileno()

    def isatty(self):
        return self._original.isatty()


pn.extension()


def create_app() -> pn.viewable.Viewable:
    """Create and return the Panel app layout.

    Returns a FastListTemplate with sidebar navigation and three content
    sections: Configure, Execute, Review.  The returned template exposes
    internal state via private attributes for testability:

    - ``_pynpx_sections``: dict of section name -> Column
    - ``_pynpx_switch(name)``: callable to switch visible section
    - ``_pynpx_error_banner``: the error alert pane
    - ``_pynpx_state``: the AppState instance
    """
    # The web UI writes diagnostic images from worker threads.
    with contextlib.suppress(ImportError):
        import matplotlib

        matplotlib.use("Agg")

    state = AppState()
    bridge = ProgressBridge(state)

    # ── Components ──
    session_form = SessionForm(state)
    subject_form = SubjectForm(state)
    probe_region_editor = ProbeRegionEditor(state)
    pipeline_form = PipelineForm(state)
    sorting_form = SortingForm(state)
    preset_bar = PresetBar(state, pipeline_form, sorting_form)
    stage_selector = StageSelector(state)

    log_viewer = LogViewer()
    ui_handler = _UILogHandler(log_viewer, bridge)
    ui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))

    # Install TeeStream wrappers for stdout/stderr capture (tqdm, print, etc.)
    tee_stdout = _TeeStream(sys.stdout, log_viewer, bridge)
    tee_stderr = _TeeStream(sys.stderr, log_viewer, bridge)
    sys.stdout = tee_stdout
    sys.stderr = tee_stderr

    def pipeline_fn(st: AppState, bridge: ProgressBridge, preview: bool = False) -> None:
        """Execute the pipeline from UI state. Runs in a background thread."""
        from pynpxpipe.core.logging import setup_logging
        from pynpxpipe.core.session import RecordingSource, SessionManager
        from pynpxpipe.pipelines.runner import PipelineRunner

        if st.input_mode == "joint" and len(st.active_recordings) < 2:
            raise ValueError("多段联合模式需要至少两组已保存的神经–行为配对")
        if not st.active_session_dir:
            raise ValueError("Session directory is required")
        if not st.output_dir:
            raise ValueError("Output directory is required")
        if st.subject_config is None:
            raise ValueError("Subject metadata is required (fill all required fields)")
        if st.pipeline_config is None:
            raise ValueError("Pipeline configuration is missing")
        if st.sorting_config is None:
            raise ValueError("Sorting configuration is missing")

        output_path = Path(str(st.output_dir))
        session_json = output_path / "session.json"

        if st.input_mode == "joint":
            session = SessionManager.create_from_recordings(
                [RecordingSource.from_dict(s) for s in st.active_recordings],
                st.subject_config,
                output_path,
                experiment=st.experiment,
                probe_plan=dict(st.probe_plan),
                date=st.recording_date,
            )
        elif session_json.exists():
            session = SessionManager.load(output_path)
            # Update subject in case the user changed it in the UI
            session.subject = st.subject_config
            session.session_dir = Path(str(st.session_dir))
            session.bhv_file = Path(str(st.bhv_file))
            session.recordings = []
            SessionManager.save(session)
        else:
            session = SessionManager.create(
                session_dir=Path(str(st.session_dir)),
                bhv_file=Path(str(st.bhv_file))
                if st.bhv_file
                else Path(str(st.session_dir)) / "dummy.bhv2",
                subject=st.subject_config,
                output_dir=output_path,
                experiment=st.experiment,
                probe_plan=dict(st.probe_plan),
                date=st.recording_date,
            )

        setup_logging(session.log_path)

        root_logger = logging.getLogger()
        root_logger.addHandler(ui_handler)
        tee_stdout.activate()
        tee_stderr.activate()
        try:
            runner = PipelineRunner(
                session,
                st.pipeline_config,
                st.sorting_config,
                progress_callback=bridge.callback,
            )
            stages = st.selected_stages if st.selected_stages else None
            if preview:
                stages = ["discover", "synchronize", "select_segments"]
            runner.run(stages=stages)
        finally:
            tee_stdout.deactivate()
            tee_stderr.deactivate()
            root_logger.removeHandler(ui_handler)

    run_panel = RunPanel(
        state,
        pipeline_fn=pipeline_fn,
        preview_fn=lambda st, br: pipeline_fn(st, br, True),
        bridge=bridge,
        tuning_controls=pipeline_form.task_preview_controls(),
    )
    progress_view = ProgressView(state)

    status_view = StatusView(state)
    figs_viewer = FigsViewer(state)
    chat_help = ChatHelp(state)

    def _on_session_loaded() -> None:
        # Mirror restored AppState into the form widgets so the user sees the
        # loaded values; otherwise widget watchers can clobber state with the
        # forms' empty/default inputs on next interaction.
        if state.subject_config is not None:
            subject_form.apply_subject(state.subject_config)
        if state.pipeline_config is not None:
            pipeline_form.apply_pipeline(state.pipeline_config)
        if state.sorting_config is not None:
            sorting_form.apply_sorting(state.sorting_config)
        session_form.apply_paths(
            state.session_dir,
            state.bhv_file,
            state.output_dir,
        )
        status_view.load_status()
        figs_viewer.load_figures()
        run_panel.load_saved_preview()
        if state.output_dir:
            session_list.remember_output(state.output_dir)
        workspace.refresh()

    # Not rendered: the session list and routed URLs load sessions through it.
    session_loader = SessionLoader(state, on_session_loaded=_on_session_loaded)
    rerun_derivatives = RerunDerivatives(state)

    # ── Sections ──
    # ── New-session wizard (ui_redesign P1-3) ──
    def _validate_data() -> str | None:
        if state.input_mode == "joint":
            if len(state.active_recordings) < 2:
                return "多段联合需要至少两组已保存的神经–行为配对。"
        elif not state.session_dir or not state.bhv_file:
            return "请先选择数据目录，并确认识别到 gate 目录和 BHV2 文件。"
        if not state.output_dir:
            return "请填写输出目录。"
        if not (state.experiment or "").strip():
            return "请填写实验名。"
        if not (state.recording_date or "").strip():
            return "请填写采集日期（YYMMDD）。"
        return None

    def _validate_subject() -> str | None:
        if state.subject_config is None:
            return "请选择动物档案，或点「+ 新动物」填写必填项。"
        if not state.probe_plan or any(not (a or "").strip() for a in state.probe_plan.values()):
            return "请为每根探针填写脑区。"
        return None

    session_form.probe_listeners.append(probe_region_editor.set_probes)

    def _prefill_areas(event) -> None:
        if event.new is not None:
            probe_region_editor.prefill_from_history(event.new.subject_id)

    state.param.watch(_prefill_areas, "subject_config")

    def _preflight_checks() -> list:
        from pynpxpipe.harness.preflight import PreflightChecker

        session_dir = Path(str(state.active_session_dir or "."))
        output_dir = Path(str(state.output_dir or "."))
        checker = PreflightChecker(session_dir, output_dir)
        pipe, sort = state.pipeline_config, state.sorting_config
        results = [checker.check_spikeinterface_version(), checker.check_disk_space()]
        if sort is not None:
            results.append(checker.check_cuda_vs_config(sort.sorter.params.torch_device))
        if pipe is not None and sort is not None:
            results.append(
                checker.check_motion_nblocks_exclusion(
                    pipe.preprocess.motion_correction.method is not None,
                    sort.sorter.params.nblocks,
                )
            )
        if pipe is not None:
            cur = pipe.curation
            results.append(
                checker.check_curation_threshold_ranges(
                    cur.isi_violation_ratio_max,
                    cur.amplitude_cutoff_max,
                    cur.presence_ratio_min,
                    cur.snr_min,
                )
            )
        if session_dir.is_dir():
            results.extend(checker.check_data_integrity())
        return results

    eta_cache: dict = {}

    def _stage_eta(stage: str) -> float | None:
        from pynpxpipe.pipelines.estimates import (
            collect_stage_rates,
            estimate_stage_seconds,
            meta_duration_s,
        )
        from pynpxpipe.ui.recent_sessions import default_recent_path, load_recent

        if "rates" not in eta_cache:
            dirs = [Path(e.output_dir) for e in load_recent(default_recent_path())]
            eta_cache["rates"] = collect_stage_rates(dirs)
            root = state.active_session_dir
            metas = sorted(Path(root).rglob("*.ap.meta")) if root and Path(root).is_dir() else []
            eta_cache["duration"] = meta_duration_s(metas[0]) if metas else None
        if not eta_cache["duration"]:
            return None
        return estimate_stage_seconds(
            eta_cache["rates"],
            stage,
            duration_s=eta_cache["duration"],
            n_probes=max(1, len(state.probe_plan or {})),
            min_samples=settings.eta_min_samples,
        )

    def _params_summary() -> str:
        select = preset_bar.preset_select
        label = next((k for k, v in select.options.items() if v == select.value), "")
        return f"{label}，改了 {len(preset_bar.diff)} 项"

    def _start_from_wizard(mode: str) -> None:
        run_panel.start(preview=mode == "align")
        router.go("session", output_dir=str(state.output_dir or ""))

    review_step = ReviewStep(
        state,
        checks_fn=_preflight_checks,
        eta_fn=_stage_eta,
        start_fn=_start_from_wizard,
        params_summary_fn=_params_summary,
    )

    def _enter_review() -> None:
        eta_cache.clear()
        review_step.refresh()

    wizard = Wizard(
        [
            WizardStep("数据", pn.Column(session_form.panel(), sizing_mode="stretch_width"),
                       _validate_data),
            WizardStep(
                "动物与探针",
                pn.Column(subject_form.wizard_panel(), probe_region_editor.panel(),
                          sizing_mode="stretch_width"),
                _validate_subject,
            ),
            WizardStep(
                "参数",
                pn.Column(preset_bar.panel(), pipeline_form.panel(), sorting_form.panel(),
                          sizing_mode="stretch_width"),
            ),
            WizardStep(
                "检查并运行",
                pn.Column(
                    review_step.panel(),
                    pn.Card(stage_selector.panel(), title="高级：选择要运行的阶段",
                            collapsed=True, sizing_mode="stretch_width"),
                    sizing_mode="stretch_width",
                ),
                on_enter=_enter_review,
            ),
        ],
        on_cancel=lambda: router.go("sessions"),
    )  # fmt: skip
    configure_section = wizard.panel()

    # Execute / review remain as the workspace's collapsed "advanced" sections (P1-5);
    # the session list replaces both SessionLoader panels (P1-2).
    execute_section = pn.Column(
        pn.pane.Markdown("### 常规运行与任务时段预览"),
        run_panel.panel(),
        progress_view.panel(),
        sizing_mode="stretch_width",
        visible=False,
    )

    review_section = pn.Column(
        status_view.panel(),
        sizing_mode="stretch_width",
        visible=False,
    )
    export_actions = pn.Column(
        ResumeExportPanel(state, bridge).panel(),
        rerun_derivatives.panel(),
        sizing_mode="stretch_width",
    )

    help_section = pn.Column(
        chat_help.panel(),
        sizing_mode="stretch_width",
        visible=False,
    )

    sections = {
        "configure": configure_section,
        "execute": execute_section,
        "review": review_section,
        "help": help_section,
    }

    # ── Views and routing (ui_redesign P1-1) ──
    location = getattr(pn.state, "location", None) if pn.state.curdoc is not None else None
    router = Router(location)
    settings = load_ui_settings()
    session_list = SessionList(router, settings=settings, open_fn=session_loader.load)
    sessions_view = pn.Column(session_list.panel(), sizing_mode="stretch_width")

    def _load_routed_session(*events) -> None:
        # A refreshed page or shared link carries ?dir=…; load it once.
        target = router.output_dir
        scoped = router.view in ("session", "task_window")
        if scoped and target and str(state.output_dir or "") != target:
            session_loader.load(target)

    router.param.watch(_load_routed_session, ["view", "output_dir"])

    def _remember_on_run(event) -> None:
        if event.new == "running" and state.output_dir:
            session_list.remember_output(state.output_dir)

    state.param.watch(_remember_on_run, "run_status")

    # ── Task-window confirmation (ui_redesign P1-4) ──
    def _apply_task_windows(cfg) -> None:
        import dataclasses

        from pynpxpipe.core.checkpoint import CheckpointManager

        pipeline_form.apply_pipeline(dataclasses.replace(state.pipeline_config, task_windows=cfg))
        CheckpointManager(Path(str(state.output_dir))).clear("select_segments")
        run_panel.start(preview=True)  # discover/synchronize are skipped by their checkpoints

    def _confirm_task_windows() -> None:
        from pynpxpipe.pipelines.run_state import clear_task_window_pending

        clear_task_window_pending(Path(str(state.output_dir)))
        run_panel.start(preview=False)
        router.go("session", output_dir=str(state.output_dir or ""))

    def _sort_eta(kept_s: float) -> float | None:
        from pynpxpipe.pipelines.estimates import collect_stage_rates, estimate_stage_seconds
        from pynpxpipe.ui.recent_sessions import default_recent_path, load_recent

        if "sort_rates" not in eta_cache:
            dirs = [Path(e.output_dir) for e in load_recent(default_recent_path())]
            eta_cache["sort_rates"] = collect_stage_rates(dirs)
        return estimate_stage_seconds(
            eta_cache["sort_rates"],
            "sort",
            duration_s=kept_s,
            n_probes=max(1, len(state.probe_plan or {})),
            min_samples=settings.eta_min_samples,
        )

    task_window_page = TaskWindowPage(
        state,
        apply_fn=_apply_task_windows,
        confirm_fn=_confirm_task_windows,
        later_fn=lambda: router.go("session", output_dir=str(state.output_dir or "")),
        eta_fn=_sort_eta,
    )

    def _after_run(event) -> None:
        # An align-first run that paused for confirmation opens the confirmation page.
        from pynpxpipe.pipelines.run_state import is_task_window_pending

        if event.new != "completed" or not state.output_dir:
            return
        same = router.output_dir in ("", str(state.output_dir))
        if same and is_task_window_pending(Path(str(state.output_dir))):
            if router.view == "task_window":
                task_window_page.load(state.output_dir)
            else:
                router.go("task_window", output_dir=str(state.output_dir))

    state.param.watch(_after_run, "run_status")

    def _open_params() -> None:
        router.go("new")
        wizard.go(2)

    def _apply_suggestion(changes: tuple, stage: str, probe: str | None) -> None:
        """P1-6: apply the classifier's change, then confirm the rerun (P0-4 dialog)."""
        from pynpxpipe.ui.components.preset_bar import flatten_config, replace_path

        pipe, sort = state.pipeline_config, state.sorting_config
        for key, value in changes:
            if sort is not None and key in flatten_config(sort):
                sort = replace_path(sort, key.split("."), value)
            elif pipe is not None:
                pipe = replace_path(pipe, key.split("."), value)
        if pipe is not None:
            pipeline_form.apply_pipeline(pipe)
        if sort is not None:
            sorting_form.apply_sorting(sort)
        status_view.open_rerun(stage)
        if probe and probe in status_view.rerun_scope.options.values():
            status_view.rerun_scope.value = probe

    error_view = ErrorView(
        state,
        apply_fn=_apply_suggestion,
        open_params_fn=_open_params,
        help_fn=lambda: router.go("help"),
        min_batch_size=settings.min_batch_size,
    )

    workspace = Workspace(
        state,
        router,
        log_viewer=log_viewer,
        figures=figs_viewer.panel(),
        export_actions=export_actions,
        advanced=[("运行控制与任务时段时间轴", execute_section), ("全部阶段状态", review_section)],
        rerun_fn=status_view.open_rerun,
        stop_fn=lambda: get_run_manager().stop(str(state.output_dir or "")),
        open_params_fn=_open_params,
        settings=settings,
        error_view=error_view,
        resume_fn=lambda: run_panel.start(preview=False),
    )
    session_view = pn.Column(workspace.panel(), sizing_mode="stretch_width")
    views = {
        "sessions": sessions_view,
        "new": configure_section,
        "session": session_view,
        "task_window": task_window_page.panel(),
        "help": help_section,
    }
    # Legacy section names (tests, older links) map onto the routed views.
    legacy_views = {"configure": "new", "execute": "session", "review": "session"}

    def _show_view(*events) -> None:
        current = router.view
        for key, view in views.items():
            view.visible = key == current
        execute_section.visible = review_section.visible = current == "session"
        if current == "task_window" and state.output_dir:
            task_window_page.load(state.output_dir)
        if current == "session":
            workspace.refresh()

    router.param.watch(_show_view, ["view", "output_dir"])
    _show_view()

    def switch_section(name: str) -> None:
        router.go(legacy_views.get(name, name))

    # ── Error banner ──
    error_banner = pn.pane.Alert(
        "",
        alert_type="danger",
        visible=False,
        sizing_mode="stretch_width",
    )

    def _on_error_change(event) -> None:
        msg = event.new
        if msg:
            error_banner.object = msg
            error_banner.visible = True
        else:
            error_banner.visible = False

    state.param.watch(_on_error_change, ["error_message"])

    # ── Safe-to-exit banner ──
    # Driven by AppState.safe_to_exit, which RunPanel flips to True after a
    # successful pipeline (including Phase 3 raw export + bit-exact verify).
    safe_banner = pn.pane.Alert(
        "✅ 处理完成，可安全关闭窗口。",
        alert_type="success",
        visible=False,
        sizing_mode="stretch_width",
    )

    def _on_safe_to_exit_change(event) -> None:
        safe_banner.visible = bool(event.new)

    state.param.watch(_on_safe_to_exit_change, ["safe_to_exit"])

    # ── Header (navigation, machine status, run badge) ──
    top_bar = TopBar(state, router)
    if pn.state.curdoc is not None and pn.state.curdoc.session_context is not None:
        pn.state.onload(lambda: top_bar.start_polling(settings.poll_s))
        pn.state.onload(lambda: session_list.start_polling(settings.poll_s))
        pn.state.onload(lambda: workspace.start_polling(settings.poll_s))
        pn.state.onload(_load_routed_session)

    # ── Template ──
    template = pn.template.FastListTemplate(
        title="pynpxpipe",
        theme="default",
        theme_toggle=True,
        accent_base_color="#0B6E8E",
        header=[top_bar.panel()],
        # One container: hidden views would otherwise each leave an empty template card.
        main=[pn.Column(error_banner, safe_banner, *views.values(), sizing_mode="stretch_width")],
        modal=[status_view.rerun_dialog],
    )
    status_view.set_modal_handlers(template.open_modal, template.close_modal)

    # ── Expose internals for testing ──
    template._pynpx_sections = sections
    template._pynpx_switch = switch_section
    template._pynpx_error_banner = error_banner
    template._pynpx_safe_banner = safe_banner
    template._pynpx_state = state
    template._pynpx_preset_bar = preset_bar
    template._pynpx_status_view = status_view
    template._pynpx_status_badge = top_bar.status_badge
    template._pynpx_router = router
    template._pynpx_views = views
    template._pynpx_top_bar = top_bar
    template._pynpx_session_list = session_list
    template._pynpx_wizard = wizard
    template._pynpx_task_window_page = task_window_page
    template._pynpx_workspace = workspace
    template._pynpx_error_view = error_view

    return template


def main() -> None:
    """Entry point for `pynpxpipe-ui` script."""
    app = create_app()
    app.show(title="pynpxpipe UI")
