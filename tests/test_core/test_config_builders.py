"""Tests for _build_* private builder functions in pynpxpipe.core.config.

Each builder takes a raw dict (YAML section) and returns the matching dataclass.
Missing keys fall back to dataclass defaults; unknown keys are silently ignored.
"""

from __future__ import annotations

from pathlib import Path

from pynpxpipe.core.config import (
    _build_analyzer,
    _build_bad_channel,
    _build_bandpass,
    _build_common_reference,
    _build_curation,
    _build_import_cfg,
    _build_motion_correction,
    _build_parallel,
    _build_preprocess,
    _build_resources,
    _build_sorter,
    _build_sync,
)

# ---------------------------------------------------------------------------
# Empty dict → all defaults
# ---------------------------------------------------------------------------


def test_build_resources_empty_returns_defaults():
    cfg = _build_resources({})
    assert cfg.n_jobs == "auto"
    assert cfg.chunk_duration == "auto"
    assert cfg.max_memory == "auto"


def test_build_parallel_empty_returns_defaults():
    cfg = _build_parallel({})
    assert cfg.enabled is False
    assert cfg.max_workers == "auto"


def test_build_bandpass_empty_returns_defaults():
    cfg = _build_bandpass({})
    assert cfg.freq_min == 300.0
    assert cfg.freq_max == 6000.0


def test_build_bad_channel_empty_returns_defaults():
    cfg = _build_bad_channel({})
    assert cfg.method == "coherence+psd"
    assert cfg.dead_channel_threshold == 0.5


def test_build_common_reference_empty_returns_defaults():
    cfg = _build_common_reference({})
    assert cfg.reference == "global"
    assert cfg.operator == "median"


def test_build_motion_correction_empty_returns_defaults():
    cfg = _build_motion_correction({})
    assert cfg.method == "dredge"
    assert cfg.preset == "nonrigid_accurate"


def test_build_preprocess_empty_returns_defaults():
    from pynpxpipe.core.config import PreprocessConfig

    cfg = _build_preprocess({})
    assert isinstance(cfg, PreprocessConfig)
    assert cfg.bandpass.freq_min == 300.0
    assert cfg.bad_channel_detection.method == "coherence+psd"
    assert cfg.common_reference.reference == "global"
    assert cfg.motion_correction.method == "dredge"


def test_build_curation_empty_returns_defaults():
    cfg = _build_curation({})
    assert cfg.isi_violation_ratio_max == 0.1
    assert cfg.amplitude_cutoff_max == 0.1
    assert cfg.presence_ratio_min == 0.9
    assert cfg.snr_min == 0.5


def test_build_sync_empty_returns_defaults():
    cfg = _build_sync({})
    assert cfg.sync_bit == 0
    assert cfg.event_bits == [1, 2, 3, 4, 5, 6, 7]
    assert cfg.max_time_error_ms == 17.0
    assert cfg.generate_plots is True


def test_build_sorter_empty_returns_defaults():
    cfg = _build_sorter({})
    assert cfg.name == "kilosort4"
    assert cfg.params.batch_size == "auto"
    assert cfg.params.nblocks == 15


def test_build_import_cfg_empty_returns_defaults():
    cfg = _build_import_cfg({})
    assert cfg.format == "kilosort4"
    assert cfg.paths == {}


def test_build_analyzer_empty_returns_defaults():
    from pynpxpipe.core.config import AnalyzerConfig

    cfg = _build_analyzer({})
    assert isinstance(cfg, AnalyzerConfig)
    assert cfg.random_spikes.max_spikes_per_unit == 500
    assert cfg.random_spikes.method == "uniform"
    assert cfg.waveforms.ms_before == 1.0
    assert cfg.waveforms.ms_after == 2.0
    assert cfg.unit_locations_method == "monopolar_triangulation"


# ---------------------------------------------------------------------------
# Partial dict → correct fields set, rest are defaults
# ---------------------------------------------------------------------------


def test_build_resources_n_jobs_set():
    cfg = _build_resources({"n_jobs": 8})
    assert cfg.n_jobs == 8
    assert cfg.chunk_duration == "auto"  # unchanged default


def test_build_resources_all_fields_set():
    cfg = _build_resources({"n_jobs": 4, "chunk_duration": "1s", "max_memory": "32G"})
    assert cfg.n_jobs == 4
    assert cfg.chunk_duration == "1s"
    assert cfg.max_memory == "32G"


def test_build_parallel_enabled_set():
    cfg = _build_parallel({"enabled": True, "max_workers": 2})
    assert cfg.enabled is True
    assert cfg.max_workers == 2


def test_build_bandpass_freq_min_set():
    cfg = _build_bandpass({"freq_min": 500.0})
    assert cfg.freq_min == 500.0
    assert cfg.freq_max == 6000.0  # unchanged default


def test_build_bandpass_freq_max_set():
    cfg = _build_bandpass({"freq_max": 5000.0})
    assert cfg.freq_min == 300.0  # unchanged default
    assert cfg.freq_max == 5000.0


def test_build_bad_channel_method_set():
    cfg = _build_bad_channel({"method": "psd"})
    assert cfg.method == "psd"
    assert cfg.dead_channel_threshold == 0.5  # unchanged


def test_build_common_reference_operator_set():
    cfg = _build_common_reference({"operator": "mean"})
    assert cfg.operator == "mean"
    assert cfg.reference == "global"  # unchanged


def test_build_motion_correction_null_method():
    cfg = _build_motion_correction({"method": None})
    assert cfg.method is None


def test_build_motion_correction_method_set():
    cfg = _build_motion_correction({"method": "kilosort"})
    assert cfg.method == "kilosort"


def test_build_curation_thresholds_set():
    cfg = _build_curation({"snr_min": 2.0, "presence_ratio_min": 0.8})
    assert cfg.snr_min == 2.0
    assert cfg.presence_ratio_min == 0.8
    assert cfg.isi_violation_ratio_max == 0.1  # unchanged


def test_build_sync_event_bits_set():
    cfg = _build_sync({"event_bits": [1, 2, 3]})
    assert cfg.event_bits == [1, 2, 3]


def test_build_sync_sync_bit_set():
    cfg = _build_sync({"sync_bit": 7})
    assert cfg.sync_bit == 7
    assert cfg.event_bits == [1, 2, 3, 4, 5, 6, 7]  # unchanged


def test_build_sync_event_bits_is_list_of_int():
    cfg = _build_sync({"event_bits": [1, 2, 3]})
    assert isinstance(cfg.event_bits, list)
    assert all(isinstance(b, int) for b in cfg.event_bits)


def test_build_sorter_name_set():
    cfg = _build_sorter({"name": "kilosort3"})
    assert cfg.name == "kilosort3"
    assert cfg.params.batch_size == "auto"  # nested default unchanged


def test_build_sorter_params_nested():
    cfg = _build_sorter({"name": "kilosort4", "params": {"nblocks": 5}})
    assert cfg.params.nblocks == 5
    assert cfg.params.batch_size == "auto"  # other nested defaults unchanged


def test_build_sorter_params_do_car():
    cfg = _build_sorter({"params": {"do_CAR": True}})
    assert cfg.params.do_CAR is True
    assert cfg.params.nblocks == 15  # unchanged


def test_build_import_cfg_format_set():
    cfg = _build_import_cfg({"format": "phy"})
    assert cfg.format == "phy"
    assert cfg.paths == {}  # unchanged


def test_build_import_cfg_paths_converted_to_path():
    cfg = _build_import_cfg({"paths": {"imec0": "C:/some/path"}})
    assert cfg.paths["imec0"] == Path("C:/some/path")


def test_build_import_cfg_paths_already_path_objects():
    cfg = _build_import_cfg({"paths": {"imec0": Path("/data/sorting")}})
    assert isinstance(cfg.paths["imec0"], Path)


def test_build_import_cfg_multiple_probes():
    cfg = _build_import_cfg({"paths": {"imec0": "/data/probe0", "imec1": "/data/probe1"}})
    assert cfg.paths["imec0"] == Path("/data/probe0")
    assert cfg.paths["imec1"] == Path("/data/probe1")


def test_build_analyzer_nested_random_spikes():
    cfg = _build_analyzer({"random_spikes": {"max_spikes_per_unit": 200}})
    assert cfg.random_spikes.max_spikes_per_unit == 200
    assert cfg.waveforms.ms_before == 1.0  # unchanged nested default


def test_build_analyzer_nested_waveforms():
    cfg = _build_analyzer({"waveforms": {"ms_before": 2.0, "ms_after": 3.0}})
    assert cfg.waveforms.ms_before == 2.0
    assert cfg.waveforms.ms_after == 3.0
    assert cfg.random_spikes.max_spikes_per_unit == 500  # unchanged


def test_build_analyzer_template_operators_set():
    cfg = _build_analyzer({"template_operators": ["average"]})
    assert cfg.template_operators == ["average"]


def test_build_preprocess_bandpass_sub_section():
    cfg = _build_preprocess({"bandpass": {"freq_min": 400.0}})
    assert cfg.bandpass.freq_min == 400.0
    assert cfg.bandpass.freq_max == 6000.0  # unchanged
    assert cfg.common_reference.reference == "global"  # sibling default unchanged


def test_build_preprocess_motion_correction_sub_section():
    cfg = _build_preprocess({"motion_correction": {"method": None}})
    assert cfg.motion_correction.method is None


# ---------------------------------------------------------------------------
# Unknown keys → silently ignored (no exception raised)
# ---------------------------------------------------------------------------


def test_build_resources_unknown_key_ignored():
    cfg = _build_resources({"n_jobs": 4, "this_key_does_not_exist": 99})
    assert cfg.n_jobs == 4
    # must NOT raise


def test_build_parallel_unknown_key_ignored():
    cfg = _build_parallel({"enabled": True, "nonexistent": "value"})
    assert cfg.enabled is True


def test_build_bandpass_unknown_key_ignored():
    cfg = _build_bandpass({"freq_min": 400.0, "mystery_param": 1})
    assert cfg.freq_min == 400.0


def test_build_bad_channel_unknown_key_ignored():
    cfg = _build_bad_channel({"method": "psd", "extra": 42})
    assert cfg.method == "psd"


def test_build_common_reference_unknown_key_ignored():
    cfg = _build_common_reference({"reference": "local", "foo": "bar"})
    assert cfg.reference == "local"


def test_build_motion_correction_unknown_key_ignored():
    cfg = _build_motion_correction({"method": "dredge", "bogus": True})
    assert cfg.method == "dredge"


def test_build_preprocess_unknown_key_in_top_level():
    cfg = _build_preprocess({"bandpass": {"freq_min": 400}, "unknown_section": {}})
    assert cfg.bandpass.freq_min == 400.0


def test_build_preprocess_unknown_key_in_sub_section():
    cfg = _build_preprocess({"bandpass": {"freq_min": 400, "mystery_param": 1}})
    assert cfg.bandpass.freq_min == 400.0
    # must NOT raise


def test_build_curation_unknown_key_ignored():
    cfg = _build_curation({"snr_min": 1.0, "unknown_metric": 99})
    assert cfg.snr_min == 1.0


def test_build_sync_unknown_key_ignored():
    cfg = _build_sync({"sync_bit": 1, "not_a_real_field": "oops"})
    assert cfg.sync_bit == 1


def test_build_sorter_unknown_key_ignored():
    cfg = _build_sorter({"name": "kilosort4", "weird_option": True})
    assert cfg.name == "kilosort4"


def test_build_sorter_params_unknown_key_ignored():
    cfg = _build_sorter({"params": {"nblocks": 5, "invented_param": 999}})
    assert cfg.params.nblocks == 5


def test_build_import_cfg_unknown_key_ignored():
    cfg = _build_import_cfg({"format": "phy", "surprise": 123})
    assert cfg.format == "phy"


def test_build_analyzer_unknown_key_ignored():
    cfg = _build_analyzer({"unit_locations_method": "center_of_mass", "extra": 0})
    assert cfg.unit_locations_method == "center_of_mass"
