"""Tests for _validate_* private validation functions in pynpxpipe.core.config.

TDD: each validation rule has at least one PASS case and one FAIL case.
FAIL cases check exc_info.value.field equals the expected dot-path.
"""

from __future__ import annotations

import pytest

from pynpxpipe.core.config import (
    PipelineConfig,
    SortingConfig,
    _validate_pipeline_config,
    _validate_sorting_config,
    _validate_subject,
)
from pynpxpipe.core.errors import ConfigError

# ===========================================================================
# _validate_pipeline_config — resources
# ===========================================================================


class TestResourcesNJobs:
    def test_auto_passes(self):
        cfg = PipelineConfig()
        cfg.resources.n_jobs = "auto"
        _validate_pipeline_config(cfg)  # should not raise

    def test_valid_int_passes(self):
        cfg = PipelineConfig()
        cfg.resources.n_jobs = 4
        _validate_pipeline_config(cfg)

    def test_zero_raises(self):
        cfg = PipelineConfig()
        cfg.resources.n_jobs = 0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "resources.n_jobs"

    def test_negative_raises(self):
        cfg = PipelineConfig()
        cfg.resources.n_jobs = -1
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "resources.n_jobs"


class TestResourcesChunkDuration:
    def test_auto_passes(self):
        cfg = PipelineConfig()
        cfg.resources.chunk_duration = "auto"
        _validate_pipeline_config(cfg)

    def test_valid_int_seconds_passes(self):
        cfg = PipelineConfig()
        cfg.resources.chunk_duration = "1s"
        _validate_pipeline_config(cfg)

    def test_valid_float_seconds_passes(self):
        cfg = PipelineConfig()
        cfg.resources.chunk_duration = "0.5s"
        _validate_pipeline_config(cfg)

    def test_invalid_no_unit_raises(self):
        cfg = PipelineConfig()
        cfg.resources.chunk_duration = "abc"
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "resources.chunk_duration"

    def test_invalid_ms_unit_raises(self):
        cfg = PipelineConfig()
        cfg.resources.chunk_duration = "100ms"
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "resources.chunk_duration"


class TestResourcesMaxMemory:
    def test_auto_passes(self):
        cfg = PipelineConfig()
        cfg.resources.max_memory = "auto"
        _validate_pipeline_config(cfg)

    def test_valid_gigabytes_passes(self):
        cfg = PipelineConfig()
        cfg.resources.max_memory = "32G"
        _validate_pipeline_config(cfg)

    def test_valid_megabytes_passes(self):
        cfg = PipelineConfig()
        cfg.resources.max_memory = "512M"
        _validate_pipeline_config(cfg)

    def test_invalid_gb_suffix_raises(self):
        cfg = PipelineConfig()
        cfg.resources.max_memory = "32GB"
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "resources.max_memory"

    def test_invalid_no_unit_raises(self):
        cfg = PipelineConfig()
        cfg.resources.max_memory = "32"
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "resources.max_memory"


# ===========================================================================
# _validate_pipeline_config — parallel
# ===========================================================================


class TestParallelMaxWorkers:
    def test_auto_passes(self):
        cfg = PipelineConfig()
        cfg.parallel.max_workers = "auto"
        _validate_pipeline_config(cfg)

    def test_valid_int_passes(self):
        cfg = PipelineConfig()
        cfg.parallel.max_workers = 2
        _validate_pipeline_config(cfg)

    def test_zero_raises(self):
        cfg = PipelineConfig()
        cfg.parallel.max_workers = 0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "parallel.max_workers"

    def test_negative_raises(self):
        cfg = PipelineConfig()
        cfg.parallel.max_workers = -1
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "parallel.max_workers"


# ===========================================================================
# _validate_pipeline_config — preprocess.bandpass
# ===========================================================================


class TestBandpass:
    def test_valid_defaults_pass(self):
        cfg = PipelineConfig()
        _validate_pipeline_config(cfg)

    def test_freq_min_zero_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.bandpass.freq_min = 0.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.bandpass.freq_min"

    def test_freq_min_negative_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.bandpass.freq_min = -100.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.bandpass.freq_min"

    def test_freq_min_greater_than_freq_max_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.bandpass.freq_min = 8000.0
        cfg.preprocess.bandpass.freq_max = 6000.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.bandpass.freq_max"

    def test_freq_min_equal_freq_max_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.bandpass.freq_min = 3000.0
        cfg.preprocess.bandpass.freq_max = 3000.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.bandpass.freq_max"

    def test_freq_max_less_than_freq_min_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.bandpass.freq_min = 300.0
        cfg.preprocess.bandpass.freq_max = 100.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.bandpass.freq_max"


# ===========================================================================
# _validate_pipeline_config — preprocess.bad_channel_detection
# ===========================================================================


class TestBadChannelDetection:
    def test_valid_threshold_passes(self):
        cfg = PipelineConfig()
        cfg.preprocess.bad_channel_detection.dead_channel_threshold = 0.5
        _validate_pipeline_config(cfg)

    def test_threshold_zero_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.bad_channel_detection.dead_channel_threshold = 0.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.bad_channel_detection.dead_channel_threshold"

    def test_threshold_one_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.bad_channel_detection.dead_channel_threshold = 1.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.bad_channel_detection.dead_channel_threshold"

    def test_threshold_above_one_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.bad_channel_detection.dead_channel_threshold = 1.5
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.bad_channel_detection.dead_channel_threshold"


# ===========================================================================
# _validate_pipeline_config — preprocess.common_reference
# ===========================================================================


class TestCommonReference:
    def test_valid_global_median_passes(self):
        cfg = PipelineConfig()
        cfg.preprocess.common_reference.reference = "global"
        cfg.preprocess.common_reference.operator = "median"
        _validate_pipeline_config(cfg)

    def test_valid_local_average_passes(self):
        cfg = PipelineConfig()
        cfg.preprocess.common_reference.reference = "local"
        cfg.preprocess.common_reference.operator = "average"
        _validate_pipeline_config(cfg)

    def test_invalid_reference_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.common_reference.reference = "all"
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.common_reference.reference"

    def test_invalid_operator_mean_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.common_reference.operator = "mean"
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.common_reference.operator"


# ===========================================================================
# _validate_pipeline_config — preprocess.motion_correction
# ===========================================================================


class TestMotionCorrection:
    def test_dredge_passes(self):
        cfg = PipelineConfig()
        cfg.preprocess.motion_correction.method = "dredge"
        _validate_pipeline_config(cfg)

    def test_kilosort_passes(self):
        cfg = PipelineConfig()
        cfg.preprocess.motion_correction.method = "kilosort"
        _validate_pipeline_config(cfg)

    def test_none_method_passes(self):
        cfg = PipelineConfig()
        cfg.preprocess.motion_correction.method = None
        _validate_pipeline_config(cfg)

    def test_invalid_method_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.motion_correction.method = "dredge2"
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.motion_correction.method"

    def test_rigid_fast_preset_passes(self):
        cfg = PipelineConfig()
        cfg.preprocess.motion_correction.preset = "rigid_fast"
        _validate_pipeline_config(cfg)

    def test_nonrigid_accurate_preset_passes(self):
        cfg = PipelineConfig()
        cfg.preprocess.motion_correction.preset = "nonrigid_accurate"
        _validate_pipeline_config(cfg)

    def test_invalid_preset_raises(self):
        cfg = PipelineConfig()
        cfg.preprocess.motion_correction.preset = "fast"
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "preprocess.motion_correction.preset"


# ===========================================================================
# _validate_pipeline_config — curation
# ===========================================================================


class TestCuration:
    def test_defaults_pass(self):
        cfg = PipelineConfig()
        _validate_pipeline_config(cfg)

    def test_isi_violation_ratio_max_negative_raises(self):
        cfg = PipelineConfig()
        cfg.curation.isi_violation_ratio_max = -0.1
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "curation.isi_violation_ratio_max"

    def test_isi_violation_ratio_max_zero_passes(self):
        cfg = PipelineConfig()
        cfg.curation.isi_violation_ratio_max = 0.0
        _validate_pipeline_config(cfg)

    def test_isi_violation_ratio_max_one_passes(self):
        cfg = PipelineConfig()
        cfg.curation.isi_violation_ratio_max = 1.0
        _validate_pipeline_config(cfg)

    def test_amplitude_cutoff_max_above_one_raises(self):
        cfg = PipelineConfig()
        cfg.curation.amplitude_cutoff_max = 1.5
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "curation.amplitude_cutoff_max"

    def test_amplitude_cutoff_max_negative_raises(self):
        cfg = PipelineConfig()
        cfg.curation.amplitude_cutoff_max = -0.1
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "curation.amplitude_cutoff_max"

    def test_presence_ratio_min_above_one_raises(self):
        cfg = PipelineConfig()
        cfg.curation.presence_ratio_min = 1.5
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "curation.presence_ratio_min"

    def test_presence_ratio_min_negative_raises(self):
        cfg = PipelineConfig()
        cfg.curation.presence_ratio_min = -0.1
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "curation.presence_ratio_min"

    def test_snr_min_negative_raises(self):
        cfg = PipelineConfig()
        cfg.curation.snr_min = -1.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "curation.snr_min"

    def test_snr_min_zero_passes(self):
        cfg = PipelineConfig()
        cfg.curation.snr_min = 0.0
        _validate_pipeline_config(cfg)


# ===========================================================================
# _validate_pipeline_config — sync
# ===========================================================================


class TestSync:
    def test_defaults_pass(self):
        cfg = PipelineConfig()
        _validate_pipeline_config(cfg)

    def test_sync_bit_valid_passes(self):
        cfg = PipelineConfig()
        cfg.sync.imec_sync_bit = 3
        _validate_pipeline_config(cfg)

    def test_sync_bit_zero_passes(self):
        cfg = PipelineConfig()
        cfg.sync.imec_sync_bit = 0
        _validate_pipeline_config(cfg)

    def test_sync_bit_seven_passes(self):
        cfg = PipelineConfig()
        cfg.sync.imec_sync_bit = 7
        _validate_pipeline_config(cfg)

    def test_sync_bit_eight_raises(self):
        cfg = PipelineConfig()
        cfg.sync.imec_sync_bit = 8
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.imec_sync_bit"

    def test_sync_bit_negative_raises(self):
        cfg = PipelineConfig()
        cfg.sync.imec_sync_bit = -1
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.imec_sync_bit"

    def test_event_bits_valid_passes(self):
        cfg = PipelineConfig()
        cfg.sync.event_bits = [1, 2, 3]
        _validate_pipeline_config(cfg)

    def test_event_bits_empty_raises(self):
        cfg = PipelineConfig()
        cfg.sync.event_bits = []
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.event_bits"

    def test_event_bits_out_of_range_raises(self):
        cfg = PipelineConfig()
        cfg.sync.event_bits = [1, 2, 8]
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.event_bits"

    def test_event_bits_negative_raises(self):
        cfg = PipelineConfig()
        cfg.sync.event_bits = [-1, 1]
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.event_bits"

    def test_max_time_error_ms_positive_passes(self):
        cfg = PipelineConfig()
        cfg.sync.max_time_error_ms = 17.0
        _validate_pipeline_config(cfg)

    def test_max_time_error_ms_zero_raises(self):
        cfg = PipelineConfig()
        cfg.sync.max_time_error_ms = 0.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.max_time_error_ms"

    def test_max_time_error_ms_negative_raises(self):
        cfg = PipelineConfig()
        cfg.sync.max_time_error_ms = -1.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.max_time_error_ms"

    def test_trial_count_tolerance_zero_passes(self):
        cfg = PipelineConfig()
        cfg.sync.trial_count_tolerance = 0
        _validate_pipeline_config(cfg)

    def test_trial_count_tolerance_positive_passes(self):
        cfg = PipelineConfig()
        cfg.sync.trial_count_tolerance = 5
        _validate_pipeline_config(cfg)

    def test_trial_count_tolerance_negative_raises(self):
        cfg = PipelineConfig()
        cfg.sync.trial_count_tolerance = -1
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.trial_count_tolerance"

    def test_stim_onset_code_valid_passes(self):
        cfg = PipelineConfig()
        cfg.sync.stim_onset_code = 64
        _validate_pipeline_config(cfg)

    def test_stim_onset_code_zero_passes(self):
        cfg = PipelineConfig()
        cfg.sync.stim_onset_code = 0
        _validate_pipeline_config(cfg)

    def test_stim_onset_code_255_passes(self):
        cfg = PipelineConfig()
        cfg.sync.stim_onset_code = 255
        _validate_pipeline_config(cfg)

    def test_stim_onset_code_above_255_raises(self):
        cfg = PipelineConfig()
        cfg.sync.stim_onset_code = 300
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.stim_onset_code"

    def test_stim_onset_code_negative_raises(self):
        cfg = PipelineConfig()
        cfg.sync.stim_onset_code = -1
        with pytest.raises(ConfigError) as exc_info:
            _validate_pipeline_config(cfg)
        assert exc_info.value.field == "sync.stim_onset_code"


# ===========================================================================
# _validate_sorting_config — sorting.mode
# ===========================================================================


class TestSortingMode:
    def test_local_passes(self):
        cfg = SortingConfig()
        cfg.mode = "local"
        _validate_sorting_config(cfg)

    def test_import_passes(self):
        cfg = SortingConfig()
        cfg.mode = "import"
        _validate_sorting_config(cfg)

    def test_invalid_mode_raises(self):
        cfg = SortingConfig()
        cfg.mode = "both"
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "sorting.mode"


# ===========================================================================
# _validate_sorting_config — sorter.params
# ===========================================================================


class TestSorterParams:
    def test_defaults_pass(self):
        cfg = SortingConfig()
        _validate_sorting_config(cfg)

    def test_nblocks_zero_passes(self):
        cfg = SortingConfig()
        cfg.sorter.params.nblocks = 0
        _validate_sorting_config(cfg)

    def test_nblocks_negative_raises(self):
        cfg = SortingConfig()
        cfg.sorter.params.nblocks = -1
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "sorter.params.nblocks"

    def test_th_learned_positive_passes(self):
        cfg = SortingConfig()
        cfg.sorter.params.Th_learned = 7.0
        _validate_sorting_config(cfg)

    def test_th_learned_zero_raises(self):
        cfg = SortingConfig()
        cfg.sorter.params.Th_learned = 0.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "sorter.params.Th_learned"

    def test_th_learned_negative_raises(self):
        cfg = SortingConfig()
        cfg.sorter.params.Th_learned = -1.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "sorter.params.Th_learned"

    def test_batch_size_auto_passes(self):
        cfg = SortingConfig()
        cfg.sorter.params.batch_size = "auto"
        _validate_sorting_config(cfg)

    def test_batch_size_valid_int_passes(self):
        cfg = SortingConfig()
        cfg.sorter.params.batch_size = 65536
        _validate_sorting_config(cfg)

    def test_batch_size_zero_raises(self):
        cfg = SortingConfig()
        cfg.sorter.params.batch_size = 0
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "sorter.params.batch_size"

    def test_batch_size_negative_raises(self):
        cfg = SortingConfig()
        cfg.sorter.params.batch_size = -1
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "sorter.params.batch_size"

    def test_n_jobs_one_passes(self):
        cfg = SortingConfig()
        cfg.sorter.params.n_jobs = 1
        _validate_sorting_config(cfg)

    def test_n_jobs_zero_raises(self):
        cfg = SortingConfig()
        cfg.sorter.params.n_jobs = 0
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "sorter.params.n_jobs"


# ===========================================================================
# _validate_sorting_config — import_cfg
# ===========================================================================


class TestImportCfg:
    def test_kilosort4_passes(self):
        cfg = SortingConfig()
        cfg.import_cfg.format = "kilosort4"
        _validate_sorting_config(cfg)

    def test_phy_passes(self):
        cfg = SortingConfig()
        cfg.import_cfg.format = "phy"
        _validate_sorting_config(cfg)

    def test_invalid_format_raises(self):
        cfg = SortingConfig()
        cfg.import_cfg.format = "kilosort3"
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "import_cfg.format"


# ===========================================================================
# _validate_sorting_config — analyzer
# ===========================================================================


class TestAnalyzerRandomSpikes:
    def test_valid_max_spikes_passes(self):
        cfg = SortingConfig()
        cfg.analyzer.random_spikes.max_spikes_per_unit = 500
        _validate_sorting_config(cfg)

    def test_max_spikes_one_passes(self):
        cfg = SortingConfig()
        cfg.analyzer.random_spikes.max_spikes_per_unit = 1
        _validate_sorting_config(cfg)

    def test_max_spikes_zero_raises(self):
        cfg = SortingConfig()
        cfg.analyzer.random_spikes.max_spikes_per_unit = 0
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "analyzer.random_spikes.max_spikes_per_unit"

    def test_method_uniform_passes(self):
        cfg = SortingConfig()
        cfg.analyzer.random_spikes.method = "uniform"
        _validate_sorting_config(cfg)

    def test_method_all_passes(self):
        cfg = SortingConfig()
        cfg.analyzer.random_spikes.method = "all"
        _validate_sorting_config(cfg)

    def test_method_smart_passes(self):
        cfg = SortingConfig()
        cfg.analyzer.random_spikes.method = "smart"
        _validate_sorting_config(cfg)

    def test_method_invalid_raises(self):
        cfg = SortingConfig()
        cfg.analyzer.random_spikes.method = "random"
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "analyzer.random_spikes.method"


class TestAnalyzerWaveforms:
    def test_valid_ms_before_passes(self):
        cfg = SortingConfig()
        cfg.analyzer.waveforms.ms_before = 1.0
        _validate_sorting_config(cfg)

    def test_ms_before_zero_raises(self):
        cfg = SortingConfig()
        cfg.analyzer.waveforms.ms_before = 0.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "analyzer.waveforms.ms_before"

    def test_ms_before_negative_raises(self):
        cfg = SortingConfig()
        cfg.analyzer.waveforms.ms_before = -1.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "analyzer.waveforms.ms_before"

    def test_valid_ms_after_passes(self):
        cfg = SortingConfig()
        cfg.analyzer.waveforms.ms_after = 2.0
        _validate_sorting_config(cfg)

    def test_ms_after_zero_raises(self):
        cfg = SortingConfig()
        cfg.analyzer.waveforms.ms_after = 0.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "analyzer.waveforms.ms_after"

    def test_ms_after_negative_raises(self):
        cfg = SortingConfig()
        cfg.analyzer.waveforms.ms_after = -1.0
        with pytest.raises(ConfigError) as exc_info:
            _validate_sorting_config(cfg)
        assert exc_info.value.field == "analyzer.waveforms.ms_after"


# ===========================================================================
# _validate_subject
# ===========================================================================


class TestValidateSubject:
    def test_valid_dict_passes(self):
        raw = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "species": "Macaca mulatta",
            "sex": "M",
            "age": "P4Y",
            "weight": "12.8kg",
        }
        _validate_subject(raw)  # should not raise

    def test_missing_subject_id_raises(self):
        raw = {
            "description": "good monkey",
            "species": "Macaca mulatta",
            "sex": "M",
            "age": "P4Y",
        }
        with pytest.raises(ConfigError) as exc_info:
            _validate_subject(raw)
        assert exc_info.value.field == "subject.subject_id"

    def test_missing_description_raises(self):
        raw = {
            "subject_id": "MaoDan",
            "species": "Macaca mulatta",
            "sex": "M",
            "age": "P4Y",
        }
        with pytest.raises(ConfigError) as exc_info:
            _validate_subject(raw)
        assert exc_info.value.field == "subject.description"

    def test_missing_species_raises(self):
        raw = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "sex": "M",
            "age": "P4Y",
        }
        with pytest.raises(ConfigError) as exc_info:
            _validate_subject(raw)
        assert exc_info.value.field == "subject.species"

    def test_missing_sex_raises(self):
        raw = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "species": "Macaca mulatta",
            "age": "P4Y",
        }
        with pytest.raises(ConfigError) as exc_info:
            _validate_subject(raw)
        assert exc_info.value.field == "subject.sex"

    def test_missing_age_raises(self):
        raw = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "species": "Macaca mulatta",
            "sex": "M",
        }
        with pytest.raises(ConfigError) as exc_info:
            _validate_subject(raw)
        assert exc_info.value.field == "subject.age"

    def test_weight_optional_passes(self):
        raw = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "species": "Macaca mulatta",
            "sex": "M",
            "age": "P4Y",
            # no weight
        }
        _validate_subject(raw)  # should not raise

    def test_invalid_sex_raises(self):
        raw = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "species": "Macaca mulatta",
            "sex": "Male",
            "age": "P4Y",
        }
        with pytest.raises(ConfigError) as exc_info:
            _validate_subject(raw)
        assert exc_info.value.field == "subject.sex"

    def test_valid_sex_values_pass(self):
        base = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "species": "Macaca mulatta",
            "age": "P4Y",
        }
        for sex in ("M", "F", "U", "O"):
            _validate_subject({**base, "sex": sex})

    def test_invalid_age_format_raises(self):
        raw = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "species": "Macaca mulatta",
            "sex": "M",
            "age": "4years",
        }
        with pytest.raises(ConfigError) as exc_info:
            _validate_subject(raw)
        assert exc_info.value.field == "subject.age"

    def test_valid_age_formats_pass(self):
        base = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "species": "Macaca mulatta",
            "sex": "M",
        }
        for age in ("P4Y", "P6M", "P30D", "P12Y"):
            _validate_subject({**base, "age": age})

    def test_age_with_multiple_components_raises(self):
        # "P4Y6M" is valid ISO 8601 but spec regex only allows P + digits + single letter
        raw = {
            "subject_id": "MaoDan",
            "description": "good monkey",
            "species": "Macaca mulatta",
            "sex": "M",
            "age": "P4Y6M",
        }
        with pytest.raises(ConfigError) as exc_info:
            _validate_subject(raw)
        assert exc_info.value.field == "subject.age"
