import pytest

from pynpxpipe.core.errors import ConfigError, PynpxpipeError


def test_pynpxpipe_error_is_exception_subclass():
    assert issubclass(PynpxpipeError, Exception)


def test_config_error_is_pynpxpipe_error_subclass():
    assert issubclass(ConfigError, PynpxpipeError)


def test_config_error_stores_field():
    error = ConfigError("resources.n_jobs", 0, "must be >= 1")
    assert error.field == "resources.n_jobs"


def test_config_error_stores_value():
    error = ConfigError("resources.n_jobs", 0, "must be >= 1")
    assert error.value == 0


def test_config_error_stores_reason():
    error = ConfigError("resources.n_jobs", 0, "must be >= 1")
    assert error.reason == "must be >= 1"


def test_config_error_str_repr():
    error = ConfigError("resources.n_jobs", 0, "must be >= 1")
    assert str(error) == "ConfigError [resources.n_jobs=0]: must be >= 1"


def test_config_error_caught_as_pynpxpipe_error():
    with pytest.raises(PynpxpipeError):
        raise ConfigError("resources.n_jobs", 0, "must be >= 1")


def test_config_error_caught_as_exception():
    with pytest.raises(Exception):  # noqa: B017
        raise ConfigError("resources.n_jobs", 0, "must be >= 1")


def test_config_error_str_includes_field_value_reason():
    error = ConfigError("sync.stim_onset_code", 300, "must be 0-255")
    result = str(error)
    assert "sync.stim_onset_code" in result
    assert "300" in result
    assert "must be 0-255" in result


# --- CheckpointError tests ---

from pathlib import Path  # noqa: E402

from pynpxpipe.core.errors import CheckpointError  # noqa: E402


def test_checkpoint_error_is_pynpxpipe_error_subclass():
    assert issubclass(CheckpointError, PynpxpipeError)


def test_checkpoint_error_stores_stage():
    path = Path("/tmp/checkpoints/sort_imec0.json")
    error = CheckpointError("sort", path, "file not found")
    assert error.stage == "sort"


def test_checkpoint_error_stores_path():
    path = Path("/tmp/checkpoints/sort_imec0.json")
    error = CheckpointError("sort", path, "file not found")
    assert error.path == path


def test_checkpoint_error_stores_reason():
    path = Path("/tmp/checkpoints/sort_imec0.json")
    error = CheckpointError("sort", path, "file not found")
    assert error.reason == "file not found"


def test_checkpoint_error_str_includes_stage():
    path = Path("/tmp/checkpoints/sort_imec0.json")
    error = CheckpointError("sort", path, "JSON decode error")
    assert "sort" in str(error)


def test_checkpoint_error_str_includes_path():
    path = Path("/tmp/checkpoints/discover.json")
    error = CheckpointError("discover", path, "corrupt")
    assert str(path) in str(error)


def test_checkpoint_error_caught_as_pynpxpipe_error():
    path = Path("/tmp/checkpoints/export.json")
    with pytest.raises(PynpxpipeError):
        raise CheckpointError("export", path, "disk full")
