# Spec: ui/components/probe_region_editor.py

## 1. 目标

`ProbeRegionEditor` 是 Panel UI 的一个表单组件，负责维护 `AppState.probe_plan: dict[str, str]` —— 即用户在运行 pipeline 之前声明的 `{probe_id: target_area}` 映射。

该组件的设计原则：

- **轻薄 UI 层**：不做任何业务校验，不 import `core.session`，只读写 `AppState.probe_plan`（`param.Dict`）
- **与 Session 耦合点唯一**：`SessionManager.create()` 从 `state.probe_plan` 取值构造 `Session.probe_plan` 与 `SessionID.region`（`region = "-".join(sorted by probe_id)`）
- **无正则校验**：用户输入的 `target_area` 是自由字符串（例如 `"MSB"`, `"V4"`, `"IT"`），空值仅通过红框视觉提示，不阻塞
- **probe_id 自动生成**：点击 `+ Add probe` 时，新 probe_id 固定为 `imec{max_existing+1}`，用户不可编辑
- **支持外部回填**：`SessionLoader` 从磁盘恢复 Session 时写入 `state.probe_plan`，组件监听该 param 变化后重渲染
- **顺序稳定**：内部维持 `dict[str, str]` 的插入 / 编辑顺序，不做 sort

无业务逻辑，仅操作 `state.probe_plan`。region 的拼接由 `SessionID.derive_region()` 在下游完成（见 `docs/specs/session.md` §5.5），本组件**不**计算 region。

---

## 2. 输入

### 2.1 构造参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `state` | `AppState` | 全局 UI 状态对象，组件读写其 `probe_plan` 字段 |

### 2.2 依赖的 AppState 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `state.probe_plan` | `param.Dict` | `{probe_id: target_area}`；组件初始化时若为空则自动填入 `{"imec0": ""}` |

注：`AppState` 当前未显式声明 `probe_plan`，需在 `state.py` 增加：

```python
probe_plan = param.Dict(default={}, doc="{probe_id: target_area} declared before run")
```

### 2.3 用户交互输入

| 事件源 | 说明 |
|--------|------|
| 每行的 `TextInput`（area） | 值变化时写入 `state.probe_plan[probe_id]` |
| 每行的 `×` Button | 点击后从 `state.probe_plan` 删除该 probe_id |
| `+ Add probe` Button | 点击后向 `state.probe_plan` 追加 `{"imec{max+1}": ""}` |

---

## 3. 输出

组件通过 `__panel__()` 渲染为一个 `pn.Column`，布局如下：

```
┌──────────────────────────────────────────────┐
│ ### Probe Target Areas                       │
├──────────────────────────────────────────────┤
│ imec0    [ MSB           ]    [ × ]          │
│ imec1    [ V4            ]    [ × ]          │
│ imec2    [               ]    [ × ]  ← red   │
├──────────────────────────────────────────────┤
│ [ + Add probe ]                              │
└──────────────────────────────────────────────┘
```

- probe_id 以只读 Markdown / `StaticText` 呈现，不做 TextInput
- area TextInput 的 `stylesheets` 根据值是否为空动态切换（空 → red border）
- `×` Button 当 `len(probe_plan) == 1` 时 `disabled=True`
- 唯一副作用：`state.probe_plan` 被原地写入新 dict（保证 param watch 触发）

---

## 4. 处理步骤

### 4.1 初始化

1. 保存 `self._state = state`
2. 若 `state.probe_plan` 为空 dict，写入 `{"imec0": ""}`（触发一次 param 事件）
3. 注册 `state.param.watch(self._rerender, "probe_plan")`，用于外部回填
4. 首次构建 `self._container = pn.Column(...)`，调用 `_rerender()` 渲染初始行

### 4.2 `_rerender(event=None)` — 重建所有行

1. 清空 `self._container.objects`
2. 对 `state.probe_plan.items()` 按插入顺序遍历：
   - 为每个 probe 构造一行 `pn.Row(label, TextInput, delete_btn)`
   - TextInput 注册 `watch("value")` → `_on_area_change(probe_id, new_value)`
   - 空值时 TextInput 加红框 `stylesheets`
   - delete_btn 注册 `on_click` → `_delete_probe(probe_id)`，当 `len == 1` 时 disabled
3. 在最后追加 `+ Add probe` 按钮
4. 每次 rerender 重新创建 widget 实例（避免 watcher 残留）

### 4.3 `_add_probe(event=None)` — 追加一行

1. 从当前 `state.probe_plan` 的 key 中取出所有匹配 `imec\d+$` 的 probe_id
2. 计算 `max_n = max(int(k[4:]) for k in keys)`；若无 key 则 `max_n = -1`
3. 新 probe_id = `f"imec{max_n + 1}"`
4. 写入 `state.probe_plan = {**state.probe_plan, new_probe_id: ""}`（新 dict 触发 watch）
5. `_rerender()` 由 watch 自动触发

### 4.4 `_delete_probe(probe_id)` — 删除一行

1. 若 `len(state.probe_plan) <= 1` → 直接返回（防御，UI 已 disabled）
2. `new_plan = {k: v for k, v in state.probe_plan.items() if k != probe_id}`
3. `state.probe_plan = new_plan`
4. `_rerender()` 由 watch 自动触发

### 4.5 `_on_area_change(probe_id, new_value)` — 值变化回写

1. 若 `probe_id` 不在 `state.probe_plan`（可能已被删除）→ 返回
2. `new_plan = {**state.probe_plan, probe_id: new_value}`
3. `state.probe_plan = new_plan`
4. **不** 调用 `_rerender()`（避免 TextInput 失焦）；红框样式通过 widget 自身 style 切换即可

**注**：因为 `_on_area_change` 会写 `state.probe_plan`，而组件又 watch 同一 param，需在写入前后用 `self._suppress_watch` 标志位避免 rerender 反弹。或者在 `_rerender` 内比较 DOM 与目标结构、只在 key 集合变化时重建。实现上采用**标志位**方案，简单直接。

### 4.6 外部回填（SessionLoader 场景）

当 `SessionLoader` 调用 `state.probe_plan = {"imec0": "MSB", "imec1": "V4"}`：

1. param watch 触发 `_rerender(event)`
2. `event.new` 与 `event.old` 的 key 集合不同，或值不同
3. 清空 `_container` 重新渲染所有行
4. 用户肉眼可见新数据

---

## 5. 公开 API

### 5.1 类签名

```python
from __future__ import annotations

import panel as pn
import param

from pynpxpipe.ui.state import AppState


class ProbeRegionEditor(pn.viewable.Viewer):
    """Per-probe target_area editor bound to AppState.probe_plan.

    Layout: one row per probe `[probe_id label][TextInput area][× button]`,
    followed by a single `+ Add probe` button. No regex validation — an
    empty area input shows a red border as a visual hint only.
    """

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self._state = state
        self._suppress_watch = False
        self._container = pn.Column()

        if not self._state.probe_plan:
            self._state.probe_plan = {"imec0": ""}

        self._state.param.watch(self._on_external_update, "probe_plan")
        self._rerender()

    # Public

    def __panel__(self) -> pn.Column:
        return self._container

    # Internal (exposed for tests)

    def _add_probe(self, event=None) -> None: ...
    def _delete_probe(self, probe_id: str) -> None: ...
    def _on_area_change(self, probe_id: str, new_value: str) -> None: ...
    def _on_external_update(self, event) -> None: ...
    def _rerender(self) -> None: ...
    def _next_probe_id(self) -> str: ...
```

### 5.2 关键方法实现草图

```python
_RED_BORDER_STYLE = {"border": "2px solid #d9534f"}

def _next_probe_id(self) -> str:
    nums = [
        int(k[4:]) for k in self._state.probe_plan
        if k.startswith("imec") and k[4:].isdigit()
    ]
    return f"imec{(max(nums) + 1) if nums else 0}"

def _add_probe(self, event=None) -> None:
    new_id = self._next_probe_id()
    self._state.probe_plan = {**self._state.probe_plan, new_id: ""}

def _delete_probe(self, probe_id: str) -> None:
    if len(self._state.probe_plan) <= 1:
        return
    self._state.probe_plan = {
        k: v for k, v in self._state.probe_plan.items() if k != probe_id
    }

def _on_area_change(self, probe_id: str, new_value: str) -> None:
    if probe_id not in self._state.probe_plan:
        return
    self._suppress_watch = True
    try:
        self._state.probe_plan = {**self._state.probe_plan, probe_id: new_value}
    finally:
        self._suppress_watch = False

def _on_external_update(self, event) -> None:
    if self._suppress_watch:
        return
    self._rerender()
```

### 5.3 AppState 集成

`ui/state.py` 需新增一行：

```python
probe_plan = param.Dict(
    default={},
    doc="{probe_id: target_area} declared before run; written by ProbeRegionEditor.",
)
```

下游 `SessionLoader` / `SessionForm` 读写同一 param，两者通过 AppState 解耦。

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_ui/test_probe_region_editor.py`

| # | 测试名 | 测试点 |
|---|--------|-------|
| 1 | `test_initial_renders_imec0_row_when_plan_empty` | `AppState()` 默认 `probe_plan == {}`；构造 `ProbeRegionEditor(state)` 后 `state.probe_plan == {"imec0": ""}`，容器含一行且 probe_id 文本为 `"imec0"` |
| 2 | `test_renders_one_row_per_probe_in_plan` | 预置 `state.probe_plan = {"imec0": "MSB", "imec1": "V4"}` 后构造组件，容器首行 probe label 含 `"imec0"`、area TextInput.value == `"MSB"`；第二行对应 `"imec1"` / `"V4"` |
| 3 | `test_add_probe_appends_next_imec_id` | 预置 `{"imec0": "MSB"}`，调用 `_add_probe()`，`state.probe_plan` keys 为 `["imec0", "imec1"]`，新值为空串 |
| 4 | `test_add_probe_with_gap_uses_max_plus_one` | 预置 `{"imec0": "A", "imec2": "B"}`，调用 `_add_probe()`，新 key == `"imec3"`（`max + 1`，非填补 `imec1`） |
| 5 | `test_delete_removes_row_and_updates_state` | 预置两行，调用 `_delete_probe("imec0")`，`state.probe_plan` 仅剩 `"imec1"`，容器行数 == 1 |
| 6 | `test_delete_disabled_when_single_row` | 仅一行时，该行 delete_btn.disabled == True；调用 `_delete_probe("imec0")` 无副作用（dict 不变） |
| 7 | `test_text_input_writes_to_state_on_change` | 找到 `"imec0"` 的 TextInput，模拟 `text_input.value = "IT"`，断言 `state.probe_plan["imec0"] == "IT"` |
| 8 | `test_empty_target_area_shows_red_border` | 预置 `{"imec0": ""}`，对应 TextInput 的 `stylesheets` 含 red border 样式；再设为非空后红框消失 |
| 9 | `test_external_state_update_rerenders` | 构造组件（默认单行），外部调用 `state.probe_plan = {"imec0": "MSB", "imec1": "V4"}`，容器重渲染为两行且值正确（模拟 SessionLoader 回填） |

测试约束：

- 使用 `AppState()` 真实实例，不 mock param 层
- Panel widget 的值读写通过 `widget.value = ...` 直接触发，不依赖真实浏览器
- 判定 red border 时通过 `widget.stylesheets` 内容字符串包含 `"#d9534f"` 或约定的 class 名
- 不启动 Panel server；测试只读容器对象结构（`len(editor._container.objects)`、嵌套 Row 的子节点类型）

---

## 7. 依赖

- `panel >= 1.0` — `pn.viewable.Viewer`, `pn.Column`, `pn.Row`, `pn.widgets.TextInput`, `pn.widgets.Button`, `pn.pane.Markdown` / `pn.widgets.StaticText`
- `param` — 通过 `AppState.param.watch` 监听外部更新
- `pynpxpipe.ui.state.AppState` — 共享模型，读写 `probe_plan` 字段

不依赖：

- `core.session` — 本组件不构造 `Session` 或 `SessionID`，region 派生由 `SessionManager.create()` + `SessionID.derive_region()` 负责
- `core.config` — 无 YAML 读写
- 任何业务模块（io / stages / pipelines）

---

## 8. 与现有组件的关系

| 组件 | 关系 |
|------|------|
| `SubjectForm` | 并列关系，同为 `AppState` 的写入者；两者通过 AppState 解耦，不互相 import |
| `SessionLoader` | `SessionLoader` 加载 `session.json` 后写入 `state.probe_plan`，触发本组件重渲染 |
| `SessionForm` | 执行时从 `state.probe_plan` 取值调用 `SessionManager.create(..., probe_plan=state.probe_plan, ...)`；若 `probe_plan` 为空或含空 area，由 `SessionManager` 侧 raise `ValueError`（与无正则校验原则一致，UI 不提前拦截） |

---

## 9. 不做什么

- 不校验 `target_area` 字符集、长度、大小写（用户自由填写）
- 不校验 probe_id 唯一性（由自动生成保证）
- 不允许用户手改 probe_id（固定 `imec{N}`）
- 不提供 reorder（拖拽排序）能力 —— 顺序由插入时间决定
- 不计算 / 不展示 `SessionID.region` 预览 —— 属于 `SessionForm` 的 preview 区职责
- 不持久化到 YAML —— 状态随 `session.json` 在 `SessionManager.save()` 中统一落盘
