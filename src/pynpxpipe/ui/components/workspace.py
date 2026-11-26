"""ui/components/workspace.py — Session workspace (ui_redesign.md §4.3 P1-5).

Stage rail → stage detail (per-probe progress, logs) → stage actions, figures
and the task-window summary. Progress comes from ``checkpoints/run_state.json``
and per-probe checkpoints, so any browser session sees a run started elsewhere.
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from pathlib import Path

import panel as pn

from pynpxpipe.pipelines.constants import PER_PROBE_STAGES, STAGE_ORDER
from pynpxpipe.pipelines.run_state import (
    effective_status,
    is_task_window_pending,
    read_run_state,
)
from pynpxpipe.pipelines.status import read_pipeline_status
from pynpxpipe.ui.components.log_viewer import LogViewer
from pynpxpipe.ui.router import Router
from pynpxpipe.ui.settings import UISettings
from pynpxpipe.ui.state import AppState

_ICONS = {"done": "✓", "running": "▶", "failed": "!", "waiting": "⏸", "pending": "○"}
_LABELS = {"done": "完成", "failed": "失败", "waiting": "待确认", "pending": "等待"}
_BADGES = {
    "running": ("运行中", "#E3F0F5", "#08516A"),
    "waiting": ("等你确认任务时段", "#FBF0DA", "#7A4D00"),
    "failed": ("已停止 · {stage} 失败", "#FBE6E4", "#8F1C13"),
    "interrupted": ("已中断 · {stage}", "#EFEFEA", "#4A4F59"),
    "done": ("已导出 NWB", "#E4F2E9", "#155E35"),
    "idle": ("未在运行", "#EFEFEA", "#4A4F59"),
}


def _probe_status(cp_dir: Path, stage: str, probe_id: str) -> str:
    try:
        data = json.loads((cp_dir / f"{stage}_{probe_id}.json").read_text("utf-8"))
        return data.get("status", "pending")
    except (OSError, ValueError):
        return "pending"


class Workspace:
    """Per-session view: progress rail, stage detail, actions and figures.

    Args:
        state: Shared AppState (output_dir, probe_plan, subject).
        router: App router (``stage`` selects the stage detail).
        log_viewer: Shared log viewer (filters follow the selected stage).
        figures: Diagnostic figure browser layout.
        export_actions: Resume-export / derivative tools shown for the export stage.
        advanced: Extra (title, layout) sections, collapsed at the bottom.
        rerun_fn: Opens the rerun confirmation for a stage (P0-4).
        stop_fn: Requests the running job to stop.
        open_params_fn: Shows the parameters (wizard step 3).
        settings: UI settings (heartbeat timeout).
        error_view: Failure view shown for a failed stage (P1-6), or None.
        resume_fn: Continues the pipeline (completed stages are skipped), or None.
    """

    def __init__(
        self,
        state: AppState,
        router: Router,
        *,
        log_viewer: LogViewer,
        figures: pn.viewable.Viewable,
        export_actions: pn.viewable.Viewable,
        advanced: list[tuple[str, pn.viewable.Viewable]],
        rerun_fn: Callable[[str], None],
        stop_fn: Callable[[], None],
        open_params_fn: Callable[[], None],
        settings: UISettings | None = None,
        error_view=None,
        resume_fn: Callable[[], None] | None = None,
    ) -> None:
        self._state = state
        self._router = router
        self._log_viewer = log_viewer
        self._figures = figures
        self._advanced = advanced
        self._settings = settings or UISettings()
        self._error_view = error_view
        self.error_box = pn.Column(
            *([error_view.panel()] if error_view is not None else []),
            visible=False,
            sizing_mode="stretch_width",
        )
        self.selected = STAGE_ORDER[0]
        self._stage_status: dict[str, str] = {}

        self.header = pn.pane.HTML("", sizing_mode="stretch_width")
        self.badge = pn.pane.HTML("")
        self.stop_btn = pn.widgets.Button(name="停止", button_type="danger", width=80)
        self.continue_btn = pn.widgets.Button(
            name="继续运行", button_type="primary", width=100, visible=False
        )
        self._resume_fn = resume_fn
        self.continue_btn.on_click(lambda event: self._resume_fn and self._resume_fn())
        self.rail_buttons: dict[str, pn.widgets.Button] = {}
        for stage in STAGE_ORDER:
            btn = pn.widgets.Button(name=stage, button_type="light", width=150)
            btn.on_click(lambda event, s=stage: self.select(s))
            self.rail_buttons[stage] = btn
        self.stage_title = pn.pane.Markdown("")
        self.probes_pane = pn.Column(sizing_mode="stretch_width")
        self.params_btn = pn.widgets.Button(name="查看本阶段所用参数")
        self.rerun_btn = pn.widgets.Button(name="改参数并从此阶段重跑…", button_type="warning")
        self.import_btn = pn.widgets.Button(name="改用外部 sorting 结果…")
        self.export_box = pn.Column(export_actions, visible=False, sizing_mode="stretch_width")
        self.task_card = pn.pane.Markdown("", sizing_mode="stretch_width")
        self.task_btn = pn.widgets.Button(name="查看时间轴", width=120)

        self.stop_btn.on_click(lambda event: stop_fn())
        self.params_btn.on_click(lambda event: open_params_fn())
        self.import_btn.on_click(lambda event: open_params_fn())
        self.rerun_btn.on_click(lambda event: rerun_fn(self.selected))
        self.task_btn.on_click(
            lambda event: self._router.go("task_window", output_dir=self._router.output_dir)
        )

    # ── Data ──

    def refresh(self) -> None:
        """Re-read checkpoints and the run registry, then redraw (polled while open)."""
        st = self._state
        out = Path(str(st.output_dir)) if st.output_dir else None
        if out is None or not out.is_dir():
            self.header.object = "<h2>未打开 session</h2>"
            self.badge.object = ""
            self.stop_btn.visible = self.continue_btn.visible = False
            return

        probes = sorted((st.probe_plan or {}).keys())
        statuses = read_pipeline_status(out, probes)
        run_state = read_run_state(out)
        run = (
            effective_status(run_state, timeout_s=self._settings.heartbeat_timeout_s)
            if run_state
            else ""
        )
        self._run_state, self._run = run_state, run
        pending = is_task_window_pending(out)

        stage_status: dict[str, str] = {}
        for stage in STAGE_ORDER:
            raw = statuses.get(stage, "pending")
            stage_status[stage] = (
                "done" if raw == "completed" else "failed" if raw == "failed" else "pending"
            )
        if pending:
            stage_status["select_segments"] = "waiting"
        running_stage = run_state.current_stage if run == "running" else ""
        if running_stage in stage_status:
            stage_status[running_stage] = "running"
        self._stage_status = stage_status

        for stage, btn in self.rail_buttons.items():
            status = stage_status[stage]
            meta = (
                f"{run_state.fraction * 100:.0f}%"
                if status == "running"
                else _LABELS.get(status, "")
            )
            btn.name = f"{_ICONS[status]} {stage} · {meta}"

        failed = next((s for s in STAGE_ORDER if stage_status[s] == "failed"), "")
        if run == "running":
            kind, stage_label = "running", running_stage
        elif pending:
            kind, stage_label = "waiting", "select_segments"
        elif failed:
            kind, stage_label = "failed", failed
        elif run == "interrupted":
            kind, stage_label = "interrupted", run_state.current_stage
        elif stage_status["export"] == "done":
            kind, stage_label = "done", "export"
        else:
            kind, stage_label = "idle", ""
        text, bg, fg = _BADGES[kind]
        self.badge.object = (
            f'<span style="padding:4px 12px;border-radius:999px;background:{bg};color:{fg}">'
            f"{html.escape(text.format(stage=stage_label))}</span>"
        )
        self.stop_btn.visible = kind == "running"
        self.continue_btn.visible = self._resume_fn is not None and kind in (
            "failed",
            "interrupted",
            "idle",
        )

        subject = st.subject_config.subject_id if st.subject_config else "—"
        areas = "，".join(f"{p} {a}" for p, a in sorted((st.probe_plan or {}).items()))
        self.header.object = (
            f'<div><h2 style="margin:0">{html.escape(out.name)}</h2>'
            f'<div style="color:#5B606B">{html.escape(subject)} · '
            f"{html.escape(st.recording_date or '—')} · {html.escape(areas or '—')} · "
            f'<span style="font-family:monospace">{html.escape(str(out))}</span></div></div>'
        )

        self._render_task_card(out)
        wanted = self._router.stage if self._router.stage in STAGE_ORDER else ""
        default = (
            wanted
            or running_stage
            or failed
            or next((s for s in STAGE_ORDER if stage_status[s] != "done"), STAGE_ORDER[-1])
        )
        self._show(default)

    def _render_task_card(self, out: Path) -> None:
        try:
            info = json.loads((out / "03_segments" / "summary.json").read_text("utf-8"))
        except (OSError, ValueError):
            self.task_card.object = "#### 任务时段\n尚未生成。"
            self.task_btn.visible = False
            return
        kept = float(info.get("retained_duration_s", 0.0))
        dropped = float(info.get("original_duration_s", kept)) - kept
        self.task_card.object = (
            f"#### 任务时段\n保留 {info.get('n_blocks', '?')} 段，共 {kept / 60:.1f} min，"
            f"丢弃 {dropped / 60:.1f} min 空闲。"
        )
        self.task_btn.visible = True

    # ── Stage detail ──

    def select(self, stage: str) -> None:
        """Show *stage* in the detail panel and record it in the URL."""
        self._router.go("session", output_dir=self._router.output_dir, stage=stage)
        self._show(stage)

    def _show(self, stage: str) -> None:
        self.selected = stage
        for name, btn in self.rail_buttons.items():
            btn.button_type = "primary" if name == stage else "light"
        status = self._stage_status.get(stage, "pending")
        self.stage_title.object = f"### {stage}\n{_LABELS.get(status, '运行中')}"
        self._log_viewer.current_stage = stage
        self._log_viewer.refresh()
        self.import_btn.visible = stage == "sort"
        self.export_box.visible = stage == "export"
        failed = self._stage_status.get(stage) == "failed"
        self.error_box.visible = bool(
            failed
            and self._error_view is not None
            and self._state.output_dir
            and self._error_view.load(self._state.output_dir, stage)
        )
        self._render_probes(stage)

    def _render_probes(self, stage: str) -> None:
        probes = sorted((self._state.probe_plan or {}).keys())
        if stage not in PER_PROBE_STAGES or not probes or not self._state.output_dir:
            self.probes_pane.objects = []
            return
        cp_dir = Path(str(self._state.output_dir)) / "checkpoints"
        rs = getattr(self, "_run_state", None)
        running = getattr(self, "_run", "") == "running" and rs is not None
        rows = []
        for probe in probes:
            status = _probe_status(cp_dir, stage, probe)
            if status == "completed":
                value, text = 100, "完成"
            elif status == "failed":
                value, text = 0, "失败"
            elif running and rs.current_stage == stage and rs.current_probe == probe:
                value, text = round(rs.fraction * 100), f"{rs.fraction * 100:.0f}%"
            else:
                value, text = 0, "等待"
            rows.append(
                pn.Row(
                    pn.pane.Markdown(f"`{probe}` {text}", width=160),
                    pn.indicators.Progress(value=value, max=100, sizing_mode="stretch_width"),
                    sizing_mode="stretch_width",
                )
            )
        self.probes_pane.objects = rows

    def start_polling(self, period_s: float) -> None:
        """Refresh every *period_s* seconds while the page is open."""
        pn.state.add_periodic_callback(self._poll, period=int(period_s * 1000))

    def _poll(self) -> None:
        if self._router.view == "session":
            self.refresh()

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        """Return the workspace layout."""
        return pn.Column(
            pn.Row(
                self.header,
                self.badge,
                self.stop_btn,
                self.continue_btn,
                sizing_mode="stretch_width",
            ),
            pn.FlexBox(*self.rail_buttons.values(), sizing_mode="stretch_width"),
            pn.Row(
                pn.Column(
                    self.stage_title,
                    self.error_box,
                    self.probes_pane,
                    self._log_viewer.panel(),
                    sizing_mode="stretch_width",
                ),
                pn.Column(
                    pn.pane.Markdown("#### 此阶段"),
                    self.params_btn,
                    self.rerun_btn,
                    self.import_btn,
                    self.export_box,
                    pn.pane.Markdown("#### 诊断图"),
                    self._figures,
                    self.task_card,
                    self.task_btn,
                    width=420,
                ),
                sizing_mode="stretch_width",
            ),
            *(
                pn.Card(body, title=title, collapsed=True, sizing_mode="stretch_width")
                for title, body in self._advanced
            ),
            sizing_mode="stretch_width",
        )
