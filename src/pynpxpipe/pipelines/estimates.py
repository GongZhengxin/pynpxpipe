"""Stage-duration estimates from past runs' logs (ui_redesign.md §8.4).

Each finished stage logs ``stage_complete`` with ``elapsed_s`` (core/logging.py).
Dividing by the recording seconds that run processed gives a rate; the median
rate over past sessions times the new recording's length is the estimate. Per-probe
stages yield one sample per probe and scale with the probe count (sort is serial).
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from pynpxpipe.pipelines.constants import PER_PROBE_STAGES


def meta_duration_s(ap_meta: Path) -> float | None:
    """Recording length from SpikeGLX ``fileTimeSecs``, or None."""
    from pynpxpipe.io.spikeglx import SpikeGLXDiscovery

    try:
        return float(SpikeGLXDiscovery.parse_meta(Path(ap_meta))["fileTimeSecs"])
    except (OSError, KeyError, ValueError):
        return None


def recording_duration_s(output_dir: Path) -> float | None:
    """Seconds of recording a session processed.

    Uses ``03_segments/summary.json`` (retained, else original duration), then the
    first probe's AP meta listed in ``session.json``.

    Args:
        output_dir: Session output root.

    Returns:
        Duration in seconds, or None when unknown.
    """
    output_dir = Path(output_dir)
    try:
        info = json.loads((output_dir / "03_segments" / "summary.json").read_text(encoding="utf-8"))
        for key in ("retained_duration_s", "original_duration_s"):
            if info.get(key):
                return float(info[key])
    except (OSError, ValueError):
        pass
    try:
        data = json.loads((output_dir / "session.json").read_text(encoding="utf-8"))
        probes = data.get("probes") or []
        return meta_duration_s(Path(probes[0]["ap_meta"])) if probes else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _stage_events(output_dir: Path) -> list[dict]:
    events = []
    for log in sorted((output_dir / "logs").glob("*.log")):
        try:
            lines = log.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict) and record.get("event") == "stage_complete":
                events.append(record)
    return events


def collect_stage_rates(output_dirs: Iterable[Path]) -> dict[str, list[float]]:
    """Seconds of work per recording second, per stage, from past sessions.

    Per-probe stages contribute one sample per probe-level event; other stages one
    per stage-level event. Sessions without a known duration are skipped.

    Args:
        output_dirs: Past session output roots (e.g. the recent-sessions list).

    Returns:
        ``{stage: [rate, ...]}``.
    """
    rates: dict[str, list[float]] = defaultdict(list)
    for out in output_dirs:
        out = Path(out)
        if not out.is_dir():
            continue
        duration = recording_duration_s(out)
        if not duration:
            continue
        for event in _stage_events(out):
            stage, elapsed = event.get("stage"), event.get("elapsed_s")
            if not stage or not isinstance(elapsed, int | float):
                continue
            per_probe_event = event.get("probe_id") is not None
            if per_probe_event == (stage in PER_PROBE_STAGES):
                rates[stage].append(float(elapsed) / duration)
    return dict(rates)


def estimate_stage_seconds(
    rates: dict[str, list[float]],
    stage: str,
    *,
    duration_s: float,
    n_probes: int,
    min_samples: int,
) -> float | None:
    """Median-rate estimate for one stage, or None with too few samples.

    Args:
        rates: Output of :func:`collect_stage_rates`.
        stage: Stage name.
        duration_s: Recording seconds the new run will process.
        n_probes: Probe count (per-probe stages scale with it).
        min_samples: Minimum samples (ui.eta_min_samples).
    """
    samples = rates.get(stage, [])
    if len(samples) < min_samples:
        return None
    scale = n_probes if stage in PER_PROBE_STAGES else 1
    return statistics.median(samples) * duration_s * scale


def format_duration(seconds: float) -> str:
    """``<1 min`` / ``35 min`` / ``1 h 20 min`` / ``2 h``."""
    minutes = round(seconds / 60)
    if minutes < 1:
        return "<1 min"
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"
