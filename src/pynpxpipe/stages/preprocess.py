"""Preprocess stage: bandpass filter, CMR, and motion correction per probe.

Saves preprocessed recordings as Zarr format. No UI dependencies.
"""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session


class PreprocessStage(BaseStage):
    """Applies preprocessing pipeline to each probe's AP recording.

    Processing order per probe: bad channel detection → bandpass filter →
    common median reference → motion correction → save as Zarr.

    Each probe is processed serially. After each probe, large objects are
    deleted and gc.collect() is called.
    """

    STAGE_NAME = "preprocess"

    def __init__(
        self,
        session: "Session",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the preprocess stage.

        Args:
            session: Active pipeline session with probes populated.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        raise NotImplementedError("TODO")

    def run(self) -> None:
        """Preprocess all probes serially.

        For each probe (skipping those with a completed checkpoint):
        1. Load AP recording lazily via SpikeGLXLoader.
        2. Detect and remove bad channels.
        3. Apply bandpass filter.
        4. Apply common median reference.
        5. Apply motion correction (if configured).
        6. Save to Zarr at {output_dir}/preprocessed/{probe_id}/.
        7. Write per-probe checkpoint; del recording + gc.collect().

        Raises:
            PreprocessError: If Zarr write fails (disk full, permissions).
        """
        raise NotImplementedError("TODO")

    def _preprocess_probe(self, probe_id: str) -> None:
        """Run the full preprocessing pipeline for a single probe.

        Args:
            probe_id: Identifier of the probe to process (e.g. "imec0").

        Raises:
            PreprocessError: On unrecoverable processing failure.
        """
        raise NotImplementedError("TODO")
