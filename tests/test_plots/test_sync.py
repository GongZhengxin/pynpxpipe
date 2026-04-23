"""Tests for pynpxpipe.plots.sync — Nature-style synchronize diagnostic plots.

All plots are rendered with the ``Agg`` backend; no display is required.
Input data is kept small (≤ 100 samples per dimension) so CI runs fast.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from pynpxpipe.io.sync.bhv_nidq_align import TrialAlignment
from pynpxpipe.io.sync.imec_nidq_align import SyncResult
from pynpxpipe.io.sync.photodiode_calibrate import CalibratedOnsets
from pynpxpipe.plots.sync import emit_all

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

N_PULSES = 100
N_TRIALS = 10
NIDQ_SR = 25_000.0


def _make_sync_result(probe_id: str = "imec0") -> SyncResult:
    return SyncResult(
        probe_id=probe_id,
        a=1.0,
        b=0.0,
        residual_ms=0.1,
        n_repaired=0,
    )


def _make_sync_times() -> tuple[np.ndarray, np.ndarray]:
    ap = np.arange(N_PULSES, dtype=np.float64) * 1.0  # 1 second intervals
    nidq = ap + 0.001 * np.random.RandomState(0).randn(N_PULSES)
    return ap, nidq


def _make_trial_alignment() -> TrialAlignment:
    # Three distinct trial_ids, some with multiple stim events.
    df = pd.DataFrame(
        {
            "trial_id": [1, 1, 2, 3, 3, 3] + list(range(4, 4 + N_TRIALS - 3)),
            "onset_nidq_s": np.linspace(1.0, 5.0, 6 + N_TRIALS - 3),
            "stim_onset_nidq_s": np.linspace(1.1, 5.1, 6 + N_TRIALS - 3),
            "condition_id": [0] * (6 + N_TRIALS - 3),
            "stim_index": [1] * (6 + N_TRIALS - 3),
            "trial_valid": [np.nan] * (6 + N_TRIALS - 3),
        }
    )
    return TrialAlignment(
        trial_events_df=df,
        dataset_name="mock",
        bhv_metadata={"DatasetName": "mock"},
        detected_trial_start_bit=3,
    )


def _make_calibrated(n: int = N_TRIALS) -> CalibratedOnsets:
    # Spread across 1-5 seconds so windows don't fall outside our pd_signal.
    onsets = np.linspace(1.0, 5.0, n)
    latency = np.linspace(5.0, 20.0, n)
    flags = np.zeros(n, dtype=np.int32)
    flags[-1] = 2  # one out_of_bounds trial
    return CalibratedOnsets(
        stim_onset_nidq_s=onsets,
        onset_latency_ms=latency,
        quality_flags=flags,
        n_suspicious=int((flags != 0).sum()),
    )


def _make_pd_signal(duration_s: float = 10.0, sr: float = NIDQ_SR) -> np.ndarray:
    n = int(duration_s * sr)
    # Fake photodiode: baseline noise + step at each second.
    rng = np.random.RandomState(1)
    signal = rng.randn(n).astype(np.float64) * 100.0
    for onset_s in np.arange(0.5, duration_s, 1.0):
        idx = int(onset_s * sr)
        signal[idx : idx + int(0.05 * sr)] += 5000.0
    return signal.astype(np.int16)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_emit_all_returns_paths(tmp_path: Path) -> None:
    """Without pd_signal, emit_all should still produce a non-empty list."""
    ap, nidq = _make_sync_times()
    out = emit_all(
        sync_results={"imec0": _make_sync_result("imec0")},
        ap_sync_times_map={"imec0": ap},
        nidq_sync_times=nidq,
        trial_alignment=_make_trial_alignment(),
        calibrated=_make_calibrated(),
        output_dir=tmp_path,
    )
    assert len(out) > 0
    for p in out:
        assert p.exists()
        assert p.stat().st_size > 0


def test_emit_all_with_photodiode(tmp_path: Path) -> None:
    """With pd_signal + sample rate the full photodiode family is produced."""
    ap, nidq = _make_sync_times()
    pd_signal = _make_pd_signal(duration_s=10.0)
    out = emit_all(
        sync_results={"imec0": _make_sync_result("imec0")},
        ap_sync_times_map={"imec0": ap},
        nidq_sync_times=nidq,
        trial_alignment=_make_trial_alignment(),
        calibrated=_make_calibrated(),
        output_dir=tmp_path,
        pd_signal=pd_signal,
        nidq_sample_rate=NIDQ_SR,
        voltage_range=5.0,
    )
    names = {p.name for p in out}
    expected = {
        "photodiode_raw.png",
        "photodiode_diff.png",
        "photodiode_diff_abs.png",
        "photodiode_polarity_corrected.png",
        "photodiode_before_calibration.png",
        "photodiode_after_calibration.png",
        "photodiode_valid_only.png",
        "onset_latency_hist.png",
    }
    assert expected.issubset(names), f"missing photodiode plots: {expected - names}"


def test_emit_all_without_eye_points(tmp_path: Path) -> None:
    """Eye-density plot is skipped when eye_points is None."""
    ap, nidq = _make_sync_times()
    out = emit_all(
        sync_results={"imec0": _make_sync_result("imec0")},
        ap_sync_times_map={"imec0": ap},
        nidq_sync_times=nidq,
        trial_alignment=_make_trial_alignment(),
        calibrated=_make_calibrated(),
        output_dir=tmp_path,
    )
    names = {p.name for p in out}
    assert "eye_density.png" not in names


def test_emit_all_with_eye_points(tmp_path: Path) -> None:
    """Eye-density plot is produced when eye_points is supplied."""
    rng = np.random.RandomState(2)
    eye = rng.randn(500, 2).astype(np.float64) * 2.0
    ap, nidq = _make_sync_times()
    out = emit_all(
        sync_results={"imec0": _make_sync_result("imec0")},
        ap_sync_times_map={"imec0": ap},
        nidq_sync_times=nidq,
        trial_alignment=_make_trial_alignment(),
        calibrated=_make_calibrated(),
        output_dir=tmp_path,
        eye_points=eye,
    )
    names = {p.name for p in out}
    assert "eye_density.png" in names


def test_individual_plot_failure_does_not_abort(tmp_path: Path) -> None:
    """A bad input on one plot still lets the rest of the suite run.

    Here we give an empty ``nidq_sync_times`` which breaks the per-probe
    interval + residual plots for imec0, yet the remaining plots (stim
    events, onset latency hist) must still appear.
    """
    ap, _ = _make_sync_times()
    empty_nidq = np.array([], dtype=np.float64)
    out = emit_all(
        sync_results={"imec0": _make_sync_result("imec0")},
        ap_sync_times_map={"imec0": ap},
        nidq_sync_times=empty_nidq,
        trial_alignment=_make_trial_alignment(),
        calibrated=_make_calibrated(),
        output_dir=tmp_path,
    )
    names = {p.name for p in out}
    # Failing plots produced nothing:
    assert "sync_intervals_imec0.png" not in names
    # Independent plots still succeeded:
    assert "stim_events_per_trial.png" in names
    assert "onset_latency_hist.png" in names


def test_pngs_open_with_pil(tmp_path: Path) -> None:
    """Every returned PNG must be a valid image parseable by PIL."""
    ap, nidq = _make_sync_times()
    out = emit_all(
        sync_results={"imec0": _make_sync_result("imec0")},
        ap_sync_times_map={"imec0": ap},
        nidq_sync_times=nidq,
        trial_alignment=_make_trial_alignment(),
        calibrated=_make_calibrated(),
        output_dir=tmp_path,
    )
    assert out  # non-empty
    for p in out:
        with Image.open(p) as img:
            img.verify()  # raises on corrupt PNG


# ---------------------------------------------------------------------------
# V.6 — Photodiode trial matrix must use trigger-aligned onsets and
# after_calibration realignment must shift by -latency, not +latency.
# Regression guard for docs/todo.md V.6 double-correction bug.
# ---------------------------------------------------------------------------


def test_build_pd_trial_matrix_trigger_aligned_step_location() -> None:
    """With align_to='trigger' and onsets at trigger time, the PD step appears
    at t = +latency in the extracted matrix (not at t=0)."""
    from pynpxpipe.plots.sync import _build_pd_trial_matrix

    sr = 25_000.0
    # One trial with trigger at 1.0s, PD step at 1.015s (latency = 15ms).
    trigger_s = np.array([1.0])
    step_sample = int(1.015 * sr)
    n = int(3.0 * sr)
    signal = np.zeros(n, dtype=np.int16)
    signal[step_sample:] = 10_000  # step up to ~1.5V at t=1.015s

    raw, time_ms, _polarity = _build_pd_trial_matrix(
        pd_signal=signal,
        nidq_sample_rate=sr,
        voltage_range=5.0,
        stim_onset_nidq_s=trigger_s,
        pre_ms=20.0,
        post_ms=60.0,
        align_to="trigger",
    )
    # Step is in the signal itself at +15ms relative to trigger-aligned t=0.
    # In z-scored units, the transition should land near time_ms ≈ 15ms.
    assert raw.shape == (1, int(80 / 1000 * sr))
    # Locate the largest forward jump in the diff.
    diff_peak_idx = int(np.argmax(np.diff(raw[0])))
    t_peak_ms = float(time_ms[diff_peak_idx])
    assert 13.0 <= t_peak_ms <= 17.0, f"step should be near +15ms, got {t_peak_ms:.2f}ms"


def test_build_pd_trial_matrix_calibrated_aligned_step_at_zero() -> None:
    """With align_to='calibrated' and onsets at PD-bright time, the step is at t≈0."""
    from pynpxpipe.plots.sync import _build_pd_trial_matrix

    sr = 25_000.0
    # Calibrated onset = actual PD bright time = 1.015s.
    calibrated_s = np.array([1.015])
    step_sample = int(1.015 * sr)
    n = int(3.0 * sr)
    signal = np.zeros(n, dtype=np.int16)
    signal[step_sample:] = 10_000

    raw, time_ms, _polarity = _build_pd_trial_matrix(
        pd_signal=signal,
        nidq_sample_rate=sr,
        voltage_range=5.0,
        stim_onset_nidq_s=calibrated_s,
        pre_ms=20.0,
        post_ms=60.0,
        align_to="calibrated",
    )
    diff_peak_idx = int(np.argmax(np.diff(raw[0])))
    t_peak_ms = float(time_ms[diff_peak_idx])
    # Step should be near t=0 in calibrated mode.
    assert -2.0 <= t_peak_ms <= 2.0, f"step should be near 0ms, got {t_peak_ms:.2f}ms"


def test_realign_by_latency_shifts_step_to_zero() -> None:
    """After realignment by latency, a trigger-aligned matrix with a step at
    t=+lat should have the step land at t=0."""
    from pynpxpipe.plots.sync import _realign_by_latency

    # Trigger-aligned matrix: 1 trial, step at sample index where t=+15ms.
    pre_ms, post_ms = 20.0, 60.0
    n_samples = 80  # 1ms per sample for easy bookkeeping
    time_ms = np.linspace(-pre_ms, post_ms, n_samples, endpoint=False)
    step_idx = int(np.searchsorted(time_ms, 15.0))
    matrix = np.zeros((1, n_samples), dtype=np.float64)
    matrix[0, step_idx:] = 1.0
    latency_ms = np.array([15.0])

    aligned = _realign_by_latency(matrix, time_ms, latency_ms)
    # After shift, step should be near t=0. Mask the nan tail (rows where
    # interp hit the right edge) before argmax so it doesn't latch onto the
    # 1→nan boundary.
    diff_arr = np.diff(aligned[0])
    finite = np.isfinite(diff_arr)
    masked = np.where(finite, diff_arr, -np.inf)
    diff_peak_idx = int(np.argmax(masked))
    t_peak_ms = float(time_ms[diff_peak_idx])
    assert -2.0 <= t_peak_ms <= 2.0, f"step should land at 0ms, got {t_peak_ms:.2f}ms"


def test_emit_all_builds_pd_matrix_twice_with_different_align_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """emit_all must call _build_pd_trial_matrix twice:

    1. ``align_to="trigger"`` with ``trial_alignment.stim_onset_nidq_s`` for
       the raster / before-calibration family (rows aligned on event-code
       rising edges; PD step appears at ``t ≈ +latency``).
    2. ``align_to="calibrated"`` with ``calibrated.stim_onset_nidq_s`` for
       ``_plot_photodiode_after_calibration`` (rows re-sliced around the
       PD-bright time; step at ``t ≈ 0``, MATLAB L220-225 behavior).

    Double-correction regression (docs/todo.md V.6): trigger onsets must
    *only* feed the trigger-aligned family, calibrated onsets must *only*
    feed the after-calibration plot — never crossed.
    """
    import pynpxpipe.plots.sync as sync_mod

    calls: list[dict] = []
    real_fn = sync_mod._build_pd_trial_matrix

    def spy(*args, **kwargs):
        calls.append(
            {
                "stim_onset_nidq_s": kwargs.get("stim_onset_nidq_s"),
                "align_to": kwargs.get("align_to"),
            }
        )
        return real_fn(*args, **kwargs)

    monkeypatch.setattr(sync_mod, "_build_pd_trial_matrix", spy)

    ap, nidq = _make_sync_times()
    trial_align = _make_trial_alignment()
    calibrated = _make_calibrated()
    pd_signal = _make_pd_signal(duration_s=10.0)

    emit_all(
        sync_results={"imec0": _make_sync_result("imec0")},
        ap_sync_times_map={"imec0": ap},
        nidq_sync_times=nidq,
        trial_alignment=trial_align,
        calibrated=calibrated,
        output_dir=tmp_path,
        pd_signal=pd_signal,
        nidq_sample_rate=NIDQ_SR,
        voltage_range=5.0,
    )
    modes = [c["align_to"] for c in calls]
    assert "trigger" in modes, f"expected a trigger-aligned call, got {modes}"
    assert "calibrated" in modes, f"expected a calibrated-aligned call, got {modes}"

    trig_onsets = trial_align.trial_events_df["stim_onset_nidq_s"].to_numpy()
    cal_onsets = calibrated.stim_onset_nidq_s
    trigger_call = next(c for c in calls if c["align_to"] == "trigger")
    calibrated_call = next(c for c in calls if c["align_to"] == "calibrated")
    np.testing.assert_allclose(trigger_call["stim_onset_nidq_s"], trig_onsets)
    np.testing.assert_allclose(calibrated_call["stim_onset_nidq_s"], cal_onsets)


def test_plot_photodiode_after_calibration_matches_matlab_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After-calibration plot must reproduce MATLAB L220-225 behavior:

    - Re-slice raw ``pd_signal`` around each trial's *calibrated* onset.
    - Re-run per-trial z-score + polarity correction.
    - Average across trials.

    The resulting mean curve has a negative baseline (t<0) and a positive
    plateau (t>0), with the transition centered at t=0, because each window
    is pre-registered on the PD bright edge. This is the regression against
    the earlier implementation, which only interpolated a trigger-aligned
    matrix (``_realign_by_latency``) and therefore produced a shape that
    did not match the MATLAB "After time calibration" figure.
    """
    import pynpxpipe.plots.sync as sync_mod

    sr = 25_000.0
    # 3 trials: each has a clean rising step at its calibrated onset.
    onsets = np.array([0.5, 1.5, 2.5])
    n = int(3.5 * sr)
    signal = np.zeros(n, dtype=np.int16)
    for t in onsets:
        signal[int(t * sr) :] = 10_000  # step up and stays high
        # Reset to zero for the next pre-onset baseline (clean synthetic).
        if t != onsets[-1]:
            next_t = float(onsets[onsets > t][0])
            gap = int(next_t * sr) - int((t + 0.15) * sr)
            if gap > 0:
                signal[int((t + 0.15) * sr) : int(next_t * sr)] = 0

    captured: dict = {}
    real_band = sync_mod._plot_photodiode_band

    def capture_band(**kwargs):
        captured["matrix"] = kwargs["matrix"]
        captured["time_ms"] = kwargs["time_ms"]
        captured["title_stub"] = kwargs["title_stub"]
        return real_band(**kwargs)

    monkeypatch.setattr(sync_mod, "_plot_photodiode_band", capture_band)

    sync_mod._plot_photodiode_after_calibration(
        pd_signal=signal,
        nidq_sample_rate=sr,
        voltage_range=5.0,
        calibrated_onsets_nidq_s=onsets,
        pre_ms=10.0,
        post_ms=100.0,
        output_dir=tmp_path,
        session_label="test",
    )

    matrix = captured["matrix"]
    time_ms = captured["time_ms"]
    assert matrix.shape[0] == len(onsets)
    mean_curve = np.nanmean(matrix, axis=0)
    baseline = mean_curve[time_ms < -1.0]
    plateau = mean_curve[time_ms > 5.0]
    # MATLAB-shape invariants: baseline is clearly negative, plateau positive.
    assert float(np.nanmean(baseline)) < -1.0, (
        f"baseline should be clearly negative (<-1), got {float(np.nanmean(baseline)):.3f}"
    )
    assert float(np.nanmean(plateau)) > 0.1, (
        f"plateau should be positive (>0.1), got {float(np.nanmean(plateau)):.3f}"
    )
    # Output file exists and is non-empty.
    out_path = tmp_path / "photodiode_after_calibration.png"
    assert out_path.exists()
    assert out_path.stat().st_size > 0


def test_sync_intervals_title_contains_probe_id(tmp_path: Path) -> None:
    """Generated file names must embed the probe_id."""
    ap, nidq = _make_sync_times()
    out = emit_all(
        sync_results={
            "imec0": _make_sync_result("imec0"),
            "imec1": _make_sync_result("imec1"),
        },
        ap_sync_times_map={"imec0": ap, "imec1": ap},
        nidq_sync_times=nidq,
        trial_alignment=_make_trial_alignment(),
        calibrated=_make_calibrated(),
        output_dir=tmp_path,
    )
    names = {p.name for p in out}
    assert "sync_intervals_imec0.png" in names
    assert "sync_intervals_imec1.png" in names
    assert "sync_residuals_imec0.png" in names
    assert "sync_residuals_imec1.png" in names


def test_emit_all_raises_without_matplotlib(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When matplotlib is unavailable, emit_all raises a clear RuntimeError."""
    import pynpxpipe.plots.sync as sync_module

    monkeypatch.setattr(sync_module, "plt", None)
    ap, nidq = _make_sync_times()
    with pytest.raises(RuntimeError, match="matplotlib"):
        emit_all(
            sync_results={"imec0": _make_sync_result("imec0")},
            ap_sync_times_map={"imec0": ap},
            nidq_sync_times=nidq,
            trial_alignment=_make_trial_alignment(),
            calibrated=_make_calibrated(),
            output_dir=tmp_path,
        )
