"""Discover stage: scan SpikeGLX folder and validate data integrity.

Populates session.probes and writes session_info.json. No UI dependencies.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING

from pynpxpipe.core.errors import DiscoverError
from pynpxpipe.io.spikeglx import SpikeGLXDiscovery
from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session

BHV2_MAGIC = b"\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition"


class DiscoverStage(BaseStage):
    """Scans the SpikeGLX recording folder and validates all data files.

    After this stage completes, ``session.probes`` is populated with one
    ``ProbeInfo`` per discovered IMEC probe, and a ``session_info.json`` is
    written to ``session.output_dir``.

    Raises:
        DiscoverError: If no probes found, NIDQ missing, or BHV2 file invalid.
    """

    STAGE_NAME = "discover"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the discover stage.

        Args:
            session: Active pipeline session.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        super().__init__(session, progress_callback)

    def run(self) -> None:
        """Scan session_dir for all probes and validate data integrity.

        Steps:
        1. Check for completed checkpoint and skip if found.
        2. Use SpikeGLXDiscovery to find imec{N} directories.
        3. Validate each probe (bin/meta existence and size match).
        4. Locate NIDQ data.
        5. Validate BHV2 file header magic bytes.
        6. Populate session.probes and write session_info.json.
        7. Write completed checkpoint.

        Raises:
            DiscoverError: If NIDQ files or BHV2 file are not found, or if
                no probes are discovered.
        """
        if self._is_complete():
            self._report_progress("Discover already complete", 1.0)
            return

        self._report_progress("Scanning session directory", 0.0)

        try:
            discovery = SpikeGLXDiscovery(self.session.session_dir)

            # Step 1: discover probes
            probes = discovery.discover_probes()
            if not probes:
                raise DiscoverError(f"No IMEC probes found in {self.session.session_dir}")

            # Step 2: validate probes, collect warnings
            warnings: list[str] = []
            for probe in probes:
                warnings.extend(discovery.validate_probe(probe))

            # Step 3: discover NIDQ (raises DiscoverError if not found)
            discovery.discover_nidq()

            # Step 4: determine lf_found from probe metadata
            lf_found = any(p.lf_bin is not None for p in probes)

            # Step 5: validate BHV2 magic bytes
            bhv_path = self.session.bhv_file
            if not bhv_path.exists():
                raise DiscoverError(f"BHV2 file not found: {bhv_path}")
            header = bhv_path.read_bytes()[: len(BHV2_MAGIC)]
            if header != BHV2_MAGIC:
                raise DiscoverError(
                    f"BHV2 file {bhv_path} is not a valid BHV2 file (magic bytes do not match)"
                )

        except DiscoverError as exc:
            self._write_failed_checkpoint(exc)
            raise

        # Step 6: sort probes alphabetically and populate session.probes
        probes.sort(key=lambda p: p.probe_id)
        self.session.probes = probes

        probe_ids = [p.probe_id for p in probes]
        probe_sample_rates = {p.probe_id: p.sample_rate for p in probes}

        # Step 7: write session_info.json
        session_info = {
            "session_dir": str(self.session.session_dir),
            "n_probes": len(probes),
            "probe_ids": probe_ids,
            "probe_sample_rates": probe_sample_rates,
            "nidq_found": True,
            "lf_found": lf_found,
            "bhv_file": str(self.session.bhv_file),
            "warnings": warnings,
        }
        info_path = self.session.output_dir / "session_info.json"
        info_path.write_text(json.dumps(session_info, indent=2), encoding="utf-8")

        # Step 8: write completed checkpoint
        self._write_checkpoint(
            {
                "n_probes": len(probes),
                "probe_ids": probe_ids,
                "nidq_found": True,
                "lf_found": lf_found,
                "warnings": warnings,
            }
        )

        self._report_progress("Discover complete", 1.0)
