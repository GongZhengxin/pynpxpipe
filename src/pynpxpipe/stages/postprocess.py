"""Postprocess stage: full SortingAnalyzer computation and SLAY scoring.

Computes waveforms, templates, unit locations, and SLAY scores per probe.
No UI dependencies.
"""

from __future__ import annotations

import gc
import json
import math
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import spikeinterface.core as si
from scipy.stats import spearmanr

from pynpxpipe.core.errors import PostprocessError
from pynpxpipe.io.bhv import BHV2Parser
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


def _halve_chunk_duration(chunk_duration: str) -> str:
    """Halve a chunk_duration string (e.g. '1s' → '0.5s', 'auto' → '0.5s')."""
    if chunk_duration == "auto":
        return "0.5s"
    value = float(chunk_duration.rstrip("s"))
    halved = value / 2
    if halved == int(halved):
        return f"{int(halved)}s"
    return f"{halved}s"


class PostprocessStage(BaseStage):
    """Computes SortingAnalyzer extensions and SLAY scores for each probe.

    Extension sequence: random_spikes → waveforms → templates →
    unit_locations → template_similarity.

    OOM handling: if waveform extraction runs out of memory, chunk_duration
    is halved and retried once. Still OOM → PostprocessError.

    SLAY: trial-to-trial Spearman correlation of spike rate vectors.
    Quantifies response reliability: 1.0 = perfect consistency,
    0.0 = random. Returns NaN if fewer than 5 qualifying trials.

    Eye validation (optional): reads BHV2 analog eye channel per trial
    (chunked, no pre-allocated 3D matrix), updates trial_valid column.
    """

    STAGE_NAME = "postprocess"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        super().__init__(session, progress_callback)

    def run(self) -> None:
        """Compute all postprocessing extensions for all probes serially.

        Raises:
            PostprocessError: If waveform extraction OOM cannot be resolved by
                halving chunk_duration.
        """
        if self._is_complete():
            return

        behavior_events_path = self.session.output_dir / "sync" / "behavior_events.parquet"
        behavior_events_df = pd.read_parquet(behavior_events_path)

        self._report_progress("Starting postprocess", 0.0)

        n_probes = len(self.session.probes)
        for i, probe in enumerate(self.session.probes):
            self._postprocess_probe(probe.probe_id, behavior_events_df)
            self._report_progress(
                f"Postprocessed {probe.probe_id}",
                0.1 + 0.8 * (i + 1) / n_probes,
            )

        eye_cfg = self.session.config.postprocess.eye_validation
        if eye_cfg.enabled:
            self._run_eye_validation(behavior_events_df)

        self._write_checkpoint({"n_probes": n_probes})
        self._report_progress("Postprocess complete", 1.0)

    def _postprocess_probe(self, probe_id: str, behavior_events_df: pd.DataFrame) -> None:
        """Full postprocessing for one probe.

        Args:
            probe_id: Probe identifier.
            behavior_events_df: Trial events DataFrame from synchronize stage.

        Raises:
            PostprocessError: If OOM cannot be resolved by halving chunk_duration.
        """
        if self._is_complete(probe_id):
            return

        cfg = self.session.config
        n_jobs = cfg.resources.n_jobs
        chunk_duration = cfg.resources.chunk_duration
        slay_pre_s = cfg.postprocess.slay_pre_s
        slay_post_s = cfg.postprocess.slay_post_s

        # Load resources
        curated_dir = self.session.output_dir / "curated" / probe_id
        preprocessed_dir = self.session.output_dir / "preprocessed" / probe_id
        sorting = si.load(curated_dir)
        recording = si.load(preprocessed_dir)

        # Create SortingAnalyzer (binary_folder, written to disk)
        output_dir = self.session.output_dir / "postprocessed" / probe_id
        analyzer = si.create_sorting_analyzer(
            sorting,
            recording,
            format="binary_folder",
            folder=output_dir,
            sparse=True,
        )

        # Compute extensions in required order
        analyzer.compute("random_spikes")

        # Waveforms with OOM retry
        try:
            analyzer.compute("waveforms", chunk_duration=chunk_duration, n_jobs=n_jobs)
        except MemoryError:
            reduced = _halve_chunk_duration(chunk_duration)
            self.logger.warning(
                "MemoryError on waveforms, retrying with chunk_duration=%s", reduced
            )
            try:
                analyzer.compute("waveforms", chunk_duration=reduced, n_jobs=n_jobs)
            except MemoryError as exc:
                raise PostprocessError(f"OOM on waveforms even with {reduced}: {exc}") from exc

        analyzer.compute("templates")
        analyzer.compute("unit_locations")
        analyzer.compute("template_similarity")

        # Compute SLAY scores
        unit_ids = analyzer.sorting.get_unit_ids()
        fs = float(analyzer.sorting.get_sampling_frequency())

        # Parse per-probe stim onset times from JSON column
        stim_times: list[float] = []
        for val in behavior_events_df["stim_onset_imec_s"]:
            parsed = json.loads(val)
            stim_times.append(float(parsed.get(probe_id, float("nan"))))
        stim_onset_times = np.array(stim_times, dtype=float)

        slay_scores: dict[str, float] = {}
        for uid in unit_ids:
            spike_samples = analyzer.sorting.get_unit_spike_train(uid, segment_index=0)
            spike_times_s = np.asarray(spike_samples, dtype=float) / fs
            slay_scores[str(uid)] = self._compute_slay(
                spike_times_s, stim_onset_times, slay_pre_s, slay_post_s
            )

        # Write slay_scores.json (NaN serialised as null)
        output_dir.mkdir(parents=True, exist_ok=True)
        serializable = {k: (None if math.isnan(v) else v) for k, v in slay_scores.items()}
        slay_path = output_dir / "slay_scores.json"
        slay_path.write_text(json.dumps(serializable), encoding="utf-8")

        # Write per-probe checkpoint
        finite_scores = [v for v in slay_scores.values() if not math.isnan(v)]
        slay_mean = float(np.mean(finite_scores)) if finite_scores else float("nan")
        self._write_checkpoint(
            {
                "probe_id": probe_id,
                "n_units": len(unit_ids),
                "slay_mean": slay_mean if not math.isnan(slay_mean) else None,
                "slay_nan_count": len(slay_scores) - len(finite_scores),
                "analyzer_path": str(output_dir),
            },
            probe_id=probe_id,
        )

        del analyzer, sorting, recording
        gc.collect()

    def _compute_slay(
        self,
        spike_times: np.ndarray,
        stim_onset_times: np.ndarray,
        pre_s: float = 0.05,
        post_s: float = 0.30,
    ) -> float:
        """Compute SLAY score for a single unit.

        Returns:
            Float in [0, 1], or np.nan if fewer than 5 valid trials or
            the unit has an inhibitory / absent response.
        """
        # Step 1: filter valid onsets
        valid_onsets = stim_onset_times[~np.isnan(stim_onset_times)]

        # Step 2: check minimum trial count
        if len(valid_onsets) < 5:
            return float("nan")

        # Step 3: bin the window (10 ms bins)
        n_bins = int((pre_s + post_s) / 0.01)
        pre_bins = int(pre_s / 0.01)

        # Step 4: build per-trial spike count vectors
        trial_vectors = []
        for onset in valid_onsets:
            window_start = onset - pre_s
            window_end = onset + post_s
            spikes_in = spike_times[(spike_times >= window_start) & (spike_times < window_end)]
            counts, _ = np.histogram(
                spikes_in - window_start,
                bins=n_bins,
                range=(0, pre_s + post_s),
            )
            trial_vectors.append(counts)
        trial_mat = np.array(trial_vectors)  # (n_trials, n_bins)

        # Step 5: pairwise Spearman correlations
        correlations: list[float] = []
        n_trials = len(trial_mat)
        for i in range(n_trials):
            for j in range(i + 1, n_trials):
                corr, _ = spearmanr(trial_mat[i], trial_mat[j])
                if not np.isnan(corr):
                    correlations.append(float(corr))

        # Step 6: direction filter — exclude inhibitory/absent responses
        baseline_rate = trial_mat[:, :pre_bins].mean(axis=1)
        response_rate = trial_mat[:, pre_bins:].mean(axis=1)
        if response_rate.mean() <= baseline_rate.mean():
            return float("nan")

        # Step 7: return mean correlation
        if not correlations:
            return float("nan")
        return float(np.mean(correlations))

    def _run_eye_validation(self, behavior_events_df: pd.DataFrame) -> pd.DataFrame:
        """Validate trials by fixation ratio and update trial_valid column.

        Reads eye analog data from BHV2 per trial (no 3D pre-allocation).
        """
        eye_cfg = self.session.config.postprocess.eye_validation
        parser = BHV2Parser(self.session.bhv_file)
        eye_data = parser.get_analog_data("Eye")

        fixation_window = 50.0  # default pixels/degrees
        trial_valid = behavior_events_df["trial_valid"].copy()
        trial_ids = behavior_events_df["trial_id"].tolist()

        for idx, tid in enumerate(trial_ids):
            if tid not in eye_data:
                continue
            data = eye_data[tid]
            if data.ndim == 1:
                data = data.reshape(-1, 1)
            if data.shape[1] >= 2:
                dist = np.sqrt(data[:, 0] ** 2 + data[:, 1] ** 2)
            else:
                dist = np.abs(data[:, 0])
            ratio = float(np.sum(dist < fixation_window) / len(dist))
            trial_valid.iloc[idx] = 1.0 if ratio > eye_cfg.eye_threshold else 0.0

        result = behavior_events_df.copy()
        result["trial_valid"] = trial_valid
        parquet_path = self.session.output_dir / "sync" / "behavior_events.parquet"
        result.to_parquet(parquet_path)
        return result
