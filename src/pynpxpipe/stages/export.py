"""Export stage: write all processed data to a single NWB file.

Combines all probe data, behavioral events, and subject metadata into one
NWB 2.x file conforming to DANDI standards. No UI dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class ExportStage(BaseStage):
    """Writes all pipeline outputs to a single NWB file.

    Processes probes one at a time to control memory usage: each probe's
    SortingAnalyzer is loaded, written to NWB, then released before the
    next probe is loaded.

    The LFP interface is stubbed out (``add_lfp`` raises NotImplementedError)
    for future implementation.
    """

    STAGE_NAME = "export"

    def __init__(
        self,
        session: "Session",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the export stage.

        Args:
            session: Active pipeline session with all upstream stages completed.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        raise NotImplementedError("TODO")

    def run(self) -> None:
        """Write all data to the output NWB file.

        Steps:
        1. Check for completed checkpoint; skip if found.
        2. Determine output NWB path: {output_dir}/NWBFile_{session_id}.nwb.
        3. Create NWBFile with subject and session metadata.
        4. For each probe: add electrode group, electrodes, and units table.
        5. Add trials table from behavior_events.parquet.
        6. Add stimulus information from BHV2.
        7. Write NWB file to disk.
        8. Write completed checkpoint with file size.

        Raises:
            ExportError: If NWB write fails. Any partial file is deleted before raising.
        """
        raise NotImplementedError("TODO")

    def _get_output_path(self) -> Path:
        """Compute the output NWB file path.

        The file name is ``NWBFile_{session_id}.nwb`` where session_id is
        derived from the session_dir name.

        Returns:
            Absolute path to the output NWB file.
        """
        raise NotImplementedError("TODO")
