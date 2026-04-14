"""Tests for agent/chat_harness.py — self-check + auto-fix for chat env."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fake openai modules for injection
# ---------------------------------------------------------------------------


class _FakeOpenAIOld:
    """openai package with version below minimum."""

    __version__ = "0.28.0"


class _FakeOpenAINew:
    """openai package with acceptable version."""

    __version__ = "1.50.0"

    class OpenAI:
        def __init__(self, api_key, base_url):
            self.api_key = api_key
            self.base_url = base_url


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "GRAPH_REPORT.md").write_text("graph", encoding="utf-8")
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "best_practices.md").write_text("bp", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def ready_config(tmp_path):
    from pynpxpipe.agent.llm_client import LLMConfig

    cfg = LLMConfig(provider="moonshot")
    cfg.api_keys["moonshot"] = "sk-test"
    return cfg


@pytest.fixture()
def empty_key_config():
    from pynpxpipe.agent.llm_client import LLMConfig

    return LLMConfig(provider="moonshot")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


class TestOpenAIInstalled:
    def test_missing_reports_red(self, ready_config, tmp_project, monkeypatch):
        from pynpxpipe.agent.chat_harness import ChatHarness

        saved = sys.modules.pop("openai", None)
        monkeypatch.setitem(sys.modules, "openai", None)
        try:
            harness = ChatHarness(ready_config, tmp_project)
            report = harness.check_all(do_ping=False)
        finally:
            if saved is not None:
                sys.modules["openai"] = saved

        failed = [r for r in report.results if r.name == "openai_installed"]
        assert len(failed) == 1
        assert failed[0].status == "fail"

    def test_present_reports_pass(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(ready_config, tmp_project, openai_module=_FakeOpenAINew())
        report = harness.check_all(do_ping=False)
        results = {r.name: r for r in report.results}
        assert results["openai_installed"].status == "pass"

    def test_old_version_reports_fail(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(ready_config, tmp_project, openai_module=_FakeOpenAIOld())
        report = harness.check_all(do_ping=False)
        results = {r.name: r for r in report.results}
        assert results["openai_version"].status == "fail"


class TestConfigFileCheck:
    def test_missing_file_creates_default_when_auto_fix(self, ready_config, tmp_project, tmp_path):
        from pynpxpipe.agent.chat_harness import ChatHarness

        cfg_path = tmp_path / "nested" / "llm_config.json"
        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            config_path=cfg_path,
        )
        report = harness.check_all(do_ping=False)
        harness.auto_fix(report)
        assert cfg_path.exists()

    def test_corrupt_config_backed_up_and_reset(self, ready_config, tmp_project, tmp_path):
        from pynpxpipe.agent.chat_harness import ChatHarness

        cfg_path = tmp_path / "llm_config.json"
        cfg_path.write_text("not json{{", encoding="utf-8")

        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            config_path=cfg_path,
        )
        report = harness.check_all(do_ping=False)
        corrupt = [r for r in report.results if r.name == "config_file_readable"]
        assert corrupt and corrupt[0].status == "warn"
        assert corrupt[0].auto_fixable is True

        harness.auto_fix(report)
        # Backup should exist
        backups = list(tmp_path.glob("llm_config.json.bak_*"))
        assert len(backups) == 1
        # Re-read should now succeed
        restored = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert "provider" in restored


class TestApiKeyCheck:
    def test_empty_key_reports_red(self, empty_key_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(empty_key_config, tmp_project, openai_module=_FakeOpenAINew())
        report = harness.check_all(do_ping=False)
        results = {r.name: r for r in report.results}
        assert results["api_key_present"].status == "fail"

    def test_present_key_reports_pass(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(ready_config, tmp_project, openai_module=_FakeOpenAINew())
        report = harness.check_all(do_ping=False)
        results = {r.name: r for r in report.results}
        assert results["api_key_present"].status == "pass"


class TestContextFileChecks:
    def test_missing_graph_report_is_warn_not_fail(self, ready_config, tmp_path):
        from pynpxpipe.agent.chat_harness import ChatHarness

        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "best_practices.md").write_text("bp", encoding="utf-8")

        harness = ChatHarness(ready_config, tmp_path, openai_module=_FakeOpenAINew())
        report = harness.check_all(do_ping=False)
        results = {r.name: r for r in report.results}
        assert results["graph_report_exists"].status == "warn"

    def test_missing_best_practices_is_warn_not_fail(self, ready_config, tmp_path):
        from pynpxpipe.agent.chat_harness import ChatHarness

        (tmp_path / "graphify-out").mkdir()
        (tmp_path / "graphify-out" / "GRAPH_REPORT.md").write_text("g", encoding="utf-8")

        harness = ChatHarness(ready_config, tmp_path, openai_module=_FakeOpenAINew())
        report = harness.check_all(do_ping=False)
        results = {r.name: r for r in report.results}
        assert results["best_practices_exists"].status == "warn"

    def test_both_present_reports_pass(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(ready_config, tmp_project, openai_module=_FakeOpenAINew())
        report = harness.check_all(do_ping=False)
        results = {r.name: r for r in report.results}
        assert results["graph_report_exists"].status == "pass"
        assert results["best_practices_exists"].status == "pass"


class TestBaseUrlCheck:
    def test_unresolvable_reports_fail(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        def failing_lookup(host: str) -> str:
            raise OSError(f"dns failed: {host}")

        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            dns_lookup=failing_lookup,
        )
        report = harness.check_all(do_ping=False)
        results = {r.name: r for r in report.results}
        assert results["provider_base_url_resolvable"].status == "fail"

    def test_resolvable_reports_pass(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            dns_lookup=lambda host: "127.0.0.1",
        )
        report = harness.check_all(do_ping=False)
        results = {r.name: r for r in report.results}
        assert results["provider_base_url_resolvable"].status == "pass"


class TestPingCheck:
    def test_ping_skipped_when_disabled(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            dns_lookup=lambda host: "127.0.0.1",
        )
        report = harness.check_all(do_ping=False)
        names = {r.name for r in report.results}
        assert "ping_round_trip" not in names

    def test_ping_success_reports_pass(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            dns_lookup=lambda host: "127.0.0.1",
            ping_fn=lambda cfg, project_root, openai_module: "pong",
        )
        report = harness.check_all(do_ping=True)
        results = {r.name: r for r in report.results}
        assert results["ping_round_trip"].status == "pass"

    def test_ping_failure_reports_fail(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        def failing_ping(cfg, project_root, openai_module):
            raise RuntimeError("401 invalid api key")

        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            dns_lookup=lambda host: "127.0.0.1",
            ping_fn=failing_ping,
        )
        report = harness.check_all(do_ping=True)
        results = {r.name: r for r in report.results}
        assert results["ping_round_trip"].status == "fail"
        assert "401" in results["ping_round_trip"].message


# ---------------------------------------------------------------------------
# HarnessReport aggregates
# ---------------------------------------------------------------------------


class TestHarnessReport:
    def test_passed_true_when_no_failures(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            dns_lookup=lambda host: "127.0.0.1",
        )
        report = harness.check_all(do_ping=False)
        assert report.passed is True

    def test_passed_false_when_any_red(self, empty_key_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(
            empty_key_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            dns_lookup=lambda host: "127.0.0.1",
        )
        report = harness.check_all(do_ping=False)
        assert report.passed is False

    def test_format_is_multiline_string(self, ready_config, tmp_project):
        from pynpxpipe.agent.chat_harness import ChatHarness

        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            dns_lookup=lambda host: "127.0.0.1",
        )
        report = harness.check_all(do_ping=False)
        text = report.format()
        assert isinstance(text, str)
        assert "\n" in text
        assert "openai_installed" in text

    def test_warnings_and_failures_properties(self, empty_key_config, tmp_path):
        from pynpxpipe.agent.chat_harness import ChatHarness

        # Missing context files → warn; missing api key → fail
        harness = ChatHarness(
            empty_key_config,
            tmp_path,
            openai_module=_FakeOpenAINew(),
            dns_lookup=lambda host: "127.0.0.1",
        )
        report = harness.check_all(do_ping=False)
        assert any(r.status == "warn" for r in report.warnings)
        assert any(r.status == "fail" for r in report.failures)


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------


class TestAutoFix:
    def test_auto_fix_rewrites_corrupt_config_and_clears_warning(
        self, ready_config, tmp_project, tmp_path
    ):
        from pynpxpipe.agent.chat_harness import ChatHarness

        cfg_path = tmp_path / "llm_config.json"
        cfg_path.write_text("garbage{{", encoding="utf-8")

        harness = ChatHarness(
            ready_config,
            tmp_project,
            openai_module=_FakeOpenAINew(),
            config_path=cfg_path,
            dns_lookup=lambda host: "127.0.0.1",
        )
        report = harness.check_all(do_ping=False)
        report_fixed = harness.auto_fix(report)

        names = {r.name: r.status for r in report_fixed.results}
        assert names["config_file_readable"] == "pass"
        assert report_fixed.applied_fixes
