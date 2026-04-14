"""Tests for config dataclass definitions.

Verifies default values, nested structure, and type flexibility for all
config dataclasses in pynpxpipe.core.config.
"""

from __future__ import annotations

from pynpxpipe.core.config import (
    AnalyzerConfig,
    BadChannelConfig,
    BandpassConfig,
    CommonReferenceConfig,
    CurationConfig,
    EyeValidationConfig,
    ImportConfig,
    MotionCorrectionConfig,
    ParallelConfig,
    PipelineConfig,
    PostprocessConfig,
    PreprocessConfig,
    RandomSpikesConfig,
    ResourcesConfig,
    SorterConfig,
    SorterParams,
    SortingConfig,
    SubjectConfig,
    SyncConfig,
    WaveformConfig,
)

# ---------------------------------------------------------------------------
# 1. Every dataclass can be instantiated with no arguments (default values)
# ---------------------------------------------------------------------------


def test_resources_config_default_instantiation():
    cfg = ResourcesConfig()
    assert cfg is not None


def test_parallel_config_default_instantiation():
    cfg = ParallelConfig()
    assert cfg is not None


def test_bandpass_config_default_instantiation():
    cfg = BandpassConfig()
    assert cfg is not None


def test_bad_channel_config_default_instantiation():
    cfg = BadChannelConfig()
    assert cfg is not None


def test_common_reference_config_default_instantiation():
    cfg = CommonReferenceConfig()
    assert cfg is not None


def test_motion_correction_config_default_instantiation():
    cfg = MotionCorrectionConfig()
    assert cfg is not None


def test_preprocess_config_default_instantiation():
    cfg = PreprocessConfig()
    assert cfg is not None


def test_curation_config_default_instantiation():
    cfg = CurationConfig()
    assert cfg is not None


def test_sync_config_default_instantiation():
    cfg = SyncConfig()
    assert cfg is not None


def test_eye_validation_config_default_instantiation():
    cfg = EyeValidationConfig()
    assert cfg is not None


def test_postprocess_config_default_instantiation():
    cfg = PostprocessConfig()
    assert cfg is not None


def test_pipeline_config_default_instantiation():
    cfg = PipelineConfig()
    assert cfg is not None


def test_sorter_params_default_instantiation():
    cfg = SorterParams()
    assert cfg is not None


def test_sorter_config_default_instantiation():
    cfg = SorterConfig()
    assert cfg is not None


def test_import_config_default_instantiation():
    cfg = ImportConfig()
    assert cfg is not None


def test_random_spikes_config_default_instantiation():
    cfg = RandomSpikesConfig()
    assert cfg is not None


def test_waveform_config_default_instantiation():
    cfg = WaveformConfig()
    assert cfg is not None


def test_analyzer_config_default_instantiation():
    cfg = AnalyzerConfig()
    assert cfg is not None


def test_sorting_config_default_instantiation():
    cfg = SortingConfig()
    assert cfg is not None


def test_subject_config_default_instantiation():
    cfg = SubjectConfig()
    assert cfg is not None


# ---------------------------------------------------------------------------
# 2. "auto" fields accept the string "auto" (type is int | str)
# ---------------------------------------------------------------------------


def test_resources_n_jobs_accepts_auto_string():
    cfg = ResourcesConfig(n_jobs="auto")
    assert cfg.n_jobs == "auto"


def test_parallel_max_workers_accepts_auto_string():
    cfg = ParallelConfig(max_workers="auto")
    assert cfg.max_workers == "auto"


def test_sorter_params_batch_size_accepts_auto_string():
    cfg = SorterParams(batch_size="auto")
    assert cfg.batch_size == "auto"


# ---------------------------------------------------------------------------
# 3. "auto" fields also accept integers (type is int | str)
# ---------------------------------------------------------------------------


def test_resources_n_jobs_accepts_integer():
    cfg = ResourcesConfig(n_jobs=8)
    assert cfg.n_jobs == 8


def test_parallel_max_workers_accepts_integer():
    cfg = ParallelConfig(max_workers=4)
    assert cfg.max_workers == 4


def test_sorter_params_batch_size_accepts_integer():
    cfg = SorterParams(batch_size=65536)
    assert cfg.batch_size == 65536


# ---------------------------------------------------------------------------
# 4. Nested dataclasses are correctly nested
# ---------------------------------------------------------------------------


def test_pipeline_config_preprocess_is_preprocess_config():
    cfg = PipelineConfig()
    assert isinstance(cfg.preprocess, PreprocessConfig)


def test_pipeline_config_resources_is_resources_config():
    cfg = PipelineConfig()
    assert isinstance(cfg.resources, ResourcesConfig)


def test_pipeline_config_parallel_is_parallel_config():
    cfg = PipelineConfig()
    assert isinstance(cfg.parallel, ParallelConfig)


def test_pipeline_config_curation_is_curation_config():
    cfg = PipelineConfig()
    assert isinstance(cfg.curation, CurationConfig)


def test_pipeline_config_sync_is_sync_config():
    cfg = PipelineConfig()
    assert isinstance(cfg.sync, SyncConfig)


def test_preprocess_config_bandpass_is_bandpass_config():
    cfg = PreprocessConfig()
    assert isinstance(cfg.bandpass, BandpassConfig)


def test_preprocess_config_bad_channel_is_bad_channel_config():
    cfg = PreprocessConfig()
    assert isinstance(cfg.bad_channel_detection, BadChannelConfig)


def test_preprocess_config_common_reference_is_common_reference_config():
    cfg = PreprocessConfig()
    assert isinstance(cfg.common_reference, CommonReferenceConfig)


def test_preprocess_config_motion_correction_is_motion_correction_config():
    cfg = PreprocessConfig()
    assert isinstance(cfg.motion_correction, MotionCorrectionConfig)


def test_sorting_config_sorter_is_sorter_config():
    cfg = SortingConfig()
    assert isinstance(cfg.sorter, SorterConfig)


def test_sorting_config_import_cfg_is_import_config():
    cfg = SortingConfig()
    assert isinstance(cfg.import_cfg, ImportConfig)


def test_sorting_config_analyzer_is_analyzer_config():
    cfg = SortingConfig()
    assert isinstance(cfg.analyzer, AnalyzerConfig)


def test_sorter_config_params_is_sorter_params():
    cfg = SorterConfig()
    assert isinstance(cfg.params, SorterParams)


def test_analyzer_config_random_spikes_is_random_spikes_config():
    cfg = AnalyzerConfig()
    assert isinstance(cfg.random_spikes, RandomSpikesConfig)


def test_analyzer_config_waveforms_is_waveform_config():
    cfg = AnalyzerConfig()
    assert isinstance(cfg.waveforms, WaveformConfig)


# ---------------------------------------------------------------------------
# 5. New dataclasses exist and are importable
# ---------------------------------------------------------------------------


def test_bad_channel_config_exists():
    cfg = BadChannelConfig()
    assert hasattr(cfg, "method")
    assert hasattr(cfg, "dead_channel_threshold")


def test_common_reference_config_exists():
    cfg = CommonReferenceConfig()
    assert hasattr(cfg, "reference")
    assert hasattr(cfg, "operator")


def test_random_spikes_config_exists():
    cfg = RandomSpikesConfig()
    assert hasattr(cfg, "max_spikes_per_unit")
    assert hasattr(cfg, "method")


# ---------------------------------------------------------------------------
# 6. PreprocessConfig has exactly 4 sub-fields
# ---------------------------------------------------------------------------


def test_preprocess_config_has_bandpass_field():
    cfg = PreprocessConfig()
    assert hasattr(cfg, "bandpass")


def test_preprocess_config_has_bad_channel_detection_field():
    cfg = PreprocessConfig()
    assert hasattr(cfg, "bad_channel_detection")


def test_preprocess_config_has_common_reference_field():
    cfg = PreprocessConfig()
    assert hasattr(cfg, "common_reference")


def test_preprocess_config_has_motion_correction_field():
    cfg = PreprocessConfig()
    assert hasattr(cfg, "motion_correction")


def test_preprocess_config_has_exactly_4_fields():
    import dataclasses

    fields = dataclasses.fields(PreprocessConfig)
    assert len(fields) == 4


# ---------------------------------------------------------------------------
# 7. AnalyzerConfig field structure
# ---------------------------------------------------------------------------


def test_pipeline_config_has_exactly_7_fields():
    import dataclasses

    fields = dataclasses.fields(PipelineConfig)
    assert len(fields) == 7


def test_sync_config_has_exactly_14_fields():
    import dataclasses

    fields = dataclasses.fields(SyncConfig)
    assert len(fields) == 14


def test_postprocess_config_has_exactly_4_fields():
    import dataclasses

    fields = dataclasses.fields(PostprocessConfig)
    assert len(fields) == 4


def test_analyzer_config_has_random_spikes_field():
    cfg = AnalyzerConfig()
    assert isinstance(cfg.random_spikes, RandomSpikesConfig)


def test_analyzer_config_has_waveforms_field():
    cfg = AnalyzerConfig()
    assert isinstance(cfg.waveforms, WaveformConfig)


def test_analyzer_config_has_template_operators_list():
    cfg = AnalyzerConfig()
    assert isinstance(cfg.template_operators, list)


def test_analyzer_config_has_unit_locations_method_str():
    cfg = AnalyzerConfig()
    assert isinstance(cfg.unit_locations_method, str)


def test_analyzer_config_has_template_similarity_method_str():
    cfg = AnalyzerConfig()
    assert isinstance(cfg.template_similarity_method, str)


def test_analyzer_config_has_exactly_5_fields():
    import dataclasses

    fields = dataclasses.fields(AnalyzerConfig)
    assert len(fields) == 5


# ---------------------------------------------------------------------------
# 8. Default values match the spec
# ---------------------------------------------------------------------------


def test_bandpass_config_freq_min_default():
    assert BandpassConfig().freq_min == 300.0


def test_bandpass_config_freq_max_default():
    assert BandpassConfig().freq_max == 6000.0


def test_sync_config_stim_onset_code_default():
    assert SyncConfig().stim_onset_code == 64


def test_sorter_params_batch_size_default_is_auto():
    assert SorterParams().batch_size == "auto"


def test_sync_config_event_bits_default():
    assert SyncConfig().event_bits == [1, 2, 3, 4, 5, 6, 7]


def test_sync_config_event_bits_default_is_independent_copy():
    cfg1 = SyncConfig()
    cfg2 = SyncConfig()
    cfg1.event_bits.append(99)
    assert cfg2.event_bits == [1, 2, 3, 4, 5, 6, 7]


def test_resources_config_n_jobs_default():
    assert ResourcesConfig().n_jobs == "auto"


def test_parallel_config_enabled_default():
    assert ParallelConfig().enabled is False


def test_motion_correction_config_method_default():
    assert MotionCorrectionConfig().method == "dredge"


def test_bad_channel_config_method_default():
    assert BadChannelConfig().method == "coherence+psd"


def test_bad_channel_config_dead_channel_threshold_default():
    assert BadChannelConfig().dead_channel_threshold == 0.5


def test_common_reference_config_reference_default():
    assert CommonReferenceConfig().reference == "global"


def test_common_reference_config_operator_default():
    assert CommonReferenceConfig().operator == "median"


def test_random_spikes_config_max_spikes_per_unit_default():
    assert RandomSpikesConfig().max_spikes_per_unit == 500


def test_random_spikes_config_method_default():
    assert RandomSpikesConfig().method == "uniform"


def test_waveform_config_ms_before_default():
    assert WaveformConfig().ms_before == 1.0


def test_waveform_config_ms_after_default():
    assert WaveformConfig().ms_after == 2.0


def test_analyzer_config_template_operators_default():
    assert AnalyzerConfig().template_operators == ["average", "std"]


def test_analyzer_config_unit_locations_method_default():
    assert AnalyzerConfig().unit_locations_method == "monopolar_triangulation"


def test_analyzer_config_template_similarity_method_default():
    assert AnalyzerConfig().template_similarity_method == "cosine_similarity"


def test_sorter_config_name_default():
    assert SorterConfig().name == "kilosort4"


def test_sorting_config_mode_default():
    assert SortingConfig().mode == "local"


def test_subject_config_subject_id_default():
    assert SubjectConfig().subject_id == ""


def test_curation_config_isi_violation_ratio_max_default():
    assert CurationConfig().isi_violation_ratio_max == 2.0


def test_sorter_params_nblocks_default():
    assert SorterParams().nblocks == 0


def test_sorter_params_do_car_default():
    assert SorterParams().do_CAR is False
