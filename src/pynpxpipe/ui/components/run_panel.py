"""ui/components/run_panel.py — Execution control panel.

Provides Run/Stop buttons, status text, and threading for pipeline execution.
The actual pipeline function is injected (for testability). In production it
calls SessionManager + PipelineRunner; tests inject a mock callable.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

import panel as pn

from pynpxpipe.ui.components.task_timeline import TaskTimeline, TimelineData
from pynpxpipe.ui.run_manager import RunManager, get_run_manager
from pynpxpipe.ui.state import AppState, ProgressBridge

if TYPE_CHECKING:
    import pandas as pd


@dataclass
class PreviewReport:
    """Formal selection summary and optional artifacts for on-screen comparison."""

    text: str
    table: pd.DataFrame | None = None
    timeline: TimelineData | None = None


class RunPanel:
    """Execution control: Run, Stop, status display.

    Args:
        state: Shared AppState instance.
        pipeline_fn: Callable(state, bridge) executed in a background thread.
            If None, defaults to a no-op (useful for layout-only testing).
        preview_fn: Optional alignment and task selection callable.
        bridge: Shares the active browser document with the log handlers.
    """

    def __init__(
        self,
        state: AppState,
        pipeline_fn: Callable[[AppState, ProgressBridge], None] | None = None,
        preview_fn: Callable[[AppState, ProgressBridge], None] | None = None,
        bridge: ProgressBridge | None = None,
        tuning_controls: list[pn.widgets.Widget] | None = None,
        run_manager: RunManager | None = None,
    ) -> None:
        self._state = state
        self._run_manager = run_manager or get_run_manager()
        self._pipeline_fn = pipeline_fn or (lambda st, br: None)
        self._preview_fn = preview_fn
        self._bridge = bridge or ProgressBridge(state)
        self._thread: threading.Thread | None = None
        self._interrupt = threading.Event()
        self._preview_key: tuple | None = None

        # ── Widgets ──
        self.run_btn = pn.widgets.Button(name="Run", button_type="primary")
        self.stop_btn = pn.widgets.Button(name="Stop", button_type="danger", disabled=True)
        self.preview_btn = pn.widgets.Button(
            name="对齐并预览任务时段", visible=preview_fn is not None
        )
        self.preview_result = pn.pane.Markdown("尚未加载任务时段预览。")
        self.preview_table = pn.pane.DataFrame(visible=False, max_rows=100)
        self.details = pn.Accordion(
            ("已保存的保留区间（秒）", self.preview_table), active=[], visible=False
        )
        self.refresh_btn = pn.widgets.Button(name="刷新试算", icon="refresh")
        self.refresh_btn.on_click(self._on_refresh_click)
        self.timeline = TaskTimeline([*(tuning_controls or []), self.refresh_btn])
        self.status_text = pn.pane.Str("Status: idle", styles={"font-size": "14px"})
        self.validation_alert = pn.pane.Alert(
            "", alert_type="danger", visible=False, sizing_mode="stretch_width"
        )

        # ── Wire events ──
        self.run_btn.on_click(self._on_run_click)
        self.stop_btn.on_click(self._on_stop_click)
        self.preview_btn.on_click(self._on_preview_click)

        # Watch run_status for button enable/disable and status text
        state.param.watch(self._on_status_change, ["run_status"])
        state.param.watch(
            self._on_preview_inputs,
            [
                "pipeline_config",
                "input_mode",
                "session_dir",
                "bhv_file",
                "recordings",
                "output_dir",
            ],
        )

    def _alignment_key(self) -> tuple:
        st = self._state
        cfg = st.pipeline_config
        pairs = (
            tuple(
                (
                    row["source_id"],
                    str(row["session_dir"]),
                    str(row["bhv_file"]),
                    row.get("start_offset_s"),
                )
                for row in st.active_recordings
            )
            if st.input_mode == "joint"
            else (str(st.session_dir), str(st.bhv_file))
        )
        return (
            st.input_mode,
            str(st.output_dir),
            pairs,
            cfg.sync if cfg else None,
            cfg.task_windows.recording_timezone if cfg else None,
            cfg.task_windows.trial_start_code if cfg else None,
        )

    def _on_preview_inputs(self, event) -> None:
        if self._preview_key is None:
            return
        if self._preview_key != self._alignment_key():
            self._clear_preview()
            self.preview_result.object = "输入或同步设置已改变，请重新执行对齐预览。"
        elif self.timeline.data is not None:
            self.timeline.update(self._state.pipeline_config.task_windows)

    def _clear_preview(self) -> None:
        self._preview_key = None
        self.preview_result.object = ""
        self.preview_table.visible = self.details.visible = False
        self.preview_table.object = None
        self.timeline.clear()

    def _show_report(self, report: PreviewReport) -> None:
        self.preview_result.object = report.text
        self.preview_table.object = report.table
        self.preview_table.visible = self.details.visible = report.table is not None
        if report.timeline is not None and self._state.pipeline_config is not None:
            try:
                self.timeline.show(report.timeline, self._state.pipeline_config.task_windows)
            except Exception as exc:
                logging.getLogger(__name__).exception("Cannot render task timeline")
                self.timeline.clear()
                self.preview_result.object += f"\n\n**时间轴不可用**：{exc}"

    def load_saved_preview(self) -> None:
        """Restore an existing selection on session load, without invoking the runner."""
        self._clear_preview()
        if not self._state.output_dir:
            return
        root = Path(self._state.output_dir)
        if not (root / "03_segments" / "summary.json").is_file():
            self.preview_result.object = (
                "此输出目录没有任务时段预览：缺少 `03_segments/summary.json`。"
            )
            if any((root / ".invalidated").glob("*/03_segments/summary.json")):
                self.preview_result.object += " 在 `.invalidated` 中找到了已归档的预览。"
            return
        try:
            self._show_report(self._read_preview(root))
            self._preview_key = self._alignment_key()
        except (OSError, KeyError, ValueError) as exc:
            self.preview_result.object = f"无法读取已保存的预览：{exc}"

    def _validate_before_run(self) -> str | None:
        """Null-check the NWB filename fields. Returns an error message or None."""
        st = self._state
        if st.subject_config is None:
            return "Please fill in Subject information."
        if st.input_mode == "joint" and len(st.active_recordings) < 2:
            return "多段联合模式需要至少两组已保存的神经–行为配对。"
        if not st.active_session_dir:
            return "Data directory is invalid or missing."
        if not st.output_dir:
            return "Output directory is required."
        if not st.experiment or not st.experiment.strip():
            return "Experiment name is required."
        if not st.recording_date or not st.recording_date.strip():
            return "Recording date is required. Click 'Detect Date' or enter manually."
        if not st.probe_plan:
            return "At least one probe must be declared."
        if any(not (v and v.strip()) for v in st.probe_plan.values()):
            return "All probe target areas must be non-empty."
        return None

    def _on_run_click(self, event, *, preview: bool = False) -> None:
        """Start pipeline in background thread (ignored if already running)."""
        if self._state.execution_busy:
            return

        self._clear_preview()
        error = self._validate_before_run()
        if error is None and self._run_manager.is_running(self._state.output_dir):
            error = "该输出目录正在运行（可能来自另一个浏览器窗口），请到首页查看进度。"
        if error:
            self.validation_alert.object = error
            self.validation_alert.alert_type = "danger"
            self.validation_alert.visible = True
            return
        self.validation_alert.visible = False
        if preview:
            self._preview_key = self._alignment_key()

        self._state.run_status = "running"
        self._state.stage_progress = 0.0
        self._state.current_stage = ""
        self._state.error_message = ""
        self._state.stage_statuses = {}
        self._state.safe_to_exit = False

        self._bridge.bind_document(pn.state.curdoc)
        stages = (
            ["discover", "synchronize", "select_segments"]
            if preview
            else list(self._state.selected_stages)
        )
        try:
            handle = self._run_manager.start(
                Path(self._state.output_dir),
                lambda callback, interrupt: self._run_wrapper(preview, callback),
                stages,
                final_status="awaiting_confirmation" if preview else "completed",
            )
        except (OSError, RuntimeError) as exc:
            self._finish_run(preview, None, str(exc))
            return
        if handle is None:
            self._finish_run(preview, None, "该输出目录已有运行中的任务。")
            return
        self._thread, self._interrupt = handle.thread, handle.interrupt

    def start(self, *, preview: bool) -> None:
        """Start a run: alignment preview (pauses for task-window confirmation) or full."""
        self._on_run_click(None, preview=preview)

    def _on_preview_click(self, event) -> None:

        if self._preview_fn is not None:
            self._on_run_click(event, preview=True)

    def _on_refresh_click(self, event) -> None:
        if self.timeline.data is not None and self._state.pipeline_config is not None:
            self.timeline.update(self._state.pipeline_config.task_windows)

    def _on_stop_click(self, event) -> None:
        """Ask the run to stop when its next stage starts (ui_redesign §8.2)."""
        self._interrupt.set()

    def _run_wrapper(self, preview: bool, callback=None) -> None:
        """Perform work and read preview artifacts off the UI thread.

        ``callback`` (from RunManager) records progress in run_state.json; errors are
        re-raised after the UI update so the registry records the failure too.
        """
        result = None
        error = None
        raised: BaseException | None = None
        self._bridge.set_listener(callback)
        try:
            if preview and self._preview_fn:
                output_dir = Path(self._state.output_dir)
                self._preview_fn(self._state, self._bridge)
                result = self._read_preview(output_dir)
            else:
                self._pipeline_fn(self._state, self._bridge)
            if self._interrupt.is_set():
                error = "Interrupted by user"
        except Exception as exc:  # noqa: BLE001
            error = str(exc) or type(exc).__name__
            raised = exc
        finally:
            self._bridge.set_listener(None)
        self._bridge.dispatch(partial(self._finish_run, preview, result, error))
        if raised is not None:
            raise raised

    def _finish_run(self, preview: bool, result: PreviewReport | None, error: str | None) -> None:
        self._bridge.release_document()
        if error is not None:
            self._state.error_message = error
            stage = self._state.current_stage
            if self._state.stage_statuses.get(stage) == "running":
                self._state.stage_statuses = {**self._state.stage_statuses, stage: "failed"}
            self._state.run_status = "failed"
            return
        if result is not None and self._preview_key == self._alignment_key():
            self._show_report(result)
        self._state.safe_to_exit = not preview
        self._state.run_status = "completed"

    @staticmethod
    def _read_preview(output_dir: Path) -> PreviewReport:
        import json

        import pandas as pd

        from pynpxpipe.core.segments import SegmentManifest

        root = output_dir / "03_segments"
        if not (root / "summary.json").exists():
            return PreviewReport("未启用截取：将处理完整记录。")
        info = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        reduction = 100 * (1 - info["retained_duration_s"] / info["original_duration_s"])
        text = (
            f"{info['n_sources']} 段记录，{info['n_blocks']} 个任务块。"
            f"原始 {info['original_duration_s']:.1f} s → 保留 {info['retained_duration_s']:.1f} s，减少 {reduction:.1f}%。"
            f"最大同步残差 {info['max_sync_residual_ms']:.3f} ms。"
        )
        if "n_empty_trials" in info:
            text += (
                f" 有刺激的 trial：{info['n_trials']} 个；空 trial：{info['n_empty_trials']} 个。"
            )
        else:
            text += f" 蓝色为旧版按全部 {info['n_trials']} 个 trial 保存的选区。"
        if info.get("joint_sorting_compatible") is False:
            text += (
                "\n\n**对齐预览已完成，联合 sorting 尚不能执行：** " + info["joint_sorting_error"]
            )
        elif info.get("n_sources", 1) > 1:
            text += "\n\n探针元数据兼容检查通过；联合预处理时还会核对实际通道配置。"
        manifest = SegmentManifest.load(root / "segments.json")
        if info["signature"] != manifest.signature:
            raise ValueError("时段摘要与选区不匹配，请重新执行对齐预览。")
        table = pd.DataFrame(
            [
                {
                    "source": s.source_id,
                    "start_s": s.time(s.start_frame),
                    "stop_s": s.time(s.stop_frame),
                    "duration_s": s.length / s.sample_rate,
                }
                for s in manifest.for_probe("imec0")
            ]
        )
        report = PreviewReport("**已保存的正式预览**：" + text, table)
        try:
            report.timeline = TimelineData.load(output_dir, manifest, info)
        except (OSError, ValueError, KeyError) as exc:
            report.text += f"\n\n**时间轴不可用**：{exc}"
        return report

    def _on_status_change(self, event) -> None:
        """Update button states and status text when run_status changes."""
        status = event.new
        self.run_btn.disabled = self._state.execution_busy
        self.preview_btn.disabled = self._state.execution_busy
        self.stop_btn.disabled = status != "running"

        labels = {
            "idle": "Status: idle",
            "running": "Status: running",
            "checking_export": "正在检查 NWB 导出条件",
            "exporting": "正在续跑 NWB 导出",
            "completed": "Status: completed",
            "failed": f"Status: failed — {self._state.error_message}",
        }
        self.status_text.object = labels.get(status, f"Status: {status}")

    def panel(self, restore_form: pn.viewable.Viewable | None = None) -> pn.viewable.Viewable:
        """Return the Panel layout for this component."""
        return pn.Column(
            pn.Row(self.run_btn, self.stop_btn, self.preview_btn),
            self.status_text,
            self.validation_alert,
            pn.pane.Markdown("### 任务时段时间轴"),
            *([restore_form] if restore_form is not None else []),
            self.preview_result,
            self.timeline.layout,
            self.details,
            sizing_mode="stretch_width",
        )
