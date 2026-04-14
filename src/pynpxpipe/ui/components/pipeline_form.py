"""ui/components/pipeline_form.py — PipelineConfig parameter form."""

from __future__ import annotations

import dataclasses

import panel as pn

from pynpxpipe.core.config import (
    BadChannelConfig,
    BandpassConfig,
    CommonReferenceConfig,
    CurationConfig,
    EyeValidationConfig,
    MergeConfig,
    MotionCorrectionConfig,
    ParallelConfig,
    PipelineConfig,
    PostprocessConfig,
    PreprocessConfig,
    ResourcesConfig,
    SyncConfig,
)
from pynpxpipe.ui.state import AppState

_DEFAULTS = PipelineConfig()


class PipelineForm:
    """Collapsible panels for each PipelineConfig sub-config group."""

    def __init__(self, state: AppState) -> None:
        self._state = state

        # ── Resources ──
        self.n_jobs_input = pn.widgets.TextInput(
            name="n_jobs",
            value=str(_DEFAULTS.resources.n_jobs),
            description="Number of parallel workers. 'auto' = detect from CPU cores. Used by preprocess and postprocess stages.",
        )
        self.chunk_duration_input = pn.widgets.TextInput(
            name="Chunk Duration",
            value=_DEFAULTS.resources.chunk_duration,
            description="Duration of each processing chunk (e.g. '1s', '2s'). 'auto' = estimate from RAM. Controls memory usage during preprocessing.",
        )
        self.max_memory_input = pn.widgets.TextInput(
            name="Max Memory",
            value=_DEFAULTS.resources.max_memory,
            description="Max RAM budget (e.g. '4G', '8G'). 'auto' = use 75% of free RAM. Limits chunk allocation.",
        )

        # ── Parallel ──
        self.parallel_enabled_checkbox = pn.widgets.Checkbox(
            name="Enable multi-probe parallelism (ProcessPoolExecutor)",
            value=_DEFAULTS.parallel.enabled,
        )
        self.parallel_max_workers_input = pn.widgets.TextInput(
            name="Max Workers",
            value=str(_DEFAULTS.parallel.max_workers),
            description="Worker process count for multi-probe parallelism. 'auto' = ResourceDetector recommends based on free RAM.",
        )

        # ── Bandpass ──
        self.freq_min_input = pn.widgets.FloatInput(
            name="Freq Min (Hz)",
            value=_DEFAULTS.preprocess.bandpass.freq_min,
            step=10.0,
            description="High-pass cutoff frequency. Standard: 300 Hz for AP band. Removes low-frequency LFP and drift.",
        )
        self.freq_max_input = pn.widgets.FloatInput(
            name="Freq Max (Hz)",
            value=_DEFAULTS.preprocess.bandpass.freq_max,
            step=100.0,
            description="Low-pass cutoff frequency. Standard: 6000 Hz. Set to Nyquist/2 (15000) to disable low-pass.",
        )

        # ── Bad Channel ──
        self.bad_channel_method_input = pn.widgets.TextInput(
            name="Bad Channel Method",
            value=_DEFAULTS.preprocess.bad_channel_detection.method,
            description="Detection algorithm. 'coherence+psd' = combined coherence and power spectral density (SpikeInterface default).",
        )
        self.dead_channel_threshold_input = pn.widgets.FloatInput(
            name="Dead Channel Threshold",
            value=_DEFAULTS.preprocess.bad_channel_detection.dead_channel_threshold,
            description="Threshold for dead channel detection. Lower = more sensitive. Channels below this are marked as dead and excluded.",
        )

        # ── Common Reference ──
        self.cmr_reference_select = pn.widgets.Select(
            name="Reference",
            options=["global", "local"],
            value=_DEFAULTS.preprocess.common_reference.reference,
            description="Reference scope. 'global' = all channels, 'local' = nearby channels only. Global is standard for Neuropixels.",
        )
        self.cmr_operator_select = pn.widgets.Select(
            name="Operator",
            options=["median", "mean"],
            value=_DEFAULTS.preprocess.common_reference.operator,
            description="Aggregation operator. 'median' is more robust to outliers (recommended). 'mean' is faster.",
        )

        # ── Motion Correction ──
        _mc = _DEFAULTS.preprocess.motion_correction
        self.motion_enabled_checkbox = pn.widgets.Checkbox(
            name="Enable Motion Correction (DREDge drift correction, mutually exclusive with KS4 nblocks)",
            value=_mc.method is not None,
        )
        self.motion_preset_select = pn.widgets.Select(
            name="Preset",
            options=[
                "dredge",
                "dredge_fast",
                "nonrigid_accurate",
                "nonrigid_fast_and_accurate",
                "rigid_fast",
                "kilosort_like",
                "medicine",
            ],
            value=_mc.preset,
            description="SpikeInterface motion correction preset. 'dredge' = DREDge AP (recommended). 'nonrigid_accurate' = decentralized non-rigid. See SI docs for details.",
        )

        # ── Curation ──
        self.isi_max_input = pn.widgets.FloatInput(
            name="ISI Violation Ratio Max",
            value=_DEFAULTS.curation.isi_violation_ratio_max,
            description="Max ISI violation ratio (refractory period violations / total spikes). Higher = more permissive. Typical: 0.5.",
        )
        self.amp_cutoff_input = pn.widgets.FloatInput(
            name="Amplitude Cutoff Max",
            value=_DEFAULTS.curation.amplitude_cutoff_max,
            description="Max amplitude cutoff. Measures how much of the amplitude distribution is clipped. Typical: 0.1.",
        )
        self.presence_min_input = pn.widgets.FloatInput(
            name="Presence Ratio Min",
            value=_DEFAULTS.curation.presence_ratio_min,
            description="Min fraction of recording where unit fires. 0.9 = unit must be present in 90% of time bins. Lower for short recordings.",
        )
        self.snr_min_input = pn.widgets.FloatInput(
            name="SNR Min",
            value=_DEFAULTS.curation.snr_min,
            description="Minimum signal-to-noise ratio. Units below this threshold are excluded. Typical: 5.0.",
        )

        # ── Sync ──
        _sync = _DEFAULTS.sync
        self.sync_bit_input = pn.widgets.IntInput(
            name="Sync Bit",
            value=_sync.imec_sync_bit,
            start=0,
            end=7,
            description="Digital bit index for IMEC-NIDQ clock sync pulses. Check SpikeGLX configuration for your setup.",
        )
        self.event_bits_input = pn.widgets.TextInput(
            name="Event Bits",
            value=",".join(str(b) for b in _sync.event_bits),
            description="Comma-separated list of digital bit indices encoding behavioral event codes from MonkeyLogic.",
        )
        self.stim_onset_code_input = pn.widgets.IntInput(
            name="Stim Onset Code",
            value=_sync.stim_onset_code,
            start=0,
            end=255,
            description="Event code value that marks stimulus onset in the BHV2 file. Must match MonkeyLogic task configuration.",
        )
        self.imec_sync_code_input = pn.widgets.IntInput(
            name="IMEC Sync Code",
            value=_sync.imec_sync_code,
            start=0,
            end=255,
            description="Event code on NIDQ digital lines that marks IMEC sync pulses. Used for clock alignment.",
        )
        self.monitor_delay_input = pn.widgets.FloatInput(
            name="Monitor Delay (ms)",
            value=_sync.monitor_delay_ms,
            step=1.0,
            description="Expected monitor display delay in ms. Used by photodiode calibration to correct stimulus onset times.",
        )
        self.generate_plots_checkbox = pn.widgets.Checkbox(
            name="Generate Sync Diagnostic Plots (requires matplotlib)",
            value=_sync.generate_plots,
        )

        # ── Postprocess ──
        _post = _DEFAULTS.postprocess
        self.slay_pre_input = pn.widgets.FloatInput(
            name="SLAy Pre (s)",
            value=_post.slay_pre_s,
            step=0.01,
            description="Baseline window before stimulus onset for SLAY score computation. Typical: 0.05s (50ms).",
        )
        self.slay_post_input = pn.widgets.FloatInput(
            name="SLAy Post (s)",
            value=_post.slay_post_s,
            step=0.01,
            description="Response window after stimulus onset for SLAY score. Typical: 0.30s (300ms). Adjust to match your task timing.",
        )
        self.eye_enabled_checkbox = pn.widgets.Checkbox(
            name="Eye Validation (fixation ratio from BHV2 analog eye channel)",
            value=_post.eye_validation.enabled,
        )
        self.eye_threshold_input = pn.widgets.FloatInput(
            name="Eye Threshold",
            value=_post.eye_validation.eye_threshold,
            step=0.001,
            description="Min fixation ratio to pass validation. 0.8 = eye must be within fixation window for 80% of trial duration.",
        )

        # Watch all widgets
        all_widgets = [
            self.n_jobs_input,
            self.chunk_duration_input,
            self.max_memory_input,
            self.parallel_enabled_checkbox,
            self.parallel_max_workers_input,
            self.freq_min_input,
            self.freq_max_input,
            self.bad_channel_method_input,
            self.dead_channel_threshold_input,
            self.cmr_reference_select,
            self.cmr_operator_select,
            self.motion_enabled_checkbox,
            self.motion_preset_select,
            self.isi_max_input,
            self.amp_cutoff_input,
            self.presence_min_input,
            self.snr_min_input,
            self.sync_bit_input,
            self.event_bits_input,
            self.stim_onset_code_input,
            self.imec_sync_code_input,
            self.monitor_delay_input,
            self.generate_plots_checkbox,
            self.slay_pre_input,
            self.slay_post_input,
            self.eye_enabled_checkbox,
            self.eye_threshold_input,
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

        max_workers_raw = self.parallel_max_workers_input.value
        try:
            max_workers = int(max_workers_raw)
        except (ValueError, TypeError):
            max_workers = max_workers_raw or "auto"

        # Parse event_bits from comma-separated string
        event_bits_raw = self.event_bits_input.value
        try:
            event_bits = [int(b.strip()) for b in event_bits_raw.split(",") if b.strip()]
        except ValueError:
            event_bits = _DEFAULTS.sync.event_bits

        self._state.pipeline_config = dataclasses.replace(
            _DEFAULTS,
            resources=ResourcesConfig(
                n_jobs=n_jobs,
                chunk_duration=self.chunk_duration_input.value or "auto",
                max_memory=self.max_memory_input.value or "auto",
            ),
            parallel=ParallelConfig(
                enabled=self.parallel_enabled_checkbox.value,
                max_workers=max_workers,
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
                motion_correction=MotionCorrectionConfig(
                    method="dredge" if self.motion_enabled_checkbox.value else None,
                    preset=self.motion_preset_select.value,
                ),
            ),
            curation=CurationConfig(
                isi_violation_ratio_max=self.isi_max_input.value,
                amplitude_cutoff_max=self.amp_cutoff_input.value,
                presence_ratio_min=self.presence_min_input.value,
                snr_min=self.snr_min_input.value,
            ),
            sync=SyncConfig(
                imec_sync_bit=self.sync_bit_input.value,
                event_bits=event_bits,
                stim_onset_code=self.stim_onset_code_input.value,
                imec_sync_code=self.imec_sync_code_input.value,
                monitor_delay_ms=self.monitor_delay_input.value,
                generate_plots=self.generate_plots_checkbox.value,
            ),
            postprocess=PostprocessConfig(
                slay_pre_s=self.slay_pre_input.value,
                slay_post_s=self.slay_post_input.value,
                eye_validation=EyeValidationConfig(
                    enabled=self.eye_enabled_checkbox.value,
                    eye_threshold=self.eye_threshold_input.value,
                ),
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
                self.parallel_enabled_checkbox,
                self.parallel_max_workers_input,
                title="Parallel (multi-probe)",
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
                self.motion_enabled_checkbox,
                self.motion_preset_select,
                title="Motion Correction",
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
            pn.Card(
                self.sync_bit_input,
                self.event_bits_input,
                self.stim_onset_code_input,
                self.imec_sync_code_input,
                self.monitor_delay_input,
                self.generate_plots_checkbox,
                title="Synchronization",
                collapsed=True,
            ),
            pn.Card(
                self.slay_pre_input,
                self.slay_post_input,
                self.eye_enabled_checkbox,
                self.eye_threshold_input,
                title="Postprocessing",
                collapsed=True,
            ),
        )
