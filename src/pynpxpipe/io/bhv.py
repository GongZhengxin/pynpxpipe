"""MonkeyLogic BHV2 behavioral data parsing.

BHV2 (.bhv2) is MonkeyLogic's proprietary binary format. By default this
module uses :class:`BHV2Reader` (pure Python, no MATLAB dependency).

Set environment variable ``BHV2_BACKEND=matlab`` to switch to the legacy
MATLAB Engine backend (requires ``matlabengine`` package and MATLAB install).

Public API:
  - :class:`TrialData` — dataclass for a single trial's behavioral data.
  - :class:`BHV2Parser` — high-level parser: ``parse()``, ``get_event_code_times()``,
    ``get_session_metadata()``, ``get_analog_data()``, ``get_dataset_tsv_path()``.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pynpxpipe.io.bhv2_reader import BHV2Reader

logger = logging.getLogger(__name__)

# BHV2 file magic: uint64 LE value 13 (len of "IndexPosition") + b'IndexPosition'
BHV2_MAGIC: bytes = b"\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition"


@dataclass
class TrialData:
    """Behavioral data for a single trial.

    Attributes:
        trial_id: 1-indexed trial number from BHV2 (Trial field).
        condition_id: Stimulus condition number (Condition field).
        events: List of (time_ms, event_code) tuples in BHV2 time.
        user_vars: Dict of UserVars fields for this trial. The
            ``DatasetName`` entry (per-trial copy of the session-level
            stimulus tsv path) is read by
            :meth:`BHV2Parser.get_dataset_tsv_path`.
        variable_changes: Dict of VariableChanges for this trial
            (e.g. onset_time, offset_time, fixation_window).
        task_object: Dict of TaskObject fields for this trial. For
            image_train paradigms ``TaskObject.Attribute`` only carries
            a ``'fix'`` stimulus; actual stim filenames live in the
            external tsv referenced by ``user_vars['DatasetName']``.
            Empty dict if the trial carries no TaskObject.
    """

    trial_id: int
    condition_id: int
    events: list[tuple[float, int]]
    user_vars: dict = field(default_factory=dict)
    variable_changes: dict = field(default_factory=dict)
    task_object: dict = field(default_factory=dict)


class BHV2Parser:
    """Parses MonkeyLogic BHV2 files using pure-Python BHV2Reader.

    BHV2 is MonkeyLogic's proprietary binary format (not HDF5). The
    :class:`BHV2Reader` handles binary parsing directly using ``struct``.
    No MATLAB dependency is required.

    Args:
        bhv_file: Path to the MonkeyLogic BHV2 (.bhv2) file.

    Raises:
        FileNotFoundError: If bhv_file does not exist.
        IOError: If the first 21 bytes do not match BHV2_MAGIC.
    """

    def __init__(self, bhv_file: Path) -> None:
        bhv_file = Path(bhv_file)
        if not bhv_file.exists():
            raise FileNotFoundError(f"BHV2 file not found: {bhv_file}")

        with bhv_file.open("rb") as f:
            header = f.read(21)

        if len(header) < 21 or header != BHV2_MAGIC:
            raise OSError(f"Not a valid BHV2 file: {bhv_file}")

        self.bhv_file = bhv_file
        self._reader: BHV2Reader | None = None
        self._cache: list[TrialData] | None = None

    def _get_reader(self) -> BHV2Reader:
        """Lazily create and cache the BHV2Reader instance.

        Returns:
            Open BHV2Reader pointing to self.bhv_file.
        """
        if self._reader is None:
            self._reader = BHV2Reader(self.bhv_file)
        return self._reader

    def parse(self) -> list[TrialData]:
        """Load all trial data from the BHV2 file.

        Results are cached; subsequent calls return the same list.

        Returns:
            TrialData list sorted ascending by trial_id.
        """
        if self._cache is not None:
            return self._cache

        reader = self._get_reader()
        var_names = reader.list_variables()
        trial_var_names = sorted(
            [v for v in var_names if re.fullmatch(r"Trial\d+", v)],
            key=lambda v: int(v[5:]),
        )

        trials: list[TrialData] = []
        for var_name in trial_var_names:
            raw = reader.read(var_name)
            trials.append(self._map_trial(raw))

        trials.sort(key=lambda t: t.trial_id)
        self._cache = trials
        return self._cache

    def get_event_code_times(
        self,
        event_code: int,
        trials: list[int] | None = None,
    ) -> list[tuple[int, float]]:
        """Return (trial_id, time_ms) pairs for all occurrences of an event code.

        Args:
            event_code: Integer event code to search for.
            trials: Optional list of trial_id values to restrict search.
                    None means all trials.

        Returns:
            List of (trial_id, time_ms) tuples sorted by trial_id.
            Empty list if the code is not found.
        """
        all_trials = self.parse()
        if trials is not None:
            trial_set = set(trials)
            all_trials = [t for t in all_trials if t.trial_id in trial_set]

        result: list[tuple[int, float]] = []
        for trial in all_trials:
            for time_ms, code in trial.events:
                if code == event_code:
                    result.append((trial.trial_id, time_ms))
        return result

    def get_session_metadata(self) -> dict:
        """Extract session-level metadata from the BHV2 file.

        Reads MLConfig variable and counts TrialN variables for TotalTrials.

        Returns:
            Dict with keys: ExperimentName, MLVersion, SubjectName, TotalTrials.
        """
        reader = self._get_reader()
        mlconfig = reader.read("MLConfig")
        var_names = reader.list_variables()
        total_trials = sum(1 for v in var_names if re.fullmatch(r"Trial\d+", v))

        return {
            "ExperimentName": str(mlconfig.get("ExperimentName", "")),
            "MLVersion": str(mlconfig.get("MLVersion", "")),
            "SubjectName": str(mlconfig.get("SubjectName", "")),
            "TotalTrials": total_trials,
        }

    def get_analog_data(
        self,
        channel_name: str,
        trials: list[int] | None = None,
    ) -> dict[int, np.ndarray]:
        """Read analog signal data per trial (e.g. Eye, Joystick).

        Data is read trial-by-trial (no 3D pre-allocation). Trials missing
        the requested channel are skipped with a warning log.

        Args:
            channel_name: Analog channel name, e.g. 'Eye', 'Joystick'.
            trials: Optional trial_id list to restrict reading. None = all.

        Returns:
            Dict mapping trial_id → np.ndarray of shape [n_samples, n_ch].
        """
        all_trials = self.parse()
        trial_ids = trials if trials is not None else [t.trial_id for t in all_trials]

        reader = self._get_reader()
        result: dict[int, np.ndarray] = {}
        for tid in trial_ids:
            raw = reader.read(f"Trial{tid}")
            analog = raw.get("AnalogData", {})
            if not isinstance(analog, dict):
                logger.warning("Trial %d AnalogData is not a dict; skipping.", tid)
                continue
            if channel_name not in analog:
                logger.warning("Trial %d has no analog channel '%s'; skipping.", tid, channel_name)
                continue
            arr = analog[channel_name]
            if isinstance(arr, np.ndarray):
                if arr.ndim == 1:
                    arr = arr.reshape(-1, 1)
                result[tid] = arr
            else:
                logger.warning(
                    "Trial %d channel '%s' is not ndarray (%s); skipping.",
                    tid,
                    channel_name,
                    type(arr).__name__,
                )

        return result

    def get_dataset_tsv_path(self) -> str | None:
        """Return the session's stimulus tsv path from ``UserVars.DatasetName``.

        MonkeyLogic writes a per-trial copy of the session-level
        ``DatasetName`` — a Windows absolute path string pointing to an
        external ``.tsv`` stim manifest (e.g.
        ``'C:\\#Datasets\\TripleN10k\\stimuli\\nsd1w.tsv'``). All trials
        share the same value; this reader walks trials and returns the
        first non-empty string found. Different-value sessions log a
        warning (multi-dataset sessions are not supported).

        No filesystem existence check is performed — the caller
        (``io.stim_resolver``) handles fallback lookup under user-
        provided ``image_vault_paths``.

        Returns:
            Windows path string if any trial carries a non-empty
            ``DatasetName``; None if every trial's UserVars lacks the
            key or holds an empty string (legacy non-image paradigm).
        """
        trials = self.parse()
        first_value: str | None = None
        for trial in trials:
            raw = trial.user_vars.get("DatasetName")
            if not isinstance(raw, str) or not raw:
                continue
            if first_value is None:
                first_value = raw
            elif raw != first_value:
                logger.warning(
                    "UserVars.DatasetName varies across trials "
                    "(trial %d = %r vs first = %r); using first non-empty value.",
                    trial.trial_id,
                    raw,
                    first_value,
                )
                break
        return first_value

    def get_sample_interval(self) -> float:
        """Read the analog SampleInterval (ms) from the first trial.

        Returns:
            SampleInterval in milliseconds (typically 4.0 for 250 Hz).
        """
        reader = self._get_reader()
        var_names = reader.list_variables()
        trial_names = sorted(v for v in var_names if re.fullmatch(r"Trial\d+", v))
        if not trial_names:
            return 1.0  # safe fallback
        raw = reader.read(trial_names[0])
        analog = raw.get("AnalogData", {})
        if isinstance(analog, dict):
            return float(analog.get("SampleInterval", 1.0))
        return 1.0

    @staticmethod
    def _map_trial(raw: dict) -> TrialData:
        """Map a raw BHV2Reader trial dict to a TrialData dataclass.

        Args:
            raw: Dict returned by ``BHV2Reader.read("TrialN")``.

        Returns:
            Populated TrialData instance.
        """
        trial_id = int(raw["Trial"])
        condition_id = int(raw["Condition"])

        codes = raw["BehavioralCodes"]
        times_flat = codes["CodeTimes"].flatten().astype(float).tolist()
        numbers_flat = codes["CodeNumbers"].flatten().astype(int).tolist()
        events = list(zip(times_flat, numbers_flat, strict=True))

        user_vars = raw.get("UserVars", {})
        if not isinstance(user_vars, dict):
            user_vars = {}

        variable_changes = raw.get("VariableChanges", {})
        if not isinstance(variable_changes, dict):
            variable_changes = {}

        task_object = raw.get("TaskObject", {})
        if not isinstance(task_object, dict):
            task_object = {}

        return TrialData(
            trial_id=trial_id,
            condition_id=condition_id,
            events=events,
            user_vars=user_vars,
            variable_changes=variable_changes,
            task_object=task_object,
        )


# ---------------------------------------------------------------------------
# Backend compatibility switch
# ---------------------------------------------------------------------------
# Set BHV2_BACKEND=matlab to use the legacy MATLAB Engine parser (requires
# matlabengine package and a local MATLAB installation). Default is "python".

if os.environ.get("BHV2_BACKEND", "").lower() == "matlab":
    from pynpxpipe.io._bhv_matlab import BHV2Parser as BHV2Parser  # noqa: F811
