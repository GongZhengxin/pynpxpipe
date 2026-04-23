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

        self.subject_id_input = pn.widgets.TextInput(name="Subject ID", placeholder="MaoDan")
        self.description_input = pn.widgets.TextInput(name="Description", placeholder="")
        self.species_input = pn.widgets.TextInput(name="Species", value="Macaca mulatta")
        self.sex_select = pn.widgets.Select(name="Sex", options=["M", "F", "U", "O"], value="M")
        self.age_input = pn.widgets.TextInput(name="Age (ISO 8601)", placeholder="P3Y")
        self.weight_input = pn.widgets.TextInput(name="Weight", placeholder="10kg")
        self.image_vault_paths_input = pn.widgets.TextAreaInput(
            name="Image Vault Paths (one per line, optional)",
            placeholder="/data/stimuli\n/mnt/shared/stim_library",
            height=90,
        )

        # ── YAML loader ──
        self.yaml_input = BrowsableInput(
            name="Subject YAML",
            placeholder="/path/to/monkey.yaml",
            file_pattern="*.yaml",
            only_files=True,
        )
        self.yaml_input.text_input.param.watch(self._on_yaml_input, "value")

        # ── YAML saver ──
        self.save_path_input = BrowsableInput(
            name="Save Path (optional)",
            placeholder="default: <project_root>/monkeys/<subject_id>.yaml",
            file_pattern="*.yaml",
            only_files=True,
        )
        self.save_btn = pn.widgets.Button(name="Save to monkeys/", button_type="success")
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
            self._show_message("Fill all required fields before saving.", level="warning")
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
                f"File exists at {target}. Click again to overwrite.",
                level="warning",
            )
            return

        try:
            save_subject_config(cfg, target)
        except OSError as exc:
            self._pending_overwrite_path = None
            self._show_message(f"Failed to save: {exc}", level="danger")
            return

        self._pending_overwrite_path = None
        self._show_message(f"Saved to {target}", level="success")

    def _show_message(self, text: str, *, level: str) -> None:
        self.save_message.alert_type = level
        self.save_message.object = text
        self.save_message.visible = True

    # ── Public API ──

    def load_from_yaml(self, yaml_path: Path) -> None:
        """Load subject config from a YAML file and fill widget values."""
        cfg = load_subject_config(yaml_path)
        self.subject_id_input.value = cfg.subject_id
        self.description_input.value = cfg.description
        self.species_input.value = cfg.species
        self.sex_select.value = cfg.sex
        self.age_input.value = cfg.age
        self.weight_input.value = cfg.weight
        self.image_vault_paths_input.value = "\n".join(
            str(p) for p in cfg.image_vault_paths
        )

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("### Subject Metadata"),
            self.yaml_input.panel(),
            self.subject_id_input,
            self.description_input,
            self.species_input,
            self.sex_select,
            self.age_input,
            self.weight_input,
            self.image_vault_paths_input,
            self.save_path_input.panel(),
            self.save_btn,
            self.save_message,
        )
