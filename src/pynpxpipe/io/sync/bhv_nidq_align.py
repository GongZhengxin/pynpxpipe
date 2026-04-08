"""BHV2-to-NIDQ behavioral event alignment.

Decodes trial onset times from NIDQ digital event codes, matches them 1:1
with BHV2 trials, and computes stimulus onset times in NIDQ clock by adding
per-trial BHV2 relative offsets to the aligned trial onset times.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from pynpxpipe.core.errors import SyncError
from pynpxpipe.io.bhv import BHV2Parser

logger = logging.getLogger(__name__)


@dataclass
class TrialAlignment:
    """Result of BHV2-to-NIDQ behavioral event alignment.

    Attributes:
        trial_events_df: Per-trial aligned event table in NIDQ clock.
            Columns: trial_id (int), onset_nidq_s (float),
            stim_onset_nidq_s (float), condition_id (int),
            trial_valid (float, NaN placeholder for postprocess stage).
        dataset_name: Value of DatasetName field from BHV2 MLConfig.
        bhv_metadata: Full session metadata dict from BHV2Parser.get_session_metadata().
        detected_trial_start_bit: The NIDQ digital bit used to identify trial
            onsets (either as given or auto-detected).
    """

    trial_events_df: pd.DataFrame
    dataset_name: str
    bhv_metadata: dict
    detected_trial_start_bit: int


def align_bhv2_to_nidq(
    bhv_parser: BHV2Parser,
    nidq_event_times: np.ndarray,
    nidq_event_codes: np.ndarray,
    stim_onset_code: int,
    trial_start_bit: int | None = None,
    max_time_error_ms: float = 17.0,
    trial_count_tolerance: int = 2,
) -> TrialAlignment:
    """Align BHV2 behavioral events to the NIDQ clock.

    Decodes trial onset times from NIDQ digital event codes, matches them
    1:1 with BHV2 trials, and computes stimulus onset times in NIDQ clock
    by adding per-trial BHV2 relative offsets to the aligned trial onset times.

    Auto-detection of trial_start_bit: if trial_start_bit is None, iterates
    bits 0-7 to find the NIDQ bit whose event count best matches n_bhv_trials.

    Args:
        bhv_parser: Initialized BHV2Parser pointing to the .bhv2 file.
        nidq_event_times: 1D float64 array of event times in NIDQ seconds.
            Must have the same length as nidq_event_codes.
        nidq_event_codes: 1D int array of decoded integer event codes from
            the NIDQ digital channel. Same length as nidq_event_times.
        stim_onset_code: Integer event code value that marks stimulus onset
            in the BHV2 event list. Read from config.sync.stim_onset_code.
            Must be in range 0-255. Never hardcode.
        trial_start_bit: NIDQ digital bit position (0-7) for trial start signal.
            If None, auto-detection is performed.
        max_time_error_ms: Maximum allowed alignment error in milliseconds.
            Read from config.sync.max_time_error_ms. Default 17.0.
        trial_count_tolerance: Maximum allowed difference between BHV2 trial
            count and NIDQ decoded trial count before raising SyncError.
            Read from config.sync.trial_count_tolerance. Default 2.

    Returns:
        TrialAlignment with per-trial DataFrame, dataset_name, bhv_metadata,
        and the trial_start_bit actually used.

    Raises:
        SyncError: If event array lengths mismatch, stim_onset_code out of
            range, trial count mismatch exceeds tolerance, auto-detection
            fails, or alignment error exceeds max_time_error_ms.
    """
    # Step 1: Input validation
    n_times = len(nidq_event_times)
    n_codes = len(nidq_event_codes)
    if n_times != n_codes:
        raise SyncError(f"NIDQ event_times and event_codes length mismatch: {n_times} vs {n_codes}")
    if not (0 <= stim_onset_code <= 255):
        raise SyncError(f"stim_onset_code {stim_onset_code} out of range 0-255")

    # Step 2: Parse BHV2
    trials = bhv_parser.parse()
    n_bhv = len(trials)
    bhv_metadata = bhv_parser.get_session_metadata()
    dataset_name = bhv_metadata.get("DatasetName", "")

    # Step 3: Determine trial_start_bit
    if trial_start_bit is not None:
        detected_trial_start_bit = trial_start_bit
    else:
        detected_trial_start_bit = _auto_detect_trial_start_bit(
            nidq_event_times,
            nidq_event_codes,
            n_bhv,
            trial_count_tolerance=trial_count_tolerance,
        )

    # Step 4: Extract trial onset times from NIDQ
    trial_code_val = 2**detected_trial_start_bit
    onset_mask = nidq_event_codes == trial_code_val
    nidq_trial_onset_times = nidq_event_times[onset_mask]
    n_nidq = len(nidq_trial_onset_times)

    # Step 5: Trial count validation and truncation
    diff = abs(n_bhv - n_nidq)
    if diff > trial_count_tolerance:
        raise SyncError(
            f"Trial count mismatch: BHV2={n_bhv}, NIDQ={n_nidq}, "
            f"tolerance={trial_count_tolerance}. "
            f"Check BHV2 file and NIDQ recording completeness."
        )
    if diff > 0:
        n_trials = min(n_bhv, n_nidq)
        discarded_bhv = [t.trial_id for t in trials[n_trials:]] if n_bhv > n_trials else []
        discarded_nidq = n_nidq - n_trials if n_nidq > n_trials else 0
        if discarded_bhv:
            logger.warning(
                "BHV2 has %d more trial(s) than NIDQ; discarding BHV2 trial(s): %s",
                len(discarded_bhv),
                discarded_bhv,
            )
        if discarded_nidq:
            logger.warning(
                "NIDQ has %d more trial(s) than BHV2; discarding last %d NIDQ onset(s)",
                discarded_nidq,
                discarded_nidq,
            )
        trials = trials[:n_trials]
        nidq_trial_onset_times = nidq_trial_onset_times[:n_trials]
    else:
        n_trials = n_bhv

    # Step 6: Extract stimulus onset times
    stim_event_pairs = bhv_parser.get_event_code_times(
        stim_onset_code,
        trials=[t.trial_id for t in trials],
    )
    # Build per-trial lookup: trial_id → first stim time (ms)
    stim_time_by_trial: dict[int, float] = {}
    for trial_id, time_ms in stim_event_pairs:
        if trial_id not in stim_time_by_trial:
            stim_time_by_trial[trial_id] = time_ms

    stim_onset_nidq_s = np.empty(n_trials, dtype=np.float64)
    for idx, trial in enumerate(trials):
        if trial.trial_id in stim_time_by_trial:
            # BHV2 stim offset relative to trial start (time 0 ms)
            offset_s = stim_time_by_trial[trial.trial_id] / 1000.0
            stim_onset_nidq_s[idx] = nidq_trial_onset_times[idx] + offset_s
        else:
            logger.warning(
                "Trial %d has no stim_onset_code=%d in BHV2; stim_onset_nidq_s set to NaN",
                trial.trial_id,
                stim_onset_code,
            )
            stim_onset_nidq_s[idx] = np.nan

    # Step 7: Alignment quality validation (inter-trial interval consistency)
    if n_trials >= 2:
        # Use stim_onset times for cross-validation if available
        valid_mask = ~np.isnan(stim_onset_nidq_s)
        if valid_mask.sum() >= 2:
            nidq_onsets_valid = nidq_trial_onset_times[valid_mask]
            nidq_iti = np.diff(nidq_onsets_valid)
            # Compare BHV2 stim-onset inter-trial intervals with NIDQ
            stim_valid = stim_onset_nidq_s[valid_mask]
            stim_iti = np.diff(stim_valid)
            if len(nidq_iti) > 0 and len(stim_iti) > 0:
                mean_err_s = (
                    np.abs(nidq_iti - stim_iti).mean() if len(nidq_iti) == len(stim_iti) else 0.0
                )
                if mean_err_s > max_time_error_ms / 1000.0:
                    raise SyncError(
                        f"BHV2-NIDQ alignment error exceeds {max_time_error_ms} ms. "
                        "Check event code definitions."
                    )

    # Step 8: Build DataFrame
    df = pd.DataFrame(
        {
            "trial_id": [t.trial_id for t in trials],
            "onset_nidq_s": nidq_trial_onset_times,
            "stim_onset_nidq_s": stim_onset_nidq_s,
            "condition_id": [t.condition_id for t in trials],
            "trial_valid": np.full(n_trials, np.nan),
        }
    )

    return TrialAlignment(
        trial_events_df=df,
        dataset_name=dataset_name,
        bhv_metadata=bhv_metadata,
        detected_trial_start_bit=detected_trial_start_bit,
    )


def _auto_detect_trial_start_bit(
    nidq_event_times: np.ndarray,
    nidq_event_codes: np.ndarray,
    n_bhv_trials: int,
    trial_count_tolerance: int = 2,
) -> int:
    """Find the NIDQ digital bit whose onset count best matches BHV2 trial count.

    Iterates bits 0-7 and selects the bit whose decoded event count is
    closest to n_bhv_trials.

    Args:
        nidq_event_times: 1D float64 array of NIDQ event times (seconds).
        nidq_event_codes: 1D int array of decoded event codes.
        n_bhv_trials: Number of trials from BHV2 file.
        trial_count_tolerance: Maximum allowed mismatch before raising SyncError.

    Returns:
        Best-matching bit index (0-7).

    Raises:
        SyncError: If no bit produces a count within trial_count_tolerance
            of n_bhv_trials.
    """
    best_bit = -1
    best_diff = n_bhv_trials + 1  # larger than any possible diff

    for bit in range(8):
        code_val = 2**bit
        count = int(np.sum(nidq_event_codes == code_val))
        diff = abs(count - n_bhv_trials)
        if diff < best_diff:
            best_diff = diff
            best_bit = bit

    if best_diff > trial_count_tolerance:
        raise SyncError(
            f"Cannot auto-detect trial_start_bit: no NIDQ bit matches "
            f"BHV2 trial count {n_bhv_trials}. "
            "Check config.sync.trial_start_bit."
        )

    logger.info(
        "Auto-detected trial_start_bit=%d (NIDQ count=%d, BHV2 count=%d)",
        best_bit,
        int(np.sum(nidq_event_codes == 2**best_bit)),
        n_bhv_trials,
    )
    return best_bit
