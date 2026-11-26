"""ui/components/status_view.py — Stage status display and "rerun from this stage".

Shows the checkpoint-based completion status of every pipeline stage. Each row
has a "从此阶段重跑…" button that opens a confirmation dialog (ui_redesign.md
§4.2 P0-4) listing the checkpoint files of that stage **and every downstream
stage** that will be cleared, the upstream results that are kept, and the
parameter changes since the last run. Nothing is deleted until the user confirms.

``get_status_fn`` is injected for testability.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import panel as pn

from pynpxpipe.pipelines.constants import PER_PROBE_STAGES, STAGE_ORDER
from pynpxpipe.ui.state import AppState

# Status → display style mapping
_STATUS_STYLES: dict[str, str] = {
    "completed": "color: green; font-weight: bold",
    "failed": "color: red; font-weight: bold",
    "pending": "color: gray",
}

# Stages that read the preprocessed Zarr; the runner deletes it after postprocess
# (preprocess.delete_zarr_after_postprocess), so rerunning them needs preprocess too.
_ZARR_CONSUMERS = ("sort", "merge", "curate", "postprocess")
_PREPROCESSED_DIR = "01_preprocessed"


@dataclass
class RerunPlan:
    """What a "rerun from stage" would clear and keep.

    Attributes:
        stage: Stage the user picked.
        probe_id: Probe the rerun is limited to, or None for all probes.
        clear: ``(stage, probe_id | None, path)`` for each existing checkpoint to delete.
        keep: Upstream stages whose results stay untouched.
        needs_preprocess: Probes whose Zarr is gone, so preprocess is cleared too.
    """

    stage: str
    probe_id: str | None
    clear: list[tuple[str, str | None, Path]] = field(default_factory=list)
    keep: list[str] = field(default_factory=list)
    needs_preprocess: list[str] = field(default_factory=list)


def _probe_ids(output_dir: Path) -> list[str]:
    ids = set()
    cp_dir = output_dir / "checkpoints"
    for stage in PER_PROBE_STAGES:
        ids.update(p.stem[len(stage) + 1 :] for p in cp_dir.glob(f"{stage}_*.json"))
    ids.update(p.stem for p in (output_dir / _PREPROCESSED_DIR).glob("*.zarr"))
    return sorted(ids)


def plan_rerun(output_dir: Path, stage: str, probe_id: str | None = None) -> RerunPlan:
    """Work out which checkpoint files a rerun from *stage* must delete.

    The stage and all downstream stages are cleared (otherwise the runner would
    skip downstream stages whose results no longer match). With *probe_id*, only
    that probe's per-probe checkpoints are cleared, plus the stage-level
    aggregate files that would otherwise mark the whole stage complete.

    Args:
        output_dir: Session output root.
        stage: Stage to rerun from (must be in STAGE_ORDER).
        probe_id: Limit per-probe stages to this probe; None for all probes.

    Returns:
        The RerunPlan; only files that currently exist are listed.
    """
    output_dir = Path(output_dir)
    cp_dir = output_dir / "checkpoints"
    probes = [probe_id] if probe_id else _probe_ids(output_dir)
    start = STAGE_ORDER.index(stage)
    plan = RerunPlan(stage, probe_id)

    if stage in _ZARR_CONSUMERS:
        plan.needs_preprocess = [
            pid
            for pid in probes
            if (cp_dir / f"preprocess_{pid}.json").exists()
            and not (output_dir / _PREPROCESSED_DIR / f"{pid}.zarr").exists()
        ]
    if plan.needs_preprocess:
        start = STAGE_ORDER.index("preprocess")
    plan.keep = STAGE_ORDER[:start]

    for name in STAGE_ORDER[start:]:
        candidates: list[tuple[str | None, Path]] = [(None, cp_dir / f"{name}.json")]
        if name in PER_PROBE_STAGES:
            scope = probes
            if name == "preprocess" and stage != "preprocess":
                scope = plan.needs_preprocess
            candidates += [(pid, cp_dir / f"{name}_{pid}.json") for pid in scope]
        plan.clear += [(name, pid, path) for pid, path in candidates if path.exists()]
    return plan


class StatusView:
    """Displays pipeline stage status and offers a confirmed "rerun from stage".

    Args:
        state: Shared AppState instance.
        get_status_fn: Callable(output_dir) -> dict[str, str]. Defaults to
            reading saved checkpoint files in the selected directory.
    """

    def __init__(
        self,
        state: AppState,
        get_status_fn: Callable[[str], dict[str, str]] | None = None,
    ) -> None:
        self._state = state
        self._get_status_fn = get_status_fn or self._default_get_status
        self._open_modal: Callable[[], None] = lambda: None
        self._close_modal: Callable[[], None] = lambda: None

        # ── Widgets ──
        self.message_pane = pn.pane.Str(
            "设置输出目录（output_dir）后点击「读取状态」。",
            styles={"font-size": "13px"},
        )
        self.load_btn = pn.widgets.Button(name="读取状态", button_type="primary")
        self.load_btn.on_click(self._on_load_click)

        # stage_rows: {stage_name: {"status_text": HTML, "reset_btn": Button, "row": Row}}
        self.stage_rows: dict[str, dict] = {}
        self._table_container = pn.Column()

        # ── Rerun confirmation dialog (rendered in the template's modal area) ──
        self.rerun_plan: RerunPlan | None = None
        self.rerun_title = pn.pane.Markdown("")
        self.rerun_scope = pn.widgets.Select(name="范围", options={}, visible=False)
        self.rerun_clear_pane = pn.pane.Markdown("")
        self.rerun_warning = pn.pane.Alert("", alert_type="warning", visible=False)
        self.rerun_keep_pane = pn.pane.Markdown("")
        self.rerun_params_pane = pn.pane.Markdown("")
        self.rerun_cancel_btn = pn.widgets.Button(name="取消")
        self.rerun_confirm_btn = pn.widgets.Button(name="确认清除检查点", button_type="danger")
        self.rerun_dialog = pn.Column(
            self.rerun_title,
            self.rerun_scope,
            self.rerun_clear_pane,
            self.rerun_warning,
            self.rerun_keep_pane,
            self.rerun_params_pane,
            pn.Row(self.rerun_cancel_btn, self.rerun_confirm_btn),
            visible=False,
            sizing_mode="stretch_width",
        )
        self.rerun_scope.param.watch(self._on_scope_change, "value")
        self.rerun_cancel_btn.on_click(lambda event: self._close_rerun())
        self.rerun_confirm_btn.on_click(lambda event: self.confirm_rerun())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_status(self) -> None:
        """Fetch status from output_dir and rebuild the stage table."""
        output_dir = self._state.output_dir
        if not output_dir:
            self.message_pane.object = "尚未设置输出目录（output_dir）。"
            return

        try:
            statuses = self._get_status_fn(output_dir)
        except Exception as exc:  # noqa: BLE001
            self.message_pane.object = str(exc)
            return

        self.message_pane.object = ""
        self._build_table(statuses)

    def set_modal_handlers(self, open_fn: Callable[[], None], close_fn: Callable[[], None]) -> None:
        """Wire the dialog to a template modal (``template.open_modal`` / ``close_modal``).

        Args:
            open_fn: Called after the dialog content is prepared.
            close_fn: Called when the dialog is dismissed or confirmed.
        """
        self._open_modal, self._close_modal = open_fn, close_fn

    def open_rerun(self, stage_name: str) -> None:
        """Prepare and show the confirmation dialog for rerunning from *stage_name*.

        Args:
            stage_name: Stage the user clicked. Nothing is deleted here.
        """
        output_dir = self._state.output_dir
        if not output_dir:
            return
        self._rerun_stage = stage_name
        probes = _probe_ids(Path(output_dir))
        per_probe = stage_name in PER_PROBE_STAGES and len(probes) > 1
        self.rerun_scope.options = {"全部探针": "", **{pid: pid for pid in probes}}
        self.rerun_scope.value = ""
        self.rerun_scope.visible = per_probe
        self._refresh_plan()
        self.rerun_dialog.visible = True
        self._open_modal()

    def confirm_rerun(self) -> None:
        """Delete the planned checkpoints, close the dialog and refresh the table."""
        from pynpxpipe.core.checkpoint import CheckpointManager

        output_dir = self._state.output_dir
        if self.rerun_plan is None or not output_dir:
            return
        manager = CheckpointManager(Path(output_dir))
        for stage, probe_id, _ in self.rerun_plan.clear:
            manager.clear(stage, probe_id)
        self._close_rerun()
        self.load_status()

    def panel(self) -> pn.viewable.Viewable:
        """Return the Panel layout for this component."""
        return pn.Column(
            pn.pane.Markdown("## 阶段状态"),
            pn.Row(self.load_btn),
            self.message_pane,
            self._table_container,
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_load_click(self, event) -> None:
        """Handle Load button click."""
        self.load_status()

    def _on_reset_click(self, stage_name: str) -> None:
        self.open_rerun(stage_name)

    def _on_scope_change(self, event) -> None:
        if self.rerun_dialog.visible:
            self._refresh_plan()

    def _close_rerun(self) -> None:
        self.rerun_dialog.visible = False
        self.rerun_plan = None
        self._close_modal()

    # ------------------------------------------------------------------
    # Dialog content
    # ------------------------------------------------------------------

    def _refresh_plan(self) -> None:
        root = Path(self._state.output_dir)
        stage = self._rerun_stage
        probe_id = self.rerun_scope.value or None
        plan = plan_rerun(root, stage, probe_id)
        self.rerun_plan = plan

        scope = f"探针 {probe_id}" if probe_id else "全部探针"
        self.rerun_title.object = f"### 从 {stage} 重跑（{scope}）"
        if plan.clear:
            lines = [f"- `{path.relative_to(root).as_posix()}`" for _, _, path in plan.clear]
            self.rerun_clear_pane.object = "**将清除以下检查点**\n\n" + "\n".join(lines)
        else:
            self.rerun_clear_pane.object = "**将清除**：没有已存在的检查点。"
        if plan.needs_preprocess:
            self.rerun_warning.object = (
                f"{', '.join(plan.needs_preprocess)} 的预处理 Zarr 已删除，"
                "需要连同 preprocess 一起重跑；已把 preprocess 加入清除列表。"
            )
        self.rerun_warning.visible = bool(plan.needs_preprocess)
        self.rerun_keep_pane.object = (
            "**将保留**：" + "、".join(plan.keep) if plan.keep else "**将保留**：无（从头重跑）"
        )
        self.rerun_params_pane.object = self._param_changes(root)

    def _param_changes(self, root: Path) -> str:
        from pynpxpipe.core.config import load_pipeline_config, load_sorting_config
        from pynpxpipe.ui.components.preset_bar import diff_configs

        lines, missing = [], []
        for name, loader, current in (
            ("used_pipeline.yaml", load_pipeline_config, self._state.pipeline_config),
            ("used_sorting.yaml", load_sorting_config, self._state.sorting_config),
        ):
            path = root / name
            if not path.exists():
                missing.append(name)
                continue
            if current is None:
                continue
            try:
                used = loader(path)
            except Exception as exc:  # noqa: BLE001
                lines.append(f"- `{name}` 无法读取：{exc}")
                continue
            lines += [
                f"- `{key}`：`{old!r}` → `{new!r}`" for key, old, new in diff_configs(used, current)
            ]
        text = "**本次参数变化**（当前表单 vs 上次运行）\n\n"
        text += "\n".join(lines) if lines else "与上次运行一致。"
        if missing:
            text += "\n\n找不到 " + "、".join(f"`{m}`" for m in missing) + "，无法比较。"
        return text

    # ------------------------------------------------------------------
    # Table building
    # ------------------------------------------------------------------

    def _build_table(self, statuses: dict[str, str]) -> None:
        """Build the stage status table from a status dict."""
        self.stage_rows.clear()
        rows = []

        for stage_name in STAGE_ORDER:
            status = statuses.get(stage_name, "pending")
            style = _STATUS_STYLES.get(
                status.split()[0] if " " in status else status,
                "color: orange",
            )

            status_text = pn.pane.HTML(
                f'<span style="{style}">{status}</span>',
                styles={"min-width": "200px"},
            )
            reset_btn = pn.widgets.Button(name="从此阶段重跑…", button_type="warning", width=130)
            reset_btn.on_click(lambda event, sn=stage_name: self._on_reset_click(sn))

            stage_label = pn.pane.Str(
                stage_name,
                styles={"font-weight": "bold", "min-width": "120px"},
            )

            row = pn.Row(stage_label, status_text, reset_btn)
            self.stage_rows[stage_name] = {
                "status_text": status_text,
                "reset_btn": reset_btn,
                "row": row,
            }
            rows.append(row)

        self._table_container.clear()
        self._table_container.extend(rows)

    # ------------------------------------------------------------------
    # Default implementations (production wiring)
    # ------------------------------------------------------------------

    @staticmethod
    def _default_get_status(output_dir: str) -> dict[str, str]:
        """Inspect the selected output root, even if it has moved since recording."""
        from pynpxpipe.core.session import SessionManager
        from pynpxpipe.pipelines.status import read_pipeline_status

        root = Path(output_dir)
        session = SessionManager.load(root)
        return read_pipeline_status(root, [p.probe_id for p in session.probes])
