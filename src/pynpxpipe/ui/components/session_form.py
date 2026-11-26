"""ui/components/session_form.py — Session path configuration panel.

Single-recording inputs and ordered joint-recording pairs are separate modes.
"""

from __future__ import annotations

import re
from pathlib import Path

import panel as pn

from pynpxpipe.ui.components.browsable_input import BrowsableInput
from pynpxpipe.ui.state import AppState


def _discover_paths(data_dir: Path) -> tuple[list[Path], list[Path], list[str]]:
    """Discover all gate-directory and BHV2 candidates in *data_dir*.

    Returns:
        (gate_dirs, bhv_files, errors); candidates are sorted by name and
        ``errors`` is empty when at least one of each was found.
    """
    if not data_dir.exists():
        return [], [], [f"目录不存在：{data_dir}"]

    gate_dirs = sorted(p for p in data_dir.iterdir() if p.is_dir() and re.search(r"_g\d+$", p.name))
    bhv_files = sorted(data_dir.glob("*.bhv2"))

    errors: list[str] = []
    if not gate_dirs:
        errors.append("未找到 *_g[0-9] gate 目录")
    if not bhv_files:
        errors.append("未找到 .bhv2 行为文件")
    return gate_dirs, bhv_files, errors


def _format_size(n_bytes: int) -> str:
    size = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class SessionForm:
    """Single-recording paths and an independent editor for joint source pairs."""

    def __init__(self, state: AppState) -> None:
        self._state = state
        self.validation_message: str = ""
        self.discovery_status: str = ""
        self._editing_index: int | None = None

        # ── Mode toggle ──
        self.input_mode = pn.widgets.RadioButtonGroup(
            name="处理模式",
            options={"单段记录": "single", "多段联合": "joint"},
            value=state.input_mode,
            button_type="primary",
        )
        self.advanced_toggle = pn.widgets.Toggle(name="手动指定单段路径", value=False)

        # ── Simple mode widget ──
        self.data_dir_input = BrowsableInput(
            name="数据目录",
            placeholder="/path/to/experiment_folder",
            file_pattern="*",
            only_files=False,
        )

        # ── Advanced mode widgets (hidden by default) ──
        self.session_dir_input = BrowsableInput(
            name="Gate 目录（含 NIDQ 文件和 _imec 子目录）",
            placeholder="/path/to/session_root",
            file_pattern="*",
            only_files=False,
        )
        self.bhv_file_input = BrowsableInput(
            name="BHV2 文件",
            placeholder="/path/to/recording.bhv2",
            file_pattern="*.bhv2",
            only_files=True,
        )

        # ── Shared widget ──
        self.output_dir_input = BrowsableInput(
            name="输出目录",
            placeholder="/path/to/output",
            file_pattern="*",
            only_files=False,
        )

        # ── NWB filename fields (SID S3) ──
        self.experiment_input = pn.widgets.TextInput(
            name="实验名",
            placeholder="e.g. nsd1w",
            value=state.experiment,
        )
        self.recording_date_input = pn.widgets.TextInput(
            name="采集日期（YYMMDD）",
            placeholder="251024",
            value=state.recording_date,
        )
        self.detect_date_btn = pn.widgets.Button(
            name="读取采集日期",
            button_type="default",
        )
        self.detect_date_alert = pn.pane.Alert(
            "", alert_type="warning", visible=False, sizing_mode="stretch_width"
        )

        # ── Discovery result card (ui_redesign P0-1) ──
        self.discovery_card = pn.pane.Alert(
            "", alert_type="success", visible=False, sizing_mode="stretch_width"
        )
        self.choice_alert = pn.pane.Alert(
            "", alert_type="warning", visible=False, sizing_mode="stretch_width"
        )
        self.gate_select = pn.widgets.Select(name="Gate 目录", options={}, visible=False)
        self.bhv_select = pn.widgets.Select(name="BHV2 文件", options={}, visible=False)
        self.validation_alert = pn.pane.Alert(
            "", alert_type="danger", visible=False, sizing_mode="stretch_width"
        )
        self.discovery_box = pn.Column(
            self.discovery_card,
            self.choice_alert,
            self.gate_select,
            self.bhv_select,
            sizing_mode="stretch_width",
        )
        import pandas as pd

        self.pair_session_dir_input = BrowsableInput(
            name="神经记录目录（含 NIDQ 文件和 _imec 子目录）",
            placeholder="例如 D:/data/261109/recording_g0",
        )
        self.pair_bhv_file_input = BrowsableInput(
            name="对应的 BHV2 行为文件",
            file_pattern="*.bhv2",
            only_files=True,
        )
        self.source_id_input = pn.widgets.TextInput(name="记录名称", value="source0")
        self.source_offset_input = pn.widgets.TextInput(name="起始偏移秒（留空读取采集时间）")
        self.add_pair_btn = pn.widgets.Button(name="添加配对", button_type="primary")
        self.edit_pair_btn = pn.widgets.Button(name="编辑所选配对")
        self.save_pair_btn = pn.widgets.Button(name="保存修改", disabled=True)
        self.remove_pair_btn = pn.widgets.Button(name="移除所选配对")
        self.move_up_btn = pn.widgets.Button(name="上移")
        self.move_down_btn = pn.widgets.Button(name="下移")
        self.pairs_table = pn.widgets.Tabulator(
            pd.DataFrame(columns=["source_id", "session_dir", "bhv_file", "start_offset_s"]),
            selectable=1,
            disabled=True,
            show_index=False,
            sortable=False,
            height=180,
        )
        self.pairs_alert = pn.pane.Alert(
            "同一动物、同一天、探针位置及配置未改变；按采集顺序添加。", alert_type="info"
        )
        self.add_pair_btn.on_click(self._add_pair)
        self.edit_pair_btn.on_click(self._edit_pair)
        self.save_pair_btn.on_click(self._save_pair)
        self.remove_pair_btn.on_click(self._remove_pair)
        self.move_up_btn.on_click(lambda event: self._move_pair(-1))
        self.move_down_btn.on_click(lambda event: self._move_pair(1))
        state.param.watch(self._refresh_pairs, "recordings")

        # Hide advanced inputs initially
        self.session_dir_input.visible = False
        self.bhv_file_input.visible = False
        self.single_paths = pn.Column(
            self.advanced_toggle,
            self.data_dir_input.panel(),
            self.discovery_box,
            self.session_dir_input.panel(),
            self.bhv_file_input.panel(),
            self.validation_alert,
        )
        self.joint_paths = pn.Column(
            pn.pane.Markdown(
                "**两段记录联合 sorting**\n\n"
                "1. 每段分别选择神经目录与对应 BHV2，点击 **添加配对**。至少添加两组，"
                "下方表格按采集先后排列；可选择行后编辑、上移或下移。\n"
                "2. 神经目录选 `…/run_g0` 这一层：里面直接有 `*.nidq.bin/.meta`，"
                "以及包含 AP 文件的 `run_g0_imec0/`。BHV2 单独选择，通常在日期目录下。\n"
                "3. 在右侧 **任务时段截取** 中设置采集时区（中国采集填写 `Asia/Shanghai`），"
                "按需启用 **只处理任务时段**。\n"
                "4. 填好下方输出目录、实验名、日期、动物和探针脑区；进入 **Execute**，"
                "先点击 **对齐并预览任务时段**，核对结果后点击 **Run** 进行联合预处理和 sorting。\n\n"
                "执行使用下方**已保存配对**；修改输入框后需要点击添加或保存修改。"
                "同一动物、同一天，探针插入位置及配置应保持不变；"
                "程序从原始元数据读取序列号，无需手填。"
            ),
            self.pair_session_dir_input.panel(),
            self.pair_bhv_file_input.panel(),
            self.source_id_input,
            self.source_offset_input,
            pn.Row(self.add_pair_btn, self.save_pair_btn),
            self.pairs_alert,
            self.pairs_table,
            pn.Row(self.edit_pair_btn, self.remove_pair_btn, self.move_up_btn, self.move_down_btn),
        )

        # ── Watchers ──
        self.advanced_toggle.param.watch(self._on_mode_change, "value")
        self.input_mode.param.watch(lambda event: setattr(state, "input_mode", event.new), "value")
        state.param.watch(self._on_input_mode, "input_mode")
        self.data_dir_input.text_input.param.watch(self._on_data_dir, "value")
        self.gate_select.param.watch(self._on_candidate_change, "value")
        self.bhv_select.param.watch(self._on_candidate_change, "value")
        self.session_dir_input.text_input.param.watch(self._on_session_dir, "value")
        self.bhv_file_input.text_input.param.watch(self._on_bhv_file, "value")
        self.output_dir_input.text_input.param.watch(self._on_output_dir, "value")
        self.experiment_input.param.watch(self._on_experiment, "value")
        self.recording_date_input.param.watch(self._on_recording_date, "value")
        self.detect_date_btn.on_click(self._on_detect_date_click)
        state.param.watch(self._on_state_experiment, "experiment")
        state.param.watch(self._on_state_recording_date, "recording_date")
        self._on_input_mode()
        self._refresh_pairs()

    # ── Mode switching ──

    def _on_input_mode(self, event=None) -> None:
        joint = self._state.input_mode == "joint"
        self.input_mode.value = self._state.input_mode
        self.single_paths.visible = not joint
        self.joint_paths.visible = joint

    def _refresh_pairs(self, event=None) -> None:
        import pandas as pd

        self.pairs_table.value = pd.DataFrame(
            self._state.recordings,
            columns=["source_id", "session_dir", "bhv_file", "start_offset_s"],
        )
        self._finish_pair_edit()

    def _pair_from_inputs(self, replacing: int | None = None) -> dict:
        from pynpxpipe.core.session import RecordingSource

        if not self.pair_session_dir_input.value or not self.pair_bhv_file_input.value:
            raise ValueError("先选择神经记录目录和对应的 BHV2 文件")
        folder = Path(self.pair_session_dir_input.value)
        bhv = Path(self.pair_bhv_file_input.value)
        if (
            not folder.is_dir()
            or not any(folder.glob("*_imec*/*.ap.meta"))
            or not any(folder.glob("*.nidq.bin"))
        ):
            raise ValueError(
                "神经目录层级不正确：请选择直接包含 NIDQ 文件和 _imec 子目录的 run_g0/run_g1 目录。"
            )
        if bhv.suffix.lower() != ".bhv2" or not bhv.is_file():
            raise ValueError("请选择存在的 .bhv2 行为文件")
        source = RecordingSource(
            self.source_id_input.value.strip(),
            folder,
            bhv,
            float(self.source_offset_input.value)
            if self.source_offset_input.value.strip()
            else None,
        )
        for i, saved in enumerate(self._state.recordings):
            if i == replacing:
                continue
            if saved["source_id"] == source.source_id:
                raise ValueError("记录名称不能重复")
            if Path(saved["session_dir"]).resolve() == folder.resolve():
                raise ValueError("该神经目录已添加；请为下一段选择另一个记录目录")
        return source.to_dict()

    def _add_pair(self, event=None) -> None:
        try:
            source = self._pair_from_inputs()
            self._state.recordings = [*self._state.recordings, source]
            self._finish_pair_edit()
            self.pairs_alert.object = "已添加；表格顺序即联合处理顺序。"
            self.pairs_alert.alert_type = "success"
        except (OSError, ValueError) as exc:
            self.pairs_alert.object = str(exc)
            self.pairs_alert.alert_type = "danger"

    def _edit_pair(self, event=None) -> None:
        if not self.pairs_table.selection:
            return
        self._editing_index = self.pairs_table.selection[0]
        source = self._state.recordings[self._editing_index]
        self.source_id_input.value = source["source_id"]
        self.pair_session_dir_input.value = str(source["session_dir"])
        self.pair_bhv_file_input.value = str(source["bhv_file"])
        offset = source.get("start_offset_s")
        self.source_offset_input.value = "" if offset is None else str(offset)
        self.save_pair_btn.disabled = False
        self.add_pair_btn.disabled = True
        self.pairs_alert.object = "正在编辑所选配对；完成后点击保存修改。"
        self.pairs_alert.alert_type = "info"

    def _save_pair(self, event=None) -> None:
        if self._editing_index is None:
            return
        try:
            source = self._pair_from_inputs(replacing=self._editing_index)
            pairs = list(self._state.recordings)
            pairs[self._editing_index] = source
            self._state.recordings = pairs
            self._finish_pair_edit()
            self.pairs_alert.object = "配对修改已保存。"
            self.pairs_alert.alert_type = "success"
        except (OSError, ValueError) as exc:
            self.pairs_alert.object = str(exc)
            self.pairs_alert.alert_type = "danger"

    def _finish_pair_edit(self) -> None:
        self._editing_index = None
        self.save_pair_btn.disabled = True
        self.add_pair_btn.disabled = False
        names = {s["source_id"] for s in self._state.recordings}
        index = 0
        while f"source{index}" in names:
            index += 1
        self.source_id_input.value = f"source{index}"
        self.source_offset_input.value = ""

    def _move_pair(self, direction: int) -> None:
        if not self.pairs_table.selection:
            return
        index = self.pairs_table.selection[0]
        target = index + direction
        pairs = list(self._state.recordings)
        if not 0 <= target < len(pairs):
            return
        pairs[index], pairs[target] = pairs[target], pairs[index]
        self._state.recordings = pairs
        self.pairs_table.selection = [target]
        self._finish_pair_edit()

    def _remove_pair(self, event=None) -> None:
        selected = set(self.pairs_table.selection)
        self._state.recordings = [
            s for i, s in enumerate(self._state.recordings) if i not in selected
        ]
        self.pairs_table.selection = []
        self._finish_pair_edit()

    def _on_mode_change(self, event) -> None:
        advanced = event.new
        self.data_dir_input.visible = not advanced
        self.discovery_box.visible = not advanced
        self.session_dir_input.visible = advanced
        self.bhv_file_input.visible = advanced

        if advanced:
            # Simple → Advanced: fill advanced fields with discovered values
            if self._state.session_dir is not None:
                self.session_dir_input.value = str(self._state.session_dir)
            if self._state.bhv_file is not None:
                self.bhv_file_input.value = str(self._state.bhv_file)
        else:
            # Advanced → Simple: infer data_dir from session_dir parent
            if self.session_dir_input.value:
                parent = str(Path(self.session_dir_input.value).parent)
                self.data_dir_input.value = parent

    # ── Simple mode: auto-discovery ──

    def _on_data_dir(self, event) -> None:
        val: str = event.new or ""
        gate_dirs, bhv_files, errors = _discover_paths(Path(val)) if val else ([], [], [])
        if not val:
            self.discovery_status = ""
        elif errors:
            self.discovery_status = " | ".join(errors)
        else:
            self.discovery_status = f"已找到：{gate_dirs[0].name} | {bhv_files[0].name}"

        # Updating options re-fires _on_candidate_change; suppress until both are set.
        self._updating_candidates = True
        self.gate_select.options = {p.name: str(p) for p in gate_dirs}
        self.gate_select.value = str(gate_dirs[0]) if gate_dirs else None
        self.bhv_select.options = {p.name: str(p) for p in bhv_files}
        self.bhv_select.value = str(bhv_files[0]) if bhv_files else None
        self._updating_candidates = False

        self.gate_select.visible = len(gate_dirs) > 1
        self.bhv_select.visible = len(bhv_files) > 1
        notes = []
        if len(gate_dirs) > 1:
            notes.append(f"找到 {len(gate_dirs)} 个 gate 目录，默认使用第一个，请确认。")
        if len(bhv_files) > 1:
            notes.append(f"找到 {len(bhv_files)} 个 BHV2 文件，请选择与这段记录对应的一个。")
        self.choice_alert.object = "\n\n".join(notes)
        self.choice_alert.visible = bool(notes)

        if not val:
            self.discovery_card.visible = False
            self._state.session_dir = None
            self._state.bhv_file = None
            return
        if errors:
            self._show_discovery_error(errors)
            self._state.session_dir = gate_dirs[0] if gate_dirs else None
            self._state.bhv_file = bhv_files[0] if bhv_files else None
            return
        self._on_candidate_change()

    def _on_candidate_change(self, event=None) -> None:
        if getattr(self, "_updating_candidates", False):
            return
        if not self.gate_select.value or not self.bhv_select.value:
            return
        gate = Path(self.gate_select.value)
        self._state.session_dir = gate
        self._state.bhv_file = Path(self.bhv_select.value)
        self._identify_recording(gate)

    def _show_discovery_error(self, errors: list[str]) -> None:
        self.discovery_card.alert_type = "danger"
        self.discovery_card.object = "**未能识别这段记录**\n\n" + "\n".join(
            f"- {e}" for e in errors
        )
        self.discovery_card.visible = True

    def _identify_recording(self, gate: Path) -> None:
        """Read probes, NIDQ and recording date from *gate* via io/spikeglx and render the card."""
        from pynpxpipe.core.errors import DiscoverError
        from pynpxpipe.io.spikeglx import SpikeGLXDiscovery, SpikeGLXLoader

        try:
            discovery = SpikeGLXDiscovery(gate)
            nidq_bin, _ = discovery.discover_nidq()
            probes = discovery.discover_probes()
        except (DiscoverError, OSError) as exc:
            self._show_discovery_error([str(exc)])
            return

        warnings = [f"{p.probe_id}: {w}" for p in probes for w in discovery.validate_probe(p)]
        try:
            date = SpikeGLXLoader.read_recording_date(probes[0].ap_meta)
            date_text = f"`{date}` · 从 {probes[0].probe_id} ap.meta 读取"
            self._state.recording_date = date
            self.recording_date_input.value = date
        except (OSError, ValueError) as exc:
            date_text = f"读取失败（{exc}），可手动填写或点「读取采集日期」重试"

        rows = "\n".join(
            f"| `{p.probe_id}` | {p.probe_type} | `{p.serial_number}` | {p.n_channels} | "
            f"{_format_size(p.ap_bin.stat().st_size) if p.ap_bin.exists() else '缺失'} |"
            for p in probes
        )
        lines = [
            "**已识别这段记录**",
            "",
            f"- Gate 目录：`{gate.name}`",
            f"- NIDQ：`{nidq_bin.name}`",
            f"- 采集日期：{date_text}",
            "",
            "| 探针 | 型号 | 序列号 | 通道 | AP 文件 |",
            "|---|---|---|---|---|",
            rows,
        ]
        if warnings:
            lines += ["", "**注意**", *(f"- {w}" for w in warnings)]
        self.discovery_card.alert_type = "warning" if warnings else "success"
        self.discovery_card.object = "\n".join(lines)
        self.discovery_card.visible = True

    # ── Advanced mode watchers ──

    def _on_session_dir(self, event) -> None:
        self._state.session_dir = Path(event.new) if event.new else None

    def _on_bhv_file(self, event) -> None:
        val: str = event.new or ""
        if val and not val.endswith(".bhv2"):
            self.validation_message = "BHV2 文件必须以 .bhv2 结尾"
        else:
            self.validation_message = ""
            self._state.bhv_file = Path(val) if val else None
        self.validation_alert.object = self.validation_message
        self.validation_alert.visible = bool(self.validation_message)

    def _on_output_dir(self, event) -> None:
        self._state.output_dir = Path(event.new) if event.new else None

    # ── NWB filename fields (SID S3) ──

    def _on_experiment(self, event) -> None:
        self._state.experiment = event.new or ""

    def _on_recording_date(self, event) -> None:
        self._state.recording_date = event.new or ""

    def _on_state_experiment(self, event) -> None:
        if self.experiment_input.value != event.new:
            self.experiment_input.value = event.new

    # ── Public API ──

    def apply_paths(
        self,
        session_dir: str | Path | None,
        bhv_file: str | Path | None,
        output_dir: str | Path | None,
    ) -> None:
        """Populate session/BHV/output path widgets after a restore.

        Switches to Advanced mode so the loaded paths are visible. The widget
        watchers propagate the new values into ``state.session_dir`` /
        ``state.bhv_file`` / ``state.output_dir``.
        """
        self.advanced_toggle.value = True
        self.session_dir_input.value = str(session_dir) if session_dir else ""
        self.bhv_file_input.value = str(bhv_file) if bhv_file else ""
        self.output_dir_input.value = str(output_dir) if output_dir else ""

    def _on_state_recording_date(self, event) -> None:
        if self.recording_date_input.value != event.new:
            self.recording_date_input.value = event.new

    def _find_ap_meta(self) -> Path | None:
        """Return the first *.ap.meta under session_dir, or None."""
        if self._state.active_session_dir is None:
            return None
        root = Path(self._state.active_session_dir)
        if not root.exists():
            return None
        metas = sorted(root.rglob("*.ap.meta"))
        return metas[0] if metas else None

    def _on_detect_date_click(self, event) -> None:
        from pynpxpipe.io.spikeglx import SpikeGLXLoader

        meta_path = self._find_ap_meta()
        if meta_path is None:
            self.detect_date_alert.object = (
                "在 gate 目录下没有找到 *.ap.meta，请先选择有效的数据目录。"
            )
            self.detect_date_alert.alert_type = "warning"
            self.detect_date_alert.visible = True
            return
        try:
            yymmdd = SpikeGLXLoader.read_recording_date(meta_path)
        except Exception as exc:  # noqa: BLE001
            self.detect_date_alert.object = f"读取采集日期失败：{exc}"
            self.detect_date_alert.alert_type = "danger"
            self.detect_date_alert.visible = True
            return
        self._state.recording_date = yymmdd
        self.recording_date_input.value = yymmdd
        self.detect_date_alert.object = f"已读取采集日期：{yymmdd}"
        self.detect_date_alert.alert_type = "success"
        self.detect_date_alert.visible = True

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("### 数据与输出"),
            self.input_mode,
            self.single_paths,
            self.joint_paths,
            self.output_dir_input.panel(),
            self.experiment_input,
            pn.Row(self.recording_date_input, self.detect_date_btn),
            self.detect_date_alert,
        )
