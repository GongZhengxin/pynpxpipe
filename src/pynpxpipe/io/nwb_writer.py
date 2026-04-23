"""NWB file generation for multi-probe electrophysiology data.

Wraps pynwb to write NWB 2.x files conforming to DANDI archive standards.
All probes are written to a single NWB file. No UI dependencies.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import numpy as np
import pandas as pd
from hdmf.backends.hdf5.h5_utils import H5DataIO
from hdmf.data_utils import GenericDataChunkIterator
from pynwb import NWBHDF5IO, NWBFile, TimeSeries
from pynwb.ecephys import ElectricalSeries
from pynwb.file import Subject as NWBSubject

from pynpxpipe.core.errors import DiscoverError, ExportError
from pynpxpipe.io.spikeglx import SpikeGLXDiscovery, SpikeGLXLoader

if TYPE_CHECKING:
    import spikeinterface.core as si

    from pynpxpipe.core.session import ProbeInfo, Session

logger = logging.getLogger(__name__)

# Reference probe for the trials-table primary clock. Hardcoded by design
# (E1.1): all NWB files emitted by pynpxpipe anchor start_time / stop_time /
# stim_onset_time to imec0's IMEC clock so that `units.spike_times` and
# `trials.start_time` share one timebase. Per-probe onsets remain available
# as `stim_onset_imec_{probe_id}` columns for reprocessing.
_REFERENCE_PROBE = "imec0"

# E3.1 — scratch key for the full effective PipelineConfig JSON payload.
_PIPELINE_CONFIG_SCRATCH_KEY = "pipeline_config"
_PIPELINE_CONFIG_DESCRIPTION = (
    "Effective PipelineConfig serialized with dataclasses.asdict + json.dumps"
)

# E3.3 — scratch key for stim_name lookup provenance (dataset_name,
# resolved tsv path, resolution source tag). Written only when a BHV2
# DatasetName was present; absence means the session had no stim tsv.
_STIM_NAME_PROVENANCE_KEY = "stim_name_provenance"
_STIM_NAME_PROVENANCE_DESCRIPTION = (
    "stim_name lookup provenance: BHV2 UserVars.DatasetName, the resolved "
    "tsv path used (after optional image_vault_paths fallback), and the "
    "resolver source tag."
)

# DANDI-compliant whitelist for pynwb's Subject. Any extra fields on
# ``SubjectConfig`` (e.g. pipeline-internal ``image_vault_paths``) are
# filtered out by ``_build_subject`` before constructing NWBSubject.
_NWB_SUBJECT_FIELDS: tuple[str, ...] = (
    "subject_id",
    "description",
    "species",
    "sex",
    "age",
    "weight",
)


def _build_subject(subject: object) -> NWBSubject:
    """Construct ``pynwb.file.Subject`` from the DANDI-whitelisted fields only.

    ``SubjectConfig`` carries pipeline-internal fields like
    ``image_vault_paths`` that are not part of the DANDI schema. This helper
    selects only the whitelisted subset (``_NWB_SUBJECT_FIELDS``) so that the
    resulting NWB file stays DANDI-valid regardless of which extra
    config-layer fields exist now or in the future.

    Args:
        subject: A ``SubjectConfig`` (or duck-typed equivalent) exposing the
            DANDI fields as attributes.

    Returns:
        A fresh ``NWBSubject`` populated from the whitelisted attributes;
        ``weight`` is coerced to ``None`` when the source string is empty
        (pynwb treats ``""`` as a value rather than "not provided").
    """
    payload: dict[str, object] = {}
    for field_name in _NWB_SUBJECT_FIELDS:
        value = getattr(subject, field_name, None)
        if field_name == "weight" and not value:
            payload["weight"] = None
            continue
        payload[field_name] = value
    return NWBSubject(**payload)


def _safe_int(unit_id, fallback: int) -> int:
    """Convert unit_id to int, falling back to index if non-numeric."""
    try:
        return int(unit_id)
    except (ValueError, TypeError):
        return fallback


def _build_nidq_description(meta: dict[str, str], session: Session) -> str:
    """Build the description string for the NIDQ_raw TimeSeries.

    The description must embed enough of the original SpikeGLX .nidq.meta
    (``niAiRangeMax``, ``niSampRate``, ``snsMnMaXaDw``, optional ``niMNGain`` /
    ``niMAGain``) and the pipeline's sync-bit contract (``event_bits`` /
    ``sync_bit``) that downstream readers can decode analog channels to volts
    and digital bits to events without reparsing the original meta file.

    Args:
        meta: Parsed NIDQ meta dict (string values).
        session: Pipeline Session; ``session.config.sync`` supplies the
            ``event_bits`` list and ``nidq_sync_bit`` if a PipelineConfig is
            attached. When absent, defaults from
            ``pynpxpipe.core.config.SyncConfig`` are used.

    Returns:
        Human + machine readable multi-line description string. All required
        literal substrings are always present: ``niAiRangeMax=``,
        ``niSampRate=``, ``event_bits=``, ``sync_bit=``.
    """
    # Default sync fields — falls back to SyncConfig defaults when the
    # session has no PipelineConfig attached (e.g. direct NWBWriter use).
    event_bits: list[int] = [1, 2, 3, 4, 5, 6, 7]
    sync_bit: int = 0
    cfg = getattr(session, "config", None)
    sync_cfg = getattr(cfg, "sync", None) if cfg is not None else None
    if sync_cfg is not None:
        event_bits = list(getattr(sync_cfg, "event_bits", event_bits))
        sync_bit = int(getattr(sync_cfg, "nidq_sync_bit", sync_bit))

    parts: list[str] = [
        "Raw NIDQ recording (SpikeGLX); int16, all analog + digital channels preserved.",
        "Analog channels: V = (sample * conversion). Digital word: bits packed into "
        "last channel(s) per snsMnMaXaDw; readers must extract bits using the "
        "sync_bit / event_bits indices below.",
        f"niAiRangeMax={meta.get('niAiRangeMax', '')}",
        f"niSampRate={meta.get('niSampRate', '')}",
    ]
    if "snsMnMaXaDw" in meta:
        parts.append(f"snsMnMaXaDw={meta['snsMnMaXaDw']}")
    if "niMNGain" in meta:
        parts.append(f"niMNGain={meta['niMNGain']}")
    if "niMAGain" in meta:
        parts.append(f"niMAGain={meta['niMAGain']}")
    parts.append(f"sync_bit={sync_bit}")
    parts.append(f"event_bits={event_bits}")
    return " | ".join(parts)


def _collect_imec_nidq_fits(sync_dir: Path) -> dict:
    """Read per-probe IMEC↔NIDQ linear fits from ``sync_dir``.

    Iterates ``*_imec_nidq.json`` files; each is expected to carry the
    linear-fit coefficients ``{a, b, rmse, n_pulses}`` produced by the
    synchronize stage. The probe_id is extracted from the filename stem
    (everything before ``_imec_nidq``). Corrupt or unreadable files are
    skipped with a warning so a single bad file cannot block export.

    Args:
        sync_dir: Directory that may contain ``{probe_id}_imec_nidq.json``.

    Returns:
        Mapping ``{probe_id: payload}``. If no per-probe files are found the
        result is ``{"_missing": True}`` — a sentinel downstream code can
        detect without confusing it with "zero probes found".
    """
    fits: dict[str, object] = {}
    if not sync_dir.exists() or not sync_dir.is_dir():
        logger.warning(
            "sync_tables: no sync_dir at %s; IMEC↔NIDQ fits marked missing",
            sync_dir,
        )
        return {"_missing": True}

    matches = sorted(sync_dir.glob("*_imec_nidq.json"))
    if not matches:
        logger.warning(
            "sync_tables: no *_imec_nidq.json files in %s; fits marked missing",
            sync_dir,
        )
        return {"_missing": True}

    for path in matches:
        probe_id = path.stem.replace("_imec_nidq", "")
        try:
            fits[probe_id] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("sync_tables: could not read %s: %s", path, exc)

    if not fits:
        return {"_missing": True}
    return fits


def _collect_photodiode_rows(behavior_events: pd.DataFrame | None) -> list | dict:
    """Extract PD-calibrated onset rows from a behavior events DataFrame.

    Only trials where ``pd_onset_nidq_s`` and ``ec_onset_nidq_s`` are both
    non-null are emitted. Latency is computed as
    ``ec_onset_nidq_s - pd_onset_nidq_s`` (NIDQ seconds). Trial index is the
    DataFrame row index preserved from ``behavior_events.reset_index``.

    Args:
        behavior_events: Optional events DataFrame.

    Returns:
        List of per-trial dicts, or ``{"_missing": True}`` if the DataFrame
        is missing or lacks the required columns.
    """
    if behavior_events is None:
        return {"_missing": True}
    required = {"pd_onset_nidq_s", "ec_onset_nidq_s"}
    if not required.issubset(behavior_events.columns):
        return {"_missing": True}

    rows: list[dict] = []
    for idx, row in behavior_events.reset_index(drop=True).iterrows():
        pd_val = row.get("pd_onset_nidq_s")
        ec_val = row.get("ec_onset_nidq_s")
        if pd.isna(pd_val) or pd.isna(ec_val):
            continue
        rows.append(
            {
                "trial_index": int(idx),
                "pd_onset_nidq_s": float(pd_val),
                "ec_onset_nidq_s": float(ec_val),
                "latency_s": float(ec_val) - float(pd_val),
            }
        )
    return rows


def _collect_event_code_rows(behavior_events: pd.DataFrame | None) -> list | dict:
    """Extract event-code triples (start / stim onset / reward) per trial.

    Matches the shape of what ``io/sync/bhv_nidq_align.py`` produces: a row
    per trial with NIDQ-second timestamps for the three key code events. All
    three columns are optional — missing columns emit None for that field.

    Args:
        behavior_events: Optional events DataFrame.

    Returns:
        List of per-trial dicts, or ``{"_missing": True}`` if the DataFrame
        is missing entirely.
    """
    if behavior_events is None:
        return {"_missing": True}
    df = behavior_events.reset_index(drop=True)
    rows: list[dict] = []
    for idx, row in df.iterrows():
        entry: dict[str, object] = {"trial_index": int(idx)}
        for col in ("onset_nidq_s", "stim_onset_nidq_s", "reward_nidq_s"):
            if col in df.columns:
                val = row.get(col)
                entry[_EVENT_CODE_COL_ALIAS[col]] = None if pd.isna(val) else float(val)
            else:
                entry[_EVENT_CODE_COL_ALIAS[col]] = None
        rows.append(entry)
    return rows


# Canonical JSON field names for the event-code block. Source columns in
# behavior_events use NIDQ-seconds names already, so the mapping is largely a
# rename from the "raw" aligner column → the "start/stim_onset/reward" triple
# documented in the sync_tables JSON schema.
_EVENT_CODE_COL_ALIAS = {
    "onset_nidq_s": "start_nidq_s",
    "stim_onset_nidq_s": "stim_onset_nidq_s",
    "reward_nidq_s": "reward_nidq_s",
}


def _get_compression_filter() -> dict:
    """Return H5DataIO kwargs for Blosc zstd compression, with gzip fallback.

    Returns:
        Dict of kwargs suitable for ``H5DataIO(..., **kwargs)``.
    """
    try:
        import hdf5plugin

        b = hdf5plugin.Blosc(cname="zstd", clevel=6, shuffle=hdf5plugin.Blosc.SHUFFLE)
        return {
            "compression": b.filter_id,
            "compression_opts": b.filter_options,
            "allow_plugin_filters": True,
        }
    except ImportError:
        return {"compression": "gzip", "compression_opts": 4}


class _Phase3Reporter:
    """Aggregates write + verify progress across all Phase 3 streams.

    Write phase maps to fraction range [0.0, 0.7], verify phase maps to
    [0.7, 1.0]. ``finalize()`` emits a terminal 1.0 regardless of totals so
    the caller's progress bar always lands on "done".

    Args:
        callback: User-supplied ``(msg, fraction)`` sink. When ``None`` the
            reporter is a cheap no-op.
    """

    _WRITE_CEIL = 0.7

    def __init__(self, callback: Callable[[str, float], None] | None) -> None:
        self._callback = callback
        self._total_writes = 0
        self._total_verifies = 0
        self._writes_done = 0
        self._verifies_done = 0
        self._last_fraction = 0.0

    @property
    def enabled(self) -> bool:
        return self._callback is not None

    def register_write_stream(self, num_buffers: int) -> None:
        self._total_writes += max(0, int(num_buffers))

    def register_verify_stream(self, num_chunks: int) -> None:
        self._total_verifies += max(0, int(num_chunks))

    def on_write(self, tag: str) -> None:
        self._writes_done += 1
        if self._callback is None:
            return
        denom = max(1, self._total_writes)
        raw = self._WRITE_CEIL * min(1.0, self._writes_done / denom)
        self._emit(f"append {tag}", raw)

    def on_verify(self, tag: str) -> None:
        self._verifies_done += 1
        if self._callback is None:
            return
        denom = max(1, self._total_verifies)
        raw = self._WRITE_CEIL + (1.0 - self._WRITE_CEIL) * min(1.0, self._verifies_done / denom)
        self._emit(f"verify {tag}", raw)

    def finalize(self) -> None:
        if self._callback is None:
            return
        self._emit("done", 1.0)

    def make_write_hook(self, tag: str) -> Callable[[], None]:
        def hook() -> None:
            self.on_write(tag)

        return hook

    def _emit(self, msg: str, raw_fraction: float) -> None:
        fraction = max(self._last_fraction, min(1.0, max(0.0, raw_fraction)))
        self._last_fraction = fraction
        assert self._callback is not None  # already guarded by callers
        self._callback(msg, fraction)


def _count_iterator_buffers(iterator: GenericDataChunkIterator) -> int:
    """Compute the total number of ``_get_data`` calls an iterator will make.

    The hdmf generic iterator walks ``maxshape`` in steps of ``buffer_shape``
    across every axis, so the total is the product of the per-axis ceils.
    Returns 1 for degenerate zero-length shapes so the reporter's denominator
    is never zero.
    """
    maxshape = iterator.maxshape
    buffer_shape = iterator.buffer_shape
    n = 1
    for ms, bs in zip(maxshape, buffer_shape, strict=False):
        if bs <= 0:
            return 1
        n *= max(1, (ms + bs - 1) // bs)
    return max(1, n)


class SpikeGLXDataChunkIterator(GenericDataChunkIterator):
    """Streams a SpikeInterface Recording into NWB via hdmf chunk iteration.

    Wraps ``BaseRecording.get_traces(return_scaled=False)`` to yield raw
    int16 chunks suitable for ``H5DataIO`` + ``ElectricalSeries``.

    Args:
        recording: Lazy SpikeInterface Recording (AP or LF).
        buffer_gb: RAM budget per buffer in GB (default 0.5).
        chunk_mb: Target HDF5 chunk size in MB (default 5.0).
        on_chunk: Optional zero-arg callable invoked once per ``_get_data``
            call. Used by Phase 3 export to drive a progress bar without
            leaking the reporter object into the iterator's hash identity.
    """

    def __init__(
        self,
        recording: si.BaseRecording,
        buffer_gb: float = 0.5,
        chunk_mb: float = 5.0,
        on_chunk: Callable[[], None] | None = None,
    ) -> None:
        self._recording = recording
        self._on_chunk = on_chunk
        super().__init__(buffer_gb=buffer_gb, chunk_mb=chunk_mb)

    def _get_data(self, selection: tuple[slice, ...]) -> np.ndarray:
        time_slice, ch_slice = selection
        traces = self._recording.get_traces(
            start_frame=time_slice.start,
            end_frame=time_slice.stop,
            return_in_uV=False,
        )
        # Explicit cast: SpikeGLX returns int16 natively; NumpyRecording
        # may return float32 — ensure consistent dtype for HDF5 dataset.
        out = traces[:, ch_slice].astype(np.int16, copy=False)
        if self._on_chunk is not None:
            self._on_chunk()
        return out

    def _get_dtype(self) -> np.dtype:
        return np.dtype(np.int16)

    def _get_maxshape(self) -> tuple[int, int]:
        return (
            self._recording.get_num_samples(),
            self._recording.get_num_channels(),
        )


class NWBWriter:
    """Assembles and writes a DANDI-compliant NWB 2.x file for one session.

    Usage::

        writer = NWBWriter(session, output_path)
        writer.create_file()
        for probe in session.probes:
            writer.add_probe_data(probe, analyzer)
        writer.add_trials(behavior_events_df)
        writer.write()

    LFP export is reserved for a future release and raises NotImplementedError.
    """

    def __init__(self, session: Session, output_path: Path) -> None:
        """Initialize the NWB writer.

        Args:
            session: Session object (provides subject, probes, timestamps).
            output_path: Path where the .nwb file will be written.
        """
        self.session = session
        self.output_path = Path(output_path)
        self._nwbfile: NWBFile | None = None
        self._unit_columns_initialized: bool = False
        self._has_raster_column: bool = False

    def create_file(self) -> NWBFile:
        """Create the top-level NWBFile object with session metadata.

        Reads session_start_time from the first probe's .ap.meta fileCreateTime.
        Must be called before add_probe_data(), add_trials(), or write().

        Returns:
            The created NWBFile (also stored as self._nwbfile).

        Raises:
            ValueError: If any DANDI-required subject field is empty.
        """
        subject = self.session.subject
        required = {
            "subject_id": subject.subject_id,
            "species": subject.species,
            "sex": subject.sex,
            "age": subject.age,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required DANDI subject fields: {missing}")

        probe = self.session.probes[0]
        discovery = SpikeGLXDiscovery(self.session.session_dir)
        meta = discovery.parse_meta(probe.ap_meta)
        session_start_time = datetime.strptime(meta["fileCreateTime"], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=UTC
        )

        nwb_subject = _build_subject(subject)

        canonical = self.session.session_id.canonical()
        self._nwbfile = NWBFile(
            identifier=str(uuid.uuid4()),
            session_id=canonical,
            session_description=f"{canonical} | pynpxpipe processed",
            session_start_time=session_start_time,
            subject=nwb_subject,
        )
        return self._nwbfile

    def add_probe_data(
        self,
        probe: ProbeInfo,
        analyzer: si.SortingAnalyzer,
        rasters: dict | None = None,
    ) -> None:
        """Add all data for one probe to the NWBFile.

        Adds ElectrodeGroup, electrode table rows, and units table rows.

        Args:
            probe: ProbeInfo with channel_positions populated.
            analyzer: SortingAnalyzer with waveforms, templates, unit_locations computed.
            rasters: Optional dict mapping unit_id → np.ndarray (n_valid_trials, n_bins).

        Raises:
            RuntimeError: If create_file() has not been called.
            ValueError: If analyzer is missing a required extension.
        """
        if self._nwbfile is None:
            raise RuntimeError("call create_file() before add_probe_data()")

        required_exts = ["waveforms", "templates", "unit_locations"]
        for ext in required_exts:
            if not analyzer.has_extension(ext):
                raise ValueError(f"Analyzer missing required extension: {ext}")

        # Device and electrode group
        device = self._nwbfile.create_device(
            name=probe.probe_id,
            description=f"{probe.probe_type} SN:{probe.serial_number}",
            manufacturer="IMEC",
        )
        electrode_group = self._nwbfile.create_electrode_group(
            name=probe.probe_id,
            description=f"Probe {probe.probe_id}: {probe.probe_type} SN:{probe.serial_number}",
            location=probe.target_area,
            device=device,
        )

        # Resolve channel positions: prefer ProbeInfo, fallback to analyzer probe
        channel_positions = probe.channel_positions
        if not channel_positions:
            try:
                pi_probe = analyzer.get_probe()
                positions = pi_probe.contact_positions  # (n_contacts, 2)
                channel_positions = [(float(x), float(y)) for x, y in positions]
            except Exception:
                channel_positions = []

        # Add electrode table columns and rows only if we have channel data
        if channel_positions:
            if self._nwbfile.electrodes is None:
                self._nwbfile.add_electrode_column("probe_id", "Probe identifier")
                self._nwbfile.add_electrode_column("channel_id", "Channel index within probe")

            for ch_idx, (x, y) in enumerate(channel_positions):
                self._nwbfile.add_electrode(
                    x=float(x),
                    y=float(y),
                    z=0.0,
                    group=electrode_group,
                    group_name=electrode_group.name,
                    location=probe.target_area,
                    probe_id=probe.probe_id,
                    channel_id=ch_idx,
                )

        # Extract extension data
        templates_ext = analyzer.get_extension("templates")
        unit_locs_ext = analyzer.get_extension("unit_locations")

        all_templates = templates_ext.get_templates()  # (n_units, n_samples, n_channels)
        try:
            all_templates_std = templates_ext.get_templates(operator="std")
        except Exception:
            all_templates_std = np.zeros_like(all_templates)

        all_locations = unit_locs_ext.get_data()  # (n_units, 2 or 3)

        qm_df: pd.DataFrame | None = None
        if analyzer.has_extension("quality_metrics"):
            qm_df = analyzer.get_extension("quality_metrics").get_data()

        # Load slay_scores.json for is_visual and slay_score (new format)
        slay_scores_data: dict = {}
        if hasattr(self.session, "output_dir"):
            slay_path = (
                self.session.output_dir / "06_postprocessed" / probe.probe_id / "slay_scores.json"
            )
            if slay_path.exists():
                try:
                    slay_scores_data = json.loads(slay_path.read_text(encoding="utf-8"))
                except Exception:
                    pass

        unit_ids = list(analyzer.sorting.get_unit_ids())

        # Initialize unit columns once
        if not self._unit_columns_initialized:
            for name, desc in [
                ("probe_id", "Probe identifier"),
                ("electrode_group", "Electrode group for this unit"),
                ("ks_id", "Kilosort cluster ID"),
                ("unittype_string", "Unit classification (SUA/MUA/NON-SOMA/NOISE/unknown)"),
                ("isi_violation_ratio", "ISI violation ratio"),
                ("amplitude_cutoff", "Amplitude cutoff"),
                ("presence_ratio", "Presence ratio"),
                ("snr", "Signal-to-noise ratio"),
                ("slay_score", "SLAY quality score (NaN if unavailable)"),
                ("is_visual", "Visual responsiveness flag (Mann-Whitney U p<0.001)"),
                ("waveform_mean", "Mean waveform shape (n_samples × n_channels), μV"),
                ("waveform_std", "Waveform std (n_samples × n_channels), μV"),
                ("unit_location", "Unit location in μm [x, y, z]"),
            ]:
                self._nwbfile.add_unit_column(name, desc)
            # E3.2 — ragged int64 column; rescued pre-write for the all-empty
            # case (see _rescue_merged_from_dtype).
            self._nwbfile.add_unit_column(
                "merged_from",
                "SLAy auto-merge source ks_ids ([] if unit was not a merge target)",
                index=True,
            )
            if rasters:
                self._nwbfile.add_unit_column(
                    "Raster",
                    "Spike raster (n_valid_trials × n_bins) at 1ms resolution, uint8",
                )
            self._has_raster_column = bool(rasters)
            self._unit_columns_initialized = True

        # E3.2 — resolve the merge log once per probe (one file read at most).
        merge_map = self._load_merge_log(probe.probe_id)

        # Get unittype_string property if available
        sorting_props = analyzer.sorting.get_property("unittype_string")

        for unit_idx, unit_id in enumerate(unit_ids):
            spike_times = np.asarray(
                analyzer.sorting.get_unit_spike_train(unit_id, return_times=True),
                dtype=np.float64,
            )
            waveform_mean = all_templates[unit_idx]  # (n_samples, n_channels)
            waveform_std = all_templates_std[unit_idx]  # (n_samples, n_channels)

            loc = all_locations[unit_idx]
            unit_location = np.array(
                [float(loc[0]), float(loc[1]), float(loc[2]) if len(loc) > 2 else 0.0],
                dtype=np.float64,
            )

            if qm_df is not None and unit_id in qm_df.index:
                row = qm_df.loc[unit_id]
                isi_vr = (
                    float(row["isi_violation_ratio"])
                    if "isi_violation_ratio" in qm_df.columns
                    else np.nan
                )
                amp_cut = (
                    float(row["amplitude_cutoff"])
                    if "amplitude_cutoff" in qm_df.columns
                    else np.nan
                )
                pr = float(row["presence_ratio"]) if "presence_ratio" in qm_df.columns else np.nan
                snr_val = float(row["snr"]) if "snr" in qm_df.columns else np.nan
                slay = float(row["slay_score"]) if "slay_score" in qm_df.columns else np.nan
            else:
                isi_vr = amp_cut = pr = snr_val = slay = np.nan

            # Read is_visual from slay_scores.json if available
            is_vis = bool(slay_scores_data.get(str(unit_id), {}).get("is_visual", False))
            # Override slay from slay_scores.json if available (new format)
            if str(unit_id) in slay_scores_data:
                entry = slay_scores_data[str(unit_id)]
                if isinstance(entry, dict):
                    raw_slay = entry.get("slay_score")
                    slay = float(raw_slay) if raw_slay is not None else np.nan

            unittype_str = (
                str(sorting_props[unit_idx])
                if sorting_props is not None and unit_idx < len(sorting_props)
                else "unknown"
            )

            # E3.2 — look up SLAy merge source ids for this unit.  Typed
            # np.int64 elements give HDMF an inferable dtype when at least
            # one row is non-empty; the all-empty case is rescued in write().
            merged_from_ids = merge_map.get(str(unit_id), [])
            merged_from_row = [np.int64(x) for x in merged_from_ids]

            self._nwbfile.add_unit(
                spike_times=spike_times,
                probe_id=probe.probe_id,
                electrode_group=electrode_group,
                ks_id=_safe_int(unit_id, unit_idx),
                unittype_string=unittype_str,
                isi_violation_ratio=isi_vr,
                amplitude_cutoff=amp_cut,
                presence_ratio=pr,
                snr=snr_val,
                slay_score=slay,
                is_visual=is_vis,
                waveform_mean=waveform_mean,
                waveform_std=waveform_std,
                unit_location=unit_location,
                merged_from=merged_from_row,
                **(
                    {"Raster": rasters[unit_id]}
                    if self._has_raster_column and rasters and unit_id in rasters
                    else {"Raster": np.zeros((0, 0), dtype=np.uint8)}
                    if self._has_raster_column
                    else {}
                ),
            )

    def _load_merge_log(self, probe_id: str) -> dict[str, list[int]]:
        """Load SLAy merge log for one probe; also stash raw JSON into scratch.

        Returns a mapping ``{str(new_id): [merged_ids...]}`` so callers can
        match by stringified unit id regardless of whether the sorter uses
        int or str. Missing file → DEBUG log + ``{}`` (merge off is normal).
        Malformed file → WARNING log + ``{}``. Scratch write is idempotent
        (warn and skip on duplicate).

        Args:
            probe_id: Probe identifier (e.g., ``"imec0"``).

        Returns:
            Map from stringified ``new_id`` to its ``merged_ids`` list.
        """
        merge_log_path = self.session.output_dir / "03_merged" / probe_id / "merge_log.json"
        if not merge_log_path.exists():
            logger.debug(
                "No merge_log.json at %s; merged_from will be [] for all units of %s",
                merge_log_path,
                probe_id,
            )
            return {}

        try:
            raw_text = merge_log_path.read_text(encoding="utf-8")
            payload = json.loads(raw_text)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "Failed to parse merge_log.json for %s (%s); merged_from will be [] "
                "for all units of that probe",
                probe_id,
                exc,
            )
            return {}

        # Stash raw JSON in scratch for full provenance (idempotent).
        scratch_name = f"merge_log_{probe_id}"
        if self._nwbfile is not None and scratch_name in self._nwbfile.scratch:
            logger.warning(
                "Scratch entry %s already exists; skipping duplicate write",
                scratch_name,
            )
        elif self._nwbfile is not None:
            self._nwbfile.add_scratch(
                data=raw_text,
                name=scratch_name,
                description=f"Raw SLAy merge log for {probe_id}",
            )

        merges = payload.get("merges", []) if isinstance(payload, dict) else []
        merge_map: dict[str, list[int]] = {}
        for entry in merges:
            if not isinstance(entry, dict):
                continue
            new_id = entry.get("new_id")
            merged_ids = entry.get("merged_ids", [])
            if new_id is None:
                continue
            merge_map[str(new_id)] = [int(m) for m in merged_ids]
        return merge_map

    def add_trials(
        self,
        behavior_events: pd.DataFrame,
        *,
        stim_map: dict[int, str] | None = None,
    ) -> None:
        """Add the trials table to the NWBFile.

        Each row in behavior_events becomes one NWB trial row, i.e. **one row
        per stimulus onset**. For RSVP paradigms with multiple stimuli per ML
        trial, the DataFrame has been pre-expanded upstream (one row per
        onset); each row carries its own ``stim_index``, and multiple rows
        sharing the same ``trial_id`` indicate they belong to the same ML
        trial (sync_plot consumers rely on this).

        **Clock convention (E1.1)**: start_time / stop_time / stim_onset_time are
        written in IMEC seconds, using the reference probe ``imec0`` (module
        constant ``_REFERENCE_PROBE``). This matches ``units.spike_times`` which
        are also in IMEC seconds. For multi-probe sessions each probe's onset
        is additionally written to ``stim_onset_imec_{probe_id}`` columns, and
        the NIDQ value survives as the diagnostic column
        ``stim_onset_nidq_s_diag``.

        stop_time is set to start_time + onset_time_ms/1000 (from VariableChanges),
        still on the IMEC clock.

        **stim_name column (E3.3)**: when both ``stim_map`` is supplied *and*
        the DataFrame carries a ``stim_index`` column, a ``stim_name`` column
        is declared and populated by looking each row's ``stim_index`` up in
        the map. Rows with ``stim_index == 0`` fall back to ``""`` (the BHV
        convention for "no stim"); unknown positive indices also fall back to
        ``""`` and are logged at DEBUG. If ``stim_map`` is ``None`` or the
        DataFrame has no ``stim_index`` column, the ``stim_name`` column is
        **not declared at all** — downstream consumers distinguish "lookup
        skipped" from "lookup ran but returned empty".

        Sanity check: every non-zero ``stim_index`` must fall in
        ``[1, len(stim_map)]``; out-of-range values raise ``ValueError``.

        Args:
            behavior_events: DataFrame with required columns trial_id,
                onset_nidq_s, stim_onset_nidq_s, stim_onset_imec_s,
                condition_id, trial_valid. Optional ``stim_index`` enables
                stim_name lookup when paired with ``stim_map``.
                ``stim_onset_imec_s`` must be a JSON string mapping
                ``{probe_id: t_imec_seconds}`` and must contain ``imec0``.
            stim_map: Optional ``{stim_index: stim_name}`` mapping derived
                from the BHV2 session's external tsv (resolved by
                ``io.stim_resolver``). Keys are 1-based indices matching
                the MATLAB convention. ``None`` means no lookup is performed
                and the ``stim_name`` column is omitted.

        Raises:
            RuntimeError: If create_file() has not been called.
            ValueError: If required columns are missing from the DataFrame,
                the IMEC JSON cannot be parsed, the reference probe is
                absent, or any non-zero ``stim_index`` value is negative or
                exceeds ``len(stim_map)``.
        """
        if self._nwbfile is None:
            raise RuntimeError("call create_file() before add_trials()")

        required_cols = {
            "trial_id",
            "onset_nidq_s",
            "stim_onset_nidq_s",
            "stim_onset_imec_s",
            "condition_id",
            "trial_valid",
        }
        missing = sorted(required_cols - set(behavior_events.columns))
        if missing:
            raise ValueError(f"Missing required DataFrame columns: {missing}")

        has_stim_index = "stim_index" in behavior_events.columns
        has_onset_time = "onset_time_ms" in behavior_events.columns
        has_offset_time = "offset_time_ms" in behavior_events.columns

        # E3.3: stim_name column only materialises when both the map and the
        # stim_index column are available. Out-of-range positive indices raise
        # immediately so downstream consumers never see silently-dropped labels.
        declare_stim_name = bool(stim_map) and has_stim_index
        if declare_stim_name and stim_map is not None:
            max_key = max(stim_map) if stim_map else 0
            stim_index_series = behavior_events["stim_index"]
            if (stim_index_series < 0).any():
                bad = int(stim_index_series[stim_index_series < 0].iloc[0])
                raise ValueError(f"stim_index must be >= 0, got {bad}")
            if (stim_index_series > max_key).any():
                bad = int(stim_index_series[stim_index_series > max_key].iloc[0])
                raise ValueError(f"stim_index {bad} exceeds len(stim_map)={max_key}")

        # Parse the IMEC JSON once per row up front. We need two things:
        #   (1) the set of probe_ids in the first row to declare per-probe
        #       columns before any add_trial() call (pynwb constraint);
        #   (2) the imec0 value to anchor start_time.
        parsed_imec: list[dict[str, float]] = []
        for idx, raw in enumerate(behavior_events["stim_onset_imec_s"].tolist()):
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else dict(raw)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(f"stim_onset_imec_s row {idx} is not valid JSON: {raw!r}") from exc
            if _REFERENCE_PROBE not in parsed:
                raise ValueError(
                    f"stim_onset_imec_s row {idx} is missing reference probe "
                    f"{_REFERENCE_PROBE!r}; keys present: {sorted(parsed)}"
                )
            parsed_imec.append({k: float(v) for k, v in parsed.items()})

        probe_ids_in_json = sorted(parsed_imec[0].keys()) if parsed_imec else []

        # Initialize trial columns once (before any add_trial call)
        if self._nwbfile.trials is None:
            self._nwbfile.add_trial_column(
                "stim_onset_time",
                f"Stimulus onset time in IMEC seconds (reference probe {_REFERENCE_PROBE})",
            )
            self._nwbfile.add_trial_column("trial_id", "BHV2 trial identifier")
            self._nwbfile.add_trial_column("condition_id", "Experimental condition identifier")
            self._nwbfile.add_trial_column("trial_valid", "Whether the trial is valid")
            self._nwbfile.add_trial_column(
                "stim_onset_nidq_s_diag",
                "Stimulus onset time in NIDQ seconds (diagnostic only)",
            )
            if declare_stim_name:
                self._nwbfile.add_trial_column(
                    "stim_name",
                    "Stimulus file/image name resolved from the external tsv "
                    "manifest via stim_index lookup; empty string when "
                    "stim_index==0 or the index is not present in the map.",
                )
            for pid in probe_ids_in_json:
                self._nwbfile.add_trial_column(
                    f"stim_onset_imec_{pid}",
                    f"Stimulus onset time in IMEC seconds for probe {pid}",
                )
            if has_stim_index:
                self._nwbfile.add_trial_column("stim_index", "Stimulus identity index (1-based)")
            if has_onset_time:
                self._nwbfile.add_trial_column(
                    "onset_time_ms", "Stimulus ON duration in ms (from VariableChanges)"
                )
            if has_offset_time:
                self._nwbfile.add_trial_column(
                    "offset_time_ms", "Inter-stimulus interval in ms (from VariableChanges)"
                )

        smap = stim_map or {}
        for (_, row), imec_map in zip(behavior_events.iterrows(), parsed_imec, strict=True):
            stim_onset_imec = imec_map[_REFERENCE_PROBE]
            onset_ms = float(row["onset_time_ms"]) if has_onset_time else 150.0
            cond_id = int(row["condition_id"])
            kwargs: dict[str, object] = {
                "start_time": stim_onset_imec,
                "stop_time": stim_onset_imec + onset_ms / 1000.0,
                "stim_onset_time": stim_onset_imec,
                "trial_id": int(row["trial_id"]),
                "condition_id": cond_id,
                "trial_valid": bool(row["trial_valid"]),
                "stim_onset_nidq_s_diag": float(row["stim_onset_nidq_s"]),
            }
            if declare_stim_name:
                idx = int(row["stim_index"])
                if idx == 0:
                    stim_name = ""
                elif idx in smap:
                    stim_name = smap[idx]
                else:
                    logger.debug(
                        "stim_index %d not in stim_map; stim_name='' (len(map)=%d)",
                        idx,
                        len(smap),
                    )
                    stim_name = ""
                kwargs["stim_name"] = stim_name
            for pid in probe_ids_in_json:
                # NaN is safer than KeyError if a later trial unexpectedly
                # omits one probe — but we declared the columns off the first
                # row, so we hard-require consistency.
                if pid not in imec_map:
                    raise ValueError(
                        f"trial {int(row['trial_id'])} stim_onset_imec_s is missing "
                        f"probe {pid!r}; all rows must list the same probes"
                    )
                kwargs[f"stim_onset_imec_{pid}"] = imec_map[pid]
            if has_stim_index:
                kwargs["stim_index"] = int(row["stim_index"])
            if has_onset_time:
                kwargs["onset_time_ms"] = onset_ms
            if has_offset_time:
                kwargs["offset_time_ms"] = float(row["offset_time_ms"])
            self._nwbfile.add_trial(**kwargs)

    def add_sync_tables(
        self,
        nwbfile: NWBFile,
        sync_dir: Path,
        *,
        behavior_events: pd.DataFrame | None = None,
    ) -> dict[str, int | bool]:
        """Write clock alignment and photodiode calibration tables to NWB scratch.

        Persists the minimal material a downstream consumer needs to redo or
        audit IMEC↔NIDQ clock alignment *after* the raw SpikeGLX bins have
        been deleted (E1.3). Collects three sources and serialises them into a
        single JSON payload attached to ``nwbfile.scratch["sync_tables"]``:

        - Per-probe IMEC↔NIDQ linear fits from ``sync_dir/{probe_id}_imec_nidq.json``
          (keys ``a, b, rmse, n_pulses`` preserved verbatim from the sync stage).
        - Photodiode-calibrated onsets from ``behavior_events`` — one record per
          trial with both the PD-detected NIDQ time and the event-code NIDQ
          time, plus the derived latency.
        - Event-code triples (start / stim_onset / reward) from the same
          DataFrame, for reconstructing BHV↔NIDQ matching without the
          original BHV2 file.

        Missing sources are recorded with a ``{"_missing": true}`` marker
        instead of raising, so export never fails on a partial sync run.
        Idempotent: if ``nwbfile.scratch`` already contains ``"sync_tables"``,
        this method returns immediately with ``idempotent_skipped=True``.

        Args:
            nwbfile: Open NWB file to modify in place.
            sync_dir: Path to the session's sync output directory containing
                ``{probe_id}_imec_nidq.json`` files.
            behavior_events: Optional trial events dataframe. When None, the
                photodiode and event_codes sections are recorded with
                ``_missing: true``.

        Returns:
            Summary dict with keys ``n_probes`` (int), ``n_trials_pd`` (int),
            ``n_trials_ec`` (int), ``idempotent_skipped`` (bool).
        """
        # Idempotency: a previous call or an externally-written file already
        # carries the scratch block — leave it alone.
        try:
            existing = nwbfile.scratch
        except Exception:
            existing = None
        if existing is not None and "sync_tables" in existing:
            return {
                "n_probes": 0,
                "n_trials_pd": 0,
                "n_trials_ec": 0,
                "idempotent_skipped": True,
            }

        imec_nidq = _collect_imec_nidq_fits(sync_dir)
        photodiode = _collect_photodiode_rows(behavior_events)
        event_codes = _collect_event_code_rows(behavior_events)

        n_probes = (
            0 if isinstance(imec_nidq, dict) and imec_nidq.get("_missing") else len(imec_nidq)
        )
        n_trials_pd = 0 if isinstance(photodiode, dict) else len(photodiode)
        n_trials_ec = 0 if isinstance(event_codes, dict) else len(event_codes)

        payload = {
            "imec_nidq": imec_nidq,
            "photodiode": photodiode,
            "event_codes": event_codes,
        }

        nwbfile.add_scratch(
            data=json.dumps(payload, indent=2, default=str),
            name="sync_tables",
            description=(
                "Clock alignment and photodiode calibration tables for "
                "reproducing sync without raw bins. JSON payload with keys: "
                "imec_nidq (per-probe linear fit t_nidq = a*t_imec + b), "
                "photodiode (per-trial PD-detected stim onsets in NIDQ "
                "seconds), event_codes (per-trial event-code triples used for "
                "BHV<->NIDQ matching). All times in NIDQ seconds unless noted."
            ),
        )

        return {
            "n_probes": n_probes,
            "n_trials_pd": n_trials_pd,
            "n_trials_ec": n_trials_ec,
            "idempotent_skipped": False,
        }

    def add_pipeline_metadata(self, config: object) -> None:
        """Serialize a PipelineConfig dataclass into ``nwbfile.scratch['pipeline_config']``.

        The full effective configuration is JSON-encoded (``indent=2``,
        ``default=str`` so Path/Enum values round-trip as strings) and stored
        as a scratch entry for provenance (E3.1). Calling twice on the same
        NWBFile emits a WARNING and skips (idempotent).

        Args:
            config: A dataclass instance (typically :class:`PipelineConfig`).

        Raises:
            RuntimeError: If ``create_file()`` has not been called.
            TypeError: If ``config`` is not a dataclass instance.
        """
        if self._nwbfile is None:
            raise RuntimeError("call create_file() before add_pipeline_metadata()")
        if not dataclasses.is_dataclass(config) or isinstance(config, type):
            raise TypeError(
                f"add_pipeline_metadata requires a dataclass instance, got {type(config)!r}"
            )

        if _PIPELINE_CONFIG_SCRATCH_KEY in self._nwbfile.scratch:
            logger.warning(
                "pipeline_config already present in NWB scratch; skipping second write "
                "(scratch_key=%s)",
                _PIPELINE_CONFIG_SCRATCH_KEY,
            )
            return

        payload = json.dumps(dataclasses.asdict(config), indent=2, default=str)
        self._nwbfile.add_scratch(
            data=payload,
            name=_PIPELINE_CONFIG_SCRATCH_KEY,
            description=_PIPELINE_CONFIG_DESCRIPTION,
        )

    def add_stim_provenance(
        self,
        *,
        dataset_name: str | None,
        resolved_tsv_path: str | None,
        source_tag: str,
    ) -> None:
        """Record the stim_name lookup provenance in NWB scratch.

        Writes a JSON blob to ``nwbfile.scratch['stim_name_provenance']`` so
        that the full resolution chain — the raw BHV2 ``UserVars.DatasetName``
        string, the tsv path actually read (after any ``image_vault_paths``
        fallback), and the resolver's source tag — survives in the NWB file
        alongside the trials table. This enables downstream audit of how
        each ``stim_name`` was obtained without re-running the resolver.

        Calling twice is idempotent: a subsequent call with the same key
        logs a WARNING and returns early.

        Args:
            dataset_name: The raw ``UserVars.DatasetName`` string, or ``None``
                if the BHV2 file carried no such value.
            resolved_tsv_path: Absolute path of the tsv finally read, or
                ``None`` if no tsv could be resolved.
            source_tag: Resolver source tag: one of ``"direct"``,
                ``"vault:<path>"``, ``"vault:<path>(multi)"``, ``"vault_miss"``,
                ``"no_dataset_name"``.

        Raises:
            RuntimeError: If ``create_file()`` has not been called.
        """
        if self._nwbfile is None:
            raise RuntimeError("call create_file() before add_stim_provenance()")

        if _STIM_NAME_PROVENANCE_KEY in self._nwbfile.scratch:
            logger.warning(
                "stim_name_provenance already present in NWB scratch; "
                "skipping second write (scratch_key=%s)",
                _STIM_NAME_PROVENANCE_KEY,
            )
            return

        payload = json.dumps(
            {
                "dataset_name": dataset_name,
                "resolved_tsv_path": resolved_tsv_path,
                "source_tag": source_tag,
            },
            indent=2,
        )
        self._nwbfile.add_scratch(
            data=payload,
            name=_STIM_NAME_PROVENANCE_KEY,
            description=_STIM_NAME_PROVENANCE_DESCRIPTION,
        )

    def add_lfp(self, probe: ProbeInfo, lfp_data: np.ndarray) -> None:
        """Reserved interface for LFP export — not yet implemented.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "LFP export is not yet implemented. Reserved for future lfp_process stage integration."
        )

    def add_eye_tracking(
        self,
        bhv_parser: object,
        behavior_events: pd.DataFrame,
    ) -> None:
        """Add eye tracking data to the NWBFile as a TimeSeries.

        Reads analog eye channel from BHV2Parser and writes to
        processing/behavior/EyeTracking. No-op if eye data is unavailable.

        Args:
            bhv_parser: BHV2Parser instance with get_analog_data("Eye") method.
            behavior_events: Trial events DataFrame (for timing reference).
        """
        if self._nwbfile is None:
            raise RuntimeError("call create_file() before add_eye_tracking()")

        try:
            from pynwb.behavior import EyeTracking, SpatialSeries

            eye_data = bhv_parser.get_analog_data("Eye")
            sample_interval_ms = bhv_parser.get_sample_interval()
            if not eye_data:
                return

            # Concatenate all trial eye data into one array
            all_eye: list[np.ndarray] = []
            for tid in sorted(eye_data.keys()):
                data = eye_data[tid]
                if data.ndim == 1:
                    data = data.reshape(-1, 1)
                all_eye.append(data)

            if not all_eye:
                return

            eye_array = np.concatenate(all_eye, axis=0)
            rate = 1000.0 / float(sample_interval_ms)

            spatial_series = SpatialSeries(
                name="eye_position",
                data=eye_array,
                reference_frame="screen center (degrees)",
                rate=rate,
                unit="degrees",
            )
            eye_tracking = EyeTracking(spatial_series=spatial_series)

            if "behavior" not in self._nwbfile.processing:
                self._nwbfile.create_processing_module(
                    name="behavior", description="Behavioral data"
                )
            self._nwbfile.processing["behavior"].add(eye_tracking)

        except Exception:
            # Eye tracking is optional — do not fail the export
            pass

    def add_ks4_sorting(
        self,
        probe_id: str,
        sorter_output_path: Path,
    ) -> None:
        """Add KS4 sorter output metadata to the NWBFile.

        Reads spike_templates.npy and amplitudes.npy from the KS4 sorter_output
        directory and stores them as TimeSeries in processing/ecephys.

        Args:
            probe_id: Probe identifier (e.g. "imec0").
            sorter_output_path: Path to the KS4 sorter_output directory.
        """
        if self._nwbfile is None:
            raise RuntimeError("call create_file() before add_ks4_sorting()")

        sorter_output_path = Path(sorter_output_path)
        try:
            from pynwb.ecephys import ElectricalSeries
            from pynwb.misc import Units

            amplitudes_path = sorter_output_path / "amplitudes.npy"
            templates_path = sorter_output_path / "spike_templates.npy"

            if not amplitudes_path.exists() or not templates_path.exists():
                return

            amplitudes = np.load(str(amplitudes_path)).squeeze()
            spike_templates = np.load(str(templates_path)).squeeze()

            if "ecephys" not in self._nwbfile.processing:
                self._nwbfile.create_processing_module(
                    name="ecephys", description="Electrophysiology data"
                )

            from pynwb import TimeSeries

            self._nwbfile.processing["ecephys"].add(
                TimeSeries(
                    name=f"kilosort4_{probe_id}_amplitudes",
                    data=amplitudes,
                    unit="μV",
                    rate=1.0,
                    description=f"KS4 spike amplitudes for {probe_id}",
                )
            )
            self._nwbfile.processing["ecephys"].add(
                TimeSeries(
                    name=f"kilosort4_{probe_id}_spike_templates",
                    data=spike_templates.astype(np.int32),
                    unit="index",
                    rate=1.0,
                    description=f"KS4 spike template assignments for {probe_id}",
                )
            )
        except Exception:
            # KS4 metadata is optional — do not fail the export
            pass

    def append_raw_data(
        self,
        session: Session,
        nwb_path: Path,
        *,
        time_range: tuple[float, float] | None = None,
        buffer_gb: float = 0.5,
        chunk_mb: float = 5.0,
        verify_policy: Literal["full", "sample"] = "full",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> dict[str, int | str | dict]:
        """Append compressed raw AP/LF/NIDQ voltage data to an existing NWB file.

        Opens the NWB in append mode, streams each probe's AP (and LF if
        available) recording through ``SpikeGLXDataChunkIterator`` with Blosc
        zstd compression, then appends a single session-level
        ``TimeSeries("NIDQ_raw", ...)`` holding the raw int16 NIDQ array (all
        analog + digital channels kept together — no bit decoding, no channel
        splitting). Idempotent: streams already present in ``acquisition`` are
        skipped. When the session has no ``.nidq.bin`` on disk the NIDQ step
        logs a warning and continues without raising.

        After the write, performs a bit-exact verification scan (E2.1): each
        just-written stream is re-read chunk-by-chunk from the fresh NWB and
        compared against the source recording. A mismatch raises
        ``ExportError`` with the offending probe / stream / chunk index. The
        ``verify_policy`` kwarg switches between ``"full"`` (every chunk — the
        default and strongly recommended) and ``"sample"`` (first/middle/last
        chunk only — a performance escape hatch).

        Args:
            session: Session object with probe AP/LF bin paths and
                ``session_dir`` (used for NIDQ discovery).
            nwb_path: Path to the existing NWB file to append to.
            time_range: Optional (start_sec, end_sec) to export a subset
                (applied to AP, LF, and NIDQ alike).
            buffer_gb: RAM budget per buffer in GB.
            chunk_mb: Target HDF5 chunk size in MB.
            verify_policy: ``"full"`` to scan every chunk (default) or
                ``"sample"`` to scan only first/middle/last chunks.
            progress_callback: Optional ``(message, fraction)`` sink invoked
                during both the append and verify sub-phases. ``fraction``
                is monotonic within [0.0, 1.0]; append contributes to
                [0.0, 0.7] and verify to [0.7, 1.0]. Always fires once with
                fraction == 1.0 at the end when a callback was supplied.

        Returns:
            Summary dict with ``streams_written``, ``stream_names``,
            ``verify_policy``, ``n_chunks_scanned_per_stream``
            (``{stream_name: int}``).

        Raises:
            FileNotFoundError: If nwb_path does not exist.
            ExportError: If bit-exact verification detects a chunk mismatch.
        """
        if not nwb_path.exists():
            raise FileNotFoundError(f"NWB file not found: {nwb_path}")

        reporter = _Phase3Reporter(progress_callback)
        comp = _get_compression_filter()
        streams_written: list[str] = []
        # Records enough state per written stream for ``_verify_raw_data`` to
        # re-scan the source vs. the freshly written NWB dataset without
        # regenerating load_* calls or re-deriving chunk decomposition.
        written_streams: list[dict] = []

        with NWBHDF5IO(str(nwb_path), "a") as io:
            nwbfile = io.read()

            for probe in session.probes:
                # --- AP stream ---
                ap_name = f"ElectricalSeriesAP_{probe.probe_id}"
                if ap_name not in nwbfile.acquisition:
                    info = self._append_recording_stream(
                        nwbfile,
                        probe,
                        stream_type="ap",
                        series_name=ap_name,
                        time_range=time_range,
                        buffer_gb=buffer_gb,
                        chunk_mb=chunk_mb,
                        comp=comp,
                        reporter=reporter,
                    )
                    streams_written.append(ap_name)
                    written_streams.append(info)

                # --- LF stream ---
                if probe.lf_bin is not None:
                    lf_name = f"ElectricalSeriesLF_{probe.probe_id}"
                    if lf_name not in nwbfile.acquisition:
                        info = self._append_recording_stream(
                            nwbfile,
                            probe,
                            stream_type="lf",
                            series_name=lf_name,
                            time_range=time_range,
                            buffer_gb=buffer_gb,
                            chunk_mb=chunk_mb,
                            comp=comp,
                            reporter=reporter,
                        )
                        streams_written.append(lf_name)
                        written_streams.append(info)

            # --- NIDQ stream (session-level, single TimeSeries) ---
            if "NIDQ_raw" not in nwbfile.acquisition:
                nidq_info = self._append_nidq_stream(
                    nwbfile,
                    session,
                    time_range=time_range,
                    buffer_gb=buffer_gb,
                    chunk_mb=chunk_mb,
                    comp=comp,
                    reporter=reporter,
                )
                if nidq_info is not None:
                    streams_written.append("NIDQ_raw")
                    written_streams.append(nidq_info)

            io.write(nwbfile)

        # Run the post-write bit-exact scan. If NO streams were just written
        # (fully idempotent call) the scan is a no-op and we return without
        # raising — the caller can't have introduced a mismatch in this call.
        n_chunks_per_stream: dict[str, int] = {}
        if written_streams:
            n_chunks_per_stream = self._verify_raw_data(
                nwb_path, written_streams, verify_policy, reporter=reporter
            )
        reporter.finalize()

        return {
            "streams_written": len(streams_written),
            "stream_names": ", ".join(streams_written),
            "verify_policy": verify_policy,
            "n_chunks_scanned_per_stream": n_chunks_per_stream,
        }

    def _verify_raw_data(
        self,
        nwb_path: Path,
        written_streams: list[dict],
        policy: Literal["full", "sample"],
        *,
        reporter: _Phase3Reporter | None = None,
    ) -> dict[str, int]:
        """Bit-exact compare each just-written stream against its source.

        Opens the NWB file read-only, then for every entry in
        ``written_streams`` iterates chunk-sized slices of both the source
        SpikeInterface recording and the NWB dataset and calls
        ``np.array_equal``. On first mismatch, raises ``ExportError`` with the
        probe / stream / chunk index embedded in the message so the caller
        can locate the corrupted region without a full log replay.

        Args:
            nwb_path: NWB file on disk (will be opened in ``"r"`` mode).
            written_streams: List of dicts each with keys ``series_name``,
                ``stream_type`` (``"AP"`` / ``"LF"`` / ``"NIDQ"``),
                ``probe_id``, ``recording`` (the SpikeInterface source),
                ``chunk_frames`` (int), ``n_samples`` (int), ``n_channels`` (int).
            policy: ``"full"`` scans every chunk. ``"sample"`` scans only the
                first, middle, and last chunk (deduped for small streams).

        Returns:
            Mapping ``{series_name: n_chunks_scanned}``.

        Raises:
            ExportError: On any chunk mismatch.
        """
        n_chunks_scanned: dict[str, int] = {}
        # Pre-register verify totals so the first on_verify emits an
        # accurate fraction instead of jumping straight to 1.0.
        if reporter is not None:
            for entry in written_streams:
                chunk_frames = int(entry["chunk_frames"])
                n_samples = int(entry["n_samples"])
                if chunk_frames <= 0 or n_samples <= 0:
                    continue
                n_chunks = (n_samples + chunk_frames - 1) // chunk_frames
                if policy == "sample":
                    n_chunks = len({0, n_chunks // 2, max(0, n_chunks - 1)})
                reporter.register_verify_stream(n_chunks)

        with NWBHDF5IO(str(nwb_path), "r") as io:
            nwbfile = io.read()
            for entry in written_streams:
                series_name: str = entry["series_name"]
                stream_type: str = entry["stream_type"]
                probe_id: str = entry["probe_id"]
                rec = entry["recording"]
                chunk_frames = int(entry["chunk_frames"])
                n_samples = int(entry["n_samples"])

                if series_name not in nwbfile.acquisition:
                    raise ExportError(
                        f"Bit-exact verification failed: {probe_id} {stream_type} "
                        f"series {series_name!r} absent from NWB acquisition"
                    )
                dataset = nwbfile.acquisition[series_name].data

                # Enumerate chunk indices per policy.
                if chunk_frames <= 0 or n_samples <= 0:
                    n_chunks_scanned[series_name] = 0
                    continue
                n_chunks = (n_samples + chunk_frames - 1) // chunk_frames
                if policy == "sample":
                    indices = sorted({0, n_chunks // 2, n_chunks - 1})
                else:
                    indices = list(range(n_chunks))

                verify_tag = f"{probe_id}_{stream_type}"
                scanned = 0
                for chunk_idx in indices:
                    start = chunk_idx * chunk_frames
                    stop = min(start + chunk_frames, n_samples)
                    source_chunk = rec.get_traces(
                        start_frame=start,
                        end_frame=stop,
                        return_in_uV=False,
                    ).astype(np.int16, copy=False)
                    nwb_chunk = np.asarray(dataset[start:stop])
                    if not np.array_equal(source_chunk, nwb_chunk):
                        raise ExportError(
                            f"Bit-exact verification failed: {probe_id} {stream_type} "
                            f"chunk {chunk_idx} mismatch at sample offset {start}"
                        )
                    scanned += 1
                    if reporter is not None:
                        reporter.on_verify(verify_tag)
                n_chunks_scanned[series_name] = scanned

        return n_chunks_scanned

    def _append_nidq_stream(
        self,
        nwbfile: NWBFile,
        session: Session,
        *,
        time_range: tuple[float, float] | None,
        buffer_gb: float,
        chunk_mb: float,
        comp: dict,
        reporter: _Phase3Reporter | None = None,
    ) -> dict | None:
        """Append a single NIDQ_raw TimeSeries to the NWB acquisition.

        Locates the session's nidq.bin/meta via ``SpikeGLXDiscovery``; if
        either file is missing (``DiscoverError``), logs a warning and returns
        None without raising. Otherwise streams the raw int16 recording
        through ``SpikeGLXDataChunkIterator`` with Blosc zstd compression and
        stores the full channel layout + bit definitions in the TimeSeries
        ``description`` so downstream readers can decode the digital word
        without reparsing the original SpikeGLX meta.

        Args:
            nwbfile: Open NWBFile to add the NIDQ_raw TimeSeries to.
            session: Session whose ``session_dir`` hosts the NIDQ files.
            time_range: Optional (start_sec, end_sec) frame slice.
            buffer_gb: RAM budget per buffer.
            chunk_mb: Target HDF5 chunk size.
            comp: Compression kwargs from ``_get_compression_filter()``.

        Returns:
            Stream info dict (series_name, stream_type, probe_id, recording,
            chunk_frames, n_samples, n_channels) when the TimeSeries was added;
            None if NIDQ was skipped.
        """
        discovery = SpikeGLXDiscovery(session.session_dir)
        try:
            nidq_bin, nidq_meta = discovery.discover_nidq()
        except DiscoverError as exc:
            logger.warning("Skipping NIDQ export — nidq files not found: %s", exc)
            return None

        if not nidq_bin.exists() or not nidq_meta.exists():
            logger.warning(
                "Skipping NIDQ export — missing nidq files: bin=%s, meta=%s",
                nidq_bin,
                nidq_meta,
            )
            return None

        meta = discovery.parse_meta(nidq_meta)
        try:
            ni_samp_rate = float(meta["niSampRate"])
            ni_ai_range_max = float(meta["niAiRangeMax"])
        except (KeyError, ValueError) as exc:
            logger.warning(
                "Skipping NIDQ export — %s missing required meta fields "
                "(niSampRate/niAiRangeMax): %s",
                nidq_meta,
                exc,
            )
            return None

        try:
            rec = SpikeGLXLoader.load_nidq(nidq_bin, nidq_meta)
        except Exception as exc:
            logger.warning("Skipping NIDQ export — load_nidq failed: %s", exc)
            return None

        if time_range is not None:
            t0, t1 = time_range
            sr = rec.get_sampling_frequency()
            rec = rec.frame_slice(start_frame=int(t0 * sr), end_frame=int(t1 * sr))

        n_samples = rec.get_num_samples()
        n_channels = rec.get_num_channels()
        if n_samples == 0 or n_channels == 0:
            logger.warning(
                "Skipping NIDQ export — recording is empty (n_samples=%s, n_channels=%s)",
                n_samples,
                n_channels,
            )
            return None

        on_chunk = reporter.make_write_hook("nidq_session") if reporter is not None else None
        iterator = SpikeGLXDataChunkIterator(
            rec, buffer_gb=buffer_gb, chunk_mb=chunk_mb, on_chunk=on_chunk
        )
        if reporter is not None:
            reporter.register_write_stream(_count_iterator_buffers(iterator))
        chunk_frames = int(iterator.chunk_shape[0])
        wrapped = H5DataIO(
            data=iterator,
            chunks=(min(40000, n_samples), n_channels),
            **comp,
        )

        description = _build_nidq_description(meta, session)
        conversion = float(ni_ai_range_max) / 32768.0

        ts = TimeSeries(
            name="NIDQ_raw",
            data=wrapped,
            starting_time=0.0,
            rate=float(ni_samp_rate),
            conversion=conversion,
            unit="V",
            description=description,
        )
        nwbfile.add_acquisition(ts)
        return {
            "series_name": "NIDQ_raw",
            "stream_type": "NIDQ",
            "probe_id": "session",
            "recording": rec,
            "chunk_frames": chunk_frames,
            "n_samples": n_samples,
            "n_channels": n_channels,
        }

    def _append_recording_stream(
        self,
        nwbfile: NWBFile,
        probe: ProbeInfo,
        *,
        stream_type: str,
        series_name: str,
        time_range: tuple[float, float] | None,
        buffer_gb: float,
        chunk_mb: float,
        comp: dict,
        reporter: _Phase3Reporter | None = None,
    ) -> dict:
        """Add one AP or LF recording stream to the NWB acquisition.

        Args:
            nwbfile: Open NWBFile to add the ElectricalSeries to.
            probe: ProbeInfo for this probe.
            stream_type: "ap" or "lf".
            series_name: Name for the ElectricalSeries.
            time_range: Optional (start_sec, end_sec) for subsetting.
            buffer_gb: RAM budget per buffer.
            chunk_mb: Target HDF5 chunk size.
            comp: Compression kwargs from _get_compression_filter().

        Returns:
            Stream info dict (series_name, stream_type, probe_id, recording,
            chunk_frames, n_samples, n_channels) used by
            ``_verify_raw_data`` for the post-write bit-exact scan.
        """
        if stream_type == "ap":
            rec = SpikeGLXLoader.load_ap(probe)
            filtering = "AP band: 300-10000 Hz"
        else:
            rec = SpikeGLXLoader.load_lf(probe)
            filtering = "LF band: 0.5-1000 Hz"

        sr = rec.get_sampling_frequency()

        if time_range is not None:
            t0, t1 = time_range
            rec = rec.frame_slice(start_frame=int(t0 * sr), end_frame=int(t1 * sr))

        # Voltage conversion: gain_to_uV → volts. A missing / empty / all-NaN
        # gain_to_uV property would silently bake a conversion=1.0 into the
        # NWB (E2.2: no more silent fallback — every exported stream must
        # carry a verifiable µV→V scale factor).
        gain_to_uV = rec.get_property("gain_to_uV")
        gain_array = None if gain_to_uV is None else np.asarray(gain_to_uV)
        stream_label = stream_type.upper()
        if (
            gain_array is None
            or gain_array.size == 0
            or (np.issubdtype(gain_array.dtype, np.number) and np.isnan(gain_array).all())
        ):
            raise ExportError(
                f"{probe.probe_id} {stream_label} missing gain_to_uV — "
                "cannot compute NWB conversion factor"
            )
        try:
            conversion = float(gain_array.flat[0]) * 1e-6
        except (TypeError, ValueError) as exc:
            raise ExportError(
                f"{probe.probe_id} {stream_label} gain_to_uV not numeric "
                f"({gain_array!r}) — cannot compute NWB conversion factor"
            ) from exc

        n_ch = rec.get_num_channels()
        n_samples = rec.get_num_samples()
        on_chunk = (
            reporter.make_write_hook(f"{stream_type}_{probe.probe_id}")
            if reporter is not None
            else None
        )
        iterator = SpikeGLXDataChunkIterator(
            rec, buffer_gb=buffer_gb, chunk_mb=chunk_mb, on_chunk=on_chunk
        )
        if reporter is not None:
            reporter.register_write_stream(_count_iterator_buffers(iterator))
        chunk_frames = int(iterator.chunk_shape[0])
        wrapped = H5DataIO(
            data=iterator,
            chunks=(min(40000, n_samples), min(64, n_ch)),
            **comp,
        )

        # Build electrode table region from existing electrodes
        electrode_indices = self._find_electrode_indices(nwbfile, probe.probe_id, n_ch)
        region = nwbfile.create_electrode_table_region(
            region=electrode_indices,
            description=f"{stream_type.upper()} electrodes for {probe.probe_id}",
        )

        es = ElectricalSeries(
            name=series_name,
            data=wrapped,
            electrodes=region,
            starting_time=0.0,
            rate=sr,
            conversion=conversion,
            filtering=filtering,
            description=f"Raw {stream_type.upper()} recording for {probe.probe_id}",
        )
        nwbfile.add_acquisition(es)
        return {
            "series_name": series_name,
            "stream_type": stream_type.upper(),
            "probe_id": probe.probe_id,
            "recording": rec,
            "chunk_frames": chunk_frames,
            "n_samples": n_samples,
            "n_channels": n_ch,
        }

    @staticmethod
    def _find_electrode_indices(nwbfile: NWBFile, probe_id: str, n_channels: int) -> list[int]:
        """Find electrode table row indices for a given probe_id.

        Falls back to a sequential range [0, n_channels) if the electrode
        table has no probe_id column or no matching rows.

        Args:
            nwbfile: NWBFile with electrode table populated.
            probe_id: Probe identifier to filter by.
            n_channels: Expected number of channels.

        Returns:
            List of integer indices into the electrode table.
        """
        if nwbfile.electrodes is None:
            return list(range(n_channels))

        try:
            probe_ids = nwbfile.electrodes["probe_id"].data[:]
            indices = [i for i, pid in enumerate(probe_ids) if pid == probe_id]
            if indices:
                return indices
        except (KeyError, TypeError):
            pass

        return list(range(min(n_channels, len(nwbfile.electrodes))))

    def verify_nwb(self, nwb_path: Path) -> bool:
        """Verify that a written NWB file can be opened and read.

        Args:
            nwb_path: Path to the NWB file to verify.

        Returns:
            True if the file opens successfully.

        Raises:
            RuntimeError: If the file cannot be opened.
        """
        try:
            with NWBHDF5IO(str(nwb_path), "r") as io:
                io.read()
            return True
        except Exception as exc:
            raise RuntimeError(f"NWB file verification failed: {nwb_path}: {exc}") from exc

    def write(self) -> Path:
        """Serialize the NWBFile to disk.

        Returns:
            Absolute path of the written .nwb file.

        Raises:
            RuntimeError: If create_file() has not been called.
        """
        if self._nwbfile is None:
            raise RuntimeError("call create_file() before write()")

        self._rescue_merged_from_dtype()
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        with NWBHDF5IO(str(self.output_path), mode="w") as io:
            io.write(self._nwbfile)

        return self.output_path

    def _rescue_merged_from_dtype(self) -> None:
        """Ensure the ragged ``merged_from`` column has an inferable dtype.

        HDMF infers a VectorData column's dtype from its underlying data
        container. When every unit's ``merged_from`` is empty (merge off),
        the container is a bare ``list`` with no elements and no dtype, and
        writing fails with "could not resolve dtype for VectorData
        'merged_from'". We replace that empty list with an empty typed
        ``np.int64`` ndarray so HDMF can emit a well-typed empty column.

        No-op when units table is absent or the column already has typed
        contents.
        """
        if self._nwbfile is None or self._nwbfile.units is None:
            return
        if "merged_from" not in self._nwbfile.units.colnames:
            return
        vi = self._nwbfile.units["merged_from"]
        vd = vi.target  # VectorIndex → VectorData
        data = vd.data
        if isinstance(data, list) and len(data) == 0:
            # Name-mangled private attribute on hdmf.container.Data. This is
            # the documented workaround — HDMF has no public setter for an
            # empty VectorData's storage. Kept narrow (exact type + empty
            # check) so it never touches populated columns.
            vd._Data__data = np.asarray([], dtype=np.int64)
