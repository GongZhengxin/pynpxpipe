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
        self.use_bombcell_checkbox = pn.widgets.Checkbox(
            name="Use Bombcell four-class classification (SUA/MUA/NON-SOMA/NOISE)",
            value=_DEFAULTS.curation.use_bombcell,
        )
        self.isi_max_input = pn.widgets.FloatInput(
            name="ISI Violation Ratio Max",
            value=_DEFAULTS.curation.isi_violation_ratio_max,
            description="NOISE filter upper bound. Units with ISI violation ratio above this are discarded. Default 2.0 is permissive (bombcell handles SUA classification separately).",
        )
        self.amp_cutoff_input = pn.widgets.FloatInput(
            name="Amplitude Cutoff Max",
            value=_DEFAULTS.curation.amplitude_cutoff_max,
            description="NOISE filter upper bound for amplitude cutoff. Default 0.5 is permissive.",
        )
        self.presence_min_input = pn.widgets.FloatInput(
            name="Presence Ratio Min",
            value=_DEFAULTS.curation.presence_ratio_min,
            description="NOISE filter lower bound. Units present in < this fraction of recording are discarded. Default 0.5 keeps units appearing in >=50% of bins.",
        )
        self.snr_min_input = pn.widgets.FloatInput(
            name="SNR Min",
            value=_DEFAULTS.curation.snr_min,
            description="NOISE filter lower bound for SNR. Default 0.3 is very permissive (bombcell handles SUA).",
        )
        self.good_isi_max_input = pn.widgets.FloatInput(
            name="Good ISI Max (SUA threshold, manual mode)",
            value=_DEFAULTS.curation.good_isi_max,
            step=0.01,
            description="ISI violation ratio upper bound for SUA classification (fallback when use_bombcell=False).",
        )
        self.good_snr_min_input = pn.widgets.FloatInput(
            name="Good SNR Min (SUA threshold, manual mode)",
            value=_DEFAULTS.curation.good_snr_min,
            step=0.5,
            description="SNR lower bound for SUA classification (fallback when use_bombcell=False).",
        )

        # ── Sync ──
        _sync = _DEFAULTS.sync
        self.sync_bit_input = pn.widgets.IntInput(
            name="IMEC Sync Bit",
            value=_sync.imec_sync_bit,
            start=0,
            end=7,
            description="Digital bit index for IMEC sync pulses on the IMEC stream. Check SpikeGLX configuration.",
        )
        self.nidq_sync_bit_input = pn.widgets.IntInput(
            name="NIDQ Sync Bit",
            value=_sync.nidq_sync_bit,
            start=0,
            end=7,
            description="Bit position of sync pulse in NIDQ digital word (wiring-dependent, typically 0).",
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
        self.max_time_error_input = pn.widgets.FloatInput(
            name="Max Time Error (ms)",
            value=_sync.max_time_error_ms,
            start=0.0,
            step=1.0,
            description="Maximum allowed IMEC<->NIDQ alignment residual. Alignment fails above this.",
        )
        self.trial_count_tolerance_input = pn.widgets.IntInput(
            name="Trial Count Tolerance",
            value=_sync.trial_count_tolerance,
            start=0,
            description="Maximum BHV2<->NIDQ trial count mismatch auto-repaired via padding/trimming.",
        )
        self.gap_threshold_enable_checkbox = pn.widgets.Checkbox(
            name="Enable Dropped-Pulse Gap Detection",
            value=_sync.gap_threshold_ms is not None,
        )
        self.gap_threshold_input = pn.widgets.FloatInput(
            name="Gap Threshold (ms)",
            value=_sync.gap_threshold_ms if _sync.gap_threshold_ms is not None else 1200.0,
            start=0.0,
            step=50.0,
            disabled=_sync.gap_threshold_ms is None,
            description="Intervals above this are flagged as dropped pulses for repair.",
        )
        self.trial_start_bit_enable_checkbox = pn.widgets.Checkbox(
            name="Enable Explicit Trial Start Bit",
            value=_sync.trial_start_bit is not None,
        )
        self.trial_start_bit_input = pn.widgets.IntInput(
            name="Trial Start Bit",
            value=_sync.trial_start_bit if _sync.trial_start_bit is not None else 0,
            start=0,
            end=7,
            disabled=_sync.trial_start_bit is None,
            description="Optional NIDQ bit marking trial start (leave disabled to infer from event codes).",
        )
        self.photodiode_channel_input = pn.widgets.IntInput(
            name="Photodiode Channel Index",
            value=_sync.photodiode_channel_index,
            start=0,
            description="NIDQ analog channel index for the photodiode signal.",
        )
        self.monitor_delay_input = pn.widgets.FloatInput(
            name="Monitor Delay (ms)",
            value=_sync.monitor_delay_ms,
            step=1.0,
            description="Expected monitor display delay in ms. Used by photodiode calibration to correct stimulus onset times.",
        )
        self.pd_window_pre_input = pn.widgets.FloatInput(
            name="PD Window Pre (ms)",
            value=_sync.pd_window_pre_ms,
            start=0.0,
            step=1.0,
            description="Baseline window before photodiode event for calibration.",
        )
        self.pd_window_post_input = pn.widgets.FloatInput(
            name="PD Window Post (ms)",
            value=_sync.pd_window_post_ms,
            start=0.0,
            step=5.0,
            description="Detection window after photodiode event for calibration.",
        )
        self.pd_min_variance_input = pn.widgets.FloatInput(
            name="PD Min Signal Variance",
            value=_sync.pd_min_signal_variance,
            start=0.0,
            step=1e-6,
            description="Below this variance the photodiode channel is treated as absent (skip calibration).",
        )
        self.generate_plots_checkbox = pn.widgets.Checkbox(
            name="Generate Sync Diagnostic Plots (requires matplotlib)",
            value=_sync.generate_plots,
        )

        self.gap_threshold_enable_checkbox.param.watch(
            lambda e: setattr(self.gap_threshold_input, "disabled", not e.new),
            "value",
        )
        self.trial_start_bit_enable_checkbox.param.watch(
            lambda e: setattr(self.trial_start_bit_input, "disabled", not e.new),
            "value",
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
        self.pre_onset_ms_input = pn.widgets.FloatInput(
            name="Pre-onset (ms)",
            value=_post.pre_onset_ms,
            step=5.0,
            description="Dynamic SLAY window pre-stimulus margin (pre_s = pre_onset_ms / 1000).",
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

        # ── Merge ──
        self.merge_enabled_checkbox = pn.widgets.Checkbox(
            name="Enable auto-merge stage (irreversible; review sorting quality first)",
            value=_DEFAULTS.merge.enabled,
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
            self.use_bombcell_checkbox,
            self.isi_max_input,
            self.amp_cutoff_input,
            self.presence_min_input,
            self.snr_min_input,
            self.good_isi_max_input,
            self.good_snr_min_input,
            self.sync_bit_input,
            self.nidq_sync_bit_input,
            self.event_bits_input,
            self.stim_onset_code_input,
            self.imec_sync_code_input,
            self.max_time_error_input,
            self.trial_count_tolerance_input,
            self.gap_threshold_enable_checkbox,
            self.gap_threshold_input,
            self.trial_start_bit_enable_checkbox,
            self.trial_start_bit_input,
            self.photodiode_channel_input,
            self.monitor_delay_input,
            self.pd_window_pre_input,
            self.pd_window_post_input,
            self.pd_min_variance_input,
            self.generate_plots_checkbox,
            self.slay_pre_input,
            self.slay_post_input,
            self.pre_onset_ms_input,
            self.eye_enabled_checkbox,
            self.eye_threshold_input,
            self.merge_enabled_checkbox,
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
                good_isi_max=self.good_isi_max_input.value,
                good_snr_min=self.good_snr_min_input.value,
                use_bombcell=self.use_bombcell_checkbox.value,
            ),
            sync=SyncConfig(
                imec_sync_bit=self.sync_bit_input.value,
                nidq_sync_bit=self.nidq_sync_bit_input.value,
                event_bits=event_bits,
                max_time_error_ms=self.max_time_error_input.value,
                trial_count_tolerance=self.trial_count_tolerance_input.value,
                photodiode_channel_index=self.photodiode_channel_input.value,
                monitor_delay_ms=self.monitor_delay_input.value,
                stim_onset_code=self.stim_onset_code_input.value,
                imec_sync_code=self.imec_sync_code_input.value,
                generate_plots=self.generate_plots_checkbox.value,
                gap_threshold_ms=(
                    self.gap_threshold_input.value
                    if self.gap_threshold_enable_checkbox.value
                    else None
                ),
                trial_start_bit=(
                    self.trial_start_bit_input.value
                    if self.trial_start_bit_enable_checkbox.value
                    else None
                ),
                pd_window_pre_ms=self.pd_window_pre_input.value,
                pd_window_post_ms=self.pd_window_post_input.value,
                pd_min_signal_variance=self.pd_min_variance_input.value,
            ),
            postprocess=PostprocessConfig(
                slay_pre_s=self.slay_pre_input.value,
                slay_post_s=self.slay_post_input.value,
                pre_onset_ms=self.pre_onset_ms_input.value,
                eye_validation=EyeValidationConfig(
                    enabled=self.eye_enabled_checkbox.value,
                    eye_threshold=self.eye_threshold_input.value,
                ),
            ),
            merge=MergeConfig(enabled=self.merge_enabled_checkbox.value),
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
                self.use_bombcell_checkbox,
                self.isi_max_input,
                self.amp_cutoff_input,
                self.presence_min_input,
                self.snr_min_input,
                self.good_isi_max_input,
                self.good_snr_min_input,
                title="Curation Thresholds",
                collapsed=True,
            ),
            pn.Card(
                self.sync_bit_input,
                self.nidq_sync_bit_input,
                self.max_time_error_input,
                self.gap_threshold_enable_checkbox,
                self.gap_threshold_input,
                self.event_bits_input,
                self.stim_onset_code_input,
                self.imec_sync_code_input,
                self.trial_count_tolerance_input,
                self.trial_start_bit_enable_checkbox,
                self.trial_start_bit_input,
                self.photodiode_channel_input,
                self.monitor_delay_input,
                self.pd_window_pre_input,
                self.pd_window_post_input,
                self.pd_min_variance_input,
                self.generate_plots_checkbox,
                title="Synchronization",
                collapsed=True,
            ),
            pn.Card(
                self.slay_pre_input,
                self.slay_post_input,
                self.pre_onset_ms_input,
                self.eye_enabled_checkbox,
                self.eye_threshold_input,
                title="Postprocessing",
                collapsed=True,
            ),
            pn.Card(
                self.merge_enabled_checkbox,
                title="Auto-Merge (opt-in, irreversible)",
                collapsed=True,
            ),
        )
