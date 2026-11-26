"""Tests for ui/run_manager.py and ui/settings.py (ui_redesign.md §8.2, §8.9)."""

from __future__ import annotations

import threading
import time

import pytest

from pynpxpipe.pipelines.run_state import read_run_state
from pynpxpipe.ui.run_manager import RunInterrupted, RunManager
from pynpxpipe.ui.settings import UISettings, load_ui_settings


def _manager(heartbeat_s: float = 5.0) -> RunManager:
    return RunManager(UISettings(heartbeat_s=heartbeat_s))


class TestRunManager:
    def test_runs_target_in_background_and_records_completion(self, tmp_path):
        seen = []

        def target(callback, interrupt):
            seen.append(threading.get_ident())
            callback("discover:Scanning", 0.0)
            callback("discover:Done", 1.0)

        handle = _manager().start(tmp_path, target, ["discover"])
        handle.thread.join(timeout=5)
        assert seen and seen[0] != threading.get_ident()
        rs = read_run_state(tmp_path)
        assert rs.status == "completed"
        assert rs.current_stage == "discover"

    def test_duplicate_start_for_same_directory_is_refused(self, tmp_path):
        release = threading.Event()
        manager = _manager()
        handle = manager.start(tmp_path, lambda cb, ev: release.wait(5), ["sort"])
        assert manager.is_running(tmp_path)
        assert manager.start(tmp_path, lambda cb, ev: None, ["sort"]) is None
        release.set()
        handle.thread.join(timeout=5)
        assert not manager.is_running(tmp_path)

    def test_failure_records_failed_status(self, tmp_path):
        def target(callback, interrupt):
            raise RuntimeError("CUDA out of memory\ndetails")

        handle = _manager().start(tmp_path, target, ["sort"])
        handle.thread.join(timeout=5)
        rs = read_run_state(tmp_path)
        assert rs.status == "failed"
        assert rs.error == "CUDA out of memory"
        assert isinstance(handle.error, RuntimeError)

    def test_stop_takes_effect_when_next_stage_starts(self, tmp_path):
        started, finished = threading.Event(), []

        def target(callback, interrupt):
            callback("preprocess:working", 0.5)
            started.set()
            interrupt.wait(5)
            callback("preprocess:done", 1.0)  # current stage may finish
            finished.append("preprocess")
            callback("sort:Starting", 0.0)  # raises RunInterrupted
            finished.append("sort")

        manager = _manager()
        handle = manager.start(tmp_path, target, ["preprocess", "sort"])
        started.wait(5)
        assert manager.stop(tmp_path) is True
        handle.thread.join(timeout=5)
        assert finished == ["preprocess"]
        assert isinstance(handle.error, RunInterrupted)
        assert read_run_state(tmp_path).status == "stopped"

    def test_heartbeat_thread_keeps_long_stage_alive(self, tmp_path):
        release = threading.Event()
        handle = _manager(heartbeat_s=0.05).start(
            tmp_path, lambda cb, ev: release.wait(5), ["sort"]
        )
        first = read_run_state(tmp_path).heartbeat_at
        time.sleep(0.3)
        assert read_run_state(tmp_path).heartbeat_at > first
        release.set()
        handle.thread.join(timeout=5)

    def test_custom_final_status_for_preview_runs(self, tmp_path):
        handle = _manager().start(
            tmp_path, lambda cb, ev: None, ["select_segments"], final_status="awaiting_confirmation"
        )
        handle.thread.join(timeout=5)
        assert read_run_state(tmp_path).status == "awaiting_confirmation"

    def test_shared_instance_is_process_wide(self):
        from pynpxpipe.ui.run_manager import get_run_manager

        assert get_run_manager() is get_run_manager()


class TestUISettings:
    def test_defaults_when_file_missing(self, tmp_path):
        s = load_ui_settings(tmp_path / "ui.yaml")
        assert s == UISettings()
        assert (s.heartbeat_s, s.heartbeat_timeout_s, s.poll_s) == (5.0, 60.0, 2.0)
        assert (s.recent_sessions_max, s.eta_min_samples, s.min_batch_size) == (20, 3, 10000)

    def test_reads_yaml_overrides(self, tmp_path):
        path = tmp_path / "ui.yaml"
        path.write_text("ui:\n  poll_s: 1.5\n  recent_sessions_max: 5\n", encoding="utf-8")
        s = load_ui_settings(path)
        assert s.poll_s == 1.5 and s.recent_sessions_max == 5
        assert s.heartbeat_s == 5.0

    def test_rejects_non_positive_values(self, tmp_path):
        from pynpxpipe.core.errors import ConfigError

        path = tmp_path / "ui.yaml"
        path.write_text("ui:\n  heartbeat_s: 0\n", encoding="utf-8")
        with pytest.raises(ConfigError):
            load_ui_settings(path)

    def test_repository_ui_yaml_matches_defaults(self):
        from pathlib import Path

        repo_yaml = Path(__file__).resolve().parents[2] / "config" / "ui.yaml"
        assert load_ui_settings(repo_yaml) == UISettings()
