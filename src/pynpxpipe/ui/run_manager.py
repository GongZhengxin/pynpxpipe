"""ui/run_manager.py — Process-wide owner of pipeline runs (ui_redesign.md §8.2).

Runs belong to the ``pynpxpipe-ui`` server process, not to the browser session
that started them: closing a tab leaves the run going, and any session can read
its progress from ``checkpoints/run_state.json``. One run per output directory.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pynpxpipe.pipelines.run_state import RunStateRecorder, mark_task_window_pending
from pynpxpipe.ui.settings import UISettings, load_ui_settings

ProgressCallback = Callable[[str, float], None]
RunTarget = Callable[[ProgressCallback, threading.Event], None]


class RunInterrupted(Exception):
    """Raised from the progress callback when a stopped run reaches its next stage."""


@dataclass
class RunHandle:
    """A started run: its worker thread, stop flag and (after finishing) error."""

    output_dir: Path
    thread: threading.Thread
    interrupt: threading.Event
    error: BaseException | None = None
    _done: threading.Event = field(default_factory=threading.Event)


class RunManager:
    """Starts, tracks and stops pipeline runs keyed by output directory.

    Args:
        settings: UI settings (heartbeat interval); defaults to config/ui.yaml.
    """

    def __init__(self, settings: UISettings | None = None) -> None:
        self._settings = settings or load_ui_settings()
        self._lock = threading.Lock()
        self._runs: dict[Path, RunHandle] = {}

    @staticmethod
    def _key(output_dir: Path | str) -> Path:
        return Path(output_dir).resolve()

    def is_running(self, output_dir: Path | str) -> bool:
        """Whether a run for *output_dir* is still executing in this process."""
        handle = self._runs.get(self._key(output_dir))
        return handle is not None and not handle._done.is_set()

    def start(
        self,
        output_dir: Path | str,
        target: RunTarget,
        stages: list[str],
        *,
        final_status: str = "completed",
    ) -> RunHandle | None:
        """Run ``target(callback, interrupt)`` in a background thread.

        ``callback`` records progress in run_state.json and raises RunInterrupted
        at the first message of a new stage after :meth:`stop`.

        Args:
            output_dir: Session output root (registry location, de-duplication key).
            target: Work to run; must pass ``callback`` on as its progress callback.
            stages: Stages planned for the run (stored in the registry).
            final_status: Status recorded on success ("awaiting_confirmation" for
                align-then-confirm runs, which also marks task windows pending).

        Returns:
            The RunHandle, or None if a run for this directory is already active.
        """
        key = self._key(output_dir)
        with self._lock:
            if self.is_running(key):
                return None
            recorder = RunStateRecorder(key, stages, heartbeat_s=self._settings.heartbeat_s)
            interrupt = threading.Event()
            handle = RunHandle(key, threading.Thread(daemon=True), interrupt)
            handle.thread = threading.Thread(
                target=self._run,
                args=(handle, recorder, target, final_status),
                daemon=True,
                name=f"pynpxpipe-run-{key.name}",
            )
            self._runs[key] = handle
            recorder.start()
            handle.thread.start()
        return handle

    def stop(self, output_dir: Path | str) -> bool:
        """Ask the run for *output_dir* to stop at its next stage boundary.

        Returns:
            True if a running job was signalled.
        """
        handle = self._runs.get(self._key(output_dir))
        if handle is None or handle._done.is_set():
            return False
        handle.interrupt.set()
        return True

    def _run(
        self,
        handle: RunHandle,
        recorder: RunStateRecorder,
        target: RunTarget,
        final_status: str,
    ) -> None:
        stage_seen = {"stage": None}

        def callback(message: str, fraction: float) -> None:
            stage = message.partition(":")[0]
            if handle.interrupt.is_set() and stage != stage_seen["stage"]:
                raise RunInterrupted(f"Stopped by user before {stage}")
            stage_seen["stage"] = stage
            recorder.callback(message, fraction)

        beat_stop = threading.Event()

        def beat() -> None:
            while not beat_stop.wait(self._settings.heartbeat_s):
                recorder.heartbeat()

        beater = threading.Thread(target=beat, daemon=True)
        beater.start()
        status, error = final_status, ""
        try:
            target(callback, handle.interrupt)
            if handle.interrupt.is_set():
                status = "stopped"
        except RunInterrupted as exc:
            handle.error, status, error = exc, "stopped", str(exc)
        except BaseException as exc:  # noqa: BLE001 — recorded, then re-raised to the caller's view
            handle.error, status, error = exc, "failed", str(exc) or type(exc).__name__
        finally:
            beat_stop.set()
            beater.join(timeout=self._settings.heartbeat_s)
            if status == "awaiting_confirmation":
                mark_task_window_pending(handle.output_dir)
            recorder.finish(status, error)
            handle._done.set()


_MANAGER: RunManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_run_manager() -> RunManager:
    """Return the process-wide RunManager (created on first use)."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = RunManager()
        return _MANAGER
