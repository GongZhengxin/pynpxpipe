"""ui/components/stage_selector.py — Stage selection with dependency warnings."""

from __future__ import annotations

import panel as pn

from pynpxpipe.pipelines.constants import STAGE_ORDER
from pynpxpipe.ui.state import AppState

# Stages that depend on sort output being present
_SORT_DEPENDENTS = {"synchronize", "curate", "postprocess", "export"}

# Stages that are off by default — opt-in only (irreversible side effects).
_OPT_IN_STAGES = {"merge"}


class StageSelector:
    """Checkboxes for selecting which pipeline stages to run."""

    def __init__(self, state: AppState) -> None:
        self._state = state
        self.dependency_warning: str = ""

        self.stage_checkboxes: dict[str, pn.widgets.Checkbox] = {
            name: pn.widgets.Checkbox(name=name, value=(name not in _OPT_IN_STAGES))
            for name in STAGE_ORDER
        }

        self.select_all_btn = pn.widgets.Button(name="Select All", button_type="default")
        self.deselect_all_btn = pn.widgets.Button(name="Deselect All", button_type="default")

        for cb in self.stage_checkboxes.values():
            cb.param.watch(self._on_checkbox_change, "value")

        self.select_all_btn.param.watch(self._on_select_all, "clicks")
        self.deselect_all_btn.param.watch(self._on_deselect_all, "clicks")

        # Re-evaluate warnings when pipeline_config (carrying merge.enabled) changes.
        state.param.watch(self._on_checkbox_change, "pipeline_config")

        # Initialise state
        self._sync_state()

    # ── Internal ──

    def _sync_state(self) -> None:
        selected = [name for name, cb in self.stage_checkboxes.items() if cb.value]
        self._state.selected_stages = selected
        self._update_dependency_warning(selected)

    def _update_dependency_warning(self, selected: list[str]) -> None:
        warnings = []
        sort_selected = "sort" in selected
        for stage in _SORT_DEPENDENTS:
            if stage in selected and not sort_selected:
                warnings.append(f"'{stage}' depends on sort output")
        if "merge" in selected and not self._merge_enabled_in_config():
            warnings.append(
                "'merge' stage selected but Auto-Merge is disabled in Pipeline "
                "parameters — stage will no-op"
            )
        self.dependency_warning = "; ".join(warnings)

    def _merge_enabled_in_config(self) -> bool:
        cfg = getattr(self._state, "pipeline_config", None)
        merge_cfg = getattr(cfg, "merge", None) if cfg is not None else None
        return bool(getattr(merge_cfg, "enabled", False))

    def _on_checkbox_change(self, event=None) -> None:
        self._sync_state()

    def _on_select_all(self, event=None) -> None:
        for cb in self.stage_checkboxes.values():
            cb.value = True

    def _on_deselect_all(self, event=None) -> None:
        for cb in self.stage_checkboxes.values():
            cb.value = False

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        warning_pane = pn.pane.Str("", styles={"color": "orange", "font-size": "12px"})

        @pn.depends(*(cb.param.value for cb in self.stage_checkboxes.values()), watch=True)
        def _update_warning(*args):
            warning_pane.object = self.dependency_warning

        # Also refresh warning pane when dependency_warning is recomputed via
        # pipeline_config changes (which don't flow through the checkbox deps above).
        def _refresh_from_config(event):
            warning_pane.object = self.dependency_warning

        self._state.param.watch(_refresh_from_config, "pipeline_config")

        return pn.Column(
            pn.pane.Markdown("### Stages to Run"),
            pn.Row(self.select_all_btn, self.deselect_all_btn),
            *self.stage_checkboxes.values(),
            warning_pane,
        )
