"""ui/components/wizard.py — Step-by-step "new session" shell (ui_redesign.md §4.3 P1-3).

The wizard only arranges existing form components into steps; every form writes
AppState as the user types, so moving between steps never loses the draft.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass

import panel as pn


@dataclass
class WizardStep:
    """One wizard page.

    Attributes:
        title: Short step name shown in the indicator.
        body: Layout shown while the step is active.
        validate: Returns an error message blocking "next", or None.
        on_enter: Called each time the step becomes active (e.g. rerun checks).
    """

    title: str
    body: pn.viewable.Viewable
    validate: Callable[[], str | None] | None = None
    on_enter: Callable[[], None] | None = None


class Wizard:
    """Step indicator, one visible body, and cancel / previous / next buttons.

    Args:
        steps: The pages, in order.
        on_cancel: Called when the user cancels (e.g. route back to the session list).
    """

    def __init__(
        self, steps: list[WizardStep], on_cancel: Callable[[], None] | None = None
    ) -> None:
        self.steps = steps
        self.index = 0
        self._on_cancel = on_cancel or (lambda: None)

        self.indicator = pn.pane.HTML("", sizing_mode="stretch_width")
        self.draft_note = pn.pane.HTML(
            '<span style="font-size:12px;color:#5B606B">草稿已自动保存</span>'
        )
        self.alert = pn.pane.Alert("", alert_type="warning", visible=False)
        self.cancel_btn = pn.widgets.Button(name="取消", width=90)
        self.prev_btn = pn.widgets.Button(name="上一步", width=90)
        self.next_btn = pn.widgets.Button(name="", button_type="primary", width=220)

        self.cancel_btn.on_click(lambda event: self._on_cancel())
        self.prev_btn.on_click(lambda event: self.go(self.index - 1))
        self.next_btn.on_click(lambda event: self.next())
        self._render()

    def next(self) -> bool:
        """Validate the current step and advance; returns whether it moved."""
        check = self.steps[self.index].validate
        error = check() if check else None
        if error:
            self.alert.object = error
            self.alert.visible = True
            return False
        return self.go(self.index + 1)

    def go(self, index: int) -> bool:
        """Show step *index* (clamped); returns whether the step changed."""
        index = max(0, min(index, len(self.steps) - 1))
        if index == self.index:
            return False
        self.index = index
        self.alert.visible = False
        self._render()
        if self.steps[index].on_enter is not None:
            self.steps[index].on_enter()
        return True

    def reset(self) -> None:
        """Return to the first step (e.g. when starting another new session)."""
        self.index = 0
        self.alert.visible = False
        self._render()

    def _render(self) -> None:
        for i, step in enumerate(self.steps):
            step.body.visible = i == self.index
        items = []
        for i, step in enumerate(self.steps):
            if i < self.index:
                mark, style, current = "✓", "background:#2E8B57;color:#FFFFFF", ""
            elif i == self.index:
                mark, style, current = (
                    str(i + 1),
                    "background:#0B6E8E;color:#FFFFFF",
                    (' aria-current="step"'),
                )
            else:
                mark, style, current = str(i + 1), "border:1px solid #C9C9C2;color:#5B606B", ""
            weight = "600" if i == self.index else "400"
            items.append(
                f'<li{current} style="display:flex;align-items:center;gap:8px;'
                f'font-weight:{weight}"><span style="width:24px;height:24px;border-radius:50%;'
                f'display:grid;place-items:center;font-size:12px;{style}">{mark}</span>'
                f"{html.escape(step.title)}</li>"
            )
        self.indicator.object = (
            '<ol style="display:flex;gap:24px;list-style:none;margin:0;padding:8px 0">'
            + "".join(items)
            + "</ol>"
        )
        last = self.index == len(self.steps) - 1
        self.prev_btn.visible = self.index > 0
        self.next_btn.visible = not last
        if not last:
            self.next_btn.name = f"下一步：{self.steps[self.index + 1].title}"

    def panel(self) -> pn.Column:
        """Return the wizard layout."""
        return pn.Column(
            pn.Row(self.indicator, self.draft_note, sizing_mode="stretch_width"),
            self.alert,
            *(step.body for step in self.steps),
            pn.Row(
                self.cancel_btn,
                pn.layout.HSpacer(),
                self.prev_btn,
                self.next_btn,
                sizing_mode="stretch_width",
            ),
            sizing_mode="stretch_width",
        )


_CHECK_ICONS = {
    "pass": ("✓", "#E4F2E9", "#155E35"),
    "warn": ("!", "#FBF0DA", "#7A4D00"),
    "fail": ("✗", "#FBE6E4", "#8F1C13"),
}
_MODE_NOTES = {
    "align": (
        "先跑完 discover、synchronize、select_segments 后暂停，等你在时间轴上核对保留区间，"
        "再继续 preprocess 到 export。"
    ),
    "full": "直接从头运行到 export。参数已在之前的 session 验证过时使用。",
}


class ReviewStep:
    """Wizard step 4: summary, preflight checklist, run mode and stage plan.

    Args:
        state: Shared AppState.
        checks_fn: Runs the preflight checks (harness PreflightChecker results).
        eta_fn: Estimated seconds for a stage, or None when unknown (§8.4).
        start_fn: Starts the run with mode "align" or "full".
        params_summary_fn: One-line parameter summary (preset and changes).
    """

    def __init__(
        self,
        state,
        *,
        checks_fn: Callable[[], list],
        eta_fn: Callable[[str], float | None],
        start_fn: Callable[[str], None],
        params_summary_fn: Callable[[], str],
    ) -> None:
        self._state = state
        self._checks_fn = checks_fn
        self._eta_fn = eta_fn
        self._start_fn = start_fn
        self._params_fn = params_summary_fn

        self.summary = pn.pane.Markdown("", sizing_mode="stretch_width")
        self.checks_title = pn.pane.Markdown("")
        self.checks_pane = pn.pane.HTML("", sizing_mode="stretch_width")
        self.recheck_btn = pn.widgets.Button(name="重新检查", width=100)
        self.mode = pn.widgets.RadioBoxGroup(
            options={"先对齐，确认任务时段后再继续（推荐）": "align", "直接全部运行": "full"},
            value="align",
        )
        self.mode_note = pn.pane.Markdown("", styles={"font-size": "13px"})
        self.stages_pane = pn.pane.HTML("", sizing_mode="stretch_width")
        self.total_eta = pn.pane.Markdown("")
        self.start_btn = pn.widgets.Button(name="", button_type="primary", width=180)

        self.recheck_btn.on_click(lambda event: self.refresh())
        self.mode.param.watch(lambda event: self._render_mode(), "value")
        self.start_btn.on_click(lambda event: self._start_fn(self.mode.value))
        self._render_mode()

    def refresh(self) -> None:
        """Recompute summary, checks and stage estimates (on entering the step)."""
        st = self._state
        sid = st.session_id
        probes = "，".join(f"{p} {a}" for p, a in sorted((st.probe_plan or {}).items()))
        n_rec = len(st.active_recordings) if st.input_mode == "joint" else 1
        self.summary.object = (
            "#### 摘要\n\n"
            f"- Session：`{sid.canonical() if sid else '—'}`\n"
            f"- 数据：{n_rec} 段记录 · {len(st.probe_plan or {})} 探针（{probes or '—'}）\n"
            f"- 参数：{self._params_fn()}\n"
            f"- 输出：`{st.output_dir or '—'}`"
        )
        self._render_checks()
        self._render_stages()

    def _render_checks(self) -> None:
        try:
            results = list(self._checks_fn())
        except Exception as exc:  # noqa: BLE001 — a broken check must not hide the page
            results = []
            self.checks_title.object = f"#### 运行前检查\n检查本身出错：{exc}"
        counts = {k: sum(r.status == k for r in results) for k in ("pass", "warn", "fail")}
        parts = [f"{counts['pass']} 项通过"]
        if counts["warn"]:
            parts.append(f"{counts['warn']} 项提醒")
        if counts["fail"]:
            parts.append(f"{counts['fail']} 项未通过")
        if results:
            self.checks_title.object = "#### 运行前检查 · " + " · ".join(parts)
        rows = []
        for r in results:
            icon, bg, fg = _CHECK_ICONS.get(r.status, _CHECK_ICONS["warn"])
            rows.append(
                '<div style="display:flex;gap:10px;align-items:flex-start;margin:6px 0">'
                f'<span style="width:22px;height:22px;border-radius:50%;background:{bg};'
                f'color:{fg};display:grid;place-items:center;font-size:12px">{icon}</span>'
                f'<div><div style="font-weight:500">{html.escape(r.name)}</div>'
                f'<div style="font-size:12px;color:#5B606B">{html.escape(r.message)}</div></div>'
                "</div>"
            )
        self.checks_pane.object = "".join(rows)
        self.start_btn.disabled = counts["fail"] > 0

    def _render_stages(self) -> None:
        from pynpxpipe.pipelines.constants import STAGE_ORDER
        from pynpxpipe.pipelines.estimates import format_duration

        selected = set(self._state.selected_stages or STAGE_ORDER)
        cells, total, known = [], 0.0, True
        for stage in STAGE_ORDER:
            if stage not in selected:
                cells.append((stage, "跳过", True))
                continue
            eta = self._eta_fn(stage)
            if eta is None:
                known = False
            else:
                total += eta
            cells.append((stage, format_duration(eta) if eta is not None else "—", False))
        self.stages_pane.object = (
            '<div style="display:flex;flex-wrap:wrap;gap:8px">'
            + "".join(
                '<span style="font-family:monospace;padding:6px 10px;border-radius:8px;'
                f'border:1px solid #D6D6D0;{"color:#8A8F99;background:#F6F6F3" if off else ""}">'
                f'{stage} <span style="color:#5B606B">{eta}</span></span>'
                for stage, eta, off in cells
            )
            + "</div>"
        )
        self.total_eta.object = f"预计 {format_duration(total)}" if known and total else ""

    def _render_mode(self) -> None:
        self.mode_note.object = _MODE_NOTES[self.mode.value]
        self.start_btn.name = "开始对齐" if self.mode.value == "align" else "开始全部运行"

    def panel(self) -> pn.viewable.Viewable:
        """Return the step-4 layout."""
        return pn.Row(
            pn.Column(
                self.summary,
                pn.Row(self.checks_title, self.recheck_btn),
                self.checks_pane,
                sizing_mode="stretch_width",
            ),
            pn.Column(
                pn.pane.Markdown("#### 怎么运行\n已完成的阶段会根据检查点自动跳过。"),
                self.mode,
                self.mode_note,
                pn.Row(pn.pane.Markdown("#### 将执行的阶段"), self.total_eta),
                self.stages_pane,
                pn.pane.Markdown(
                    "merge 是否运行由参数「Auto-Merge」决定。阶段依赖会自动检查。",
                    styles={"font-size": "12px", "color": "#5B606B"},
                ),
                self.start_btn,
                sizing_mode="stretch_width",
            ),
            sizing_mode="stretch_width",
        )
