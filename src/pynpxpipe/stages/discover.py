"""Discover stage: scan SpikeGLX folder and validate data integrity.

Populates session.probes and writes session_info.json. No UI dependencies.
"""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class DiscoverStage(BaseStage):
    """Scans the SpikeGLX recording folder and validates all data files.

    After this stage completes, ``session.probes`` is populated with one
    ``ProbeInfo`` per discovered IMEC probe, and a ``session_info.json`` is
    written to ``session.output_dir``.
    """

    STAGE_NAME = "discover"

    def __init__(
        self,
        session: "Session",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the discover stage.

        Args:
            session: Active pipeline session.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        raise NotImplementedError("TODO")

    def run(self) -> None:
        """Scan session_dir for all probes and validate data integrity.

        Steps:
        1. Check for completed checkpoint and skip if found.
        2. Use SpikeGLXDiscovery to find imec{N} directories.
        3. Validate each probe (bin/meta existence and size match).
        4. Locate NIDQ data.
        5. Validate BHV2 file header.
        6. Populate session.probes and write session_info.json.
        7. Write completed checkpoint.

        Raises:
            DiscoverError: If NIDQ files or BHV2 file are not found, or if
                all probe validations fail.
        """
        raise NotImplementedError("TODO")
