"""ui/components/subject_form.py — Subject metadata form."""

from __future__ import annotations

from pathlib import Path

import panel as pn

from pynpxpipe.core.config import load_subject_config, save_subject_config
from pynpxpipe.core.session import SubjectConfig
from pynpxpipe.ui.components.browsable_input import BrowsableInput
from pynpxpipe.ui.state import AppState

_REQUIRED_FIELDS = ("subject_id", "species", "age", "weight")


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


class SubjectForm:
    """Form for entering NWB subject metadata."""

    def __init__(self, state: AppState, *, project_root: Path | None = None) -> None:
        self._state = state
        self._project_root = project_root or _default_project_root()
        self._pending_overwrite_path: Path | None = None

        self.subject_id_input = pn.widgets.TextInput(name="动物 ID", placeholder="MaoDan")
        self.description_input = pn.widgets.TextInput(name="描述", placeholder="")
        self.species_input = pn.widgets.TextInput(name="物种", value="Macaca mulatta")
        self.sex_select = pn.widgets.Select(name="性别", options=["M", "F", "U", "O"], value="M")
        self.age_input = pn.widgets.TextInput(name="年龄（ISO 8601，如 P3Y）", placeholder="P3Y")
        self.weight_input = pn.widgets.TextInput(name="体重（如 10kg）", placeholder="10kg")
        self.image_vault_paths_input = pn.widgets.TextAreaInput(
            name="图像库路径（每行一个，可选）",
            placeholder="/data/stimuli\n/mnt/shared/stim_library",
            height=90,
        )

        # ── YAML loader ──
        self.yaml_input = BrowsableInput(
            name="从动物档案 YAML 读取",
            placeholder="/path/to/monkey.yaml",
            file_pattern="*.yaml",
            only_files=True,
        )
        self.yaml_input.text_input.param.watch(self._on_yaml_input, "value")

        # ── YAML saver ──
        self.save_path_input = BrowsableInput(
            name="保存路径（可选）",
            placeholder="default: <project_root>/monkeys/<subject_id>.yaml",
            file_pattern="*.yaml",
            only_files=True,
        )
        self.save_btn = pn.widgets.Button(name="保存到 monkeys/", button_type="success")
        self.save_btn.on_click(self._on_save_click)
        self.save_message = pn.pane.Alert(
            "", alert_type="light", sizing_mode="stretch_width", visible=False
        )

        for widget in (
            self.subject_id_input,
            self.description_input,
            self.species_input,
            self.sex_select,
            self.age_input,
            self.weight_input,
            self.image_vault_paths_input,
        ):
            widget.param.watch(self._rebuild_config, "value")

        # ── Wizard step 2: profile cards (ui_redesign P1-3) ──
        self.profile_buttons: dict[str, pn.widgets.Button] = {}
        monkeys = self._project_root / "monkeys"
        for path in sorted(monkeys.glob("*.yaml")) if monkeys.is_dir() else []:
            btn = pn.widgets.Button(name=path.stem, button_type="light", width=140)
            btn.on_click(lambda event, p=path: self.select_profile(p))
            self.profile_buttons[path.stem] = btn
        self.new_subject_btn = pn.widgets.Button(name="+ 新动物", button_type="light", width=140)
        self.new_subject_btn.on_click(lambda event: self.start_new_subject())
        self.profile_summary = pn.pane.Markdown("", visible=False)
        self.edit_btn = pn.widgets.Button(name="编辑档案", visible=False, width=100)
        self.edit_btn.on_click(lambda event: setattr(self.fields_box, "visible", True))
        self.fields_box = pn.Column(
            self._field(self.subject_id_input, "subject_id"),
            self._field(self.description_input, "description"),
            self._field(self.species_input, "species"),
            self._field(self.sex_select, "sex"),
            self._field(self.age_input, "age"),
            self._field(self.weight_input, "weight"),
            self._field(self.image_vault_paths_input, "image_vault_paths"),
            self.save_path_input.panel(),
            self.save_btn,
            self.save_message,
            sizing_mode="stretch_width",
        )

    # ── Internal ──

    def _on_yaml_input(self, event) -> None:
        import contextlib

        path = event.new or ""
        if path and path.endswith(".yaml"):
            with contextlib.suppress(Exception):
                self.load_from_yaml(Path(path))

    def _rebuild_config(self, event=None) -> None:
        if not all(
            [
                self.subject_id_input.value,
                self.species_input.value,
                self.age_input.value,
                self.weight_input.value,
            ]
        ):
            self._state.subject_config = None
            return
        raw = self.image_vault_paths_input.value or ""
        vault_paths = [Path(line.strip()) for line in raw.splitlines() if line.strip()]
        self._state.subject_config = SubjectConfig(
            subject_id=self.subject_id_input.value,
            description=self.description_input.value,
            species=self.species_input.value,
            sex=self.sex_select.value,
            age=self.age_input.value,
            weight=self.weight_input.value,
            image_vault_paths=vault_paths,
        )

    def _on_save_click(self, event) -> None:
        cfg = self._state.subject_config
        if cfg is None:
            self._show_message("请先填写所有必填项再保存。", level="warning")
            self._pending_overwrite_path = None
            return

        raw_path = (self.save_path_input.value or "").strip()
        target = (
            Path(raw_path)
            if raw_path
            else self._project_root / "monkeys" / f"{cfg.subject_id}.yaml"
        )

        if target.exists() and self._pending_overwrite_path != target:
            self._pending_overwrite_path = target
            self._show_message(
                f"文件已存在：{target}。再点一次将覆盖。",
                level="warning",
            )
            return

        try:
            save_subject_config(cfg, target)
        except OSError as exc:
            self._pending_overwrite_path = None
            self._show_message(f"保存失败：{exc}", level="danger")
            return

        self._pending_overwrite_path = None
        self._show_message(f"已保存到 {target}", level="success")

    def _show_message(self, text: str, *, level: str) -> None:
        self.save_message.alert_type = level
        self.save_message.object = text
        self.save_message.visible = True

    # ── Wizard step 2 ──

    def select_profile(self, yaml_path: Path) -> None:
        """Load a monkeys/*.yaml profile and show it read-only until "编辑档案"."""
        self.load_from_yaml(Path(yaml_path))
        self._highlight(Path(yaml_path).stem)
        cfg = self._state.subject_config
        if cfg is not None:
            vault = "、".join(f"`{p}`" for p in cfg.image_vault_paths) or "—"
            self.profile_summary.object = (
                f"#### {cfg.subject_id}\n\n"
                f"物种 *{cfg.species}* · 性别 {cfg.sex} · 年龄 `{cfg.age}` · "
                f"体重 {cfg.weight or '—'} · 刺激图片库 {vault}"
            )
        self.profile_summary.visible = True
        self.edit_btn.visible = True
        self.fields_box.visible = False

    def start_new_subject(self) -> None:
        """Open an empty form for an animal without a saved profile."""
        for widget in (
            self.subject_id_input,
            self.description_input,
            self.age_input,
            self.weight_input,
            self.image_vault_paths_input,
        ):
            widget.value = ""
        self._highlight(None)
        self.profile_summary.visible = False
        self.edit_btn.visible = False
        self.fields_box.visible = True

    def _highlight(self, stem: str | None) -> None:
        for name, btn in self.profile_buttons.items():
            btn.button_type = "primary" if name == stem else "light"
        self.new_subject_btn.button_type = "primary" if stem is None else "light"

    def wizard_panel(self) -> pn.viewable.Viewable:
        """Step-2 layout: profile cards, read-only summary, editable fields on demand."""
        return pn.Column(
            pn.pane.Markdown(
                "### 实验动物\n从 `monkeys/` 里已保存的档案中选择。信息会写进 NWB 的 Subject。"
            ),
            pn.Row(*self.profile_buttons.values(), self.new_subject_btn),
            self.profile_summary,
            self.edit_btn,
            self.fields_box,
            sizing_mode="stretch_width",
        )

    # ── Public API ──

    def load_from_yaml(self, yaml_path: Path) -> None:
        """Load subject config from a YAML file and fill widget values."""
        cfg = load_subject_config(yaml_path)
        self.apply_subject(cfg)

    def apply_subject(self, cfg: SubjectConfig) -> None:
        """Populate every widget from a SubjectConfig dataclass.

        Used by SessionLoader after restoring ``state.subject_config`` so the
        Subject Form reflects the loaded session. The widget watchers will
        then rebuild ``state.subject_config`` from the populated values, which
        is a no-op when the widgets are filled from the same dataclass.
        """
        self.subject_id_input.value = cfg.subject_id
        self.description_input.value = cfg.description
        self.species_input.value = cfg.species
        self.sex_select.value = cfg.sex
        self.age_input.value = cfg.age
        self.weight_input.value = cfg.weight
        self.image_vault_paths_input.value = "\n".join(str(p) for p in cfg.image_vault_paths)

    @staticmethod
    def _field(widget: pn.widgets.Widget, key: str) -> pn.Column:
        """Widget with its SubjectConfig key in small monospace below (ui_redesign §4.1)."""
        caption = pn.pane.Markdown(
            f"`{key}`", styles={"font-size": "11px", "color": "#8A8F99"}, margin=(-12, 10, 4, 10)
        )
        return pn.Column(widget, caption, margin=0, sizing_mode="stretch_width")

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("### 动物信息"),
            self.yaml_input.panel(),
            self._field(self.subject_id_input, "subject_id"),
            self._field(self.description_input, "description"),
            self._field(self.species_input, "species"),
            self._field(self.sex_select, "sex"),
            self._field(self.age_input, "age"),
            self._field(self.weight_input, "weight"),
            self._field(self.image_vault_paths_input, "image_vault_paths"),
            self.save_path_input.panel(),
            self.save_btn,
            self.save_message,
        )
