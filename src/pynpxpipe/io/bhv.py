"""MonkeyLogic BHV2 behavioral data parsing.

Parses BHV2 files produced by NIMH MonkeyLogic. Uses h5py for v7.3 MAT files
(the format written when MATLAB saves with -v7.3 flag). No UI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TrialData:
    """Behavioral data for a single trial.

    Attributes:
        trial_id: 1-indexed trial number from BHV2.
        condition_id: Stimulus condition number.
        events: List of (time_ms, event_code) tuples in BHV2 time.
        user_vars: Dict of UserVars fields for this trial.
    """

    trial_id: int
    condition_id: int
    events: list[tuple[float, int]]
    user_vars: dict


class BHV2Parser:
    """Parses MonkeyLogic BHV2 files without requiring MATLAB.

    BHV2 files are MATLAB .mat files saved in v7.3 format (HDF5). This parser
    uses h5py directly. The struct array layout is: top-level variable ``MLConfig``
    for session metadata and a trial struct array for per-trial data.

    Note:
        The legacy codebase required MATLAB engine for BHV2 conversion. This
        parser handles BHV2 natively in Python via h5py.
    """

    def __init__(self, bhv_file: Path) -> None:
        """Initialize the BHV2 parser.

        Args:
            bhv_file: Path to the MonkeyLogic BHV2 (.bhv2) file.

        Raises:
            FileNotFoundError: If bhv_file does not exist.
            ValueError: If the file header does not match the expected BHV2 magic bytes.
        """
        raise NotImplementedError("TODO")

    def parse(self) -> list[TrialData]:
        """Parse all trials from the BHV2 file.

        Reads the HDF5 structure, extracts per-trial events and user variables,
        and returns a list of TrialData objects.

        Returns:
            List of TrialData objects, one per trial, sorted by trial_id.

        Raises:
            IOError: If the file cannot be read.
            KeyError: If expected HDF5 fields are missing.
        """
        raise NotImplementedError("TODO")

    def get_event_code_times(
        self, event_code: int, trials: list[TrialData] | None = None
    ) -> list[tuple[int, float]]:
        """Get (trial_id, time_ms) pairs for all occurrences of a specific event code.

        Args:
            event_code: The MonkeyLogic event code to search for (read from config,
                not hardcoded).
            trials: List of TrialData to search. If None, parses the file first.

        Returns:
            List of (trial_id, time_ms_in_bhv2_clock) tuples sorted by trial_id.
        """
        raise NotImplementedError("TODO")

    def get_session_metadata(self) -> dict:
        """Extract session-level metadata from the MLConfig block.

        Returns:
            Dict with fields such as ExperimentName, MLVersion, TotalTrials, etc.
        """
        raise NotImplementedError("TODO")

    def _load_h5py_struct(self, h5_group) -> dict:
        """Recursively convert an h5py Group (MATLAB struct) to a Python dict.

        Handles MATLAB v7.3 struct arrays, cell arrays, and scalar types.
        Based on the battle-tested logic from the legacy data_loader.py.

        Args:
            h5_group: An h5py Group or Dataset object.

        Returns:
            Python dict or array with MATLAB types converted to native Python types.
        """
        raise NotImplementedError("TODO")

    def _normalize_scalar(self, value) -> int | float | str:
        """Convert h5py scalar datasets to native Python types.

        Args:
            value: An h5py Dataset or numpy scalar.

        Returns:
            Python int, float, or str.
        """
        raise NotImplementedError("TODO")
