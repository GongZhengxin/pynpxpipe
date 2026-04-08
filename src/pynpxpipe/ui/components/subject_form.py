"""ui/components/subject_form.py — Subject metadata form."""

from __future__ import annotations

from pathlib import Path

import panel as pn

from pynpxpipe.core.config import load_subject_config
from pynpxpipe.core.session import SubjectConfig
from pynpxpipe.ui.state import AppState

_REQUIRED_FIELDS = ("subject_id", "species", "age", "weight")


class SubjectForm:
    """Form for entering NWB subject metadata."""

    def __init__(self, state: AppState) -> None:
        self._state = state

        self.subject_id_input = pn.widgets.TextInput(name="Subject ID", placeholder="MaoDan")
        self.description_input = pn.widgets.TextInput(name="Description", placeholder="")
        self.species_input = pn.widgets.TextInput(name="Species", value="Macaca mulatta")
        self.sex_select = pn.widgets.Select(name="Sex", options=["M", "F", "U", "O"], value="M")
        self.age_input = pn.widgets.TextInput(name="Age (ISO 8601)", placeholder="P3Y")
        self.weight_input = pn.widgets.TextInput(name="Weight", placeholder="10kg")

        for widget in (
            self.subject_id_input,
            self.description_input,
            self.species_input,
            self.sex_select,
            self.age_input,
            self.weight_input,
        ):
            widget.param.watch(self._rebuild_config, "value")

    # ── Internal ──

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
        self._state.subject_config = SubjectConfig(
            subject_id=self.subject_id_input.value,
            description=self.description_input.value,
            species=self.species_input.value,
            sex=self.sex_select.value,
            age=self.age_input.value,
            weight=self.weight_input.value,
        )

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

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("### Subject Metadata"),
            self.subject_id_input,
            self.description_input,
            self.species_input,
            self.sex_select,
            self.age_input,
            self.weight_input,
        )
