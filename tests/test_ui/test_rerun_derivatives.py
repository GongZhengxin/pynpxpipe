"""Tests for ui/components/rerun_derivatives.py — Phase 2.5 rerun panel (A8)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import panel as pn
import pytest

from pynpxpipe.core.config import (
    DerivativesConfig,
    ExportConfig,
    PipelineConfig,
)
from pynpxpipe.core.errors import ExportError
from pynpxpipe.ui.state import AppState


@pytest.fixture()
def state():
    return AppState()


def _make_run_fn(return_path: Path, raises: Exception | None = None) -> MagicMock:
    """Synchronous run_fn for tests; records calls and either returns or raises."""
    mock = MagicMock()
    if raises is not None:
        mock.side_effect = raises
    else:
        mock.return_value = return_path
    return mock


# ---------------------------------------------------------------------------
# Construction & widget state
# ---------------------------------------------------------------------------


class TestRerunDerivativesConstruction:
    def test_creates_panel_layout(self, state):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        panel = RerunDerivatives(state).panel()
        assert isinstance(panel, pn.viewable.Viewable)

    def test_button_disabled_when_output_dir_missing(self, state):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        panel = RerunDerivatives(state)
        assert panel.run_btn.disabled is True

    def test_button_enables_after_output_dir_set(self, state, tmp_path):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        panel = RerunDerivatives(state)
        state.output_dir = str(tmp_path)
        assert panel.run_btn.disabled is False

    def test_button_re_disables_when_output_dir_cleared(self, state, tmp_path):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        panel = RerunDerivatives(state)
        state.output_dir = str(tmp_path)
        assert panel.run_btn.disabled is False
        state.output_dir = None
        assert panel.run_btn.disabled is True


# ---------------------------------------------------------------------------
# run_fn dispatch
# ---------------------------------------------------------------------------


class TestRerunDerivativesDispatch:
    def test_click_calls_run_fn_with_output_dir(self, state, tmp_path):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        derivatives_dir = tmp_path / "07_derivatives"
        run_fn = _make_run_fn(derivatives_dir)
        panel = RerunDerivatives(state, run_fn=run_fn)
        state.output_dir = str(tmp_path)
        panel._on_click(None)

        run_fn.assert_called_once()
        call_path, call_cfg = run_fn.call_args.args
        assert call_path == Path(str(tmp_path))
        assert isinstance(call_cfg, DerivativesConfig)

    def test_click_uses_pipeline_config_derivatives_when_present(self, state, tmp_path):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        run_fn = _make_run_fn(tmp_path / "07_derivatives")
        panel = RerunDerivatives(state, run_fn=run_fn)
        state.output_dir = str(tmp_path)
        custom_cfg = DerivativesConfig(
            enabled=True,
            pre_onset_ms=70.0,
            post_onset_ms=400.0,
            bin_size_ms=2.5,
            n_jobs=4,
        )
        state.pipeline_config = PipelineConfig(export=ExportConfig(derivatives=custom_cfg))
        panel._on_click(None)

        _, called_cfg = run_fn.call_args.args
        assert called_cfg.bin_size_ms == 2.5
        assert called_cfg.pre_onset_ms == 70.0
        assert called_cfg.n_jobs == 4

    def test_click_falls_back_to_default_derivatives_when_pipeline_config_none(
        self, state, tmp_path
    ):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        run_fn = _make_run_fn(tmp_path / "07_derivatives")
        panel = RerunDerivatives(state, run_fn=run_fn)
        state.output_dir = str(tmp_path)
        state.pipeline_config = None
        panel._on_click(None)

        _, called_cfg = run_fn.call_args.args
        defaults = DerivativesConfig()
        assert called_cfg.pre_onset_ms == defaults.pre_onset_ms
        assert called_cfg.post_onset_ms == defaults.post_onset_ms
        assert called_cfg.bin_size_ms == defaults.bin_size_ms


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


class TestRerunDerivativesAlerts:
    def test_successful_run_shows_success_alert(self, state, tmp_path):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        derivatives_dir = tmp_path / "07_derivatives"
        run_fn = _make_run_fn(derivatives_dir)
        panel = RerunDerivatives(state, run_fn=run_fn)
        state.output_dir = str(tmp_path)
        panel._on_click(None)

        assert panel.message_pane.alert_type == "success"
        assert panel.message_pane.visible is True
        assert "07_derivatives" in str(panel.message_pane.object)

    def test_run_fn_export_error_shows_danger_alert(self, state, tmp_path):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        run_fn = _make_run_fn(tmp_path, raises=ExportError("nwb missing"))
        panel = RerunDerivatives(state, run_fn=run_fn)
        state.output_dir = str(tmp_path)
        panel._on_click(None)

        assert panel.message_pane.alert_type == "danger"
        assert "nwb missing" in str(panel.message_pane.object)

    def test_run_fn_unexpected_exception_shows_danger_alert(self, state, tmp_path):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        run_fn = _make_run_fn(tmp_path, raises=RuntimeError("kaboom"))
        panel = RerunDerivatives(state, run_fn=run_fn)
        state.output_dir = str(tmp_path)
        panel._on_click(None)

        assert panel.message_pane.alert_type == "danger"
        assert "kaboom" in str(panel.message_pane.object)

    def test_click_when_output_dir_does_not_exist_shows_danger(self, state, tmp_path):
        from pynpxpipe.ui.components.rerun_derivatives import RerunDerivatives

        run_fn = _make_run_fn(tmp_path)
        panel = RerunDerivatives(state, run_fn=run_fn)
        state.output_dir = str(tmp_path / "missing_dir")
        panel._on_click(None)

        run_fn.assert_not_called()
        assert panel.message_pane.alert_type == "danger"
        assert (
            "not found" in str(panel.message_pane.object).lower()
            or "exist" in str(panel.message_pane.object).lower()
        )
