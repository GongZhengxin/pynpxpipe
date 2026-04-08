"""MonkeyLogic BHV2 behavioral data parsing — MATLAB Engine backend.

This module is the legacy implementation preserved for comparison. Set
environment variable ``BHV2_BACKEND=matlab`` to use this backend.

BHV2 (.bhv2) is MonkeyLogic's proprietary binary format. Reading requires
MATLAB Python Engine (matlab.engine) plus the mlbhv2.m class from the
legacy_reference utilities. No UI dependencies.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# BHV2 file magic: uint64 LE value 13 (len of "IndexPosition") + b'IndexPosition'
BHV2_MAGIC: bytes = b"\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition"

# Path to mlbhv2.m (project_root/legacy_reference/pyneuralpipe/Util/)
_MLBHV2_DIR = (
    Path(__file__).parent.parent.parent.parent / "legacy_reference" / "pyneuralpipe" / "Util"
)


@dataclass
class TrialData:
    """Behavioral data for a single trial.

    Attributes:
        trial_id: 1-indexed trial number from BHV2 (Trial field).
        condition_id: Stimulus condition number (Condition field).
        events: List of (time_ms, event_code) tuples in BHV2 time.
        user_vars: Dict of UserVars fields for this trial.
    """

    trial_id: int
    condition_id: int
    events: list[tuple[float, int]]
    user_vars: dict = field(default_factory=dict)


class BHV2Parser:
    """Parses MonkeyLogic BHV2 files via MATLAB Python Engine.

    BHV2 is MonkeyLogic's proprietary binary format. The mlbhv2 MATLAB class
    (legacy_reference/pyneuralpipe/Util/mlbhv2.m) handles binary parsing.
    The MATLAB Engine is started lazily on first use and cached for the
    lifetime of this parser instance.

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
        self._engine = None
        self._cache: list[TrialData] | None = None

    def _get_engine(self):
        """Lazily start and cache the MATLAB Engine.

        Adds the mlbhv2.m directory to MATLAB path on first call.

        Returns:
            Running matlab.engine instance.
        """
        if self._engine is None:
            import matlab.engine

            self._engine = matlab.engine.start_matlab()
            self._engine.addpath(str(_MLBHV2_DIR), nargout=0)
            logger.info("MATLAB engine started, mlbhv2 path added: %s", _MLBHV2_DIR)
        return self._engine

    def parse(self) -> list[TrialData]:
        """Load all trial data from the BHV2 file via MATLAB Engine.

        Results are cached; subsequent calls return the same list without
        re-invoking MATLAB.

        Returns:
            TrialData list sorted ascending by trial_id.
        """
        if self._cache is not None:
            return self._cache

        eng = self._get_engine()
        safe_path = str(self.bhv_file).replace("\\", "/")
        eng.eval(f"bhv2obj = mlbhv2('{safe_path}');", nargout=0)

        # Enumerate TrialN variable names
        all_vars = list(eng.eval("bhv2obj.who()", nargout=1))
        trial_var_names = sorted(
            [v for v in all_vars if re.fullmatch(r"Trial\d+", v)],
            key=lambda v: int(v[5:]),
        )

        trials: list[TrialData] = []
        for var_name in trial_var_names:
            eng.eval(f"bhv2t = bhv2obj.read('{var_name}');", nargout=0)

            trial_id = int(eng.eval("bhv2t.Trial", nargout=1))
            condition_id = int(eng.eval("bhv2t.Condition", nargout=1))

            # BehavioralCodes → list of (time_ms, code) tuples
            times = eng.eval("bhv2t.BehavioralCodes.CodeTimes", nargout=1)
            codes = eng.eval("bhv2t.BehavioralCodes.CodeNumbers", nargout=1)
            times_flat = [float(x) for x in np.array(times).flatten()]
            codes_flat = [int(x) for x in np.array(codes).flatten()]
            events = list(zip(times_flat, codes_flat, strict=True))

            # UserVars: MATLAB engine returns dict directly
            user_vars = eng.eval("bhv2t.UserVars", nargout=1)
            if not isinstance(user_vars, dict):
                user_vars = {}

            trials.append(
                TrialData(
                    trial_id=trial_id,
                    condition_id=condition_id,
                    events=events,
                    user_vars=user_vars,
                )
            )

        eng.eval("bhv2obj.close(); clear bhv2obj bhv2t", nargout=0)

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
        eng = self._get_engine()
        safe_path = str(self.bhv_file).replace("\\", "/")
        eng.eval(f"bhv2meta = mlbhv2('{safe_path}');", nargout=0)
        eng.eval("bhv2cfg = bhv2meta.read('MLConfig');", nargout=0)

        all_vars = list(eng.eval("bhv2meta.who()", nargout=1))
        total_trials = sum(1 for v in all_vars if re.fullmatch(r"Trial\d+", v))

        metadata = {
            "ExperimentName": str(eng.eval("bhv2cfg.ExperimentName", nargout=1)),
            "MLVersion": str(eng.eval("bhv2cfg.MLVersion", nargout=1)),
            "SubjectName": str(eng.eval("bhv2cfg.SubjectName", nargout=1)),
            "TotalTrials": total_trials,
        }

        eng.eval("bhv2meta.close(); clear bhv2meta bhv2cfg", nargout=0)
        return metadata

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

        eng = self._get_engine()
        safe_path = str(self.bhv_file).replace("\\", "/")
        eng.eval(f"bhv2ad = mlbhv2('{safe_path}');", nargout=0)

        result: dict[int, np.ndarray] = {}
        for tid in trial_ids:
            eng.eval(f"bhv2adtrial = bhv2ad.read('Trial{tid}');", nargout=0)
            try:
                data = eng.eval(f"bhv2adtrial.AnalogData.{channel_name}", nargout=1)
                arr = np.array(data)
                if arr.ndim == 1:
                    arr = arr.reshape(-1, 1)
                result[tid] = arr
            except Exception:
                logger.warning("Trial %d has no analog channel '%s'; skipping.", tid, channel_name)

        eng.eval("bhv2ad.close(); clear bhv2ad bhv2adtrial", nargout=0)
        return result
