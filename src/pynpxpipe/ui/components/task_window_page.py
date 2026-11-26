"""ui/components/task_window_page.py — Confirm task windows (ui_redesign.md §4.3 P1-4).

After an align-first run pauses at select_segments, this page shows the saved
selection, lets the user try other gap/padding values (computed in memory with
``TimelineData.select`` → ``core.segments.select_task_windows``, no raw reads),
and either applies them (rewrite the selection) or confirms and continues.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from pathlib import Path

import panel as pn

from pynpxpipe.core.config import TaskWindowConfig
from pynpxpipe.core.segments import Segment, SegmentManifest
from pynpxpipe.ui.components.task_timeline import TaskTimeline, TimelineData
from pynpxpipe.ui.state import AppState

# Slider ranges, docs/specs/ui_redesign.md §5 (widened to include a saved value).
_IDLE_RANGE = (30, 600, 10)
_PAD_RANGE = (0, 120, 5)
_LISTED_GAP_S = 30.0


def _slider(name: str, value: float, start: float, end: float, step: float):
    return pn.widgets.EditableFloatSlider(
        name=name,
        value=float(value),
        start=min(start, value),
        end=max(end, value),
        step=step,
        width=320,
    )


def _blocks(segments: list[Segment]) -> list[tuple[float, float]]:
    return [(s.time(s.start_frame), s.time(s.stop_frame)) for s in segments]


class TaskWindowPage:
    """Task-window preview, live what-if and the apply / confirm decision.

    Args:
        state: Shared AppState (its pipeline_config holds the saved parameters).
        apply_fn: Receives the proposed TaskWindowConfig to write and re-select.
        confirm_fn: Accept the saved selection and continue with preprocess.
        later_fn: Leave the page without deciding.
        eta_fn: Estimated sort seconds for a kept duration, or None.
    """

    def __init__(
        self,
        state: AppState,
        *,
        apply_fn: Callable[[TaskWindowConfig], None],
        confirm_fn: Callable[[], None],
        later_fn: Callable[[], None],
        eta_fn: Callable[[float], float | None] | None = None,
    ) -> None:
        self._state = state
        self._apply_fn = apply_fn
        self._eta_fn = eta_fn or (lambda kept: None)
        self._data: TimelineData | None = None
        self._saved_cfg: TaskWindowConfig | None = None
        self._syncing = False

        self.message = pn.pane.Alert("", alert_type="warning", visible=False)
        self.status = pn.pane.HTML("")
        self.metrics = pn.pane.Markdown("", sizing_mode="stretch_width")
        self.timeline = TaskTimeline()
        self.idle = _slider("最大连续空闲 max_idle_s（秒）", 180, *_IDLE_RANGE)
        self.pre = _slider("任务前保留 padding_before_s（秒）", 30, *_PAD_RANGE)
        self.post = _slider("任务后保留 padding_after_s（秒）", 30, *_PAD_RANGE)
        self.gaps = pn.pane.Markdown("", styles={"font-size": "13px"})
        self.comparison = pn.pane.Markdown("", sizing_mode="stretch_width")
        self.coverage = pn.pane.Alert("", alert_type="success")
        self.footer_note = pn.pane.Markdown("")
        self.revert_btn = pn.widgets.Button(name="恢复已保存参数")
        self.apply_btn = pn.widgets.Button(name="应用试算", button_type="primary")
        self.later_btn = pn.widgets.Button(name="稍后再确认")
        self.confirm_btn = pn.widgets.Button(name="确认并继续 preprocess", button_type="primary")

        for slider in (self.idle, self.pre, self.post):
            slider.param.watch(self._on_slider, "value_throttled")
        self.revert_btn.on_click(lambda event: self._revert())
        self.apply_btn.on_click(lambda event: self._apply_fn(self.current_config()))
        self.later_btn.on_click(lambda event: later_fn())
        self.confirm_btn.on_click(lambda event: confirm_fn())
        self._set_dirty(False)

    # ── Loading ──

    def load(self, output_dir: str | Path) -> None:
        """Read the saved preview of *output_dir* and show it."""
        from pynpxpipe.pipelines.run_state import TASK_WINDOW_PENDING_FILE

        root = Path(output_dir)
        try:
            summary = json.loads((root / "03_segments" / "summary.json").read_text("utf-8"))
            manifest = SegmentManifest.load(root / "03_segments" / "segments.json")
            data = TimelineData.load(root, manifest, summary)
        except (OSError, ValueError, KeyError) as exc:
            self.message.object = f"没有可用的任务时段预览：{exc}"
            self.message.visible = True
            return
        cfg = self._state.pipeline_config.task_windows if self._state.pipeline_config else None
        marker = root / "checkpoints" / TASK_WINDOW_PENDING_FILE
        paused = None
        if marker.exists():
            import time

            try:
                paused = time.time() - json.loads(marker.read_text("utf-8"))["marked_at"]
            except (OSError, ValueError, KeyError):
                paused = 0.0
        self.show(data, summary, cfg or TaskWindowConfig(enabled=True), paused_s=paused)

    def show(
        self,
        data: TimelineData,
        summary: dict,
        saved_cfg: TaskWindowConfig,
        *,
        paused_s: float | None = None,
    ) -> None:
        """Display *data* with *saved_cfg* as the saved parameters."""
        self.message.visible = False
        self._data, self._saved_cfg = data, saved_cfg
        if paused_s is None:
            self.status.object = ""
        else:
            self.status.object = (
                '<span style="padding:4px 12px;border-radius:999px;background:#FBF0DA;'
                f'color:#7A4D00">等你确认 · 已暂停 {paused_s / 60:.0f} min</span>'
            )
        n_trials = int(summary.get("n_trials", len(data.trials)))
        n_empty = int(summary.get("n_empty_trials", 0))
        compatible = summary.get("joint_sorting_compatible", True)
        self.metrics.object = (
            "| trial 对齐 | 最大同步残差 | 有刺激 trial | 空 trial（不计入任务） | 探针元数据 |\n"
            "|---|---|---|---|---|\n"
            f"| {n_trials + n_empty} | {summary.get('max_sync_residual_ms', float('nan')):.3f} ms "
            f"| {n_trials} | {n_empty} | {'兼容' if compatible else '不兼容'} |"
        )
        self._syncing = True
        try:
            for slider, value, (start, end, step) in (
                (self.idle, saved_cfg.max_idle_s, _IDLE_RANGE),
                (self.pre, saved_cfg.padding_before_s, _PAD_RANGE),
                (self.post, saved_cfg.padding_after_s, _PAD_RANGE),
            ):
                slider.param.update(start=min(start, value), end=max(end, value), step=step)
                slider.value = float(value)
        finally:
            self._syncing = False
        self.timeline.show(data, saved_cfg)
        self._recompute()

    # ── What-if ──

    def current_config(self) -> TaskWindowConfig:
        """Saved config with the slider values substituted."""
        base = self._saved_cfg or TaskWindowConfig(enabled=True)
        return dataclasses.replace(
            base,
            max_idle_s=float(self.idle.value),
            padding_before_s=float(self.pre.value),
            padding_after_s=float(self.post.value),
        )

    def _on_slider(self, event) -> None:
        if not self._syncing and self._data is not None:
            self.timeline.update(self.current_config())
            self._recompute()

    def _revert(self) -> None:
        if self._saved_cfg is None:
            return
        self._syncing = True
        try:
            self.idle.value = float(self._saved_cfg.max_idle_s)
            self.pre.value = float(self._saved_cfg.padding_before_s)
            self.post.value = float(self._saved_cfg.padding_after_s)
        finally:
            self._syncing = False
        self.timeline.update(self._saved_cfg)
        self._recompute()

    def _recompute(self) -> None:
        data, cfg = self._data, self.current_config()
        try:
            candidate = data.select(cfg)
        except ValueError as exc:
            self.comparison.object = f"**当前参数无法试算：** {exc}"
            return
        saved_blocks, cand_blocks = _blocks(data.saved), _blocks(candidate)
        original = sum(s.duration for s in data.sources)
        stats = []
        for blocks in (saved_blocks, cand_blocks):
            kept = sum(b - a for a, b in blocks)
            eta = self._eta_fn(kept)
            stats.append(
                (
                    str(len(blocks)),
                    f"{kept / 60:.1f} min",
                    f"{100 * (1 - kept / original):.0f}%" if original else "—",
                    f"{eta / 60:.0f} min" if eta is not None else "—",
                )
            )
        labels = ("任务块", "保留时长", "比原始减少", "预计 sort 用时")
        table = ["| | 已保存 | 当前试算 |", "|---|---|---|"]
        table += [f"| {label} | {s} | {c} |" for label, s, c in zip(labels, *stats, strict=True)]
        table += ["", "| # | 开始 | 结束 | 时长 |", "|---|---|---|---|"]
        table += [
            f"| {i + 1} | {a / 60:.1f} min | {b / 60:.1f} min | {(b - a) / 60:.1f} min |"
            for i, (a, b) in enumerate(cand_blocks)
        ]
        self.comparison.object = "\n".join(table)

        trials = data.trials
        missing = [
            key
            for key, start, stop in zip(
                trials.trial_key, trials.start_time, trials.stop_time, strict=True
            )
            if not any(a <= start and stop <= b for a, b in cand_blocks)
        ]
        if missing:
            self.coverage.alert_type = "danger"
            self.coverage.object = (
                f"{len(missing)} 个有刺激 trial 不在保留区内：{', '.join(missing)}"
            )
        else:
            self.coverage.alert_type = "success"
            self.coverage.object = f"全部 {len(trials)} 个有刺激 trial 都在保留区内。"

        gap_lines = []
        for source_id, rows_ in trials.sort_values("start_time").groupby("source_id"):
            stops, starts = rows_.stop_time.to_numpy()[:-1], rows_.start_time.to_numpy()[1:]
            for stop, start in zip(stops, starts, strict=True):
                if start - stop <= _LISTED_GAP_S:
                    continue
                mid = (start + stop) / 2
                kept = any(a <= mid <= b for a, b in cand_blocks)
                gap_lines.append(
                    f"- {source_id}：{(start - stop) / 60:.1f} min 间隙 → {'保留' if kept else '切开'}"
                )
        self.gaps.object = "\n".join(gap_lines) or "没有长于 30 s 的 trial 间隙。"
        self._set_dirty(self._differs(cfg))

    def _differs(self, cfg: TaskWindowConfig) -> bool:
        saved = self._saved_cfg
        if saved is None:
            return False
        return (cfg.max_idle_s, cfg.padding_before_s, cfg.padding_after_s) != (
            saved.max_idle_s,
            saved.padding_before_s,
            saved.padding_after_s,
        )

    def _set_dirty(self, dirty: bool) -> None:
        self.revert_btn.visible = self.apply_btn.visible = dirty
        self.later_btn.visible = self.confirm_btn.visible = not dirty
        self.footer_note.object = (
            "试算与已保存选区不同。应用后会重写选区和时间映射（不重新对齐）。"
            if dirty
            else "当前就是已保存的选区。拖动参数可以试算其他方案。"
        )

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        """Return the page layout."""
        return pn.Column(
            pn.Row(
                pn.pane.Markdown(
                    "## 确认任务时段\n对齐已完成，流程暂停在 select_segments。"
                    "只有保留区内的数据会进入 preprocess 和 sort。"
                ),
                pn.layout.HSpacer(),
                self.status,
                sizing_mode="stretch_width",
            ),
            self.message,
            self.metrics,
            self.timeline.layout,
            pn.Row(
                pn.Column(
                    pn.pane.Markdown("#### 调整参数\n松手即时试算，不读原始数据。"),
                    self.idle,
                    self.gaps,
                    self.pre,
                    self.post,
                ),
                pn.Column(
                    pn.pane.Markdown("#### 试算结果"),
                    self.comparison,
                    self.coverage,
                    sizing_mode="stretch_width",
                ),
                sizing_mode="stretch_width",
            ),
            pn.Row(
                self.footer_note,
                pn.layout.HSpacer(),
                self.revert_btn,
                self.apply_btn,
                self.later_btn,
                self.confirm_btn,
                sizing_mode="stretch_width",
            ),
            sizing_mode="stretch_width",
        )
