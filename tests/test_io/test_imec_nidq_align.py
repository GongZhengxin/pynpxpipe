"""Tests for io/sync/imec_nidq_align.py — IMEC↔NIDQ time alignment."""

import numpy as np
import pytest

from pynpxpipe.core.errors import SyncError
from pynpxpipe.io.sync.imec_nidq_align import SyncResult, align_imec_to_nidq


class TestAlignImecToNidq:
    """Test suite for align_imec_to_nidq function."""

    def test_perfect_alignment_returns_identity(self):
        """Spec: Perfect alignment (identical times) returns a≈1.0, b≈0.0."""
        probe_id = "imec0"
        times = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64)

        result = align_imec_to_nidq(
            probe_id=probe_id,
            ap_sync_times=times,
            nidq_sync_times=times,
            max_time_error_ms=17.0,
            gap_threshold_ms=None,
        )

        assert isinstance(result, SyncResult)
        assert result.probe_id == probe_id
        assert abs(result.a - 1.0) < 1e-6
        assert abs(result.b) < 1e-6
        assert result.residual_ms < 1e-6
        assert result.n_repaired == 0

    def test_constant_offset_returns_correct_intercept(self):
        """Spec: Constant offset (b=0.5s) returns a≈1.0, b≈0.5."""
        probe_id = "imec1"
        ap_times = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
        nidq_times = ap_times + 0.5

        result = align_imec_to_nidq(
            probe_id=probe_id,
            ap_sync_times=ap_times,
            nidq_sync_times=nidq_times,
            max_time_error_ms=17.0,
            gap_threshold_ms=None,
        )

        assert abs(result.a - 1.0) < 1e-6
        assert abs(result.b - 0.5) < 1e-3
        assert result.residual_ms < 1.0

    def test_clock_drift_returns_slope_not_one(self):
        """Spec: Clock drift (1% faster) returns a≈1.01."""
        probe_id = "imec0"
        ap_times = np.array([0.0, 100.0, 200.0, 300.0], dtype=np.float64)
        nidq_times = ap_times * 1.01

        result = align_imec_to_nidq(
            probe_id=probe_id,
            ap_sync_times=ap_times,
            nidq_sync_times=nidq_times,
            max_time_error_ms=17.0,
            gap_threshold_ms=None,
        )

        assert abs(result.a - 1.01) < 1e-4
        assert result.residual_ms < 1.0

    def test_insufficient_pulses_raises_sync_error(self):
        """Spec: < 2 pulses raises SyncError."""
        with pytest.raises(SyncError, match="Insufficient sync pulses"):
            align_imec_to_nidq(
                probe_id="imec0",
                ap_sync_times=np.array([1.0]),
                nidq_sync_times=np.array([1.0]),
                max_time_error_ms=17.0,
                gap_threshold_ms=None,
            )

    def test_nan_in_times_raises_sync_error(self):
        """Spec: NaN in sync times raises SyncError."""
        with pytest.raises(SyncError, match="contain NaN or Inf"):
            align_imec_to_nidq(
                probe_id="imec0",
                ap_sync_times=np.array([0.0, np.nan, 2.0]),
                nidq_sync_times=np.array([0.0, 1.0, 2.0]),
                max_time_error_ms=17.0,
                gap_threshold_ms=None,
            )

    def test_length_mismatch_without_repair_raises_sync_error(self):
        """Spec: Length mismatch with gap_threshold_ms=None raises SyncError."""
        with pytest.raises(SyncError, match="Sync pulse count mismatch"):
            align_imec_to_nidq(
                probe_id="imec0",
                ap_sync_times=np.array([0.0, 1.0, 2.0]),
                nidq_sync_times=np.array([0.0, 1.0]),
                max_time_error_ms=17.0,
                gap_threshold_ms=None,
            )

    def test_excessive_residual_raises_sync_error(self):
        """Spec: Residual > max_time_error_ms raises SyncError."""
        probe_id = "imec0"
        ap_times = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
        # Add large noise to create high residual
        nidq_times = ap_times + np.array([0.0, 0.05, -0.05, 0.1])

        with pytest.raises(SyncError, match="Alignment residual.*exceeds threshold"):
            align_imec_to_nidq(
                probe_id=probe_id,
                ap_sync_times=ap_times,
                nidq_sync_times=nidq_times,
                max_time_error_ms=1.0,  # Very strict threshold
                gap_threshold_ms=None,
            )

    def test_repair_single_missing_pulse_ap_side(self):
        """Spec: Missing 1 pulse on AP side gets repaired."""
        probe_id = "imec0"
        # AP missing pulse at t=2.0
        ap_times = np.array([0.0, 1.0, 3.0, 4.0], dtype=np.float64)
        nidq_times = np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=np.float64)

        result = align_imec_to_nidq(
            probe_id=probe_id,
            ap_sync_times=ap_times,
            nidq_sync_times=nidq_times,
            max_time_error_ms=17.0,
            gap_threshold_ms=1200.0,  # 1.2s threshold, gap is 2.0s
        )

        assert result.n_repaired == 1
        assert result.residual_ms < 10.0

    def test_repair_single_missing_pulse_nidq_side(self):
        """Spec: Missing 1 pulse on NIDQ side gets repaired."""
        probe_id = "imec0"
        ap_times = np.array([0.0, 1.0, 2.0, 3.0, 4.0], dtype=np.float64)
        # NIDQ missing pulse at t=2.0
        nidq_times = np.array([0.0, 1.0, 3.0, 4.0], dtype=np.float64)

        result = align_imec_to_nidq(
            probe_id=probe_id,
            ap_sync_times=ap_times,
            nidq_sync_times=nidq_times,
            max_time_error_ms=17.0,
            gap_threshold_ms=1200.0,
        )

        assert result.n_repaired == 1
        assert result.residual_ms < 10.0

    def test_repair_fails_large_mismatch(self):
        """Spec: Large mismatch without corresponding gap raises SyncError."""
        probe_id = "imec0"
        # AP has 100 pulses, NIDQ has 90, but no single gap > threshold
        ap_times = np.linspace(0, 99, 100, dtype=np.float64)
        nidq_times = np.linspace(0, 89, 90, dtype=np.float64)

        with pytest.raises(SyncError, match="after repair"):
            align_imec_to_nidq(
                probe_id=probe_id,
                ap_sync_times=ap_times,
                nidq_sync_times=nidq_times,
                max_time_error_ms=17.0,
                gap_threshold_ms=1200.0,
            )

    def test_repair_preserves_regression_accuracy(self):
        """Spec: Repair should not degrade regression accuracy."""
        probe_id = "imec0"
        # Perfect alignment except 1 missing pulse
        ap_times = np.array([0.0, 1.0, 3.0, 4.0, 5.0], dtype=np.float64)
        nidq_times = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)

        result = align_imec_to_nidq(
            probe_id=probe_id,
            ap_sync_times=ap_times,
            nidq_sync_times=nidq_times,
            max_time_error_ms=17.0,
            gap_threshold_ms=1200.0,
        )

        assert result.n_repaired == 1
        assert result.residual_ms < 1.0  # Should still be very accurate
