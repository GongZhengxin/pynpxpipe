"""Cross-session run registry kept in the output directory (ui_redesign.md §8.2).

A run started from any browser session writes ``checkpoints/run_state.json`` so
that other sessions (and the session list) can show its progress after the
starting browser tab is closed. A separate ``task_window_pending.json`` marks a
session that stopped after select_segments for the user to confirm task windows.

No UI imports: the UI layer polls these files.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil

RUN_STATE_FILE = "run_state.json"
TASK_WINDOW_PENDING_FILE = "task_window_pending.json"
RUN_STATUSES = ("running", "awaiting_confirmation", "completed", "failed", "stopped")
_PROBE_PREFIX = "["


@dataclass
class RunState:
    """Snapshot of one pipeline run, as stored in ``run_state.json``.

    Attributes:
        run_id: Random id of this run.
        pid: Process running the pipeline.
        started_at: Epoch seconds at start.
        heartbeat_at: Epoch seconds of the last write.
        stages: Stages planned for this run.
        current_stage: Stage of the latest progress message.
        current_probe: Probe of the latest per-probe message, if any.
        fraction: Progress of the current stage in [0, 1].
        status: One of RUN_STATUSES.
        error: First line of the error for failed runs.
    """

    run_id: str
    pid: int
    started_at: float
    heartbeat_at: float
    stages: list[str] = field(default_factory=list)
    current_stage: str = ""
    current_probe: str | None = None
    fraction: float = 0.0
    status: str = "running"
    error: str = ""


def run_state_path(output_dir: Path) -> Path:
    """Return the registry file path for *output_dir*."""
    return Path(output_dir) / "checkpoints" / RUN_STATE_FILE


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def write_run_state(output_dir: Path, state: RunState) -> None:
    """Atomically write *state* to ``checkpoints/run_state.json``.

    Args:
        output_dir: Session output root.
        state: Snapshot to persist.
    """
    _atomic_write(run_state_path(output_dir), asdict(state))


def read_run_state(output_dir: Path) -> RunState | None:
    """Read the registry, or None when it is missing or unreadable.

    Args:
        output_dir: Session output root.

    Returns:
        The stored RunState, or None.
    """
    try:
        data = json.loads(run_state_path(output_dir).read_text(encoding="utf-8"))
        return RunState(**data)
    except (OSError, ValueError, TypeError):
        return None


def effective_status(
    state: RunState,
    *,
    now: float | None = None,
    timeout_s: float,
    pid_alive: Callable[[int], bool] = psutil.pid_exists,
) -> str:
    """Return the status to show, turning dead or silent "running" runs into "interrupted".

    Args:
        state: Stored snapshot.
        now: Current epoch seconds (defaults to time.time()).
        timeout_s: Heartbeat age after which a running run counts as interrupted.
        pid_alive: Process liveness check (injectable for tests).

    Returns:
        ``state.status``, or ``"interrupted"``.
    """
    if state.status != "running":
        return state.status
    now = time.time() if now is None else now
    if now - state.heartbeat_at > timeout_s or not pid_alive(state.pid):
        return "interrupted"
    return "running"


def _parse_message(message: str) -> tuple[str, str | None]:
    """Split ``"stage:[probe] text"`` (ui_redesign §8.5) into stage and optional probe."""
    stage, _, rest = message.partition(":")
    rest = rest.lstrip()
    if rest.startswith(_PROBE_PREFIX) and "]" in rest:
        return stage, rest[1 : rest.index("]")]
    return stage, None


class RunStateRecorder:
    """Feeds progress messages into ``run_state.json`` with throttled writes.

    Args:
        output_dir: Session output root.
        stages: Stages planned for the run.
        heartbeat_s: Minimum interval between writes within one stage.
        clock: Epoch-seconds source (injectable for tests).
    """

    def __init__(
        self,
        output_dir: Path,
        stages: list[str],
        *,
        heartbeat_s: float,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._output_dir = Path(output_dir)
        self._heartbeat_s = heartbeat_s
        self._clock = clock
        now = clock()
        self.state = RunState(uuid.uuid4().hex, os.getpid(), now, now, list(stages))
        self._last_write = now

    def _write(self) -> None:
        now = self._clock()
        self.state.heartbeat_at = now
        self._last_write = now
        write_run_state(self._output_dir, self.state)

    def start(self) -> None:
        """Record the run as running."""
        self.state.status = "running"
        self._write()

    def callback(self, message: str, fraction: float) -> None:
        """Progress-callback compatible ``(message, fraction)`` sink."""
        stage, probe = _parse_message(message)
        changed = stage != self.state.current_stage or probe != self.state.current_probe
        self.state.current_stage = stage
        self.state.current_probe = probe
        self.state.fraction = float(fraction)
        due = self._clock() - self._last_write >= self._heartbeat_s
        if changed or fraction >= 1.0 or due:
            self._write()

    def heartbeat(self) -> None:
        """Refresh ``heartbeat_at`` even when no progress arrives (long stages)."""
        self._write()

    def finish(self, status: str, error: str = "") -> None:
        """Record the final status.

        Args:
            status: One of RUN_STATUSES other than "running".
            error: Error text; only the first line is kept.

        Raises:
            ValueError: For an unknown status.
        """
        if status not in RUN_STATUSES:
            raise ValueError(f"Unknown run status: {status!r}")
        self.state.status = status
        self.state.error = (error.strip().splitlines() or [""])[0]
        self._write()


def _pending_path(output_dir: Path) -> Path:
    return Path(output_dir) / "checkpoints" / TASK_WINDOW_PENDING_FILE


def mark_task_window_pending(output_dir: Path) -> None:
    """Mark that the run paused after select_segments for task-window confirmation."""
    _atomic_write(_pending_path(output_dir), {"marked_at": time.time()})


def is_task_window_pending(output_dir: Path) -> bool:
    """Whether task windows still await confirmation."""
    return _pending_path(output_dir).exists()


def clear_task_window_pending(output_dir: Path) -> None:
    """Remove the pending marker once the user confirms the task windows."""
    _pending_path(output_dir).unlink(missing_ok=True)
