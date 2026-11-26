"""Exercise the two-click recovery flow with the same widgets as a fresh Execute page."""

from unittest.mock import Mock

import panel as pn
import pytest
from bokeh.document import Document
from panel.io.state import set_curdoc

from pynpxpipe.ui.components.resume_export import ResumeExportPanel
from pynpxpipe.ui.components.run_panel import RunPanel
from pynpxpipe.ui.state import AppState, ProgressBridge


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    root = tmp_path / "processed"
    root.mkdir()
    (root / "session.json").touch()
    state = AppState()
    panel = ResumeExportPanel(state, ProgressBridge(state))
    panel.output.value = str(root)
    panel.vault.text_input.value_input = str(tmp_path)
    assert not panel.check_btn.disabled
    doc = Document()
    ticks = []
    monkeypatch.setattr(doc, "add_next_tick_callback", ticks.append)
    backend = Mock(return_value=root / "result.nwb")
    monkeypatch.setattr("pynpxpipe.pipelines.resume_export.resume_export", backend)

    def click(button):
        with set_curdoc(doc):
            button.clicks += 1

    def flush():
        panel._thread.join(timeout=5)
        assert not panel._thread.is_alive()
        while ticks:
            ticks.pop(0)()

    return panel, state, backend, click, flush, root


def test_export_requires_check_and_updates_clicking_document(recovery):
    panel, state, backend, click, flush, root = recovery
    regular = RunPanel(state, pipeline_fn=Mock(), preview_fn=Mock())
    click(panel.export_btn)
    backend.assert_not_called()
    click(panel.check_btn)
    assert state.run_status == "checking_export"
    assert regular.run_btn.disabled and regular.preview_btn.disabled and regular.stop_btn.disabled
    click(regular.run_btn)
    click(regular.preview_btn)
    assert not regular.validation_alert.visible
    click(panel.check_btn)
    flush()
    backend.assert_called_once_with(
        root, [root.parent], recorded_vaults=[], check_only=True, progress_callback=None
    )
    assert not panel.export_btn.disabled and not state.safe_to_exit

    def export(out, vaults, *, check_only, recorded_vaults, progress_callback):
        assert not check_only and vaults == [root.parent] and out == root
        progress_callback("export:Verified block 1", 0.75)
        return root / "result.nwb"

    backend.side_effect = export
    click(panel.export_btn)
    click(panel.export_btn)
    assert state.run_status == "exporting" and not state.safe_to_exit
    flush()
    assert state.run_status == "completed" and state.safe_to_exit
    assert panel.progress.value == 75 and panel.detail.object == str(root / "result.nwb")
    assert backend.call_count == 2 and panel.export_btn.disabled and not regular.run_btn.disabled


def test_stale_check_and_edited_or_failed_inputs_cannot_export(recovery):
    panel, state, backend, click, flush, root = recovery
    click(panel.check_btn)
    panel.output.text_input.value_input = "uncommitted edit"
    flush()
    assert panel.export_btn.disabled
    panel.output.value = str(root)
    click(panel.check_btn)
    flush()
    assert not panel.export_btn.disabled
    panel.vault.value = str(root)
    click(panel.export_btn)
    assert panel.export_btn.disabled and backend.call_count == 2
    backend.side_effect = ValueError("original roots missing: --recorded-vault")
    click(panel.check_btn)
    flush()
    assert panel.recorded.visible and state.run_status == "failed"
    assert panel.export_btn.disabled and "原始数据" in panel.message.object
    panel.recorded.value = str(root.parent / "original-library")
    backend.side_effect = None
    click(panel.check_btn)
    flush()
    assert backend.call_args.kwargs["recorded_vaults"] == [root.parent / "original-library"]
    backend.side_effect = OSError("disk full")
    click(panel.export_btn)
    flush()
    assert panel.export_btn.disabled and panel.detail.object == "disk full"
    assert not state.safe_to_exit and not panel.check_btn.disabled


def test_fresh_execute_exposes_recovery():
    from pynpxpipe.ui.app import create_app

    app = create_app()
    # P1-5: export recovery lives in the workspace's export-stage actions.
    workspace = app._pynpx_workspace
    workspace.select("export")
    execute = workspace.export_box
    assert execute.visible
    assert {"已保存的输出目录", "刺激表目录"} <= {
        w.name for w in execute.select(pn.widgets.TextInput)
    }
    buttons = {w.name: w for w in execute.select(pn.widgets.Button)}
    assert buttons["仅继续 NWB 导出"].disabled and buttons["检查导出条件"].disabled
