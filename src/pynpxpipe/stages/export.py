"""Export stage: write all processed data to a single NWB file.

Combines all probe data, behavioral events, and subject metadata into one
NWB 2.x file conforming to DANDI standards. No UI dependencies.
"""

from __future__ import annotations

import gc
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import pynwb
import spikeinterface.core as si

from pynpxpipe.core.errors import ExportError
from pynpxpipe.io.nwb_writer import NWBWriter
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class ExportStage(BaseStage):
    """Writes all pipeline outputs to a single NWB 2.x file.

    Processes probes one at a time to control memory:
    load analyzer → write to NWB → del + gc.collect.

    On write failure: deletes partial NWB file before raising ExportError.
    NWB file is verified readable (NWBHDF5IO round-trip) before checkpoint.

    Raises:
        ExportError: If NWBWriter raises, or if the written file cannot be read.
    """

    STAGE_NAME = "export"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the export stage.

        Args:
            session: Active pipeline session with all upstream stages completed.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        super().__init__(session, progress_callback)

    def run(self) -> None:
        """Write all data to the output NWB file.

        Raises:
            ExportError: On write failure or file verification failure.
        """
        if self._is_complete():
            return

        self._report_progress("Starting export", 0.0)
        nwb_path = self._get_output_path()
        writer = NWBWriter(self.session, nwb_path)

        try:
            writer.create_file()

            n_units_total = 0
            n_probes = len(self.session.probes)
            for i, probe in enumerate(self.session.probes):
                probe_id = probe.probe_id
                postprocessed_dir = self.session.output_dir / "postprocessed" / probe_id
                analyzer = si.load(postprocessed_dir)
                n_units = writer.add_probe_data(probe, analyzer)
                if isinstance(n_units, int):
                    n_units_total += n_units
                del analyzer
                gc.collect()
                self._report_progress(
                    f"Exported {probe_id}",
                    0.1 + 0.7 * (i + 1) / n_probes,
                )

            behavior_events_path = self.session.output_dir / "sync" / "behavior_events.parquet"
            behavior_events = pd.read_parquet(behavior_events_path)
            writer.add_trials(behavior_events)

            nwb_path_written = writer.write()

            # Verify the written file is readable
            io = pynwb.NWBHDF5IO(str(nwb_path_written), "r")
            io.close()

            n_trials = len(behavior_events)
            self._write_checkpoint(
                {
                    "nwb_path": str(nwb_path_written),
                    "n_probes": n_probes,
                    "n_units_total": n_units_total,
                    "n_trials": n_trials,
                }
            )

        except Exception as exc:
            nwb_path.unlink(missing_ok=True)
            self._write_failed_checkpoint(exc)
            if isinstance(exc, ExportError):
                raise
            raise ExportError(str(exc)) from exc

        self._report_progress("Export complete", 1.0)

    def _get_output_path(self) -> Path:
        """Compute the output NWB path: {output_dir}/{session_dir.name}.nwb."""
        return self.session.output_dir / f"{self.session.session_dir.name}.nwb"
