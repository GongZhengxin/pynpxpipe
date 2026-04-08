"""IMEC↔NIDQ time alignment via linear regression on sync pulses.

This module provides time synchronization between IMEC AP clock and NIDQ clock
by fitting a linear correction function to sync pulse rising-edge times.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pynpxpipe.core.errors import SyncError


@dataclass
class SyncResult:
    """Result of IMEC-to-NIDQ time alignment.

    Attributes:
        probe_id: Probe identifier (e.g. "imec0").
        a: Linear coefficient (slope): t_nidq = a * t_imec + b.
        b: Linear coefficient (intercept), in seconds.
        residual_ms: RMS alignment error in milliseconds.
        n_repaired: Total number of repaired missing pulses (AP + NIDQ sides).
    """

    probe_id: str
    a: float
    b: float
    residual_ms: float
    n_repaired: int


def align_imec_to_nidq(
    probe_id: str,
    ap_sync_times: np.ndarray,
    nidq_sync_times: np.ndarray,
    max_time_error_ms: float = 17.0,
    gap_threshold_ms: float | None = 1200.0,
) -> SyncResult:
    """Fit a linear time correction from IMEC AP clock to NIDQ clock.

    Uses sync pulse rising-edge times from both streams to perform
    least-squares linear regression: t_nidq = a * t_imec + b.

    When gap_threshold_ms is not None, missing pulses are detected
    (intervals exceeding the threshold) and repaired by interpolation
    before regression. This handles the common case where one side
    drops sync pulses during recording.

    Args:
        probe_id: Probe identifier string (e.g. "imec0"), used for labeling.
        ap_sync_times: Rising-edge times from AP digital sync channel, in
            AP clock seconds. Must be 1D float64.
        nidq_sync_times: Rising-edge times from NIDQ digital sync channel, in
            NIDQ clock seconds. Must be 1D float64.
        max_time_error_ms: Maximum allowed RMS residual in milliseconds.
            Default 17.0 ms (1 sample at 60 Hz behavioral sampling).
        gap_threshold_ms: Threshold for detecting missing pulses, in milliseconds.
            Intervals exceeding this are considered gaps and repaired by
            interpolation. None disables repair (requires equal-length arrays).
            Default 1200.0 ms (20% above typical 1000 ms pulse interval).

    Returns:
        SyncResult with linear coefficients, residual, and repair count.

    Raises:
        SyncError: If sync times contain NaN/Inf, have < 2 pulses, length
            mismatch (when repair disabled or repair fails), or alignment
            residual exceeds max_time_error_ms.
    """
    # Step 1: Input validation
    if not np.isfinite(ap_sync_times).all() or not np.isfinite(nidq_sync_times).all():
        raise SyncError(f"Sync times contain NaN or Inf for probe {probe_id}")

    if len(ap_sync_times) < 2:
        raise SyncError(
            f"Insufficient sync pulses: need >= 2, got {len(ap_sync_times)} for probe {probe_id}"
        )
    if len(nidq_sync_times) < 2:
        raise SyncError(
            f"Insufficient sync pulses: need >= 2, got {len(nidq_sync_times)} for probe {probe_id}"
        )

    # Step 2: Missing pulse detection and repair
    n_repaired = 0
    ap_times = ap_sync_times.copy()
    nidq_times = nidq_sync_times.copy()

    if gap_threshold_ms is not None:
        gap_threshold_s = gap_threshold_ms / 1000.0

        # Repair AP side
        ap_times, n_ap = _repair_missing_pulses(ap_times, gap_threshold_s)
        # Repair NIDQ side
        nidq_times, n_nidq = _repair_missing_pulses(nidq_times, gap_threshold_s)

        n_repaired = n_ap + n_nidq

        # Check length match after repair
        if len(ap_times) != len(nidq_times):
            raise SyncError(
                f"Sync pulse count mismatch after repair: AP={len(ap_times)}, "
                f"NIDQ={len(nidq_times)} for probe {probe_id}. "
                f"gap_threshold_ms={gap_threshold_ms}."
            )
    else:
        # No repair, require exact match
        if len(ap_times) != len(nidq_times):
            raise SyncError(
                f"Sync pulse count mismatch: AP={len(ap_times)}, "
                f"NIDQ={len(nidq_times)} for probe {probe_id}"
            )

    # Step 3: Linear regression
    coeffs = np.polyfit(ap_times, nidq_times, 1)
    a, b = float(coeffs[0]), float(coeffs[1])

    # Step 4: Residual calculation
    predicted = a * ap_times + b
    residuals_ms = (nidq_times - predicted) * 1000.0
    residual_ms = float(np.sqrt(np.mean(residuals_ms**2)))

    # Step 5: Residual validation
    if residual_ms > max_time_error_ms:
        raise SyncError(
            f"Alignment residual {residual_ms:.3f} ms exceeds threshold "
            f"{max_time_error_ms} ms for probe {probe_id}"
        )

    # Step 6: Return result
    return SyncResult(
        probe_id=probe_id,
        a=a,
        b=b,
        residual_ms=residual_ms,
        n_repaired=n_repaired,
    )


def _repair_missing_pulses(times: np.ndarray, gap_threshold_s: float) -> tuple[np.ndarray, int]:
    """Detect and repair missing sync pulses by interpolation.

    Args:
        times: Sync pulse times in seconds (sorted).
        gap_threshold_s: Gap detection threshold in seconds.

    Returns:
        Tuple of (repaired_times, n_repaired).
    """
    if len(times) < 2:
        return times, 0

    intervals = np.diff(times)
    median_interval = np.median(intervals)

    # Find gaps exceeding threshold
    gap_mask = intervals > gap_threshold_s
    gap_indices = np.where(gap_mask)[0]

    if len(gap_indices) == 0:
        return times, 0

    # Insert interpolated pulses for each gap
    repaired_segments = []
    n_repaired = 0
    prev_idx = 0

    for gap_idx in gap_indices:
        # Add times before the gap
        repaired_segments.append(times[prev_idx : gap_idx + 1])

        # Estimate number of missing pulses
        interval = intervals[gap_idx]
        n_missing = int(round(interval / median_interval)) - 1

        if n_missing > 0:
            # Insert n_missing evenly-spaced points
            t_start = times[gap_idx]
            t_end = times[gap_idx + 1]
            inserted = np.linspace(t_start, t_end, n_missing + 2)[1:-1]
            repaired_segments.append(inserted)
            n_repaired += n_missing

        prev_idx = gap_idx + 1

    # Add remaining times after last gap
    repaired_segments.append(times[prev_idx:])

    repaired_times = np.concatenate(repaired_segments)
    return repaired_times, n_repaired
