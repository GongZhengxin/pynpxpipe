"""ui/components/rerun_derivatives.py — Phase 2.5 rerun panel (A8).

Standalone widget for the Review tab: given an already-loaded ``output_dir``,
re-run Phase 2.5 derivatives without redoing Phase 1 (NWB write) or Phase 3
(raw-data append + verify). Useful when the original Phase 2.5 failed
non-fatally (e.g. ``KeyError 'stim_name'`` from an unresolvable BHV2 dataset
path) but the rest of the pipeline succeeded.

Spec: ``docs/specs/ui.md`` §3.12.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import panel as pn

from pynpxpipe.core.config import DerivativesConfig
from pynpxpipe.ui.state import AppState

RunFn = Callable[[Path, DerivativesConfig], Path]


def _default_run_fn(output_dir: Path, derivatives_cfg: DerivativesConfig) -> Path:
    """Production rerun implementation: load session + config, invoke ExportStage.

    Args:
        output_dir: Pipeline output directory containing ``session.json`` and
            ``checkpoints/export.json``.
        derivatives_cfg: DerivativesConfig overriding the on-disk
            ``used_pipeline.yaml`` (when present) export.derivatives section.

    Returns:
        ``{output_dir}/07_derivatives``.
    """
    from pynpxpipe.core.config import load_pipeline_config
    from pynpxpipe.core.session import SessionManager
    from pynpxpipe.stages.export import ExportStage

    session = SessionManager.load(output_dir)
    used_pipeline = output_dir / "used_pipeline.yaml"
    pipeline_cfg = load_pipeline_config(used_pipeline if used_pipeline.exists() else None)
    pipeline_cfg.export.derivatives = derivatives_cfg
    session.config = pipeline_cfg

    ExportStage(session).rerun_phase2_only()
    return output_dir / "07_derivatives"


class RerunDerivatives:
    """Phase 2.5 rerun control: button + status alert.

    Args:
        state: Shared AppState instance.
        run_fn: ``(output_dir, derivatives_cfg) -> derivatives_path``.
            Tests inject a synchronous mock; production uses
            :func:`_default_run_fn` which spawns no extra threads (the panel
            itself wraps the call in a daemon thread).
    """

    def __init__(self, state: AppState, *, run_fn: RunFn | None = None) -> None:
        self._state = state
        self._run_fn = run_fn or _default_run_fn
        self._thread: threading.Thread | None = None

        self.run_btn = pn.widgets.Button(
            name="Rerun derivatives",
            button_type="primary",
            disabled=state.output_dir is None,
        )
        # Production: run in a daemon thread so UI stays responsive during the
        # few-minutes Phase 2.5 work. Tests bypass this by calling _on_click
        # directly for synchronous, deterministic assertions.
        self.run_btn.on_click(self.dispatch_async)

        self.message_pane = pn.pane.Alert(
            "", alert_type="light", visible=False, sizing_mode="stretch_width"
        )

        # React to output_dir changes coming from SessionLoader.
        state.param.watch(self._on_output_dir_change, "output_dir")

    # ── Internal ──

    def _on_output_dir_change(self, event) -> None:
        """Enable / disable button when state.output_dir flips between set/None."""
        new_value = event.new
        is_set = bool(new_value) and str(new_value).strip() != ""
        self.run_btn.disabled = not is_set

    def _resolve_derivatives_cfg(self) -> DerivativesConfig:
        """Read derivatives sub-config from state.pipeline_config (if any)."""
        pcfg = getattr(self._state, "pipeline_config", None)
        if pcfg is None:
            return DerivativesConfig()
        try:
            return pcfg.export.derivatives
        except AttributeError:
            return DerivativesConfig()

    def _show_message(self, text: str, *, level: str) -> None:
        self.message_pane.alert_type = level
        self.message_pane.object = text
        self.message_pane.visible = True

    def _on_click(self, event) -> None:
        """Validate inputs, then dispatch run_fn (synchronously here; production
        wraps in a daemon thread via :meth:`_dispatch_async`)."""
        output_dir_raw = self._state.output_dir
        if not output_dir_raw or not str(output_dir_raw).strip():
            self._show_message("Please load an output directory first.", level="danger")
            return

        output_dir = Path(str(output_dir_raw))
        if not output_dir.exists():
            self._show_message(f"Output directory not found: {output_dir}", level="danger")
            return

        derivatives_cfg = self._resolve_derivatives_cfg()

        # Synchronous path: run inline (used by tests + as the body of the
        # async wrapper). UI freezing is bounded by the few-minutes work the
        # caller is doing; production callers should wrap _on_click in a
        # daemon thread via _dispatch_async if responsiveness matters.
        self._show_message("Rerunning Phase 2.5 derivatives…", level="info")
        self.run_btn.disabled = True
        try:
            result_path = self._run_fn(output_dir, derivatives_cfg)
            self._show_message(f"Wrote derivatives to {result_path}", level="success")
        except Exception as exc:  # noqa: BLE001 — surface arbitrary errors to UI
            self._show_message(f"{type(exc).__name__}: {exc}", level="danger")
        finally:
            self.run_btn.disabled = self._state.output_dir is None

    def dispatch_async(self, event=None) -> None:
        """Production wrapper: run :meth:`_on_click` in a daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._on_click, args=(event,), daemon=True)
        self._thread.start()

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("## Re-run Phase 2.5 Derivatives"),
            pn.pane.Str(
                "Regenerate 07_derivatives/ from the loaded NWB without redoing "
                "Phase 1 (NWB write) or Phase 3 (raw data append + verify). "
                "Use after a Phase 2.5 failure leaves derivatives missing.",
                styles={"font-size": "13px", "color": "#666"},
            ),
            self.run_btn,
            self.message_pane,
            sizing_mode="stretch_width",
        )
