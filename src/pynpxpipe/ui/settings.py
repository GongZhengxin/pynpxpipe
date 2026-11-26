"""ui/settings.py — UI-only settings from ``config/ui.yaml`` (ui_redesign.md §8.9).

These knobs only affect the web UI (polling, heartbeats, list sizes), so they
live outside PipelineConfig. A missing file means all defaults.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

import yaml

from pynpxpipe.core.errors import ConfigError


@dataclass(frozen=True)
class UISettings:
    """Web UI timing and list settings.

    Attributes:
        heartbeat_s: Interval at which a running job refreshes run_state.json.
        heartbeat_timeout_s: Heartbeat age after which a run counts as interrupted.
        poll_s: How often browser sessions re-read run state and machine status.
        recent_sessions_max: Entries kept in the recent-sessions list.
        eta_min_samples: Past sessions needed before a stage duration estimate is shown.
        min_batch_size: Lower bound when suggesting a smaller Kilosort batch_size.
    """

    heartbeat_s: float = 5.0
    heartbeat_timeout_s: float = 60.0
    poll_s: float = 2.0
    recent_sessions_max: int = 20
    eta_min_samples: int = 3
    min_batch_size: int = 10000


def default_ui_settings_path() -> Path:
    """``<project root>/config/ui.yaml``."""
    return Path(__file__).resolve().parents[3] / "config" / "ui.yaml"


def load_ui_settings(path: Path | None = None) -> UISettings:
    """Load UI settings, filling defaults for missing keys.

    Args:
        path: YAML file with a top-level ``ui:`` mapping; defaults to config/ui.yaml.

    Returns:
        Validated UISettings.

    Raises:
        ConfigError: If a value is not a positive number.
    """
    path = Path(path) if path is not None else default_ui_settings_path()
    raw: dict = {}
    if path.exists():
        raw = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("ui") or {}
    values = {}
    for fld in dataclasses.fields(UISettings):
        if fld.name not in raw:
            continue
        value = raw[fld.name]
        kind = int if isinstance(fld.default, int) else float
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise ConfigError(f"ui.{fld.name}", value, "must be a positive number")
        values[fld.name] = kind(value)
    return UISettings(**values)
