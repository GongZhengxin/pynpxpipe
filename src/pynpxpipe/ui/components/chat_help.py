"""ui/components/chat_help.py — LLM-powered help assistant.

Thin Panel shell around ``agent/llm_client.py``. Provides a provider /
model / API-key form, a chat interface, harness-based environment
self-check, and buttons for refreshing static context and importing the
current UI configuration into the chat context.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import panel as pn
import yaml

from pynpxpipe.agent.chat_harness import ChatHarness, HarnessReport
from pynpxpipe.agent.llm_client import (
    PROVIDERS,
    LLMConfig,
    LLMConfigError,
    LLMNotAvailable,
)
from pynpxpipe.ui.state import AppState


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


class ChatHelp:
    """Help / chat assistant UI component.

    Args:
        state: Shared ``AppState``.
        project_root: Repository root (for GRAPH_REPORT + best_practices).
        config_path: Path to ``llm_config.json`` (default
            ``~/.pynpxpipe/llm_config.json``).
        llm_client_factory: Callable ``(LLMConfig, project_root) -> LLMClient``.
            Injected for testing so no real ``openai`` import is required.
        harness_factory: Callable ``(LLMConfig, project_root) -> ChatHarness``.
            Injected for testing.
    """

    def __init__(
        self,
        state: AppState,
        *,
        project_root: Path | None = None,
        config_path: Path | None = None,
        llm_client_factory: Callable[[LLMConfig, Path], Any] | None = None,
        harness_factory: Callable[[LLMConfig, Path], ChatHarness] | None = None,
    ) -> None:
        self._state = state
        self._project_root = project_root or _default_project_root()
        self._config_path = config_path
        self._config = LLMConfig.load(config_path) if config_path else LLMConfig.load()
        self._llm_client_factory = llm_client_factory or self._default_client_factory
        self._harness_factory = harness_factory or self._default_harness_factory

        self._client: Any | None = None
        self._extra_context: str | None = None

        # ── Widgets ──
        self.provider_select = pn.widgets.Select(
            name="Provider",
            options=list(PROVIDERS.keys()),
            value=self._config.provider,
            width=160,
        )
        self.model_input = pn.widgets.TextInput(
            name="Model",
            placeholder=PROVIDERS[self._config.provider].default_model,
            value=self._config.model,
            width=240,
        )
        self.api_key_input = pn.widgets.PasswordInput(
            name="API Key",
            value=self._config.api_keys.get(self._config.provider, ""),
            width=280,
        )
        self.save_btn = pn.widgets.Button(name="Save Config", button_type="success")
        self.save_btn.on_click(self._on_save_config)
        self.refresh_btn = pn.widgets.Button(name="Refresh Context", button_type="primary")
        self.refresh_btn.on_click(self._on_refresh_context)
        self.import_btn = pn.widgets.Button(name="Import Current UI Config", button_type="primary")
        self.import_btn.on_click(self._on_import_ui_config)
        self.verify_btn = pn.widgets.Button(name="Verify Connection", button_type="default")
        self.verify_btn.on_click(self._on_verify)

        self.message_pane = pn.pane.Alert(
            "", alert_type="light", sizing_mode="stretch_width", visible=False
        )
        self.harness_alert = pn.pane.Markdown("", sizing_mode="stretch_width")

        self.provider_select.param.watch(self._on_provider_change, "value")

        # Panel's ChatInterface is what actually renders the chat thread.
        self._chat_interface: Any | None = None

        # Run initial harness self-check.
        self._run_harness(do_ping=False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def panel(self) -> pn.viewable.Viewable:
        """Return the full help-section layout."""
        if self._chat_interface is None:
            self._chat_interface = pn.chat.ChatInterface(
                callback=self._chat_callback,
                show_button_name=False,
                sizing_mode="stretch_width",
                height=500,
            )
        form_row = pn.Row(
            self.provider_select,
            self.model_input,
            self.api_key_input,
            self.save_btn,
        )
        button_row = pn.Row(self.refresh_btn, self.import_btn, self.verify_btn)
        return pn.Column(
            pn.pane.Markdown("## Help / AI Assistant"),
            form_row,
            button_row,
            self.message_pane,
            self.harness_alert,
            self._chat_interface,
            sizing_mode="stretch_width",
        )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_provider_change(self, event) -> None:
        new_provider = event.new
        self.model_input.placeholder = PROVIDERS[new_provider].default_model
        self.api_key_input.value = self._config.api_keys.get(new_provider, "")

    def _on_save_config(self, event) -> None:
        self._config.provider = self.provider_select.value
        self._config.model = self.model_input.value
        self._config.api_keys[self._config.provider] = self.api_key_input.value
        try:
            if self._config_path is not None:
                self._config.save(self._config_path)
            else:
                self._config.save()
        except OSError as exc:
            self._show_message(f"Failed to save config: {exc}", level="danger")
            return
        self._client = None
        self._show_message("Config saved.", level="success")

    def _on_refresh_context(self, event) -> None:
        self._client = None
        self._show_message(
            "Context refreshed — next message will reload GRAPH_REPORT and best_practices.",
            level="info",
        )

    def _on_import_ui_config(self, event) -> None:
        pipeline_cfg = self._state.pipeline_config
        sorting_cfg = self._state.sorting_config
        if pipeline_cfg is None:
            self._show_message("No pipeline config in UI state.", level="warning")
            return
        self._extra_context = self._dump_configs(pipeline_cfg, sorting_cfg)
        self._client = None
        self._show_message("Current UI config imported into chat context.", level="success")

    def _on_verify(self, event) -> None:
        self._run_harness(do_ping=True)

    def _chat_callback(self, contents: str, user: str, instance: Any) -> Iterator[str]:
        """Panel ChatInterface callback — called when the user hits send."""
        history = self._extract_history(instance)
        return self._on_user_message(contents, user=user, instance=instance, history=history)

    def _on_user_message(
        self,
        contents: str,
        user: str = "User",
        instance: Any = None,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        """Internal hook exposed for unit tests (bypasses ChatInterface)."""
        if self._client is None:
            try:
                self._client = self._llm_client_factory(self._config, self._project_root)
            except LLMNotAvailable as exc:
                yield f"[chat unavailable] {exc}"
                return
            except Exception as exc:  # noqa: BLE001
                yield f"[chat init failed] {exc}"
                return

        try:
            iterator = self._client.chat(
                contents,
                history=history or [],
                stream=True,
                extra_context=self._extra_context,
            )
            yield from iterator
        except LLMConfigError as exc:
            yield f"[config error] {exc}"
        except Exception as exc:  # noqa: BLE001
            yield f"[chat error] {type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------
    # Harness
    # ------------------------------------------------------------------

    def _run_harness(self, *, do_ping: bool) -> HarnessReport:
        harness = self._harness_factory(self._config, self._project_root)
        report = harness.check_all(do_ping=do_ping)
        self.harness_alert.object = "```\n" + report.format() + "\n```"
        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _show_message(self, text: str, *, level: str) -> None:
        self.message_pane.alert_type = level
        self.message_pane.object = text
        self.message_pane.visible = True

    @staticmethod
    def _extract_history(instance: Any) -> list[dict[str, str]]:
        """Pull prior messages from a Panel ChatInterface instance."""
        if instance is None or not hasattr(instance, "objects"):
            return []
        history: list[dict[str, str]] = []
        for obj in instance.objects:
            user = getattr(obj, "user", "") or ""
            content = getattr(obj, "object", None)
            if content is None or user.lower() == "system":
                continue
            role = "assistant" if user.lower() != "user" else "user"
            history.append({"role": role, "content": str(content)})
        return history

    @staticmethod
    def _dump_configs(pipeline_cfg: Any, sorting_cfg: Any) -> str:
        parts: list[str] = []
        if is_dataclass(pipeline_cfg):
            parts.append("### pipeline.yaml")
            parts.append(
                "```yaml\n"
                + yaml.safe_dump(asdict(pipeline_cfg), allow_unicode=True, sort_keys=False)
                + "```"
            )
        if is_dataclass(sorting_cfg):
            parts.append("### sorting.yaml")
            parts.append(
                "```yaml\n"
                + yaml.safe_dump(asdict(sorting_cfg), allow_unicode=True, sort_keys=False)
                + "```"
            )
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Default factories (production wiring)
    # ------------------------------------------------------------------

    @staticmethod
    def _default_client_factory(config: LLMConfig, project_root: Path) -> Any:
        from pynpxpipe.agent.llm_client import LLMClient

        return LLMClient(config, project_root)

    @staticmethod
    def _default_harness_factory(config: LLMConfig, project_root: Path) -> ChatHarness:
        return ChatHarness(config, project_root)
