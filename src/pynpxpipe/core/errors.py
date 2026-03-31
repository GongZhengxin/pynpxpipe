class PynpxpipeError(Exception):
    """Base class for all pynpxpipe custom exceptions."""


class ConfigError(PynpxpipeError):
    """Raised when a configuration field value is invalid or structurally wrong.

    Attributes:
        field: Dot-separated path to the offending field, e.g. "resources.n_jobs"
        value: The invalid value.
        reason: Human-readable explanation of why the value is invalid.
    """

    def __init__(self, field: str, value: object, reason: str) -> None:
        self.field = field
        self.value = value
        self.reason = reason
        super().__init__(f"ConfigError [{field}={value!r}]: {reason}")
