"""ui/components/pipeline_form.py — PipelineConfig parameter form."""

from __future__ import annotations

import dataclasses

import panel as pn

from pynpxpipe.core.config import (
    BadChannelConfig,
    BandpassConfig,
    CommonReferenceConfig,
    CurationConfig,
    PipelineConfig,
    PreprocessConfig,
    ResourcesConfig,
)
from pynpxpipe.ui.state import AppState

_DEFAULTS = PipelineConfig()


class PipelineForm:
    """Collapsible panels for each PipelineConfig sub-config group."""

    def __init__(self, state: AppState) -> None:
        self._state = state

        # ── Resources ──
        self.n_jobs_input = pn.widgets.TextInput(
            name="n_jobs", value=str(_DEFAULTS.resources.n_jobs)
        )
        self.chunk_duration_input = pn.widgets.TextInput(
            name="Chunk Duration", value=_DEFAULTS.resources.chunk_duration
        )
        self.max_memory_input = pn.widgets.TextInput(
            name="Max Memory", value=_DEFAULTS.resources.max_memory
        )

        # ── Bandpass ──
        self.freq_min_input = pn.widgets.FloatInput(
            name="Freq Min (Hz)", value=_DEFAULTS.preprocess.bandpass.freq_min, step=10.0
        )
        self.freq_max_input = pn.widgets.FloatInput(
            name="Freq Max (Hz)", value=_DEFAULTS.preprocess.bandpass.freq_max, step=100.0
        )

        # ── Bad Channel ──
        self.bad_channel_method_input = pn.widgets.TextInput(
            name="Bad Channel Method", value=_DEFAULTS.preprocess.bad_channel_detection.method
        )
        self.dead_channel_threshold_input = pn.widgets.FloatInput(
            name="Dead Channel Threshold",
            value=_DEFAULTS.preprocess.bad_channel_detection.dead_channel_threshold,
        )

        # ── Common Reference ──
        self.cmr_reference_select = pn.widgets.Select(
            name="Reference",
            options=["global", "local"],
            value=_DEFAULTS.preprocess.common_reference.reference,
        )
        self.cmr_operator_select = pn.widgets.Select(
            name="Operator",
            options=["median", "mean"],
            value=_DEFAULTS.preprocess.common_reference.operator,
        )

        # ── Curation ──
        self.isi_max_input = pn.widgets.FloatInput(
            name="ISI Violation Ratio Max", value=_DEFAULTS.curation.isi_violation_ratio_max
        )
        self.amp_cutoff_input = pn.widgets.FloatInput(
            name="Amplitude Cutoff Max", value=_DEFAULTS.curation.amplitude_cutoff_max
        )
        self.presence_min_input = pn.widgets.FloatInput(
            name="Presence Ratio Min", value=_DEFAULTS.curation.presence_ratio_min
        )
        self.snr_min_input = pn.widgets.FloatInput(name="SNR Min", value=_DEFAULTS.curation.snr_min)

        # Watch all widgets
        all_widgets = [
            self.n_jobs_input,
            self.chunk_duration_input,
            self.max_memory_input,
            self.freq_min_input,
            self.freq_max_input,
            self.bad_channel_method_input,
            self.dead_channel_threshold_input,
            self.cmr_reference_select,
            self.cmr_operator_select,
            self.isi_max_input,
            self.amp_cutoff_input,
            self.presence_min_input,
            self.snr_min_input,
        ]
        for w in all_widgets:
            w.param.watch(self._rebuild_config, "value")

        # Initialize state
        self._rebuild_config()

    # ── Internal ──

    def _rebuild_config(self, event=None) -> None:
        n_jobs_raw = self.n_jobs_input.value
        try:
            n_jobs = int(n_jobs_raw)
        except (ValueError, TypeError):
            n_jobs = n_jobs_raw or "auto"

        self._state.pipeline_config = dataclasses.replace(
            _DEFAULTS,
            resources=ResourcesConfig(
                n_jobs=n_jobs,
                chunk_duration=self.chunk_duration_input.value or "auto",
                max_memory=self.max_memory_input.value or "auto",
            ),
            preprocess=PreprocessConfig(
                bandpass=BandpassConfig(
                    freq_min=self.freq_min_input.value,
                    freq_max=self.freq_max_input.value,
                ),
                bad_channel_detection=BadChannelConfig(
                    method=self.bad_channel_method_input.value,
                    dead_channel_threshold=self.dead_channel_threshold_input.value,
                ),
                common_reference=CommonReferenceConfig(
                    reference=self.cmr_reference_select.value,
                    operator=self.cmr_operator_select.value,
                ),
                motion_correction=_DEFAULTS.preprocess.motion_correction,
            ),
            curation=CurationConfig(
                isi_violation_ratio_max=self.isi_max_input.value,
                amplitude_cutoff_max=self.amp_cutoff_input.value,
                presence_ratio_min=self.presence_min_input.value,
                snr_min=self.snr_min_input.value,
            ),
        )

    # ── Layout ──

    def panel(self) -> pn.viewable.Viewable:
        return pn.Column(
            pn.pane.Markdown("### Pipeline Parameters"),
            pn.Card(
                self.n_jobs_input,
                self.chunk_duration_input,
                self.max_memory_input,
                title="Resources",
                collapsed=True,
            ),
            pn.Card(
                self.freq_min_input,
                self.freq_max_input,
                title="Bandpass Filter",
                collapsed=False,
            ),
            pn.Card(
                self.bad_channel_method_input,
                self.dead_channel_threshold_input,
                self.cmr_reference_select,
                self.cmr_operator_select,
                title="Bad Channel & Common Reference",
                collapsed=True,
            ),
            pn.Card(
                self.isi_max_input,
                self.amp_cutoff_input,
                self.presence_min_input,
                self.snr_min_input,
                title="Curation Thresholds",
                collapsed=True,
            ),
        )
