"""NWB file generation for multi-probe electrophysiology data.

Wraps pynwb to write NWB 2.x files conforming to DANDI archive standards.
All probes are written to a single NWB file. No UI dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd
    import spikeinterface.core as si
    from pynwb import NWBFile
    from pynpxpipe.core.session import ProbeInfo, Session


class NWBWriter:
    """Builds and writes NWB files for a processed electrophysiology session.

    Usage::

        writer = NWBWriter(session, output_path)
        writer.create_file()
        for probe in session.probes:
            writer.add_probe_data(probe, analyzer)
        writer.add_trials(behavior_events_df)
        writer.write()
    """

    def __init__(self, session: "Session", output_path: Path) -> None:
        """Initialize the NWB writer.

        Args:
            session: Session object (provides subject, probes, timestamps).
            output_path: Path where the .nwb file will be written.

        Raises:
            OSError: If the output directory is not writable.
        """
        raise NotImplementedError("TODO")

    def create_file(self) -> "NWBFile":
        """Create the top-level NWBFile object with session metadata.

        Populates:
        - identifier (UUID)
        - session_description
        - session_start_time (from SpikeGLX meta fileCreateTime)
        - subject (NWBSubject from session.subject SubjectConfig)

        Returns:
            The created NWBFile object (also stored as self._nwbfile).

        Raises:
            ValueError: If session.subject has missing DANDI-required fields.
        """
        raise NotImplementedError("TODO")

    def add_probe_data(
        self,
        probe: "ProbeInfo",
        analyzer: "si.SortingAnalyzer",
    ) -> None:
        """Add all data for one probe to the NWBFile.

        Adds:
        - ElectrodeGroup for the probe
        - Electrode table rows (channel x/y/z positions)
        - Units table rows (spike_times, waveforms, quality metrics, slay_score)

        Args:
            probe: ProbeInfo with channel_positions populated.
            analyzer: Fully computed SortingAnalyzer for this probe.

        Raises:
            ValueError: If analyzer has not computed required extensions
                (waveforms, templates, unit_locations).
        """
        raise NotImplementedError("TODO")

    def add_trials(self, behavior_events: "pd.DataFrame") -> None:
        """Add the trials table to the NWBFile.

        Maps behavior_events DataFrame columns to NWB TimeIntervals fields.
        Expected columns: trial_id, onset_nidq_s, stim_onset_nidq_s, condition_id.

        Args:
            behavior_events: DataFrame from sync/behavior_events.parquet.

        Raises:
            KeyError: If required columns are missing from the DataFrame.
        """
        raise NotImplementedError("TODO")

    def add_lfp(self, probe: "ProbeInfo", lfp_data: np.ndarray) -> None:
        """Add LFP data for a probe to the NWBFile.

        Args:
            probe: ProbeInfo for the probe whose LFP is being added.
            lfp_data: LFP array, shape (n_samples, n_channels), in μV.

        Raises:
            NotImplementedError: Always. LFP writing is reserved for future implementation.
        """
        raise NotImplementedError(
            "LFP export is not yet implemented. "
            "Reserved for future lfp_process stage integration."
        )

    def write(self) -> Path:
        """Serialize the NWBFile to disk using Blosc/zstd compression.

        Returns:
            Path to the written .nwb file (same as output_path passed at init).

        Raises:
            RuntimeError: If create_file() has not been called.
            OSError: If the file cannot be written.
        """
        raise NotImplementedError("TODO")
