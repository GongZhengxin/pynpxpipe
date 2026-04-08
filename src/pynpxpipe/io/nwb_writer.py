"""NWB file generation for multi-probe electrophysiology data.

Wraps pynwb to write NWB 2.x files conforming to DANDI archive standards.
All probes are written to a single NWB file. No UI dependencies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from pynwb import NWBHDF5IO, NWBFile
from pynwb.file import Subject as NWBSubject

from pynpxpipe.io.spikeglx import SpikeGLXDiscovery

if TYPE_CHECKING:
    import spikeinterface.core as si

    from pynpxpipe.core.session import ProbeInfo, Session


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

        nwb_subject = NWBSubject(
            subject_id=subject.subject_id,
            description=subject.description,
            species=subject.species,
            sex=subject.sex,
            age=subject.age,
            weight=subject.weight if subject.weight else None,
        )

        self._nwbfile = NWBFile(
            identifier=str(uuid.uuid4()),
            session_description=f"pynpxpipe processed: {self.session.session_dir.name}",
            session_start_time=session_start_time,
            subject=nwb_subject,
        )
        return self._nwbfile

    def add_probe_data(
        self,
        probe: ProbeInfo,
        analyzer: si.SortingAnalyzer,
    ) -> None:
        """Add all data for one probe to the NWBFile.

        Adds ElectrodeGroup, electrode table rows, and units table rows.

        Args:
            probe: ProbeInfo with channel_positions populated.
            analyzer: SortingAnalyzer with waveforms, templates, unit_locations computed.

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
            location="unknown",
            device=device,
        )

        # Add electrode table columns on first call
        if self._nwbfile.electrodes is None:
            self._nwbfile.add_electrode_column("probe_id", "Probe identifier")
            self._nwbfile.add_electrode_column("channel_id", "Channel index within probe")

        channel_positions = probe.channel_positions or []
        for ch_idx, (x, y) in enumerate(channel_positions):
            self._nwbfile.add_electrode(
                x=float(x),
                y=float(y),
                z=0.0,
                group=electrode_group,
                group_name=electrode_group.name,
                location="unknown",
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

        unit_ids = list(analyzer.sorting.get_unit_ids())

        # Initialize unit columns once
        if not self._unit_columns_initialized:
            for name, desc in [
                ("probe_id", "Probe identifier"),
                ("electrode_group", "Electrode group for this unit"),
                ("isi_violation_ratio", "ISI violation ratio"),
                ("amplitude_cutoff", "Amplitude cutoff"),
                ("presence_ratio", "Presence ratio"),
                ("snr", "Signal-to-noise ratio"),
                ("slay_score", "SLAY quality score (NaN if unavailable)"),
                ("waveform_mean", "Mean waveform shape (n_samples × n_channels), μV"),
                ("waveform_std", "Waveform std (n_samples × n_channels), μV"),
                ("unit_location", "Unit location in μm [x, y, z]"),
            ]:
                self._nwbfile.add_unit_column(name, desc)
            self._unit_columns_initialized = True

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

            self._nwbfile.add_unit(
                spike_times=spike_times,
                probe_id=probe.probe_id,
                electrode_group=electrode_group,
                isi_violation_ratio=isi_vr,
                amplitude_cutoff=amp_cut,
                presence_ratio=pr,
                snr=snr_val,
                slay_score=slay,
                waveform_mean=waveform_mean,
                waveform_std=waveform_std,
                unit_location=unit_location,
            )

    def add_trials(self, behavior_events: pd.DataFrame) -> None:
        """Add the trials table to the NWBFile.

        Args:
            behavior_events: DataFrame with columns trial_id, onset_nidq_s,
                stim_onset_nidq_s, condition_id, trial_valid.

        Raises:
            RuntimeError: If create_file() has not been called.
            ValueError: If required columns are missing from the DataFrame.
        """
        if self._nwbfile is None:
            raise RuntimeError("call create_file() before add_trials()")

        required_cols = {
            "trial_id",
            "onset_nidq_s",
            "stim_onset_nidq_s",
            "condition_id",
            "trial_valid",
        }
        missing = sorted(required_cols - set(behavior_events.columns))
        if missing:
            raise ValueError(f"Missing required DataFrame columns: {missing}")

        # Initialize trial columns once (before any add_trial call)
        if self._nwbfile.trials is None:
            self._nwbfile.add_trial_column("stim_onset_time", "Stimulus onset time in NIDQ seconds")
            self._nwbfile.add_trial_column("trial_id", "Trial identifier")
            self._nwbfile.add_trial_column("condition_id", "Experimental condition identifier")
            self._nwbfile.add_trial_column("trial_valid", "Whether the trial is valid")

        for _, row in behavior_events.iterrows():
            self._nwbfile.add_trial(
                start_time=float(row["onset_nidq_s"]),
                stop_time=float(row["onset_nidq_s"]),
                stim_onset_time=float(row["stim_onset_nidq_s"]),
                trial_id=int(row["trial_id"]),
                condition_id=int(row["condition_id"]),
                trial_valid=bool(row["trial_valid"]),
            )

    def add_lfp(self, probe: ProbeInfo, lfp_data: np.ndarray) -> None:
        """Reserved interface for LFP export — not yet implemented.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "LFP export is not yet implemented. Reserved for future lfp_process stage integration."
        )

    def write(self) -> Path:
        """Serialize the NWBFile to disk.

        Returns:
            Absolute path of the written .nwb file.

        Raises:
            RuntimeError: If create_file() has not been called.
        """
        if self._nwbfile is None:
            raise RuntimeError("call create_file() before write()")

        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        with NWBHDF5IO(str(self.output_path), mode="w") as io:
            io.write(self._nwbfile)

        return self.output_path
