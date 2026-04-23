"""Tests for ui/components/probe_region_editor.py — SID S3 probe region declaration."""

from __future__ import annotations

import panel as pn

from pynpxpipe.ui.state import AppState


class TestProbeRegionEditor:
    def test_default_shows_one_imec0_row(self):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor

        state = AppState()
        editor = ProbeRegionEditor(state)
        assert isinstance(editor.panel(), pn.viewable.Viewable)
        assert len(editor._rows_col) == 1

    def test_edit_target_area_updates_state(self):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor

        state = AppState()
        editor = ProbeRegionEditor(state)
        row = editor._rows_col[0]
        row._pynpx_area_input.value = "V4"
        assert state.probe_plan == {"imec0": "V4"}

    def test_add_probe_appends_next_imec_id(self):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor

        state = AppState()
        editor = ProbeRegionEditor(state)
        editor._on_add_click(None)
        assert set(state.probe_plan.keys()) == {"imec0", "imec1"}
        assert len(editor._rows_col) == 2

    def test_remove_probe_drops_row_and_updates_state(self):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor

        state = AppState()
        editor = ProbeRegionEditor(state)
        editor._on_add_click(None)
        # Now we have imec0 and imec1. Remove imec1.
        row = next(r for r in editor._rows_col if r._pynpx_probe_id == "imec1")
        row._pynpx_remove_btn.clicks += 1  # simulate click; on_click handler triggers

        assert "imec1" not in state.probe_plan
        assert "imec0" in state.probe_plan

    def test_external_probe_plan_change_rebuilds_rows(self):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor

        state = AppState()
        editor = ProbeRegionEditor(state)
        state.probe_plan = {"imec0": "MSB", "imec1": "V4", "imec2": "IT"}
        assert len(editor._rows_col) == 3
        ids = sorted(r._pynpx_probe_id for r in editor._rows_col)
        assert ids == ["imec0", "imec1", "imec2"]

    def test_remove_disabled_when_only_one_row(self):
        from pynpxpipe.ui.components.probe_region_editor import ProbeRegionEditor

        state = AppState()
        editor = ProbeRegionEditor(state)
        row = editor._rows_col[0]
        assert row._pynpx_remove_btn.disabled is True
