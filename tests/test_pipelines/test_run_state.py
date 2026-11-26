"""Tests for pipelines/run_state.py — cross-session run registry (ui_redesign.md §8.2)."""

from __future__ import annotations

import json
import os

import pytest

from pynpxpipe.pipelines.run_state import (
    RunState,
    RunStateRecorder,
    clear_task_window_pending,
    effective_status,
    is_task_window_pending,
    mark_task_window_pending,
    read_run_state,
    run_state_path,
    write_run_state,
)


def _state(**kw) -> RunState:
    base = {
        "run_id": "r1",
        "pid": os.getpid(),
        "started_at": 100.0,
        "heartbeat_at": 100.0,
        "stages": ["discover", "sort"],
        "current_stage": "",
        "current_probe": None,
        "fraction": 0.0,
        "status": "running",
        "error": "",
    }
    base.update(kw)
    return RunState(**base)


class TestReadWrite:
    def test_round_trip(self, tmp_path):
        write_run_state(tmp_path, _state(current_stage="sort", fraction=0.5))
        assert read_run_state(tmp_path) == _state(current_stage="sort", fraction=0.5)
        assert run_state_path(tmp_path) == tmp_path / "checkpoints" / "run_state.json"
        assert not list((tmp_path / "checkpoints").glob("*.tmp"))

    def test_missing_or_corrupt_file_reads_as_none(self, tmp_path):
        assert read_run_state(tmp_path) is None
        run_state_path(tmp_path).parent.mkdir(parents=True)
        run_state_path(tmp_path).write_text("{not json", encoding="utf-8")
        assert read_run_state(tmp_path) is None


class TestEffectiveStatus:
    def test_fresh_running_stays_running(self):
        assert effective_status(_state(), now=120.0, timeout_s=60) == "running"

    def test_stale_heartbeat_is_interrupted(self):
        assert effective_status(_state(), now=200.0, timeout_s=60) == "interrupted"

    def test_dead_process_is_interrupted(self):
        rs = _state()
        assert (
            effective_status(rs, now=101.0, timeout_s=60, pid_alive=lambda pid: False)
            == "interrupted"
        )

    def test_finished_status_is_kept(self):
        rs = _state(status="completed", heartbeat_at=0.0)
        assert effective_status(rs, now=10_000.0, timeout_s=60) == "completed"


class TestRecorder:
    def _recorder(self, tmp_path, clock):
        return RunStateRecorder(tmp_path, ["discover", "sort"], heartbeat_s=5, clock=clock)

    def test_start_writes_running_state(self, tmp_path):
        rec = self._recorder(tmp_path, clock=lambda: 50.0)
        rec.start()
        rs = read_run_state(tmp_path)
        assert rs.status == "running"
        assert rs.stages == ["discover", "sort"]
        assert rs.started_at == rs.heartbeat_at == 50.0
        assert rs.pid == os.getpid()

    def test_callback_parses_stage_and_probe(self, tmp_path):
        now = [0.0]
        rec = self._recorder(tmp_path, clock=lambda: now[0])
        rec.start()
        now[0] = 1.0
        rec.callback("sort:[imec1] batch 3 / 10", 0.3)
        rs = read_run_state(tmp_path)
        assert (rs.current_stage, rs.current_probe, rs.fraction) == ("sort", "imec1", 0.3)

    def test_same_stage_updates_are_throttled(self, tmp_path):
        now = [0.0]
        rec = self._recorder(tmp_path, clock=lambda: now[0])
        rec.start()
        rec.callback("sort:Starting", 0.0)
        now[0] = 1.0
        rec.callback("sort:half", 0.5)
        assert read_run_state(tmp_path).fraction == 0.0
        now[0] = 6.0
        rec.callback("sort:more", 0.6)
        assert read_run_state(tmp_path).fraction == 0.6

    def test_heartbeat_refreshes_timestamp(self, tmp_path):
        now = [0.0]
        rec = self._recorder(tmp_path, clock=lambda: now[0])
        rec.start()
        now[0] = 30.0
        rec.heartbeat()
        assert read_run_state(tmp_path).heartbeat_at == 30.0

    def test_finish_records_status_and_first_error_line(self, tmp_path):
        rec = self._recorder(tmp_path, clock=lambda: 1.0)
        rec.start()
        rec.finish("failed", "CUDA out of memory\nTraceback ...")
        rs = read_run_state(tmp_path)
        assert rs.status == "failed"
        assert rs.error == "CUDA out of memory"

    def test_finish_rejects_unknown_status(self, tmp_path):
        rec = self._recorder(tmp_path, clock=lambda: 1.0)
        with pytest.raises(ValueError):
            rec.finish("weird")


class TestTaskWindowPending:
    def test_mark_check_clear(self, tmp_path):
        assert not is_task_window_pending(tmp_path)
        mark_task_window_pending(tmp_path)
        assert is_task_window_pending(tmp_path)
        data = json.loads(
            (tmp_path / "checkpoints" / "task_window_pending.json").read_text(encoding="utf-8")
        )
        assert "marked_at" in data
        clear_task_window_pending(tmp_path)
        assert not is_task_window_pending(tmp_path)
