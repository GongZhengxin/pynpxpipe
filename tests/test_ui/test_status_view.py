"""Tests for ui/components/status_view.py — Stage status display + reset."""

from __future__ import annotations

from unittest.mock import MagicMock

import panel as pn
import pytest

from pynpxpipe.ui.state import AppState

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def state():
    return AppState()


@pytest.fixture()
def mock_status():
    """Return a typical get_status() result."""
    return {
        "discover": "completed",
        "preprocess": "completed",
        "sort": "completed",
        "merge": "pending",
        "synchronize": "pending",
        "curate": "pending",
        "postprocess": "pending",
        "export": "pending",
    }


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestStatusViewConstruction:
    def test_creates_panel_layout(self, state):
        from pynpxpipe.ui.components.status_view import StatusView

        view = StatusView(state)
        layout = view.panel()
        assert isinstance(layout, pn.viewable.Viewable)

    def test_initial_state_no_output_dir(self, state):
        """When output_dir is not set, show a placeholder message."""
        from pynpxpipe.ui.components.status_view import StatusView

        view = StatusView(state)
        view.panel()
        # Should contain a message about no output_dir
        assert view.message_pane.object != ""


# ---------------------------------------------------------------------------
# Status rendering
# ---------------------------------------------------------------------------


class TestStatusRendering:
    def test_load_status_shows_all_stages(self, state, mock_status, tmp_path):
        """After loading status, all 8 stages should be displayed."""
        from pynpxpipe.ui.components.status_view import StatusView

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: mock_status)
        view.load_status()

        # Should have 8 stage rows (merge added)
        assert len(view.stage_rows) == 9

    def test_stage_status_text_shows_correctly(self, state, mock_status, tmp_path):
        """Each stage row should display the stage name and its status."""
        from pynpxpipe.ui.components.status_view import StatusView

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: mock_status)
        view.load_status()

        # Check that completed stages show "completed"
        discover_row = view.stage_rows["discover"]
        assert "completed" in discover_row["status_text"].object.lower()

        # Check pending stages
        curate_row = view.stage_rows["curate"]
        assert "pending" in curate_row["status_text"].object.lower()

    def test_partial_status_shown(self, state, tmp_path):
        """Partial probe completion should be displayed."""
        from pynpxpipe.ui.components.status_view import StatusView

        partial_status = {
            "discover": "completed",
            "preprocess": "partial (1/2 probes)",
            "sort": "pending",
            "synchronize": "pending",
            "curate": "pending",
            "postprocess": "pending",
            "export": "pending",
        }
        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: partial_status)
        view.load_status()

        preprocess_row = view.stage_rows["preprocess"]
        assert "partial" in preprocess_row["status_text"].object.lower()

    def test_failed_status_shown(self, state, tmp_path):
        """Failed stages should be shown with failed status."""
        from pynpxpipe.ui.components.status_view import StatusView

        failed_status = {
            "discover": "completed",
            "preprocess": "failed",
            "sort": "pending",
            "synchronize": "pending",
            "curate": "pending",
            "postprocess": "pending",
            "export": "pending",
        }
        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: failed_status)
        view.load_status()

        preprocess_row = view.stage_rows["preprocess"]
        assert "failed" in preprocess_row["status_text"].object.lower()


# ---------------------------------------------------------------------------
# Rerun-from-stage (ui_redesign.md §4.2 P0-4)
# ---------------------------------------------------------------------------


def _write_cp(root, name, status="completed"):
    import json

    cp = root / "checkpoints"
    cp.mkdir(parents=True, exist_ok=True)
    (cp / f"{name}.json").write_text(json.dumps({"status": status}), encoding="utf-8")


@pytest.fixture()
def finished_output(tmp_path):
    """Output dir where every stage completed for imec0 and imec1."""
    from pynpxpipe.pipelines.constants import PER_PROBE_STAGES, STAGE_ORDER

    for stage in STAGE_ORDER:
        _write_cp(tmp_path, stage)
        if stage in PER_PROBE_STAGES:
            for pid in ("imec0", "imec1"):
                _write_cp(tmp_path, f"{stage}_{pid}")
    for pid in ("imec0", "imec1"):
        (tmp_path / "01_preprocessed" / f"{pid}.zarr").mkdir(parents=True)
    return tmp_path


def _cp_names(root):
    return sorted(p.stem for p in (root / "checkpoints").glob("*.json"))


def _view(state, root):
    from pynpxpipe.ui.components.status_view import StatusView

    state.output_dir = str(root)
    view = StatusView(state, get_status_fn=lambda output_dir: {})
    view.load_status()
    return view


class TestResetStage:
    def test_each_stage_has_rerun_button(self, state, mock_status, tmp_path):
        from pynpxpipe.ui.components.status_view import StatusView

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: mock_status)
        view.load_status()

        for stage_name in mock_status:
            assert view.stage_rows[stage_name]["reset_btn"].name == "从此阶段重跑…"

    def test_click_opens_dialog_without_touching_files(self, state, finished_output):
        view = _view(state, finished_output)
        before = _cp_names(finished_output)
        view.stage_rows["sort"]["reset_btn"].clicks += 1

        assert view.rerun_dialog.visible is True
        assert _cp_names(finished_output) == before

    def test_cancel_deletes_nothing(self, state, finished_output):
        view = _view(state, finished_output)
        before = _cp_names(finished_output)
        view.open_rerun("sort")
        view.rerun_cancel_btn.clicks += 1

        assert view.rerun_dialog.visible is False
        assert _cp_names(finished_output) == before

    def test_plan_lists_stage_and_all_downstream_checkpoints(self, state, finished_output):
        view = _view(state, finished_output)
        view.open_rerun("sort")

        cleared = sorted(p.stem for _, _, p in view.rerun_plan.clear)
        expected = ["export"]
        for stage in ("sort", "merge", "curate", "postprocess"):
            expected += [stage, f"{stage}_imec0", f"{stage}_imec1"]
        assert cleared == sorted(expected)
        assert view.rerun_plan.keep == ["discover", "synchronize", "select_segments", "preprocess"]
        text = str(view.rerun_clear_pane.object)
        assert "sort_imec0.json" in text and "export.json" in text

    def test_confirm_clears_stage_and_downstream_only(self, state, finished_output):
        view = _view(state, finished_output)
        view.open_rerun("curate")
        view.rerun_confirm_btn.clicks += 1

        remaining = _cp_names(finished_output)
        assert "preprocess_imec0" in remaining and "sort_imec1" in remaining
        assert not any(n.startswith(("curate", "postprocess", "export")) for n in remaining)
        assert view.rerun_dialog.visible is False

    def test_single_probe_scope_keeps_other_probe(self, state, finished_output):
        view = _view(state, finished_output)
        view.open_rerun("sort")
        assert view.rerun_scope.visible is True
        assert view.rerun_scope.value == ""
        view.rerun_scope.value = "imec0"
        view.rerun_confirm_btn.clicks += 1

        remaining = _cp_names(finished_output)
        assert "sort_imec0" not in remaining and "curate_imec0" not in remaining
        assert "sort_imec1" in remaining and "curate_imec1" in remaining
        # Aggregate stage-level files would otherwise make the runner skip the probe.
        assert "sort" not in remaining and "export" not in remaining
        assert "preprocess_imec0" in remaining

    def test_scope_hidden_for_session_level_stage(self, state, finished_output):
        view = _view(state, finished_output)
        view.open_rerun("synchronize")
        assert view.rerun_scope.visible is False

    def test_missing_zarr_pulls_in_preprocess(self, state, finished_output):
        import shutil

        shutil.rmtree(finished_output / "01_preprocessed" / "imec0.zarr")
        view = _view(state, finished_output)
        view.open_rerun("sort")

        assert view.rerun_plan.needs_preprocess == ["imec0"]
        cleared = {p.stem for _, _, p in view.rerun_plan.clear}
        assert {"preprocess", "preprocess_imec0"} <= cleared
        assert "preprocess_imec1" not in cleared
        assert "需要连同 preprocess 一起重跑" in str(view.rerun_warning.object)
        assert view.rerun_warning.visible is True

    def test_missing_zarr_does_not_matter_for_export(self, state, finished_output):
        import shutil

        shutil.rmtree(finished_output / "01_preprocessed" / "imec0.zarr")
        view = _view(state, finished_output)
        view.open_rerun("export")

        assert view.rerun_plan.needs_preprocess == []
        assert view.rerun_warning.visible is False

    def test_param_diff_against_used_configs(self, state, finished_output):
        import dataclasses

        from pynpxpipe.core.config import SortingConfig, save_sorting_config

        state.sorting_config = SortingConfig()
        base = SortingConfig()
        params = dataclasses.replace(base.sorter.params, Th_learned=7.25)
        used = dataclasses.replace(base, sorter=dataclasses.replace(base.sorter, params=params))
        save_sorting_config(used, finished_output / "used_sorting.yaml")

        view = _view(state, finished_output)
        view.open_rerun("sort")

        text = str(view.rerun_params_pane.object)
        assert "sorter.params.Th_learned" in text
        assert "used_pipeline.yaml" in text  # reported as missing

    def test_modal_handlers_are_called(self, state, finished_output):
        view = _view(state, finished_output)
        open_fn, close_fn = MagicMock(), MagicMock()
        view.set_modal_handlers(open_fn, close_fn)
        view.open_rerun("export")
        open_fn.assert_called_once()
        view.rerun_cancel_btn.clicks += 1
        close_fn.assert_called_once()

    def test_confirm_refreshes_status(self, state, finished_output):
        from pynpxpipe.ui.components.status_view import StatusView

        calls = []
        state.output_dir = str(finished_output)
        view = StatusView(state, get_status_fn=lambda d: calls.append(d) or {})
        view.load_status()
        view.open_rerun("export")
        view.rerun_confirm_btn.clicks += 1
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# Output dir change
# ---------------------------------------------------------------------------


class TestOutputDirChange:
    def test_load_button_triggers_status_load(self, state, mock_status, tmp_path):
        """Clicking the Load button should trigger a status load."""
        from pynpxpipe.ui.components.status_view import StatusView

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=lambda output_dir: mock_status)
        view._on_load_click(None)

        assert len(view.stage_rows) == 9

    def test_load_with_no_output_dir_shows_message(self, state):
        """Loading when output_dir is empty should show an error message."""
        from pynpxpipe.ui.components.status_view import StatusView

        view = StatusView(state)
        view._on_load_click(None)

        assert "output" in view.message_pane.object.lower()

    def test_load_with_error_shows_message(self, state, tmp_path):
        """If get_status_fn raises, show the error message."""
        from pynpxpipe.ui.components.status_view import StatusView

        def failing_get_status(output_dir):
            raise FileNotFoundError("session.json not found")

        state.output_dir = str(tmp_path)
        view = StatusView(state, get_status_fn=failing_get_status)
        view._on_load_click(None)

        assert "not found" in view.message_pane.object.lower()
