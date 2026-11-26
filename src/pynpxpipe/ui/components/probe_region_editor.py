"""ui/components/probe_region_editor.py — Probe -> target_area declaration.

Manages ``state.probe_plan: dict[str, str]``. Each row is one probe id paired
with a free-text brain region. Rows can be added/removed. Empty regions are
allowed during editing but block the session_id derivation on AppState.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import panel as pn

from pynpxpipe.ui.recent_sessions import default_recent_path, load_recent
from pynpxpipe.ui.state import AppState

_PROBE_RE = re.compile(r"^imec(\d+)$")


def _subject_history(subject_id: str) -> list[dict[str, str]]:
    """probe_plan of each recent session of *subject_id*, newest first (ui_redesign §8.7)."""
    plans = []
    for entry in load_recent(default_recent_path()):
        if entry.subject_id != subject_id:
            continue
        try:
            data = json.loads((Path(entry.output_dir) / "session.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        plan = data.get("probe_plan")
        if isinstance(plan, dict):
            plans.append({str(k): str(v) for k, v in plan.items()})
    return plans


_AREA_INPUT_WIDTH = 140


def _next_probe_id(existing: list[str]) -> str:
    max_idx = -1
    for key in existing:
        match = _PROBE_RE.match(key)
        if match:
            max_idx = max(max_idx, int(match.group(1)))
    return f"imec{max_idx + 1}"


class ProbeRegionEditor:
    """Row-based editor bound to ``state.probe_plan``.

    Internal add/remove operations mutate ``_rows_col`` incrementally to
    avoid Bokeh model churn (which surfaced as "reference already known"
    warnings on full-rebuild). Full rebuild is only used when the external
    ``state.probe_plan`` keyset diverges from the visible rows.
    """

    def __init__(self, state: AppState) -> None:
        self._state = state
        self._rows_col = pn.Column(sizing_mode="stretch_width")
        self.add_btn = pn.widgets.Button(name="+ 添加探针", button_type="default")
        self.add_btn.on_click(self._on_add_click)
        self.history_hint = pn.pane.Markdown("", visible=False, styles={"font-size": "13px"})
        self._suppress_state_watch = False
        self._rebuild_rows()
        state.param.watch(self._on_state_probe_plan, "probe_plan")

    # ------------------------------------------------------------------
    # Row construction
    # ------------------------------------------------------------------

    def _rebuild_rows(self) -> None:
        self._suppress_state_watch = True
        try:
            self._rows_col.clear()
            plan = dict(self._state.probe_plan or {})
            if not plan:
                plan = {"imec0": ""}
                self._state.probe_plan = plan
            single = len(plan) == 1
            for probe_id in sorted(plan.keys(), key=self._probe_sort_key):
                self._rows_col.append(self._make_row(probe_id, plan[probe_id], single))
        finally:
            self._suppress_state_watch = False

    @staticmethod
    def _probe_sort_key(probe_id: str) -> tuple[int, str]:
        match = _PROBE_RE.match(probe_id)
        return (int(match.group(1)), probe_id) if match else (10_000, probe_id)

    def _make_row(self, probe_id: str, target_area: str, single: bool) -> pn.Row:
        probe_label = pn.widgets.StaticText(value=probe_id, width=80)
        area_input = pn.widgets.TextInput(
            placeholder="e.g. V4",
            value=target_area,
            width=_AREA_INPUT_WIDTH,
        )
        remove_btn = pn.widgets.Button(name="×", button_type="danger", width=40, disabled=single)

        def _on_area_change(event, pid=probe_id) -> None:
            if self._suppress_state_watch:
                return
            plan = dict(self._state.probe_plan or {})
            plan[pid] = event.new or ""
            self._suppress_state_watch = True
            try:
                self._state.probe_plan = plan
            finally:
                self._suppress_state_watch = False

        def _on_remove(event, pid=probe_id) -> None:
            self._remove_probe(pid)

        area_input.param.watch(_on_area_change, "value")
        remove_btn.on_click(_on_remove)

        row = pn.Row(probe_label, area_input, remove_btn)
        row._pynpx_probe_id = probe_id  # for testing
        row._pynpx_area_input = area_input
        row._pynpx_remove_btn = remove_btn
        return row

    def _update_single_flag(self) -> None:
        single = len(self._rows_col) == 1
        for row in self._rows_col:
            btn = getattr(row, "_pynpx_remove_btn", None)
            if btn is not None:
                btn.disabled = single

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_add_click(self, event) -> None:
        plan = dict(self._state.probe_plan or {})
        new_id = _next_probe_id(list(plan.keys()))
        plan[new_id] = ""
        self._suppress_state_watch = True
        try:
            self._state.probe_plan = plan
        finally:
            self._suppress_state_watch = False
        self._rows_col.append(self._make_row(new_id, "", False))
        self._update_single_flag()

    def _remove_probe(self, pid: str) -> None:
        plan = dict(self._state.probe_plan or {})
        if pid not in plan:
            return
        plan.pop(pid)
        if not plan:
            # Last probe removed → reset to blank imec0 via full rebuild.
            plan = {"imec0": ""}
            self._suppress_state_watch = True
            try:
                self._state.probe_plan = plan
            finally:
                self._suppress_state_watch = False
            self._rebuild_rows()
            return
        # Incremental remove: drop the specific row without rebuilding.
        for i, row in enumerate(list(self._rows_col)):
            if getattr(row, "_pynpx_probe_id", None) == pid:
                self._rows_col.pop(i)
                break
        self._suppress_state_watch = True
        try:
            self._state.probe_plan = plan
        finally:
            self._suppress_state_watch = False
        self._update_single_flag()

    def _on_state_probe_plan(self, event) -> None:
        if self._suppress_state_watch:
            return
        new_plan = dict(event.new or {})
        current_ids = [getattr(r, "_pynpx_probe_id", None) for r in self._rows_col]
        if sorted(current_ids) != sorted(new_plan.keys()):
            self._rebuild_rows()
            return
        for row in self._rows_col:
            pid = getattr(row, "_pynpx_probe_id", None)
            area_input = getattr(row, "_pynpx_area_input", None)
            if pid in new_plan and area_input is not None and area_input.value != new_plan[pid]:
                self._suppress_state_watch = True
                try:
                    area_input.value = new_plan[pid]
                finally:
                    self._suppress_state_watch = False

    # ------------------------------------------------------------------
    # Wizard step 2 (ui_redesign P1-3, §8.7)
    # ------------------------------------------------------------------

    def set_probes(self, probe_ids: list[str]) -> None:
        """Make the rows match the probes found in step 1, keeping typed areas."""
        if not probe_ids:
            return
        current = dict(self._state.probe_plan or {})
        self._state.probe_plan = {pid: current.get(pid, "") for pid in probe_ids}

    def prefill_from_history(self, subject_id: str) -> None:
        """Fill empty areas from this animal's latest recent session and list past areas."""
        history = _subject_history(subject_id) if subject_id else []
        if not history:
            self.history_hint.visible = False
            return
        latest = history[0]
        plan = dict(self._state.probe_plan or {})
        filled = {pid: latest[pid] for pid, area in plan.items() if not area and latest.get(pid)}
        if filled:
            self._state.probe_plan = {**plan, **filled}
        used = list(dict.fromkeys(a for p in history for a in p.values() if a))
        last = "、".join(f"{pid} = {area}" for pid, area in sorted(latest.items()))
        self.history_hint.object = (
            f"上次为 {subject_id} 填的是 {last}"
            + ("，已自动带入。" if filled else "。")
            + f" 以往用过：{'、'.join(used)}。"
        )
        self.history_hint.visible = True

    # ------------------------------------------------------------------
    # Panel
    # ------------------------------------------------------------------

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("### 探针脑区\n探针列表来自第 1 步的识别结果，只需填写脑区。"),
            self._rows_col,
            self.add_btn,
            self.history_hint,
            sizing_mode="stretch_width",
        )
