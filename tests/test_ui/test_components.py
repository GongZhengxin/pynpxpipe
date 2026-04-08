"""Tests for ui/components/ — A2 form components.

Groups:
  A. SessionForm    — path inputs update AppState; bhv2 extension validation
  B. SubjectForm    — default values; sex options; state update; YAML load
  C. PipelineForm   — viewable; default bandpass; field change → state update
  D. SortingForm    — viewable; kilosort4 option; default mode; state update
  E. StageSelector  — 7 stages; select/deselect all; state update; dep warning
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import panel as pn
import pytest

from pynpxpipe.ui.state import AppState

# ─────────────────────────────────────────────────────────────────────────────
# A. SessionForm
# ─────────────────────────────────────────────────────────────────────────────


def test_session_form_is_viewable():
    """SessionForm.panel() returns a Panel Viewable."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    assert isinstance(form.panel(), pn.viewable.Viewable)


def test_session_form_has_three_text_inputs():
    """SessionForm exposes session_dir_input, bhv_file_input, output_dir_input."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    assert isinstance(form.session_dir_input, pn.widgets.TextInput)
    assert isinstance(form.bhv_file_input, pn.widgets.TextInput)
    assert isinstance(form.output_dir_input, pn.widgets.TextInput)


def test_session_form_session_dir_input_updates_state():
    """Changing session_dir_input.value updates state.session_dir."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    form.session_dir_input.value = "/some/session/dir"
    assert state.session_dir == Path("/some/session/dir")


def test_session_form_bhv_file_input_updates_state():
    """Changing bhv_file_input.value to a .bhv2 path updates state.bhv_file."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    form.bhv_file_input.value = "/some/file.bhv2"
    assert state.bhv_file == Path("/some/file.bhv2")


def test_session_form_output_dir_input_updates_state():
    """Changing output_dir_input.value updates state.output_dir."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    form.output_dir_input.value = "/some/output"
    assert state.output_dir == Path("/some/output")


def test_session_form_bhv2_extension_validation():
    """Non-.bhv2 file sets validation_message; .bhv2 clears it."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    form.bhv_file_input.value = "/some/file.mat"
    assert form.validation_message != ""
    form.bhv_file_input.value = "/some/file.bhv2"
    assert form.validation_message == ""


def test_session_form_empty_input_clears_state():
    """Clearing a path input resets the corresponding state field to None."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    form.session_dir_input.value = "/some/dir"
    form.session_dir_input.value = ""
    assert state.session_dir is None


# ─────────────────────────────────────────────────────────────────────────────
# B. SubjectForm
# ─────────────────────────────────────────────────────────────────────────────


def test_subject_form_is_viewable():
    """SubjectForm.panel() returns a Panel Viewable."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state)
    assert isinstance(form.panel(), pn.viewable.Viewable)


def test_subject_form_default_species():
    """species_input defaults to 'Macaca mulatta'."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state)
    assert form.species_input.value == "Macaca mulatta"


def test_subject_form_sex_select_options():
    """sex_select contains exactly ['M', 'F', 'U', 'O']."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state)
    assert list(form.sex_select.options) == ["M", "F", "U", "O"]


def test_subject_form_all_fields_set_updates_state():
    """When all required fields are filled, state.subject_config is a SubjectConfig."""
    from pynpxpipe.core.session import SubjectConfig
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state)
    form.subject_id_input.value = "MaoDan"
    form.description_input.value = "test subject"
    form.species_input.value = "Macaca mulatta"
    form.sex_select.value = "M"
    form.age_input.value = "P3Y"
    form.weight_input.value = "10kg"
    assert isinstance(state.subject_config, SubjectConfig)
    assert state.subject_config.subject_id == "MaoDan"


def test_subject_form_missing_required_field_keeps_state_none():
    """If subject_id is empty, state.subject_config remains None."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state)
    # leave subject_id_input empty, set everything else
    form.species_input.value = "Macaca mulatta"
    form.age_input.value = "P3Y"
    form.weight_input.value = "10kg"
    assert state.subject_config is None


def test_subject_form_load_from_yaml(tmp_path: Path):
    """load_from_yaml fills all widget values from a YAML file."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    yaml_content = textwrap.dedent("""\
        Subject:
          subject_id: YamlMonkey
          description: loaded from yaml
          species: Macaca mulatta
          sex: F
          age: P5Y
          weight: 12kg
    """)
    yaml_file = tmp_path / "monkey.yaml"
    yaml_file.write_text(yaml_content)

    state = AppState()
    form = SubjectForm(state)
    form.load_from_yaml(yaml_file)

    assert form.subject_id_input.value == "YamlMonkey"
    assert form.sex_select.value == "F"
    assert form.age_input.value == "P5Y"


# ─────────────────────────────────────────────────────────────────────────────
# C. PipelineForm
# ─────────────────────────────────────────────────────────────────────────────


def test_pipeline_form_is_viewable():
    """PipelineForm.panel() returns a Panel Viewable."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert isinstance(form.panel(), pn.viewable.Viewable)


def test_pipeline_form_default_bandpass_freq_min():
    """freq_min_input defaults to 300.0 (BandpassConfig default)."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.freq_min_input.value == pytest.approx(300.0)


def test_pipeline_form_default_bandpass_freq_max():
    """freq_max_input defaults to 6000.0."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.freq_max_input.value == pytest.approx(6000.0)


def test_pipeline_form_changing_freq_min_updates_state():
    """Changing freq_min_input updates state.pipeline_config.preprocess.bandpass.freq_min."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.freq_min_input.value = 250.0
    assert state.pipeline_config is not None
    assert state.pipeline_config.preprocess.bandpass.freq_min == pytest.approx(250.0)


def test_pipeline_form_state_pipeline_config_initialized():
    """After construction, state.pipeline_config is a PipelineConfig (not None)."""
    from pynpxpipe.core.config import PipelineConfig
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    PipelineForm(state)
    assert isinstance(state.pipeline_config, PipelineConfig)


# ─────────────────────────────────────────────────────────────────────────────
# D. SortingForm
# ─────────────────────────────────────────────────────────────────────────────


def test_sorting_form_is_viewable():
    """SortingForm.panel() returns a Panel Viewable."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert isinstance(form.panel(), pn.viewable.Viewable)


def test_sorting_form_has_kilosort4_option():
    """sorter_select includes 'kilosort4' as an option."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert "kilosort4" in form.sorter_select.options


def test_sorting_form_default_mode_is_local():
    """mode_select defaults to 'local'."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert form.mode_select.value == "local"


def test_sorting_form_changing_mode_updates_state():
    """Changing mode_select to 'import' updates state.sorting_config.mode."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    form.mode_select.value = "import"
    assert state.sorting_config is not None
    assert state.sorting_config.mode == "import"


def test_sorting_form_state_sorting_config_initialized():
    """After construction, state.sorting_config is a SortingConfig (not None)."""
    from pynpxpipe.core.config import SortingConfig
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    SortingForm(state)
    assert isinstance(state.sorting_config, SortingConfig)


# ─────────────────────────────────────────────────────────────────────────────
# E. StageSelector
# ─────────────────────────────────────────────────────────────────────────────


def test_stage_selector_is_viewable():
    """StageSelector.panel() returns a Panel Viewable."""
    from pynpxpipe.ui.components.stage_selector import StageSelector

    state = AppState()
    sel = StageSelector(state)
    assert isinstance(sel.panel(), pn.viewable.Viewable)


def test_stage_selector_has_all_seven_stages():
    """stage_checkboxes contains exactly the 7 STAGE_ORDER names."""
    from pynpxpipe.pipelines.runner import STAGE_ORDER
    from pynpxpipe.ui.components.stage_selector import StageSelector

    state = AppState()
    sel = StageSelector(state)
    assert list(sel.stage_checkboxes.keys()) == STAGE_ORDER


def test_stage_selector_default_all_stages_selected():
    """All 7 stages are checked by default; state.selected_stages == STAGE_ORDER."""
    from pynpxpipe.pipelines.runner import STAGE_ORDER
    from pynpxpipe.ui.components.stage_selector import StageSelector

    state = AppState()
    StageSelector(state)
    assert state.selected_stages == STAGE_ORDER


def test_stage_selector_deselect_all_clears_selection():
    """Clicking deselect_all_btn unchecks all boxes; state.selected_stages == []."""
    from pynpxpipe.ui.components.stage_selector import StageSelector

    state = AppState()
    sel = StageSelector(state)
    sel.deselect_all_btn.clicks += 1
    assert state.selected_stages == []


def test_stage_selector_select_all_selects_all():
    """After deselect-all, clicking select_all_btn restores all stages."""
    from pynpxpipe.pipelines.runner import STAGE_ORDER
    from pynpxpipe.ui.components.stage_selector import StageSelector

    state = AppState()
    sel = StageSelector(state)
    sel.deselect_all_btn.clicks += 1
    sel.select_all_btn.clicks += 1
    assert state.selected_stages == STAGE_ORDER


def test_stage_selector_unchecking_stage_updates_state():
    """Unchecking a checkbox removes that stage from state.selected_stages."""
    from pynpxpipe.ui.components.stage_selector import StageSelector

    state = AppState()
    sel = StageSelector(state)
    sel.stage_checkboxes["export"].value = False
    assert "export" not in state.selected_stages


def test_stage_selector_dependency_warning_export_without_sort():
    """Selecting export but not sort sets a non-empty dependency_warning."""
    from pynpxpipe.ui.components.stage_selector import StageSelector

    state = AppState()
    sel = StageSelector(state)
    sel.stage_checkboxes["sort"].value = False
    # export is still selected (default), sort is not
    assert "export" in state.selected_stages
    assert "sort" not in state.selected_stages
    assert sel.dependency_warning != ""
