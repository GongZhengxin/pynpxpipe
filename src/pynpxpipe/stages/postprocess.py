"""Postprocess stage: full SortingAnalyzer computation and SLAY scoring.

Computes waveforms, templates, unit locations, SLAY scores, and is_visual
flags per probe. No UI dependencies.
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
from scipy.stats import mannwhitneyu, rankdata

from pynpxpipe.core.errors import PostprocessError
from pynpxpipe.io.bhv import BHV2Parser
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pathlib import Path

    from pynpxpipe.core.session import Session


REQUIRED_EXTENSIONS: tuple[str, ...] = (
    "random_spikes",
    "waveforms",
    "templates",
    "unit_locations",
    "template_similarity",
)


def _halve_chunk_duration(chunk_duration: str) -> str:
    """Halve a chunk_duration string (e.g. '1s' → '0.5s', 'auto' → '0.5s')."""
    if chunk_duration == "auto":
        return "0.5s"
    value = float(chunk_duration.rstrip("s"))
    halved = value / 2
    if halved == int(halved):
        return f"{int(halved)}s"
    return f"{halved}s"


def _analyzer_has_all_extensions(output_dir: Path) -> bool:
    """True iff output_dir is a complete SortingAnalyzer binary_folder.

    Checks presence of the extensions subfolder and every entry in
    REQUIRED_EXTENSIONS. Used to decide whether to reuse an existing
    analyzer (resume) or create one fresh (first run / forced recompute).
    """
    ext_dir = output_dir / "extensions"
    if not ext_dir.exists():
        return False
    return all((ext_dir / name).exists() for name in REQUIRED_EXTENSIONS)


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

        behavior_events_path = self.session.output_dir / "04_sync" / "behavior_events.parquet"
        behavior_events_df = pd.read_parquet(behavior_events_path)

        self._report_progress("Starting postprocess", 0.0)
        self._setup_spikeinterface_jobs()

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

        # Dynamic SLAY window: use behavior_events median if columns present
        if (
            "onset_time_ms" in behavior_events_df.columns
            and "offset_time_ms" in behavior_events_df.columns
        ):
            slay_pre_s = cfg.postprocess.pre_onset_ms / 1000.0
            slay_post_s = (
                float(behavior_events_df["onset_time_ms"].median())
                + float(behavior_events_df["offset_time_ms"].median())
            ) / 1000.0
        else:
            slay_pre_s = cfg.postprocess.slay_pre_s
            slay_post_s = cfg.postprocess.slay_post_s

        # Load resources
        curated_dir = self.session.output_dir / "05_curated" / probe_id
        preprocessed_dir = self.session.output_dir / "01_preprocessed" / f"{probe_id}.zarr"
        sorting = si.load(curated_dir)
        recording = si.load(preprocessed_dir)

        # Skip if no units survived curation
        n_units = len(sorting.get_unit_ids())
        if n_units == 0:
            self.logger.warning(
                "Zero units after curation — skipping postprocess", probe_id=probe_id
            )
            output_dir = self.session.output_dir / "06_postprocessed" / probe_id
            output_dir.mkdir(parents=True, exist_ok=True)
            slay_path = output_dir / "slay_scores.json"
            slay_path.write_text("{}", encoding="utf-8")
            self._write_checkpoint(
                {"probe_id": probe_id, "n_units": 0, "slay_mean": None, "slay_nan_count": 0},
                probe_id=probe_id,
            )
            return

        # Create OR reuse SortingAnalyzer.
        #
        # Resume rule: if `06_postprocessed/{probe_id}/extensions/` on disk
        # already carries every REQUIRED_EXTENSIONS, load it instead of
        # overwriting — prevents a mid-SLAY crash from discarding hours of
        # waveform extraction. `create_sorting_analyzer(overwrite=True)`
        # would erase the folder unconditionally.
        output_dir = self.session.output_dir / "06_postprocessed" / probe_id
        slay_path = output_dir / "slay_scores.json"

        if _analyzer_has_all_extensions(output_dir):
            self.logger.info(
                "Reusing existing analyzer with all extensions",
                probe_id=probe_id,
                path=str(output_dir),
            )
            analyzer = si.load_sorting_analyzer(output_dir)
        else:
            analyzer = si.create_sorting_analyzer(
                sorting,
                recording,
                format="binary_folder",
                folder=output_dir,
                sparse=True,
                overwrite=True,
            )

            # Compute extensions in required order
            analyzer.compute("random_spikes")

            # Waveforms with OOM retry
            try:
                analyzer.compute("waveforms")
            except MemoryError:
                chunk_duration = self.session.config.resources.chunk_duration
                reduced = _halve_chunk_duration(chunk_duration)
                self.logger.warning(
                    "MemoryError on waveforms, retrying with chunk_duration=%s", reduced
                )
                si.set_global_job_kwargs(chunk_duration=reduced)
                try:
                    analyzer.compute("waveforms", chunk_duration=reduced)
                except MemoryError as exc:
                    raise PostprocessError(f"OOM on waveforms even with {reduced}: {exc}") from exc

            analyzer.compute("templates")
            analyzer.compute("unit_locations")
            analyzer.compute("template_similarity")

        # Compute OR reload SLAY scores and is_visual flags.
        #
        # Resume rule: if slay_scores.json exists AND its keys match the
        # analyzer's current unit_ids, trust it and skip recomputation.
        # This is the ~Ns-to-minutes hot loop; skipping it makes warm
        # restarts effectively instant.
        unit_ids = analyzer.sorting.get_unit_ids()
        fs = float(analyzer.sorting.get_sampling_frequency())
        unit_id_strs = {str(uid) for uid in unit_ids}

        # Parse per-probe stim onset times — needed for figures even when
        # SLAY scores are loaded from cache
        stim_times: list[float] = []
        for val in behavior_events_df["stim_onset_imec_s"]:
            parsed = json.loads(val)
            stim_times.append(float(parsed.get(probe_id, float("nan"))))
        stim_onset_times = np.array(stim_times, dtype=float)

        cached_scores: dict[str, dict] | None = None
        if slay_path.exists():
            try:
                loaded = json.loads(slay_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and set(loaded.keys()) == unit_id_strs:
                    cached_scores = loaded
            except (json.JSONDecodeError, OSError):
                cached_scores = None

        if cached_scores is not None:
            self.logger.info(
                "Reusing existing slay_scores.json",
                probe_id=probe_id,
                n_units=len(cached_scores),
            )
            unit_scores = cached_scores
        else:
            # {unit_id: {"slay_score": float|None, "is_visual": bool}}
            #
            # Naming note (V.5.2 of docs/todo.md): "slay_score" here is the
            # trial-to-trial Spearman over all-stim-mixed 10ms-binned spike
            # count vectors — it measures stimulus-locked *response
            # consistency*, NOT the SpikeInterface SLAy GNN auto-merger
            # (`spikeinterface.sortingcomponents.merging.slay`) despite the
            # shared acronym. Semantics are documented in
            # `docs/specs/postprocess.md` §"度量语义与命名".
            # TODO(V.5.1): rename to "response_consistency_score" in a
            # dedicated migration session. Blocks: JSON schema of
            # slay_scores.json, NWB units column "slay_score", 10+ tests.
            unit_scores = {}
            for uid in unit_ids:
                spike_samples = analyzer.sorting.get_unit_spike_train(uid, segment_index=0)
                spike_times_s = np.asarray(spike_samples, dtype=float) / fs
                slay_val = self._compute_slay(
                    spike_times_s, stim_onset_times, slay_pre_s, slay_post_s
                )
                is_vis = self._compute_ranksum(
                    spike_times_s, stim_onset_times, slay_pre_s, slay_post_s
                )
                unit_scores[str(uid)] = {
                    "slay_score": None if math.isnan(slay_val) else slay_val,
                    "is_visual": is_vis,
                }

            # Write slay_scores.json
            output_dir.mkdir(parents=True, exist_ok=True)
            slay_path.write_text(json.dumps(unit_scores), encoding="utf-8")

        # Emit diagnostic figures (best-effort; never blocks the pipeline)
        try:
            from pynpxpipe.plots.postprocess import emit_all as _emit_post_plots

            figures_dir = output_dir / "figures"
            _emit_post_plots(
                analyzer=analyzer,
                unit_scores=unit_scores,
                behavior_events_df=behavior_events_df,
                stim_onset_times=stim_onset_times,
                probe_id=probe_id,
                output_dir=figures_dir,
                session_label=self.session.session_id.canonical(),
            )
        except ImportError:
            pass  # matplotlib not installed
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("postprocess figure generation failed: %s", exc)

        # Write per-probe checkpoint
        finite_scores = [
            v["slay_score"] for v in unit_scores.values() if v["slay_score"] is not None
        ]
        slay_mean = float(np.mean(finite_scores)) if finite_scores else float("nan")
        self._write_checkpoint(
            {
                "probe_id": probe_id,
                "n_units": len(unit_ids),
                "slay_mean": slay_mean if not math.isnan(slay_mean) else None,
                "slay_nan_count": len(unit_scores) - len(finite_scores),
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
        trial_mat = np.asarray(trial_vectors, dtype=float)  # (n_trials, n_bins)

        # Step 5: direction filter — exclude inhibitory/absent responses
        # Applied on the full matrix BEFORE the constant-row drop, so a
        # unit that's silent everywhere fails here (baseline == response == 0)
        # instead of surviving via an empty correlation matrix.
        baseline_rate = trial_mat[:, :pre_bins].mean(axis=1)
        response_rate = trial_mat[:, pre_bins:].mean(axis=1)
        if response_rate.mean() <= baseline_rate.mean():
            return float("nan")

        # Step 6: vectorised Spearman.
        # Spearman r between two rows == Pearson r of their ranks. Ranking
        # each row once then feeding the rank matrix to np.corrcoef returns
        # the full n_trials × n_trials correlation matrix in one BLAS call
        # — orders of magnitude faster than O(n²) scipy.stats.spearmanr
        # calls when n_trials is in the hundreds-to-thousands range.
        #
        # Rows with zero variance (e.g. an all-silent trial) would produce
        # NaN correlations AND emit scipy's ConstantInputWarning. Drop them
        # up-front: a constant row carries no rank information and would
        # have been filtered out of the mean anyway.
        row_var = trial_mat.var(axis=1)
        non_constant = trial_mat[row_var > 0]
        if non_constant.shape[0] < 2:
            return float("nan")

        ranks = rankdata(non_constant, axis=1)
        corr_matrix = np.corrcoef(ranks)
        iu = np.triu_indices_from(corr_matrix, k=1)
        corrs = corr_matrix[iu]
        corrs = corrs[~np.isnan(corrs)]
        if corrs.size == 0:
            return float("nan")
        return float(np.mean(corrs))

    def _compute_ranksum(
        self,
        spike_times: np.ndarray,
        stim_onset_times: np.ndarray,
        pre_s: float = 0.05,
        post_s: float = 0.30,
    ) -> bool:
        """Mann-Whitney U test for visual responsiveness.

        Matches legacy data_integrator.py:635-643 _statistical_test.

        Args:
            spike_times: Spike times in seconds (IMEC clock).
            stim_onset_times: Stimulus onset times in seconds.
            pre_s: Pre-stimulus baseline window (seconds).
            post_s: Post-stimulus response window (seconds).

        Returns:
            True if response > baseline AND Mann-Whitney U p < 0.001.
        """
        valid_onsets = stim_onset_times[~np.isnan(stim_onset_times)]
        if len(valid_onsets) < 5:
            return False

        baseline_counts: list[int] = []
        response_counts: list[int] = []
        for onset in valid_onsets:
            baseline = spike_times[(spike_times >= onset - pre_s) & (spike_times < onset)]
            response = spike_times[(spike_times >= onset) & (spike_times < onset + post_s)]
            baseline_counts.append(len(baseline))
            response_counts.append(len(response))

        mean_baseline = float(np.mean(baseline_counts))
        mean_response = float(np.mean(response_counts))
        if mean_response <= mean_baseline:
            return False

        try:
            _, p = mannwhitneyu(baseline_counts, response_counts, alternative="less")
            return bool(p < 0.001)
        except Exception:
            return False

    def _run_eye_validation(self, behavior_events_df: pd.DataFrame) -> pd.DataFrame:
        """Validate per-stimulus fixation and update trial_valid column.

        For each row (= one stimulus presentation), extracts the eye data slice
        during [stim_onset_bhv_ms, stim_onset_bhv_ms + onset_time_ms] within
        the BHV2 trial, and checks whether eye distance from center stays
        within fixation_window degrees.
        """
        eye_cfg = self.session.config.postprocess.eye_validation
        parser = BHV2Parser(self.session.bhv_file)
        eye_data = parser.get_analog_data("Eye")
        sample_interval_ms = parser.get_sample_interval()

        has_stim_onset_bhv = "stim_onset_bhv_ms" in behavior_events_df.columns
        has_onset_time = "onset_time_ms" in behavior_events_df.columns
        has_fix_win = "fixation_window" in behavior_events_df.columns

        trial_valid = behavior_events_df["trial_valid"].copy()

        for idx, row in behavior_events_df.iterrows():
            tid = int(row["trial_id"])
            if tid not in eye_data:
                continue
            data = eye_data[tid]
            if data.ndim == 1:
                data = data.reshape(-1, 1)

            # Compute eye distance from center
            if data.shape[1] >= 2:
                dist = np.sqrt(data[:, 0] ** 2 + data[:, 1] ** 2)
            else:
                dist = np.abs(data[:, 0])

            # Per-stimulus window slicing
            if has_stim_onset_bhv and has_onset_time:
                stim_start_ms = float(row["stim_onset_bhv_ms"])
                onset_ms = float(row["onset_time_ms"])
                if np.isnan(stim_start_ms) or np.isnan(onset_ms):
                    # No stim timing info — validate entire trial
                    window_dist = dist
                else:
                    i_start = int(stim_start_ms / sample_interval_ms)
                    i_end = int((stim_start_ms + onset_ms) / sample_interval_ms)
                    i_start = max(0, min(i_start, len(dist)))
                    i_end = max(i_start, min(i_end, len(dist)))
                    window_dist = dist[i_start:i_end] if i_end > i_start else dist
            else:
                # Legacy path: validate entire trial
                window_dist = dist

            fix_win = float(row["fixation_window"]) if has_fix_win else 5.0
            if len(window_dist) == 0:
                trial_valid.iloc[idx] = 0.0
            else:
                ratio = float(np.sum(window_dist < fix_win) / len(window_dist))
                trial_valid.iloc[idx] = 1.0 if ratio > eye_cfg.eye_threshold else 0.0

        result = behavior_events_df.copy()
        result["trial_valid"] = trial_valid
        parquet_path = self.session.output_dir / "04_sync" / "behavior_events.parquet"
        result.to_parquet(parquet_path)
        return result
