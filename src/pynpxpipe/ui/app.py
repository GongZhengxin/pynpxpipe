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
from pynpxpipe.ui.components.figs_viewer import FigsViewer
from pynpxpipe.ui.components.log_viewer import LogViewer
from pynpxpipe.ui.components.pipeline_form import PipelineForm
from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor
from pynpxpipe.ui.components.progress_view import ProgressView
from pynpxpipe.ui.components.run_panel import RunPanel
from pynpxpipe.ui.components.session_form import SessionForm
from pynpxpipe.ui.components.session_loader import SessionLoader
from pynpxpipe.ui.components.sorting_form import SortingForm
from pynpxpipe.ui.components.stage_selector import StageSelector
from pynpxpipe.ui.components.status_view import StatusView
from pynpxpipe.ui.components.subject_form import SubjectForm
from pynpxpipe.ui.state import AppState, ProgressBridge


class _UILogHandler(logging.Handler):
    """Logging handler that feeds log records to a LogViewer widget.

    Thread-safe: schedules UI updates via pn.state.execute().
    """

    def __init__(self, log_viewer: LogViewer) -> None:
        super().__init__()
        self._log_viewer = log_viewer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            pn.state.execute(lambda m=msg: self._push(m))
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

    def __init__(self, original: io.TextIOBase, log_viewer: LogViewer) -> None:
        self._original = original
        self._log_viewer = log_viewer
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
                if is_overwrite:
                    pn.state.execute(
                        lambda t=stripped: (
                            self._log_viewer.replace_last(t),
                            self._log_viewer.refresh(),
                        )
                    )
                else:
                    pn.state.execute(lambda text=stripped: self._push(text))
        return result

    def _push(self, text: str) -> None:
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
    state = AppState()

    # ── Components ──
    session_form = SessionForm(state)
    subject_form = SubjectForm(state)
    probe_region_editor = ProbeRegionEditor(state)
    pipeline_form = PipelineForm(state)
    sorting_form = SortingForm(state)
    stage_selector = StageSelector(state)

    log_viewer = LogViewer()
    ui_handler = _UILogHandler(log_viewer)
    ui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s"))

    # Install TeeStream wrappers for stdout/stderr capture (tqdm, print, etc.)
    tee_stdout = _TeeStream(sys.stdout, log_viewer)
    tee_stderr = _TeeStream(sys.stderr, log_viewer)
    sys.stdout = tee_stdout
    sys.stderr = tee_stderr

    def pipeline_fn(st: AppState, bridge: ProgressBridge) -> None:
        """Execute the pipeline from UI state. Runs in a background thread."""
        from pynpxpipe.core.logging import setup_logging
        from pynpxpipe.core.session import SessionManager
        from pynpxpipe.pipelines.runner import PipelineRunner

        if not st.session_dir:
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

        if session_json.exists():
            session = SessionManager.load(output_path)
            # Update subject in case the user changed it in the UI
            session.subject = st.subject_config
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
            runner.run(stages=stages)
        finally:
            tee_stdout.deactivate()
            tee_stderr.deactivate()
            root_logger.removeHandler(ui_handler)

    run_panel = RunPanel(state, pipeline_fn=pipeline_fn)
    progress_view = ProgressView(state)

    status_view = StatusView(state)
    figs_viewer = FigsViewer(state)
    chat_help = ChatHelp(state)

    def _on_session_loaded() -> None:
        status_view.load_status()
        figs_viewer.load_figures()

    session_loader = SessionLoader(state, on_session_loaded=_on_session_loaded)

    # ── Sections ──
    configure_left = pn.Column(
        session_form.panel(),
        subject_form.panel(),
        probe_region_editor.panel(),
        stage_selector.panel(),
        sizing_mode="stretch_width",
    )
    configure_right = pn.Column(
        pipeline_form.panel(),
        sorting_form.panel(),
        sizing_mode="stretch_width",
    )
    configure_section = pn.Row(
        configure_left,
        configure_right,
        sizing_mode="stretch_width",
    )

    execute_section = pn.Row(
        pn.Column(
            run_panel.panel(),
            progress_view.panel(),
            sizing_mode="stretch_width",
            min_width=400,
        ),
        pn.Column(
            log_viewer.panel(),
            sizing_mode="stretch_both",
            min_width=400,
        ),
        sizing_mode="stretch_width",
        visible=False,
    )

    review_section = pn.Column(
        session_loader.panel(),
        status_view.panel(),
        figs_viewer.panel(),
        sizing_mode="stretch_width",
        visible=False,
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

    # ── Section switching ──
    def switch_section(name: str) -> None:
        for key, col in sections.items():
            col.visible = key == name

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

    # ── Sidebar navigation ──
    nav_buttons = {}
    for label in ("Configure", "Execute", "Review", "Help"):
        btn = pn.widgets.Button(
            name=label,
            button_type="primary" if label == "Configure" else "default",
            width=150,
        )
        nav_buttons[label.lower()] = btn

    def _make_nav_handler(name: str):
        def handler(event):
            switch_section(name)
            for key, btn in nav_buttons.items():
                btn.button_type = "primary" if key == name else "default"

        return handler

    for name, btn in nav_buttons.items():
        btn.on_click(_make_nav_handler(name))

    status_indicator = pn.pane.Str(
        "Status: idle",
        styles={"font-size": "12px", "color": "#8b949e", "margin-top": "16px"},
    )

    def _on_run_status_change(event) -> None:
        status_indicator.object = f"Status: {event.new}"

    state.param.watch(_on_run_status_change, ["run_status"])

    # ── Template ──
    template = pn.template.FastListTemplate(
        title="pynpxpipe",
        theme="dark",
        accent_base_color="#1f6feb",
        sidebar=[
            *nav_buttons.values(),
            status_indicator,
        ],
        main=[
            error_banner,
            safe_banner,
            configure_section,
            execute_section,
            review_section,
            help_section,
        ],
    )

    # ── Expose internals for testing ──
    template._pynpx_sections = sections
    template._pynpx_switch = switch_section
    template._pynpx_error_banner = error_banner
    template._pynpx_safe_banner = safe_banner
    template._pynpx_state = state

    return template


def main() -> None:
    """Entry point for `pynpxpipe-ui` script."""
    app = create_app()
    app.show(title="pynpxpipe UI")
