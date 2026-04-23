"""Curate stage: quality metric computation and unit filtering per probe.

Uses SpikeInterface quality_metrics extension and Bombcell classification.
No UI dependencies.
"""

from __future__ import annotations

import copy
import gc
from collections.abc import Callable
from typing import TYPE_CHECKING

import spikeinterface.core as si

from pynpxpipe.core.errors import CurateError
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    import pandas as pd

    from pynpxpipe.core.config import BombcellConfig
    from pynpxpipe.core.session import Session

# Bombcell label → unittype_string mapping
_BOMBCELL_LABEL_MAP = {
    "good": "SUA",
    "mua": "MUA",
    "non_soma": "NON-SOMA",
    "noise": "NOISE",
}


def _deep_merge_thresholds(base: dict, override: dict) -> dict:
    """Recursively merge ``override`` into ``base`` without mutating either.

    Used to apply ``BombcellConfig.extra_overrides`` on top of the
    BombcellConfig-derived mua overrides. Nested dicts merge key-by-key;
    any non-dict value in ``override`` replaces the corresponding key.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_thresholds(result[key], value)
        else:
            result[key] = value
    return result


def _build_bombcell_thresholds(bombcell_cfg: BombcellConfig, defaults: dict) -> dict:
    """Construct the thresholds dict passed to ``bombcell_label_units``.

    Steps:
      1. ``deepcopy(defaults)`` (so the SI-owned dict is never mutated)
      2. Override the ``mua`` layer fields from ``BombcellConfig``
         (``greater``/``less`` only — sibling keys like ``abs`` are kept).
      3. ``deep_merge`` ``bombcell_cfg.extra_overrides`` on top.
    """
    thresholds = copy.deepcopy(defaults)
    mua = thresholds.setdefault("mua", {})

    _set_bound(mua, "amplitude_median", "greater", bombcell_cfg.amplitude_median_min)
    _set_bound(mua, "num_spikes", "greater", bombcell_cfg.num_spikes_min)
    _set_bound(mua, "presence_ratio", "greater", bombcell_cfg.presence_ratio_min)
    _set_bound(mua, "snr", "greater", bombcell_cfg.snr_min)
    _set_bound(mua, "amplitude_cutoff", "less", bombcell_cfg.amplitude_cutoff_max)
    _set_bound(mua, "rp_contamination", "less", bombcell_cfg.rp_contamination_max)
    _set_bound(mua, "drift_ptp", "less", bombcell_cfg.drift_ptp_max)

    if bombcell_cfg.extra_overrides:
        thresholds = _deep_merge_thresholds(thresholds, bombcell_cfg.extra_overrides)
    return thresholds


def _set_bound(layer: dict, metric: str, bound: str, value: float | int) -> None:
    """Set ``layer[metric][bound]`` without clobbering sibling keys (e.g. ``abs``)."""
    entry = dict(layer.get(metric) or {})
    entry[bound] = value
    layer[metric] = entry


class CurateStage(BaseStage):
    """Computes quality metrics and filters units for each probe.

    Primary path (use_bombcell=True): calls SI bombcell_label_units() for
    four-class classification (SUA/MUA/NON-SOMA/NOISE). Requires template_metrics
    extension in addition to quality_metrics.

    Fallback path (use_bombcell=False): manual threshold-based classification
    using CurationConfig thresholds. GOOD renamed to SUA.

    Only NOISE units are discarded; SUA, MUA, and NON-SOMA are kept.
    Zero units after curation: WARNING, not error (pipeline continues).

    Raises:
        CurateError: If sorting or recording cannot be loaded.
    """

    STAGE_NAME = "curate"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the curate stage.

        Args:
            session: Active pipeline session with sorting results available.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        super().__init__(session, progress_callback)

    def run(self) -> None:
        """Compute quality metrics and curate all probes serially."""
        if self._is_complete():
            self._report_progress("Curate already complete", 1.0)
            return

        self._report_progress("Starting curate", 0.0)
        self._setup_spikeinterface_jobs()

        n_probes = len(self.session.probes)
        for i, probe in enumerate(self.session.probes):
            probe_id = probe.probe_id
            try:
                self._curate_probe(probe_id)
            except Exception as exc:
                self._write_failed_checkpoint(exc, probe_id=probe_id)
                raise
            self._report_progress(f"Curated {probe_id}", (i + 1) / n_probes)

        self._write_checkpoint({"probe_ids": [p.probe_id for p in self.session.probes]})
        self._report_progress("Curate complete", 1.0)

    def _curate_probe(self, probe_id: str) -> tuple[int, int]:
        """Run curation for a single probe.

        Args:
            probe_id: Probe identifier (e.g. "imec0").

        Returns:
            Tuple (n_units_before, n_units_after).
        """
        if self._is_complete(probe_id=probe_id):
            return (0, 0)

        sorted_path = self.session.output_dir / "02_sorted" / probe_id
        recording_path = self.session.output_dir / "01_preprocessed" / f"{probe_id}.zarr"

        try:
            sorting = si.load(sorted_path)
            recording = si.load(recording_path)
        except Exception as exc:
            raise CurateError(f"Failed to load data for {probe_id}: {exc}") from exc

        analyzer = si.create_sorting_analyzer(
            sorting,
            recording,
            format="memory",
            sparse=True,
        )
        curation = self.session.config.curation

        analyzer.compute("random_spikes")
        analyzer.compute("waveforms")
        analyzer.compute("templates")
        analyzer.compute("noise_levels")
        analyzer.compute("spike_amplitudes")
        if curation.use_bombcell:
            # drift metric needs spike_locations (monopolar triangulation,
            # minutes-slow on large recordings but required for bombcell).
            analyzer.compute("spike_locations")
            # template_metrics powers bombcell's non-somatic waveform-shape
            # classification; keep adjacent to quality_metrics for clarity.
            analyzer.compute("template_metrics")
            metric_names = [
                "snr",
                "amplitude_cutoff",
                "amplitude_median",
                "presence_ratio",
                "num_spikes",
                "isi_violation",
                "rp_violation",  # → rp_contamination column
                "drift",  # → drift_ptp column
                "firing_rate",
            ]
        else:
            metric_names = ["isi_violation", "amplitude_cutoff", "presence_ratio", "snr"]
        analyzer.compute("quality_metrics", metric_names=metric_names)

        qm = analyzer.get_extension("quality_metrics").get_data()

        output_probe_dir = self.session.output_dir / "05_curated" / probe_id
        output_probe_dir.mkdir(parents=True, exist_ok=True)

        n_before = len(sorting.get_unit_ids())

        if curation.use_bombcell:
            unittype_map, bombcell_labels_df, bombcell_thresholds = self._classify_bombcell(
                analyzer, qm
            )
        else:
            unittype_map = self._classify_manual(qm, curation)
            bombcell_labels_df = None
            bombcell_thresholds = None

        # Keep SUA + MUA + NON-SOMA, discard NOISE
        keep_ids = [uid for uid, utype in unittype_map.items() if utype != "NOISE"]
        curated_sorting = sorting.select_units(keep_ids)

        unittype_labels = [unittype_map[uid] for uid in keep_ids]
        curated_sorting.set_property("unittype_string", unittype_labels)

        n_after = len(keep_ids)
        n_sua = sum(1 for u in unittype_labels if u == "SUA")
        n_mua = sum(1 for u in unittype_labels if u == "MUA")
        n_non_soma = sum(1 for u in unittype_labels if u == "NON-SOMA")
        if n_after == 0:
            self.logger.warning("Zero units after curation", probe_id=probe_id)
        else:
            self.logger.info(
                "Curation result",
                probe_id=probe_id,
                n_before=n_before,
                n_after=n_after,
                n_sua=n_sua,
                n_mua=n_mua,
                n_non_soma=n_non_soma,
                n_noise=n_before - n_after,
            )

        curated_sorting.save(folder=output_probe_dir, overwrite=True)
        qm.to_csv(output_probe_dir / "quality_metrics.csv")

        figures_dir = output_probe_dir / "figures"
        try:
            from pynpxpipe.plots.curate import emit_all as _emit_curate_plots

            _emit_curate_plots(
                analyzer=analyzer,
                qm=qm,
                unittype_map=unittype_map,
                probe_id=probe_id,
                output_dir=figures_dir,
                session_label=self.session.session_id,
            )
        except ImportError:
            pass  # matplotlib not installed
        except Exception as exc:
            self.logger.warning("curate figure generation failed: %s", exc, exc_info=True)

        try:
            from pynpxpipe.plots.bombcell import emit_bombcell_plots

            emit_bombcell_plots(
                analyzer=analyzer,
                unittype_map=unittype_map,
                labels_df=bombcell_labels_df,
                thresholds=bombcell_thresholds,
                probe_id=probe_id,
                output_dir=figures_dir,
            )
        except ImportError as exc:
            # matplotlib or spikeinterface.widgets not installed — log once so
            # the user sees *which* dependency is missing rather than silent skip.
            self.logger.warning(
                "bombcell figure generation skipped (ImportError: %s). "
                "Install the [plots] extra: `uv sync --inexact --extra plots`",
                exc,
            )
        except Exception as exc:
            self.logger.warning("bombcell figure generation failed: %s", exc, exc_info=True)

        self._write_checkpoint(
            {
                "probe_id": probe_id,
                "n_units_before": n_before,
                "n_units_after": n_after,
                "thresholds": {
                    "isi_violation_ratio_max": curation.isi_violation_ratio_max,
                    "amplitude_cutoff_max": curation.amplitude_cutoff_max,
                    "presence_ratio_min": curation.presence_ratio_min,
                    "snr_min": curation.snr_min,
                },
            },
            probe_id=probe_id,
        )

        del analyzer, sorting, recording
        gc.collect()

        return (n_before, n_after)

    def _classify_bombcell(
        self, analyzer: si.SortingAnalyzer, qm
    ) -> tuple[dict, pd.DataFrame | None, dict | None]:
        """Classify units using SI bombcell_label_units() (four-class).

        Expects ``template_metrics`` + ``quality_metrics`` extensions to
        already be computed by ``_curate_probe``. As a safety net still
        computes ``template_metrics`` if missing — but the normal path
        reaches this method with both extensions present so bombcell can
        find all its required metric columns.

        Args:
            analyzer: SortingAnalyzer with quality_metrics and template_metrics
                computed.
            qm: quality_metrics DataFrame (used as fallback if bombcell fails).

        Returns:
            Triple ``(unittype_map, labels_df, thresholds_dict)``:

            - ``unittype_map``: dict ``{unit_id: "SUA" | "MUA" | "NON-SOMA" | "NOISE"}``.
            - ``labels_df``: raw bombcell output DataFrame (index=unit_id,
              column ``bombcell_label``). ``None`` when bombcell fails.
            - ``thresholds_dict``: bombcell default thresholds for diagnostic
              plots. ``None`` when bombcell fails.
        """
        import spikeinterface.curation as sc

        if not analyzer.has_extension("template_metrics"):
            analyzer.compute("template_metrics")

        bombcell_cfg = self.session.config.curation.bombcell
        try:
            defaults = sc.bombcell_get_default_thresholds()
            thresholds = _build_bombcell_thresholds(bombcell_cfg, defaults)
            labels_df = sc.bombcell_label_units(
                analyzer,
                thresholds=thresholds,
                label_non_somatic=bombcell_cfg.label_non_somatic,
                split_non_somatic_good_mua=bombcell_cfg.split_non_somatic_good_mua,
            )
            # SI ≥0.104 renames "label" → "bombcell_label" inside
            # bombcell_label_units. Reading the old key silently fell back
            # to manual thresholds in every previous run.
            unittype_map = {
                uid: _BOMBCELL_LABEL_MAP.get(str(label).lower(), "NOISE")
                for uid, label in labels_df["bombcell_label"].items()
            }
            return unittype_map, labels_df, thresholds
        except Exception as exc:
            self.logger.warning(
                "bombcell_label_units failed, falling back to manual thresholds",
                error=str(exc),
            )
            return self._classify_manual(qm, self.session.config.curation), None, None

    def _classify_manual(self, qm, curation) -> dict:
        """Classify units using manual ISI/SNR thresholds (fallback).

        Also applies amplitude_cutoff and presence_ratio filters — units that
        fail these hard filters are classified as NOISE regardless of ISI/SNR.

        Args:
            qm: quality_metrics DataFrame.
            curation: CurationConfig with threshold values.

        Returns:
            Dict mapping unit_id → "SUA" | "MUA" | "NOISE".
        """
        unittype_map: dict = {}
        for uid in qm.index:
            isi = float(qm.loc[uid, "isi_violations_ratio"])
            snr_val = float(qm.loc[uid, "snr"])
            pr = float(qm.loc[uid, "presence_ratio"])

            # Hard filters: presence_ratio and amplitude_cutoff
            if pr < curation.presence_ratio_min:
                unittype_map[uid] = "NOISE"
                continue
            if "amplitude_cutoff" in qm.columns:
                amp = qm.loc[uid, "amplitude_cutoff"]
                if amp is not None and not (amp != amp):  # not NaN
                    if float(amp) > curation.amplitude_cutoff_max:
                        unittype_map[uid] = "NOISE"
                        continue

            # ISI/SNR classification
            if isi <= curation.good_isi_max and snr_val >= curation.good_snr_min:
                unittype_map[uid] = "SUA"
            elif isi <= curation.isi_violation_ratio_max and snr_val >= curation.snr_min:
                unittype_map[uid] = "MUA"
            else:
                unittype_map[uid] = "NOISE"
        return unittype_map
