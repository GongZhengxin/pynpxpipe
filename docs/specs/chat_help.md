# Spec: ui/components/chat_help.py

## 1. 目标

在 UI 里新增一个 **Help** 分区（和 Configure / Execute / Review 平级），承载：

1. **Provider 配置表单**：provider 选择、model 输入、API key 输入、保存按钮
2. **Panel ChatInterface 聊天控件**：多轮对话 UI + 流式渲染
3. **上下文刷新按钮**：用户手动编辑 `best_practices.md` 后点击重载 system prompt
4. **"导入当前 UI 配置"按钮**：把 `AppState.pipeline_config` 和 `sorting_config` 以 YAML 形式注入 system prompt 的 `extra`，让 LLM 基于当前配置回答

**定位**：UI 薄壳，业务逻辑在 `agent/llm_client.py`。本文件只负责布局、事件绑定、错误提示。

**非目标**：
- 不做对话历史持久化（会话关闭即丢）
- 不做 RAG —— 所有上下文来自静态 markdown
- 不做多 session chat tab —— 单一 ChatInterface 即可

---

## 2. 输入

- `state: AppState` —— 用于读取当前 `pipeline_config` / `sorting_config` 给 "导入配置" 按钮使用
- `llm_client_factory: Callable[[LLMConfig], LLMClient] | None` —— 可注入的工厂，默认用 `LLMClient(config, project_root)`；测试时替换为返回 mock client

---

## 3. 输出

### 3.1 公开 API

```python
class ChatHelp:
    def __init__(
        self,
        state: AppState,
        *,
        project_root: Path | None = None,
        llm_client_factory: Callable[[LLMConfig], "LLMClient"] | None = None,
    ) -> None: ...

    def panel(self) -> pn.viewable.Viewable:
        """Return the full Help section layout (config form + chat interface)."""
```

### 3.2 UI 布局

```
## Help / AI Assistant

[ Provider dropdown ▾ ] [ Model text ] [ API Key password ]  [ Save Config ]
[ Refresh Context ] [ Import Current UI Config ]

[ ---- Panel ChatInterface ---- ]
| user: 怎么开启运动校正?                                   |
| assistant: 在 Configure → Pipeline 面板中找 Motion ...    |
| (streaming)                                             |
| [ Type a message... ]  [ Send ]                         |
```

widgets:
- `provider_select: pn.widgets.Select(options=list(PROVIDERS.keys()))`
- `model_input: pn.widgets.TextInput(placeholder="(empty = provider default)")`
- `api_key_input: pn.widgets.PasswordInput()`
- `save_btn: pn.widgets.Button(name="Save Config")`
- `refresh_btn: pn.widgets.Button(name="Refresh Context")`
- `import_cfg_btn: pn.widgets.Button(name="Import Current UI Config")`
- `message_pane: pn.pane.Alert`（保存成功 / 报错提示）
- `chat: pn.chat.ChatInterface(callback=self._on_user_message, show_button_name=False)`

---

## 4. 处理步骤

### 4.1 初始化

1. `project_root = project_root or Path(__file__).resolve().parents[4]` （回到仓库根）
2. `self._config = LLMConfig.load()` —— 读 `~/.pynpxpipe/llm_config.json`
3. 创建 widgets，并把当前 config 的值回显到表单
4. `provider_select.param.watch(self._on_provider_change, "value")` —— 切换 provider 时自动刷新 model_input 的 placeholder 并从 `config.api_keys[new_provider]` 取对应 key
5. `save_btn.on_click(self._on_save_config)`
6. `refresh_btn.on_click(self._on_refresh_context)`
7. `import_cfg_btn.on_click(self._on_import_ui_config)`
8. `verify_btn.on_click(self._on_verify)` —— 触发 harness `check_all(do_ping=True)` 做在线自检
9. `self._client: LLMClient | None = None` —— 懒加载，首次 chat 时才实例化
10. 运行一次 `ChatHarness(config, project_root).check_all(do_ping=False)`，把结果显示在顶部 Alert（warn 黄色、fail 红色）

### 4.2 `_on_save_config`

1. 把表单值写回 `self._config`
2. `self._config.save()`
3. `self._client = None` —— 强制下次 chat 重建 client
4. `message_pane.object = "Config saved."`；`alert_type = "success"`

### 4.3 `_on_refresh_context`

1. `self._client = None`
2. 消息提示："Context refreshed. Next message will reload GRAPH_REPORT and best_practices."

### 4.4 `_on_import_ui_config`

1. 读取 `self._state.pipeline_config` 和 `sorting_config`
2. 转 YAML 字符串（用 `yaml.safe_dump`）
3. 保存到 `self._extra_context`
4. `self._client = None`（下次 chat 时注入新 extra）
5. 消息提示 "Current UI config imported into chat context."

如果 `pipeline_config` 为 None，提示 "No pipeline config in UI state"。

### 4.5 `_on_user_message(contents, user, instance)`

Panel 的 ChatInterface callback 签名：`(contents: str, user: str, instance: ChatInterface)`。

1. 确保 client 存在：
   ```python
   if self._client is None:
       try:
           self._client = self._llm_client_factory(self._config)
       except LLMNotAvailable as exc:
           instance.send(str(exc), user="System", respond=False)
           return
   ```
2. 组装 history：从 `instance.objects` 里取之前所有消息（排除 System 消息），映射到 `[{"role": "user"|"assistant", "content": ...}]`
3. 调用 `self._client.chat(contents, history=history, stream=True)`
4. **流式返回处理**：Panel ChatInterface 的 callback 可以直接 `return` 一个 iterator，Panel 会自动把 chunks append 到 assistant 消息
5. 错误处理：捕获 `LLMConfigError` 和通用 `Exception`，send 错误文本到 chat 窗口

### 4.6 构造 `extra` 字符串

```python
def _build_extra(self) -> str | None:
    if self._state.pipeline_config is None:
        return None
    import yaml
    pc = yaml.safe_dump(asdict(self._state.pipeline_config), allow_unicode=True, sort_keys=False)
    sc = yaml.safe_dump(asdict(self._state.sorting_config), allow_unicode=True, sort_keys=False)
    return f"### pipeline.yaml\n```yaml\n{pc}\n```\n### sorting.yaml\n```yaml\n{sc}\n```"
```

---

## 5. 可配参数

无 —— 所有运行时参数走 `LLMConfig`（持久化到 `~/.pynpxpipe/llm_config.json`），本组件无 yaml 配置项。

---

## 6. 与 app.py 的集成

在 `create_app()` 中：
1. `chat_help = ChatHelp(state)`
2. 新建 `help_section = pn.Column(chat_help.panel(), visible=False)`
3. 加到 `sections` dict 和 `FastListTemplate.main` 列表
4. 侧栏 nav 按钮增加 "Help"
5. `switch_section` 逻辑自动涵盖

---

## 7. 错误处理

| 场景 | UI 行为 |
|---|---|
| `openai` 未安装 | 在 chat 窗口以 "System" 身份 send `"openai package not installed. Install with: uv pip install -e .[chat]"`，表单仍可保存 config |
| API key 为空 | 在 chat 窗口 send `"API key not set for provider X. Please save config first."` |
| HTTP 401 / 网络错误 | send 原始异常字符串（不屏蔽） |
| 保存 config 失败（写磁盘权限） | `message_pane` 红色 alert |

---

## 8. 测试策略（RED 要求）

### 8.1 构造与布局

- `test_creates_panel_layout`
- `test_widgets_reflect_loaded_config`（mock `LLMConfig.load` 返回预设值）
- `test_provider_select_has_all_6_options`

### 8.2 Save / Refresh / Import 按钮

- `test_save_config_writes_file`（mock `LLMConfig.save`）
- `test_save_config_resets_client`
- `test_refresh_context_resets_client`
- `test_import_ui_config_sets_extra`
- `test_import_ui_config_none_shows_message`

### 8.3 Provider 切换

- `test_provider_change_updates_api_key_field`

### 8.4 Chat callback（mock LLMClient）

构造 `FakeLLMClient`，`chat()` 返回固定 iterator。

- `test_user_message_lazy_instantiates_client`
- `test_user_message_returns_iterator`
- `test_user_message_handles_llm_not_available`
- `test_user_message_handles_llm_config_error`
- `test_user_message_includes_history`
- `test_user_message_includes_extra_context_after_import`

### 8.5 错误提示

- `test_save_config_write_error_shows_message`

---

## 9. 依赖

- `panel >= 1.4`（`pn.chat.ChatInterface` 需要 1.4+）
- `pyyaml`（已有）
- `openai >= 1.0`（通过 `[chat]` extra，由 `llm_client.py` 统一管理）

**不引入**：
- 不引入 `langchain` / `llama-index` 等 RAG 框架
- 不引入 `tiktoken`（不做精确 token 计数，只做粗估）
