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
