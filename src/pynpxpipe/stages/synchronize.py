"""Synchronize stage: two-level time alignment (IMEC↔NIDQ, BHV2↔NIDQ).

Produces per-probe time correction functions and a unified behavioral events table.
No UI dependencies.
"""

from __future__ import annotations

from typing import Callable, TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd
    from pynpxpipe.core.session import Session


class SynchronizeStage(BaseStage):
    """Aligns all data streams to the NIDQ clock.

    Level 1 — IMEC ↔ NIDQ: extracts sync pulse edges from each probe's AP
    digital channel and the NIDQ digital channel, then fits a linear correction
    function t_nidq = a × t_imec + b per probe.

    Level 2 — BHV2 ↔ NIDQ: extracts MonkeyLogic digital event codes from the
    NIDQ digital channel and aligns them to BHV2 trial timestamps.

    Outputs:
    - ``{output_dir}/sync/sync_tables.json`` — per-probe time correction params
    - ``{output_dir}/sync/behavior_events.parquet`` — unified behavioral events
    """

    STAGE_NAME = "synchronize"

    def __init__(
        self,
        session: "Session",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None:
        """Initialize the synchronize stage.

        Args:
            session: Active pipeline session with probes and bhv_file available.
            progress_callback: Optional GUI/progress callback; None in CLI mode.
        """
        raise NotImplementedError("TODO")

    def run(self) -> None:
        """Execute both levels of synchronization.

        Steps:
        1. Check for completed checkpoint; skip if found.
        2. Level 1: align each probe to NIDQ (calls _align_probe_to_nidq).
        3. Validate all alignment errors are within max_time_error_ms.
        4. Level 2: parse BHV2 and align to NIDQ (calls _align_bhv2_to_nidq).
        5. Save sync_tables.json and behavior_events.parquet.
        6. Write completed checkpoint.

        Raises:
            SyncError: If any probe alignment error exceeds max_time_error_ms,
                or if BHV2 trial count mismatch exceeds trial_count_tolerance.
        """
        raise NotImplementedError("TODO")

    def _align_probe_to_nidq(
        self,
        probe_id: str,
        nidq_sync_times: "np.ndarray",
    ) -> tuple[float, float, float]:
        """Fit a linear time correction function for one probe.

        Extracts sync pulse rising edges from the probe's AP digital channel,
        pairs them with NIDQ sync edges, and performs least-squares regression.

        Args:
            probe_id: Probe identifier (e.g. "imec0").
            nidq_sync_times: Array of NIDQ sync pulse times in seconds.

        Returns:
            Tuple (a, b, residual_ms) where t_nidq = a × t_imec + b and
            residual_ms is the RMS alignment error in milliseconds.

        Raises:
            SyncError: If residual_ms > config.sync.max_time_error_ms.
        """
        raise NotImplementedError("TODO")

    def _align_bhv2_to_nidq(
        self,
        nidq_event_times: "np.ndarray",
        nidq_event_codes: "np.ndarray",
    ) -> "pd.DataFrame":
        """Align BHV2 trial events to the NIDQ time axis.

        Parses the BHV2 file, extracts event code sequences, matches them to
        NIDQ digital events, and produces the behavior_events DataFrame.
        Attempts auto-repair if trial counts differ by at most
        config.sync.trial_count_tolerance.

        Args:
            nidq_event_times: Array of event times in NIDQ seconds.
            nidq_event_codes: Array of integer event codes from NIDQ digital channel.

        Returns:
            DataFrame with columns: trial_id, onset_nidq_s, stim_onset_nidq_s,
            condition_id, trial_valid.

        Raises:
            SyncError: If trial count mismatch exceeds trial_count_tolerance.
        """
        raise NotImplementedError("TODO")

    def _decode_nidq_events(
        self,
        nidq_recording,
        event_bits: list[int],
        sample_rate: float,
    ) -> tuple["np.ndarray", "np.ndarray"]:
        """Decode MonkeyLogic event codes from NIDQ digital channel bits.

        Reads the specified bit positions from the NIDQ digital channel,
        assembles them into integer event codes at each transition, and
        converts sample indices to seconds.

        Args:
            nidq_recording: Lazy NIDQ SpikeInterface Recording.
            event_bits: List of bit positions for event code decoding.
            sample_rate: NIDQ sampling rate in Hz (read from meta, not hardcoded).

        Returns:
            Tuple (event_times_s, event_codes) as numpy arrays.
        """
        raise NotImplementedError("TODO")
