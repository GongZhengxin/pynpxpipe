"""Real-data integration tests for pynpxpipe.core.config.

Loads the actual config files committed to the repository and verifies
end-to-end behaviour: parsing, field values, merge_with_overrides, and
subject config loading.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pynpxpipe.core.config import (
    AnalyzerConfig,
    PipelineConfig,
    SortingConfig,
    SubjectConfig,
    load_pipeline_config,
    load_sorting_config,
    load_subject_config,
    merge_with_overrides,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent


def _pipeline_yaml_path() -> Path:
    return _PROJECT_ROOT / "config" / "pipeline.yaml"


def _sorting_yaml_path() -> Path:
    return _PROJECT_ROOT / "config" / "sorting.yaml"


def _monkey_yaml_paths() -> list[Path]:
    monkeys_dir = _PROJECT_ROOT / "monkeys"
    if not monkeys_dir.is_dir():
        return []
    return list(monkeys_dir.glob("*.yaml"))


# ===========================================================================
# Test A: load real pipeline.yaml
# ===========================================================================


def test_load_real_pipeline_yaml():
    """Load the actual project pipeline.yaml and verify it parses correctly."""
    config_path = _pipeline_yaml_path()
    assert config_path.exists(), f"pipeline.yaml not found at {config_path}"

    config = load_pipeline_config(config_path)

    assert isinstance(config, PipelineConfig)


def test_real_pipeline_yaml_resources_fields():
    """Verify resources section values match pipeline.yaml exactly."""
    config = load_pipeline_config(_pipeline_yaml_path())

    # pipeline.yaml: n_jobs: auto, chunk_duration: auto, max_memory: auto
    assert config.resources.n_jobs == "auto"
    assert config.resources.chunk_duration == "auto"
    assert config.resources.max_memory == "auto"


def test_real_pipeline_yaml_parallel_fields():
    """Verify parallel section values match pipeline.yaml exactly."""
    config = load_pipeline_config(_pipeline_yaml_path())

    # pipeline.yaml: enabled: false, max_workers: auto
    assert config.parallel.enabled is False
    assert config.parallel.max_workers == "auto"


def test_real_pipeline_yaml_preprocess_fields():
    """Verify preprocess section values match pipeline.yaml exactly."""
    config = load_pipeline_config(_pipeline_yaml_path())

    # pipeline.yaml: freq_min: 300, freq_max: 6000
    assert config.preprocess.bandpass.freq_min == 300.0
    assert config.preprocess.bandpass.freq_max == 6000.0

    # bad_channel_detection: method: "coherence+psd", dead_channel_threshold: 0.5
    assert config.preprocess.bad_channel_detection.method == "coherence+psd"
    assert config.preprocess.bad_channel_detection.dead_channel_threshold == 0.5

    # common_reference: reference: "global", operator: "median"
    assert config.preprocess.common_reference.reference == "global"
    assert config.preprocess.common_reference.operator == "median"

    # motion_correction: method: "dredge", preset: "dredge"
    assert config.preprocess.motion_correction.method == "dredge"
    assert config.preprocess.motion_correction.preset == "dredge"


def test_real_pipeline_yaml_curation_fields():
    """Verify curation section values match pipeline.yaml exactly."""
    config = load_pipeline_config(_pipeline_yaml_path())

    # pipeline.yaml curation thresholds
    assert config.curation.isi_violation_ratio_max == 2.0
    assert config.curation.amplitude_cutoff_max == 0.5
    assert config.curation.presence_ratio_min == 0.5
    assert config.curation.snr_min == 0.3
    assert config.curation.good_isi_max == 0.1
    assert config.curation.good_snr_min == 3.0


def test_real_pipeline_yaml_sync_fields():
    """Verify sync section values match pipeline.yaml exactly."""
    config = load_pipeline_config(_pipeline_yaml_path())

    # pipeline.yaml sync parameters
    assert config.sync.imec_sync_bit == 6
    assert config.sync.event_bits == [1, 2, 3, 4, 5, 6, 7]
    assert config.sync.max_time_error_ms == 17.0
    assert config.sync.trial_count_tolerance == 2
    assert config.sync.photodiode_channel_index == 0
    assert config.sync.monitor_delay_ms == -5.0
    assert config.sync.stim_onset_code == 64
    assert config.sync.generate_plots is True


# ===========================================================================
# Test B: load real sorting.yaml
# ===========================================================================


def test_load_real_sorting_yaml():
    """Load the actual project sorting.yaml and verify it parses correctly."""
    config_path = _sorting_yaml_path()
    assert config_path.exists(), f"sorting.yaml not found at {config_path}"

    config = load_sorting_config(config_path)

    assert isinstance(config, SortingConfig)


def test_real_sorting_yaml_mode():
    """Verify mode field matches sorting.yaml."""
    config = load_sorting_config(_sorting_yaml_path())

    # sorting.yaml: mode: "local"
    assert config.mode == "local"


def test_real_sorting_yaml_sorter_fields():
    """Verify sorter section values match sorting.yaml exactly."""
    config = load_sorting_config(_sorting_yaml_path())

    # sorting.yaml: name: "kilosort4"
    assert config.sorter.name == "kilosort4"

    # sorting.yaml sorter.params
    assert config.sorter.params.nblocks == 0
    assert config.sorter.params.Th_learned == 8.0
    assert config.sorter.params.Th_universal == 9.0
    assert config.sorter.params.cluster_downsampling == 1
    assert config.sorter.params.max_cluster_subset == 25000
    assert config.sorter.params.do_CAR is False
    assert config.sorter.params.batch_size == "auto"
    assert config.sorter.params.n_jobs == 1


def test_real_sorting_yaml_import_cfg_populated():
    """Verify import_cfg is populated from sorting.yaml 'import:' section."""
    config = load_sorting_config(_sorting_yaml_path())

    # CRITICAL: sorting.yaml has 'import:' section with format: "kilosort4"
    assert config.import_cfg is not None
    assert config.import_cfg.format == "kilosort4"
    # paths not specified in YAML (commented out) → empty dict
    assert config.import_cfg.paths == {}


def test_real_sorting_yaml_analyzer_fields():
    """Verify analyzer section values match sorting.yaml exactly."""
    config = load_sorting_config(_sorting_yaml_path())

    assert isinstance(config.analyzer, AnalyzerConfig)

    # random_spikes: max_spikes_per_unit: 500, method: "uniform"
    assert config.analyzer.random_spikes.max_spikes_per_unit == 500
    assert config.analyzer.random_spikes.method == "uniform"

    # waveforms: ms_before: 1.0, ms_after: 2.0
    assert config.analyzer.waveforms.ms_before == 1.0
    assert config.analyzer.waveforms.ms_after == 2.0

    # templates: operators: ["average", "std"]
    assert config.analyzer.template_operators == ["average", "std"]

    # unit_locations: method: "monopolar_triangulation"
    assert config.analyzer.unit_locations_method == "monopolar_triangulation"

    # template_similarity: method: "cosine_similarity"
    assert config.analyzer.template_similarity_method == "cosine_similarity"


# ===========================================================================
# Test D: merge_with_overrides on real pipeline config
# ===========================================================================


def test_merge_overrides_on_real_pipeline_config_n_jobs():
    """merge_with_overrides updates n_jobs while leaving other fields unchanged."""
    config = load_pipeline_config(_pipeline_yaml_path())
    original_chunk_duration = config.resources.chunk_duration

    new_config = merge_with_overrides(config, {"resources": {"n_jobs": 16}})

    assert new_config.resources.n_jobs == 16
    # Other resource fields unchanged
    assert new_config.resources.chunk_duration == original_chunk_duration
    assert new_config.resources.max_memory == config.resources.max_memory


def test_merge_overrides_on_real_pipeline_config_does_not_mutate():
    """merge_with_overrides returns a new object, the original is not mutated."""
    config = load_pipeline_config(_pipeline_yaml_path())

    new_config = merge_with_overrides(config, {"resources": {"n_jobs": 4}})

    assert new_config is not config
    # Original remains "auto" (as set in pipeline.yaml)
    assert config.resources.n_jobs == "auto"
    assert new_config.resources.n_jobs == 4


def test_merge_overrides_on_real_pipeline_config_nested_sync():
    """merge_with_overrides can update a nested sync field."""
    config = load_pipeline_config(_pipeline_yaml_path())

    new_config = merge_with_overrides(config, {"sync": {"max_time_error_ms": 10.0}})

    assert new_config.sync.max_time_error_ms == 10.0
    # Unmodified sync fields remain as in the real YAML
    assert new_config.sync.imec_sync_bit == config.sync.imec_sync_bit
    assert new_config.sync.stim_onset_code == config.sync.stim_onset_code


def test_merge_overrides_on_real_sorting_config():
    """merge_with_overrides works on a real SortingConfig loaded from file."""
    config = load_sorting_config(_sorting_yaml_path())
    original_name = config.sorter.name

    new_config = merge_with_overrides(config, {"sorter": {"params": {"nblocks": 5}}})

    assert new_config.sorter.params.nblocks == 5
    # Other sorter fields unchanged
    assert new_config.sorter.name == original_name
    assert new_config.sorter.params.Th_learned == config.sorter.params.Th_learned


# ===========================================================================
# Test E: load_subject_config for each real monkeys/*.yaml file
# ===========================================================================


def _all_monkey_yaml_ids() -> list[str]:
    """Return a pytest parameter id for each monkey YAML found."""
    return [p.stem for p in _monkey_yaml_paths()]


@pytest.mark.parametrize("monkey_stem", _all_monkey_yaml_ids() or ["_skip"])
def test_load_real_subject_config(monkey_stem: str):
    """Load each real monkeys/*.yaml and verify it parses into SubjectConfig."""
    if monkey_stem == "_skip":
        pytest.skip("no monkeys/*.yaml found")

    yaml_path = _PROJECT_ROOT / "monkeys" / f"{monkey_stem}.yaml"
    config = load_subject_config(yaml_path)

    assert isinstance(config, SubjectConfig)
    assert config.subject_id != ""
    assert config.species != ""
    assert config.sex in {"M", "F", "U", "O"}
    # ISO 8601 duration: starts with P
    assert config.age.startswith("P")


def test_load_maodan_yaml_field_values():
    """Verify MaoDan.yaml specific field values."""
    yaml_paths = _monkey_yaml_paths()
    maodan = next((p for p in yaml_paths if p.stem == "MaoDan"), None)
    if maodan is None:
        pytest.skip("MaoDan.yaml not found")

    config = load_subject_config(maodan)

    assert config.subject_id == "MaoDan"
    assert config.description == "good monkey"
    assert config.species == "Macaca mulatta"
    assert config.sex == "M"
    assert config.age == "P4Y"
    assert config.weight == "12.8kg"


def test_load_jianjian_yaml_field_values():
    """Verify JianJian.yaml specific field values."""
    yaml_paths = _monkey_yaml_paths()
    jianjian = next((p for p in yaml_paths if p.stem == "JianJian"), None)
    if jianjian is None:
        pytest.skip("JianJian.yaml not found")

    config = load_subject_config(jianjian)

    assert config.subject_id == "JianJian"
    assert config.description == "good monkey"
    assert config.species == "Macaca mulatta"
    assert config.sex == "M"
    assert config.age == "P4Y"
    assert config.weight == "6.4kg"
