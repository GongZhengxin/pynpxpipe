"""Tests for ui/components/preset_bar.py — P0-2 presets and diff (ui_redesign.md §4.2).

Groups:
  A. list_presets — suffix pairing and pipeline/sorting fallback
  B. diff_configs — dotted-path flattening and comparison
  C. PresetBar selection — applies presets to both forms
  D. Diff card — badge, per-field restore, changed-field markers
  E. Import / export YAML
"""

from __future__ import annotations

from pathlib import Path

import panel as pn
import pytest

from pynpxpipe.ui.state import AppState


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    d.mkdir()
    (d / "pipeline.yaml").write_text("curation:\n  snr_min: 0.3\n", encoding="utf-8")
    (d / "sorting.yaml").write_text("sorter:\n  params:\n    nblocks: 0\n", encoding="utf-8")
    (d / "pipeline_E2.yaml").write_text(
        "curation:\n  snr_min: 0.3\npreprocess:\n  motion_correction:\n    method: null\n",
        encoding="utf-8",
    )
    (d / "sorting_E1.yaml").write_text(
        "sorter:\n  params:\n    nblocks: 0\n    Th_learned: 7.0\n", encoding="utf-8"
    )
    (d / "sorting_E2.yaml").write_text("sorter:\n  params:\n    nblocks: 5\n", encoding="utf-8")
    (d / "recordings.example.yaml").write_text("recordings: []\n", encoding="utf-8")
    return d


def _make_bar(config_dir: Path):
    from pynpxpipe.ui.components.pipeline_form import PipelineForm
    from pynpxpipe.ui.components.preset_bar import PresetBar
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    pipeline_form = PipelineForm(state)
    sorting_form = SortingForm(state)
    bar = PresetBar(state, pipeline_form, sorting_form, config_dir=config_dir)
    return state, pipeline_form, sorting_form, bar


# ── A. list_presets ──


class TestListPresets:
    def test_pairs_by_suffix_with_default_first(self, config_dir: Path):
        from pynpxpipe.ui.components.preset_bar import list_presets

        presets = list_presets(config_dir)
        assert [p.name for p in presets] == ["默认", "E1", "E2"]

    def test_e2_uses_its_own_pipeline_file(self, config_dir: Path):
        from pynpxpipe.ui.components.preset_bar import list_presets

        e2 = {p.name: p for p in list_presets(config_dir)}["E2"]
        assert e2.pipeline_path == config_dir / "pipeline_E2.yaml"
        assert e2.sorting_path == config_dir / "sorting_E2.yaml"
        assert e2.pipeline_fallback is False

    def test_missing_pipeline_falls_back_to_default(self, config_dir: Path):
        from pynpxpipe.ui.components.preset_bar import list_presets

        e1 = {p.name: p for p in list_presets(config_dir)}["E1"]
        assert e1.pipeline_path == config_dir / "pipeline.yaml"
        assert e1.pipeline_fallback is True
        assert e1.sorting_fallback is False

    def test_fallback_is_noted_in_select_labels(self, config_dir: Path):
        _, _, _, bar = _make_bar(config_dir)
        labels = list(bar.preset_select.options)
        e1_label = next(label for label in labels if label.startswith("E1"))
        assert "pipeline.yaml" in e1_label
        e2_label = next(label for label in labels if label.startswith("E2"))
        assert "pipeline.yaml" not in e2_label


# ── B. diff_configs ──


class TestDiffConfigs:
    def test_identical_configs_have_no_diff(self):
        from pynpxpipe.core.config import PipelineConfig
        from pynpxpipe.ui.components.preset_bar import diff_configs

        assert diff_configs(PipelineConfig(), PipelineConfig()) == []

    def test_reports_dotted_key_with_both_values(self):
        import dataclasses

        from pynpxpipe.core.config import SortingConfig
        from pynpxpipe.ui.components.preset_bar import diff_configs

        base = SortingConfig()
        params = dataclasses.replace(base.sorter.params, Th_learned=6.5)
        current = dataclasses.replace(base, sorter=dataclasses.replace(base.sorter, params=params))
        assert diff_configs(base, current) == [
            ("sorter.params.Th_learned", base.sorter.params.Th_learned, 6.5)
        ]


# ── C. Selection ──


class TestPresetSelection:
    def test_selecting_preset_applies_both_configs(self, config_dir: Path):
        state, _, _, bar = _make_bar(config_dir)
        bar.preset_select.value = "E2"

        assert state.sorting_config.sorter.params.nblocks == 5
        assert state.pipeline_config.preprocess.motion_correction.method is None
        assert bar.diff == []
        assert "已改 0 项" in str(bar.badge.object)

    def test_selecting_fallback_preset_loads_default_pipeline(self, config_dir: Path):
        state, _, _, bar = _make_bar(config_dir)
        bar.preset_select.value = "E1"

        assert state.sorting_config.sorter.params.Th_learned == 7.0
        assert state.pipeline_config.curation.snr_min == 0.3
        assert bar.diff == []


# ── D. Diff card ──


class TestDiffCard:
    def test_empty_diff_says_no_changes(self, config_dir: Path):
        _, _, _, bar = _make_bar(config_dir)
        text = " ".join(str(p.object) for p in bar.diff_list.select(pn.pane.Markdown))
        assert "没有改动" in text

    def test_editing_a_field_shows_badge_and_diff_row(self, config_dir: Path):
        state, _, sorting_form, bar = _make_bar(config_dir)
        bar.preset_select.value = "E1"
        sorting_form.th_learned_input.value = 6.0

        assert bar.diff == [("sorter.params.Th_learned", 7.0, 6.0)]
        assert "已改 1 项" in str(bar.badge.object)
        text = " ".join(str(p.object) for p in bar.diff_list.select(pn.pane.Markdown))
        assert "sorter.params.Th_learned" in text

    def test_changed_widget_is_marked_and_unmarked(self, config_dir: Path):
        state, pipeline_form, sorting_form, bar = _make_bar(config_dir)
        bar.preset_select.value = "E1"
        sorting_form.th_learned_input.value = 6.0
        pipeline_form.snr_min_input.value = 1.5

        assert "pynpx-changed" in sorting_form.th_learned_input.css_classes
        assert "pynpx-changed" in pipeline_form.snr_min_input.css_classes
        assert "pynpx-changed" not in sorting_form.nblocks_input.css_classes

        bar.restore("curation.snr_min")
        assert "pynpx-changed" not in pipeline_form.snr_min_input.css_classes

    def test_restore_button_reverts_one_field(self, config_dir: Path):
        state, pipeline_form, sorting_form, bar = _make_bar(config_dir)
        bar.preset_select.value = "E1"
        sorting_form.th_learned_input.value = 6.0
        pipeline_form.snr_min_input.value = 1.5
        assert len(bar.diff) == 2

        buttons = [b for b in bar.diff_list.select(pn.widgets.Button) if b.name == "恢复"]
        assert len(buttons) == 2
        target = next(b for b in buttons if b.tags == ["sorter.params.Th_learned"])
        target.clicks += 1

        assert state.sorting_config.sorter.params.Th_learned == 7.0
        assert sorting_form.th_learned_input.value == 7.0
        assert state.pipeline_config.curation.snr_min == 1.5
        assert "已改 1 项" in str(bar.badge.object)

    def test_restore_field_without_widget_keeps_other_edits(self, config_dir: Path):
        import dataclasses

        state, pipeline_form, _, bar = _make_bar(config_dir)
        bar.preset_select.value = "默认"
        cfg = state.pipeline_config
        state.pipeline_config = dataclasses.replace(
            cfg, preprocess=dataclasses.replace(cfg.preprocess, save_dtype="float32")
        )
        assert [d[0] for d in bar.diff] == ["preprocess.save_dtype"]

        bar.restore("preprocess.save_dtype")
        assert state.pipeline_config.preprocess.save_dtype == cfg.preprocess.save_dtype
        assert bar.diff == []


# ── E. Import / export ──


class TestImportExport:
    def test_import_sorting_yaml_applies_and_becomes_baseline(self, config_dir, tmp_path):
        state, _, _, bar = _make_bar(config_dir)
        custom = tmp_path / "my_sorting.yaml"
        custom.write_text("sorter:\n  params:\n    nblocks: 3\n", encoding="utf-8")

        bar.import_kind.value = "sorting"
        bar.import_path.value = str(custom)
        bar.import_btn.clicks += 1

        assert state.sorting_config.sorter.params.nblocks == 3
        assert "my_sorting.yaml" in str(bar.message.object)
        assert bar.message.alert_type == "success"
        assert bar.diff == []

    def test_import_invalid_yaml_shows_error(self, config_dir, tmp_path):
        state, _, _, bar = _make_bar(config_dir)
        before = state.pipeline_config
        bad = tmp_path / "bad.yaml"
        bad.write_text("curation:\n  snr_min: -5\n", encoding="utf-8")

        bar.import_kind.value = "pipeline"
        bar.import_path.value = str(bad)
        bar.import_btn.clicks += 1

        assert bar.message.alert_type == "danger"
        assert state.pipeline_config == before

    def test_export_writes_round_trippable_pair(self, config_dir, tmp_path):
        from pynpxpipe.core.config import load_pipeline_config, load_sorting_config

        state, _, sorting_form, bar = _make_bar(config_dir)
        sorting_form.th_learned_input.value = 6.0
        out = tmp_path / "out"

        bar.export_dir.value = str(out)
        bar.export_name.value = "mine"
        bar.export_btn.clicks += 1

        assert load_sorting_config(out / "sorting_mine.yaml") == state.sorting_config
        assert load_pipeline_config(out / "pipeline_mine.yaml") == state.pipeline_config
        assert bar.message.alert_type == "success"

    def test_export_refuses_to_overwrite(self, config_dir):
        _, _, _, bar = _make_bar(config_dir)
        before = (config_dir / "sorting_E2.yaml").read_text(encoding="utf-8")

        bar.export_dir.value = str(config_dir)
        bar.export_name.value = "E2"
        bar.export_btn.clicks += 1

        assert bar.message.alert_type == "danger"
        assert (config_dir / "sorting_E2.yaml").read_text(encoding="utf-8") == before

    def test_export_into_config_dir_adds_new_preset(self, config_dir):
        _, _, _, bar = _make_bar(config_dir)
        bar.export_dir.value = str(config_dir)
        bar.export_name.value = "E9"
        bar.export_btn.clicks += 1

        assert "E9" in bar.preset_select.options.values()


def test_pd_highline_labels_fix_typo_only():
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    form = PipelineForm(AppState())
    for widget in (form.pd_hignline_skip_input, form.pd_hignline_width_input):
        assert "Highline" in widget.name
        assert "hignline" not in widget.name.lower()
        assert "hignline" not in (widget.description or "").lower()
