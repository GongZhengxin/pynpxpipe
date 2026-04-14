"""Tests for load_* public functions and merge_with_overrides in pynpxpipe.core.config.

Covers all 13 behaviors specified in docs/specs/config.md §11.
"""

from __future__ import annotations

import pytest

from pynpxpipe.core.config import (
    PipelineConfig,
    SortingConfig,
    SubjectConfig,
    load_pipeline_config,
    load_sorting_config,
    load_subject_config,
    merge_with_overrides,
    save_subject_config,
)
from pynpxpipe.core.errors import ConfigError

# ===========================================================================
# 1. load_pipeline_config(None) → returns full-default PipelineConfig
# ===========================================================================


def test_load_pipeline_config_none_returns_defaults():
    """Behavior 1: load_pipeline_config(None) returns full-default PipelineConfig, no exception."""
    config = load_pipeline_config(None)
    assert isinstance(config, PipelineConfig)
    # Check key defaults
    assert config.resources.n_jobs == "auto"
    assert config.resources.chunk_duration == "auto"
    assert config.resources.max_memory == "auto"
    assert config.parallel.enabled is False
    assert config.parallel.max_workers == "auto"
    assert config.preprocess.bandpass.freq_min == 300.0
    assert config.preprocess.bandpass.freq_max == 6000.0
    assert config.curation.isi_violation_ratio_max == 2.0
    assert config.sync.imec_sync_bit == 6
    assert config.sync.stim_onset_code == 64


def test_load_pipeline_config_nonexistent_path_returns_defaults(tmp_path):
    """Behavior 1 variant: non-existent path also uses defaults (no exception)."""
    config = load_pipeline_config(tmp_path / "does_not_exist.yaml")
    assert isinstance(config, PipelineConfig)
    assert config.resources.n_jobs == "auto"


# ===========================================================================
# 2. load_pipeline_config(path) file exists → correct fields loaded
# ===========================================================================


def test_load_pipeline_config_from_file_reads_fields(tmp_path):
    """Behavior 2: file exists → correct fields loaded."""
    yaml_content = (
        "resources:\n"
        "  n_jobs: 4\n"
        "  chunk_duration: '2s'\n"
        "  max_memory: '16G'\n"
        "parallel:\n"
        "  enabled: true\n"
        "  max_workers: 2\n"
        "preprocess:\n"
        "  bandpass:\n"
        "    freq_min: 200.0\n"
        "    freq_max: 5000.0\n"
        "curation:\n"
        "  snr_min: 1.0\n"
        "sync:\n"
        "  imec_sync_bit: 1\n"
        "  stim_onset_code: 32\n"
    )
    config_file = tmp_path / "pipeline.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    config = load_pipeline_config(config_file)

    assert config.resources.n_jobs == 4
    assert config.resources.chunk_duration == "2s"
    assert config.resources.max_memory == "16G"
    assert config.parallel.enabled is True
    assert config.parallel.max_workers == 2
    assert config.preprocess.bandpass.freq_min == 200.0
    assert config.preprocess.bandpass.freq_max == 5000.0
    assert config.curation.snr_min == 1.0
    assert config.sync.imec_sync_bit == 1
    assert config.sync.stim_onset_code == 32


# ===========================================================================
# 3. load_pipeline_config(path) file exists but field missing → uses default
# ===========================================================================


def test_load_pipeline_config_missing_field_uses_default(tmp_path):
    """Behavior 3: file exists but field missing → default is used."""
    yaml_content = "resources:\n  n_jobs: 4\n"
    config_file = tmp_path / "pipeline.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    config = load_pipeline_config(config_file)

    # Only n_jobs was specified, others get defaults
    assert config.resources.n_jobs == 4
    assert config.resources.chunk_duration == "auto"  # default
    assert config.resources.max_memory == "auto"  # default
    assert config.parallel.enabled is False  # default
    assert config.preprocess.bandpass.freq_min == 300.0  # default


# ===========================================================================
# 4. "auto" string preserved (not replaced)
# ===========================================================================


def test_auto_string_preserved_in_fields(tmp_path):
    """Behavior 4: "auto" string preserved in n_jobs, chunk_duration, batch_size."""
    yaml_content = (
        "resources:\n"
        "  n_jobs: auto\n"
        "  chunk_duration: auto\n"
        "  max_memory: auto\n"
        "parallel:\n"
        "  max_workers: auto\n"
    )
    config_file = tmp_path / "pipeline.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    config = load_pipeline_config(config_file)

    assert config.resources.n_jobs == "auto"
    assert config.resources.chunk_duration == "auto"
    assert config.resources.max_memory == "auto"
    assert config.parallel.max_workers == "auto"


def test_auto_string_preserved_in_sorting_batch_size(tmp_path):
    """Behavior 4: "auto" preserved in sorter.params.batch_size."""
    yaml_content = "sorter:\n  params:\n    batch_size: auto\n"
    config_file = tmp_path / "sorting.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    config = load_sorting_config(config_file)

    assert config.sorter.params.batch_size == "auto"


# ===========================================================================
# 5. n_jobs: 0 → raises ConfigError
# ===========================================================================


def test_n_jobs_zero_raises_config_error(tmp_path):
    """Behavior 5: n_jobs: 0 → raises ConfigError(field='resources.n_jobs', ...)."""
    yaml_content = "resources:\n  n_jobs: 0\n"
    config_file = tmp_path / "pipeline.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_pipeline_config(config_file)

    assert exc_info.value.field == "resources.n_jobs"
    assert exc_info.value.value == 0


# ===========================================================================
# 6. freq_min: 8000, freq_max: 6000 → raises ConfigError(field="preprocess.bandpass.freq_max")
# ===========================================================================


def test_freq_max_less_than_freq_min_raises_config_error(tmp_path):
    """Behavior 6: freq_min=8000 > freq_max=6000 → ConfigError on freq_max."""
    yaml_content = "preprocess:\n  bandpass:\n    freq_min: 8000\n    freq_max: 6000\n"
    config_file = tmp_path / "pipeline.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_pipeline_config(config_file)

    assert exc_info.value.field == "preprocess.bandpass.freq_max"


# ===========================================================================
# 7. YAML with unknown key → no raise
# ===========================================================================


def test_unknown_key_in_yaml_does_not_raise(tmp_path):
    """Behavior 7: YAML with unknown key → silently ignored, no exception."""
    yaml_content = (
        "resources:\n"
        "  n_jobs: 4\n"
        "  unknown_future_key: some_value\n"
        "totally_unknown_section:\n"
        "  key: value\n"
    )
    config_file = tmp_path / "pipeline.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    # Should not raise
    config = load_pipeline_config(config_file)
    assert config.resources.n_jobs == 4


# ===========================================================================
# 8. YAML "import:" key → correctly maps to SortingConfig.import_cfg
# ===========================================================================


def test_yaml_import_key_maps_to_import_cfg(tmp_path):
    """Behavior 8: YAML 'import:' key correctly maps to SortingConfig.import_cfg."""
    yaml_content = "mode: import\nimport:\n  format: phy\n"
    config_file = tmp_path / "sorting.yaml"
    config_file.write_text(yaml_content, encoding="utf-8")

    config = load_sorting_config(config_file)

    assert config.mode == "import"
    assert config.import_cfg.format == "phy"


# ===========================================================================
# 9. merge_with_overrides → new object with updated field
# ===========================================================================


def test_merge_with_overrides_updates_field():
    """Behavior 9: merge updates specified field, others unchanged."""
    config = load_pipeline_config(None)
    new_config = merge_with_overrides(config, {"resources": {"n_jobs": 8}})

    assert new_config.resources.n_jobs == 8
    # Other fields unchanged
    assert new_config.resources.chunk_duration == "auto"
    assert new_config.resources.max_memory == "auto"
    assert new_config.parallel.enabled is False
    assert new_config.preprocess.bandpass.freq_min == 300.0


# ===========================================================================
# 10. merge_with_overrides with invalid value → raises ConfigError
# ===========================================================================


def test_merge_with_overrides_invalid_value_raises():
    """Behavior 10: merge with n_jobs=0 → raises ConfigError."""
    config = load_pipeline_config(None)

    with pytest.raises(ConfigError) as exc_info:
        merge_with_overrides(config, {"resources": {"n_jobs": 0}})

    assert exc_info.value.field == "resources.n_jobs"


# ===========================================================================
# 11. load_subject_config missing subject_id → raises ConfigError
# ===========================================================================


def test_load_subject_config_missing_subject_id_raises(tmp_path):
    """Behavior 11: subject YAML missing subject_id → raises ConfigError."""
    yaml_content = (
        "Subject:\n"
        "  description: 'good monkey'\n"
        "  species: 'Macaca mulatta'\n"
        "  sex: M\n"
        "  age: P4Y\n"
    )
    subject_file = tmp_path / "monkey.yaml"
    subject_file.write_text(yaml_content, encoding="utf-8")

    with pytest.raises(ConfigError) as exc_info:
        load_subject_config(subject_file)

    assert "subject_id" in exc_info.value.field


# ===========================================================================
# 12. load_subject_config nonexistent path → raises FileNotFoundError
# ===========================================================================


def test_load_subject_config_nonexistent_raises(tmp_path):
    """Behavior 12: non-existent file → raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_subject_config(tmp_path / "nonexistent.yaml")


# ===========================================================================
# 13. merge_with_overrides returns NEW object, does not mutate original
# ===========================================================================


def test_merge_with_overrides_returns_new_object():
    """Behavior 13: merge returns new object, original is unchanged."""
    config = load_pipeline_config(None)
    new_config = merge_with_overrides(config, {"resources": {"n_jobs": 8}})

    assert new_config is not config
    assert config.resources.n_jobs == "auto"  # original unchanged
    assert new_config.resources.n_jobs == 8


# ===========================================================================
# Additional: load_subject_config happy path
# ===========================================================================


def test_load_subject_config_valid_file(tmp_path):
    """load_subject_config with valid YAML returns correct SubjectConfig."""
    yaml_content = (
        "Subject:\n"
        "  subject_id: MaoDan\n"
        "  description: 'good monkey'\n"
        "  species: 'Macaca mulatta'\n"
        "  sex: M\n"
        "  age: P4Y\n"
        "  weight: '12.8kg'\n"
    )
    subject_file = tmp_path / "MaoDan.yaml"
    subject_file.write_text(yaml_content, encoding="utf-8")

    config = load_subject_config(subject_file)

    assert isinstance(config, SubjectConfig)
    assert config.subject_id == "MaoDan"
    assert config.species == "Macaca mulatta"
    assert config.sex == "M"
    assert config.age == "P4Y"
    assert config.weight == "12.8kg"


def test_load_subject_config_without_top_level_key(tmp_path):
    """load_subject_config works without top-level 'Subject:' key."""
    yaml_content = (
        "subject_id: JianJian\n"
        "description: 'another monkey'\n"
        "species: 'Macaca mulatta'\n"
        "sex: F\n"
        "age: P3Y\n"
    )
    subject_file = tmp_path / "JianJian.yaml"
    subject_file.write_text(yaml_content, encoding="utf-8")

    config = load_subject_config(subject_file)

    assert config.subject_id == "JianJian"
    assert config.weight == ""  # optional, defaults to ""


def test_load_sorting_config_none_returns_defaults():
    """load_sorting_config(None) returns full-default SortingConfig."""
    config = load_sorting_config(None)
    assert isinstance(config, SortingConfig)
    assert config.mode == "local"
    assert config.sorter.name == "kilosort4"
    assert config.sorter.params.batch_size == "auto"
    assert config.import_cfg.format == "kilosort4"


# ===========================================================================
# save_subject_config — round-trip with load_subject_config
# ===========================================================================


def test_save_subject_config_writes_top_level_block(tmp_path):
    """save_subject_config writes a file with the top-level Subject: key."""
    cfg = SubjectConfig(
        subject_id="Koko",
        description="calm monkey",
        species="Macaca mulatta",
        sex="F",
        age="P6Y",
        weight="9.5kg",
    )
    target = tmp_path / "Koko.yaml"
    save_subject_config(cfg, target)

    text = target.read_text(encoding="utf-8")
    assert text.startswith("Subject:")
    assert "subject_id: Koko" in text
    assert "species: Macaca mulatta" in text


def test_save_subject_config_round_trips_via_load(tmp_path):
    """Saved file loads back into an equivalent SubjectConfig."""
    cfg = SubjectConfig(
        subject_id="Pippo",
        description="curious monkey",
        species="Macaca fascicularis",
        sex="M",
        age="P2Y",
        weight="7kg",
    )
    target = tmp_path / "Pippo.yaml"
    save_subject_config(cfg, target)

    loaded = load_subject_config(target)
    assert loaded == cfg


def test_save_subject_config_creates_parent_directories(tmp_path):
    """Missing parent directories are created automatically."""
    cfg = SubjectConfig(
        subject_id="Nested",
        description="",
        species="Macaca mulatta",
        sex="U",
        age="P1Y",
        weight="5kg",
    )
    nested_target = tmp_path / "deep" / "subfolder" / "Nested.yaml"
    save_subject_config(cfg, nested_target)
    assert nested_target.exists()


def test_save_subject_config_overwrites_existing_file(tmp_path):
    """save_subject_config replaces any existing file content (UI gates this)."""
    target = tmp_path / "Mono.yaml"
    target.write_text("old content\n", encoding="utf-8")

    cfg = SubjectConfig(
        subject_id="Mono",
        description="fresh",
        species="Macaca mulatta",
        sex="M",
        age="P3Y",
        weight="8kg",
    )
    save_subject_config(cfg, target)
    assert "old content" not in target.read_text(encoding="utf-8")
    loaded = load_subject_config(target)
    assert loaded.description == "fresh"
