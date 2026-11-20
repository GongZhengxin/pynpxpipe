"""ui/components/run_panel.py — Execution control panel.

Provides Run/Stop buttons, status text, and threading for pipeline execution.
The actual pipeline function is injected (for testability). In production it
calls SessionManager + PipelineRunner; tests inject a mock callable.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

import panel as pn

from pynpxpipe.ui.state import AppState, ProgressBridge


class RunPanel:
    """Execution control: Run, Stop, status display.

    Args:
        state: Shared AppState instance.
        pipeline_fn: Callable(state, bridge) executed in a background thread.
            If None, defaults to a no-op (useful for layout-only testing).
    """

    def __init__(
        self,
        state: AppState,
        pipeline_fn: Callable[[AppState, ProgressBridge], None] | None = None,
        preview_fn: Callable[[AppState, ProgressBridge], None] | None = None,
    ) -> None:
        self._state = state
        self._pipeline_fn = pipeline_fn or (lambda st, br: None)
        self._preview_fn = preview_fn
        self._preview_mode = False
        self._bridge = ProgressBridge(state)
        self._thread: threading.Thread | None = None
        self._interrupt = threading.Event()

        # ── Widgets ──
        self.run_btn = pn.widgets.Button(name="Run", button_type="primary")
        self.stop_btn = pn.widgets.Button(name="Stop", button_type="danger", disabled=True)
        self.preview_btn = pn.widgets.Button(
            name="对齐并预览任务时段", visible=preview_fn is not None
        )
        self.preview_result = pn.pane.Markdown("")
        self.preview_table = pn.pane.DataFrame(visible=False, max_rows=100)
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

    def _on_run_click(self, event) -> None:
        """Start pipeline in background thread (ignored if already running)."""
        if self._state.run_status == "running":
            return

        error = self._validate_before_run()
        if error:
            self.validation_alert.object = error
            self.validation_alert.alert_type = "danger"
            self.validation_alert.visible = True
            return
        self.validation_alert.visible = False

        self._state.run_status = "running"
        self._state.stage_progress = 0.0
        self._state.current_stage = ""
        self._state.error_message = ""
        self._state.stage_statuses = {}
        self._state.safe_to_exit = False
        self._interrupt.clear()

        self._thread = threading.Thread(target=self._run_wrapper, daemon=True)
        self._thread.start()

    def _on_preview_click(self, event) -> None:
        if self._state.run_status == "running":
            return
        self._preview_mode = True
        self._on_run_click(event)
        if self.validation_alert.visible:
            self._preview_mode = False

    def _on_stop_click(self, event) -> None:
        """Set interrupt flag to signal the pipeline to stop."""
        self._interrupt.set()

    def _run_wrapper(self) -> None:
        """Execute pipeline_fn and update state on completion or failure."""
        try:
            if self._preview_mode and self._preview_fn:
                self._preview_fn(self._state, self._bridge)
                self._load_preview()
            else:
                self._pipeline_fn(self._state, self._bridge)
            if not self._interrupt.is_set():
                self._state.run_status = "completed"
                # Phase 3 (raw export + bit-exact verify) blocks inside
                # ExportStage with wait_for_raw=True, so when we land here
                # the NWB is fully written and verified: window-close safe.
                self._state.safe_to_exit = not self._preview_mode
            else:
                self._state.run_status = "failed"
                self._state.error_message = "Interrupted by user"
        except Exception as exc:  # noqa: BLE001
            self._state.error_message = str(exc)
            self._state.run_status = "failed"
        finally:
            self._preview_mode = False

    def _load_preview(self) -> None:
        import json
        from pathlib import Path

        import pandas as pd

        from pynpxpipe.core.segments import SegmentManifest

        root = Path(self._state.output_dir) / "03_segments"
        if not (root / "summary.json").exists():
            self.preview_result.object = "未启用截取：将处理完整记录。"
            return
        info = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        reduction = 100 * (1 - info["retained_duration_s"] / info["original_duration_s"])
        self.preview_result.object = (
            f"{info['n_sources']} 段记录，{info['n_trials']} 个试次，{info['n_blocks']} 个任务块。"
            f"原始 {info['original_duration_s']:.1f} s → 保留 {info['retained_duration_s']:.1f} s，减少 {reduction:.1f}%。"
            f"最大同步残差 {info['max_sync_residual_ms']:.3f} ms。"
        )
        if info.get("joint_sorting_compatible") is False:
            self.preview_result.object += (
                "\n\n**对齐预览已完成，联合 sorting 尚不能执行：** " + info["joint_sorting_error"]
            )
        elif info.get("n_sources", 1) > 1:
            self.preview_result.object += (
                "\n\n探针元数据兼容检查通过；联合预处理时还会核对实际通道配置。"
            )
        manifest = SegmentManifest.load(root / "segments.json")
        self.preview_table.object = pd.DataFrame(
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
        self.preview_table.visible = True

    def _on_status_change(self, event) -> None:
        """Update button states and status text when run_status changes."""
        status = event.new
        self.run_btn.disabled = status == "running"
        self.preview_btn.disabled = status == "running"
        self.stop_btn.disabled = status != "running"

        labels = {
            "idle": "Status: idle",
            "running": "Status: running",
            "completed": "Status: completed",
            "failed": f"Status: failed — {self._state.error_message}",
        }
        self.status_text.object = labels.get(status, f"Status: {status}")

    def panel(self) -> pn.viewable.Viewable:
        """Return the Panel layout for this component."""
        return pn.Column(
            pn.Row(self.run_btn, self.stop_btn, self.preview_btn),
            self.status_text,
            self.validation_alert,
            self.preview_result,
            self.preview_table,
        )
