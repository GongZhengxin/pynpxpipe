"""YAML configuration loading and validation.

Loads pipeline.yaml and sorting.yaml into typed dataclasses.
No UI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


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
class MotionCorrectionConfig:
    """Motion correction (drift correction) parameters.

    Attributes:
        method: Method to use: "dredge", "kilosort", or None to skip.
        preset: Method-specific preset string.
    """

    method: str | None = "dredge"
    preset: str = "nonrigid_accurate"


@dataclass
class PreprocessConfig:
    """Preprocessing stage parameters.

    Attributes:
        bandpass: Bandpass filter settings.
        motion_correction: Motion correction settings.
    """

    bandpass: BandpassConfig = field(default_factory=BandpassConfig)
    motion_correction: MotionCorrectionConfig = field(default_factory=MotionCorrectionConfig)


@dataclass
class CurationConfig:
    """Quality metric thresholds for the curate stage.

    Attributes:
        isi_violation_ratio_max: ISI violation ratio upper bound (0–1).
        amplitude_cutoff_max: Amplitude cutoff upper bound (0–1).
        presence_ratio_min: Presence ratio lower bound (0–1).
        snr_min: Signal-to-noise ratio lower bound.
    """

    isi_violation_ratio_max: float = 0.1
    amplitude_cutoff_max: float = 0.1
    presence_ratio_min: float = 0.9
    snr_min: float = 0.5


@dataclass
class SyncConfig:
    """Time synchronization parameters for the synchronize stage.

    Attributes:
        sync_bit: Bit position of the SpikeGLX sync pulse in digital channels.
        event_bits: List of bit positions used by MonkeyLogic for event codes.
        max_time_error_ms: Maximum allowed IMEC↔NIDQ alignment error in ms.
        trial_count_tolerance: Maximum trial count mismatch for auto-repair.
        photodiode_channel_index: NIDQ analog channel index for the photodiode signal.
        monitor_delay_ms: Monitor system delay correction in ms (60 Hz ≈ -5).
        stim_onset_code: Event code value representing stimulus onset on NIDQ.
        imec_sync_code: Sync marker code value on IMEC digital channel.
        generate_plots: Whether to generate sync diagnostic plots.
    """

    sync_bit: int = 0
    event_bits: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    max_time_error_ms: float = 17.0
    trial_count_tolerance: int = 2
    photodiode_channel_index: int = 0
    monitor_delay_ms: float = -5.0
    stim_onset_code: int = 64
    imec_sync_code: int = 64
    generate_plots: bool = True


@dataclass
class PipelineConfig:
    """Full pipeline configuration loaded from config/pipeline.yaml.

    Attributes:
        resources: CPU/memory resource settings.
        parallel: Multi-probe parallelism settings.
        preprocess: Preprocessing stage parameters.
        curation: Curation thresholds.
        sync: Synchronization parameters.
    """

    resources: ResourcesConfig = field(default_factory=ResourcesConfig)
    parallel: ParallelConfig = field(default_factory=ParallelConfig)
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    curation: CurationConfig = field(default_factory=CurationConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)


@dataclass
class SorterParams:
    """Kilosort4 (or other sorter) parameters.

    Attributes:
        nblocks: Number of drift correction blocks (0 = disabled).
        Th_learned: Learning threshold.
        do_CAR: Whether KS applies CAR internally (disable if preprocessed).
        batch_size: Number of samples per batch.
            "auto" = ResourceDetector recommends based on free GPU VRAM.
        n_jobs: Internal parallelism (usually 1 for GPU).
    """

    nblocks: int = 15
    Th_learned: float = 7.0
    do_CAR: bool = False
    batch_size: int | str = "auto"
    n_jobs: int = 1


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
class WaveformConfig:
    """Waveform extraction parameters for SortingAnalyzer.

    Attributes:
        max_spikes_per_unit: Maximum spikes sampled per unit.
        ms_before: Pre-spike window in milliseconds.
        ms_after: Post-spike window in milliseconds.
    """

    max_spikes_per_unit: int = 500
    ms_before: float = 1.0
    ms_after: float = 2.0


@dataclass
class AnalyzerConfig:
    """SortingAnalyzer postprocessing parameters.

    Attributes:
        waveforms: Waveform extraction settings.
        unit_locations_method: Spatial localization method.
        template_similarity_method: Template similarity computation method.
    """

    waveforms: WaveformConfig = field(default_factory=WaveformConfig)
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


def load_pipeline_config(config_path: Path) -> PipelineConfig:
    """Load and validate pipeline.yaml into a PipelineConfig dataclass.

    Args:
        config_path: Path to the pipeline.yaml file.

    Returns:
        Fully populated PipelineConfig with defaults applied for missing fields.

    Raises:
        FileNotFoundError: If config_path does not exist.
        ValueError: If a required field has an invalid value (e.g. n_jobs < -1).
    """
    raise NotImplementedError("TODO")


def load_sorting_config(config_path: Path) -> SortingConfig:
    """Load and validate sorting.yaml into a SortingConfig dataclass.

    Args:
        config_path: Path to the sorting.yaml file.

    Returns:
        Fully populated SortingConfig with defaults applied for missing fields.

    Raises:
        FileNotFoundError: If config_path does not exist.
        ValueError: If mode is not "local" or "import".
    """
    raise NotImplementedError("TODO")


def load_subject_config(yaml_path: Path) -> "SubjectConfig":  # noqa: F821
    """Load a subject configuration from a monkeys/*.yaml file.

    Args:
        yaml_path: Path to the subject YAML file (e.g. monkeys/MaoDan.yaml).

    Returns:
        SubjectConfig populated from the YAML ``Subject:`` block.

    Raises:
        FileNotFoundError: If yaml_path does not exist.
        ValueError: If required DANDI fields (subject_id, species, sex, age) are missing.
    """
    raise NotImplementedError("TODO")
