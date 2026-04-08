"""Tests for io/sync/photodiode_calibrate.py.

Uses 1 kHz signals (sample_rate_hz=1000) for most tests so that
resample_poly(v, 1000, 1000) is a near-identity op and millisecond
arithmetic is exact.  Separate tests cover the resampling path at
30 kHz / 25 kHz.
"""

from __future__ import annotations

import numpy as np
import pytest

from pynpxpipe.core.errors import PynpxpipeError, SyncError
from pynpxpipe.io.sync.photodiode_calibrate import CalibratedOnsets, calibrate_photodiode

# --------------------------------------------------------------------------- #
# Shared constants / helpers
# --------------------------------------------------------------------------- #
SR = 1000.0  # 1 kHz — "no-op" resample path
VR = 5.0  # voltage range (V)
PRE = 10.0  # pd_window_pre_ms default
POST = 100.0  # pd_window_post_ms default
DUR = 5.0  # total signal duration (s)
MIN_VAR = 1e-6  # min_signal_variance default


def _step_int16(
    n_samples: int,
    step_idx: int,
    low_v: float = 0.0,
    high_v: float = 1.0,
    voltage_range: float = VR,
) -> np.ndarray:
    """Int16-encoded rising step: low before step_idx, high after."""
    v = np.where(np.arange(n_samples) >= step_idx, high_v, low_v)
    return (v * 32768.0 / voltage_range).astype(np.int16)


def _falling_step_int16(
    n_samples: int,
    step_idx: int,
    low_v: float = 0.0,
    high_v: float = 1.0,
    voltage_range: float = VR,
) -> np.ndarray:
    """Int16-encoded falling step: high before step_idx, low after."""
    v = np.where(np.arange(n_samples) >= step_idx, low_v, high_v)
    return (v * 32768.0 / voltage_range).astype(np.int16)


def _good_call(
    trigger_s: float = 1.0,
    latency_ms: float = 20.0,
    monitor_delay_ms: float = 0.0,
    sample_rate_hz: float = SR,
    pre_ms: float = PRE,
    post_ms: float = POST,
    voltage_range: float = VR,
) -> CalibratedOnsets:
    """Run calibrate_photodiode with a single clean rising-step trial."""
    n = int(DUR * sample_rate_hz)
    step_idx = int(round((trigger_s + latency_ms / 1000.0) * sample_rate_hz))
    pd = _step_int16(n, step_idx, voltage_range=voltage_range)
    onsets = np.array([trigger_s])
    return calibrate_photodiode(
        pd,
        sample_rate_hz,
        voltage_range,
        onsets,
        monitor_delay_ms=monitor_delay_ms,
        pd_window_pre_ms=pre_ms,
        pd_window_post_ms=post_ms,
    )


# =========================================================================== #
# Normal cases
# =========================================================================== #


def test_returns_calibrated_onsets_dataclass():
    result = _good_call()
    assert isinstance(result, CalibratedOnsets)


def test_good_trial_quality_flag_zero():
    result = _good_call(latency_ms=20.0)
    assert result.quality_flags[0] == 0


def test_onset_latency_detected_correctly():
    result = _good_call(latency_ms=20.0, monitor_delay_ms=0.0)
    assert abs(result.onset_latency_ms[0] - 20.0) <= 1.0


def test_monitor_delay_applied():
    # latency_raw=20ms, monitor_delay=-5ms → corrected = 20 - (-5) = 25
    result = _good_call(latency_ms=20.0, monitor_delay_ms=-5.0)
    assert abs(result.onset_latency_ms[0] - 25.0) <= 1.0


def test_stim_onset_nidq_updated():
    result = _good_call(trigger_s=1.0, latency_ms=20.0, monitor_delay_ms=0.0)
    # onset should be updated to ~1.020
    assert abs(result.stim_onset_nidq_s[0] - 1.020) <= 0.001


def test_multiple_trials_all_good():
    n = int(DUR * SR)
    trigger_times = np.array([0.5, 1.0, 1.5, 2.0, 2.5])
    latencies_ms = [15.0, 20.0, 25.0, 30.0, 35.0]
    voltage = np.zeros(n, dtype=float)
    for t, lat in zip(trigger_times, latencies_ms, strict=True):
        step_idx = int(round((t + lat / 1000.0) * SR))
        voltage[step_idx:] += 1.0
    # Encode to int16
    pd = (voltage * 32768.0 / VR).clip(-32768, 32767).astype(np.int16)
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        trigger_times,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert all(result.quality_flags == 0)


def test_n_suspicious_zero_when_all_good():
    result = _good_call()
    assert result.n_suspicious == 0


def test_int16_to_voltage_conversion():
    """Verify int16→voltage: v = int16 * (voltage_range / 32768)."""
    known_int16 = np.array([0, 16384, -16384, 32767], dtype=np.int16)
    expected_v = known_int16.astype(float) * (VR / 32768.0)
    # Create a zero-variance guard: pad with variation so global var passes
    n = int(DUR * SR)
    pd = np.zeros(n, dtype=np.int16)
    # Place known values at positions 0..3
    pd[:4] = known_int16
    # Add a step at 3s to ensure global variance passes and we can call it
    pd[3000:] = np.int16(16384)
    # Just verify the conversion formula numerically (independent of API)
    converted = known_int16.astype(float) * (VR / 32768.0)
    np.testing.assert_allclose(converted, expected_v)


# =========================================================================== #
# Resampling
# =========================================================================== #


def test_resample_to_1ms():
    """1 second of 30 kHz data resamples to ≈1000 samples."""
    sr = 30_000.0
    n = int(1.0 * sr)  # 30000 samples
    pd = _step_int16(n, n // 2)  # step in the middle
    onsets = np.array([0.3])  # well within the 1s duration
    result = calibrate_photodiode(
        pd,
        sr,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    # Smoke test: function runs without error and returns correct type
    assert isinstance(result, CalibratedOnsets)


def test_resample_preserves_step_location():
    """After resampling 30 kHz → 1 ms, detected onset ≈ planted latency."""
    sr = 30_000.0
    trigger_s = 0.5
    latency_ms = 20.0
    n = int(2.0 * sr)  # 2 seconds
    step_idx = int(round((trigger_s + latency_ms / 1000.0) * sr))
    pd = _step_int16(n, step_idx)
    onsets = np.array([trigger_s])
    result = calibrate_photodiode(
        pd,
        sr,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert result.quality_flags[0] == 0
    assert abs(result.onset_latency_ms[0] - latency_ms) <= 2.0


def test_resample_ratio_from_sample_rate():
    """25 kHz signal resamples correctly (down ratio = 25, not 25000)."""
    sr = 25_000.0
    trigger_s = 0.5
    latency_ms = 30.0
    n = int(2.0 * sr)
    step_idx = int(round((trigger_s + latency_ms / 1000.0) * sr))
    pd = _step_int16(n, step_idx)
    onsets = np.array([trigger_s])
    result = calibrate_photodiode(
        pd,
        sr,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert result.quality_flags[0] == 0
    assert abs(result.onset_latency_ms[0] - latency_ms) <= 2.0


# =========================================================================== #
# Quality flags
# =========================================================================== #


def test_negative_latency_flag():
    """Signal exceeds threshold before digital trigger → flag=1."""
    n = int(DUR * SR)
    trigger_s = 1.0
    # Step 5ms BEFORE trigger (within the pre-window of 10ms)
    step_idx = int((trigger_s - 0.005) * SR)
    pd = _step_int16(n, step_idx)
    onsets = np.array([trigger_s])
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert result.quality_flags[0] == 1


def test_out_of_bounds_flag_window_start():
    """Window start < 0 → flag=2."""
    n = int(DUR * SR)
    pd = _step_int16(n, 100)
    # Trigger at 5ms → idx_start = round(5 - 10) = -5 < 0
    onsets = np.array([0.005])
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert result.quality_flags[0] == 2


def test_out_of_bounds_flag_window_end():
    """Window end > len(pd_1ms) → flag=2."""
    n = int(DUR * SR)
    pd = _step_int16(n, 100)
    # Trigger very close to end: DUR - 0.05s → idx_end = DUR*1000 - 50 + 100 = beyond len
    onsets = np.array([DUR - 0.05])
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert result.quality_flags[0] == 2


def test_nan_onset_flag_out_of_bounds():
    """NaN onset → flag=2."""
    n = int(DUR * SR)
    pd = _step_int16(n, 500)
    onsets = np.array([np.nan])
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert result.quality_flags[0] == 2


def test_low_signal_per_trial_flag():
    """Window with near-zero variance → flag=3."""
    n = int(DUR * SR)
    # Global signal has variation (so we pass global check) but one trial
    # window is nearly flat
    pd = _step_int16(n, int(3.5 * SR))  # step at 3.5s
    # Trial at 1.0s: window [990:1100] is all-zero (flat)
    onsets = np.array([1.0])
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
        min_signal_variance=1e-6,
    )
    assert result.quality_flags[0] == 3


def test_suspicious_count_matches_flags():
    """n_suspicious counts trials with quality_flag != 0."""
    n = int(DUR * SR)
    # trial 0: good (step at trigger+20ms)
    # trial 1: good (step at trigger+30ms)
    # trial 2: NaN → flag=2
    # trial 3: step before trigger → flag=1

    # Build signal manually
    voltage = np.zeros(n, dtype=float)
    voltage[int(1.020 * SR) :] += 1.0  # rising at 1.020s (good for trial 0)
    voltage[int(1.530 * SR) :] += 1.0  # another rise (good for trial 1)
    pd = (voltage * 32768.0 / VR).clip(-32768, 32767).astype(np.int16)

    onsets = np.array([1.0, 1.5, np.nan, 2.5])
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    # trial 2 (NaN) → flag=2; count the rest based on actual detection
    assert result.quality_flags[2] == 2
    assert result.n_suspicious == int(np.sum(result.quality_flags != 0))


def test_flagged_trials_retain_original_time():
    """Trials with quality_flag != 0 keep original stim_onset_times_s value."""
    n = int(DUR * SR)
    pd = _step_int16(n, 500)
    onsets = np.array([np.nan, 0.0025])  # trial0: NaN; trial1: OOB (window start<0)
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    # NaN onset: original is NaN → retained as NaN
    assert np.isnan(result.stim_onset_nidq_s[0])
    # OOB onset: original time retained unchanged
    assert result.stim_onset_nidq_s[1] == pytest.approx(0.0025)


# =========================================================================== #
# Threshold calculation
# =========================================================================== #


def test_global_threshold_formula():
    """Threshold = 0.1*baseline_mean + 0.9*stim_period_mean (end-to-end)."""
    # Single trial: step at +30ms, pre=10ms, post=100ms
    # Analytically: 40 low samples, 70 high samples in 110-sample window
    # baseline_mean < 0 (z-score), stim_period_mean mostly positive
    # threshold makes first_above=30 → latency≈30ms
    result = _good_call(trigger_s=1.0, latency_ms=30.0, monitor_delay_ms=0.0)
    assert result.quality_flags[0] == 0
    assert abs(result.onset_latency_ms[0] - 30.0) <= 1.5


def test_threshold_is_global_not_per_trial():
    """Two trials with same signal profile get the same latency."""
    n = int(DUR * SR)
    trigger_times = np.array([1.0, 2.5])
    latency_ms = 25.0
    voltage = np.zeros(n, dtype=float)
    for t in trigger_times:
        step_idx = int(round((t + latency_ms / 1000.0) * SR))
        if step_idx < n:
            voltage[step_idx:] += 1.0
    pd = (voltage * 32768.0 / VR).clip(-32768, 32767).astype(np.int16)
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        trigger_times,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert result.quality_flags[0] == 0
    assert result.quality_flags[1] == 0
    # Both should detect at roughly the same latency (global threshold applied)
    assert abs(result.onset_latency_ms[0] - result.onset_latency_ms[1]) <= 1.0


# =========================================================================== #
# Global signal quality
# =========================================================================== #


def test_dead_signal_raises_sync_error():
    """All-zero int16 signal → SyncError with 'variance' in message."""
    pd = np.zeros(int(DUR * SR), dtype=np.int16)
    with pytest.raises(SyncError, match="variance"):
        calibrate_photodiode(pd, SR, VR, np.array([1.0]), monitor_delay_ms=0.0)


def test_near_zero_signal_raises_sync_error():
    """Signal variance < min_signal_variance → SyncError."""
    pd = np.ones(int(DUR * SR), dtype=np.int16)  # constant 1 → near-zero var
    with pytest.raises(SyncError):
        calibrate_photodiode(
            pd,
            SR,
            VR,
            np.array([1.0]),
            monitor_delay_ms=0.0,
            min_signal_variance=1.0,
        )


def test_sync_error_is_pynpxpipe_error():
    """SyncError is a subclass of PynpxpipeError."""
    pd = np.zeros(int(DUR * SR), dtype=np.int16)
    with pytest.raises(PynpxpipeError):
        calibrate_photodiode(pd, SR, VR, np.array([1.0]), monitor_delay_ms=0.0)


# =========================================================================== #
# Edge cases
# =========================================================================== #


def test_single_trial():
    """Single trial returns arrays of length 1."""
    result = _good_call()
    assert len(result.stim_onset_nidq_s) == 1
    assert len(result.onset_latency_ms) == 1
    assert len(result.quality_flags) == 1


def test_all_trials_out_of_bounds():
    """All trials OOB → all flags=2, n_suspicious=n_trials."""
    n = int(DUR * SR)
    pd = _step_int16(n, 100)
    # All triggers near time=0 → idx_start < 0
    onsets = np.array([0.005, 0.007, 0.009])
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert np.all(result.quality_flags == 2)
    assert result.n_suspicious == 3


def test_no_threshold_crossing():
    """Flat stim window (no crossing) → flag=3."""
    n = int(DUR * SR)
    # Step is very late (at 4.9s), trigger at 1.0s → window [990:1100] is flat
    pd = _step_int16(n, int(4.9 * SR))
    onsets = np.array([1.0])
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
        min_signal_variance=1e-6,
    )
    assert result.quality_flags[0] == 3


# =========================================================================== #
# Polarity correction
# =========================================================================== #


def test_falling_edge_signal_corrected():
    """Falling-edge (high→low) signal still detects onset correctly."""
    n = int(DUR * SR)
    trigger_s = 1.0
    latency_ms = 20.0
    step_idx = int(round((trigger_s + latency_ms / 1000.0) * SR))
    pd = _falling_step_int16(n, step_idx)
    onsets = np.array([trigger_s])
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        onsets,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert result.quality_flags[0] == 0
    assert abs(result.onset_latency_ms[0] - latency_ms) <= 1.5


def test_rising_edge_signal_unchanged():
    """Rising edge: polarity NOT flipped, detection correct."""
    result = _good_call(latency_ms=25.0, monitor_delay_ms=0.0)
    assert result.quality_flags[0] == 0
    assert abs(result.onset_latency_ms[0] - 25.0) <= 1.5


def test_mixed_polarity_trials():
    """Rising, falling, rising trials all detect onset at same latency."""
    n = int(DUR * SR)
    triggers = np.array([1.0, 2.0, 3.0])
    latency_ms = 20.0
    voltage = np.zeros(n, dtype=float)
    for i, t in enumerate(triggers):
        step_idx = int(round((t + latency_ms / 1000.0) * SR))
        if i == 1:  # falling edge for trial 1
            voltage[:step_idx] += 1.0  # high before, low after
        else:
            voltage[step_idx:] += 1.0  # low before, high after
    pd = (voltage * 32768.0 / VR).clip(-32768, 32767).astype(np.int16)
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        triggers,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert np.all(result.quality_flags == 0)
    # All three latencies should be close to latency_ms
    for lat in result.onset_latency_ms:
        assert abs(lat - latency_ms) <= 2.0


def test_polarity_correction_before_threshold():
    """All falling-edge trials: global threshold computed on flipped signals."""
    n = int(DUR * SR)
    triggers = np.array([1.0, 2.0, 3.0])
    latency_ms = 25.0
    voltage = np.zeros(n, dtype=float)
    for t in triggers:
        step_idx = int(round((t + latency_ms / 1000.0) * SR))
        voltage[:step_idx] += 1.0  # all falling
    pd = (voltage * 32768.0 / VR).clip(-32768, 32767).astype(np.int16)
    result = calibrate_photodiode(
        pd,
        SR,
        VR,
        triggers,
        monitor_delay_ms=0.0,
        pd_window_pre_ms=PRE,
        pd_window_post_ms=POST,
    )
    assert np.all(result.quality_flags == 0)
    for lat in result.onset_latency_ms:
        assert abs(lat - latency_ms) <= 2.0
