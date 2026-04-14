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


def test_session_form_has_browsable_inputs():
    """SessionForm exposes session_dir_input, bhv_file_input, output_dir_input as BrowsableInput."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    assert isinstance(form.session_dir_input, BrowsableInput)
    assert isinstance(form.bhv_file_input, BrowsableInput)
    assert isinstance(form.output_dir_input, BrowsableInput)


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


# ── A.2 Simple / Advanced Mode ──


def test_session_form_simple_mode_is_default():
    """SessionForm defaults to simple mode (advanced_toggle is False)."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    assert form.advanced_toggle.value is False


def test_session_form_simple_mode_has_data_dir_input():
    """Simple mode exposes a data_dir_input BrowsableInput widget."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    assert isinstance(form.data_dir_input, BrowsableInput)


def test_session_form_simple_mode_hides_session_dir_and_bhv():
    """In simple mode, session_dir_input and bhv_file_input are not visible."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    assert form.session_dir_input.visible is False
    assert form.bhv_file_input.visible is False


def test_session_form_simple_mode_data_dir_visible():
    """In simple mode, data_dir_input is visible."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    assert form.data_dir_input.visible is True


def test_session_form_advanced_mode_shows_session_dir_and_bhv():
    """Toggling to advanced mode shows session_dir and bhv_file, hides data_dir."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    form.advanced_toggle.value = True
    assert form.session_dir_input.visible is True
    assert form.bhv_file_input.visible is True
    assert form.data_dir_input.visible is False


def test_session_form_output_dir_visible_in_both_modes():
    """output_dir_input is visible in both simple and advanced mode."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    assert form.output_dir_input.visible is True
    form.advanced_toggle.value = True
    assert form.output_dir_input.visible is True


def test_session_form_data_dir_auto_discovery_success(tmp_path: Path):
    """Setting data_dir_input to a dir with gate+bhv2 auto-discovers and sets state."""
    from pynpxpipe.ui.components.session_form import SessionForm

    # Create gate dir + bhv2 file
    gate = tmp_path / "session_20260409_g0"
    gate.mkdir()
    bhv = tmp_path / "session_20260409.bhv2"
    bhv.write_text("")

    state = AppState()
    form = SessionForm(state)
    form.data_dir_input.value = str(tmp_path)

    assert Path(str(state.session_dir)) == gate
    assert Path(str(state.bhv_file)) == bhv


def test_session_form_data_dir_discovery_shows_success_status(tmp_path: Path):
    """Successful discovery sets discovery_status to a non-empty success message."""
    from pynpxpipe.ui.components.session_form import SessionForm

    gate = tmp_path / "recording_g0"
    gate.mkdir()
    bhv = tmp_path / "recording.bhv2"
    bhv.write_text("")

    state = AppState()
    form = SessionForm(state)
    form.data_dir_input.value = str(tmp_path)

    assert form.discovery_status != ""
    assert "recording_g0" in form.discovery_status
    assert "recording.bhv2" in form.discovery_status


def test_session_form_data_dir_no_gate_dir_shows_error(tmp_path: Path):
    """data_dir with no gate directory sets an error discovery_status."""
    from pynpxpipe.ui.components.session_form import SessionForm

    bhv = tmp_path / "session.bhv2"
    bhv.write_text("")

    state = AppState()
    form = SessionForm(state)
    form.data_dir_input.value = str(tmp_path)

    assert form.discovery_status != ""
    assert state.session_dir is None


def test_session_form_data_dir_no_bhv2_shows_error(tmp_path: Path):
    """data_dir with gate dir but no bhv2 sets an error discovery_status."""
    from pynpxpipe.ui.components.session_form import SessionForm

    gate = tmp_path / "session_g0"
    gate.mkdir()

    state = AppState()
    form = SessionForm(state)
    form.data_dir_input.value = str(tmp_path)

    assert form.discovery_status != ""
    assert state.bhv_file is None


def test_session_form_simple_to_advanced_preserves_values(tmp_path: Path):
    """Switching from simple to advanced preserves auto-discovered paths."""
    from pynpxpipe.ui.components.session_form import SessionForm

    gate = tmp_path / "session_g0"
    gate.mkdir()
    bhv = tmp_path / "session.bhv2"
    bhv.write_text("")

    state = AppState()
    form = SessionForm(state)
    form.data_dir_input.value = str(tmp_path)
    form.advanced_toggle.value = True

    assert form.session_dir_input.value == str(gate)
    assert form.bhv_file_input.value == str(bhv)


def test_session_form_advanced_to_simple_infers_data_dir():
    """Switching from advanced to simple infers data_dir from session_dir's parent."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    form.advanced_toggle.value = True
    form.session_dir_input.value = "/data/experiment/session_g0"
    form.advanced_toggle.value = False

    assert Path(form.data_dir_input.value) == Path("/data/experiment")


def test_session_form_data_dir_nonexistent_path_shows_error():
    """Setting data_dir to a non-existent path sets error discovery_status."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    form.data_dir_input.value = "/nonexistent/path/does_not_exist"

    assert form.discovery_status != ""
    assert state.session_dir is None


def test_session_form_clear_data_dir_clears_state():
    """Clearing data_dir resets session_dir and bhv_file to None."""
    from pynpxpipe.ui.components.session_form import SessionForm

    state = AppState()
    form = SessionForm(state)
    form.data_dir_input.value = "/some/path"
    form.data_dir_input.value = ""

    assert state.session_dir is None
    assert state.bhv_file is None


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


def test_pipeline_form_has_motion_correction_widgets():
    """PipelineForm exposes motion correction enable checkbox and preset widgets."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert isinstance(form.motion_enabled_checkbox, pn.widgets.Checkbox)
    assert isinstance(form.motion_preset_select, pn.widgets.Select)


def test_pipeline_form_motion_correction_defaults():
    """Motion correction defaults to enabled=True, preset='dredge'."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.motion_enabled_checkbox.value is True
    assert form.motion_preset_select.value == "dredge"


def test_pipeline_form_motion_disabled_updates_state():
    """Unchecking motion correction sets method to None."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.motion_enabled_checkbox.value = False
    assert state.pipeline_config.preprocess.motion_correction.method is None


def test_pipeline_form_motion_preset_change_updates_state():
    """Changing motion preset updates state accordingly."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.motion_preset_select.value = "rigid_fast"
    assert state.pipeline_config.preprocess.motion_correction.preset == "rigid_fast"


def test_pipeline_form_has_sync_widgets():
    """PipelineForm exposes sync parameter widgets."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert isinstance(form.sync_bit_input, pn.widgets.IntInput)
    assert isinstance(form.stim_onset_code_input, pn.widgets.IntInput)
    assert isinstance(form.monitor_delay_input, pn.widgets.FloatInput)


def test_pipeline_form_sync_defaults():
    """Sync widgets default to dataclass values."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.sync_bit_input.value == 6
    assert form.stim_onset_code_input.value == 64
    assert form.monitor_delay_input.value == pytest.approx(-5.0)


def test_pipeline_form_sync_change_updates_state():
    """Changing sync_bit updates state.pipeline_config.sync.imec_sync_bit."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.sync_bit_input.value = 3
    assert state.pipeline_config.sync.imec_sync_bit == 3


def test_pipeline_form_has_postprocess_widgets():
    """PipelineForm exposes postprocess parameter widgets."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert isinstance(form.slay_pre_input, pn.widgets.FloatInput)
    assert isinstance(form.slay_post_input, pn.widgets.FloatInput)
    assert isinstance(form.eye_enabled_checkbox, pn.widgets.Checkbox)
    assert isinstance(form.eye_threshold_input, pn.widgets.FloatInput)


def test_pipeline_form_postprocess_defaults():
    """Postprocess widgets default to dataclass values."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.slay_pre_input.value == pytest.approx(0.05)
    assert form.slay_post_input.value == pytest.approx(0.30)
    assert form.eye_enabled_checkbox.value is True
    assert form.eye_threshold_input.value == pytest.approx(0.999)


def test_pipeline_form_postprocess_change_updates_state():
    """Changing slay_pre_s updates state.pipeline_config.postprocess.slay_pre_s."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.slay_pre_input.value = 0.10
    assert state.pipeline_config.postprocess.slay_pre_s == pytest.approx(0.10)


# ─── C.1 Parallel + Merge (M2 UI S5 config alignment) ───


def test_pipeline_form_has_parallel_widgets():
    """PipelineForm exposes parallel_enabled_checkbox and parallel_max_workers_input."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "parallel_enabled_checkbox")
    assert hasattr(form, "parallel_max_workers_input")


def test_pipeline_form_parallel_defaults():
    """Parallel widgets default to disabled with max_workers='auto'."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.parallel_enabled_checkbox.value is False
    assert form.parallel_max_workers_input.value == "auto"


def test_pipeline_form_parallel_enable_updates_state():
    """Toggling parallel_enabled_checkbox propagates to state.pipeline_config.parallel.enabled."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.parallel_enabled_checkbox.value = True
    assert state.pipeline_config.parallel.enabled is True


def test_pipeline_form_parallel_max_workers_auto_mode():
    """max_workers_input accepts integer strings and 'auto', storing each form correctly in state."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.parallel_max_workers_input.value = "4"
    assert state.pipeline_config.parallel.max_workers == 4
    form.parallel_max_workers_input.value = "auto"
    assert state.pipeline_config.parallel.max_workers == "auto"


def test_pipeline_form_has_merge_widget():
    """PipelineForm exposes merge_enabled_checkbox widget."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "merge_enabled_checkbox")


def test_pipeline_form_merge_default_disabled():
    """Merge checkbox defaults to False and toggling it updates state.pipeline_config.merge.enabled."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert state.pipeline_config.merge.enabled is False
    form.merge_enabled_checkbox.value = True
    assert state.pipeline_config.merge.enabled is True


# ─── C.2 Curation extensions (use_bombcell, good_isi, good_snr) ───


def test_pipeline_form_has_use_bombcell_widget():
    """PipelineForm exposes a use_bombcell checkbox widget."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "use_bombcell_checkbox")


def test_pipeline_form_use_bombcell_default_true():
    """use_bombcell defaults to True in both widget and config."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.use_bombcell_checkbox.value is True
    assert state.pipeline_config.curation.use_bombcell is True


def test_pipeline_form_has_good_isi_max_widget():
    """PipelineForm exposes good_isi_max input defaulting to 0.1."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "good_isi_max_input")
    assert form.good_isi_max_input.value == 0.1


def test_pipeline_form_has_good_snr_min_widget():
    """PipelineForm exposes good_snr_min input defaulting to 3.0."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "good_snr_min_input")
    assert form.good_snr_min_input.value == 3.0


def test_pipeline_form_curation_manual_thresholds_propagate():
    """Editing good_isi_max/good_snr_min widgets updates curation config."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.good_isi_max_input.value = 0.2
    form.good_snr_min_input.value = 5.0
    assert state.pipeline_config.curation.good_isi_max == 0.2
    assert state.pipeline_config.curation.good_snr_min == 5.0


def test_pipeline_form_toggle_bombcell_updates_state():
    """Toggling use_bombcell checkbox updates curation config."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.use_bombcell_checkbox.value = False
    assert state.pipeline_config.curation.use_bombcell is False


# ─── C.3 Sync expansion (9 new fields + imec rename) ───


def test_pipeline_form_has_nidq_sync_bit_widget():
    """PipelineForm exposes nidq_sync_bit_input widget with default 0."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "nidq_sync_bit_input")
    assert form.nidq_sync_bit_input.value == 0


def test_pipeline_form_imec_sync_bit_widget_renamed():
    """Existing sync_bit_input widget is relabelled to 'IMEC Sync Bit'."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.sync_bit_input.name == "IMEC Sync Bit"


def test_pipeline_form_has_max_time_error_widget():
    """PipelineForm exposes max_time_error_input widget with default 17.0."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "max_time_error_input")
    assert form.max_time_error_input.value == 17.0


def test_pipeline_form_has_trial_count_tolerance_widget():
    """PipelineForm exposes trial_count_tolerance_input widget with default 2."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "trial_count_tolerance_input")
    assert form.trial_count_tolerance_input.value == 2


def test_pipeline_form_has_photodiode_channel_index_widget():
    """PipelineForm exposes photodiode_channel_input widget with default 0."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "photodiode_channel_input")
    assert form.photodiode_channel_input.value == 0


def test_pipeline_form_has_gap_threshold_widget():
    """PipelineForm exposes gap_threshold widget pair; default 1200.0 enables checkbox."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "gap_threshold_enable_checkbox")
    assert hasattr(form, "gap_threshold_input")
    assert form.gap_threshold_enable_checkbox.value is True
    assert form.gap_threshold_input.value == 1200.0
    assert state.pipeline_config.sync.gap_threshold_ms == 1200.0


def test_pipeline_form_gap_threshold_nullable_checkbox_disable():
    """Disabling gap_threshold checkbox sets config to None and disables the input."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    form.gap_threshold_enable_checkbox.value = False
    assert state.pipeline_config.sync.gap_threshold_ms is None
    assert form.gap_threshold_input.disabled is True


def test_pipeline_form_has_trial_start_bit_widget():
    """PipelineForm exposes trial_start_bit widget pair (checkbox + input)."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "trial_start_bit_enable_checkbox")
    assert hasattr(form, "trial_start_bit_input")


def test_pipeline_form_trial_start_bit_default_none():
    """trial_start_bit defaults to None (checkbox off, input disabled)."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.trial_start_bit_enable_checkbox.value is False
    assert state.pipeline_config.sync.trial_start_bit is None
    assert form.trial_start_bit_input.disabled is True


def test_pipeline_form_has_pd_window_pre_ms_widget():
    """PipelineForm exposes pd_window_pre_input widget with default 10.0."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "pd_window_pre_input")
    assert form.pd_window_pre_input.value == 10.0


def test_pipeline_form_has_pd_window_post_ms_widget():
    """PipelineForm exposes pd_window_post_input widget with default 100.0."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "pd_window_post_input")
    assert form.pd_window_post_input.value == 100.0


def test_pipeline_form_has_pd_min_signal_variance_widget():
    """PipelineForm exposes pd_min_variance_input widget with default 1e-6."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "pd_min_variance_input")
    assert form.pd_min_variance_input.value == 1e-6


# ─── C.4 Postprocess pre_onset_ms + Curation description fixups ───


def test_pipeline_form_has_pre_onset_ms_widget():
    """PipelineForm exposes a pre_onset_ms_input widget."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert hasattr(form, "pre_onset_ms_input")


def test_pipeline_form_pre_onset_ms_default():
    """pre_onset_ms_input defaults to 50.0 and propagates to state on change."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert form.pre_onset_ms_input.value == 50.0
    assert state.pipeline_config.postprocess.pre_onset_ms == 50.0
    form.pre_onset_ms_input.value = 75.0
    assert state.pipeline_config.postprocess.pre_onset_ms == 75.0


def test_pipeline_form_curation_descriptions_reference_noise_semantics():
    """Curation widget descriptions must document NOISE filter semantics."""
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)
    assert "noise" in form.isi_max_input.description.lower()
    assert "noise" in form.amp_cutoff_input.description.lower()
    assert "noise" in form.presence_min_input.description.lower()
    assert "noise" in form.snr_min_input.description.lower()


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


def test_sorting_form_analyzer_defaults_match_dataclass():
    """SortingForm analyzer config must match AnalyzerConfig() dataclass defaults."""
    from pynpxpipe.core.config import AnalyzerConfig
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    SortingForm(state)
    expected = AnalyzerConfig()
    actual = state.sorting_config.analyzer
    assert actual.template_operators == expected.template_operators
    assert actual.random_spikes.max_spikes_per_unit == expected.random_spikes.max_spikes_per_unit
    assert actual.waveforms.ms_before == expected.waveforms.ms_before


# ─── D.1 Analyzer widgets (M2 UI S5 config alignment) ───


def test_sorting_form_has_analyzer_widgets():
    """SortingForm exposes all 7 analyzer widgets."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert hasattr(form, "analyzer_max_spikes_input")
    assert hasattr(form, "analyzer_random_method_select")
    assert hasattr(form, "analyzer_ms_before_input")
    assert hasattr(form, "analyzer_ms_after_input")
    assert hasattr(form, "analyzer_template_operators_input")
    assert hasattr(form, "analyzer_unit_locations_select")
    assert hasattr(form, "analyzer_template_similarity_select")


def test_sorting_form_analyzer_random_spikes_defaults():
    """Analyzer random_spikes widgets and state carry correct defaults."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert form.analyzer_max_spikes_input.value == 500
    assert form.analyzer_random_method_select.value == "uniform"
    assert state.sorting_config.analyzer.random_spikes.max_spikes_per_unit == 500
    assert state.sorting_config.analyzer.random_spikes.method == "uniform"


def test_sorting_form_analyzer_waveforms_defaults():
    """Analyzer waveforms widgets and state carry correct defaults."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert form.analyzer_ms_before_input.value == 1.0
    assert form.analyzer_ms_after_input.value == 2.0
    assert state.sorting_config.analyzer.waveforms.ms_before == 1.0
    assert state.sorting_config.analyzer.waveforms.ms_after == 2.0


def test_sorting_form_analyzer_template_operators_default():
    """Analyzer template_operators widget and state default to ['average', 'std']."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert list(form.analyzer_template_operators_input.value) == ["average", "std"]
    assert state.sorting_config.analyzer.template_operators == ["average", "std"]


def test_sorting_form_analyzer_unit_locations_method_default():
    """Analyzer unit_locations_method select defaults to monopolar_triangulation."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert form.analyzer_unit_locations_select.value == "monopolar_triangulation"


def test_sorting_form_analyzer_template_similarity_method_default():
    """Analyzer template_similarity_method select defaults to cosine_similarity."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert form.analyzer_template_similarity_select.value == "cosine_similarity"


def test_sorting_form_analyzer_change_updates_state():
    """Changing analyzer widgets propagates to state.sorting_config.analyzer."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    form.analyzer_max_spikes_input.value = 1000
    form.analyzer_ms_before_input.value = 0.5
    form.analyzer_unit_locations_select.value = "center_of_mass"
    assert state.sorting_config.analyzer.random_spikes.max_spikes_per_unit == 1000
    assert state.sorting_config.analyzer.waveforms.ms_before == 0.5
    assert state.sorting_config.analyzer.unit_locations_method == "center_of_mass"


def test_sorting_form_has_analyzer_card():
    """Calling form.panel() succeeds after analyzer widgets are added."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    view = form.panel()
    assert view is not None


def test_sorting_form_analyzer_method_select_options():
    """Analyzer select widgets expose the documented option lists."""
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)
    assert form.analyzer_random_method_select.options == ["uniform", "all", "smart"]
    assert form.analyzer_unit_locations_select.options == [
        "monopolar_triangulation",
        "center_of_mass",
        "grid_convolution",
    ]
    assert form.analyzer_template_similarity_select.options == [
        "cosine_similarity",
        "l1",
        "l2",
    ]


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


# ─────────────────────────────────────────────────────────────────────────────
# F. SubjectForm — YAML BrowsableInput (T3)
# ─────────────────────────────────────────────────────────────────────────────


def test_subject_form_has_yaml_input():
    """SubjectForm exposes a yaml_input BrowsableInput for loading subject YAML."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state)
    assert isinstance(form.yaml_input, BrowsableInput)


def test_subject_form_yaml_input_file_pattern():
    """yaml_input restricts selection to *.yaml files."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state)
    assert form.yaml_input.file_selector.file_pattern == "*.yaml"
    assert form.yaml_input.file_selector.only_files is True


def test_subject_form_yaml_input_auto_loads_on_value_change(tmp_path: Path):
    """Setting yaml_input.value to a valid YAML path auto-loads subject fields."""
    import textwrap

    from pynpxpipe.ui.components.subject_form import SubjectForm

    yaml_content = textwrap.dedent("""\
        Subject:
          subject_id: AutoLoaded
          description: auto
          species: Macaca mulatta
          sex: F
          age: P2Y
          weight: 8kg
    """)
    yaml_file = tmp_path / "auto.yaml"
    yaml_file.write_text(yaml_content)

    state = AppState()
    form = SubjectForm(state)
    form.yaml_input.value = str(yaml_file)

    assert form.subject_id_input.value == "AutoLoaded"
    assert form.sex_select.value == "F"


# ─────────────────────────────────────────────────────────────────────────────
# F2. SubjectForm — Save to monkeys/ (Task 5)
# ─────────────────────────────────────────────────────────────────────────────


def _fill_valid_subject(form, subject_id="Koko"):
    form.subject_id_input.value = subject_id
    form.description_input.value = "calm"
    form.species_input.value = "Macaca mulatta"
    form.sex_select.value = "M"
    form.age_input.value = "P4Y"
    form.weight_input.value = "9kg"


def test_subject_form_has_save_button(tmp_path):
    """SubjectForm exposes a save_btn, save_path_input, and save_message."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state, project_root=tmp_path)
    assert isinstance(form.save_btn, pn.widgets.Button)
    assert isinstance(form.save_path_input, BrowsableInput)
    assert isinstance(form.save_message, pn.pane.Alert)
    assert form.save_message.visible is False


def test_subject_form_save_default_path_uses_monkeys_dir(tmp_path):
    """Clicking save with empty save_path writes to project_root/monkeys/<subject_id>.yaml."""
    from pynpxpipe.core.config import load_subject_config
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state, project_root=tmp_path)
    _fill_valid_subject(form, subject_id="MaoDan")
    form.save_path_input.value = ""
    form._on_save_click(None)

    target = tmp_path / "monkeys" / "MaoDan.yaml"
    assert target.exists()
    loaded = load_subject_config(target)
    assert loaded.subject_id == "MaoDan"
    assert form.save_message.alert_type == "success"
    assert form.save_message.visible is True


def test_subject_form_save_custom_path_is_honored(tmp_path):
    """A user-provided save_path_input value overrides the default location."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state, project_root=tmp_path)
    _fill_valid_subject(form, subject_id="Pippo")

    custom = tmp_path / "custom" / "elsewhere" / "Pippo.yaml"
    form.save_path_input.value = str(custom)
    form._on_save_click(None)

    assert custom.exists()
    assert not (tmp_path / "monkeys" / "Pippo.yaml").exists()


def test_subject_form_save_without_required_fields_warns(tmp_path):
    """If required fields are missing (state.subject_config is None), save warns and does nothing."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    state = AppState()
    form = SubjectForm(state, project_root=tmp_path)
    form.subject_id_input.value = ""  # invalid
    form._on_save_click(None)

    assert form.save_message.alert_type == "warning"
    assert not (tmp_path / "monkeys").exists()


def test_subject_form_save_warns_before_overwriting_existing_file(tmp_path):
    """First click on an existing file only warns; second click actually overwrites."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    target = tmp_path / "monkeys" / "Mono.yaml"
    target.parent.mkdir(parents=True)
    target.write_text("old content\n", encoding="utf-8")

    state = AppState()
    form = SubjectForm(state, project_root=tmp_path)
    _fill_valid_subject(form, subject_id="Mono")

    # First click — warn, no overwrite
    form._on_save_click(None)
    assert form.save_message.alert_type == "warning"
    assert target.read_text(encoding="utf-8") == "old content\n"
    assert form._pending_overwrite_path == target

    # Second click on the same path — overwrite
    form._on_save_click(None)
    assert form.save_message.alert_type == "success"
    assert "old content" not in target.read_text(encoding="utf-8")
    assert form._pending_overwrite_path is None


def test_subject_form_save_changing_path_resets_overwrite_gate(tmp_path):
    """Switching save paths between clicks cancels the pending overwrite."""
    from pynpxpipe.ui.components.subject_form import SubjectForm

    existing = tmp_path / "monkeys" / "Mono.yaml"
    existing.parent.mkdir(parents=True)
    existing.write_text("old\n", encoding="utf-8")

    state = AppState()
    form = SubjectForm(state, project_root=tmp_path)
    _fill_valid_subject(form, subject_id="Mono")

    # Arm overwrite warning on default path
    form._on_save_click(None)
    assert form._pending_overwrite_path == existing

    # Change to a fresh path and click — should save cleanly (no double-click required)
    fresh = tmp_path / "other" / "Mono.yaml"
    form.save_path_input.value = str(fresh)
    form._on_save_click(None)
    assert fresh.exists()
    assert form.save_message.alert_type == "success"


# ─────────────────────────────────────────────────────────────────────────────
# G. SessionLoader — BrowsableInput for dir_input (T3)
# ─────────────────────────────────────────────────────────────────────────────


def test_session_loader_dir_input_is_browsable_input():
    """SessionLoader.dir_input is a BrowsableInput (not a plain TextInput)."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput
    from pynpxpipe.ui.components.session_loader import SessionLoader

    state = AppState()
    loader = SessionLoader(state)
    assert isinstance(loader.dir_input, BrowsableInput)


# ─────────────────────────────────────────────────────────────────────────────
# H. Coverage harness — config<->form drift detection
# ─────────────────────────────────────────────────────────────────────────────

# Each leaf field in PipelineConfig must map to a widget attribute on
# PipelineForm. When a new field is added to core/config.py without exposing
# it in the UI, the coverage test below FAILS with a clear message.
PIPELINE_FORM_FIELD_TO_WIDGET = {
    "resources.n_jobs": "n_jobs_input",
    "resources.chunk_duration": "chunk_duration_input",
    "resources.max_memory": "max_memory_input",
    "parallel.enabled": "parallel_enabled_checkbox",
    "parallel.max_workers": "parallel_max_workers_input",
    "preprocess.bandpass.freq_min": "freq_min_input",
    "preprocess.bandpass.freq_max": "freq_max_input",
    "preprocess.bad_channel_detection.method": "bad_channel_method_input",
    "preprocess.bad_channel_detection.dead_channel_threshold": "dead_channel_threshold_input",
    "preprocess.common_reference.reference": "cmr_reference_select",
    "preprocess.common_reference.operator": "cmr_operator_select",
    "preprocess.motion_correction.method": "motion_enabled_checkbox",
    "preprocess.motion_correction.preset": "motion_preset_select",
    "curation.isi_violation_ratio_max": "isi_max_input",
    "curation.amplitude_cutoff_max": "amp_cutoff_input",
    "curation.presence_ratio_min": "presence_min_input",
    "curation.snr_min": "snr_min_input",
    "curation.good_isi_max": "good_isi_max_input",
    "curation.good_snr_min": "good_snr_min_input",
    "curation.use_bombcell": "use_bombcell_checkbox",
    "sync.imec_sync_bit": "sync_bit_input",
    "sync.nidq_sync_bit": "nidq_sync_bit_input",
    "sync.event_bits": "event_bits_input",
    "sync.max_time_error_ms": "max_time_error_input",
    "sync.trial_count_tolerance": "trial_count_tolerance_input",
    "sync.photodiode_channel_index": "photodiode_channel_input",
    "sync.monitor_delay_ms": "monitor_delay_input",
    "sync.stim_onset_code": "stim_onset_code_input",
    "sync.generate_plots": "generate_plots_checkbox",
    "sync.gap_threshold_ms": "gap_threshold_input",
    "sync.trial_start_bit": "trial_start_bit_input",
    "sync.pd_window_pre_ms": "pd_window_pre_input",
    "sync.pd_window_post_ms": "pd_window_post_input",
    "sync.pd_min_signal_variance": "pd_min_variance_input",
    "postprocess.slay_pre_s": "slay_pre_input",
    "postprocess.slay_post_s": "slay_post_input",
    "postprocess.pre_onset_ms": "pre_onset_ms_input",
    "postprocess.eye_validation.enabled": "eye_enabled_checkbox",
    "postprocess.eye_validation.eye_threshold": "eye_threshold_input",
    "merge.enabled": "merge_enabled_checkbox",
}


SORTING_FORM_FIELD_TO_WIDGET = {
    "mode": "mode_select",
    "sorter.name": "sorter_select",
    "sorter.params.nblocks": "nblocks_input",
    "sorter.params.Th_learned": "th_learned_input",
    "sorter.params.do_CAR": "do_car_checkbox",
    "sorter.params.batch_size": "batch_size_input",
    "sorter.params.n_jobs": "n_jobs_input",
    "sorter.params.torch_device": "torch_device_select",
    # import_cfg.format is derived from sorter_select.value (no dedicated widget)
    "import_cfg.format": "sorter_select",
    "import_cfg.paths": "import_path_input",
    "analyzer.random_spikes.max_spikes_per_unit": "analyzer_max_spikes_input",
    "analyzer.random_spikes.method": "analyzer_random_method_select",
    "analyzer.waveforms.ms_before": "analyzer_ms_before_input",
    "analyzer.waveforms.ms_after": "analyzer_ms_after_input",
    "analyzer.template_operators": "analyzer_template_operators_input",
    "analyzer.unit_locations_method": "analyzer_unit_locations_select",
    "analyzer.template_similarity_method": "analyzer_template_similarity_select",
}


def _enumerate_leaf_fields(dc_cls, prefix=""):
    import dataclasses

    leaves = []
    for fld in dataclasses.fields(dc_cls):
        full = f"{prefix}{fld.name}"
        if dataclasses.is_dataclass(fld.type) if isinstance(fld.type, type) else False:
            leaves.extend(_enumerate_leaf_fields(fld.type, prefix=f"{full}."))
            continue
        # fld.type may be a string due to from __future__ import annotations.
        # Resolve by inspecting the default factory's class.
        try:
            default = (
                fld.default_factory()  # type: ignore[misc]
                if fld.default_factory is not dataclasses.MISSING
                else fld.default
            )
        except Exception:
            default = None
        if dataclasses.is_dataclass(default):
            leaves.extend(_enumerate_leaf_fields(type(default), prefix=f"{full}."))
        else:
            leaves.append(full)
    return leaves


def test_pipeline_form_covers_all_pipeline_config_fields():
    """Every leaf field in PipelineConfig must have a matching widget on PipelineForm."""
    from pynpxpipe.core.config import PipelineConfig
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    form = PipelineForm(state)

    leaves = _enumerate_leaf_fields(PipelineConfig)
    missing_in_map = [f for f in leaves if f not in PIPELINE_FORM_FIELD_TO_WIDGET]
    assert not missing_in_map, (
        f"PipelineConfig has fields without an entry in PIPELINE_FORM_FIELD_TO_WIDGET: "
        f"{missing_in_map}. Add the field to the harness map AND expose a widget."
    )
    extra_in_map = [f for f in PIPELINE_FORM_FIELD_TO_WIDGET if f not in leaves]
    assert not extra_in_map, (
        f"PIPELINE_FORM_FIELD_TO_WIDGET references non-existent PipelineConfig fields: "
        f"{extra_in_map}"
    )
    missing_widgets = [
        (f, w) for f, w in PIPELINE_FORM_FIELD_TO_WIDGET.items() if not hasattr(form, w)
    ]
    assert not missing_widgets, (
        f"PipelineForm is missing widget attributes for fields: {missing_widgets}"
    )


def test_sorting_form_covers_all_sorting_config_fields():
    """Every leaf field in SortingConfig must have a matching widget on SortingForm."""
    from pynpxpipe.core.config import SortingConfig
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    form = SortingForm(state)

    leaves = _enumerate_leaf_fields(SortingConfig)
    missing_in_map = [f for f in leaves if f not in SORTING_FORM_FIELD_TO_WIDGET]
    assert not missing_in_map, (
        f"SortingConfig has fields without an entry in SORTING_FORM_FIELD_TO_WIDGET: "
        f"{missing_in_map}"
    )
    extra_in_map = [f for f in SORTING_FORM_FIELD_TO_WIDGET if f not in leaves]
    assert not extra_in_map, (
        f"SORTING_FORM_FIELD_TO_WIDGET references non-existent SortingConfig fields: {extra_in_map}"
    )
    missing_widgets = [
        (f, w) for f, w in SORTING_FORM_FIELD_TO_WIDGET.items() if not hasattr(form, w)
    ]
    assert not missing_widgets, (
        f"SortingForm is missing widget attributes for fields: {missing_widgets}"
    )


def test_pipeline_form_default_roundtrip():
    """Constructing PipelineForm with no edits must produce default PipelineConfig."""
    import dataclasses

    from pynpxpipe.core.config import PipelineConfig
    from pynpxpipe.ui.components.pipeline_form import PipelineForm

    state = AppState()
    PipelineForm(state)
    assert state.pipeline_config is not None
    actual = dataclasses.asdict(state.pipeline_config)
    expected = dataclasses.asdict(PipelineConfig())
    assert actual == expected, (
        f"PipelineForm default state drift: diff fields: "
        f"{[k for k in expected if expected[k] != actual.get(k)]}"
    )


def test_sorting_form_default_roundtrip():
    """Constructing SortingForm with no edits must produce default SortingConfig."""
    import dataclasses

    from pynpxpipe.core.config import SortingConfig
    from pynpxpipe.ui.components.sorting_form import SortingForm

    state = AppState()
    SortingForm(state)
    assert state.sorting_config is not None
    actual = dataclasses.asdict(state.sorting_config)
    expected = dataclasses.asdict(SortingConfig())
    assert actual == expected, (
        f"SortingForm default state drift: diff fields: "
        f"{[k for k in expected if expected[k] != actual.get(k)]}"
    )
