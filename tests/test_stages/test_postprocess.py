"""Tests for stages/postprocess.py — PostprocessStage.

Groups:
  A. _compute_slay  — 10 unit tests for the SLAY algorithm
  B. Normal flow    — SortingAnalyzer, extensions, SLAY json, checkpoint
  C. OOM retry      — waveforms MemoryError with halved chunk retry
  D. Checkpoint skip — per-probe and stage level
  E. Eye validation  — enabled/disabled
  F. SLAY JSON      — keys and values
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from pynpxpipe.core.config import (
    EyeValidationConfig,
    PipelineConfig,
    PostprocessConfig,
    ResourcesConfig,
)
from pynpxpipe.core.errors import PostprocessError
from pynpxpipe.core.session import ProbeInfo, Session, SessionManager, SubjectConfig
from pynpxpipe.stages.postprocess import PostprocessStage

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_subject() -> SubjectConfig:
    return SubjectConfig(
        subject_id="TestMon",
        description="test monkey",
        species="Macaca mulatta",
        sex="M",
        age="P3Y",
        weight="10kg",
    )


def _make_probe(probe_id: str, base: Path) -> ProbeInfo:
    target_area = "V4" if probe_id == "imec0" else "IT"
    return ProbeInfo(
        probe_id=probe_id,
        ap_bin=base / f"{probe_id}.ap.bin",
        ap_meta=base / f"{probe_id}.ap.meta",
        lf_bin=None,
        lf_meta=None,
        sample_rate=30000.0,
        n_channels=384,
        serial_number="SN_TEST",
        probe_type="NP1010",
        target_area=target_area,
    )


def _make_behavior_events(output_dir: Path, probe_id: str = "imec0", n_trials: int = 10) -> Path:
    """Create behavior_events.parquet under output_dir/sync/."""
    onsets = [float(i + 1) for i in range(n_trials)]
    # stim_onset_imec_s is a JSON-encoded dict per trial
    imec_s = [json.dumps({probe_id: t + 0.001}) for t in onsets]
    df = pd.DataFrame(
        {
            "trial_id": list(range(n_trials)),
            "onset_nidq_s": onsets,
            "stim_onset_nidq_s": [t + 0.01 for t in onsets],
            "stim_onset_imec_s": imec_s,
            "condition_id": [1] * n_trials,
            "trial_valid": [1.0] * n_trials,
        }
    )
    sync_dir = output_dir / "04_sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = sync_dir / "behavior_events.parquet"
    df.to_parquet(parquet_path)
    return parquet_path


def _make_config(
    n_jobs: int = 1,
    chunk_duration: str = "1s",
    slay_pre_s: float = 0.05,
    slay_post_s: float = 0.30,
    eye_enabled: bool = False,  # default disabled to avoid BHV2 in most tests
    eye_threshold: float = 0.999,
) -> PipelineConfig:
    return PipelineConfig(
        resources=ResourcesConfig(n_jobs=n_jobs, chunk_duration=chunk_duration),
        postprocess=PostprocessConfig(
            slay_pre_s=slay_pre_s,
            slay_post_s=slay_post_s,
            eye_validation=EyeValidationConfig(enabled=eye_enabled, eye_threshold=eye_threshold),
        ),
    )


def _write_completed_checkpoint(session: Session, stage: str, probe_id: str | None = None) -> None:
    filename = f"{stage}.json" if probe_id is None else f"{stage}_{probe_id}.json"
    cp_dir = session.output_dir / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    cp_path = cp_dir / filename
    cp_path.write_text(json.dumps({"stage": stage, "status": "completed"}), encoding="utf-8")


def _make_mock_sorting(unit_ids: list[str], fs: float = 30000.0) -> MagicMock:
    """Mock sorting with synthetic spike trains (one spike per unit at t=0.1s)."""
    mock = MagicMock()
    mock.get_unit_ids.return_value = unit_ids
    mock.get_sampling_frequency.return_value = fs
    # Default spike train: single spike at sample 3000 (0.1s at 30kHz)
    mock.get_unit_spike_train.return_value = np.array([3000])
    return mock


def _make_mock_analyzer(unit_ids: list[str]) -> MagicMock:
    mock = MagicMock()
    mock_sorting = _make_mock_sorting(unit_ids)
    mock.sorting = mock_sorting
    return mock


def _mock_si_load(unit_ids: list[str]):
    """Return a side_effect for si.load that gives a proper sorting mock for curated paths."""
    mock_sorting = _make_mock_sorting(unit_ids)

    def _load(path):
        if "05_curated" in str(path):
            return mock_sorting
        return MagicMock()

    return _load


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Session with two probes and behavior_events.parquet written."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(
        session_dir,
        bhv_file,
        _make_subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4", "imec1": "IT"},
        date="240101",
    )
    s.probes = [_make_probe("imec0", tmp_path), _make_probe("imec1", tmp_path)]
    s.config = _make_config()
    _make_behavior_events(output_dir, probe_id="imec0")
    return s


@pytest.fixture
def single_session(tmp_path: Path) -> Session:
    """Session with one probe and behavior_events.parquet written."""
    session_dir = tmp_path / "session_g0"
    session_dir.mkdir()
    bhv_file = tmp_path / "test.bhv2"
    bhv_file.write_bytes(b"\x00" * 30)
    output_dir = tmp_path / "output"
    s = SessionManager.create(
        session_dir,
        bhv_file,
        _make_subject(),
        output_dir,
        experiment="nsd1w",
        probe_plan={"imec0": "V4"},
        date="240101",
    )
    s.probes = [_make_probe("imec0", tmp_path)]
    s.config = _make_config()
    _make_behavior_events(output_dir, probe_id="imec0")
    return s


@pytest.fixture
def stage(single_session: Session) -> PostprocessStage:
    """Minimal PostprocessStage for _compute_slay unit tests."""
    return PostprocessStage(single_session)


# ---------------------------------------------------------------------------
# Group A — _compute_slay unit tests
# ---------------------------------------------------------------------------


class TestComputeSlay:
    def test_slay_identical_trials_returns_one(self, stage: PostprocessStage) -> None:
        """All trials have identical spike count vectors → Spearman r = 1.0."""
        # Use onset + 0.095 so offset from window_start = 0.145, clearly mid-bin 14
        # (avoids bin-boundary floating-point ambiguity that 0.10 + 0.05 = 0.15 causes)
        onsets = np.arange(1.0, 11.0, 1.0)
        spike_times = onsets + 0.095
        result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)
        assert result == pytest.approx(1.0, abs=1e-9)

    def test_slay_nan_if_fewer_than_5_trials(self, stage: PostprocessStage) -> None:
        """Only 3 valid onsets → return np.nan."""
        onsets = np.array([1.0, 2.0, 3.0])
        spike_times = onsets + 0.1
        result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)
        assert math.isnan(result)

    def test_slay_nan_onset_excluded(self, stage: PostprocessStage) -> None:
        """3 NaN onsets + 2 valid → only 2 valid → np.nan."""
        onsets = np.array([np.nan, np.nan, np.nan, 4.0, 5.0])
        spike_times = np.array([4.1, 5.1])
        result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)
        assert math.isnan(result)

    def test_slay_range_zero_to_one(self, stage: PostprocessStage) -> None:
        """Result for normal excitatory input is in [0.0, 1.0]."""
        onsets = np.arange(1.0, 11.0, 1.0)
        # Spikes at different positions in response window per trial → corr in [0,1]
        spike_times = np.array([1.1, 2.15, 3.12, 4.18, 5.1, 6.15, 7.12, 8.18, 9.1, 10.15])
        result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)
        assert not math.isnan(result)
        assert 0.0 <= result <= 1.0

    def test_slay_pre_post_window_from_params(self, stage: PostprocessStage) -> None:
        """Custom pre_s=0.1, post_s=0.5 uses 60-bin window correctly."""
        onsets = np.arange(1.0, 11.0, 1.0)
        # offset = 0.195 + 0.1 = 0.295 from window_start → bin 29 (mid-bin, avoids boundary at 0.30)
        spike_times = onsets + 0.195
        result = stage._compute_slay(spike_times, onsets, pre_s=0.1, post_s=0.5)
        # All trials identical → r = 1.0
        assert result == pytest.approx(1.0, abs=1e-9)

    def test_slay_bin_size_10ms(self, stage: PostprocessStage) -> None:
        """n_bins = int((pre_s + post_s) / 0.01) = 35 for pre=0.05, post=0.30."""
        # If bins are not 10ms, a spike at 0.1s from onset lands in different bin
        # We test indirectly: identical trials → r=1.0 regardless of n_bins
        onsets = np.arange(1.0, 11.0, 1.0)
        spike_times = onsets + 0.1
        result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)
        assert not math.isnan(result)
        # A 10ms bin at 0.1s from onset means bin_idx = 10 (in response window)
        # spike at 0.1s → pre_s/bin_size = 5 pre bins; response starts at bin 5
        # bin(0.1s) = int(0.1/0.01) = 10 ≥ 5 → response bin ✓

    def test_slay_inhibitory_response_returns_nan(self, stage: PostprocessStage) -> None:
        """mean(response) <= mean(baseline) → return np.nan (direction filter)."""
        onsets = np.arange(1.0, 11.0, 1.0)
        # Spike 0.02s before each onset → in baseline window (0-pre_s from window start)
        # Window start = onset - pre_s = onset - 0.05
        # Spike at onset - 0.02 = window_start + 0.03 → bin 3 < pre_bins=5
        spike_times = onsets - 0.02
        result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)
        assert math.isnan(result)

    def test_slay_excitatory_response_passes(self, stage: PostprocessStage) -> None:
        """mean(response) > mean(baseline) → direction check passes, returns float."""
        onsets = np.arange(1.0, 11.0, 1.0)
        spike_times = onsets + 0.1  # clearly in response window
        result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)
        assert not math.isnan(result)
        assert isinstance(result, float)

    def test_slay_equal_response_baseline_returns_nan(self, stage: PostprocessStage) -> None:
        """No spikes at all → both baseline and response = 0 → <= → return np.nan."""
        onsets = np.arange(1.0, 11.0, 1.0)
        spike_times = np.array([])  # no spikes
        result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)
        assert math.isnan(result)

    def test_slay_uncorrelated_trials_near_zero(self, stage: PostprocessStage) -> None:
        """Alternating spike patterns produce correlation < 1.0."""
        onsets = np.arange(1.0, 11.0, 1.0)
        # Even trials: spike at +0.1s; odd trials: spike at +0.25s
        spike_times = np.array([o + (0.1 if i % 2 == 0 else 0.25) for i, o in enumerate(onsets)])
        result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)
        # Not nan (response > baseline) and not 1.0 (not identical)
        assert not math.isnan(result)
        assert result < 1.0

    def test_slay_no_constant_input_warning(self, stage: PostprocessStage) -> None:
        """Mixing silent trials with active ones must not emit ConstantInputWarning.

        The vectorised implementation drops zero-variance rows before calling
        np.corrcoef; scipy's ConstantInputWarning should never reach the user.
        """
        import warnings as _warnings

        onsets = np.arange(1.0, 11.0, 1.0)
        # Trials 0, 2, 4 silent; trials 1, 3, 5, 6, 7, 8, 9 have a spike.
        spike_times = np.array([o + 0.1 for i, o in enumerate(onsets) if i % 2 == 1])

        with _warnings.catch_warnings(record=True) as caught:
            _warnings.simplefilter("always")
            result = stage._compute_slay(spike_times, onsets, pre_s=0.05, post_s=0.30)

        messages = [str(w.message) for w in caught]
        assert not any("constant" in m.lower() for m in messages), messages
        # Should still produce a defined score from the non-constant rows.
        assert not math.isnan(result)


# ---------------------------------------------------------------------------
# Group B — Normal flow
# ---------------------------------------------------------------------------


class TestNormalFlow:
    def test_run_postprocesses_all_probes(self, session: Session) -> None:
        """si.create_sorting_analyzer is called once for each probe (2 probes)."""
        unit_ids = ["u0", "u1"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch(
                "pynpxpipe.stages.postprocess.si.load",
                side_effect=_mock_si_load(unit_ids),
            ),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ) as mock_create,
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(session).run()

        assert mock_create.call_count == 2

    def test_analyzer_saved_to_binary_folder(self, single_session: Session) -> None:
        """create_sorting_analyzer is called with format='binary_folder' and correct folder."""
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ) as mock_create,
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        kwargs = mock_create.call_args.kwargs
        assert kwargs.get("format") == "binary_folder"
        assert "imec0" in str(kwargs.get("folder", ""))

    def test_slay_scores_json_written(self, single_session: Session) -> None:
        """slay_scores.json is created in the postprocessed/imec0/ directory."""
        unit_ids = ["u0", "u1"]
        mock_analyzer = _make_mock_analyzer(unit_ids)
        # Ensure postprocessed dir is created for slay json
        postprocessed_dir = single_session.output_dir / "06_postprocessed" / "imec0"

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        slay_path = postprocessed_dir / "slay_scores.json"
        assert slay_path.exists()

    def test_probe_checkpoint_written(self, single_session: Session) -> None:
        """checkpoints/postprocess_imec0.json with status=completed written after probe."""
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        cp = single_session.output_dir / "checkpoints" / "postprocess_imec0.json"
        assert cp.exists()
        data = json.loads(cp.read_text(encoding="utf-8"))
        assert data["status"] == "completed"

    def test_extension_order(self, single_session: Session) -> None:
        """Extensions computed in order: random_spikes→waveforms→templates→unit_locations→template_similarity."""
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        compute_calls = [c.args[0] for c in mock_analyzer.compute.call_args_list]
        expected = [
            "random_spikes",
            "waveforms",
            "templates",
            "unit_locations",
            "template_similarity",
        ]
        assert compute_calls == expected

    def test_analyzer_uses_binary_folder_format(self, single_session: Session) -> None:
        """create_sorting_analyzer format arg is 'binary_folder' (not 'memory')."""
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ) as mock_create,
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        assert mock_create.call_args.kwargs.get("format") == "binary_folder"

    def test_gc_called_after_probe(self, session: Session) -> None:
        """gc.collect() called at least once per probe (2 probes → ≥ 2 calls)."""
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc") as mock_gc,
        ):
            PostprocessStage(session).run()

        assert mock_gc.collect.call_count >= 2


# ---------------------------------------------------------------------------
# Group C — OOM retry
# ---------------------------------------------------------------------------


class TestOomRetry:
    def test_oom_retries_with_halved_chunk(self, single_session: Session) -> None:
        """First waveforms compute raises MemoryError → retried with halved chunk_duration."""
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)
        waveforms_calls: list[dict] = []

        def compute_side_effect(ext_name, **kwargs):
            if ext_name == "waveforms":
                waveforms_calls.append(kwargs)
                if len(waveforms_calls) == 1:
                    raise MemoryError("OOM")

        mock_analyzer.compute.side_effect = compute_side_effect

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        assert len(waveforms_calls) == 2
        # Second call must use a smaller chunk_duration than first
        first_chunk = waveforms_calls[0].get("chunk_duration", "1s")
        second_chunk = waveforms_calls[1].get("chunk_duration", "1s")
        assert second_chunk != first_chunk

    def test_oom_retry_succeeds(self, single_session: Session) -> None:
        """Retry with halved chunk succeeds → no PostprocessError, run() completes."""
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)
        called = [0]

        def compute_side_effect(ext_name, **kwargs):
            if ext_name == "waveforms":
                called[0] += 1
                if called[0] == 1:
                    raise MemoryError("OOM")
            # second call succeeds (no raise)

        mock_analyzer.compute.side_effect = compute_side_effect

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            # Should not raise
            PostprocessStage(single_session).run()

        cp = single_session.output_dir / "checkpoints" / "postprocess_imec0.json"
        assert cp.exists()

    def test_oom_retry_fails_raises_postprocess_error(self, single_session: Session) -> None:
        """Two consecutive MemoryError on waveforms → raise PostprocessError."""
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        def compute_side_effect(ext_name, **kwargs):
            if ext_name == "waveforms":
                raise MemoryError("OOM")

        mock_analyzer.compute.side_effect = compute_side_effect

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
            pytest.raises(PostprocessError),
        ):
            PostprocessStage(single_session).run()


# ---------------------------------------------------------------------------
# Group D — Checkpoint skip
# ---------------------------------------------------------------------------


class TestCheckpointSkip:
    def test_skips_postprocessed_probe(self, session: Session) -> None:
        """imec0 per-probe checkpoint complete → si.load not called for imec0."""
        _write_completed_checkpoint(session, "postprocess", "imec0")
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ) as mock_create,
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(session).run()

        # Only imec1 processed: 2 si.load calls (sorting + recording) and 1 create
        assert mock_create.call_count == 1

    def test_stage_skips_if_complete(self, single_session: Session) -> None:
        """Stage-level checkpoint complete → run() returns immediately, no si.load."""
        _write_completed_checkpoint(single_session, "postprocess")

        with patch("pynpxpipe.stages.postprocess.si.load") as mock_load:
            PostprocessStage(single_session).run()

        mock_load.assert_not_called()


# ---------------------------------------------------------------------------
# Group D2 — Fine-grained checkpoint resume (reuse analyzer + slay_scores)
# ---------------------------------------------------------------------------


def _seed_complete_analyzer_dir(output_dir: Path, probe_id: str) -> Path:
    """Create a fake '06_postprocessed/{probe_id}/extensions/...' layout.

    Just the directory shell — real loading is patched via si.load_sorting_analyzer.
    Mimics what a crashed-after-extensions run would leave behind.
    """
    d = output_dir / "06_postprocessed" / probe_id / "extensions"
    for ext in (
        "random_spikes",
        "waveforms",
        "templates",
        "unit_locations",
        "template_similarity",
    ):
        (d / ext).mkdir(parents=True, exist_ok=True)
    return d.parent


class TestCheckpointResume:
    def test_reuses_existing_analyzer_on_disk(self, single_session: Session) -> None:
        """All 5 extension folders present → load_sorting_analyzer, not create."""
        unit_ids = ["u0"]
        _seed_complete_analyzer_dir(single_session.output_dir, "imec0")
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.load_sorting_analyzer",
                return_value=mock_analyzer,
            ) as mock_load_sa,
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
            ) as mock_create,
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        mock_load_sa.assert_called_once()
        mock_create.assert_not_called()
        # Extensions must NOT be recomputed when analyzer is reused.
        mock_analyzer.compute.assert_not_called()

    def test_creates_analyzer_when_extensions_incomplete(self, single_session: Session) -> None:
        """Only 4 of 5 extension folders → fall back to create_sorting_analyzer."""
        unit_ids = ["u0"]
        base = single_session.output_dir / "06_postprocessed" / "imec0" / "extensions"
        for ext in ("random_spikes", "waveforms", "templates", "unit_locations"):
            (base / ext).mkdir(parents=True, exist_ok=True)
        # intentionally missing: template_similarity
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.load_sorting_analyzer",
            ) as mock_load_sa,
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ) as mock_create,
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        mock_load_sa.assert_not_called()
        mock_create.assert_called_once()

    def test_reuses_existing_slay_json_when_unit_ids_match(self, single_session: Session) -> None:
        """slay_scores.json matches analyzer unit_ids → SLAY loop skipped."""
        unit_ids = ["u0", "u1"]
        _seed_complete_analyzer_dir(single_session.output_dir, "imec0")
        postprocessed_dir = single_session.output_dir / "06_postprocessed" / "imec0"
        # Pre-seed scores that a fresh run could never reproduce from the
        # mock (which has a single spike at t=0.1s → response==baseline==nan).
        preseeded = {
            "u0": {"slay_score": 0.42, "is_visual": True},
            "u1": {"slay_score": None, "is_visual": False},
        }
        postprocessed_dir.mkdir(parents=True, exist_ok=True)
        (postprocessed_dir / "slay_scores.json").write_text(json.dumps(preseeded), encoding="utf-8")

        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.load_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        # After run, the pre-seeded scores survive untouched — a fresh SLAY
        # compute from the mock (single spike at t=0.1s, no stim response)
        # would produce entirely different values, so equality here is
        # proof the hot loop was skipped.
        roundtrip = json.loads((postprocessed_dir / "slay_scores.json").read_text(encoding="utf-8"))
        assert roundtrip == preseeded

    def test_recomputes_slay_when_unit_ids_mismatch(self, single_session: Session) -> None:
        """Stale slay_scores.json (different unit_ids) → recompute."""
        unit_ids = ["u0", "u1"]
        _seed_complete_analyzer_dir(single_session.output_dir, "imec0")
        postprocessed_dir = single_session.output_dir / "06_postprocessed" / "imec0"
        postprocessed_dir.mkdir(parents=True, exist_ok=True)
        stale = {"old_unit_A": {"slay_score": 0.99, "is_visual": True}}
        (postprocessed_dir / "slay_scores.json").write_text(json.dumps(stale), encoding="utf-8")

        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.load_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        # Stale contents overwritten with fresh scores keyed by the current
        # unit ids — proves recompute ran (old 'old_unit_A' key is gone).
        final = json.loads((postprocessed_dir / "slay_scores.json").read_text(encoding="utf-8"))
        assert set(final.keys()) == set(unit_ids)
        assert "old_unit_A" not in final


# ---------------------------------------------------------------------------
# Group E — Eye validation
# ---------------------------------------------------------------------------


class TestEyeValidation:
    def test_eye_validation_updates_trial_valid(self, single_session: Session) -> None:
        """With enabled=True, BHV2Parser.get_analog_data is called and trial_valid updated."""
        single_session.config = _make_config(eye_enabled=True, eye_threshold=0.5)
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        # Eye data: per trial, gaze within fixation window (distance < 1.0)
        # For 10 trials, return small-distance eye signal → ratio should be high
        n_samples = 100
        eye_data = {
            i: np.zeros((n_samples, 2))
            for i in range(10)  # all zeros = distance 0 < any threshold
        }
        mock_parser = MagicMock()
        mock_parser.get_analog_data.return_value = eye_data

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
            patch("pynpxpipe.stages.postprocess.BHV2Parser", return_value=mock_parser),
        ):
            PostprocessStage(single_session).run()

        mock_parser.get_analog_data.assert_called_once_with("Eye")

    def test_eye_validation_skipped_when_disabled(self, single_session: Session) -> None:
        """With enabled=False, BHV2Parser.get_analog_data is not called."""
        single_session.config = _make_config(eye_enabled=False)
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
            patch("pynpxpipe.stages.postprocess.BHV2Parser") as MockParser,
        ):
            PostprocessStage(single_session).run()

        MockParser.assert_not_called()


# ---------------------------------------------------------------------------
# Group F — SLAY JSON content
# ---------------------------------------------------------------------------


class TestSlayJsonContent:
    def test_slay_json_keys_are_unit_ids(self, single_session: Session) -> None:
        """slay_scores.json keys match the unit IDs from the analyzer."""
        unit_ids = ["u0", "u1", "u2"]
        mock_analyzer = _make_mock_analyzer(unit_ids)
        postprocessed_dir = single_session.output_dir / "06_postprocessed" / "imec0"

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        slay_path = postprocessed_dir / "slay_scores.json"
        data = json.loads(slay_path.read_text(encoding="utf-8"))
        assert set(data.keys()) == {"u0", "u1", "u2"}

    def test_slay_json_values_are_floats(self, single_session: Session) -> None:
        """slay_scores.json values are floats (or null for nan)."""
        unit_ids = ["u0"]
        mock_analyzer = _make_mock_analyzer(unit_ids)
        postprocessed_dir = single_session.output_dir / "06_postprocessed" / "imec0"

        with (
            patch("pynpxpipe.stages.postprocess.si.load", side_effect=_mock_si_load(unit_ids)),
            patch(
                "pynpxpipe.stages.postprocess.si.create_sorting_analyzer",
                return_value=mock_analyzer,
            ),
            patch("pynpxpipe.stages.postprocess.gc"),
        ):
            PostprocessStage(single_session).run()

        slay_path = postprocessed_dir / "slay_scores.json"
        data = json.loads(slay_path.read_text(encoding="utf-8"))
        for val in data.values():
            # New format: {slay_score: float|None, is_visual: bool}
            assert isinstance(val, dict)
            assert "slay_score" in val
            assert "is_visual" in val
            assert val["slay_score"] is None or isinstance(val["slay_score"], float)
