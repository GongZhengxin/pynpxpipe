"""agent/chat_harness.py — Self-check + auto-fix for the chat assistant.

Runs a battery of checks against the current environment (openai version,
config file state, API key presence, context file presence, DNS
resolution, optional live ping) and returns a ``HarnessReport`` that the
UI can display. A subset of failures is auto-fixable (YELLOW tier):
missing / corrupt config files get rewritten with defaults.
"""

from __future__ import annotations

import json
import socket
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pynpxpipe.agent.llm_client import (
    PROVIDERS,
    LLMConfig,
    LLMConfigError,
    _default_config_path,
)

CheckStatus = Literal["pass", "warn", "fail"]
FixTier = Literal["GREEN", "YELLOW", "RED"]

_MIN_OPENAI_VERSION: tuple[int, int] = (1, 0)


@dataclass
class ChatCheckResult:
    name: str
    status: CheckStatus
    message: str
    tier: FixTier | None = None
    auto_fixable: bool = False
    fix_description: str = ""


@dataclass
class HarnessReport:
    results: list[ChatCheckResult] = field(default_factory=list)
    applied_fixes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.status != "fail" for r in self.results)

    @property
    def warnings(self) -> list[ChatCheckResult]:
        return [r for r in self.results if r.status == "warn"]

    @property
    def failures(self) -> list[ChatCheckResult]:
        return [r for r in self.results if r.status == "fail"]

    def format(self) -> str:
        """Render a multi-line human-readable summary."""
        lines: list[str] = []
        for r in self.results:
            icon = {"pass": "OK ", "warn": "WARN", "fail": "FAIL"}[r.status]
            lines.append(f"[{icon}] {r.name}: {r.message}")
            if r.auto_fixable:
                lines.append(f"       → auto-fix: {r.fix_description}")
        if self.applied_fixes:
            lines.append("")
            lines.append("Applied fixes:")
            for fix in self.applied_fixes:
                lines.append(f"  - {fix}")
        return "\n".join(lines)


def _parse_version(version: str) -> tuple[int, int]:
    try:
        parts = version.split(".")
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return 0, 0


class ChatHarness:
    """Environment self-check for the chat assistant."""

    def __init__(
        self,
        config: LLMConfig,
        project_root: Path,
        *,
        openai_module: Any | None = None,
        dns_lookup: Callable[[str], str] | None = None,
        ping_fn: Callable[[LLMConfig, Path, Any], str] | None = None,
        config_path: Path | None = None,
    ) -> None:
        self._config = config
        self._project_root = project_root
        self._openai_module = openai_module
        self._dns_lookup = dns_lookup or socket.gethostbyname
        self._ping_fn = ping_fn or _default_ping
        self._config_path = config_path or _default_config_path()
        self._pending_fixes: list[tuple[str, Callable[[], str]]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_all(self, *, do_ping: bool = False) -> HarnessReport:
        """Run every check and return the aggregated report."""
        self._pending_fixes = []
        report = HarnessReport()

        openai_ok = self._check_openai_installed(report)
        if openai_ok:
            self._check_openai_version(report)
        self._check_config_file_readable(report)
        self._check_api_key_present(report)
        self._check_graph_report_exists(report)
        self._check_best_practices_exists(report)
        self._check_base_url_resolvable(report)
        if do_ping and report.passed:
            self._check_ping(report)

        return report

    def auto_fix(self, report: HarnessReport) -> HarnessReport:
        """Apply all queued YELLOW-tier fixes and re-run ``check_all``."""
        applied: list[str] = []
        for label, fn in self._pending_fixes:
            try:
                detail = fn()
            except Exception as exc:  # noqa: BLE001
                detail = f"fix '{label}' failed: {exc}"
            applied.append(f"{label}: {detail}")
        fresh = self.check_all(do_ping=False)
        fresh.applied_fixes = applied
        return fresh

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_openai_installed(self, report: HarnessReport) -> bool:
        module = self._resolve_openai_module()
        if module is None:
            report.results.append(
                ChatCheckResult(
                    name="openai_installed",
                    status="fail",
                    message="openai package not installed",
                    tier="RED",
                    fix_description='Run: uv pip install -e ".[chat]"',
                )
            )
            return False
        report.results.append(
            ChatCheckResult(
                name="openai_installed",
                status="pass",
                message=f"openai package present (version {getattr(module, '__version__', '?')})",
            )
        )
        self._openai_module = module
        return True

    def _check_openai_version(self, report: HarnessReport) -> None:
        version_str = getattr(self._openai_module, "__version__", "0.0.0")
        major, minor = _parse_version(version_str)
        if (major, minor) >= _MIN_OPENAI_VERSION:
            report.results.append(
                ChatCheckResult(
                    name="openai_version",
                    status="pass",
                    message=f"openai {version_str} >= {_MIN_OPENAI_VERSION[0]}.{_MIN_OPENAI_VERSION[1]} OK",
                )
            )
            return
        report.results.append(
            ChatCheckResult(
                name="openai_version",
                status="fail",
                message=(
                    f"openai {version_str} is too old — need >= "
                    f"{_MIN_OPENAI_VERSION[0]}.{_MIN_OPENAI_VERSION[1]}"
                ),
                tier="RED",
                fix_description='Run: uv pip install -U "openai>=1.0"',
            )
        )

    def _check_config_file_readable(self, report: HarnessReport) -> None:
        path = self._config_path
        if not path.exists():
            report.results.append(
                ChatCheckResult(
                    name="config_file_readable",
                    status="warn",
                    message=f"{path} does not exist; will create on first save",
                    tier="YELLOW",
                    auto_fixable=True,
                    fix_description="Create default config file",
                )
            )
            self._pending_fixes.append(("config_file_readable", self._fix_create_default_config))
            return
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            report.results.append(
                ChatCheckResult(
                    name="config_file_readable",
                    status="warn",
                    message=f"{path} is corrupt: {exc}",
                    tier="YELLOW",
                    auto_fixable=True,
                    fix_description="Back up and reset to defaults",
                )
            )
            self._pending_fixes.append(("config_file_readable", self._fix_reset_corrupt_config))
            return
        report.results.append(
            ChatCheckResult(
                name="config_file_readable",
                status="pass",
                message=f"{path} readable",
            )
        )

    def _check_api_key_present(self, report: HarnessReport) -> None:
        try:
            self._config.current_api_key()
        except LLMConfigError as exc:
            report.results.append(
                ChatCheckResult(
                    name="api_key_present",
                    status="fail",
                    message=str(exc),
                    tier="RED",
                    fix_description=(
                        "Open Help → enter API Key for provider "
                        f"'{self._config.provider}' → Save Config"
                    ),
                )
            )
            return
        report.results.append(
            ChatCheckResult(
                name="api_key_present",
                status="pass",
                message=f"API key set for provider '{self._config.provider}'",
            )
        )

    def _check_graph_report_exists(self, report: HarnessReport) -> None:
        path = self._project_root / "graphify-out" / "GRAPH_REPORT.md"
        if path.exists():
            report.results.append(
                ChatCheckResult(
                    name="graph_report_exists",
                    status="pass",
                    message=f"{path.name} present",
                )
            )
        else:
            report.results.append(
                ChatCheckResult(
                    name="graph_report_exists",
                    status="warn",
                    message=(
                        "GRAPH_REPORT.md missing — chat will work but lacks "
                        "project knowledge graph context"
                    ),
                    tier="YELLOW",
                    fix_description="Run `graphify` to regenerate the knowledge graph",
                )
            )

    def _check_best_practices_exists(self, report: HarnessReport) -> None:
        path = self._project_root / "docs" / "specs" / "best_practices.md"
        if path.exists():
            report.results.append(
                ChatCheckResult(
                    name="best_practices_exists",
                    status="pass",
                    message=f"{path.name} present",
                )
            )
        else:
            report.results.append(
                ChatCheckResult(
                    name="best_practices_exists",
                    status="warn",
                    message="best_practices.md missing — chat will lack user guide context",
                    tier="YELLOW",
                    fix_description="Create docs/specs/best_practices.md",
                )
            )

    def _check_base_url_resolvable(self, report: HarnessReport) -> None:
        provider = self._config.provider
        if provider not in PROVIDERS:
            report.results.append(
                ChatCheckResult(
                    name="provider_base_url_resolvable",
                    status="fail",
                    message=f"Unknown provider '{provider}'",
                    tier="RED",
                    fix_description=(f"Choose one of: {', '.join(sorted(PROVIDERS.keys()))}"),
                )
            )
            return
        base_url = PROVIDERS[provider].base_url
        host = urlparse(base_url).hostname
        if host is None:
            report.results.append(
                ChatCheckResult(
                    name="provider_base_url_resolvable",
                    status="fail",
                    message=f"Cannot parse hostname from {base_url}",
                    tier="RED",
                )
            )
            return
        try:
            self._dns_lookup(host)
        except OSError as exc:
            report.results.append(
                ChatCheckResult(
                    name="provider_base_url_resolvable",
                    status="fail",
                    message=f"DNS lookup failed for {host}: {exc}",
                    tier="RED",
                    fix_description="Check network / firewall / proxy settings",
                )
            )
            return
        report.results.append(
            ChatCheckResult(
                name="provider_base_url_resolvable",
                status="pass",
                message=f"{host} resolvable",
            )
        )

    def _check_ping(self, report: HarnessReport) -> None:
        try:
            reply = self._ping_fn(self._config, self._project_root, self._openai_module)
        except Exception as exc:  # noqa: BLE001
            report.results.append(
                ChatCheckResult(
                    name="ping_round_trip",
                    status="fail",
                    message=f"live ping failed: {exc}",
                    tier="RED",
                    fix_description="Verify API key, model name, and network",
                )
            )
            return
        report.results.append(
            ChatCheckResult(
                name="ping_round_trip",
                status="pass",
                message=f"live ping succeeded ({len(reply)} chars)",
            )
        )

    # ------------------------------------------------------------------
    # openai module resolution
    # ------------------------------------------------------------------

    def _resolve_openai_module(self) -> Any | None:
        if self._openai_module is not None:
            return self._openai_module
        cached = sys.modules.get("openai", "__unset__")
        if cached == "__unset__":
            try:
                import openai as _openai  # noqa: PLC0415
            except ImportError:
                return None
            return _openai
        return cached  # could be None if test stubbed it that way

    # ------------------------------------------------------------------
    # Auto-fix implementations
    # ------------------------------------------------------------------

    def _fix_create_default_config(self) -> str:
        LLMConfig().save(self._config_path)
        return f"created default config at {self._config_path}"

    def _fix_reset_corrupt_config(self) -> str:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = self._config_path.with_name(f"{self._config_path.name}.bak_{timestamp}")
        backup.write_bytes(self._config_path.read_bytes())
        LLMConfig().save(self._config_path)
        return f"backed up corrupt file to {backup.name} and reset to defaults"


# ---------------------------------------------------------------------------
# Default ping implementation
# ---------------------------------------------------------------------------


def _default_ping(config: LLMConfig, project_root: Path, openai_module: Any) -> str:
    """Send a minimal round-trip request and return the reply text."""
    from pynpxpipe.agent.llm_client import LLMClient  # noqa: PLC0415

    client = LLMClient(config, project_root, openai_module=openai_module)
    chunks = list(client.chat("ping", stream=False))
    return "".join(chunks)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    """Run `python -m pynpxpipe.agent.chat_harness` and print a report."""
    config = LLMConfig.load()
    project_root = Path(__file__).resolve().parents[3]
    harness = ChatHarness(config, project_root)
    report = harness.check_all(do_ping=False)
    print(report.format())
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
