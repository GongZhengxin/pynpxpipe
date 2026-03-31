"""Sort stage: spike sorting per probe (local run or external import).

Supports Kilosort4 (default) and import of external sorting results.
Always runs serially (GPU resource constraint). No UI dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class SortStage(BaseStage):
    """Runs spike sorting for each probe and saves the Sorting object.

    Two modes are supported via config.sorting.mode:
    - "local": Run the configured sorter (default Kilosort4) locally.
    - "import": Load an externally computed sorting result from disk.

    This stage always processes probes serially regardless of the pipeline's
    ``parallel.enabled`` setting, because spike sorting requires exclusive
    GPU access.
    """

    STAGE_NAME = "sort"

    def __init__(
        self,
        session: "Session",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the sort stage.

        Args:
            session: Active pipeline session with preprocessed recordings available.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        raise NotImplementedError("TODO")

    def run(self) -> None:
        """Sort all probes serially.

        For each probe (skipping those with a completed checkpoint):
        - In "local" mode: runs the configured sorter on the preprocessed recording.
        - In "import" mode: loads and validates the external sorting folder.

        Raises:
            SortError: If sorting fails (CUDA OOM, invalid import path, etc.).
        """
        raise NotImplementedError("TODO")

    def _sort_probe_local(self, probe_id: str) -> None:
        """Run the configured sorter locally for one probe.

        Loads the Zarr preprocessed recording, calls si.run_sorter(), validates
        the output, then releases the recording object.

        Args:
            probe_id: Identifier of the probe to sort.

        Raises:
            SortError: On sorting failure or empty sorting result.
        """
        raise NotImplementedError("TODO")

    def _import_sorting(self, probe_id: str, import_path: Path) -> None:
        """Import an externally computed sorting result for one probe.

        Loads the sorting folder via si.read_sorter_folder() or si.read_kilosort(),
        validates completeness, and saves to the standard output location.

        Args:
            probe_id: Identifier of the probe.
            import_path: Path to the external Kilosort/Phy output folder.

        Raises:
            SortError: If import_path does not exist or sorting result is invalid.
        """
        raise NotImplementedError("TODO")
