"""Execute controls for resuming NWB export from a saved segmented session."""

from __future__ import annotations

import threading
from functools import partial
from pathlib import Path

import panel as pn

from pynpxpipe.ui.components.browsable_input import BrowsableInput
from pynpxpipe.ui.state import AppState, ProgressBridge


class ResumeExportPanel:
    def __init__(self, state: AppState, bridge: ProgressBridge) -> None:
        self._state = state
        self._bridge = bridge
        self._revision = 0
        self._checked = None
        self._thread: threading.Thread | None = None

        self.output = BrowsableInput("已保存的输出目录", "包含 session.json 的那一层", wrap=True)
        self.vault = BrowsableInput(
            "刺激表目录", "包含原始刺激表和 manifest.tsv 的文件夹", wrap=True
        )
        self.recorded = pn.widgets.TextAreaInput(
            name="旧版记录：当时配置的图片库路径（按原顺序，每行一个）",
            visible=False,
            sizing_mode="stretch_width",
        )
        self.check_btn = pn.widgets.Button(name="检查导出条件", icon="list-check")
        self.export_btn = pn.widgets.Button(
            name="仅继续 NWB 导出", icon="file-export", button_type="primary", disabled=True
        )
        self.message = pn.pane.Alert("请选择两个目录。", alert_type="light")
        self.detail = pn.pane.Str(
            "", visible=False, styles={"white-space": "pre-wrap", "overflow-wrap": "anywhere"}
        )
        self.progress = pn.indicators.Progress(value=0, visible=False, sizing_mode="stretch_width")
        for widget in (self.output.text_input, self.vault.text_input, self.recorded):
            widget.param.watch(self._invalidate, "value")
            widget.param.watch(self._on_typing, "value_input")
        self.check_btn.on_click(lambda _: self._start(check=True))
        self.export_btn.on_click(lambda _: self._start(check=False))
        state.param.watch(self._on_status, "run_status")
        self._set_controls()

    def _inputs(self) -> tuple[str, str, tuple[str, ...]]:
        def clean(text):
            return text.strip().strip('"')

        return (
            clean(self.output.value),
            clean(self.vault.value),
            tuple(clean(s) for s in self.recorded.value.splitlines() if clean(s)),
        )

    @staticmethod
    def _on_typing(event) -> None:
        # Enable Check immediately after a paste, before focus leaves the path field.
        event.obj.value = event.new

    def _invalidate(self, event) -> None:
        self._revision += 1
        self._checked = None
        if not self._state.execution_busy:
            self._show("目录已改变，请检查导出条件。", "light")
            self.progress.visible = False
        self._set_controls()

    def _on_status(self, event) -> None:
        if event.new == "running" and self._checked is not None:
            self._invalidate(event)
            self._show("常规任务已启动；结束后请重新检查导出条件。", "light")
        self._set_controls()

    def _set_controls(self) -> None:
        busy = self._state.execution_busy
        inputs = self._inputs()
        self.check_btn.disabled = busy or not all(inputs[:2])
        self.export_btn.disabled = busy or self._checked != inputs
        for picker in (self.output, self.vault):
            for widget in (
                picker.text_input,
                picker.browse_btn,
                picker.drive_select,
                picker.file_selector,
            ):
                if widget is not None:
                    widget.disabled = busy
        self.recorded.disabled = busy

    def _show(self, text: str, level: str, detail: str = "") -> None:
        self.message.alert_type = level
        self.message.object = text
        self.detail.object = detail
        self.detail.visible = bool(detail)

    def _start(self, *, check: bool) -> None:
        inputs = self._inputs()
        if (
            self._state.execution_busy
            or not all(inputs[:2])
            or (not check and inputs != self._checked)
        ):
            return
        revision = self._revision
        self._checked = None
        self._state.safe_to_exit = False
        self._state.error_message = ""
        self._state.run_status = "checking_export" if check else "exporting"
        self.progress.value = -1
        self.progress.visible = True
        self._show(
            "正在检查已保存的后处理结果和各段刺激表……" if check else "正在准备 NWB 导出……", "info"
        )
        self._bridge.bind_document(pn.state.curdoc)

        def work():
            try:
                from pynpxpipe.pipelines.resume_export import resume_export

                out, vault, recorded = inputs
                if not (Path(out) / "session.json").is_file():
                    raise ValueError("输出目录里找不到 session.json，请选择上次运行的输出根目录。")
                if not Path(vault).is_dir():
                    raise ValueError("找不到刺激表目录，请选择处理电脑能访问的文件夹。")
                path = resume_export(
                    Path(out),
                    [Path(vault)],
                    recorded_vaults=[Path(s) for s in recorded],
                    check_only=check,
                    progress_callback=None if check else self._report,
                )
                finish(path, None)
            except Exception as exc:
                finish(None, str(exc) or type(exc).__name__)

        def finish(path, error):
            self._bridge.dispatch(partial(self._finish, check, inputs, revision, path, error))

        self._thread = threading.Thread(target=work, daemon=True)
        try:
            self._thread.start()
        except RuntimeError as exc:
            self._finish(check, inputs, revision, None, str(exc))

    def _report(self, message: str, fraction: float) -> None:
        def update():
            if self._state.run_status == "exporting":
                self.progress.value = round(fraction * 100)
                self._show("正在导出 NWB……", "info", message.removeprefix("export:"))

        self._bridge.dispatch(update)

    def _finish(self, check, inputs, revision, path, error) -> None:
        self._bridge.release_document()
        self.progress.visible = False
        if error:
            message = "检查未通过。" if check else "NWB 导出未完成。"
            if "--recorded-vault" in error:
                self.recorded.visible = True
                error = error.partition(" For an old session supply")[0]
                message += (
                    "请核对原始数据和配置。若旧版任务填过图片库，请在上方补填当时的路径，再检查。"
                )
            elif "--image-vault" in error:
                error = error.partition(" Specify the original package directory")[0]
                message += (
                    "请选择任务实际使用的刺激表所在目录，确认旁边有原版 manifest.tsv，再检查。"
                )
            self._show(message, "danger", error)
            self._state.error_message = message
            self._state.run_status = "failed"
        elif check:
            if revision == self._revision and inputs == self._inputs():
                self._checked = inputs
                self._show("检查通过，可以仅继续 NWB 导出。", "success", f"导出位置：{path}")
            else:
                self._show("目录已改变，请重新检查。", "warning")
            self._state.run_status = "idle"
        else:
            self._show("NWB 导出完成。", "success", str(path))
            self._state.safe_to_exit = True
            self._state.run_status = "completed"

    def panel(self):
        return pn.Column(
            pn.pane.Markdown("### 从已保存的结果继续 NWB 导出"),
            self.output.panel(),
            self.vault.panel(),
            self.recorded,
            pn.FlexBox(self.check_btn, self.export_btn),
            self.message,
            self.detail,
            self.progress,
            sizing_mode="stretch_width",
        )
