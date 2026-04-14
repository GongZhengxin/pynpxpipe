"""agent/llm_client.py — Multi-backend OpenAI-compatible LLM client.

Supports six providers (moonshot, dmxapi, openai, anthropic, siliconflow,
deepseek) through the OpenAI SDK. API keys + defaults persist to
``~/.pynpxpipe/llm_config.json``. System prompt is assembled from a hardcoded
role card plus ``graphify-out/GRAPH_REPORT.md`` and
``docs/specs/best_practices.md`` if they exist.

The ``openai`` package is an optional dependency (installed via the ``[chat]``
extra). Import failure surfaces as ``LLMNotAvailable``. Tests inject a fake
``openai`` module via the ``openai_module`` constructor argument.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LLMNotAvailable(Exception):
    """Raised when the optional ``openai`` package is not installed."""


class LLMConfigError(Exception):
    """Raised when LLM configuration is missing or malformed."""


# ---------------------------------------------------------------------------
# Provider presets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str
    default_model: str


PROVIDERS: dict[str, ProviderPreset] = {
    "moonshot": ProviderPreset(
        base_url="https://api.moonshot.cn/v1",
        default_model="kimi-k2-0711-preview",
    ),
    "dmxapi": ProviderPreset(
        base_url="https://www.dmxapi.cn/v1",
        default_model="gpt-4o",
    ),
    "openai": ProviderPreset(
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o",
    ),
    "anthropic": ProviderPreset(
        base_url="https://api.anthropic.com/v1",
        default_model="claude-opus-4-6",
    ),
    "siliconflow": ProviderPreset(
        base_url="https://api.siliconflow.cn/v1",
        default_model="deepseek-ai/DeepSeek-V3",
    ),
    "deepseek": ProviderPreset(
        base_url="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
    ),
}


# ---------------------------------------------------------------------------
# LLMConfig
# ---------------------------------------------------------------------------


def _default_api_keys() -> dict[str, str]:
    return dict.fromkeys(PROVIDERS, "")


def _default_config_path() -> Path:
    return Path.home() / ".pynpxpipe" / "llm_config.json"


@dataclass
class LLMConfig:
    """User-facing configuration for the LLM chat backend.

    Persisted as JSON to ``~/.pynpxpipe/llm_config.json`` by default.
    """

    provider: str = "moonshot"
    model: str = ""
    api_keys: dict[str, str] = field(default_factory=_default_api_keys)
    temperature: float = 0.3
    max_tokens: int = 2048

    @classmethod
    def load(cls, path: Path | None = None) -> LLMConfig:
        """Load from *path* (default ``~/.pynpxpipe/llm_config.json``).

        Missing file → return defaults. Corrupt JSON → raise
        ``LLMConfigError``. Unknown ``api_keys`` entries are silently dropped.
        """
        path = path or _default_config_path()
        if not path.exists():
            return cls()

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise LLMConfigError(
                f"Failed to parse {path}: {exc}. Delete the file to reset."
            ) from exc

        if not isinstance(raw, dict):
            raise LLMConfigError(f"{path} must be a JSON object, got {type(raw).__name__}")

        cfg = cls()
        if "provider" in raw and isinstance(raw["provider"], str):
            cfg.provider = raw["provider"]
        if "model" in raw and isinstance(raw["model"], str):
            cfg.model = raw["model"]
        if "temperature" in raw and isinstance(raw["temperature"], int | float):
            cfg.temperature = float(raw["temperature"])
        if "max_tokens" in raw and isinstance(raw["max_tokens"], int):
            cfg.max_tokens = raw["max_tokens"]
        if "api_keys" in raw and isinstance(raw["api_keys"], dict):
            for name in PROVIDERS:
                val = raw["api_keys"].get(name, "")
                cfg.api_keys[name] = val if isinstance(val, str) else ""
        return cfg

    def save(self, path: Path | None = None) -> None:
        """Write this config to *path* as pretty-printed JSON."""
        path = path or _default_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "provider": self.provider,
                    "model": self.model,
                    "api_keys": dict(self.api_keys),
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def current_api_key(self) -> str:
        """Return the API key for the current provider, or raise if empty."""
        key = self.api_keys.get(self.provider, "")
        if not key:
            raise LLMConfigError(
                f"API key not set for provider '{self.provider}'. "
                f"Open Help → Save Config after entering your key."
            )
        return key

    def current_model(self) -> str:
        """Return ``self.model`` or fall back to the provider's default."""
        if self.model:
            return self.model
        if self.provider not in PROVIDERS:
            raise LLMConfigError(f"Unknown provider '{self.provider}'")
        return PROVIDERS[self.provider].default_model


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------


_ROLE_CARD = (
    "You are the pynpxpipe assistant AI. pynpxpipe is a Neuropixels "
    "electrophysiology preprocessing pipeline (SpikeGLX multi-probe → NWB). "
    "Answer questions about pipeline usage, configuration, and error "
    "diagnosis. Refer to real module names and config fields from the "
    "project knowledge graph and best-practices sections below. If you are "
    "not sure about something, say so explicitly — never fabricate APIs, "
    "paths, or field names. Prefer short, concrete answers."
)


class LLMClient:
    """OpenAI-compatible chat client for pynpxpipe's help assistant.

    Args:
        config: Current ``LLMConfig`` (provider, model, key, sampling).
        project_root: Repository root for loading GRAPH_REPORT.md and
            best_practices.md. Typically ``Path(__file__).parents[3]``.
        openai_module: Injected ``openai`` module for testing. When
            ``None`` the real package is imported on construction.
    """

    def __init__(
        self,
        config: LLMConfig,
        project_root: Path,
        *,
        openai_module: Any | None = None,
    ) -> None:
        self._config = config
        self._project_root = project_root

        if openai_module is None:
            openai_module = sys.modules.get("openai", "__unset__")
            if openai_module == "__unset__":
                try:
                    import openai as _openai  # noqa: PLC0415
                except ImportError as exc:
                    raise LLMNotAvailable(
                        'openai package not installed. Run: uv pip install -e ".[chat]"'
                    ) from exc
                openai_module = _openai
            elif openai_module is None:
                raise LLMNotAvailable(
                    'openai package not installed. Run: uv pip install -e ".[chat]"'
                )
        self._openai = openai_module

    # ------------------------------------------------------------------
    # System prompt assembly
    # ------------------------------------------------------------------

    def build_system_prompt(self, extra: str | None = None) -> str:
        """Assemble the system prompt from role card + static context docs."""
        parts: list[str] = [_ROLE_CARD]

        graph_path = self._project_root / "graphify-out" / "GRAPH_REPORT.md"
        if graph_path.exists():
            parts.append("\n## Project Knowledge Graph\n" + graph_path.read_text(encoding="utf-8"))

        bp_path = self._project_root / "docs" / "specs" / "best_practices.md"
        if bp_path.exists():
            parts.append("\n## Best Practices\n" + bp_path.read_text(encoding="utf-8"))

        if extra:
            parts.append("\n## Current UI Configuration\n" + extra)

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        stream: bool = True,
        extra_context: str | None = None,
    ) -> Iterator[str]:
        """Send a chat request and yield text chunks.

        Args:
            user_message: Latest user input.
            history: Prior messages in the form ``[{"role", "content"}, ...]``.
            stream: If True, yield incremental chunks; otherwise yield the
                full reply in a single element.
            extra_context: Optional dynamic context appended to the system
                prompt (e.g. dumped UI configuration).
        """
        api_key = self._config.current_api_key()
        model = self._config.current_model()
        provider = self._config.provider
        if provider not in PROVIDERS:
            raise LLMConfigError(f"Unknown provider '{provider}'")
        base_url = PROVIDERS[provider].base_url

        client = self._openai.OpenAI(api_key=api_key, base_url=base_url)

        system = self.build_system_prompt(extra=extra_context)
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=stream,
            temperature=self._config.temperature,
            max_tokens=self._config.max_tokens,
        )

        if stream:
            for chunk in response:
                delta = chunk.choices[0].delta
                text = getattr(delta, "content", None) or ""
                if text:
                    yield text
        else:
            yield response.choices[0].message.content or ""
