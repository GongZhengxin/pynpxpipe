"""Photodiode analog signal calibration for stimulus onset timing.

Implements the third tier of the synchronisation pipeline:
NIDQ photodiode channel → per-trial z-score + polarity correction →
global threshold detection → calibrated stimulus onset times.

Windows are extracted directly in the native NIDQ sampling domain
(no ``resample_poly(up=1000, down=int(round(sr)))``), avoiding the
ppm-level rate mismatch that accumulates as a linear time drift
across a session when ``niSampRate`` is non-integer.

cf. MATLAB step #10 (photodiode onset calibration) and
step #11 (monitor delay correction).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from pynpxpipe.core.errors import SyncError

logger = logging.getLogger(__name__)


@dataclass
class CalibratedOnsets:
    """Photodiode-calibrated stimulus onset times.

    Attributes:
        stim_onset_nidq_s: Refined stim onset times in NIDQ clock seconds.
            Shape (n_trials,). Trials flagged non-zero retain the original
            digital event code time without photodiode correction.
        onset_latency_ms: Measured photodiode onset latency per trial (ms).
            Shape (n_trials,). NaN for trials that were skipped (flag=2).
        quality_flags: Per-trial integer quality indicator. Shape (n_trials,).
            0 = good, 1 = negative_latency, 2 = out_of_bounds, 3 = low_signal.
        n_suspicious: Count of trials where quality_flag != 0.
    """

    stim_onset_nidq_s: np.ndarray
    onset_latency_ms: np.ndarray
    quality_flags: np.ndarray
    n_suspicious: int


def calibrate_photodiode(
    photodiode_signal: np.ndarray,
    sample_rate_hz: float,
    voltage_range: float,
    stim_onset_times_s: np.ndarray,
    monitor_delay_ms: float,
    pd_window_pre_ms: float = 10.0,
    pd_window_post_ms: float = 100.0,
    pd_hignline_skip_ms: float = 50.0,
    pd_hignline_width_ms: float = 20.0,
    min_signal_variance: float = 1e-6,
) -> CalibratedOnsets:
    """Calibrate stimulus onset times using the photodiode analog signal.

    Converts the raw NIDQ int16 photodiode channel to voltage, extracts
    per-trial windows around digital stim onset times **directly in the
    NIDQ sampling domain (no 1 kHz resampling)**, applies per-trial z-score
    normalization with polarity correction, and detects the first
    global-threshold crossing to measure actual display onset latency.

    Avoiding ``resample_poly`` eliminates the ppm-level rate mismatch that
    ``int(round(niSampRate))`` introduces when ``niSampRate`` is non-integer
    (typical SpikeGLX output like ``25000.***`` / ``30000.***``). That
    mismatch accumulates into ~10–30 ms of linear drift across a
    30–60 min session.

    The global detection threshold is computed once across all valid trials:
        threshold = 0.1 * baseline_mean + 0.9 * hignline_mean
    where ``baseline`` is the pre-onset window and ``hignline`` is a narrow
    steady-state slice of the post-onset window (default 60–80 ms after
    trigger, matching MATLAB ``po_dis(:, before+after_measure+[1:20])``).
    Using the full 0–100 ms post window depresses the threshold with the
    rising edge and produces too-early detections.

    Quality flags per trial:
        0 - good: photodiode onset detected and latency correction applied.
        1 - negative_latency: signal exceeded threshold before digital trigger;
            warning logged, original digital time retained.
        2 - out_of_bounds: trial window extends beyond recording boundaries or
            stim_onset_times_s[i] is NaN; trial skipped, original time retained.
        3 - low_signal: signal variance too low in this trial's window;
            warning logged, original digital time retained.

    Args:
        photodiode_signal: Raw int16 1D array from the NIDQ analog channel
            (photodiode_channel_index). Length = n_nidq_samples.
        sample_rate_hz: NIDQ analog sampling rate in Hz. Read from nidq.meta
            niSampRate field. Never hardcode.
        voltage_range: ADC full-scale range in volts (single-sided). Read
            from nidq.meta niAiRangeMax field. Never hardcode.
        stim_onset_times_s: 1D float64 array, shape (n_trials,). Digital
            stim onset times in NIDQ clock seconds. May contain NaN.
        monitor_delay_ms: Systematic display delay correction (ms). Read from
            config.sync.monitor_delay_ms. Applied as
            ``corrected_latency = latency_raw + monitor_delay_ms`` so that a
            negative config value subtracts from the final onset time (MATLAB
            equivalent: ``onset - 5`` with a hard-coded ``-5``).
            Typical value for 60 Hz monitor is -5 ms. Never hardcode.
        pd_window_pre_ms: Baseline window before stim onset (ms). Default 10.0.
            Read from config.sync.pd_window_pre_ms.
        pd_window_post_ms: Detection window after stim onset (ms).
            Default 100.0. Read from config.sync.pd_window_post_ms.
        pd_hignline_skip_ms: Stabilization skip before threshold's "hignline"
            window (ms), counted from trigger. Default 50.0. Read from
            config.sync.pd_hignline_skip_ms.
        pd_hignline_width_ms: Hignline window width (ms). Default 20.0.
            Read from config.sync.pd_hignline_width_ms.
        min_signal_variance: Minimum acceptable signal variance after
            int16→voltage conversion. Default 1e-6.

    Returns:
        CalibratedOnsets with refined onset times, per-trial latencies,
        quality flags, and suspicious trial count.

    Raises:
        SyncError: If the overall photodiode signal variance is below
            min_signal_variance (indicates disconnected photodiode).
    """
    # ------------------------------------------------------------------ #
    # Step 1: int16 → voltage + global quality check
    # ------------------------------------------------------------------ #
    voltage = photodiode_signal.astype(float) * (voltage_range / 32768.0)
    var_global = float(np.var(voltage))
    if var_global < min_signal_variance:
        raise SyncError(
            f"Photodiode signal variance {var_global:.2e} too low. Check photodiode connection."
        )

    # ------------------------------------------------------------------ #
    # Step 2: Native-domain window sizing (no resampling; see module docstring)
    # ------------------------------------------------------------------ #
    pre_samples = int(round(pd_window_pre_ms / 1000.0 * sample_rate_hz))
    post_samples = int(round(pd_window_post_ms / 1000.0 * sample_rate_hz))
    ms_per_sample = 1000.0 / sample_rate_hz
    window_len = pre_samples + post_samples

    hignline_skip_samples = int(round(pd_hignline_skip_ms / 1000.0 * sample_rate_hz))
    hignline_width_samples = int(round(pd_hignline_width_ms / 1000.0 * sample_rate_hz))
    hignline_start = pre_samples + hignline_skip_samples
    hignline_end = hignline_start + hignline_width_samples
    if hignline_end > window_len:
        logger.warning(
            "Hignline window end (%d samples, %.1f ms) exceeds post window "
            "(%d samples, %.1f ms); falling back to full post-onset range for threshold.",
            hignline_end,
            hignline_end * ms_per_sample,
            window_len,
            window_len * ms_per_sample,
        )
        hignline_start = pre_samples
        hignline_end = window_len

    # ------------------------------------------------------------------ #
    # Step 3: Initialise output arrays
    # ------------------------------------------------------------------ #
    n_trials = len(stim_onset_times_s)
    result_onsets = stim_onset_times_s.copy().astype(float)
    onset_latency_ms = np.full(n_trials, np.nan)
    quality_flags = np.zeros(n_trials, dtype=int)

    # ------------------------------------------------------------------ #
    # Step 4: First pass — z-score + polarity correction per trial
    # ------------------------------------------------------------------ #
    z_windows: list[np.ndarray | None] = [None] * n_trials

    for i in range(n_trials):
        # 4a: NaN onset
        if np.isnan(stim_onset_times_s[i]):
            quality_flags[i] = 2
            continue

        # 4b: Extract window indices in native NIDQ samples
        center = int(round(stim_onset_times_s[i] * sample_rate_hz))
        idx_start = center - pre_samples
        idx_end = center + post_samples

        if idx_start < 0 or idx_end > len(voltage):
            quality_flags[i] = 2
            continue

        # 4c: Extract window
        window = voltage[idx_start:idx_end]

        # 4d: Per-trial signal variance check
        if np.var(window) < min_signal_variance:
            quality_flags[i] = 3
            logger.warning("Trial %d: photodiode window variance too low (flag=3)", i)
            continue

        # 4e: Z-score normalisation
        mean_w = float(np.mean(window))
        std_w = float(np.std(window))
        if std_w == 0.0:
            quality_flags[i] = 3
            continue
        z_window = (window - mean_w) / std_w

        # 4f: Per-trial polarity correction
        # cf. MATLAB step #10: polarity correction via max abs-diff
        abs_diff = np.abs(np.diff(z_window))
        max_change_idx = int(np.argmax(abs_diff))
        raw_diff = float(np.diff(z_window)[max_change_idx])
        if raw_diff < 0:  # falling edge → flip to rising
            z_window = -z_window

        z_windows[i] = z_window

    # ------------------------------------------------------------------ #
    # Step 5: Compute global threshold from all valid trials
    #         Uses only the hignline window (default 60–80 ms) to avoid
    #         the rising edge depressing the threshold.
    # ------------------------------------------------------------------ #
    valid_trials = [i for i in range(n_trials) if quality_flags[i] == 0]

    if not valid_trials:
        n_suspicious = int(np.sum(quality_flags != 0))
        return CalibratedOnsets(
            stim_onset_nidq_s=result_onsets,
            onset_latency_ms=onset_latency_ms,
            quality_flags=quality_flags,
            n_suspicious=n_suspicious,
        )

    baseline_vals: list[float] = []
    hignline_vals: list[float] = []
    for i in valid_trials:
        z_w = z_windows[i]
        assert z_w is not None  # guaranteed by valid_trials filter
        baseline_vals.extend(z_w[:pre_samples].tolist())
        hignline_vals.extend(z_w[hignline_start:hignline_end].tolist())

    baseline_mean = float(np.mean(baseline_vals))
    hignline_mean = float(np.mean(hignline_vals))
    global_threshold = 0.1 * baseline_mean + 0.9 * hignline_mean

    # ------------------------------------------------------------------ #
    # Step 6: Second pass — threshold detection
    # ------------------------------------------------------------------ #
    for i in range(n_trials):
        if quality_flags[i] != 0:
            continue

        z_w = z_windows[i]
        assert z_w is not None

        baseline_seg = z_w[:pre_samples]
        stim_seg = z_w[pre_samples:]

        # 6b/6c: Find first crossing in stim segment
        above = np.where(stim_seg > global_threshold)[0]
        if len(above) == 0:
            quality_flags[i] = 3
            logger.warning("Trial %d: no threshold crossing in stim window (flag=3)", i)
            continue

        first_above = int(above[0])
        latency_raw_ms = first_above * ms_per_sample

        # 6e: Negative-latency check (signal already high in baseline)
        if np.any(baseline_seg > global_threshold):
            quality_flags[i] = 1
            logger.warning(
                "Trial %d: negative latency — threshold crossed before digital trigger (flag=1)",
                i,
            )
            continue

        # 6f/6g: Apply monitor delay and update outputs
        # corrected = latency_raw + monitor_delay_ms  (MATLAB equivalent: onset - 5
        # with a hard-coded -5; config value is signed).
        corrected_latency_ms = latency_raw_ms + monitor_delay_ms
        onset_latency_ms[i] = corrected_latency_ms
        result_onsets[i] = stim_onset_times_s[i] + corrected_latency_ms / 1000.0

    # ------------------------------------------------------------------ #
    # Step 7: Summary
    # ------------------------------------------------------------------ #
    n_suspicious = int(np.sum(quality_flags != 0))
    if n_suspicious > 0:
        counts = {
            "negative_latency": int(np.sum(quality_flags == 1)),
            "out_of_bounds": int(np.sum(quality_flags == 2)),
            "low_signal": int(np.sum(quality_flags == 3)),
        }
        logger.warning(
            "%d suspicious trial(s) in photodiode calibration: %s",
            n_suspicious,
            counts,
        )

    return CalibratedOnsets(
        stim_onset_nidq_s=result_onsets,
        onset_latency_ms=onset_latency_ms,
        quality_flags=quality_flags,
        n_suspicious=n_suspicious,
    )
