"""ui/components/session_list.py — Home page: recent sessions (ui_redesign.md §4.3 P1-2).

Each row merges checkpoint status, the run registry (``run_state.json``) and the
task-window pending marker into a 9-segment stage strip and one status badge.
Clicking a row loads the session and routes by status: waiting → task-window
page, failed → workspace at the failed stage, otherwise → workspace.
"""

from __future__ import annotations

import html
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import panel as pn

from pynpxpipe.pipelines.constants import STAGE_ORDER
from pynpxpipe.pipelines.run_state import (
    effective_status,
    is_task_window_pending,
    read_run_state,
)
from pynpxpipe.pipelines.status import read_pipeline_status
from pynpxpipe.ui.components.browsable_input import BrowsableInput
from pynpxpipe.ui.recent_sessions import (
    RecentEntry,
    default_recent_path,
    entry_from_output,
    forget,
    load_recent,
    remember,
)
from pynpxpipe.ui.router import Router
from pynpxpipe.ui.settings import UISettings

# Stage-strip and badge colours — docs/design/ui_redesign/README.md (Main.dc.html).
_STRIP = {
    "done": "#2E8B57",
    "running": "#0B6E8E",
    "waiting": "#D99A1E",
    "failed": "#C8372D",
    "pending": "#E3E3DE",
    "skipped": "repeating-linear-gradient(45deg,#E3E3DE 0 3px,#F6F6F3 3px 6px)",
}
_BADGE = {
    "run": ("#E3F0F5", "#08516A"),
    "wait": ("#FBF0DA", "#7A4D00"),
    "fail": ("#FBE6E4", "#8F1C13"),
    "done": ("#E4F2E9", "#155E35"),
    "idle": ("#EFEFEA", "#4A4F59"),
    "missing": ("#EFEFEA", "#8A8F99"),
}
_LEGEND = (
    "色块：绿 = 完成，蓝 = 运行中，黄 = 等你确认，红 = 失败，灰 = 未开始，"
    "斜线 = 已跳过（merge 默认不跑）。"
)


def relative_time(ts: float, now: float) -> str:
    """Human "how long ago" text in Chinese."""
    delta = max(0.0, now - ts)
    if delta < 60:
        return "刚刚"
    if delta < 3600:
        return f"{int(delta // 60)} 分钟前"
    if delta < 86400:
        return f"{int(delta // 3600)} 小时前"
    if delta < 2 * 86400:
        return "昨天"
    return f"{int(delta // 86400)} 天前"


@dataclass
class SessionRow:
    """Display data for one recent session.

    Attributes:
        entry: The stored recent entry.
        stages: One of _STRIP's keys per STAGE_ORDER stage.
        kind: run / wait / fail / done / idle / missing.
        status: Badge text.
        target_view: Router view opened by clicking the row.
        target_stage: Stage to focus (failed stage), or "".
        updated: Relative time of the latest activity.
    """

    entry: RecentEntry
    stages: list[str]
    kind: str
    status: str
    target_view: str
    target_stage: str
    updated: str


def compute_row(entry: RecentEntry, settings: UISettings, now: float) -> SessionRow:
    """Derive the stage strip and status of *entry* from its output directory.

    Args:
        entry: Recent entry.
        settings: UI settings (heartbeat timeout).
        now: Epoch seconds.
    """
    out = Path(entry.output_dir)
    if not out.is_dir():
        return SessionRow(
            entry, ["pending"] * len(STAGE_ORDER), "missing", "目录不存在", "sessions", "", ""
        )
    statuses = read_pipeline_status(out, entry.probe_ids)
    state = read_run_state(out)
    run = effective_status(state, now=now, timeout_s=settings.heartbeat_timeout_s) if state else ""
    pending = is_task_window_pending(out)

    strip = []
    for i, stage in enumerate(STAGE_ORDER):
        status = statuses.get(stage, "pending")
        if status == "completed":
            colour = "done"
        elif status == "failed":
            colour = "failed"
        elif any(statuses.get(s) == "completed" for s in STAGE_ORDER[i + 1 :]):
            colour = "skipped"
        else:
            colour = "pending"
        strip.append(colour)
    if pending:
        strip[STAGE_ORDER.index("select_segments")] = "waiting"
    if run == "running" and state.current_stage in STAGE_ORDER:
        strip[STAGE_ORDER.index(state.current_stage)] = "running"

    failed_stage = next((s for s in STAGE_ORDER if statuses.get(s) == "failed"), "")
    if run == "failed" and not failed_stage:
        failed_stage = state.current_stage
    if run == "running":
        kind, text = "run", f"运行中 · {state.current_stage} {state.fraction * 100:.0f}%"
    elif pending:
        kind, text = "wait", "等你确认任务时段"
    elif failed_stage:
        reason = state.error if state and state.status == "failed" else ""
        kind, text = "fail", f"{failed_stage} 失败" + (f" · {reason}" if reason else "")
    elif run == "interrupted":
        kind, text = "idle", f"已中断 · {state.current_stage}"
    elif statuses.get("export") == "completed":
        kind, text = "done", "已导出 NWB"
    else:
        kind, text = "idle", "未完成"

    view = "task_window" if kind == "wait" else "session"
    ts = state.heartbeat_at if state else (out / "checkpoints").stat().st_mtime
    return SessionRow(
        entry,
        strip,
        kind,
        text,
        view,
        failed_stage if kind == "fail" else "",
        relative_time(ts, now) if (out / "checkpoints").exists() or state else "",
    )


def _row_html(row: SessionRow) -> str:
    e = row.entry
    cells = "".join(
        f'<span title="{s}" style="display:inline-block;width:16px;height:10px;margin-right:2px;'
        f'border-radius:2px;background:{_STRIP[c]}"></span>'
        for s, c in zip(STAGE_ORDER, row.stages, strict=True)
    )
    bg, fg = _BADGE[row.kind]
    return (
        '<div style="display:grid;grid-template-columns:2.2fr 1fr 1fr 1.6fr 1.6fr 0.8fr;'
        'gap:12px;align-items:center;font-size:13px">'
        f'<div><div style="font-weight:600">{html.escape(e.name)}</div>'
        f'<div style="font-family:monospace;font-size:12px;color:#5B606B">'
        f"{html.escape(e.output_dir)}</div></div>"
        f"<div>{html.escape(e.subject_id or '—')}</div>"
        f'<div style="font-family:monospace">{html.escape(", ".join(e.probe_ids) or "—")}</div>'
        f"<div>{cells}</div>"
        f'<div><span style="padding:3px 10px;border-radius:999px;background:{bg};color:{fg}">'
        f"{html.escape(row.status)}</span></div>"
        f'<div style="color:#5B606B">{html.escape(row.updated)}</div></div>'
    )


class SessionList:
    """Recent-session table with counts, search and "open existing" entry point.

    Args:
        router: App router.
        recent_path: Store file; defaults to <project>/.pynpxpipe/recent_sessions.json.
        settings: UI settings.
        open_fn: Loads a session into the app; returning False aborts navigation.
        now_fn: Epoch-seconds clock (injectable for tests).
    """

    def __init__(
        self,
        router: Router,
        *,
        recent_path: Path | None = None,
        settings: UISettings | None = None,
        open_fn: Callable[[str], bool | None] | None = None,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._router = router
        self._path = Path(recent_path) if recent_path else default_recent_path()
        self._settings = settings or UISettings()
        self._open_fn = open_fn or (lambda d: True)
        self._now = now_fn
        self.rows: list[SessionRow] = []
        self.counts: dict[str, int] = {}

        self.search = pn.widgets.TextInput(placeholder="搜索动物、日期、实验名", width=260)
        self.new_btn = pn.widgets.Button(name="+ 新建 session", button_type="primary", width=150)
        self.open_input = BrowsableInput(
            name="打开已有输出目录…", placeholder="含 session.json 的输出目录", only_files=False
        )
        self.open_btn = pn.widgets.Button(name="打开", width=80)
        self.message = pn.pane.Alert("", alert_type="danger", visible=False)
        self.counts_pane = pn.pane.HTML("", sizing_mode="stretch_width")
        self.list_pane = pn.Column(sizing_mode="stretch_width")

        self.search.param.watch(lambda event: self._render(), "value_input")
        self.search.param.watch(lambda event: self._render(), "value")
        self.new_btn.on_click(lambda event: self._router.go("new"))
        self.open_btn.on_click(self._on_open_existing)
        self.refresh()

    # ── Data ──

    def refresh(self) -> None:
        """Re-read the store and every session's status, then redraw."""
        now = self._now()
        self.rows = [compute_row(e, self._settings, now) for e in load_recent(self._path)]
        kinds = [r.kind for r in self.rows]
        self.counts = {
            "running": kinds.count("run"),
            "waiting": kinds.count("wait"),
            "failed": kinds.count("fail"),
            "exported": kinds.count("done"),
        }
        self._render()

    def open(self, row: SessionRow) -> None:
        """Load *row*'s session and route to the page matching its status."""
        ok = self._open_fn(row.entry.output_dir)
        if ok is False:
            self._error(f"无法打开 {row.entry.output_dir}")
            return
        remember(
            self._path,
            entry_from_output(Path(row.entry.output_dir), now=self._now()),
            max_entries=self._settings.recent_sessions_max,
            now=self._now(),
        )
        self._router.go(row.target_view, output_dir=row.entry.output_dir, stage=row.target_stage)

    def remember_output(self, output_dir: str | Path) -> None:
        """Move *output_dir* to the top of the list (on load or run start)."""
        entry = entry_from_output(Path(output_dir), now=self._now())
        remember(self._path, entry, max_entries=self._settings.recent_sessions_max, now=self._now())
        self.refresh()

    def remove(self, row: SessionRow) -> None:
        """Forget a (missing) directory."""
        forget(self._path, row.entry.output_dir)
        self.refresh()

    def _on_open_existing(self, event=None) -> None:
        raw = (self.open_input.value or "").strip()
        if not raw or not Path(raw).is_dir():
            self._error(f"目录不存在：{raw or '（未填写）'}")
            return
        self.message.visible = False
        entry = entry_from_output(Path(raw), now=self._now())
        remember(self._path, entry, max_entries=self._settings.recent_sessions_max, now=self._now())
        self.refresh()
        self.open(compute_row(entry, self._settings, self._now()))

    def _error(self, text: str) -> None:
        self.message.object = text
        self.message.visible = True

    # ── Rendering ──

    def _render(self) -> None:
        query = (self.search.value_input or self.search.value or "").strip().lower()
        boxes = [
            ("运行中", self.counts.get("running", 0)),
            ("待你确认", self.counts.get("waiting", 0)),
            ("失败", self.counts.get("failed", 0)),
            ("已导出 NWB", self.counts.get("exported", 0)),
        ]
        self.counts_pane.object = (
            '<div style="display:flex;gap:12px">'
            + "".join(
                '<div style="flex:1;padding:12px 16px;border:1px solid #E3E3DE;border-radius:10px">'
                f'<div style="font-size:12px;color:#5B606B">{label}</div>'
                f'<div style="font-size:22px;font-weight:600">{n}</div></div>'
                for label, n in boxes
            )
            + "</div>"
        )
        objects = []
        for row in self.rows:
            e = row.entry
            haystack = f"{e.name} {e.subject_id} {e.output_dir}".lower()
            if query and query not in haystack:
                continue
            if row.kind == "missing":
                btn = pn.widgets.Button(name="移除", width=70)
                btn.on_click(lambda event, r=row: self.remove(r))
            else:
                btn = pn.widgets.Button(name="打开", width=70, button_type="primary")
                btn.on_click(lambda event, r=row: self.open(r))
            objects.append(pn.Row(pn.pane.HTML(_row_html(row), sizing_mode="stretch_width"), btn))
        self.list_pane.objects = objects or [
            pn.pane.Markdown("还没有 session。点「+ 新建 session」开始。")
        ]

    def start_polling(self, period_s: float) -> None:
        """Refresh every *period_s* seconds while the page is open."""
        pn.state.add_periodic_callback(self.refresh, period=int(period_s * 1000))

    def panel(self) -> pn.Column:
        """Return the home-page layout."""
        return pn.Column(
            pn.Row(
                pn.pane.Markdown(
                    "## 你的 session\n按最近打开排序。点击一行进入工作区，"
                    "查看进度、诊断图或从某一阶段重跑。"
                ),
                pn.layout.HSpacer(),
                self.search,
                self.new_btn,
                sizing_mode="stretch_width",
            ),
            pn.Row(self.open_input.panel(), self.open_btn, sizing_mode="stretch_width"),
            self.message,
            self.counts_pane,
            self.list_pane,
            pn.pane.Markdown(_LEGEND, styles={"font-size": "12px", "color": "#5B606B"}),
            sizing_mode="stretch_width",
        )
