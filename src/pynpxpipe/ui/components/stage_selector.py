"""ui/components/stage_selector.py — Stage selection with dependency warnings."""

from __future__ import annotations

import panel as pn

from pynpxpipe.pipelines.constants import STAGE_ORDER
from pynpxpipe.ui.state import AppState

# Stages that depend on sort output being present
_SORT_DEPENDENTS = {"merge", "curate", "postprocess", "export"}

# Chinese display names; the checkbox label keeps the stage key for searchability.
_STAGE_LABELS: dict[str, str] = {
    "discover": "数据发现",
    "synchronize": "时间同步",
    "select_segments": "任务时段截取",
    "preprocess": "预处理",
    "sort": "Spike 排序",
    "merge": "自动合并",
    "curate": "质控筛选",
    "postprocess": "后处理",
    "export": "导出 NWB",
}

# Stages driven by a pipeline parameter instead of their checkbox (ui_redesign P0-3):
# merge runs iff ``merge.enabled`` is on in the Auto-Merge card.
_CONFIG_DRIVEN_STAGES = {"merge"}


class StageSelector:
    """Checkboxes for selecting which pipeline stages to run."""

    def __init__(self, state: AppState) -> None:
        self._state = state
        self.dependency_warning: str = ""

        self.stage_checkboxes: dict[str, pn.widgets.Checkbox] = {
            name: pn.widgets.Checkbox(
                name=f"{_STAGE_LABELS.get(name, name)}（{name}）",
                value=(name not in _CONFIG_DRIVEN_STAGES),
                disabled=name in _CONFIG_DRIVEN_STAGES,
            )
            for name in STAGE_ORDER
        }
        self.merge_note = pn.pane.Markdown(
            "merge 是否运行由参数「Auto-Merge」决定，请在参数中开启。",
            styles={"font-size": "12px"},
        )

        self.select_all_btn = pn.widgets.Button(name="全选", button_type="default")
        self.deselect_all_btn = pn.widgets.Button(name="全不选", button_type="default")

        for cb in self.stage_checkboxes.values():
            cb.param.watch(self._on_checkbox_change, "value")

        self.select_all_btn.param.watch(self._on_select_all, "clicks")
        self.deselect_all_btn.param.watch(self._on_deselect_all, "clicks")

        # Mirror merge.enabled whenever the pipeline config changes.
        state.param.watch(self._on_config_change, "pipeline_config")

        # Initialise state
        self._on_config_change()

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
                warnings.append(f"{stage} 依赖 sort 的输出，但 sort 未勾选")
        self.dependency_warning = "；".join(warnings)

    def _merge_enabled_in_config(self) -> bool:
        cfg = getattr(self._state, "pipeline_config", None)
        merge_cfg = getattr(cfg, "merge", None) if cfg is not None else None
        return bool(getattr(merge_cfg, "enabled", False))

    def _on_checkbox_change(self, event=None) -> None:
        self._sync_state()

    def _on_config_change(self, event=None) -> None:
        merge_cb = self.stage_checkboxes["merge"]
        enabled = self._merge_enabled_in_config()
        if merge_cb.value != enabled:
            merge_cb.value = enabled  # fires _on_checkbox_change → _sync_state
        else:
            self._sync_state()

    def _on_select_all(self, event=None) -> None:
        for name, cb in self.stage_checkboxes.items():
            if name not in _CONFIG_DRIVEN_STAGES:
                cb.value = True

    def _on_deselect_all(self, event=None) -> None:
        for name, cb in self.stage_checkboxes.items():
            if name not in _CONFIG_DRIVEN_STAGES:
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
            pn.pane.Markdown("### 要运行的阶段"),
            pn.Row(self.select_all_btn, self.deselect_all_btn),
            *self.stage_checkboxes.values(),
            self.merge_note,
            warning_pane,
        )
