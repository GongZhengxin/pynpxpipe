"""Tests for ui/components/session_form.py — SID S3 NWB filename fields.

Groups:
  A. experiment input  — widget present, bound to state.experiment
  B. recording_date input + Detect Date button — triggers SpikeGLXLoader.read_recording_date
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import panel as pn

from pynpxpipe.ui.state import AppState


def _write_meta(path: Path, create_time: str = "2025-10-24T14:30:00") -> None:
    path.write_text(
        f"fileCreateTime={create_time}\nimSampRate=30000.0\nnSavedChans=385\n",
        encoding="utf-8",
    )


class TestSessionFormNWBFields:
    def test_session_form_has_experiment_input(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        assert isinstance(form.experiment_input, pn.widgets.TextInput)

    def test_experiment_input_updates_state(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        form.experiment_input.value = "nsd1w"
        assert state.experiment == "nsd1w"

    def test_session_form_has_recording_date_input(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        assert isinstance(form.recording_date_input, pn.widgets.TextInput)

    def test_recording_date_input_updates_state(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        form.recording_date_input.value = "251024"
        assert state.recording_date == "251024"

    def test_detect_date_button_exists(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        assert isinstance(form.detect_date_btn, pn.widgets.Button)

    def test_detect_date_button_calls_read_recording_date(self, tmp_path: Path):
        """Click Detect Date with a valid session_dir -> SpikeGLXLoader is invoked."""
        from pynpxpipe.ui.components.session_form import SessionForm

        gate_dir = tmp_path / "run_g0"
        gate_dir.mkdir()
        meta = gate_dir / "run_g0_t0.imec0.ap.meta"
        _write_meta(meta)

        state = AppState()
        state.session_dir = gate_dir
        form = SessionForm(state)

        with patch(
            "pynpxpipe.io.spikeglx.SpikeGLXLoader.read_recording_date",
            return_value="251024",
        ) as mock_read:
            form._on_detect_date_click(None)

        mock_read.assert_called_once()
        called_path = Path(mock_read.call_args[0][0])
        assert called_path == meta

    def test_detect_date_button_writes_recording_date_to_state(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        gate_dir = tmp_path / "run_g0"
        gate_dir.mkdir()
        meta = gate_dir / "run_g0_t0.imec0.ap.meta"
        _write_meta(meta)

        state = AppState()
        state.session_dir = gate_dir
        form = SessionForm(state)

        with patch(
            "pynpxpipe.io.spikeglx.SpikeGLXLoader.read_recording_date",
            return_value="251024",
        ):
            form._on_detect_date_click(None)

        assert state.recording_date == "251024"
        assert form.recording_date_input.value == "251024"

    def test_detect_date_button_warns_when_no_meta(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        gate_dir = tmp_path / "run_g0"
        gate_dir.mkdir()

        state = AppState()
        state.session_dir = gate_dir
        form = SessionForm(state)
        form._on_detect_date_click(None)

        assert form.detect_date_alert.visible is True
        assert "*.ap.meta" in str(form.detect_date_alert.object)
        assert state.recording_date == ""


def _make_recording(
    root: Path,
    gate_names: tuple[str, ...] = ("MaoDan_251024_g0",),
    bhv_names: tuple[str, ...] = ("251024_MaoDan_nsd1w.bhv2",),
    probes: tuple[str, ...] = ("imec0",),
    with_nidq: bool = True,
) -> list[Path]:
    """Create a minimal SpikeGLX date folder: gate dirs with probes + NIDQ, BHV2 files."""
    gates = []
    for gate_name in gate_names:
        gate = root / gate_name
        gate.mkdir()
        if with_nidq:
            (gate / f"{gate_name}_t0.nidq.bin").write_bytes(b"\0" * 16)
            (gate / f"{gate_name}_t0.nidq.meta").write_text(
                "niSampRate=25000\nnSavedChans=8\n", encoding="utf-8"
            )
        for i, probe_id in enumerate(probes):
            probe_dir = gate / f"{gate_name}_{probe_id}"
            probe_dir.mkdir()
            stem = f"{gate_name}_t0.{probe_id}"
            (probe_dir / f"{stem}.ap.bin").write_bytes(b"\0" * 2048)
            (probe_dir / f"{stem}.ap.meta").write_text(
                "fileCreateTime=2025-10-24T14:30:00\n"
                "imSampRate=30000.0\n"
                "nSavedChans=385\n"
                f"imDatPrb_sn=1912241461{i}\n"
                "imDatPrb_type=0\n",
                encoding="utf-8",
            )
        gates.append(gate)
    for bhv_name in bhv_names:
        (root / bhv_name).write_bytes(b"")
    return gates


class TestSessionFormDiscoveryCard:
    """P0-1: discovery result card rendered inside SessionForm (ui_redesign.md §4.2)."""

    def test_card_is_part_of_layout(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        form = SessionForm(AppState())
        panes = form.panel().select(pn.pane.Alert)
        assert any(p is form.discovery_card for p in panes)

    def test_card_hidden_before_any_data_dir(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        form = SessionForm(AppState())
        assert form.discovery_card.visible is False

    def test_successful_discovery_shows_card_with_probes(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(tmp_path, probes=("imec0", "imec1"))
        form = SessionForm(AppState())
        form.data_dir_input.value = str(tmp_path)

        card = str(form.discovery_card.object)
        assert form.discovery_card.visible is True
        assert form.discovery_card.alert_type == "success"
        assert "已识别这段记录" in card
        assert "MaoDan_251024_g0" in card
        assert "MaoDan_251024_g0_t0.nidq.bin" in card
        for probe_id, serial in (("imec0", "19122414610"), ("imec1", "19122414611")):
            assert probe_id in card
            assert serial in card
        assert "385" in card
        assert "2.0 KB" in card

    def test_single_candidates_hide_select_widgets(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(tmp_path)
        form = SessionForm(AppState())
        form.data_dir_input.value = str(tmp_path)

        assert form.gate_select.visible is False
        assert form.bhv_select.visible is False
        assert form.choice_alert.visible is False

    def test_multiple_gate_dirs_show_select_defaulting_to_first(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        gates = _make_recording(tmp_path, gate_names=("run_g0", "run_g1"))
        state = AppState()
        form = SessionForm(state)
        form.data_dir_input.value = str(tmp_path)

        assert isinstance(form.gate_select, pn.widgets.Select)
        assert form.gate_select.visible is True
        assert list(form.gate_select.options.values()) == [str(g) for g in gates]
        assert form.gate_select.value == str(gates[0])
        assert Path(state.session_dir) == gates[0]
        assert form.choice_alert.visible is True
        assert "找到 2 个 gate 目录" in str(form.choice_alert.object)

        form.gate_select.value = str(gates[1])
        assert Path(state.session_dir) == gates[1]
        assert "run_g1" in str(form.discovery_card.object)

    def test_multiple_bhv_files_show_select_defaulting_to_first(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(
            tmp_path, bhv_names=("251024_MaoDan_calib.bhv2", "251024_MaoDan_nsd1w.bhv2")
        )
        state = AppState()
        form = SessionForm(state)
        form.data_dir_input.value = str(tmp_path)

        first = tmp_path / "251024_MaoDan_calib.bhv2"
        second = tmp_path / "251024_MaoDan_nsd1w.bhv2"
        assert isinstance(form.bhv_select, pn.widgets.Select)
        assert form.bhv_select.visible is True
        assert form.bhv_select.value == str(first)
        assert Path(state.bhv_file) == first
        assert "找到 2 个 BHV2 文件" in str(form.choice_alert.object)

        form.bhv_select.value = str(second)
        assert Path(state.bhv_file) == second

    def test_successful_discovery_autofills_recording_date(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(tmp_path)
        state = AppState()
        form = SessionForm(state)
        form.data_dir_input.value = str(tmp_path)

        assert state.recording_date == "251024"
        assert form.recording_date_input.value == "251024"
        assert "251024" in str(form.discovery_card.object)
        # Manual retry button is kept.
        assert isinstance(form.detect_date_btn, pn.widgets.Button)

    def test_nonexistent_dir_shows_error_card(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        missing = tmp_path / "nope"
        form = SessionForm(AppState())
        form.data_dir_input.value = str(missing)

        assert form.discovery_card.visible is True
        assert form.discovery_card.alert_type == "danger"
        assert "目录不存在" in str(form.discovery_card.object)

    def test_missing_bhv2_shows_error_card(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(tmp_path, bhv_names=())
        state = AppState()
        form = SessionForm(state)
        form.data_dir_input.value = str(tmp_path)

        assert form.discovery_card.alert_type == "danger"
        assert ".bhv2" in str(form.discovery_card.object)
        assert state.recording_date == ""

    def test_missing_probe_files_shows_error_card(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(tmp_path, probes=())
        form = SessionForm(AppState())
        form.data_dir_input.value = str(tmp_path)

        assert form.discovery_card.alert_type == "danger"
        assert "imec" in str(form.discovery_card.object)

    def test_missing_nidq_shows_error_card(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(tmp_path, with_nidq=False)
        form = SessionForm(AppState())
        form.data_dir_input.value = str(tmp_path)

        assert form.discovery_card.alert_type == "danger"
        assert "nidq" in str(form.discovery_card.object).lower()

    def test_clearing_data_dir_hides_card(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(tmp_path, gate_names=("run_g0", "run_g1"))
        form = SessionForm(AppState())
        form.data_dir_input.value = str(tmp_path)
        form.data_dir_input.value = ""

        assert form.discovery_card.visible is False
        assert form.choice_alert.visible is False
        assert form.gate_select.visible is False

    def test_validation_message_is_rendered(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        form = SessionForm(AppState())
        form.advanced_toggle.value = True
        form.bhv_file_input.value = "C:/data/task.txt"

        assert form.validation_alert.visible is True
        assert form.validation_message in str(form.validation_alert.object)
        assert any(p is form.validation_alert for p in form.panel().select(pn.pane.Alert))

        form.bhv_file_input.value = "C:/data/task.bhv2"
        assert form.validation_alert.visible is False


class TestSessionFormApplyPaths:
    """SessionForm.apply_paths() must populate path widgets after a session restore."""

    def test_apply_paths_fills_advanced_inputs_and_state(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        form.apply_paths(
            session_dir="C:/data/monkey_g0",
            bhv_file="C:/data/task.bhv2",
            output_dir="C:/output/session1",
        )

        assert form.session_dir_input.value == "C:/data/monkey_g0"
        assert form.bhv_file_input.value == "C:/data/task.bhv2"
        assert form.output_dir_input.value == "C:/output/session1"
        assert state.session_dir == Path("C:/data/monkey_g0")
        assert state.bhv_file == Path("C:/data/task.bhv2")
        assert state.output_dir == Path("C:/output/session1")

    def test_apply_paths_switches_to_advanced_mode(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        # Form starts in simple mode; advanced widgets are hidden.
        assert form.session_dir_input.visible is False

        form.apply_paths(
            session_dir="C:/data/monkey_g0",
            bhv_file="C:/data/task.bhv2",
            output_dir="C:/output/session1",
        )

        # After apply, advanced inputs must be visible so user sees what was loaded.
        assert form.advanced_toggle.value is True
        assert form.session_dir_input.visible is True
        assert form.bhv_file_input.visible is True

    def test_apply_paths_tolerates_path_objects(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        state = AppState()
        form = SessionForm(state)
        form.apply_paths(
            session_dir=Path("C:/data/monkey_g0"),
            bhv_file=Path("C:/data/task.bhv2"),
            output_dir=Path("C:/output/session1"),
        )

        assert state.session_dir == Path("C:/data/monkey_g0")
        assert state.output_dir == Path("C:/output/session1")


class TestSessionFormCopy:
    """P0-5: unified Chinese labels (ui_redesign.md §4.1)."""

    def test_labels_are_chinese(self):
        from pynpxpipe.ui.components.session_form import SessionForm

        form = SessionForm(AppState())
        assert form.data_dir_input.text_input.name == "数据目录"
        assert form.session_dir_input.text_input.name.startswith("Gate 目录")
        assert form.bhv_file_input.text_input.name == "BHV2 文件"
        assert form.output_dir_input.text_input.name == "输出目录"
        assert form.experiment_input.name == "实验名"
        assert form.recording_date_input.name == "采集日期（YYMMDD）"
        assert form.detect_date_btn.name == "读取采集日期"
        text = " ".join(str(p.object) for p in form.panel().select(pn.pane.Markdown))
        assert "数据与输出" in text

    def test_messages_are_chinese(self, tmp_path: Path):
        from pynpxpipe.ui.components.session_form import SessionForm

        _make_recording(tmp_path)
        form = SessionForm(AppState())
        form.data_dir_input.value = str(tmp_path)
        assert form.discovery_status.startswith("已找到")

        form.advanced_toggle.value = True
        form.bhv_file_input.value = "C:/data/task.txt"
        assert "必须以 .bhv2 结尾" in form.validation_message
