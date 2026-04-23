"""YAML configuration loading and validation.

Loads pipeline.yaml and sorting.yaml into typed dataclasses.
No UI dependencies.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from pathlib import Path

import structlog
import yaml

from pynpxpipe.core.errors import ConfigError
from pynpxpipe.core.session import SubjectConfig

_log = structlog.get_logger(__name__)


@dataclass
class ResourcesConfig:
    """Resource allocation settings.

    Attributes:
        n_jobs: Number of parallel threads for SpikeInterface internals.
            "auto" = ResourceDetector recommends based on CPU and RAM.
        chunk_duration: Time window for chunked processing (e.g. "1s", "0.5s").
            "auto" = ResourceDetector recommends based on available RAM.
        max_memory: Memory ceiling hint for logging warnings (e.g. "32G").
            "auto" = advisory only; no enforcement.
    """

    n_jobs: int | str = "auto"
    chunk_duration: str = "auto"
    max_memory: str = "auto"


@dataclass
class ParallelConfig:
    """Multi-probe parallelism settings.

    Attributes:
        enabled: Whether to run probes in parallel (default False = serial).
        max_workers: Maximum number of worker processes (ProcessPoolExecutor).
            "auto" = ResourceDetector recommends based on available RAM.
    """

    enabled: bool = False
    max_workers: int | str = "auto"


@dataclass
class BandpassConfig:
    """Bandpass filter parameters.

    Attributes:
        freq_min: High-pass cutoff frequency in Hz.
        freq_max: Low-pass cutoff frequency in Hz.
    """

    freq_min: float = 300.0
    freq_max: float = 6000.0


@dataclass
class BadChannelConfig:
    """Bad channel detection parameters.

    Attributes:
        method: Detection method string (e.g. "coherence+psd").
        dead_channel_threshold: Threshold for classifying a channel as dead (0–1).
    """

    method: str = "coherence+psd"
    dead_channel_threshold: float = 0.5


@dataclass
class CommonReferenceConfig:
    """Common reference subtraction parameters.

    Attributes:
        reference: Reference scope: "global" or "local".
        operator: Aggregation operator: "median" or "mean".
    """

    reference: str = "global"
    operator: str = "median"


@dataclass
class MotionCorrectionConfig:
    """Motion correction (drift correction) parameters.

    Attributes:
        method: "dredge" to enable or None to skip. The actual algorithm is
            determined by ``preset``, not ``method`` — method is only an
            enable/disable toggle.
        preset: SpikeInterface motion correction preset name passed to
            ``spp.correct_motion(preset=...)``. See SI docs for full list.
    """

    method: str | None = "dredge"
    preset: str = "dredge"


@dataclass
class PreprocessConfig:
    """Preprocessing stage parameters.

    Attributes:
        bandpass: Bandpass filter settings.
        bad_channel_detection: Bad channel detection settings.
        common_reference: Common reference subtraction settings.
        motion_correction: Motion correction settings.
    """

    bandpass: BandpassConfig = field(default_factory=BandpassConfig)
    bad_channel_detection: BadChannelConfig = field(default_factory=BadChannelConfig)
    common_reference: CommonReferenceConfig = field(default_factory=CommonReferenceConfig)
    motion_correction: MotionCorrectionConfig = field(default_factory=MotionCorrectionConfig)


@dataclass
class BombcellConfig:
    """Bombcell threshold overrides and flags for the curate stage.

    Field values override the ``mua`` layer of
    ``spikeinterface.curation.bombcell_get_default_thresholds()`` — the
    layer that separates SUA from MUA. Defaults are aligned with MATLAB
    ``bc_qualityParamValues`` (wider than SI built-ins, which were
    empirically producing too few SUA).

    Attributes:
        amplitude_median_min: mua.amplitude_median.greater (µV). MATLAB 20 µV
            (SI default 30).
        num_spikes_min: mua.num_spikes.greater. MATLAB 50 (SI 300).
        presence_ratio_min: mua.presence_ratio.greater. MATLAB 0.2 (SI 0.7).
        snr_min: mua.snr.greater. MATLAB 3.0 (SI 5.0).
        amplitude_cutoff_max: mua.amplitude_cutoff.less. Both MATLAB and SI
            use 0.2.
        rp_contamination_max: mua.rp_contamination.less. Both 0.1.
        drift_ptp_max: mua.drift_ptp.less (µm). Both 100.
        label_non_somatic: Passed to ``bombcell_label_units(label_non_somatic=...)``.
            True enables the third classification pass (NON-SOMA).
        split_non_somatic_good_mua: Passed to
            ``bombcell_label_units(split_non_somatic_good_mua=...)``. True
            subdivides NON-SOMA into NON-SOMA-GOOD / NON-SOMA-MUA.
        extra_overrides: Nested dict deep-merged into the final thresholds
            dict. Lets the user patch any ``noise`` / ``non-somatic`` layer
            metric without exposing every field on this dataclass.
    """

    amplitude_median_min: float = 20.0
    num_spikes_min: int = 50
    presence_ratio_min: float = 0.2
    snr_min: float = 3.0
    amplitude_cutoff_max: float = 0.2
    rp_contamination_max: float = 0.1
    drift_ptp_max: float = 100.0
    label_non_somatic: bool = True
    split_non_somatic_good_mua: bool = False
    extra_overrides: dict = field(default_factory=dict)


@dataclass
class CurationConfig:
    """Quality metric thresholds for the curate stage.

    Units are classified into SUA/MUA/NON-SOMA/NOISE using Bombcell
    (``use_bombcell=True``) or manual thresholds (``use_bombcell=False``).
    Only NOISE units are discarded; SUA, MUA, and NON-SOMA are kept.

    Attributes:
        isi_violation_ratio_max: ISI violation ratio upper bound for NOISE
            filter (manual fallback only, ``use_bombcell=False``).
        amplitude_cutoff_max: Amplitude cutoff upper bound for NOISE filter
            (manual fallback only).
        presence_ratio_min: Presence ratio lower bound for NOISE filter
            (manual fallback only).
        snr_min: SNR lower bound for NOISE filter (manual fallback only).
        good_isi_max: ISI violation ratio upper bound for SUA classification
            (manual fallback only).
        good_snr_min: SNR lower bound for SUA classification (manual fallback only).
        use_bombcell: If True, use SI ``bombcell_label_units()`` for four-class
            classification (SUA/MUA/NON-SOMA/NOISE). If False, use manual
            threshold-based classification.
        bombcell: Threshold overrides + flags for the bombcell main path.
    """

    isi_violation_ratio_max: float = 2.0
    amplitude_cutoff_max: float = 0.5
    presence_ratio_min: float = 0.5
    snr_min: float = 0.3
    good_isi_max: float = 0.1
    good_snr_min: float = 3.0
    use_bombcell: bool = True
    bombcell: BombcellConfig = field(default_factory=BombcellConfig)


@dataclass
class SyncConfig:
    """Time synchronization parameters for the synchronize stage.

    Attributes:
        imec_sync_bit: Bit position of the sync pulse in the IMEC AP sync channel.
            Neuropixels hardware standard is bit 6.
        nidq_sync_bit: Bit position of the sync pulse in the NIDQ digital word.
            Depends on wiring; typically bit 0.
        event_bits: List of bit positions used by MonkeyLogic for event codes.
        max_time_error_ms: Maximum allowed IMEC↔NIDQ alignment error in ms.
        trial_count_tolerance: Maximum trial count mismatch for auto-repair.
        photodiode_channel_index: NIDQ analog channel index for the photodiode signal.
        monitor_delay_ms: Monitor system delay correction in ms (60 Hz ≈ -5).
        stim_onset_code: Event code value representing stimulus onset on NIDQ.
        generate_plots: Whether to generate sync diagnostic plots.
    """

    imec_sync_bit: int = 6
    nidq_sync_bit: int = 0
    event_bits: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    max_time_error_ms: float = 17.0
    trial_count_tolerance: int = 2
    photodiode_channel_index: int = 0
    monitor_delay_ms: float = -5.0
    stim_onset_code: int = 64
    generate_plots: bool = True
    gap_threshold_ms: float | None = 1200.0
    trial_start_bit: int | None = None
    stim_onset_bit: int | None = None
    stim_count_tolerance: int = 0
    pd_window_pre_ms: float = 10.0
    pd_window_post_ms: float = 100.0
    pd_hignline_skip_ms: float = 50.0
    pd_hignline_width_ms: float = 20.0
    pd_min_signal_variance: float = 1e-6


@dataclass
class EyeValidationConfig:
    """Eye movement validation parameters for postprocess stage.

    Attributes:
        enabled: Whether to perform eye movement validation.
        eye_threshold: Fixation ratio threshold for trial validity.
    """

    enabled: bool = True
    eye_threshold: float = 0.999


@dataclass
class MergeConfig:
    """Optional auto-merge stage parameters.

    Attributes:
        enabled: Whether to run auto_merge(). Default False — merge is
            irreversible, so the user must opt in explicitly after reviewing
            sorting quality.
    """

    enabled: bool = False


@dataclass
class PostprocessConfig:
    """Postprocess stage parameters.

    Attributes:
        slay_pre_s: Pre-stimulus window for SLAY score (seconds). Fallback
            default used when behavior_events lacks onset_time_ms/offset_time_ms.
        slay_post_s: Post-stimulus window for SLAY score (seconds). Fallback
            default used when behavior_events lacks onset_time_ms/offset_time_ms.
        pre_onset_ms: Pre-stimulus window in ms for dynamic SLAY window
            calculation (``pre_s = pre_onset_ms / 1000``).
        eye_validation: Eye movement validation parameters.
    """

    slay_pre_s: float = 0.05
    slay_post_s: float = 0.30
    pre_onset_ms: float = 50.0
    eye_validation: EyeValidationConfig = field(default_factory=EyeValidationConfig)


@dataclass
class DerivativesConfig:
    """ExportStage Phase 2.5 (session-level derivative files) parameters.

    Attributes:
        enabled: Phase 2.5 master switch. Disabling skips the entire
            ``07_derivatives/`` write.
        pre_onset_ms: Pre-stimulus raster window in milliseconds (relative
            to ``trials.start_time``).
        post_onset_ms: Post-stimulus raster window in milliseconds, or the
            literal string ``"auto"`` to have ``resolve_post_onset_ms``
            derive it from ``max(onset_time + offset_time)`` across BHV2
            ``VariableChanges``.
        bin_size_ms: Raster bin width in milliseconds.
        n_jobs: joblib parallelism for ``spike_times_to_raster``.
    """

    enabled: bool = True
    pre_onset_ms: float = 50.0
    post_onset_ms: float | str = "auto"
    bin_size_ms: float = 1.0
    n_jobs: int = 1


@dataclass
class ExportConfig:
    """ExportStage configuration.

    Attributes:
        derivatives: Phase 2.5 session-level derivative export settings
            (see :class:`DerivativesConfig`).
    """

    derivatives: DerivativesConfig = field(default_factory=DerivativesConfig)


@dataclass
class PipelineConfig:
    """Full pipeline configuration loaded from config/pipeline.yaml.

    Attributes:
        resources: CPU/memory resource settings.
        parallel: Multi-probe parallelism settings.
        preprocess: Preprocessing stage parameters.
        curation: Curation thresholds.
        sync: Synchronization parameters.
        postprocess: Postprocess stage parameters.
        merge: Optional auto-merge stage parameters.
        export: Export stage parameters (Phase 2.5 derivatives).
    """

    resources: ResourcesConfig = field(default_factory=ResourcesConfig)
    parallel: ParallelConfig = field(default_factory=ParallelConfig)
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    curation: CurationConfig = field(default_factory=CurationConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    postprocess: PostprocessConfig = field(default_factory=PostprocessConfig)
    merge: MergeConfig = field(default_factory=MergeConfig)
    export: ExportConfig = field(default_factory=ExportConfig)


@dataclass
class SorterParams:
    """Kilosort4 (or other sorter) parameters.

    Attributes:
        nblocks: Number of drift correction blocks (0 = disabled).
        Th_learned: Learning threshold.
        Th_universal: Universal threshold (KS4 default 9.0).
        cluster_downsampling: Cluster downsampling factor (KS4 default 20, pinned to 5).
        max_cluster_subset: Max cluster subset size (KS4 default 25000).
        do_CAR: Whether KS applies CAR internally (disable if preprocessed).
        batch_size: Number of samples per batch.
            "auto" = ResourceDetector recommends based on free GPU VRAM.
        n_jobs: Internal parallelism (usually 1 for GPU).
        torch_device: PyTorch device for sorting. "cuda" for GPU, "cpu" for CPU.
            "auto" = use CUDA if available, else CPU.
    """

    nblocks: int = 0
    Th_learned: float = 8.0
    Th_universal: float = 9.0
    cluster_downsampling: int = 1
    max_cluster_subset: int = 25000
    do_CAR: bool = False
    batch_size: int | str = "auto"
    n_jobs: int = 1
    torch_device: str = "auto"


@dataclass
class SorterConfig:
    """Local sorter configuration.

    Attributes:
        name: SpikeInterface sorter name (e.g. "kilosort4").
        params: Sorter-specific parameter dict.
    """

    name: str = "kilosort4"
    params: SorterParams = field(default_factory=SorterParams)


@dataclass
class ImportConfig:
    """External sorting result import configuration.

    Attributes:
        format: Format of the external results ("kilosort4" or "phy").
        paths: Optional mapping of probe_id → external sorting folder path.
    """

    format: str = "kilosort4"
    paths: dict[str, Path] = field(default_factory=dict)


@dataclass
class RandomSpikesConfig:
    """Random spike sampling parameters for SortingAnalyzer.

    Attributes:
        max_spikes_per_unit: Maximum spikes sampled per unit.
        method: Sampling method (e.g. "uniform").
    """

    max_spikes_per_unit: int = 500
    method: str = "uniform"


@dataclass
class WaveformConfig:
    """Waveform extraction parameters for SortingAnalyzer.

    Attributes:
        ms_before: Pre-spike window in milliseconds.
        ms_after: Post-spike window in milliseconds.
    """

    ms_before: float = 1.0
    ms_after: float = 2.0


@dataclass
class AnalyzerConfig:
    """SortingAnalyzer postprocessing parameters.

    Attributes:
        random_spikes: Random spike sampling settings.
        waveforms: Waveform extraction settings.
        template_operators: List of operators for template computation.
        unit_locations_method: Spatial localization method.
        template_similarity_method: Template similarity computation method.
    """

    random_spikes: RandomSpikesConfig = field(default_factory=RandomSpikesConfig)
    waveforms: WaveformConfig = field(default_factory=WaveformConfig)
    template_operators: list[str] = field(default_factory=lambda: ["average", "std"])
    unit_locations_method: str = "monopolar_triangulation"
    template_similarity_method: str = "cosine_similarity"


@dataclass
class SortingConfig:
    """Full sorting configuration loaded from config/sorting.yaml.

    Attributes:
        mode: "local" to run sorter locally, "import" to load external results.
        sorter: Local sorter settings (used when mode == "local").
        import_cfg: Import settings (used when mode == "import").
        analyzer: Postprocessing analyzer settings.
    """

    mode: str = "local"
    sorter: SorterConfig = field(default_factory=SorterConfig)
    import_cfg: ImportConfig = field(default_factory=ImportConfig)
    analyzer: AnalyzerConfig = field(default_factory=AnalyzerConfig)


def _extract_known(raw: dict, dc_class: type) -> dict:
    """Return only the keys in *raw* that are valid fields of *dc_class*.

    Unknown keys are logged at DEBUG level and silently ignored.

    Args:
        raw: Raw dict from a YAML section.
        dc_class: Dataclass type whose fields define the valid key set.

    Returns:
        Filtered dict containing only known field names.
    """
    valid_fields = {f.name for f in dataclasses.fields(dc_class)}
    known: dict = {}
    for key, value in raw.items():
        if key in valid_fields:
            known[key] = value
        else:
            section = dc_class.__name__
            _log.debug("unknown config key ignored", key=key, section=section)
    return known


def _build_resources(raw: dict) -> ResourcesConfig:
    """Build a ResourcesConfig from a raw YAML dict.

    Args:
        raw: Mapping of resource config keys. Unknown keys are ignored.

    Returns:
        ResourcesConfig with known keys applied and defaults for the rest.
    """
    return ResourcesConfig(**_extract_known(raw, ResourcesConfig))


def _build_parallel(raw: dict) -> ParallelConfig:
    """Build a ParallelConfig from a raw YAML dict.

    Args:
        raw: Mapping of parallel config keys. Unknown keys are ignored.

    Returns:
        ParallelConfig with known keys applied and defaults for the rest.
    """
    return ParallelConfig(**_extract_known(raw, ParallelConfig))


def _build_bandpass(raw: dict) -> BandpassConfig:
    """Build a BandpassConfig from a raw YAML dict.

    Args:
        raw: Mapping of bandpass filter keys. Unknown keys are ignored.

    Returns:
        BandpassConfig with known keys applied and defaults for the rest.
    """
    return BandpassConfig(**_extract_known(raw, BandpassConfig))


def _build_bad_channel(raw: dict) -> BadChannelConfig:
    """Build a BadChannelConfig from a raw YAML dict.

    Args:
        raw: Mapping of bad channel detection keys. Unknown keys are ignored.

    Returns:
        BadChannelConfig with known keys applied and defaults for the rest.
    """
    return BadChannelConfig(**_extract_known(raw, BadChannelConfig))


def _build_common_reference(raw: dict) -> CommonReferenceConfig:
    """Build a CommonReferenceConfig from a raw YAML dict.

    Args:
        raw: Mapping of common reference keys. Unknown keys are ignored.

    Returns:
        CommonReferenceConfig with known keys applied and defaults for the rest.
    """
    return CommonReferenceConfig(**_extract_known(raw, CommonReferenceConfig))


def _build_motion_correction(raw: dict) -> MotionCorrectionConfig:
    """Build a MotionCorrectionConfig from a raw YAML dict.

    ``method`` may be ``None`` (YAML ``null``) to disable motion correction.

    Args:
        raw: Mapping of motion correction keys. Unknown keys are ignored.

    Returns:
        MotionCorrectionConfig with known keys applied and defaults for the rest.
    """
    return MotionCorrectionConfig(**_extract_known(raw, MotionCorrectionConfig))


def _build_preprocess(raw: dict) -> PreprocessConfig:
    """Build a PreprocessConfig from a raw YAML dict, recursing into sub-sections.

    Calls ``_build_bandpass``, ``_build_bad_channel``,
    ``_build_common_reference``, and ``_build_motion_correction`` for their
    respective sub-dicts.  Unknown top-level keys are ignored.

    Args:
        raw: Mapping of preprocess config keys. Unknown keys are ignored.

    Returns:
        PreprocessConfig with all nested configs populated.
    """
    bandpass = _build_bandpass(raw.get("bandpass") or {})
    bad_channel = _build_bad_channel(raw.get("bad_channel_detection") or {})
    common_ref = _build_common_reference(raw.get("common_reference") or {})
    motion_corr = _build_motion_correction(raw.get("motion_correction") or {})

    # Log unknown top-level keys (not sub-section keys we handle explicitly).
    handled = {"bandpass", "bad_channel_detection", "common_reference", "motion_correction"}
    for key in raw:
        if key not in handled:
            _log.debug("unknown config key ignored", key=key, section="PreprocessConfig")

    return PreprocessConfig(
        bandpass=bandpass,
        bad_channel_detection=bad_channel,
        common_reference=common_ref,
        motion_correction=motion_corr,
    )


def _build_bombcell(raw: dict) -> BombcellConfig:
    """Build a BombcellConfig from a raw YAML dict.

    ``extra_overrides`` (a nested dict for deep-merging into SI's thresholds)
    is passed through unchanged; all other keys are filtered by the
    dataclass field set.
    """
    return BombcellConfig(**_extract_known(raw, BombcellConfig))


def _build_curation(raw: dict) -> CurationConfig:
    """Build a CurationConfig from a raw YAML dict, recursing into ``bombcell``.

    Args:
        raw: Mapping of curation threshold keys. Unknown top-level keys are
            ignored. The ``bombcell`` sub-dict (if present) is built into a
            ``BombcellConfig`` dataclass.

    Returns:
        CurationConfig with known keys applied and defaults for the rest,
        including a fully-populated ``bombcell`` nested config.
    """
    bombcell = _build_bombcell(raw.get("bombcell") or {})
    handled = {"bombcell"}
    top_known = _extract_known({k: v for k, v in raw.items() if k not in handled}, CurationConfig)
    return CurationConfig(bombcell=bombcell, **top_known)


def _build_eye_validation(raw: dict) -> EyeValidationConfig:
    """Build an EyeValidationConfig from a raw YAML dict.

    Args:
        raw: Mapping of eye validation config keys. Unknown keys are ignored.

    Returns:
        EyeValidationConfig with known keys applied and defaults for the rest.
    """
    return EyeValidationConfig(**_extract_known(raw, EyeValidationConfig))


def _build_postprocess(raw: dict) -> PostprocessConfig:
    """Build a PostprocessConfig from a raw YAML dict, recursing into sub-sections.

    Args:
        raw: Mapping of postprocess config keys. Unknown keys are ignored.

    Returns:
        PostprocessConfig with all nested configs populated.
    """
    eye_validation = _build_eye_validation(raw.get("eye_validation") or {})

    handled = {"eye_validation"}
    top_known = _extract_known(
        {k: v for k, v in raw.items() if k not in handled}, PostprocessConfig
    )

    return PostprocessConfig(eye_validation=eye_validation, **top_known)


def _build_merge(raw: dict) -> MergeConfig:
    """Build a MergeConfig from a raw YAML dict.

    Args:
        raw: Mapping of merge config keys. Unknown keys are ignored.

    Returns:
        MergeConfig with known keys applied and defaults for the rest.
    """
    return MergeConfig(**_extract_known(raw, MergeConfig))


def _build_derivatives(raw: dict) -> DerivativesConfig:
    """Build a DerivativesConfig from a raw YAML dict.

    Accepts ``post_onset_ms`` as either a number or the literal string
    ``"auto"`` (passed straight through — resolved at runtime).
    """
    return DerivativesConfig(**_extract_known(raw, DerivativesConfig))


def _build_export(raw: dict) -> ExportConfig:
    """Build an ExportConfig (including nested derivatives) from raw YAML."""
    return ExportConfig(
        derivatives=_build_derivatives(raw.get("derivatives") or {}),
    )


def _build_sync(raw: dict) -> SyncConfig:
    """Build a SyncConfig from a raw YAML dict.

    ``event_bits`` is always returned as a ``list[int]`` regardless of the
    YAML representation.

    Args:
        raw: Mapping of sync config keys. Unknown keys are ignored.

    Returns:
        SyncConfig with known keys applied and defaults for the rest.
    """
    known = _extract_known(raw, SyncConfig)
    if "event_bits" in known:
        known["event_bits"] = [int(b) for b in known["event_bits"]]
    return SyncConfig(**known)


def _build_sorter(raw: dict) -> SorterConfig:
    """Build a SorterConfig from a raw YAML dict, recursing into ``params``.

    The ``params`` sub-dict is built into a ``SorterParams`` dataclass.
    Unknown keys at both levels are silently ignored.

    Args:
        raw: Mapping of sorter config keys. Unknown keys are ignored.

    Returns:
        SorterConfig with nested SorterParams populated.
    """
    params = SorterParams(**_extract_known(raw.get("params") or {}, SorterParams))
    known = _extract_known(raw, SorterConfig)
    # Replace the raw params dict (if any) with the built SorterParams object.
    known.pop("params", None)
    return SorterConfig(params=params, **known)


def _build_import_cfg(raw: dict) -> ImportConfig:
    """Build an ImportConfig from a raw YAML dict.

    String values in ``paths`` are converted to :class:`pathlib.Path` objects.

    Args:
        raw: Mapping of import config keys. Unknown keys are ignored.

    Returns:
        ImportConfig with ``paths`` values as Path objects.
    """
    known = _extract_known(raw, ImportConfig)
    if "paths" in known:
        known["paths"] = {k: Path(v) for k, v in known["paths"].items()}
    return ImportConfig(**known)


def _build_analyzer(raw: dict) -> AnalyzerConfig:
    """Build an AnalyzerConfig from a raw YAML dict, recursing into sub-sections.

    Builds nested ``RandomSpikesConfig`` and ``WaveformConfig`` from their
    respective sub-dicts.  Unknown keys at all levels are silently ignored.

    Args:
        raw: Mapping of analyzer config keys. Unknown keys are ignored.

    Returns:
        AnalyzerConfig with all nested configs populated.
    """
    random_spikes = RandomSpikesConfig(
        **_extract_known(raw.get("random_spikes") or {}, RandomSpikesConfig)
    )
    waveforms = WaveformConfig(**_extract_known(raw.get("waveforms") or {}, WaveformConfig))

    # Log unknown top-level keys (excluding handled sub-section keys).
    handled = {"random_spikes", "waveforms"}
    top_known = _extract_known({k: v for k, v in raw.items() if k not in handled}, AnalyzerConfig)

    return AnalyzerConfig(random_spikes=random_spikes, waveforms=waveforms, **top_known)


def _validate_pipeline_config(config: PipelineConfig) -> None:
    """Validate all fields of a PipelineConfig, raising ConfigError on violations.

    Args:
        config: The PipelineConfig to validate.

    Raises:
        ConfigError: If any field violates its constraint.
    """
    r = config.resources
    # resources.n_jobs
    if r.n_jobs != "auto" and not (isinstance(r.n_jobs, int) and r.n_jobs >= 1):
        raise ConfigError("resources.n_jobs", r.n_jobs, "must be 'auto' or int >= 1")
    # resources.chunk_duration
    if r.chunk_duration != "auto" and not re.fullmatch(r"^\d+\.?\d*s$", r.chunk_duration):
        raise ConfigError(
            "resources.chunk_duration",
            r.chunk_duration,
            r"must be 'auto' or match '^\d+\.?\d*s$' (e.g. '1s', '0.5s')",
        )
    # resources.max_memory
    if r.max_memory != "auto" and not re.fullmatch(r"^\d+[GM]$", r.max_memory):
        raise ConfigError(
            "resources.max_memory",
            r.max_memory,
            r"must be 'auto' or match '^\d+[GM]$' (e.g. '32G', '512M')",
        )

    p = config.parallel
    # parallel.max_workers
    if p.max_workers != "auto" and not (isinstance(p.max_workers, int) and p.max_workers >= 1):
        raise ConfigError("parallel.max_workers", p.max_workers, "must be 'auto' or int >= 1")

    bp = config.preprocess.bandpass
    # preprocess.bandpass.freq_min
    if bp.freq_min <= 0:
        raise ConfigError(
            "preprocess.bandpass.freq_min",
            bp.freq_min,
            "must be > 0",
        )
    # preprocess.bandpass.freq_max
    if bp.freq_max <= bp.freq_min:
        raise ConfigError(
            "preprocess.bandpass.freq_max",
            bp.freq_max,
            "must be > freq_min",
        )

    bcd = config.preprocess.bad_channel_detection
    # preprocess.bad_channel_detection.dead_channel_threshold
    if not (0 < bcd.dead_channel_threshold < 1):
        raise ConfigError(
            "preprocess.bad_channel_detection.dead_channel_threshold",
            bcd.dead_channel_threshold,
            "must satisfy 0 < x < 1",
        )

    cr = config.preprocess.common_reference
    # preprocess.common_reference.reference
    if cr.reference not in {"global", "local"}:
        raise ConfigError(
            "preprocess.common_reference.reference",
            cr.reference,
            "must be 'global' or 'local'",
        )
    # preprocess.common_reference.operator
    if cr.operator not in {"median", "average"}:
        raise ConfigError(
            "preprocess.common_reference.operator",
            cr.operator,
            "must be 'median' or 'average'",
        )

    mc = config.preprocess.motion_correction
    # preprocess.motion_correction.method
    if mc.method not in {"dredge", "kilosort", None}:
        raise ConfigError(
            "preprocess.motion_correction.method",
            mc.method,
            "must be 'dredge', 'kilosort', or None",
        )
    # preprocess.motion_correction.preset
    _valid_presets = {
        "dredge",
        "dredge_fast",
        "nonrigid_accurate",
        "nonrigid_fast_and_accurate",
        "rigid_fast",
        "kilosort_like",
        "medicine",
    }
    if mc.preset not in _valid_presets:
        raise ConfigError(
            "preprocess.motion_correction.preset",
            mc.preset,
            f"must be one of {sorted(_valid_presets)}",
        )

    c = config.curation
    # curation.isi_violation_ratio_max
    if c.isi_violation_ratio_max < 0.0:
        raise ConfigError(
            "curation.isi_violation_ratio_max",
            c.isi_violation_ratio_max,
            "must be >= 0.0",
        )
    # curation.amplitude_cutoff_max
    if not (0.0 <= c.amplitude_cutoff_max <= 1.0):
        raise ConfigError(
            "curation.amplitude_cutoff_max",
            c.amplitude_cutoff_max,
            "must satisfy 0.0 <= x <= 1.0",
        )
    # curation.presence_ratio_min
    if not (0.0 <= c.presence_ratio_min <= 1.0):
        raise ConfigError(
            "curation.presence_ratio_min",
            c.presence_ratio_min,
            "must satisfy 0.0 <= x <= 1.0",
        )
    # curation.snr_min
    if c.snr_min < 0.0:
        raise ConfigError("curation.snr_min", c.snr_min, "must be >= 0.0")
    # curation.good_isi_max
    if c.good_isi_max < 0.0:
        raise ConfigError("curation.good_isi_max", c.good_isi_max, "must be >= 0.0")
    # curation.good_snr_min
    if c.good_snr_min < 0.0:
        raise ConfigError("curation.good_snr_min", c.good_snr_min, "must be >= 0.0")

    s = config.sync
    # sync.imec_sync_bit (AP)
    if not (0 <= s.imec_sync_bit <= 7):
        raise ConfigError("sync.imec_sync_bit", s.imec_sync_bit, "must satisfy 0 <= x <= 7")
    # sync.nidq_sync_bit
    if not (0 <= s.nidq_sync_bit <= 7):
        raise ConfigError("sync.nidq_sync_bit", s.nidq_sync_bit, "must satisfy 0 <= x <= 7")
    # sync.event_bits
    if not s.event_bits:
        raise ConfigError("sync.event_bits", s.event_bits, "must be a non-empty list")
    for bit in s.event_bits:
        if not (0 <= bit <= 7):
            raise ConfigError(
                "sync.event_bits",
                s.event_bits,
                f"each element must satisfy 0 <= x <= 7, got {bit}",
            )
    # sync.max_time_error_ms
    if s.max_time_error_ms <= 0:
        raise ConfigError("sync.max_time_error_ms", s.max_time_error_ms, "must be > 0")
    # sync.trial_count_tolerance
    if s.trial_count_tolerance < 0:
        raise ConfigError("sync.trial_count_tolerance", s.trial_count_tolerance, "must be >= 0")
    # sync.stim_onset_code
    if not (0 <= s.stim_onset_code <= 255):
        raise ConfigError("sync.stim_onset_code", s.stim_onset_code, "must satisfy 0 <= x <= 255")
    # sync.stim_onset_bit
    if s.stim_onset_bit is not None and not (0 <= s.stim_onset_bit <= 7):
        raise ConfigError("sync.stim_onset_bit", s.stim_onset_bit, "must be None or in range 0-7")
    # sync.stim_count_tolerance
    if s.stim_count_tolerance < 0:
        raise ConfigError("sync.stim_count_tolerance", s.stim_count_tolerance, "must be >= 0")


def _validate_sorting_config(config: SortingConfig) -> None:
    """Validate all fields of a SortingConfig, raising ConfigError on violations.

    Args:
        config: The SortingConfig to validate.

    Raises:
        ConfigError: If any field violates its constraint.
    """
    # sorting.mode
    if config.mode not in {"local", "import"}:
        raise ConfigError("sorting.mode", config.mode, "must be 'local' or 'import'")

    sp = config.sorter.params
    # sorter.params.nblocks
    if sp.nblocks < 0:
        raise ConfigError("sorter.params.nblocks", sp.nblocks, "must be >= 0")
    # sorter.params.Th_learned
    if sp.Th_learned <= 0:
        raise ConfigError("sorter.params.Th_learned", sp.Th_learned, "must be > 0")
    # sorter.params.batch_size
    if sp.batch_size != "auto" and not (isinstance(sp.batch_size, int) and sp.batch_size >= 1):
        raise ConfigError(
            "sorter.params.batch_size",
            sp.batch_size,
            "must be 'auto' or int >= 1",
        )
    # sorter.params.n_jobs
    if sp.n_jobs < 1:
        raise ConfigError("sorter.params.n_jobs", sp.n_jobs, "must be >= 1")
    # sorter.params.torch_device
    if sp.torch_device not in {"auto", "cuda", "cpu"}:
        raise ConfigError(
            "sorter.params.torch_device",
            sp.torch_device,
            "must be 'auto', 'cuda', or 'cpu'",
        )

    # import_cfg.format
    if config.import_cfg.format not in {"kilosort4", "phy"}:
        raise ConfigError(
            "import_cfg.format",
            config.import_cfg.format,
            "must be 'kilosort4' or 'phy'",
        )

    rs = config.analyzer.random_spikes
    # analyzer.random_spikes.max_spikes_per_unit
    if rs.max_spikes_per_unit < 1:
        raise ConfigError(
            "analyzer.random_spikes.max_spikes_per_unit",
            rs.max_spikes_per_unit,
            "must be >= 1",
        )
    # analyzer.random_spikes.method
    if rs.method not in {"uniform", "all", "smart"}:
        raise ConfigError(
            "analyzer.random_spikes.method",
            rs.method,
            "must be 'uniform', 'all', or 'smart'",
        )

    wf = config.analyzer.waveforms
    # analyzer.waveforms.ms_before
    if wf.ms_before <= 0:
        raise ConfigError("analyzer.waveforms.ms_before", wf.ms_before, "must be > 0")
    # analyzer.waveforms.ms_after
    if wf.ms_after <= 0:
        raise ConfigError("analyzer.waveforms.ms_after", wf.ms_after, "must be > 0")


def _validate_subject(raw: dict) -> None:
    """Validate required fields in a raw subject dict, raising ConfigError on violations.

    Checks that required DANDI fields exist and that sex/age values conform to spec.

    Args:
        raw: Raw dict from the subject YAML (the ``Subject:`` block or full dict).

    Raises:
        ConfigError: If a required field is missing or has an invalid value.
    """
    _REQUIRED = ("subject_id", "description", "species", "sex", "age")
    for field_name in _REQUIRED:
        if field_name not in raw:
            raise ConfigError(
                f"subject.{field_name}",
                None,
                f"required field '{field_name}' is missing",
            )

    # subject.sex
    if raw["sex"] not in {"M", "F", "U", "O"}:
        raise ConfigError(
            "subject.sex",
            raw["sex"],
            "must be one of 'M', 'F', 'U', 'O'",
        )

    # subject.age — ISO 8601 simplified duration: P + digits + single letter (Y/M/D)
    if not re.fullmatch(r"^P\d+[YMD]$", raw["age"]):
        raise ConfigError(
            "subject.age",
            raw["age"],
            r"must match ISO 8601 duration pattern '^P\d+[YMD]$' (e.g. 'P4Y', 'P6M', 'P30D')",
        )


def _config_to_dict(config: PipelineConfig | SortingConfig) -> dict:
    """Convert config dataclass to nested dict using dataclasses.asdict().

    Args:
        config: A PipelineConfig or SortingConfig dataclass instance.

    Returns:
        Nested dict representation of the config. Path values are converted to str.
    """
    raw = dataclasses.asdict(config)
    return raw


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base, returning a new dict (does not mutate base).

    For each key in override:
    - If both base[key] and override[key] are dicts, recursively merge them.
    - Otherwise, override[key] replaces base[key].
    Keys in base not present in override are kept unchanged.

    Args:
        base: The base dict to merge into.
        override: The override dict whose values take precedence.

    Returns:
        New merged dict.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_pipeline_config(config_path: Path | None = None) -> PipelineConfig:
    """Load and validate pipeline.yaml into a PipelineConfig dataclass.

    If config_path is None or the file does not exist, all fields are populated
    with built-in defaults and an INFO log message is emitted.

    Args:
        config_path: Path to the pipeline.yaml file, or None to use defaults.

    Returns:
        Fully populated PipelineConfig with defaults applied for missing fields.

    Raises:
        ConfigError: If any field violates its constraint.
    """
    if config_path is None or not Path(config_path).exists():
        _log.info("pipeline.yaml not found, using defaults", path=str(config_path))
        raw: dict = {}
    else:
        raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}

    # Log unknown top-level keys
    known_top_keys = {
        "resources",
        "parallel",
        "preprocess",
        "curation",
        "sync",
        "postprocess",
        "merge",
        "export",
    }
    for key in raw:
        if key not in known_top_keys:
            _log.debug("unknown config key ignored", key=key, section="PipelineConfig")

    config = PipelineConfig(
        resources=_build_resources(raw.get("resources") or {}),
        parallel=_build_parallel(raw.get("parallel") or {}),
        preprocess=_build_preprocess(raw.get("preprocess") or {}),
        curation=_build_curation(raw.get("curation") or {}),
        sync=_build_sync(raw.get("sync") or {}),
        postprocess=_build_postprocess(raw.get("postprocess") or {}),
        merge=_build_merge(raw.get("merge") or {}),
        export=_build_export(raw.get("export") or {}),
    )

    _validate_pipeline_config(config)
    return config


def load_sorting_config(config_path: Path | None = None) -> SortingConfig:
    """Load and validate sorting.yaml into a SortingConfig dataclass.

    If config_path is None or the file does not exist, all fields are populated
    with built-in defaults and an INFO log message is emitted.

    Note:
        The YAML key ``import`` (a Python reserved word) maps to the
        ``import_cfg`` attribute of :class:`SortingConfig`.

    Args:
        config_path: Path to the sorting.yaml file, or None to use defaults.

    Returns:
        Fully populated SortingConfig with defaults applied for missing fields.

    Raises:
        ConfigError: If any field violates its constraint.
    """
    if config_path is None or not Path(config_path).exists():
        _log.info("sorting.yaml not found, using defaults", path=str(config_path))
        raw: dict = {}
    else:
        raw = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}

    # Log unknown top-level keys
    known_top_keys = {"mode", "sorter", "import", "analyzer"}
    for key in raw:
        if key not in known_top_keys:
            _log.debug("unknown config key ignored", key=key, section="SortingConfig")

    config = SortingConfig(
        mode=raw.get("mode", "local"),
        sorter=_build_sorter(raw.get("sorter") or {}),
        import_cfg=_build_import_cfg(raw.get("import") or {}),
        analyzer=_build_analyzer(raw.get("analyzer") or {}),
    )

    _validate_sorting_config(config)
    return config


def load_subject_config(yaml_path: Path) -> SubjectConfig:
    """Load a subject configuration from a monkeys/*.yaml file.

    Args:
        yaml_path: Path to the subject YAML file (e.g. monkeys/MaoDan.yaml).

    Returns:
        SubjectConfig populated from the YAML ``Subject:`` block.

    Raises:
        FileNotFoundError: If yaml_path does not exist.
        ConfigError: If required DANDI fields (subject_id, description, species,
            sex, age) are missing or have invalid values.
    """
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(yaml_path)

    raw_full = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    # Handle with/without top-level "Subject:" key
    subject_raw: dict = raw_full.get("Subject", raw_full) if isinstance(raw_full, dict) else {}

    _validate_subject(subject_raw)

    raw_vault = subject_raw.get("image_vault_paths") or []
    if not isinstance(raw_vault, list):
        raise ConfigError(
            "subject.image_vault_paths",
            raw_vault,
            "must be a list of path strings",
        )
    image_vault_paths = [Path(str(p)) for p in raw_vault]

    return SubjectConfig(
        subject_id=subject_raw["subject_id"],
        description=subject_raw["description"],
        species=subject_raw["species"],
        sex=subject_raw["sex"],
        age=subject_raw["age"],
        weight=subject_raw.get("weight", ""),
        image_vault_paths=image_vault_paths,
    )


def save_subject_config(cfg: SubjectConfig, yaml_path: Path) -> None:
    """Write a SubjectConfig to a YAML file with a top-level ``Subject:`` block.

    Format matches ``monkeys/MonkeyTemplate.yaml``. Missing parent directories
    are created automatically. Existing files are overwritten without warning —
    callers (e.g. the SubjectForm UI) are responsible for confirmation.

    Args:
        cfg: A fully-populated ``SubjectConfig`` to persist.
        yaml_path: Target file path (typically ``monkeys/<subject_id>.yaml``).
    """
    yaml_path = Path(yaml_path)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    subject_payload: dict[str, object] = {
        "subject_id": cfg.subject_id,
        "description": cfg.description,
        "species": cfg.species,
        "sex": cfg.sex,
        "age": cfg.age,
        "weight": cfg.weight,
    }
    if cfg.image_vault_paths:
        subject_payload["image_vault_paths"] = [str(p) for p in cfg.image_vault_paths]
    yaml_path.write_text(
        yaml.safe_dump({"Subject": subject_payload}, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def merge_with_overrides(
    config: PipelineConfig | SortingConfig,
    overrides: dict,
) -> PipelineConfig | SortingConfig:
    """Deep merge overrides into config, returning a validated new config object.

    The input config is never mutated.  The overrides dict uses the same
    nested key structure as the YAML files.  After merging, the full
    validation suite is re-run on the new config.

    Args:
        config: An existing PipelineConfig or SortingConfig instance.
        overrides: Nested dict of values to override, e.g.
            ``{"resources": {"n_jobs": 8}}``.

    Returns:
        A new PipelineConfig or SortingConfig with overrides applied.

    Raises:
        ConfigError: If the merged config violates any validation constraint.
        TypeError: If config is not a PipelineConfig or SortingConfig.
    """
    config_dict = _config_to_dict(config)
    merged = _deep_merge(config_dict, overrides)

    if isinstance(config, PipelineConfig):
        new_config = PipelineConfig(
            resources=_build_resources(merged.get("resources") or {}),
            parallel=_build_parallel(merged.get("parallel") or {}),
            preprocess=_build_preprocess(merged.get("preprocess") or {}),
            curation=_build_curation(merged.get("curation") or {}),
            sync=_build_sync(merged.get("sync") or {}),
            postprocess=_build_postprocess(merged.get("postprocess") or {}),
            export=_build_export(merged.get("export") or {}),
        )
        _validate_pipeline_config(new_config)
    elif isinstance(config, SortingConfig):
        # When rebuilding from _config_to_dict, the field is "import_cfg" (Python attr name),
        # not "import" (YAML key). We need to handle both.
        import_raw = merged.get("import_cfg") or merged.get("import") or {}
        new_config = SortingConfig(
            mode=merged.get("mode", "local"),
            sorter=_build_sorter(merged.get("sorter") or {}),
            import_cfg=_build_import_cfg(import_raw),
            analyzer=_build_analyzer(merged.get("analyzer") or {}),
        )
        _validate_sorting_config(new_config)
    else:
        raise TypeError(f"Expected PipelineConfig or SortingConfig, got {type(config)!r}")

    return new_config
