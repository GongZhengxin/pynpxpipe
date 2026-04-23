"""BHV2-to-NIDQ behavioral event alignment.

Decodes trial onset times from NIDQ digital event codes, matches them 1:1
with BHV2 trials, and resolves each stimulus onset in NIDQ clock by
directly matching it to the NIDQ stim-onset rising edge that falls inside
the trial window (MATLAB-style — cf. ground_truth step #10:
``onset_LOC = find(diff(bitand(DCode_NI.CodeVal,64))>0)+1``).

The older ``trial_anchor + bhv_offset`` formula accumulates per-trial drift
(empirically up to ±120ms) because BHV2's "trial zero" and the NIDQ
trial_start rising edge are not simultaneous — the gap between ML's
trial-entry timestamp and the first emitted NIDQ trial_start code varies
per trial. That drift pushed many stim onsets outside the photodiode
calibration window, causing widespread flag=3.
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
        trial_events_df: Per-stimulus aligned event table in NIDQ clock.
            When a BHV2 trial contains multiple stim_onset_code events
            (e.g. RSVP paradigms), each stimulus gets its own row.
            Columns: trial_id (int), onset_nidq_s (float),
            stim_onset_nidq_s (float), condition_id (int),
            stim_index (int, 1-based stimulus identity from
            Current_Image_Train UserVar, or 0 if unavailable),
            trial_valid (float, NaN placeholder for postprocess stage).
        dataset_name: Value of DatasetName field from BHV2 MLConfig.
        bhv_metadata: Full session metadata dict from BHV2Parser.get_session_metadata().
        detected_trial_start_bit: Decoded-domain bit index used for trial
            onsets (either as given or auto-detected).
        detected_stim_onset_bit: Decoded-domain bit index used for stim
            onsets (either as given or auto-detected).
    """

    trial_events_df: pd.DataFrame
    dataset_name: str
    bhv_metadata: dict
    detected_trial_start_bit: int
    detected_stim_onset_bit: int = -1


def align_bhv2_to_nidq(
    bhv_parser: BHV2Parser,
    nidq_event_times: np.ndarray,
    nidq_event_codes: np.ndarray,
    stim_onset_code: int,
    trial_start_bit: int | None = None,
    stim_onset_bit: int | None = None,
    max_time_error_ms: float = 17.0,
    trial_count_tolerance: int = 2,
    stim_count_tolerance: int = 0,
) -> TrialAlignment:
    """Align BHV2 behavioral events to the NIDQ clock.

    Decodes trial onset times from NIDQ digital event codes, matches them
    1:1 with BHV2 trials, and resolves each stimulus onset directly to the
    corresponding NIDQ rising edge inside its trial window (MATLAB-style,
    cf. ground_truth step #10: ``find(diff(bitand(CodeVal,64))>0)+1``).

    Auto-detection:
      * ``trial_start_bit=None`` → iterate decoded bits 0-7, pick the one
        whose event count best matches ``n_bhv_trials``.
      * ``stim_onset_bit=None`` → iterate decoded bits 0-7 (excluding
        ``trial_start_bit``), pick the first bit whose event count exactly
        matches total BHV2 stim events. If none match, fall back to the
        ``trial_anchor + bhv_offset`` formula (legacy behaviour; per-trial
        drift may be present — useful only when the NIDQ stim bit is
        missing from the recording).

    Args:
        bhv_parser: Initialized BHV2Parser pointing to the .bhv2 file.
        nidq_event_times: 1D float64 array of event times in NIDQ seconds.
            Must have the same length as nidq_event_codes.
        nidq_event_codes: 1D int array of decoded integer event codes from
            the NIDQ digital channel. Same length as nidq_event_times.
        stim_onset_code: Integer event code value that marks stimulus onset
            in the BHV2 event list (raw MonkeyLogic domain, e.g. 64). Read
            from config.sync.stim_onset_code. Must be in 0-255. Never
            hardcode.
        trial_start_bit: Decoded-domain bit position (0-7) for trial start.
            If None, auto-detection is performed.
        stim_onset_bit: Decoded-domain bit position (0-7) for stim onset.
            NOTE: this is the decoded bit, not the raw ML bit — the NIDQ
            decoder in synchronize.py packs ``event_bits`` into contiguous
            decoded bits, so raw bit 6 (stim_onset_code=64) typically maps
            to decoded bit 5 (value 32). If None, auto-detected.
        max_time_error_ms: Maximum allowed alignment error in milliseconds.
            Read from config.sync.max_time_error_ms. Default 17.0.
        trial_count_tolerance: Maximum allowed difference between BHV2 and
            NIDQ trial counts before raising SyncError. Default 2.
        stim_count_tolerance: Per-trial tolerance for BHV2 vs NIDQ stim
            count mismatch. 0 = strict. When within tolerance, extra BHV
            stims beyond available NIDQ rising edges get stim_onset_nidq_s
            = NaN. When exceeded, all stims in that trial → NaN. Default 0.

    Returns:
        TrialAlignment with per-stimulus DataFrame, dataset_name,
        bhv_metadata, detected_trial_start_bit, and detected_stim_onset_bit
        (-1 indicates fallback formula was used).

    Raises:
        SyncError: If event array lengths mismatch, stim_onset_code out of
            range, trial count mismatch exceeds tolerance, or trial_start
            auto-detection fails.
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

    # Step 6a: Collect BHV2 stim-onset events grouped by trial
    stim_event_pairs = bhv_parser.get_event_code_times(
        stim_onset_code,
        trials=[t.trial_id for t in trials],
    )
    stim_times_by_trial: dict[int, list[float]] = {}
    for trial_id, time_ms in stim_event_pairs:
        stim_times_by_trial.setdefault(trial_id, []).append(time_ms)
    n_bhv_stims_total = len(stim_event_pairs)

    # Step 6b: Resolve stim_onset_bit (explicit or auto-detect).
    # detected_stim_onset_bit == -1 → fallback to legacy offset formula.
    if stim_onset_bit is not None:
        detected_stim_onset_bit = stim_onset_bit
    else:
        detected_stim_onset_bit = _auto_detect_stim_onset_bit(
            nidq_event_codes,
            n_bhv_stims_total,
            exclude_bit=detected_trial_start_bit,
        )

    # Step 6c: Extract NIDQ stim rising edges (if bit is known)
    use_nidq_rising = detected_stim_onset_bit >= 0
    if use_nidq_rising:
        stim_code_val = 1 << detected_stim_onset_bit
        stim_rising_mask = nidq_event_codes == stim_code_val
        nidq_stim_rising_times = nidq_event_times[stim_rising_mask]
        logger.info(
            "Using NIDQ stim rising bit=%d (code_val=%d, n=%d) for per-trial window matching",
            detected_stim_onset_bit,
            stim_code_val,
            len(nidq_stim_rising_times),
        )
    else:
        nidq_stim_rising_times = np.array([], dtype=np.float64)
        logger.warning(
            "No NIDQ bit matches BHV2 stim count (%d); falling back to "
            "trial_anchor + bhv_offset formula (may accumulate per-trial drift).",
            n_bhv_stims_total,
        )

    # Step 6d: Build per-stimulus rows with window-based matching
    rows_trial_id: list[int] = []
    rows_onset_nidq_s: list[float] = []
    rows_stim_onset_nidq_s: list[float] = []
    rows_condition_id: list[int] = []
    rows_stim_index: list[int] = []
    rows_onset_time_ms: list[float] = []
    rows_offset_time_ms: list[float] = []
    rows_fixation_window: list[float] = []
    rows_stim_onset_bhv_ms: list[float] = []

    for idx, trial in enumerate(trials):
        stim_times_ms = stim_times_by_trial.get(trial.trial_id, [])
        vc = trial.variable_changes
        onset_time = float(vc.get("onset_time", 150.0))
        offset_time = float(vc.get("offset_time", 150.0))
        fix_win = float(vc.get("fixation_window", 5.0))

        if not stim_times_ms:
            logger.warning(
                "Trial %d has no stim_onset_code=%d in BHV2; "
                "adding one row with stim_onset_nidq_s=NaN",
                trial.trial_id,
                stim_onset_code,
            )
            rows_trial_id.append(trial.trial_id)
            rows_onset_nidq_s.append(nidq_trial_onset_times[idx])
            rows_stim_onset_nidq_s.append(np.nan)
            rows_condition_id.append(trial.condition_id)
            rows_stim_index.append(0)
            rows_onset_time_ms.append(onset_time)
            rows_offset_time_ms.append(offset_time)
            rows_fixation_window.append(fix_win)
            rows_stim_onset_bhv_ms.append(np.nan)
            continue

        cit = trial.user_vars.get("Current_Image_Train")
        cit_flat = np.asarray(cit).flatten() if cit is not None else None
        n_bhv_stim = len(stim_times_ms)

        # Compute per-stim NIDQ times
        if use_nidq_rising:
            window_start = nidq_trial_onset_times[idx]
            window_end = nidq_trial_onset_times[idx + 1] if (idx + 1) < n_trials else np.inf
            in_window = (nidq_stim_rising_times >= window_start) & (
                nidq_stim_rising_times < window_end
            )
            nidq_stims_this_trial = nidq_stim_rising_times[in_window]
            n_nidq_stim = len(nidq_stims_this_trial)

            if abs(n_bhv_stim - n_nidq_stim) > stim_count_tolerance:
                logger.warning(
                    "Trial %d: BHV stim count=%d, NIDQ rising count=%d, "
                    "tolerance=%d → all stim_onset_nidq_s = NaN",
                    trial.trial_id,
                    n_bhv_stim,
                    n_nidq_stim,
                    stim_count_tolerance,
                )
                nidq_stim_values = [np.nan] * n_bhv_stim
            else:
                n_use = min(n_bhv_stim, n_nidq_stim)
                nidq_stim_values = [
                    float(nidq_stims_this_trial[i]) if i < n_use else np.nan
                    for i in range(n_bhv_stim)
                ]
        else:
            # Legacy fallback — anchor + per-stim BHV offset
            nidq_stim_values = [
                nidq_trial_onset_times[idx] + stim_ms / 1000.0 for stim_ms in stim_times_ms
            ]

        for stim_i, (stim_ms, nidq_stim) in enumerate(
            zip(stim_times_ms, nidq_stim_values, strict=True)
        ):
            rows_trial_id.append(trial.trial_id)
            rows_onset_nidq_s.append(nidq_trial_onset_times[idx])
            rows_stim_onset_nidq_s.append(nidq_stim)
            rows_condition_id.append(trial.condition_id)
            if cit_flat is not None and stim_i < len(cit_flat):
                rows_stim_index.append(int(cit_flat[stim_i]))
            else:
                rows_stim_index.append(0)
            rows_onset_time_ms.append(onset_time)
            rows_offset_time_ms.append(offset_time)
            rows_fixation_window.append(fix_win)
            rows_stim_onset_bhv_ms.append(stim_ms)

        if n_bhv_stim > 1:
            logger.info(
                "Trial %d: expanded %d stimulus presentations (RSVP)",
                trial.trial_id,
                n_bhv_stim,
            )

    n_rows = len(rows_trial_id)
    stim_onset_nidq_s = np.array(rows_stim_onset_nidq_s, dtype=np.float64)

    logger.info(
        "Expanded %d BHV2 trials → %d stimulus rows",
        n_trials,
        n_rows,
    )

    # Step 7: Alignment quality validation (monotonicity + trial onset ordering)
    if n_trials >= 2:
        # Verify trial onset times are strictly increasing
        onset_diffs = np.diff(nidq_trial_onset_times)
        if np.any(onset_diffs <= 0):
            raise SyncError(
                "NIDQ trial onset times are not strictly increasing. "
                "Check trial_start_bit detection."
            )
        # Verify stim onset times are monotonically increasing (where valid)
        valid_mask = ~np.isnan(stim_onset_nidq_s)
        if valid_mask.sum() >= 2:
            stim_valid = stim_onset_nidq_s[valid_mask]
            stim_diffs = np.diff(stim_valid)
            if np.any(stim_diffs <= 0):
                logger.warning(
                    "Stim onset times are not strictly increasing — "
                    "%d reversals detected. Check stim_onset_code.",
                    int(np.sum(stim_diffs <= 0)),
                )

    # Step 8: Build DataFrame
    df = pd.DataFrame(
        {
            "trial_id": rows_trial_id,
            "onset_nidq_s": rows_onset_nidq_s,
            "stim_onset_nidq_s": stim_onset_nidq_s,
            "condition_id": rows_condition_id,
            "stim_index": rows_stim_index,
            "trial_valid": np.full(n_rows, np.nan),
            "onset_time_ms": rows_onset_time_ms,
            "offset_time_ms": rows_offset_time_ms,
            "fixation_window": rows_fixation_window,
            "stim_onset_bhv_ms": rows_stim_onset_bhv_ms,
        }
    )

    return TrialAlignment(
        trial_events_df=df,
        dataset_name=dataset_name,
        bhv_metadata=bhv_metadata,
        detected_trial_start_bit=detected_trial_start_bit,
        detected_stim_onset_bit=detected_stim_onset_bit,
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


def _auto_detect_stim_onset_bit(
    nidq_event_codes: np.ndarray,
    n_bhv_stims_total: int,
    *,
    exclude_bit: int,
) -> int:
    """Find a decoded-domain bit whose rising count exactly matches total BHV2 stims.

    Iterates decoded bits 0-7, skipping ``exclude_bit`` (the trial_start
    bit). Returns the first bit whose count == n_bhv_stims_total, or -1
    if none match exactly. Returning -1 lets the caller fall back to the
    legacy ``trial_anchor + bhv_offset`` formula.

    Args:
        nidq_event_codes: 1D int array of decoded NIDQ event codes.
        n_bhv_stims_total: Total number of stim_onset_code events across
            all aligned BHV2 trials.
        exclude_bit: Decoded bit to skip (typically the detected
            trial_start_bit so stim and trial don't collapse onto the
            same channel when counts happen to coincide).

    Returns:
        Best-matching decoded bit index (0-7), or -1 if no exact match.
    """
    for bit in range(8):
        if bit == exclude_bit:
            continue
        code_val = 1 << bit
        count = int(np.sum(nidq_event_codes == code_val))
        if count == n_bhv_stims_total:
            logger.info(
                "Auto-detected stim_onset_bit=%d (NIDQ count=%d, BHV2 count=%d)",
                bit,
                count,
                n_bhv_stims_total,
            )
            return bit
    return -1
