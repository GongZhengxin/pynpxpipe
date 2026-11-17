"""Complete trial coverage independent of successful stimulus presentations."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from pynpxpipe.core.errors import SyncError

if TYPE_CHECKING:
    from pynpxpipe.io.bhv import TrialData


def align_trial_intervals(
    trials: list[TrialData],
    event_times: np.ndarray,
    event_codes: np.ndarray,
    trial_start_bit: int,
    raw_start_code: int,
) -> pd.DataFrame:
    """Anchor BHV trial zero to its emitted marker, preserving failed trials.

    Raises:
        SyncError: If counts, marker identity or trial boundaries are ambiguous.
    """
    starts = event_times[event_codes == (1 << trial_start_bit)]
    if len(starts) != len(trials):
        raise SyncError("Task selection requires an unambiguous match for every BHV2 trial")
    rows = []
    for trial, ttl in zip(trials, starts, strict=True):
        anchors = [time for time, code in trial.events if code == raw_start_code]
        end = trial.end_ms
        if end is None:
            end = max((t for t, _ in trial.events), default=np.nan)
        if (
            len(anchors) != 1
            or not np.isfinite([trial.start_ms, end]).all()
            or end <= trial.start_ms
        ):
            raise SyncError(
                f"Trial {trial.trial_id}: missing/ambiguous full-trial timing or start marker {raw_start_code}; set task_windows.trial_start_code to the recorded BHV code"
            )
        zero = float(ttl - anchors[0] / 1000)
        rows.append(
            {
                "trial_id": trial.trial_id,
                "condition_id": trial.condition_id,
                "start_time": zero + trial.start_ms / 1000,
                "stop_time": zero + end / 1000,
                "bhv_zero_nidq_s": zero,
                "trial_error": trial.trial_error if trial.trial_error is not None else -1,
            }
        )
    df = pd.DataFrame(rows)
    if len(df) > 1 and np.any(df.start_time.to_numpy()[1:] < df.stop_time.to_numpy()[:-1]):
        raise SyncError("Aligned trial intervals overlap; check trial markers and BHV2 pairing")
    return df
