"""Tests for agent/llm_client.py — multi-backend LLM client.

Covers the LLMConfig dataclass (pure file I/O) and the LLMClient class
(openai SDK injection-based, no network).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Provider presets
# ---------------------------------------------------------------------------


class TestProviderPresets:
    def test_all_six_providers_registered(self):
        from pynpxpipe.agent.llm_client import PROVIDERS

        expected = {"moonshot", "dmxapi", "openai", "anthropic", "siliconflow", "deepseek"}
        assert set(PROVIDERS.keys()) == expected

    def test_each_preset_has_base_url_and_default_model(self):
        from pynpxpipe.agent.llm_client import PROVIDERS

        for name, preset in PROVIDERS.items():
            assert preset.base_url.startswith("https://"), name
            assert preset.default_model, name


# ---------------------------------------------------------------------------
# LLMConfig — file I/O and field defaults
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_default_instantiation(self):
        from pynpxpipe.agent.llm_client import LLMConfig

        cfg = LLMConfig()
        assert cfg.provider == "moonshot"
        assert cfg.model == ""
        assert cfg.temperature == 0.3
        assert cfg.max_tokens == 2048
        assert set(cfg.api_keys.keys()) >= {
            "moonshot",
            "dmxapi",
            "openai",
            "anthropic",
            "siliconflow",
            "deepseek",
        }
        for v in cfg.api_keys.values():
            assert v == ""

    def test_load_missing_file_returns_default(self, tmp_path):
        from pynpxpipe.agent.llm_client import LLMConfig

        cfg = LLMConfig.load(tmp_path / "does_not_exist.json")
        assert cfg.provider == "moonshot"

    def test_load_corrupt_json_raises(self, tmp_path):
        from pynpxpipe.agent.llm_client import LLMConfig, LLMConfigError

        p = tmp_path / "llm_config.json"
        p.write_text("not json at all{", encoding="utf-8")
        with pytest.raises(LLMConfigError):
            LLMConfig.load(p)

    def test_save_creates_parent_dir(self, tmp_path):
        from pynpxpipe.agent.llm_client import LLMConfig

        cfg = LLMConfig(provider="deepseek")
        target = tmp_path / "nested" / "deep" / "llm_config.json"
        cfg.save(target)
        assert target.exists()

    def test_save_load_roundtrip(self, tmp_path):
        from pynpxpipe.agent.llm_client import LLMConfig

        p = tmp_path / "cfg.json"
        cfg = LLMConfig(provider="openai", model="gpt-4o", temperature=0.7)
        cfg.api_keys["openai"] = "sk-test"
        cfg.save(p)

        restored = LLMConfig.load(p)
        assert restored.provider == "openai"
        assert restored.model == "gpt-4o"
        assert restored.temperature == 0.7
        assert restored.api_keys["openai"] == "sk-test"

    def test_load_partial_file_fills_defaults(self, tmp_path):
        from pynpxpipe.agent.llm_client import LLMConfig

        p = tmp_path / "cfg.json"
        p.write_text(json.dumps({"provider": "openai"}), encoding="utf-8")
        cfg = LLMConfig.load(p)
        assert cfg.provider == "openai"
        assert cfg.temperature == 0.3  # default

    def test_load_unknown_provider_key_ignored(self, tmp_path):
        from pynpxpipe.agent.llm_client import LLMConfig

        p = tmp_path / "cfg.json"
        p.write_text(
            json.dumps({"api_keys": {"moonshot": "sk-x", "bogus_provider": "sk-y"}}),
            encoding="utf-8",
        )
        cfg = LLMConfig.load(p)
        assert cfg.api_keys["moonshot"] == "sk-x"
        assert "bogus_provider" not in cfg.api_keys

    def test_current_api_key_empty_raises(self):
        from pynpxpipe.agent.llm_client import LLMConfig, LLMConfigError

        cfg = LLMConfig(provider="moonshot")
        with pytest.raises(LLMConfigError):
            cfg.current_api_key()

    def test_current_api_key_returns_value(self):
        from pynpxpipe.agent.llm_client import LLMConfig

        cfg = LLMConfig(provider="moonshot")
        cfg.api_keys["moonshot"] = "sk-abc"
        assert cfg.current_api_key() == "sk-abc"

    def test_current_model_falls_back_to_preset(self):
        from pynpxpipe.agent.llm_client import PROVIDERS, LLMConfig

        cfg = LLMConfig(provider="deepseek", model="")
        assert cfg.current_model() == PROVIDERS["deepseek"].default_model

    def test_current_model_uses_override(self):
        from pynpxpipe.agent.llm_client import LLMConfig

        cfg = LLMConfig(provider="openai", model="gpt-4o-mini")
        assert cfg.current_model() == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# LLMClient — with injected openai module
# ---------------------------------------------------------------------------


class _FakeStreamChunk:
    def __init__(self, text: str) -> None:
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=text))]


class _FakeCompletions:
    def __init__(self, stream_text: list[str], non_stream_text: str = "full reply") -> None:
        self._stream_text = stream_text
        self._non_stream_text = non_stream_text
        self.last_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        if kwargs.get("stream"):
            return iter(_FakeStreamChunk(t) for t in self._stream_text)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._non_stream_text))]
        )


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.chat = _FakeChat(_FakeCompletions(stream_text=["hello ", "world"]))


class _FakeOpenAIModule:
    __version__ = "1.50.0"
    last_instance: _FakeOpenAIClient | None = None

    def OpenAI(self, api_key: str, base_url: str) -> _FakeOpenAIClient:  # noqa: N802
        inst = _FakeOpenAIClient(api_key=api_key, base_url=base_url)
        _FakeOpenAIModule.last_instance = inst
        return inst


@pytest.fixture()
def fake_openai():
    return _FakeOpenAIModule()


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    """A fake project_root with graphify-out and docs/specs."""
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "GRAPH_REPORT.md").write_text(
        "# Graph\nGod nodes: Session, ConfigError", encoding="utf-8"
    )
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "best_practices.md").write_text(
        "# Best Practices\nDREDge and nblocks are mutually exclusive.", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture()
def ready_config():
    from pynpxpipe.agent.llm_client import LLMConfig

    cfg = LLMConfig(provider="moonshot")
    cfg.api_keys["moonshot"] = "sk-unit-test"
    return cfg


class TestLLMClientConstruction:
    def test_init_raises_if_openai_missing(self, ready_config, tmp_project, monkeypatch):
        # Force the internal import to fail.
        import sys

        from pynpxpipe.agent.llm_client import LLMClient, LLMNotAvailable

        saved = sys.modules.pop("openai", None)
        monkeypatch.setitem(sys.modules, "openai", None)
        try:
            with pytest.raises(LLMNotAvailable):
                LLMClient(ready_config, tmp_project)
        finally:
            if saved is not None:
                sys.modules["openai"] = saved

    def test_init_accepts_injected_module(self, ready_config, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        client = LLMClient(ready_config, tmp_project, openai_module=fake_openai)
        assert client is not None


class TestBuildSystemPrompt:
    def test_includes_role_card(self, ready_config, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        client = LLMClient(ready_config, tmp_project, openai_module=fake_openai)
        prompt = client.build_system_prompt()
        assert "pynpxpipe" in prompt.lower()

    def test_includes_graph_report_when_exists(self, ready_config, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        client = LLMClient(ready_config, tmp_project, openai_module=fake_openai)
        prompt = client.build_system_prompt()
        assert "God nodes: Session" in prompt

    def test_skips_missing_graph_report(self, ready_config, tmp_path, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        (tmp_path / "docs" / "specs").mkdir(parents=True)
        (tmp_path / "docs" / "specs" / "best_practices.md").write_text("bp", encoding="utf-8")

        client = LLMClient(ready_config, tmp_path, openai_module=fake_openai)
        prompt = client.build_system_prompt()
        assert "God nodes" not in prompt
        assert "bp" in prompt

    def test_includes_best_practices_when_exists(self, ready_config, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        client = LLMClient(ready_config, tmp_project, openai_module=fake_openai)
        prompt = client.build_system_prompt()
        assert "DREDge and nblocks are mutually exclusive" in prompt

    def test_skips_missing_best_practices(self, ready_config, tmp_path, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        (tmp_path / "graphify-out").mkdir()
        (tmp_path / "graphify-out" / "GRAPH_REPORT.md").write_text("g", encoding="utf-8")

        client = LLMClient(ready_config, tmp_path, openai_module=fake_openai)
        prompt = client.build_system_prompt()
        assert "DREDge" not in prompt

    def test_appends_extra(self, ready_config, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        client = LLMClient(ready_config, tmp_project, openai_module=fake_openai)
        prompt = client.build_system_prompt(extra="## EXTRA BLOCK\nfoo")
        assert "EXTRA BLOCK" in prompt
        assert "foo" in prompt


class TestLLMClientChat:
    def test_chat_streams_chunks(self, ready_config, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        client = LLMClient(ready_config, tmp_project, openai_module=fake_openai)
        chunks = list(client.chat("hi", stream=True))
        assert "".join(chunks) == "hello world"

    def test_chat_non_streaming_yields_single_chunk(self, ready_config, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        client = LLMClient(ready_config, tmp_project, openai_module=fake_openai)
        chunks = list(client.chat("hi", stream=False))
        assert chunks == ["full reply"]

    def test_chat_raises_if_api_key_empty(self, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient, LLMConfig, LLMConfigError

        cfg = LLMConfig(provider="openai")  # empty key
        client = LLMClient(cfg, tmp_project, openai_module=fake_openai)
        with pytest.raises(LLMConfigError):
            list(client.chat("hi"))

    def test_chat_passes_messages_and_history(self, ready_config, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient

        client = LLMClient(ready_config, tmp_project, openai_module=fake_openai)
        history = [
            {"role": "user", "content": "earlier Q"},
            {"role": "assistant", "content": "earlier A"},
        ]
        list(client.chat("latest Q", history=history, stream=True))

        sent_messages = _FakeOpenAIModule.last_instance.chat.completions.last_kwargs["messages"]
        # system + 2 history + latest user = 4
        assert len(sent_messages) == 4
        assert sent_messages[0]["role"] == "system"
        assert sent_messages[1] == history[0]
        assert sent_messages[2] == history[1]
        assert sent_messages[3]["role"] == "user"
        assert sent_messages[3]["content"] == "latest Q"

    def test_chat_uses_provider_base_url(self, ready_config, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import PROVIDERS, LLMClient

        client = LLMClient(ready_config, tmp_project, openai_module=fake_openai)
        list(client.chat("hi"))
        assert _FakeOpenAIModule.last_instance.base_url == PROVIDERS["moonshot"].base_url

    def test_chat_uses_current_model(self, tmp_project, fake_openai):
        from pynpxpipe.agent.llm_client import LLMClient, LLMConfig

        cfg = LLMConfig(provider="moonshot", model="custom-model")
        cfg.api_keys["moonshot"] = "sk-x"
        client = LLMClient(cfg, tmp_project, openai_module=fake_openai)
        list(client.chat("hi"))

        assert (
            _FakeOpenAIModule.last_instance.chat.completions.last_kwargs["model"] == "custom-model"
        )
