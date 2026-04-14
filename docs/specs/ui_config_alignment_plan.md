# UI Config Alignment Implementation Plan

> **For agentic workers:** Execute task-by-task. Steps use checkbox (`- [ ]`) syntax. Subagent dispatch points are marked **[SUBAGENT]**. Main agent synthesizes subagent output and runs all Edit/Write operations.

**Goal:** 系统修正 `pipeline_form.py` 与 `core/config.py` 的字段漂移，并升级 `docs/specs/ui.md` 为权威规格；新增 16 个缺失 widget + 1 个防漂移 harness 测试。

**Architecture:** Spec-first → TDD (per-group RED/GREEN) → 防漂移 harness → lint。`core/config.py` 的 dataclass 字段为 single source of truth；UI spec 和 widget 表两侧对齐。

**Tech Stack:** Panel 1.x + param, pytest, ruff, core/config.py 现有 dataclass（不新增 dataclass）。

**Scope constraint:** 只修 `ui.md`、`pipeline_form.py`、`sorting_form.py`、`test_components.py`、`progress.md`。不动 `core/config.py`、不拆分 `pipeline_form.py` 成多文件。`sorting_form.py` 新增 `AnalyzerConfig` 的 7 个字段 widget（随 scope expansion 2026-04-14 加入）。

---

## Ground Truth Manifest

### Missing fields (from `core/config.py`) — 16 个 widget 缺口

| Group | Field | Type | Default | Widget 类型 | 说明 |
|-------|-------|------|---------|-----------|------|
| **Parallel (新 Card)** | `enabled` | bool | False | Checkbox | 多探针并行开关 |
| | `max_workers` | int\|"auto" | "auto" | TextInput(auto/int) | ProcessPoolExecutor worker 数 |
| **Curation** | `good_isi_max` | float | 0.1 | FloatInput | SUA ISI 上限（手动模式） |
| | `good_snr_min` | float | 3.0 | FloatInput | SUA SNR 下限（手动模式） |
| | `use_bombcell` | bool | True | Checkbox | Bombcell 四分类开关 |
| **Sync** | `nidq_sync_bit` | int(0–7) | 0 | IntInput | NIDQ 数字词 sync bit |
| | `max_time_error_ms` | float(>0) | 17.0 | FloatInput | IMEC↔NIDQ 最大对齐误差 |
| | `trial_count_tolerance` | int(≥0) | 2 | IntInput | trial 计数容差 |
| | `photodiode_channel_index` | int(≥0) | 0 | IntInput | NIDQ 光电二极管模拟通道索引 |
| | `gap_threshold_ms` | float\|None | 1200.0 | Checkbox+FloatInput | 丢脉冲检测阈值（可禁用） |
| | `trial_start_bit` | int\|None | None | Checkbox+IntInput | 可选 trial start bit |
| | `pd_window_pre_ms` | float | 10.0 | FloatInput | 光电二极管基线窗口 |
| | `pd_window_post_ms` | float | 100.0 | FloatInput | 光电二极管检测窗口 |
| | `pd_min_signal_variance` | float | 1e-6 | FloatInput | 无信号判定方差 |
| **Postprocess** | `pre_onset_ms` | float | 50.0 | FloatInput | 动态 SLAy 窗口前置时间 |
| **Merge (新 Card)** | `enabled` | bool | False | Checkbox | 自动合并开关（默认关） |
| **Analyzer → RandomSpikes** (sorting_form) | `max_spikes_per_unit` | int(≥1) | 500 | IntInput | 每单元随机采样上限 |
| | `method` | str | "uniform" | Select(uniform/all/smart) | 采样方法 |
| **Analyzer → Waveforms** (sorting_form) | `ms_before` | float(>0) | 1.0 | FloatInput | 波形前置窗口 |
| | `ms_after` | float(>0) | 2.0 | FloatInput | 波形后置窗口 |
| **Analyzer** (sorting_form) | `template_operators` | list[str] | ["average","std"] | MultiChoice | 模板算子 |
| | `unit_locations_method` | str | "monopolar_triangulation" | Select | 单元空间定位方法 |
| | `template_similarity_method` | str | "cosine_similarity" | Select | 模板相似度方法 |

### Rename / 修正（已有 widget）

- `sync_bit_input` → 明确重命名 name 为 `"IMEC Sync Bit"`（现为 `"Sync Bit"`），避免和新增 `nidq_sync_bit` 混淆。
- Curation 四个现有 widget 的 `description` 文案错误（例如 `snr_min` 描述"Typical: 5.0"但默认 0.3），改写为"NOISE filter lower bound — 保留所有 SNR 大于该值的单元（bombcell 模式极宽松）"。

### Null 字段的 widget 设计模式

对 `gap_threshold_ms` (float|None) 和 `trial_start_bit` (int|None)：
- 一个 `Checkbox`（name=`"Enable X"`）+ 一个数值输入。
- Checkbox 未勾选 → config 字段 = None，数值输入 disabled。
- Checkbox 勾选 → config 字段 = 数值输入当前值。

---

## Development Flow (TDD + Harness)

```
Phase 1: Spec correction
  ├── [SUBAGENT × 1] 起草 ui.md §3.5 + §3.6 替换文本
  ├── Main: Edit ui.md
  └── Commit: docs(specs): align ui.md §3.5/§3.6 with core/config.py

Phase 2: TDD-RED (tests first)
  ├── [SUBAGENT × 4] 并行起草 4 组测试代码（返回文本）
  │     A: Parallel + Merge (新 Card)
  │     B: Curation 新字段
  │     C: Sync 新字段 (9 个)
  │     D: Postprocess 新字段 + 描述文案修正
  ├── Main: 汇总追加到 test_components.py
  ├── Main: pytest tests/test_ui/test_components.py -v → 预期 FAIL
  └── (不 commit — 避免 CI 红)

Phase 3: TDD-GREEN (implementation)
  ├── Group-by-group sequential edits on pipeline_form.py（主 agent）
  │   For each of {Parallel, Curation, Sync, Postprocess, Merge}:
  │     ├── Edit pipeline_form.py: 加 widget + 加到 all_widgets + 加 Card + 加 _rebuild_config 分支
  │     ├── pytest -k <group> → 预期 PASS
  │     └── Commit: feat(ui): add <group> widgets to PipelineForm
  └── Commit: feat(ui): rename imec_sync_bit widget label

Phase 4: Harness (防漂移测试)
  ├── [SUBAGENT × 1] 起草 harness 测试代码（元测试）
  ├── Main: 追加到 test_components.py
  ├── Main: pytest -k coverage → PASS
  └── Commit: test(ui): add pipeline_form config coverage harness

Phase 5: Lint + 全量回归
  ├── uv run ruff check src/pynpxpipe/ui/ tests/test_ui/
  ├── uv run ruff format src/pynpxpipe/ui/ tests/test_ui/
  ├── uv run pytest tests/test_ui/ -v
  └── 若有格式变更 → Commit: style(ui): ruff format

Phase 6: Progress update
  ├── Edit docs/progress.md (新增 UI S5 行)
  └── Commit: docs(progress): mark UI S5 — config alignment complete

Phase 7: (Optional) code-reviewer agent 审查
```

**关键原则**：
- 每个 Phase 的 subagent **只返回文本**，不直接 Write/Edit（避免权限与冲突，参考 memory `feedback_parallel_agents_write.md`）。
- Commit 粒度细：每个 group 一个 commit，便于 review 和回滚。
- Tests 与 implementation 同 Phase 但分 commit：TDD-RED 在本地验证失败后**不 commit**，GREEN 时 tests + impl 一起 commit。

---

## Task 1 — Phase 1: Spec Correction

**Files:**
- Modify: `docs/specs/ui.md` §3.5 (lines 124–140), §3.6 (lines 143–155)

- [ ] **Step 1.1: 派发 subagent 起草新 spec 文本**

Dispatch **1 Explore subagent**（返回 markdown 文本，不写文件）：

```
Prompt 要点：
- 读 docs/specs/ui.md 现有 §3.5 和 §3.6
- 读 src/pynpxpipe/core/config.py 的 ResourcesConfig, ParallelConfig, BandpassConfig,
  BadChannelConfig, CommonReferenceConfig, MotionCorrectionConfig, CurationConfig,
  SyncConfig, PostprocessConfig, EyeValidationConfig, MergeConfig, SorterParams, SortingConfig
- 产出全新的 §3.5 "pipeline_form.py — Pipeline 参数面板" markdown 章节，包括：
  * 分组表（Resources / Parallel / Bandpass / BadChannel / CommonRef / Motion /
    Curation / Sync / Postprocess / Merge），每行列出所有字段 + Widget 类型 + 默认 + 约束
  * 对 nullable 字段（gap_threshold_ms, trial_start_bit）说明 "Checkbox + 数值" 的模式
  * 对 "auto|int" 字段（n_jobs, max_workers, batch_size）说明 Switch + 数值的模式
  * 明确 "Sync Bit" 分成 imec_sync_bit 和 nidq_sync_bit 两个独立 widget
- 产出全新的 §3.6 "sorting_form.py — Sorting 参数面板" markdown 章节（analyzer 子配置
  标注为 "默认固定值，不暴露"，不列入表）
- 不改其他章节（§1-§2, §3.1-§3.4, §3.7-§3.11, §4-§8）
- 返回两段 markdown，用分隔符 "===§3.5===" "===§3.6===" 标记
- 不要写入文件
```

- [ ] **Step 1.2: Main agent 应用 Edit**

```
Read docs/specs/ui.md 对应区段确认 old_string
Edit docs/specs/ui.md 替换 §3.5
Edit docs/specs/ui.md 替换 §3.6
```

- [ ] **Step 1.3: 用户 review spec（checkpoint）**

暂停，让用户确认 spec 对齐 core/config.py。

- [ ] **Step 1.4: Commit**

```bash
git add docs/specs/ui.md
git commit -m "docs(specs): align ui.md with core/config.py field inventory"
```

---

## Task 2 — Phase 2: TDD-RED (write failing tests)

**Files:**
- Modify: `tests/test_ui/test_components.py` (append after line ~535, before sorting_form tests)

- [ ] **Step 2.1: 并行派发 4 个 subagent 起草测试代码**

**[SUBAGENT × 4 并行]** 在一条消息中发出 4 个 Agent 调用（subagent_type=general-purpose）。

每个 subagent 只返回 **Python 测试函数源码文本**。每个函数必须：
- 使用现有 `AppState()` + `PipelineForm(state)` 构造模式
- 断言 widget 存在（`hasattr(form, <attr_name>)`）
- 断言默认值与 `PipelineConfig()` 子配置的默认值一致
- 断言修改 widget 后 `state.pipeline_config.<path>` 反映新值
- 断言 widget 的 `start`/`end`/约束合法

**Subagent A — Parallel + Merge groups** (返回 6 个 test 函数源码):
```python
test_pipeline_form_has_parallel_widgets()
test_pipeline_form_parallel_defaults()
test_pipeline_form_parallel_enable_updates_state()
test_pipeline_form_parallel_max_workers_auto_mode()
test_pipeline_form_has_merge_widget()
test_pipeline_form_merge_default_disabled()
```

**Subagent B — Curation 新字段** (返回 6 个 test 函数源码):
```python
test_pipeline_form_has_use_bombcell_widget()
test_pipeline_form_use_bombcell_default_true()
test_pipeline_form_has_good_isi_max_widget()
test_pipeline_form_has_good_snr_min_widget()
test_pipeline_form_curation_manual_thresholds_propagate()
test_pipeline_form_toggle_bombcell_updates_state()
```

**Subagent C — Sync 新字段** (返回 12 个 test 函数源码):
```python
test_pipeline_form_has_nidq_sync_bit_widget()
test_pipeline_form_imec_sync_bit_widget_renamed()
test_pipeline_form_has_max_time_error_widget()
test_pipeline_form_has_trial_count_tolerance_widget()
test_pipeline_form_has_photodiode_channel_index_widget()
test_pipeline_form_has_gap_threshold_widget()
test_pipeline_form_gap_threshold_nullable_checkbox_disable()
test_pipeline_form_has_trial_start_bit_widget()
test_pipeline_form_trial_start_bit_default_none()
test_pipeline_form_has_pd_window_pre_ms_widget()
test_pipeline_form_has_pd_window_post_ms_widget()
test_pipeline_form_has_pd_min_signal_variance_widget()
```

**Subagent D — Postprocess + Curation 描述文案** (返回 3 个 test 函数源码):
```python
test_pipeline_form_has_pre_onset_ms_widget()
test_pipeline_form_pre_onset_ms_default()
test_pipeline_form_curation_descriptions_reference_noise_semantics()
```

- [ ] **Step 2.2: Main agent 汇总 subagent 返回文本，写入 test_components.py**

```
Read tests/test_ui/test_components.py (确认当前结尾)
Edit tests/test_ui/test_components.py 在 sorting_form 测试前插入新测试块
```

- [ ] **Step 2.3: Run RED verification**

```bash
uv run pytest tests/test_ui/test_components.py -v -k "parallel or merge or bombcell or good_isi or good_snr or nidq_sync or max_time_error or trial_count or photodiode_channel or gap_threshold or trial_start_bit or pd_window or pd_min or pre_onset or noise_semantics or imec_sync_bit_widget_renamed"
```

Expected: 27 个新 test 全部 FAIL，原因为 `AttributeError: 'PipelineForm' object has no attribute '<name>'`。

- [ ] **Step 2.4: 不 commit**

保持工作树 dirty，下一步同 commit 推入 impl + tests。

---

## Task 3 — Phase 3: TDD-GREEN, Group 1 — Parallel Card

**Files:**
- Modify: `src/pynpxpipe/ui/components/pipeline_form.py`

- [ ] **Step 3.1: 加 import**

Edit `src/pynpxpipe/ui/components/pipeline_form.py` 顶部 import 块：

```python
from pynpxpipe.core.config import (
    BadChannelConfig,
    BandpassConfig,
    CommonReferenceConfig,
    CurationConfig,
    EyeValidationConfig,
    MergeConfig,           # ← 新增
    MotionCorrectionConfig,
    ParallelConfig,        # ← 新增
    PipelineConfig,
    PostprocessConfig,
    PreprocessConfig,
    ResourcesConfig,
    SyncConfig,
)
```

- [ ] **Step 3.2: 加 Parallel widgets（在 Resources 之后，Bandpass 之前）**

```python
# ── Parallel ──
self.parallel_enabled_checkbox = pn.widgets.Checkbox(
    name="Enable multi-probe parallelism (ProcessPoolExecutor)",
    value=_DEFAULTS.parallel.enabled,
)
self.parallel_max_workers_input = pn.widgets.TextInput(
    name="Max Workers",
    value=str(_DEFAULTS.parallel.max_workers),
    description="Worker count. 'auto' = ResourceDetector recommends based on free RAM.",
)
```

- [ ] **Step 3.3: 加入 all_widgets 列表**

将 `self.parallel_enabled_checkbox`, `self.parallel_max_workers_input` 加到 `all_widgets`。

- [ ] **Step 3.4: 加 `_rebuild_config` 分支**

在 `_rebuild_config` 中解析 parallel fields，传入 `dataclasses.replace` 的 `parallel=ParallelConfig(...)`：

```python
max_workers_raw = self.parallel_max_workers_input.value
try:
    max_workers = int(max_workers_raw)
except (ValueError, TypeError):
    max_workers = max_workers_raw or "auto"
# ...
parallel=ParallelConfig(
    enabled=self.parallel_enabled_checkbox.value,
    max_workers=max_workers,
),
```

- [ ] **Step 3.5: 加 Parallel Card 到 `panel()`**

在 Resources Card 之后插入：

```python
pn.Card(
    self.parallel_enabled_checkbox,
    self.parallel_max_workers_input,
    title="Parallel (multi-probe)",
    collapsed=True,
),
```

- [ ] **Step 3.6: Run tests**

```bash
uv run pytest tests/test_ui/test_components.py -v -k "parallel"
```

Expected: 4 PASS.

- [ ] **Step 3.7: Commit**

```bash
git add src/pynpxpipe/ui/components/pipeline_form.py tests/test_ui/test_components.py
git commit -m "feat(ui): add Parallel config card to PipelineForm"
```

---

## Task 4 — Phase 3: TDD-GREEN, Group 2 — Curation 扩展

**Files:**
- Modify: `src/pynpxpipe/ui/components/pipeline_form.py`

- [ ] **Step 4.1: 加 3 个 widget**

```python
# ── Curation 扩展 ──
self.use_bombcell_checkbox = pn.widgets.Checkbox(
    name="Use Bombcell four-class classification (SUA/MUA/NON-SOMA/NOISE)",
    value=_DEFAULTS.curation.use_bombcell,
)
self.good_isi_max_input = pn.widgets.FloatInput(
    name="Good ISI Max (SUA threshold, manual mode)",
    value=_DEFAULTS.curation.good_isi_max,
    step=0.01,
    description="ISI violation ratio upper bound for SUA classification (fallback when use_bombcell=False).",
)
self.good_snr_min_input = pn.widgets.FloatInput(
    name="Good SNR Min (SUA threshold, manual mode)",
    value=_DEFAULTS.curation.good_snr_min,
    step=0.5,
    description="SNR lower bound for SUA classification (fallback when use_bombcell=False).",
)
```

- [ ] **Step 4.2: 修正 4 个现有 Curation widget 的 description**

```python
# isi_max_input.description:
"NOISE filter upper bound. Units with ISI violation ratio above this are discarded. "
"Default 2.0 is permissive (bombcell handles SUA classification separately)."

# amp_cutoff_input.description:
"NOISE filter upper bound for amplitude cutoff. Default 0.5 is permissive."

# presence_min_input.description:
"NOISE filter lower bound. Units present in < this fraction of recording are discarded. "
"Default 0.5 keeps units appearing in ≥50% of bins."

# snr_min_input.description:
"NOISE filter lower bound for SNR. Default 0.3 is very permissive (bombcell handles SUA)."
```

- [ ] **Step 4.3: 加入 all_widgets + `_rebuild_config` 分支**

```python
curation=CurationConfig(
    isi_violation_ratio_max=self.isi_max_input.value,
    amplitude_cutoff_max=self.amp_cutoff_input.value,
    presence_ratio_min=self.presence_min_input.value,
    snr_min=self.snr_min_input.value,
    good_isi_max=self.good_isi_max_input.value,
    good_snr_min=self.good_snr_min_input.value,
    use_bombcell=self.use_bombcell_checkbox.value,
),
```

- [ ] **Step 4.4: 加入 Curation Card 的 widget 列表**

```python
pn.Card(
    self.use_bombcell_checkbox,
    self.isi_max_input,
    self.amp_cutoff_input,
    self.presence_min_input,
    self.snr_min_input,
    self.good_isi_max_input,
    self.good_snr_min_input,
    title="Curation Thresholds",
    collapsed=True,
),
```

- [ ] **Step 4.5: Run tests**

```bash
uv run pytest tests/test_ui/test_components.py -v -k "bombcell or good_isi or good_snr or noise_semantics"
```

Expected: 7 PASS.

- [ ] **Step 4.6: Commit**

```bash
git add src/pynpxpipe/ui/components/pipeline_form.py tests/test_ui/test_components.py
git commit -m "feat(ui): expose use_bombcell and good_* curation thresholds"
```

---

## Task 5 — Phase 3: TDD-GREEN, Group 3 — Sync 扩展

**Files:**
- Modify: `src/pynpxpipe/ui/components/pipeline_form.py`

- [ ] **Step 5.1: 重命名现有 `sync_bit_input` 的 name**

```python
# self.sync_bit_input 保留 attribute 名不变，但 widget name 改为 "IMEC Sync Bit"
self.sync_bit_input = pn.widgets.IntInput(
    name="IMEC Sync Bit",  # 原 "Sync Bit"
    ...
)
```

- [ ] **Step 5.2: 新增 9 个 Sync widget**

```python
self.nidq_sync_bit_input = pn.widgets.IntInput(
    name="NIDQ Sync Bit",
    value=_sync.nidq_sync_bit,
    start=0, end=7,
    description="Bit position of sync pulse in NIDQ digital word (wiring-dependent, typically 0).",
)
self.max_time_error_input = pn.widgets.FloatInput(
    name="Max Time Error (ms)",
    value=_sync.max_time_error_ms,
    start=0.0, step=1.0,
    description="Maximum allowed IMEC↔NIDQ alignment residual. Alignment fails above this.",
)
self.trial_count_tolerance_input = pn.widgets.IntInput(
    name="Trial Count Tolerance",
    value=_sync.trial_count_tolerance,
    start=0,
    description="Maximum BHV2↔NIDQ trial count mismatch auto-repaired via padding/trimming.",
)
self.photodiode_channel_input = pn.widgets.IntInput(
    name="Photodiode Channel Index",
    value=_sync.photodiode_channel_index,
    start=0,
    description="NIDQ analog channel index for the photodiode signal.",
)
# Nullable: gap_threshold_ms
self.gap_threshold_enable_checkbox = pn.widgets.Checkbox(
    name="Enable Dropped-Pulse Gap Detection",
    value=_sync.gap_threshold_ms is not None,
)
self.gap_threshold_input = pn.widgets.FloatInput(
    name="Gap Threshold (ms)",
    value=_sync.gap_threshold_ms if _sync.gap_threshold_ms is not None else 1200.0,
    start=0.0, step=50.0,
    disabled=_sync.gap_threshold_ms is None,
    description="Intervals above this are flagged as dropped pulses for repair.",
)
# Nullable: trial_start_bit
self.trial_start_bit_enable_checkbox = pn.widgets.Checkbox(
    name="Enable Explicit Trial Start Bit",
    value=_sync.trial_start_bit is not None,
)
self.trial_start_bit_input = pn.widgets.IntInput(
    name="Trial Start Bit",
    value=_sync.trial_start_bit if _sync.trial_start_bit is not None else 0,
    start=0, end=7,
    disabled=_sync.trial_start_bit is None,
    description="Optional NIDQ bit marking trial start (leave disabled to infer from event codes).",
)
self.pd_window_pre_input = pn.widgets.FloatInput(
    name="PD Window Pre (ms)",
    value=_sync.pd_window_pre_ms,
    start=0.0, step=1.0,
    description="Baseline window before photodiode event for calibration.",
)
self.pd_window_post_input = pn.widgets.FloatInput(
    name="PD Window Post (ms)",
    value=_sync.pd_window_post_ms,
    start=0.0, step=5.0,
    description="Detection window after photodiode event for calibration.",
)
self.pd_min_variance_input = pn.widgets.FloatInput(
    name="PD Min Signal Variance",
    value=_sync.pd_min_signal_variance,
    start=0.0, step=1e-6,
    description="Below this variance the photodiode channel is treated as absent (skip calibration).",
)
```

- [ ] **Step 5.3: Watch checkboxes 控制 nullable disable 状态**

```python
self.gap_threshold_enable_checkbox.param.watch(
    lambda e: setattr(self.gap_threshold_input, "disabled", not e.new),
    "value",
)
self.trial_start_bit_enable_checkbox.param.watch(
    lambda e: setattr(self.trial_start_bit_input, "disabled", not e.new),
    "value",
)
```

- [ ] **Step 5.4: 加入 all_widgets + `_rebuild_config` 构建 SyncConfig**

```python
gap_threshold_ms = (
    self.gap_threshold_input.value
    if self.gap_threshold_enable_checkbox.value
    else None
)
trial_start_bit = (
    self.trial_start_bit_input.value
    if self.trial_start_bit_enable_checkbox.value
    else None
)
# ...
sync=SyncConfig(
    imec_sync_bit=self.sync_bit_input.value,
    nidq_sync_bit=self.nidq_sync_bit_input.value,
    event_bits=event_bits,
    max_time_error_ms=self.max_time_error_input.value,
    trial_count_tolerance=self.trial_count_tolerance_input.value,
    photodiode_channel_index=self.photodiode_channel_input.value,
    monitor_delay_ms=self.monitor_delay_input.value,
    stim_onset_code=self.stim_onset_code_input.value,
    imec_sync_code=self.imec_sync_code_input.value,
    generate_plots=self.generate_plots_checkbox.value,
    gap_threshold_ms=gap_threshold_ms,
    trial_start_bit=trial_start_bit,
    pd_window_pre_ms=self.pd_window_pre_input.value,
    pd_window_post_ms=self.pd_window_post_input.value,
    pd_min_signal_variance=self.pd_min_variance_input.value,
),
```

- [ ] **Step 5.5: 更新 Sync Card widget 顺序**

按语义分组排序：clock sync → event/trial → photodiode → plots。

- [ ] **Step 5.6: Run tests**

```bash
uv run pytest tests/test_ui/test_components.py -v -k "nidq_sync or max_time_error or trial_count or photodiode_channel or gap_threshold or trial_start_bit or pd_window or pd_min or imec_sync_bit_widget_renamed"
```

Expected: 12 PASS.

- [ ] **Step 5.7: Commit**

```bash
git add src/pynpxpipe/ui/components/pipeline_form.py tests/test_ui/test_components.py
git commit -m "feat(ui): expose full SyncConfig (9 new widgets + imec/nidq disambiguation)"
```

---

## Task 6 — Phase 3: TDD-GREEN, Group 4 — Postprocess + Merge

**Files:**
- Modify: `src/pynpxpipe/ui/components/pipeline_form.py`

- [ ] **Step 6.1: 加 pre_onset_ms widget**

```python
self.pre_onset_ms_input = pn.widgets.FloatInput(
    name="Pre-onset (ms)",
    value=_DEFAULTS.postprocess.pre_onset_ms,
    step=5.0,
    description="Dynamic SLAY window pre-stimulus margin (pre_s = pre_onset_ms / 1000).",
)
```

- [ ] **Step 6.2: 加 merge.enabled widget（新 Card）**

```python
# ── Merge ──
self.merge_enabled_checkbox = pn.widgets.Checkbox(
    name="Enable auto-merge stage (irreversible; review sorting quality first)",
    value=_DEFAULTS.merge.enabled,
)
```

- [ ] **Step 6.3: 加入 all_widgets + `_rebuild_config`**

```python
postprocess=PostprocessConfig(
    slay_pre_s=self.slay_pre_input.value,
    slay_post_s=self.slay_post_input.value,
    pre_onset_ms=self.pre_onset_ms_input.value,
    eye_validation=EyeValidationConfig(
        enabled=self.eye_enabled_checkbox.value,
        eye_threshold=self.eye_threshold_input.value,
    ),
),
merge=MergeConfig(enabled=self.merge_enabled_checkbox.value),
```

- [ ] **Step 6.4: 更新 Postprocess Card + 新增 Merge Card**

```python
pn.Card(
    self.slay_pre_input,
    self.slay_post_input,
    self.pre_onset_ms_input,   # ← 新增
    self.eye_enabled_checkbox,
    self.eye_threshold_input,
    title="Postprocessing",
    collapsed=True,
),
pn.Card(
    self.merge_enabled_checkbox,
    title="Auto-Merge (opt-in, irreversible)",
    collapsed=True,
),
```

- [ ] **Step 6.5: Run tests**

```bash
uv run pytest tests/test_ui/test_components.py -v -k "pre_onset or merge"
```

Expected: 4 PASS.

- [ ] **Step 6.6: Commit**

```bash
git add src/pynpxpipe/ui/components/pipeline_form.py tests/test_ui/test_components.py
git commit -m "feat(ui): add pre_onset_ms and merge.enabled widgets"
```

---

## Task 6.5 — Phase 3: TDD-GREEN, Group 5 — Sorting Analyzer Widgets

**Files:**
- Modify: `src/pynpxpipe/ui/components/sorting_form.py`

**Ground truth — AnalyzerConfig (7 fields)：**
- `random_spikes.max_spikes_per_unit: int = 500` (≥1)
- `random_spikes.method: str = "uniform"` options: `["uniform", "all", "smart"]`
- `waveforms.ms_before: float = 1.0` (>0)
- `waveforms.ms_after: float = 2.0` (>0)
- `template_operators: list[str] = ["average", "std"]` MultiChoice from `["average", "std", "median"]`
- `unit_locations_method: str = "monopolar_triangulation"` options: `["monopolar_triangulation", "center_of_mass", "grid_convolution"]`
- `template_similarity_method: str = "cosine_similarity"` options: `["cosine_similarity", "l1", "l2"]`

- [ ] **Step 6.5.1: 派发 subagent 起草测试**

**[SUBAGENT × 1]** 起草 9 个测试函数（返回源码文本）：
```
test_sorting_form_has_analyzer_widgets()
test_sorting_form_analyzer_random_spikes_defaults()
test_sorting_form_analyzer_waveforms_defaults()
test_sorting_form_analyzer_template_operators_default()
test_sorting_form_analyzer_unit_locations_method_default()
test_sorting_form_analyzer_template_similarity_method_default()
test_sorting_form_analyzer_change_updates_state()
test_sorting_form_has_analyzer_card()
test_sorting_form_analyzer_method_select_options()
```

- [ ] **Step 6.5.2: 追加测试到 test_components.py，跑 RED 验证**

```bash
uv run pytest tests/test_ui/test_components.py -v -k "analyzer"
```

Expected: 9 FAIL (missing attributes).

- [ ] **Step 6.5.3: 编辑 sorting_form.py — import 扩展**

```python
from pynpxpipe.core.config import (
    AnalyzerConfig,
    ImportConfig,
    RandomSpikesConfig,
    SorterConfig,
    SorterParams,
    SortingConfig,
    WaveformConfig,
)
```

- [ ] **Step 6.5.4: 加 7 个 analyzer widget**

```python
_DEFAULT_ANALYZER = AnalyzerConfig()

# ── Analyzer: Random Spikes ──
self.analyzer_max_spikes_input = pn.widgets.IntInput(
    name="Max Spikes Per Unit",
    value=_DEFAULT_ANALYZER.random_spikes.max_spikes_per_unit,
    start=1,
    description="Max spikes sampled per unit for SortingAnalyzer. Lower = faster postprocess, less accurate templates.",
)
self.analyzer_random_method_select = pn.widgets.Select(
    name="Random Spikes Method",
    options=["uniform", "all", "smart"],
    value=_DEFAULT_ANALYZER.random_spikes.method,
    description="'uniform' = random sample. 'all' = use every spike (slow). 'smart' = stratified by firing rate.",
)

# ── Analyzer: Waveforms ──
self.analyzer_ms_before_input = pn.widgets.FloatInput(
    name="Waveform ms_before",
    value=_DEFAULT_ANALYZER.waveforms.ms_before,
    start=0.0, step=0.1,
    description="Pre-spike window (ms) for waveform extraction. Typical 1.0 ms.",
)
self.analyzer_ms_after_input = pn.widgets.FloatInput(
    name="Waveform ms_after",
    value=_DEFAULT_ANALYZER.waveforms.ms_after,
    start=0.0, step=0.1,
    description="Post-spike window (ms) for waveform extraction. Typical 2.0 ms.",
)

# ── Analyzer: Template / Similarity ──
self.analyzer_template_operators_input = pn.widgets.MultiChoice(
    name="Template Operators",
    options=["average", "std", "median"],
    value=list(_DEFAULT_ANALYZER.template_operators),
    description="Operators for template computation. 'average' is the conventional template; 'std' gives per-sample variability.",
)
self.analyzer_unit_locations_select = pn.widgets.Select(
    name="Unit Locations Method",
    options=["monopolar_triangulation", "center_of_mass", "grid_convolution"],
    value=_DEFAULT_ANALYZER.unit_locations_method,
    description="Spatial localization algorithm for unit positions. monopolar_triangulation is most accurate for Neuropixels.",
)
self.analyzer_template_similarity_select = pn.widgets.Select(
    name="Template Similarity Method",
    options=["cosine_similarity", "l1", "l2"],
    value=_DEFAULT_ANALYZER.template_similarity_method,
    description="Metric for cross-unit template similarity. cosine_similarity is the SpikeInterface default.",
)
```

- [ ] **Step 6.5.5: 加入 watch 列表 + `_rebuild_config`**

```python
for widget in (
    ...,  # 现有 widgets
    self.analyzer_max_spikes_input,
    self.analyzer_random_method_select,
    self.analyzer_ms_before_input,
    self.analyzer_ms_after_input,
    self.analyzer_template_operators_input,
    self.analyzer_unit_locations_select,
    self.analyzer_template_similarity_select,
):
    widget.param.watch(self._rebuild_config, "value")
```

`_rebuild_config` 中构建 AnalyzerConfig：
```python
analyzer=AnalyzerConfig(
    random_spikes=RandomSpikesConfig(
        max_spikes_per_unit=self.analyzer_max_spikes_input.value,
        method=self.analyzer_random_method_select.value,
    ),
    waveforms=WaveformConfig(
        ms_before=self.analyzer_ms_before_input.value,
        ms_after=self.analyzer_ms_after_input.value,
    ),
    template_operators=list(self.analyzer_template_operators_input.value),
    unit_locations_method=self.analyzer_unit_locations_select.value,
    template_similarity_method=self.analyzer_template_similarity_select.value,
),
```

- [ ] **Step 6.5.6: 加 Analyzer Card 到 `panel()`**

```python
pn.Card(
    self.analyzer_max_spikes_input,
    self.analyzer_random_method_select,
    self.analyzer_ms_before_input,
    self.analyzer_ms_after_input,
    self.analyzer_template_operators_input,
    self.analyzer_unit_locations_select,
    self.analyzer_template_similarity_select,
    title="Analyzer (Postprocess SortingAnalyzer)",
    collapsed=True,
),
```

- [ ] **Step 6.5.7: Run tests**

```bash
uv run pytest tests/test_ui/test_components.py -v -k "analyzer"
```

Expected: 9 PASS.

- [ ] **Step 6.5.8: Commit**

```bash
git add src/pynpxpipe/ui/components/sorting_form.py tests/test_ui/test_components.py
git commit -m "feat(ui): expose AnalyzerConfig widgets in SortingForm"
```

---

## Task 7 — Phase 4: Harness (防漂移元测试)

**Files:**
- Modify: `tests/test_ui/test_components.py` (append)

- [ ] **Step 7.1: 派发 subagent 起草 harness 测试**

**[SUBAGENT × 1]** 返回测试函数源码：

```
Prompt 要点：
- 读 src/pynpxpipe/core/config.py 的 PipelineConfig 和 SortingConfig 所有子配置 dataclass
- 读 src/pynpxpipe/ui/components/pipeline_form.py 的 PipelineForm.__init__
- 读 src/pynpxpipe/ui/components/sorting_form.py 的 SortingForm.__init__
- 产出 test_pipeline_form_covers_all_pipeline_config_fields():
    * 构造 AppState + PipelineForm
    * 显式 EXPECTED_MAPPING 字典列出每个 PipelineConfig 叶子字段 → widget attr name
    * 遍历 dataclasses.fields(PipelineConfig) 递归展开子配置
    * 断言每个叶子字段都在 EXPECTED_MAPPING 中，且 form 有对应 attr
- 产出 test_sorting_form_covers_all_sorting_config_fields():
    * 同上，针对 SortingConfig（mode / sorter.name / sorter.params.* / analyzer.*）
    * import_cfg.paths 为 dict 不强制 widget，但 import_cfg.format 要有（复用 sorter_select 的值是 ok 的 — 断言放松为"SortingForm 或从 sorter name 推导"）
- 产出 test_pipeline_form_default_roundtrip() 和 test_sorting_form_default_roundtrip():
    * 构造 form, 立即读 state.pipeline_config / state.sorting_config
    * 用 dataclasses.asdict 转 dict 后深度比较
    * 断言 == dataclasses.asdict(PipelineConfig()) / SortingConfig()
    * 捕获默认值漂移
- 返回纯代码文本，不写文件
```

- [ ] **Step 7.2: Main agent 追加到 test_components.py**

- [ ] **Step 7.3: Run tests**

```bash
uv run pytest tests/test_ui/test_components.py -v -k "covers_all or default_roundtrip"
```

Expected: 4 PASS（PipelineConfig × 2 + SortingConfig × 2）。若 FAIL，说明 Phase 3 有遗漏 — 修对应 form 直到 PASS。

- [ ] **Step 7.4: Commit**

```bash
git add tests/test_ui/test_components.py
git commit -m "test(ui): add pipeline_form config coverage harness"
```

---

## Task 8 — Phase 5: Lint + 全量回归

- [ ] **Step 8.1: Ruff check + format**

```bash
uv run ruff check src/pynpxpipe/ui/ tests/test_ui/
uv run ruff format src/pynpxpipe/ui/ tests/test_ui/
```

Expected: 0 errors。若 format 有变更 → commit `style(ui): ruff format`.

- [ ] **Step 8.2: 全 UI 测试回归**

```bash
uv run pytest tests/test_ui/ -v
```

Expected: 所有原有 153 tests + 新增 ~29 tests 全部 PASS。

- [ ] **Step 8.3: 全项目测试冒烟（可选，跳过 matlab/gpu/integration）**

```bash
uv run pytest -m "not matlab and not gpu and not integration" --tb=short -q
```

Expected: 0 regression。

---

## Task 9 — Phase 6: Progress 更新

**Files:**
- Modify: `docs/progress.md`

- [ ] **Step 9.1: 新增 UI S5 行**

```markdown
| UI S5 | Pipeline form 与 core/config.py 对齐 | ✅ | 新增 16 widgets + harness coverage test（约 29 tests） |
```

- [ ] **Step 9.2: Commit**

```bash
git add docs/progress.md
git commit -m "docs(progress): mark UI S5 pipeline-form config alignment complete"
```

---

## Task 10 — (Optional) Phase 7: Code Review

- [ ] **Step 10.1: 派发 code-reviewer subagent**

```
subagent_type: superpowers:code-reviewer
prompt 要点：
- 对比本 session 的 commit 范围 (git log -10)
- 审查 pipeline_form.py 的 widget 是否完整覆盖 PipelineConfig
- 审查 test_components.py 的新 tests 是否 tests behavior 而非 implementation
- 审查 ui.md spec 与代码是否一致
- 报告 blocker / should-fix / nit
```

---

## Self-review checklist

**Spec coverage**：
- ✅ Parallel group — Task 3
- ✅ Curation 新字段 — Task 4
- ✅ Sync 新字段（含 nullable）— Task 5
- ✅ Postprocess + Merge — Task 6
- ✅ Harness 防漂移 — Task 7
- ✅ 默认值漂移检测 — Task 7 Step 7.1 (default_roundtrip)
- ✅ Spec 文本同步 — Task 1

**Placeholder scan**：无 TBD / TODO / "similar to"；所有代码块完整。

**Type consistency**：
- `_DEFAULTS.parallel.enabled` 指 `PipelineConfig().parallel.enabled`（Task 3 Step 3.2）
- `ParallelConfig` import 在 Task 3 Step 3.1 加入
- `MergeConfig` import 在 Task 3 Step 3.1 加入
- Widget attribute 命名一致（`_input` / `_checkbox` / `_select` 后缀风格同现有代码）

**并行 subagent 风险**：
- 4 个测试起草 subagent 各自返回独立的 test 函数源码，主 agent 合并时顺序插入，无冲突。
- 派发前在 prompt 中明确"只返回文本，不写文件"避免并行 Write。
