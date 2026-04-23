"""Discover stage: scan SpikeGLX folder and validate data integrity.

Populates session.probes and writes session_info.json. No UI dependencies.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from pynpxpipe.core.errors import DiscoverError, ProbeDeclarationMismatchError
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
            self._restore_probes_from_disk()
            self._report_progress("Discover already complete", 1.0)
            return

        # Pre-scan: session.probe_plan must be non-empty (UI/CLI contract).
        if not self.session.probe_plan:
            exc = DiscoverError("session.probe_plan is empty; at least one probe must be declared")
            self._write_failed_checkpoint(exc)
            raise exc

        self._report_progress("Scanning session directory", 0.0)

        try:
            discovery = SpikeGLXDiscovery(self.session.session_dir)

            # Step 1: discover probes
            probes = discovery.discover_probes()
            if not probes:
                raise DiscoverError(f"No IMEC probes found in {self.session.session_dir}")

            # Step 2: probe_plan ↔ disk consistency check
            declared = set(self.session.probe_plan.keys())
            found = {p.probe_id for p in probes}
            if declared != found:
                raise ProbeDeclarationMismatchError(declared, found)

            # Step 3: inject target_area from probe_plan into each discovered probe
            for probe in probes:
                probe.target_area = self.session.probe_plan[probe.probe_id]

            # Step 4: validate probes, collect warnings
            warnings: list[str] = []
            for probe in probes:
                warnings.extend(discovery.validate_probe(probe))

            # Step 5: discover NIDQ (raises DiscoverError if not found)
            discovery.discover_nidq()

            # Step 6: determine lf_found from probe metadata
            lf_found = any(p.lf_bin is not None for p in probes)

            # Step 7: validate BHV2 magic bytes
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

        # Persist probes to session.json so resuming works
        from pynpxpipe.core.session import SessionManager

        SessionManager.save(self.session)

        probe_ids = [p.probe_id for p in probes]
        probe_sample_rates = {p.probe_id: p.sample_rate for p in probes}
        probe_target_areas = {p.probe_id: p.target_area for p in probes}

        # Write session_info.json
        session_info = {
            "session_dir": str(self.session.session_dir),
            "n_probes": len(probes),
            "probe_ids": probe_ids,
            "probe_sample_rates": probe_sample_rates,
            "probe_target_areas": probe_target_areas,
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

    def _restore_probes_from_disk(self) -> None:
        """Restore session.probes from session_info.json when discover is skipped.

        If session.probes is already populated (e.g. loaded from session.json),
        this is a no-op. Otherwise reads probe_ids from session_info.json and
        re-discovers them from the raw SpikeGLX folder.

        Raises:
            DiscoverError: If session_info.json is missing/corrupt, or re-discovery
                finds no matching probes.
        """
        if self.session.probes:
            return

        info_path = self.session.output_dir / "session_info.json"
        if not info_path.exists():
            raise DiscoverError(
                "Discover checkpoint exists but session_info.json is missing. "
                "Delete the discover checkpoint and re-run."
            )

        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise DiscoverError(f"Corrupt session_info.json: {exc}") from exc

        expected_ids = set(info.get("probe_ids", []))
        if not expected_ids:
            raise DiscoverError(
                "session_info.json has no probe_ids. Delete the discover checkpoint and re-run."
            )

        discovery = SpikeGLXDiscovery(self.session.session_dir)
        probes = discovery.discover_probes()
        probes = [p for p in probes if p.probe_id in expected_ids]
        probes.sort(key=lambda p: p.probe_id)

        if not probes:
            raise DiscoverError(
                f"Re-discovery found no probes matching {expected_ids}. "
                "Delete the discover checkpoint and re-run."
            )

        # Re-inject target_area from probe_plan (discover_probes returns "" placeholder)
        for probe in probes:
            if probe.probe_id in self.session.probe_plan:
                probe.target_area = self.session.probe_plan[probe.probe_id]

        self.session.probes = probes
        self.logger.info(
            "Restored %d probe(s) from disk: %s",
            len(probes),
            [p.probe_id for p in probes],
        )
