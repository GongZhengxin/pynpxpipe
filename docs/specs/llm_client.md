# Spec: agent/llm_client.py

## 1. 目标

为 UI 内置的"chat help"模块提供一个**多后端 OpenAI 兼容 LLM 客户端**。用户在 chat 窗口提问，本模块负责：

1. 根据用户选择的 provider 路由到对应 base URL
2. 组装 system prompt（角色卡 + `GRAPH_REPORT.md` + `best_practices.md` + 动态 config dump）
3. 调用 `openai` SDK（所有 6 个 provider 都走 OpenAI 兼容协议）
4. 支持流式输出（`stream=True`），返回生成器
5. 从 `~/.pynpxpipe/llm_config.json` 读/写用户配置（API key、默认 provider、默认 model）

**模块位置**：`src/pynpxpipe/agent/llm_client.py`。`agent/` 是与 `core/` / `io/` / `stages/` / `ui/` 平级的新目录，专门放 LLM / 助手类功能（未来可能扩展 function-calling agent、RAG 等）。独立目录可以避免把 LLM 依赖渗透进 core 层。

**设计原则**：
- 零业务耦合：本模块不 import `pynpxpipe.stages.*` 或 `pynpxpipe.pipelines.*`，只读 `core/config.py` 的类型
- 可测：`openai.OpenAI` 通过依赖注入或 monkeypatch 替换，单元测试无需网络
- 可自检：配合 `agent/chat_harness.py`（见 §10）做环境自检 + 自动修复，确保部署环境即装即用
- 安全降级：`openai` 包是可选依赖（`[chat]` extra），未安装时 `LLMClient(...)` raise `LLMNotAvailable`，UI 捕获后显示"请安装 `[chat]` 依赖"

**非目标**：
- 不做 function calling / tool use（仅纯文本 QA）
- 不做对话历史持久化（历史保留在 Panel `ChatInterface` 控件内，会话关闭即丢弃）
- 不做 streaming 以外的异步并发

---

## 2. 输入

### 2.1 Provider 预设（模块常量）

```python
PROVIDERS: dict[str, ProviderPreset] = {
    "moonshot":    ProviderPreset(base_url="https://api.moonshot.cn/v1",        default_model="kimi-k2-0711-preview"),
    "dmxapi":      ProviderPreset(base_url="https://www.dmxapi.cn/v1",          default_model="gpt-4o"),
    "openai":      ProviderPreset(base_url="https://api.openai.com/v1",         default_model="gpt-4o"),
    "anthropic":   ProviderPreset(base_url="https://api.anthropic.com/v1",      default_model="claude-opus-4-6"),
    "siliconflow": ProviderPreset(base_url="https://api.siliconflow.cn/v1",     default_model="deepseek-ai/DeepSeek-V3"),
    "deepseek":    ProviderPreset(base_url="https://api.deepseek.com/v1",       default_model="deepseek-chat"),
}
```

其中 `ProviderPreset` 是 `dataclass(frozen=True)`，字段 `base_url: str`、`default_model: str`。

### 2.2 运行时配置（`~/.pynpxpipe/llm_config.json`）

```json
{
  "provider": "moonshot",
  "model": "kimi-k2-0711-preview",
  "api_keys": {
    "moonshot":    "sk-...",
    "dmxapi":      "",
    "openai":      "",
    "anthropic":   "",
    "siliconflow": "",
    "deepseek":    ""
  },
  "temperature": 0.3,
  "max_tokens": 2048
}
```

- 文件路径：`Path.home() / ".pynpxpipe" / "llm_config.json"`
- 首次启动时文件不存在 → 返回默认配置（provider="moonshot"，全部 api_key 为空）
- 写文件时父目录用 `mkdir(parents=True, exist_ok=True)`

### 2.3 `LLMClient.chat()` 调用参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `user_message` | `str` | 用户最新一条输入 |
| `history` | `list[dict[str, str]]` | 过往消息，格式 `[{"role": "user"\|"assistant", "content": "..."}]` |
| `stream` | `bool` | 是否流式（默认 True） |

---

## 3. 输出

### 3.1 公开 API

```python
from dataclasses import dataclass
from collections.abc import Iterator

@dataclass(frozen=True)
class ProviderPreset:
    base_url: str
    default_model: str

@dataclass
class LLMConfig:
    provider: str = "moonshot"
    model: str = ""                      # 空 = 用 provider default
    api_keys: dict[str, str] = field(default_factory=_default_keys)
    temperature: float = 0.3
    max_tokens: int = 2048

    @classmethod
    def load(cls, path: Path | None = None) -> "LLMConfig": ...
    def save(self, path: Path | None = None) -> None: ...

    def current_api_key(self) -> str:
        """Return api_keys[provider] or raise LLMConfigError if empty."""

    def current_model(self) -> str:
        """Return self.model or PROVIDERS[provider].default_model."""

class LLMNotAvailable(Exception):
    """openai package not installed."""

class LLMConfigError(Exception):
    """Config missing required fields (e.g., empty api_key)."""

class LLMClient:
    def __init__(
        self,
        config: LLMConfig,
        project_root: Path,
        *,
        openai_module=None,  # injection point for tests
    ) -> None: ...

    def build_system_prompt(self, extra: str | None = None) -> str:
        """Assemble role card + GRAPH_REPORT + best_practices [+ extra]."""

    def chat(
        self,
        user_message: str,
        history: list[dict[str, str]] | None = None,
        stream: bool = True,
    ) -> Iterator[str]:
        """Yield incremental text chunks. For stream=False, yields a single chunk."""
```

### 3.2 副作用

- `LLMConfig.save()` 写 `~/.pynpxpipe/llm_config.json`
- `LLMClient.chat()` 发送 HTTP 请求到 provider base_url
- 不写日志文件（UI 层由 `LogViewer` 决定是否显示），但 **失败时 raise**，不 swallow

---

## 4. 处理步骤

### 4.1 `LLMConfig.load(path)`

1. `path = path or Path.home() / ".pynpxpipe" / "llm_config.json"`
2. 文件不存在 → 返回 `LLMConfig()`（默认值）
3. 存在但 JSON 损坏 → raise `LLMConfigError` 带原始异常信息
4. 缺字段 → 用默认值补齐后返回
5. `api_keys` dict 中多出的 provider 名（不在 `PROVIDERS` 里）忽略，不 raise

### 4.2 `LLMClient.build_system_prompt(extra=None)`

1. **角色卡**（硬编码常量 `_ROLE_CARD`，~100 tokens）：
   > "你是 pynpxpipe 项目的助手 AI，对神经电生理数据处理管线熟悉。回答应该具体、引用项目中的真实模块名和配置项。不确定时明确说'不确定'，不要编造 API。"
2. 读 `{project_root}/graphify-out/GRAPH_REPORT.md`；不存在时跳过（打 warning 到 stderr，但不 raise）
3. 读 `{project_root}/docs/specs/best_practices.md`；不存在时跳过
4. 如果 `extra` 非空，追加（用于注入当前 UI 配置 dump）
5. 拼接格式：
   ```
   {ROLE_CARD}

   ## Project Knowledge Graph
   {GRAPH_REPORT.md 原文}

   ## Best Practices
   {best_practices.md 原文}

   ## Current UI Configuration
   {extra}
   ```

### 4.3 `LLMClient.chat(user_message, history, stream)`

1. 构造 messages list：`[{"role": "system", "content": build_system_prompt()}] + history + [{"role": "user", "content": user_message}]`
2. 若 `history` 为 `None`，视为 `[]`
3. 创建 `openai.OpenAI(api_key=config.current_api_key(), base_url=PROVIDERS[config.provider].base_url)`
4. 调用 `client.chat.completions.create(model=config.current_model(), messages=messages, stream=stream, temperature=config.temperature, max_tokens=config.max_tokens)`
5. **流式**：迭代 `response`，`yield chunk.choices[0].delta.content or ""`
6. **非流式**：`yield response.choices[0].message.content`

### 4.4 可选依赖的检测

`__init__` 中：
```python
if openai_module is None:
    try:
        import openai
        openai_module = openai
    except ImportError as exc:
        raise LLMNotAvailable("openai package not installed. `uv pip install -e \".[chat]\"`") from exc
self._openai = openai_module
```

---

## 5. 可配参数

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `provider` | `str` | `"moonshot"` | 6 选 1：moonshot / dmxapi / openai / anthropic / siliconflow / deepseek |
| `model` | `str` | `""` | 空则走 provider default（见 §2.1 表） |
| `api_keys.{provider}` | `str` | `""` | 每个 provider 独立 key |
| `temperature` | `float` | `0.3` | LLM 温度 |
| `max_tokens` | `int` | `2048` | 单次回复上限 |

---

## 6. 与现有模块的关系

- **core/config.py**：不改。`LLMConfig` 独立一个 dataclass，不进 `PipelineConfig`。
- **core/logging.py**：本模块**不**写 JSON Lines 日志（chat 交互不是 pipeline 事件）。
- **core/errors.py**：新增 `LLMNotAvailable`、`LLMConfigError` 两个异常类。
- **graphify-out/GRAPH_REPORT.md**：只读消费。如果 graphify 更新了报告，下一次 chat 会自动用新内容。
- **docs/specs/best_practices.md**：只读消费。用户可以手动编辑后 `/refresh-context`（UI 层实现）强制重载。

---

## 7. 错误处理

| 场景 | 行为 |
|---|---|
| `openai` 未安装 | `__init__` raise `LLMNotAvailable` |
| `api_keys[provider]` 为空 | `chat()` raise `LLMConfigError("API key not set for provider X")` |
| HTTP 401 / 网络错误 | 透传 `openai` 原生异常，UI 层 `try/except Exception` 显示错误 |
| `GRAPH_REPORT.md` 文件不存在 | `build_system_prompt` 打 stderr warning 后继续 |
| `llm_config.json` JSON 损坏 | `LLMConfig.load` raise `LLMConfigError` |

---

## 8. 测试策略（RED 要求）

### 8.1 `LLMConfig` 纯配置测试（无 mock）

- `test_default_instantiation`
- `test_load_missing_file_returns_default`
- `test_load_corrupt_json_raises`
- `test_save_creates_parent_dir`
- `test_save_roundtrip`
- `test_current_api_key_empty_raises`
- `test_current_model_falls_back_to_provider_default`
- `test_unknown_provider_key_ignored_on_load`

### 8.2 `LLMClient` 单元测试（mock `openai` module）

构造一个 fake `openai` 模块，`OpenAI()` 返回 mock，`chat.completions.create` 返回可迭代 mock。

- `test_init_raises_if_openai_missing` —— 传 `openai_module=None` 并 monkeypatch `sys.modules`
- `test_build_system_prompt_includes_role_card`
- `test_build_system_prompt_includes_graph_report_when_exists`
- `test_build_system_prompt_skips_missing_graph_report`
- `test_build_system_prompt_includes_best_practices_when_exists`
- `test_build_system_prompt_appends_extra`
- `test_chat_streams_chunks`（用 fake iterator）
- `test_chat_non_streaming_yields_single_chunk`
- `test_chat_raises_if_api_key_empty`
- `test_chat_passes_history_and_user_message`
- `test_chat_uses_provider_base_url`
- `test_chat_uses_current_model_from_config`

### 8.3 Provider 常量测试

- `test_all_6_providers_registered`
- `test_each_preset_has_base_url_and_default_model`

---

## 9. 依赖声明

`pyproject.toml` 新增：
```toml
[project.optional-dependencies]
chat = ["openai>=1.0"]
```

UI extra 和 chat extra 都是 optional；用户按需安装：
```bash
uv pip install -e ".[ui,chat]"
```

---

## 10. Harness（自我调适 / 自我修复）

> **动机**：单元测试只证明"在 mock 下代码逻辑对"，但真正跑起来还有一堆环境 / 配置 / 外部依赖问题：`openai` 没装、config 文件损坏、API key 空、`GRAPH_REPORT.md` 不存在、网络连不上、model 名写错。单靠 TDD 不够 —— 需要一层 **preflight check + 自动修复**，能在 UI 启动或 chat 首次调用时跑一次，确认"这个环境能跑 chat"或者给出**可执行的修复指令**。

Harness 模块位置：`src/pynpxpipe/agent/chat_harness.py`。遵循现有 `pynpxpipe.harness` 的 `CheckResult` / `FixTier` 命名，但**独立实现**（harness 那一套是绑定 pipeline stage 的，chat 的检查条目完全不同，复用反而拧巴）。

### 10.1 检查矩阵

| check 名 | 内容 | 失败时的 tier | 可否自动修复 |
|---|---|---|---|
| `openai_installed` | `import openai` 成功 | RED | 否（需 `uv pip install`，只能给提示） |
| `openai_version` | `openai >= 1.0` | RED | 否 |
| `config_file_readable` | `~/.pynpxpipe/llm_config.json` 可读（不存在时视为 pass，返回默认） | YELLOW | **是** —— 用默认值重写 |
| `api_key_present` | `config.api_keys[provider]` 非空 | RED | 否（用户必须自己填）|
| `graph_report_exists` | `{project_root}/graphify-out/GRAPH_REPORT.md` 存在 | YELLOW | 否（只给 warning，不影响 chat） |
| `best_practices_exists` | `{project_root}/docs/specs/best_practices.md` 存在 | YELLOW | 否 |
| `provider_base_url_resolvable` | `socket.gethostbyname(urlparse(base_url).hostname)` 成功 | RED | 否（网络问题）|
| `ping_round_trip` | 发送 1-token `"ping"` 请求，校验能拿到非空回复 | RED | 否（只做验证）|

### 10.2 API

```python
from dataclasses import dataclass
from typing import Literal

CheckStatus = Literal["pass", "warn", "fail"]
FixTier = Literal["GREEN", "YELLOW", "RED"]

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
    results: list[ChatCheckResult]
    applied_fixes: list[str]

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
        """Human-readable multi-line summary for UI display."""


class ChatHarness:
    def __init__(
        self,
        config: LLMConfig,
        project_root: Path,
        *,
        openai_module=None,       # injection
        dns_lookup=None,          # injection for offline tests
        ping_fn=None,             # injection for offline tests
    ) -> None: ...

    def check_all(self, *, do_ping: bool = False) -> HarnessReport:
        """Run all checks. do_ping=False by default to avoid network cost at startup."""

    def auto_fix(self, report: HarnessReport) -> HarnessReport:
        """Apply GREEN/YELLOW fixes. Re-run check_all() after."""
```

### 10.3 使用位置

1. **UI 启动时**：`ChatHelp.__init__` 调 `ChatHarness(config, project_root).check_all(do_ping=False)`，把 warnings/failures 显示在 help 分区顶部的 Alert 里。不阻塞 UI 加载。
2. **首次 chat 调用前**：`ChatHelp._on_user_message` 在 `LLMClient` 实例化之前调 `check_all(do_ping=False)`。有 RED fail 就拒绝 send 并回显修复指引。
3. **手动"Verify connection"按钮**：Help 分区提供按钮触发 `check_all(do_ping=True)`，用最小 prompt 实际打一次 round-trip，确认 provider 真的能用。
4. **CLI / 部署检查**：提供 `python -m pynpxpipe.agent.chat_harness` 入口，开发者 / 用户可以在命令行跑一次自检，无需打开 UI。

### 10.4 自我修复规则

- **YELLOW `config_file_readable` 失败**（JSON 损坏）：备份到 `~/.pynpxpipe/llm_config.json.bak_{timestamp}`，用默认值重写。
- **YELLOW `config_file_readable` 文件不存在**：静默创建带默认值的新文件（视为 pass）。
- **RED 级别的问题不自动修复**，只给出精确的修复指令（`uv pip install -e ".[chat]"`、"请在 Help 分区填 API Key 并点 Save"）。

### 10.5 Harness 测试策略

`tests/test_agent/test_chat_harness.py`：

- `test_openai_missing_reports_red`（monkeypatch `sys.modules["openai"] = None`）
- `test_openai_version_too_old_reports_red`（fake module with `__version__ = "0.9.0"`）
- `test_missing_config_file_creates_default`
- `test_corrupt_config_file_backed_up_and_reset`
- `test_empty_api_key_reports_red`
- `test_missing_graph_report_reports_warn_not_fail`
- `test_base_url_unresolvable_reports_red`（inject `dns_lookup=lambda host: raise OSError`）
- `test_ping_round_trip_success`（inject `ping_fn` returning `"pong"`）
- `test_ping_round_trip_failure`（inject `ping_fn` raising）
- `test_auto_fix_rewrites_corrupt_config`
- `test_harness_report_format_is_human_readable`
- `test_passed_true_when_no_failures`
- `test_passed_false_when_any_red`

另外有一个 **集成自检**（可选，打 `@pytest.mark.chat_live`，CI 跳过）：

- `test_real_environment_harness_no_network` —— 跑真实 `check_all(do_ping=False)`，至少不应该 raise，至少 `openai_installed` 应 pass（在装了 `[chat]` extra 的环境里）

### 10.6 与项目已有 `harness/` 的关系

- `pynpxpipe.harness.*` —— 面向 pipeline stage 的 preflight + validator + fixer，和录制数据、config 紧耦合
- `pynpxpipe.agent.chat_harness` —— 面向 chat 功能的环境自检，和业务无关

不共享代码，只共享命名风格（`CheckResult` / `FixTier` / "auto_fixable"）。两者各自演化。
