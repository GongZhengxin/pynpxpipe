# UI 改进计划 — 输入简化 · 默认值对齐 · 文件浏览 · 布局优化

> 状态：**待确认** | 日期：2026-04-09

---

## 0. 调研结论摘要

| 问题 | 结论 |
|------|------|
| 输入路径能否简化？ | ✅ `SessionManager.from_data_dir(data_dir)` 已实现自动发现 `*_g[0-9]*` gate 目录 + 首个 `*.bhv2`，可用单路径替代 |
| UI 默认值与 MATLAB 对齐？ | ⚠️ 发现 1 处明确 bug + 若干覆盖不全（详见 T2） |
| Panel 有文件夹浏览器？ | ✅ `pn.widgets.FileSelector`（服务端文件系统浏览），但 UI 较重，建议 TextInput + Browse 按钮模式 |
| 参数页面能左右分栏？ | ✅ 用 `pn.Row` + `pn.Column` 即可实现，FastListTemplate main 区域支持响应式宽度 |

---

## T1. 输入路径简化 — "data_dir 模式"

### 现状

`SessionForm` 提供 3 个独立 `TextInput`：
- `session_dir`（SpikeGLX gate 目录，如 `D:/data/session_g0`）
- `bhv_file`（BHV2 文件，如 `D:/data/session.bhv2`）
- `output_dir`（输出根目录）

用户须手动分别填写 SpikeGLX 目录和 BHV2 文件路径。

### 发现

`SessionManager.from_data_dir(data_dir, subject, output_dir)` 已实现：
1. 扫描 `data_dir` 下首个 `*_g[0-9]*` 目录 → `session_dir`
2. 扫描 `data_dir` 下首个 `*.bhv2` 文件 → `bhv_file`
3. 多候选时取字母序第一个，发 WARNING

典型目录结构：
```
D:/data/experiment_20260409/          ← data_dir（用户只需指定这一层）
├── session_20260409_g0/              ← 自动发现为 session_dir
│   ├── session_20260409_g0_imec0/
│   │   ├── ...ap.bin / .meta
│   │   └── ...lf.bin / .meta
│   └── session_20260409_g0_t0.nidq.bin / .meta
└── session_20260409.bhv2             ← 自动发现为 bhv_file
```

### 方案

在 `SessionForm` 中新增 **"简易模式 / 高级模式" 切换**：

| 模式 | 可见字段 | 行为 |
|------|---------|------|
| **简易模式**（默认） | `data_dir` + `output_dir` | 填入 `data_dir` 后自动调用发现逻辑，显示发现结果（"Found: session_g0, session.bhv2"） |
| **高级模式** | `session_dir` + `bhv_file` + `output_dir` | 与当前行为一致，手动指定每个路径 |

**细节设计：**
- 切换按钮：`pn.widgets.Toggle(name="高级模式", value=False)`
- 简易模式下 `data_dir` 变更时：
  1. 调用 `SessionManager._discover_gate_dir()` 和 `_discover_bhv_file()` 逻辑（提取为独立函数或直接用 `from_data_dir` 的子逻辑）
  2. 成功 → 显示绿色状态文本："✓ 发现 gate 目录: session_g0 | BHV2: session.bhv2"
  3. 失败 → 显示红色错误："✗ 未找到 *_g[0-9]* 目录" 或 "✗ 未找到 .bhv2 文件"
  4. 成功后自动填充 `state.session_dir` 和 `state.bhv_file`
- 从简易切到高级：保留已发现的值，用户可微调
- 从高级切到简易：如果已有 `session_dir`，尝试推断 `data_dir`（取 parent）

**涉及文件：**
- `src/pynpxpipe/ui/components/session_form.py` — 主要改动
- `src/pynpxpipe/ui/state.py` — 可能新增 `data_dir` 参数（或保持只用 session_dir/bhv_file）
- `tests/test_ui/test_session_form.py` — 新增简易模式测试

**风险：** data_dir 内有多个 gate 目录或多个 bhv2 文件时，自动选择第一个可能不符用户预期。需在状态文本中明确显示选了哪个，并建议切换到高级模式手动指定。

---

## T2. 默认参数对齐（dataclass ↔ YAML ↔ UI ↔ MATLAB）

### 发现的问题

#### 🔴 Bug: SortingForm.template_operators 错误

`sorting_form.py` 中 `_DEFAULT_SORTING` 的 `analyzer.template_operators` 为 `["similarity", "amplitude"]`，
但 dataclass/YAML 默认值为 `["average", "std"]`。

**修复：** 删除 `_DEFAULT_SORTING` 中的自定义 AnalyzerConfig，直接使用 `AnalyzerConfig()` dataclass 默认值。

#### 🟡 UI 未暴露的重要参数

以下参数在 dataclass 中有默认值，但 PipelineForm **完全未暴露**给用户：

| 参数组 | 缺失字段 | 默认值 | 是否应暴露 |
|--------|---------|--------|-----------|
| **preprocess.motion_correction** | method, preset | "dredge", "nonrigid_accurate" | ✅ 应暴露 — 与 KS4 nblocks 互斥，用户需决策 |
| **sync** | sync_bit, event_bits, stim_onset_code 等 | 0, [1..7], 64 | ⚠️ 可选 — 大多数用户用默认值 |
| **curation** | （已暴露 4 项） | — | ✅ 已覆盖 |
| **postprocess** | slay_pre_s, slay_post_s, eye_validation | 0.05s, 0.30s, enabled=True | ⚠️ 可选 — 高级用户场景 |

#### 🟡 MATLAB 对比中的参数差异（已知设计决策，需确认 UI 展示）

| 参数 | MATLAB | Python 默认 | UI 显示 | 说明 |
|------|--------|------------|---------|------|
| nblocks | 5 | 15 | ✅ 显示 15 | Python 有意改进，UI 已正确展示 |
| Th_learned | 7.0 | 7.0 | ✅ 显示 7.0 | 一致 |
| do_CAR | false | false | ✅ 显示 | 一致（preprocessing 已做 CMR） |
| bandpass | 300 Hz 仅高通 | 300-6000 Hz | ✅ 显示 | Python 有意改进 |
| motion_correction | 无 | dredge | ❌ 未显示 | **需加入 UI** |
| bad_channel method | — | "coherence+psd" | ✅ 显示 | — |
| dead_channel_threshold | — | 0.5 | ✅ 显示 | — |

### 修复方案

**P0（必须修复）：**
1. 修复 `_DEFAULT_SORTING` 中 `template_operators` 的错误值

**P1（推荐改进）：**
2. PipelineForm 新增 **Motion Correction** 卡片（method: select["dredge", "kilosort", "none"], preset: select["rigid_fast", "nonrigid_accurate"]）
3. 在 Motion Correction 卡片中加互斥提示：当 method="dredge" 时提示 "建议 KS4 nblocks=0"；当 method=None 时提示 "建议 KS4 nblocks≥1"

**P2（可选增强）：**
4. 新增 Sync 参数卡片（collapsed=True，仅高级用户展开）
5. 新增 Postprocess 参数卡片（collapsed=True）

**涉及文件：**
- `src/pynpxpipe/ui/components/sorting_form.py` — 修复 bug
- `src/pynpxpipe/ui/components/pipeline_form.py` — 新增 Motion Correction 卡片
- 对应测试文件

---

## T3. 文件浏览器功能

### Panel FileSelector 评估

`pn.widgets.FileSelector` 是 Panel 内置的 **服务端文件系统浏览器**：
- 双面板 UI（左侧浏览 / 右侧已选）
- 支持 `directory` 起始路径、`root_directory` 限制范围、`file_pattern` 过滤
- 可选文件和文件夹（`only_files=False`）
- **缺点：** UI 较重（占用大量垂直空间），sizing 有已知 bug

### 方案：TextInput + Browse 按钮 + 可折叠 FileSelector

为以下 3 个路径输入添加 "Browse" 按钮：

| 输入 | FileSelector 配置 | file_pattern |
|------|-------------------|-------------|
| data_dir / session_dir | `only_files=False` | `*`（浏览目录） |
| bhv_file（高级模式） | `only_files=True` | `*.bhv2` |
| output_dir | `only_files=False` | `*`（浏览目录） |

**额外场景：Subject YAML 加载**
| 输入 | FileSelector 配置 | file_pattern |
|------|-------------------|-------------|
| subject_yaml | `only_files=True` | `*.yaml` |

**交互流程：**
```
[TextInput: /path/to/data] [Browse 按钮]
                              ↓ 点击
                 [FileSelector 面板展开]
                 用户选择目录/文件后
                 → TextInput 自动填充
                 → FileSelector 自动折叠
```

**实现方案：**
- 封装 `BrowsableInput` 可复用组件（`pn.viewable.Viewer` 子类）
- 参数：`name`, `placeholder`, `file_pattern`, `only_files`, `root_directory`
- 内部组合：`TextInput` + `Button("Browse")` + `FileSelector`（初始隐藏）
- Browse 点击 → toggle `FileSelector.visible`
- FileSelector.value 变更 → 取 `value[0]` 填入 TextInput → 隐藏 FileSelector

**涉及文件：**
- `src/pynpxpipe/ui/components/browsable_input.py` — 新建可复用组件
- `src/pynpxpipe/ui/components/session_form.py` — TextInput → BrowsableInput
- `src/pynpxpipe/ui/components/subject_form.py` — 添加 YAML 文件选择
- `src/pynpxpipe/ui/components/session_loader.py` — TextInput → BrowsableInput
- 对应测试文件

---

## T4. 参数页面左右分栏布局

### 现状

Configure 页面所有表单垂直堆叠在单个 `Column` 中：
```
SessionForm
SubjectForm
PipelineForm (4 cards stacked)
SortingForm
StageSelector
```

在宽屏显示器上浪费大量水平空间，且滚动距离长。

### 方案：两列布局

```
┌─────────────────────────────────────────────────────┐
│                    Configure                        │
├──────────────────────┬──────────────────────────────┤
│  LEFT COLUMN (50%)   │  RIGHT COLUMN (50%)          │
│                      │                              │
│  ┌────────────────┐  │  ┌────────────────────────┐  │
│  │ Session Paths  │  │  │ Pipeline Config         │  │
│  │ (data_dir +    │  │  │ ┌ Bandpass ──────────┐  │  │
│  │  output_dir)   │  │  │ │ freq_min, freq_max │  │  │
│  └────────────────┘  │  │ └────────────────────┘  │  │
│                      │  │ ┌ Bad Channel & CMR ──┐  │  │
│  ┌────────────────┐  │  │ │ method, threshold  │  │  │
│  │ Subject Meta   │  │  │ │ reference, operator│  │  │
│  │ (id, species,  │  │  │ └────────────────────┘  │  │
│  │  sex, age,     │  │  │ ┌ Motion Correction ─┐  │  │
│  │  weight)       │  │  │ │ method, preset     │  │  │
│  └────────────────┘  │  │ └────────────────────┘  │  │
│                      │  │ ┌ Resources ─────────┐  │  │
│  ┌────────────────┐  │  │ │ n_jobs, chunk, mem │  │  │
│  │ Stage Selector │  │  │ └────────────────────┘  │  │
│  │ ☑ discover     │  │  │ ┌ Curation ─────────┐  │  │
│  │ ☑ preprocess   │  │  │ │ isi, amp, pres,   │  │  │
│  │ ☑ sort         │  │  │ │ snr               │  │  │
│  │ ☑ synchronize  │  │  │ └────────────────────┘  │  │
│  │ ☑ curate       │  │  └────────────────────────┘  │
│  │ ☑ postprocess  │  │                              │
│  │ ☑ export       │  │  ┌────────────────────────┐  │
│  └────────────────┘  │  │ Sorting Config         │  │
│                      │  │ sorter, mode, nblocks, │  │
│                      │  │ Th_learned, do_CAR,    │  │
│                      │  │ batch_size, n_jobs     │  │
│                      │  └────────────────────────┘  │
└──────────────────────┴──────────────────────────────┘
```

**分栏逻辑：**
- **左栏**：会话相关（输入输出路径、受试者信息、阶段选择）— 通常只设置一次
- **右栏**：算法参数（预处理、排序配置）— 需要反复调整

**实现：**
```python
configure_section = pn.Row(
    pn.Column(session_form.panel(), subject_form.panel(), stage_selector.panel(),
              sizing_mode="stretch_width"),
    pn.Column(pipeline_form.panel(), sorting_form.panel(),
              sizing_mode="stretch_width"),
    sizing_mode="stretch_width",
)
```

**涉及文件：**
- `src/pynpxpipe/ui/app.py` — 修改 Configure section 布局
- 各组件的 `panel()` 方法可能需要调整 `sizing_mode`
- 对应测试文件（布局测试）

---

## 实施顺序与依赖关系

```
T2 (默认值修复)  ←── 无依赖，最简单，先做
    ↓
T1 (输入简化)    ←── 独立于 T3/T4
    ↓
T3 (文件浏览器)  ←── 依赖 T1（BrowsableInput 用于简易模式的 data_dir）
    ↓
T4 (布局优化)    ←── 最后做（T1/T3 改变了组件结构，布局需适配最终形态）
```

### 建议的 Session 拆分

| Session | 任务 | 改动文件数 | 估计测试数 |
|---------|------|-----------|-----------|
| **S1** | T2: 修复 sorting_form bug + 新增 motion_correction 卡片 | 3 | ~10 |
| **S2** | T1: SessionForm 简易/高级模式 | 3 | ~12 |
| **S3** | T3: BrowsableInput 组件 + 集成到各表单 | 5 | ~15 |
| **S4** | T4: app.py 两列布局 + sizing 调整 | 2-3 | ~5 |

---

## 决议记录（2026-04-09 用户确认）

1. **简易模式作为默认** ✅
2. **Sync/Postprocess 参数作为折叠卡片暴露**（默认收起） ✅
3. **采用左右分栏布局** ✅
4. **BrowsableInput 默认起始目录：pynpxpipe 项目所在目录**（即 `Path(__file__).resolve().parents[N]` 或通过配置传入） ✅
5. **实施优先级 T2 → T1 → T3 → T4** ✅
