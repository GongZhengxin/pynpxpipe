"""Tests for ui/components/chat_help.py — LLM chat assistant UI."""

from __future__ import annotations

from pathlib import Path

import panel as pn
import pytest

from pynpxpipe.ui.state import AppState

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeLLMClient:
    """Fake LLMClient returning a canned stream."""

    def __init__(self, config, project_root, openai_module=None) -> None:
        self.config = config
        self.project_root = project_root
        self.last_call: dict | None = None

    def chat(self, user_message, history=None, stream=True, extra_context=None):
        self.last_call = {
            "user_message": user_message,
            "history": list(history or []),
            "stream": stream,
            "extra_context": extra_context,
        }
        yield "fake "
        yield "reply"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def state():
    return AppState()


@pytest.fixture()
def tmp_project(tmp_path: Path) -> Path:
    (tmp_path / "graphify-out").mkdir()
    (tmp_path / "graphify-out" / "GRAPH_REPORT.md").write_text("g", encoding="utf-8")
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / "docs" / "specs" / "best_practices.md").write_text("bp", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def chat_factory(tmp_path):
    """Return a factory that builds ChatHelp with a fake client."""

    def _build(state, tmp_project, config_path=None):
        from pynpxpipe.agent.llm_client import LLMConfig
        from pynpxpipe.ui.components.chat_help import ChatHelp

        cfg_path = config_path or (tmp_path / "llm_config.json")
        base_cfg = LLMConfig(provider="moonshot")
        base_cfg.api_keys["moonshot"] = "sk-test"
        base_cfg.save(cfg_path)

        return ChatHelp(
            state,
            project_root=tmp_project,
            config_path=cfg_path,
            llm_client_factory=lambda cfg, pr: _FakeLLMClient(cfg, pr),
            harness_factory=lambda cfg, pr: _make_passing_harness(cfg, pr),
        )

    return _build


def _make_passing_harness(cfg, project_root):
    """Return a harness instance that always reports pass."""
    from pynpxpipe.agent.chat_harness import ChatHarness

    return ChatHarness(
        cfg,
        project_root,
        openai_module=_FakeOpenAIOK(),
        dns_lookup=lambda host: "127.0.0.1",
    )


class _FakeOpenAIOK:
    __version__ = "1.50.0"


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestChatHelpConstruction:
    def test_creates_panel_layout(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        layout = chat.panel()
        assert isinstance(layout, pn.viewable.Viewable)

    def test_provider_select_has_six_options(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        assert len(chat.provider_select.options) == 6

    def test_widgets_reflect_loaded_config(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        assert chat.provider_select.value == "moonshot"
        assert chat.api_key_input.value == "sk-test"


# ---------------------------------------------------------------------------
# Save / Refresh / Import
# ---------------------------------------------------------------------------


class TestSaveConfig:
    def test_save_writes_file(self, state, tmp_project, chat_factory, tmp_path):
        cfg_path = tmp_path / "cfg.json"
        chat = chat_factory(state, tmp_project, config_path=cfg_path)
        chat.provider_select.value = "deepseek"
        chat.api_key_input.value = "sk-ds"
        chat._on_save_config(None)

        import json

        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert data["provider"] == "deepseek"
        assert data["api_keys"]["deepseek"] == "sk-ds"

    def test_save_resets_client(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        chat._client = object()  # pretend a client exists
        chat._on_save_config(None)
        assert chat._client is None


class TestRefreshContext:
    def test_refresh_resets_client(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        chat._client = object()
        chat._on_refresh_context(None)
        assert chat._client is None


class TestImportUIConfig:
    def test_import_with_no_pipeline_config_shows_message(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        chat._on_import_ui_config(None)
        assert "no pipeline" in chat.message_pane.object.lower()

    def test_import_sets_extra_context(self, state, tmp_project, chat_factory):
        from pynpxpipe.core.config import PipelineConfig, SortingConfig

        state.pipeline_config = PipelineConfig()
        state.sorting_config = SortingConfig()
        chat = chat_factory(state, tmp_project)
        chat._on_import_ui_config(None)
        assert chat._extra_context is not None
        assert "pipeline.yaml" in chat._extra_context


# ---------------------------------------------------------------------------
# Provider switching
# ---------------------------------------------------------------------------


class TestProviderSwitch:
    def test_switching_provider_updates_api_key_field(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        chat._config.api_keys["deepseek"] = "sk-ds-key"
        chat.provider_select.value = "deepseek"
        assert chat.api_key_input.value == "sk-ds-key"


# ---------------------------------------------------------------------------
# Chat callback
# ---------------------------------------------------------------------------


class TestChatCallback:
    def test_lazy_instantiates_client(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        assert chat._client is None

        result = chat._on_user_message("hi", user="User", instance=None)
        _ = list(result)  # drain the generator
        assert chat._client is not None

    def test_returns_iterator(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        result = chat._on_user_message("hi", user="User", instance=None)
        chunks = list(result)
        assert chunks == ["fake ", "reply"]

    def test_passes_extra_context_after_import(self, state, tmp_project, chat_factory):
        from pynpxpipe.core.config import PipelineConfig, SortingConfig

        state.pipeline_config = PipelineConfig()
        state.sorting_config = SortingConfig()
        chat = chat_factory(state, tmp_project)
        chat._on_import_ui_config(None)

        result = chat._on_user_message("hi", user="User", instance=None)
        list(result)
        assert chat._client.last_call["extra_context"] is not None
        assert "pipeline.yaml" in chat._client.last_call["extra_context"]

    def test_handles_llm_not_available(self, state, tmp_project, tmp_path):
        from pynpxpipe.agent.llm_client import LLMConfig, LLMNotAvailable
        from pynpxpipe.ui.components.chat_help import ChatHelp

        def raising_factory(cfg, pr):
            raise LLMNotAvailable("openai missing")

        cfg_path = tmp_path / "cfg.json"
        LLMConfig(provider="moonshot").save(cfg_path)

        chat = ChatHelp(
            state,
            project_root=tmp_project,
            config_path=cfg_path,
            llm_client_factory=raising_factory,
            harness_factory=_make_passing_harness,
        )
        result = chat._on_user_message("hi", user="User", instance=None)
        chunks = list(result)
        assert any("openai" in c.lower() for c in chunks)

    def test_handles_llm_config_error(self, state, tmp_project, tmp_path):
        from pynpxpipe.agent.llm_client import LLMConfig, LLMConfigError
        from pynpxpipe.ui.components.chat_help import ChatHelp

        class _ErrClient:
            def __init__(self, *args, **kw):
                pass

            def chat(self, *args, **kw):
                raise LLMConfigError("API key not set")
                yield  # make it a generator

        cfg_path = tmp_path / "cfg.json"
        LLMConfig(provider="moonshot").save(cfg_path)

        chat = ChatHelp(
            state,
            project_root=tmp_project,
            config_path=cfg_path,
            llm_client_factory=lambda cfg, pr: _ErrClient(),
            harness_factory=_make_passing_harness,
        )
        result = chat._on_user_message("hi", user="User", instance=None)
        chunks = list(result)
        assert any("api key" in c.lower() for c in chunks)


# ---------------------------------------------------------------------------
# Harness integration
# ---------------------------------------------------------------------------


class TestHarnessIntegration:
    def test_startup_runs_harness(self, state, tmp_project, chat_factory):
        chat = chat_factory(state, tmp_project)
        assert chat.harness_alert.object != ""

    def test_verify_button_runs_live_ping(self, state, tmp_project, tmp_path):
        from pynpxpipe.agent.chat_harness import ChatHarness
        from pynpxpipe.agent.llm_client import LLMConfig
        from pynpxpipe.ui.components.chat_help import ChatHelp

        cfg_path = tmp_path / "cfg.json"
        cfg = LLMConfig(provider="moonshot")
        cfg.api_keys["moonshot"] = "sk-x"
        cfg.save(cfg_path)

        def harness_factory(c, pr):
            return ChatHarness(
                c,
                pr,
                openai_module=_FakeOpenAIOK(),
                dns_lookup=lambda host: "127.0.0.1",
                ping_fn=lambda cfg, pr, mod: "pong",
            )

        chat = ChatHelp(
            state,
            project_root=tmp_project,
            config_path=cfg_path,
            llm_client_factory=lambda cfg, pr: _FakeLLMClient(cfg, pr),
            harness_factory=harness_factory,
        )
        chat._on_verify(None)
        assert "ping_round_trip" in chat.harness_alert.object
        assert "pong" not in chat.harness_alert.object  # status only, no raw reply
