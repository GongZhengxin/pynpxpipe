"""ui/components/preset_bar.py — Parameter presets and diff card (ui_redesign.md §4.2 P0-2).

Lists ``config/pipeline*.yaml`` + ``config/sorting*.yaml`` presets paired by
suffix, applies them to PipelineForm / SortingForm, imports and exports YAML,
and shows which fields differ from the selected preset with per-field restore.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import panel as pn
import yaml

from pynpxpipe.core.config import (
    PipelineConfig,
    SortingConfig,
    load_pipeline_config,
    load_sorting_config,
    save_pipeline_config,
    save_sorting_config,
)
from pynpxpipe.core.errors import ConfigError
from pynpxpipe.ui.components import pipeline_form as _pipeline_form_mod
from pynpxpipe.ui.components import sorting_form as _sorting_form_mod
from pynpxpipe.ui.components.browsable_input import BrowsableInput
from pynpxpipe.ui.state import AppState

_DEFAULT_PRESET = "默认"
_STARTUP = "__startup__"
_CHANGED_CLASS = "pynpx-changed"
_CHANGED_CSS = f":host(.{_CHANGED_CLASS}) {{ border-left: 3px solid #D99A1E; padding-left: 6px; }}"
_PRESET_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class Preset:
    """A pipeline/sorting YAML pair found in the config directory."""

    name: str
    pipeline_path: Path
    sorting_path: Path
    pipeline_fallback: bool
    sorting_fallback: bool

    @property
    def label(self) -> str:
        if self.name == _DEFAULT_PRESET:
            return f"{_DEFAULT_PRESET}（pipeline.yaml + sorting.yaml）"
        notes = [
            f"{kind} 回退到 {kind}.yaml"
            for kind, fallback in (
                ("pipeline", self.pipeline_fallback),
                ("sorting", self.sorting_fallback),
            )
            if fallback
        ]
        return f"{self.name}（{'，'.join(notes)}）" if notes else self.name


def _default_config_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "config"


def list_presets(config_dir: Path) -> list[Preset]:
    """Pair ``pipeline_<S>.yaml`` with ``sorting_<S>.yaml`` by suffix ``S``.

    A suffix that only has one of the two files falls back to the un-suffixed
    ``pipeline.yaml`` / ``sorting.yaml`` for the other half.

    Args:
        config_dir: Directory holding the preset YAML files.

    Returns:
        The default preset first (if both base files exist), then suffixes sorted by name.
    """
    config_dir = Path(config_dir)
    suffixes: set[str] = set()
    for kind in ("pipeline", "sorting"):
        for path in config_dir.glob(f"{kind}_*.yaml"):
            suffixes.add(path.stem[len(kind) + 1 :])

    def resolve(kind: str, suffix: str) -> tuple[Path, bool]:
        own = config_dir / f"{kind}_{suffix}.yaml"
        return (own, False) if own.exists() else (config_dir / f"{kind}.yaml", True)

    presets: list[Preset] = []
    if (config_dir / "pipeline.yaml").exists() and (config_dir / "sorting.yaml").exists():
        presets.append(
            Preset(
                _DEFAULT_PRESET,
                config_dir / "pipeline.yaml",
                config_dir / "sorting.yaml",
                False,
                False,
            )
        )
    for suffix in sorted(suffixes):
        pipeline_path, pipeline_fallback = resolve("pipeline", suffix)
        sorting_path, sorting_fallback = resolve("sorting", suffix)
        presets.append(
            Preset(suffix, pipeline_path, sorting_path, pipeline_fallback, sorting_fallback)
        )
    return presets


def flatten_config(cfg: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a config dataclass to ``{dotted.path: leaf_value}``.

    Walks dataclass fields (rather than the plain dict from ``_config_to_dict``)
    so that dict-valued fields such as ``import_cfg.paths`` stay a single leaf,
    matching the form's field-to-widget map.
    """
    flat: dict[str, Any] = {}
    for field in dataclasses.fields(cfg):
        value = getattr(cfg, field.name)
        key = f"{prefix}{field.name}"
        if dataclasses.is_dataclass(value):
            flat.update(flatten_config(value, f"{key}."))
        else:
            flat[key] = value
    return flat


def diff_configs(baseline: Any, current: Any) -> list[tuple[str, Any, Any]]:
    """Compare two configs field by field.

    Args:
        baseline: The preset config.
        current: The config currently held by the form.

    Returns:
        ``[(dotted_key, baseline_value, current_value)]`` for every differing leaf,
        in dataclass field order.
    """
    base, cur = flatten_config(baseline), flatten_config(current)
    return [(key, base[key], cur.get(key)) for key in base if base[key] != cur.get(key)]


def _replace_path(obj: Any, parts: list[str], value: Any) -> Any:
    if not parts:
        return value
    head, rest = parts[0], parts[1:]
    return dataclasses.replace(obj, **{head: _replace_path(getattr(obj, head), rest, value)})


def _fmt(value: Any) -> str:
    return "`null`" if value is None else f"`{value!r}`"


class PresetBar:
    """Preset selector + import/export + "changed vs preset" diff card."""

    def __init__(
        self,
        state: AppState,
        pipeline_form: Any,
        sorting_form: Any,
        *,
        config_dir: Path | None = None,
    ) -> None:
        self._state = state
        self._forms = {"pipeline": pipeline_form, "sorting": sorting_form}
        self._maps = {
            "pipeline": _pipeline_form_mod.FIELD_TO_WIDGET,
            "sorting": _sorting_form_mod.FIELD_TO_WIDGET,
        }
        self._config_dir = Path(config_dir) if config_dir else _default_config_dir()
        self._startup = {"pipeline": state.pipeline_config, "sorting": state.sorting_config}
        self._baseline: dict[str, Any] = dict(self._startup)
        self._baseline_label = "启动时的表单值"
        self._presets: dict[str, Preset] = {}
        self.diff: list[tuple[str, Any, Any]] = []

        self.preset_select = pn.widgets.Select(name="参数预设", options={}, width=320)
        self.note = pn.pane.Markdown("", visible=False)
        self.badge = pn.pane.Markdown("")
        self.message = pn.pane.Alert("", alert_type="info", visible=False)
        self.import_kind = pn.widgets.RadioButtonGroup(
            options={"Pipeline": "pipeline", "Sorting": "sorting"}, value="pipeline"
        )
        self.import_path = BrowsableInput(
            name="YAML 文件", placeholder="/path/to/config.yaml", file_pattern="*.yaml"
        )
        self.import_btn = pn.widgets.Button(name="导入 YAML…")
        self.export_dir = BrowsableInput(name="导出目录", file_pattern="*", only_files=False)
        self.export_dir.value = str(self._config_dir)
        self.export_name = pn.widgets.TextInput(name="预设名（文件后缀）", placeholder="例如 E4")
        self.export_btn = pn.widgets.Button(name="导出为 YAML")
        self.diff_title = pn.pane.Markdown("")
        self.diff_list = pn.Column(sizing_mode="stretch_width")

        self._refresh_presets()
        self.preset_select.param.watch(self._on_select, "value")
        self.import_btn.on_click(self._on_import)
        self.export_btn.on_click(self._on_export)
        state.param.watch(self._refresh_diff, ["pipeline_config", "sorting_config"])
        self._refresh_diff()

    # ── Presets ──

    def _refresh_presets(self) -> None:
        self._presets = {p.name: p for p in list_presets(self._config_dir)}
        options = {"启动时的表单值": _STARTUP}
        options.update({p.label: p.name for p in self._presets.values()})
        current = self.preset_select.value
        self.preset_select.options = options
        self.preset_select.value = current if current in options.values() else _STARTUP

    def _on_select(self, event) -> None:
        if event.new == _STARTUP:
            self._apply(self._startup, "启动时的表单值")
            self.note.visible = False
            return
        preset = self._presets.get(event.new)
        if preset is None:
            return
        try:
            configs = {
                "pipeline": load_pipeline_config(preset.pipeline_path),
                "sorting": load_sorting_config(preset.sorting_path),
            }
        except (ConfigError, OSError, yaml.YAMLError) as exc:
            self._show("danger", f"预设 {preset.name} 读取失败：{exc}")
            return
        fallbacks = [
            f"没有 `{kind}_{preset.name}.yaml`，{kind} 参数使用 `{kind}.yaml`。"
            for kind, fb in (
                ("pipeline", preset.pipeline_fallback),
                ("sorting", preset.sorting_fallback),
            )
            if fb
        ]
        self.note.object = " ".join(fallbacks)
        self.note.visible = bool(fallbacks)
        self._apply(configs, f"{preset.name} 预设")
        self.message.visible = False

    def _apply(self, configs: dict[str, Any], label: str) -> None:
        """Make *configs* (one or both kinds) the diff baseline and load them into the forms."""
        self._baseline.update(configs)
        self._baseline_label = label
        if "pipeline" in configs:
            self._forms["pipeline"].apply_pipeline(configs["pipeline"])
        if "sorting" in configs:
            self._forms["sorting"].apply_sorting(configs["sorting"])
        self._refresh_diff()

    # ── Import / export ──

    def _on_import(self, event=None) -> None:
        kind = self.import_kind.value
        raw = (self.import_path.value or "").strip()
        path = Path(raw)
        if not raw or not path.is_file():
            self._show("danger", f"找不到要导入的文件：{raw or '（未填写）'}")
            return
        loader = load_pipeline_config if kind == "pipeline" else load_sorting_config
        try:
            cfg = loader(path)
        except (ConfigError, OSError, yaml.YAMLError) as exc:
            self._show("danger", f"导入失败，{path.name} 不是有效的 {kind} 配置：{exc}")
            return
        self._apply({kind: cfg}, f"导入的 {path.name}")
        self._show("success", f"已导入 {path.name}（{kind}）。")

    def _on_export(self, event=None) -> None:
        name = (self.export_name.value or "").strip()
        if not _PRESET_NAME_RE.match(name):
            self._show("danger", "预设名只能包含字母、数字、下划线和连字符。")
            return
        out_dir = Path((self.export_dir.value or "").strip() or self._config_dir)
        targets = (out_dir / f"pipeline_{name}.yaml", out_dir / f"sorting_{name}.yaml")
        existing = [str(p) for p in targets if p.exists()]
        if existing:
            self._show(
                "danger", "文件已存在，未写入：" + "，".join(existing) + "。请换一个预设名。"
            )
            return
        try:
            save_pipeline_config(self._state.pipeline_config, targets[0])
            save_sorting_config(self._state.sorting_config, targets[1])
        except OSError as exc:
            self._show("danger", f"导出失败：{exc}")
            return
        if out_dir.resolve() == self._config_dir.resolve():
            self._refresh_presets()
        self._show("success", "已导出：" + "，".join(str(p) for p in targets))

    def _show(self, alert_type: str, text: str) -> None:
        self.message.alert_type = alert_type
        self.message.object = text
        self.message.visible = True

    # ── Diff ──

    def _current(self, kind: str) -> PipelineConfig | SortingConfig | None:
        return self._state.pipeline_config if kind == "pipeline" else self._state.sorting_config

    def _refresh_diff(self, event=None) -> None:
        per_kind: dict[str, list[tuple[str, Any, Any]]] = {}
        for kind in ("pipeline", "sorting"):
            base, cur = self._baseline.get(kind), self._current(kind)
            per_kind[kind] = diff_configs(base, cur) if base is not None and cur is not None else []
        diff = per_kind["pipeline"] + per_kind["sorting"]
        self.badge.object = f"**已改 {len(diff)} 项**"
        self.diff_title.object = f"**与{self._baseline_label}的差异**"
        if diff != self.diff or not self.diff_list.objects and diff:
            self.diff = diff
            self.diff_list.objects = [self._diff_row(*entry) for entry in diff] or [
                pn.pane.Markdown("没有改动。")
            ]
        for kind, entries in per_kind.items():
            self._mark(kind, {key for key, _, _ in entries})

    def _diff_row(self, key: str, preset_value: Any, current_value: Any) -> pn.Row:
        button = pn.widgets.Button(name="恢复", tags=[key], width=70)
        button.on_click(lambda event, k=key: self.restore(k))
        return pn.Row(
            pn.pane.Markdown(f"`{key}`：{_fmt(preset_value)} → {_fmt(current_value)}"),
            button,
            sizing_mode="stretch_width",
        )

    def _mark(self, kind: str, changed: set[str]) -> None:
        form, mapping = self._forms[kind], self._maps[kind]
        changed_attrs = {mapping.get(key) for key in changed}
        for attr in {a for a in mapping.values() if a}:
            widget = getattr(form, attr, None)
            if widget is None or not hasattr(widget, "css_classes"):
                continue
            classes = [c for c in widget.css_classes if c != _CHANGED_CLASS]
            if attr in changed_attrs:
                classes.append(_CHANGED_CLASS)
                if _CHANGED_CSS not in widget.stylesheets:
                    widget.stylesheets = [*widget.stylesheets, _CHANGED_CSS]
            if classes != widget.css_classes:
                widget.css_classes = classes

    def restore(self, key: str) -> None:
        """Reset one dotted field back to the selected preset's value.

        Args:
            key: Dotted config path as listed in :attr:`diff`.
        """
        for kind in ("pipeline", "sorting"):
            base = self._baseline.get(kind)
            if base is None or key not in flatten_config(base):
                continue
            new = _replace_path(self._current(kind), key.split("."), flatten_config(base)[key])
            if kind == "pipeline":
                self._forms["pipeline"].apply_pipeline(new)
            else:
                self._forms["sorting"].apply_sorting(new)
            self._refresh_diff()
            return

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.Column(
                pn.pane.Markdown("### 参数预设"),
                pn.Row(self.preset_select, self.badge),
                self.note,
                sizing_mode="stretch_width",
            ),
            pn.Card(
                self.import_kind,
                self.import_path.panel(),
                self.import_btn,
                pn.layout.Divider(),
                self.export_dir.panel(),
                self.export_name,
                self.export_btn,
                title="导入 / 导出 YAML",
                collapsed=True,
                sizing_mode="stretch_width",
            ),
            self.message,
            pn.Card(
                self.diff_title,
                self.diff_list,
                title="与预设的差异",
                collapsed=False,
                sizing_mode="stretch_width",
            ),
            sizing_mode="stretch_width",
        )
