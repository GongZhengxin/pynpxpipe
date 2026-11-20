"""Complete trial coverage independent of successful stimulus presentations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from pynpxpipe.core.errors import SyncError

if TYPE_CHECKING:
    from pynpxpipe.io.bhv import TrialData

logger = logging.getLogger(__name__)


def _decoded_code(raw_code: int, event_bits: list[int]) -> int:
    return sum(((raw_code >> bit) & 1) << index for index, bit in enumerate(event_bits))


def align_trial_intervals(
    trials: list[TrialData],
    event_times: np.ndarray,
    event_codes: np.ndarray,
    trial_start_bit: int,
    raw_start_code: int | None,
    *,
    event_bits: list[int] | None = None,
) -> pd.DataFrame:
    """Anchor BHV trial zero to its emitted marker, preserving failed trials.

    Args:
        trials: All parsed BHV trials in recording order.
        event_times: NIDQ transition times in seconds.
        event_codes: Packed NIDQ codes, in the same order as event_times.
        trial_start_bit: Decoded bit of the independent trial TTL used for
            stimulus window matching. It need not be a BHV event marker.
        raw_start_code: BHV event code, or None to infer the common first event.
        event_bits: Physical NIDQ bits, in decoder packing order. Maps the BHV
            marker to its own NIDQ transitions. If omitted, an explicit BHV code
            is paired to trial_start_bit for compatibility with existing callers.

    Returns:
        Full trial intervals with trial zero and both anchor codes/timestamps.

    Raises:
        SyncError: If counts, marker identity or trial boundaries are ambiguous.
    """
    event_times = np.asarray(event_times, dtype=float)
    event_codes = np.asarray(event_codes)
    if event_times.ndim != 1 or event_codes.shape != event_times.shape:
        raise SyncError("NIDQ event times and codes must be matching one-dimensional arrays")
    if not np.isfinite(event_times).all() or np.any(np.diff(event_times) <= 0):
        raise SyncError("NIDQ event times must be finite and strictly increasing")
    if not trials:
        raise SyncError("Task selection requires BHV2 trials")
    trial_ttls = event_times[event_codes == (1 << trial_start_bit)]
    if len(trial_ttls) != len(trials):
        raise SyncError("Task selection requires an unambiguous match for every BHV2 trial")

    if raw_start_code is None:
        first_codes = {trial.events[0][1] for trial in trials if trial.events}
        if event_bits is None or len(first_codes) != 1 or any(not t.events for t in trials):
            raise SyncError(
                "Cannot infer a common first BHV event; set task_windows.trial_start_code "
                "to a recorded BHV marker and provide the NIDQ event_bits mapping"
            )
        raw_start_code = first_codes.pop()

    bounds = []
    for trial in trials:
        anchors = [time for time, code in trial.events if code == raw_start_code]
        if len(anchors) != 1:
            recorded = sorted({code for _, code in trial.events})
            raise SyncError(
                f"Trial {trial.trial_id}: expected one BHV start marker {raw_start_code}, "
                f"found {len(anchors)} (recorded codes={recorded}); leave "
                "task_windows.trial_start_code unset to infer the common first BHV event, "
                "or set it to a recorded BHV code"
            )
        end = trial.end_ms
        if end is None:
            end = max((t for t, _ in trial.events), default=np.nan)
        if (
            not np.isfinite([trial.start_ms, anchors[0], end]).all()
            or end <= trial.start_ms
            or not trial.start_ms <= anchors[0] <= end
        ):
            raise SyncError(
                f"Trial {trial.trial_id}: invalid full-trial timing "
                f"(start_ms={trial.start_ms}, anchor_ms={anchors[0]}, end_ms={end})"
            )
        bounds.append((anchors[0], end))

    if event_bits is None:
        nidq_code = 1 << trial_start_bit
    else:
        nidq_code = _decoded_code(raw_start_code, event_bits)
        if nidq_code == 0:
            raise SyncError(
                f"BHV marker {raw_start_code} is not recorded in sync.event_bits={event_bits}"
            )
        collisions = {
            code
            for trial in trials
            for _, code in trial.events
            if code != raw_start_code and _decoded_code(code, event_bits) == nidq_code
        }
        if collisions:
            raise SyncError(
                f"BHV marker {raw_start_code} has a decoded NIDQ code collision with "
                f"{sorted(collisions)}; check sync.event_bits and task_windows.trial_start_code"
            )
    starts = event_times[event_codes == nidq_code]
    if len(starts) != len(trials):
        raise SyncError(
            f"BHV marker {raw_start_code} maps to decoded NIDQ code {nidq_code}, "
            f"but found {len(starts)} NIDQ anchors for {len(trials)} BHV2 trials; "
            "check sync.event_bits, task_windows.trial_start_code and recording completeness"
        )

    rows = []
    for trial, (anchor, end), ttl, marker in zip(trials, bounds, trial_ttls, starts, strict=True):
        zero = float(marker - anchor / 1000)
        start_time = zero + trial.start_ms / 1000
        stop_time = zero + end / 1000
        if not start_time <= ttl <= stop_time:
            raise SyncError(
                f"Trial {trial.trial_id}: NIDQ trial TTL {ttl:.6f} s is outside "
                f"the aligned interval [{start_time:.6f}, {stop_time:.6f}] s; "
                "check trial marker mapping and BHV2 pairing"
            )
        rows.append(
            {
                "trial_id": trial.trial_id,
                "condition_id": trial.condition_id,
                "start_time": start_time,
                "stop_time": stop_time,
                "bhv_zero_nidq_s": zero,
                "bhv_anchor_code": raw_start_code,
                "nidq_anchor_code": nidq_code,
                "bhv_anchor_ms": anchor,
                "nidq_anchor_s": float(marker),
                "trial_error": trial.trial_error if trial.trial_error is not None else -1,
            }
        )
    df = pd.DataFrame(rows)
    if len(df) > 1 and np.any(df.start_time.to_numpy()[1:] < df.stop_time.to_numpy()[:-1]):
        raise SyncError("Aligned trial intervals overlap; check trial markers and BHV2 pairing")
    logger.info(
        "Full-trial anchors: BHV code=%d -> decoded NIDQ code=%d (%d trials)",
        raw_start_code,
        nidq_code,
        len(trials),
    )
    return df
