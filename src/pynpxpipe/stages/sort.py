"""Sort stage: spike sorting per probe (local run or external import).

Supports Kilosort4 (default) and import of external sorting results.
Always runs serially (GPU resource constraint). No UI dependencies.
"""

from __future__ import annotations

import dataclasses
import gc
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

# Force non-interactive matplotlib backend before any SI import triggers Tk.
# KS4 uses matplotlib internally; without this, the Tk backend initializes
# in the worker thread and produces "main thread is not in main loop" errors.
os.environ.setdefault("MPLBACKEND", "Agg")

import spikeinterface.core as si
import spikeinterface.extractors as se
import spikeinterface.sorters as ss

from pynpxpipe.core.config import SortingConfig
from pynpxpipe.core.errors import SortError
from pynpxpipe.core.resources import ResourceDetector
from pynpxpipe.core.torch_env import resolve_device
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
    GPU access. Zero units after sorting emits a WARNING but does not raise.

    Raises:
        SortError: If mode is unknown, sorter fails (CUDA OOM etc.), or
            import path doesn't exist.
    """

    STAGE_NAME = "sort"

    def __init__(
        self,
        session: Session,
        sorting_config: SortingConfig | None = None,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the sort stage.

        Args:
            session: Active pipeline session with preprocessed recordings available.
            sorting_config: Sorting configuration; uses SortingConfig defaults when
                None (e.g. standalone testing without a runner).
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        super().__init__(session, progress_callback)
        self.sorting_config = sorting_config if sorting_config is not None else SortingConfig()

    def run(self) -> None:
        """Sort all probes serially (always, regardless of parallel config).

        Raises:
            SortError: If mode is unknown or sorting fails for any probe.
        """
        mode = self.sorting_config.mode
        if mode not in ("local", "import"):
            raise SortError(f"Unknown mode: {mode}")

        if self._is_complete():
            self._report_progress("Sort already complete", 1.0)
            return

        self._report_progress("Starting sort (always serial)", 0.0)

        if not self.session.probes:
            raise SortError(
                "No probes in session. The discover stage may not have run or "
                "failed to populate probes. Re-run from discover."
            )

        n_probes = len(self.session.probes)
        for i, probe in enumerate(self.session.probes):
            probe_id = probe.probe_id
            if mode == "local":
                self._sort_probe_local(probe_id)
            else:
                paths = self.sorting_config.import_cfg.paths
                import_path = paths.get(probe_id)
                if import_path is None:
                    err = SortError(
                        f"Import path not found: no entry for {probe_id} in import_cfg.paths"
                    )
                    self._write_failed_checkpoint(err, probe_id=probe_id)
                    raise err
                self._import_sorting(probe_id, Path(import_path))

            self._report_progress(f"Sorted {probe_id}", (i + 1) / n_probes)

        self._write_checkpoint(
            {
                "probe_ids": [p.probe_id for p in self.session.probes],
                "mode": mode,
            }
        )
        self._report_progress("Sort complete", 1.0)

    def _sort_probe_local(self, probe_id: str) -> None:
        """Run the configured sorter locally for one probe.

        Loads the Zarr preprocessed recording, calls si.run_sorter(), validates
        the output, saves to disk, and releases memory.

        Args:
            probe_id: Identifier of the probe to sort (e.g. "imec0").

        Raises:
            SortError: On sorting failure (CUDA OOM, sorter not installed, etc.).
        """
        if self._is_complete(probe_id=probe_id):
            self._report_progress(f"Skipping already sorted probe {probe_id}", 0.0)
            return

        zarr_path = self.session.output_dir / "01_preprocessed" / f"{probe_id}.zarr"
        recording = si.load(zarr_path)

        sorter_output = self.session.output_dir / "02_sorter_output_KS4" / probe_id
        params = dataclasses.asdict(self.sorting_config.sorter.params)

        # --- CUDA guard: resolve torch_device against real hardware + torch build ---
        # Raises TorchEnvError when the user explicitly requested 'cuda' but either
        # no GPU is present or torch is a CPU build (the silent-failure mode).
        # For 'auto' this falls back to cpu with a warning when torch is CPU-only.
        requested_device = params.get("torch_device", "auto")
        if requested_device in {"auto", "cuda"}:
            profile = ResourceDetector(self.session.session_dir, self.session.output_dir).detect()
            params["torch_device"] = resolve_device(
                requested_device,
                has_physical_gpu=profile.primary_gpu is not None,
            )

        try:
            sorting = ss.run_sorter(
                self.sorting_config.sorter.name,
                recording,
                folder=sorter_output,
                remove_existing_folder=True,
                **params,
            )
        except RuntimeError as exc:
            if "CUDA out of memory" in str(exc) or "OutOfMemoryError" in str(exc):
                original_batch = params.get("batch_size", 60000)
                reduced_batch = max(20000, original_batch // 2)
                self.logger.warning(
                    "CUDA OOM; retrying with reduced batch_size",
                    original_batch_size=original_batch,
                    reduced_batch_size=reduced_batch,
                    probe_id=probe_id,
                )
                params["batch_size"] = reduced_batch
                try:
                    sorting = ss.run_sorter(
                        self.sorting_config.sorter.name,
                        recording,
                        folder=sorter_output,
                        remove_existing_folder=True,
                        **params,
                    )
                except Exception as retry_exc:
                    err = SortError(f"Sorter failed for {probe_id}: {retry_exc}")
                    self._write_failed_checkpoint(err, probe_id=probe_id)
                    raise err from retry_exc
            else:
                err = SortError(f"Sorter failed for {probe_id}: {exc}")
                self._write_failed_checkpoint(err, probe_id=probe_id)
                raise err from exc
        except Exception as exc:
            err = SortError(f"Sorter failed for {probe_id}: {exc}")
            self._write_failed_checkpoint(err, probe_id=probe_id)
            raise err from exc

        n_units = len(sorting.get_unit_ids())
        if n_units == 0:
            self.logger.warning("Zero units after sorting", probe_id=probe_id)

        save_path = self.session.output_dir / "02_sorted" / probe_id
        sorting.save(folder=save_path, overwrite=True)

        self._write_checkpoint(
            {
                "probe_id": probe_id,
                "mode": "local",
                "sorter_name": self.sorting_config.sorter.name,
                "n_units": n_units,
                "output_path": str(save_path),
            },
            probe_id=probe_id,
        )

        del sorting, recording
        gc.collect()

    def _import_sorting(self, probe_id: str, import_path: Path) -> None:
        """Import an externally computed sorting result for one probe.

        Args:
            probe_id: Identifier of the probe.
            import_path: Path to the external Kilosort/Phy output folder.

        Raises:
            SortError: If import_path does not exist or loading fails.
        """
        if self._is_complete(probe_id=probe_id):
            self._report_progress(f"Skipping already imported probe {probe_id}", 0.0)
            return

        if not import_path.exists():
            err = SortError(f"Import path not found: {import_path}")
            self._write_failed_checkpoint(err, probe_id=probe_id)
            raise err

        fmt = self.sorting_config.import_cfg.format
        try:
            if fmt == "phy":
                sorting = se.read_phy(import_path)
            else:  # "kilosort4" or "kilosort"
                sorting = ss.read_sorter_folder(import_path)
        except Exception as exc:
            err = SortError(f"Failed to load sorting for {probe_id}: {exc}")
            self._write_failed_checkpoint(err, probe_id=probe_id)
            raise err from exc

        n_units = len(sorting.get_unit_ids())
        if n_units == 0:
            self.logger.warning("Zero units after import", probe_id=probe_id)

        save_path = self.session.output_dir / "02_sorted" / probe_id
        sorting.save(folder=save_path, overwrite=True)

        self._write_checkpoint(
            {
                "probe_id": probe_id,
                "mode": "import",
                "sorter_name": fmt,
                "n_units": n_units,
                "output_path": str(save_path),
            },
            probe_id=probe_id,
        )

        del sorting
        gc.collect()
