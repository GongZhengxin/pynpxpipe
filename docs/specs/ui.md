# Spec: ui/ — Panel Web UI

## 1. 目标

为 pynpxpipe pipeline 提供基于 Panel (HoloViz) 的浏览器交互界面。用户无需写代码即可：

1. 配置 session 参数（数据路径、受试者元信息、pipeline/sorting 参数）
2. 选择要运行的 stage 子集
3. 启动 pipeline 并实时监控 stage 级 + probe 级进度
4. 查看已有 output_dir 的运行状态、重置失败的 stage、断点续跑

**约束**：
- UI 层只调用 `core/`、`pipelines/` 的公开 API，不直接操作 IO 或 stage 内部逻辑
- 业务层不得 import Panel/param — 唯一桥接点是 `progress_callback: Callable[[str, float], None]`
- 长时间 pipeline 运行在后台线程中执行，UI 主线程不阻塞

---

## 2. 模块结构

```
src/pynpxpipe/ui/
    __init__.py
    app.py                 # 入口：panel serve / pynpxpipe-ui 命令
    state.py               # 全局状态：AppState param 类 + ProgressBridge
    components/
        __init__.py
        session_form.py    # Session 配置面板（路径选择 + 输出目录 + experiment + date）
        subject_form.py    # Subject 元信息表单
        probe_region_editor.py  # Probe → target_area 声明式编辑器（NWB filename 规整）
        pipeline_form.py   # PipelineConfig 参数面板
        sorting_form.py    # SortingConfig 参数面板
        stage_selector.py  # Stage 多选器
        run_panel.py       # 执行控制面板（Run / Stop / 状态）
        progress_view.py   # Stage 进度可视化
        log_viewer.py      # 实时日志面板
        status_view.py     # 已有 session 状态查看 + Reset
        session_loader.py  # Session 恢复（从 output_dir 加载）
```

---

## 3. 核心组件规格

### 3.1 state.py — AppState

```python
import param

class AppState(param.Parameterized):
    """全局应用状态，所有组件共享同一实例。"""

    # 输入路径
    session_dir = param.Path(doc="SpikeGLX 录制根目录")
    bhv_file = param.Path(doc="MonkeyLogic BHV2 文件")
    output_dir = param.Path(doc="输出根目录")
    subject_yaml = param.Path(doc="Subject YAML 文件（可选预填）")

    # 配置对象（由表单填充）
    pipeline_config = param.Parameter(doc="PipelineConfig dataclass 实例")
    sorting_config = param.Parameter(doc="SortingConfig dataclass 实例")
    subject_config = param.Parameter(doc="SubjectConfig dataclass 实例")

    # NWB filename 规整字段（A6 新增）
    experiment = param.String(default="", doc="实验名（例如 'ShapeMap'），由用户填写")
    recording_date = param.String(
        default="",
        doc="录制日期 YYMMDD，由 Detect Date 按钮自动探测或用户手动填写",
    )
    probe_plan = param.Dict(
        default={"imec0": ""},
        doc="probe_id → target_area 声明表，由 ProbeRegionEditor 管理",
    )

    # 运行时状态
    run_status = param.Selector(
        default="idle",
        objects=["idle", "running", "completed", "failed"],
    )
    selected_stages = param.List(default=[], doc="要运行的 stage 名称列表")
    error_message = param.String(default="")

    # 进度（由 ProgressBridge 写入）
    current_stage = param.String(default="")
    stage_progress = param.Number(default=0.0, bounds=(0.0, 1.0))
    stage_statuses = param.Dict(default={})  # {stage_name: "pending"|"completed"|...}

    # 派生属性

    @property
    def session_id(self):
        """返回 SessionID 实例；当 date/subject/experiment/probe_plan 任一项不完整时返回 None。

        完整定义：
        - recording_date 非空且长度为 6（YYMMDD）
        - subject_config 非 None 且 subject_id 非空
        - experiment 非空
        - probe_plan 非空且所有 target_area 值非空

        Returns:
            SessionID 实例（见 core/session.py）或 None。
        """
        from pynpxpipe.core.session import SessionID

        if not self.recording_date or len(self.recording_date) != 6:
            return None
        if self.subject_config is None or not getattr(self.subject_config, "subject_id", ""):
            return None
        if not self.experiment:
            return None
        if not self.probe_plan:
            return None
        if any(not v for v in self.probe_plan.values()):
            return None
        return SessionID(
            date=self.recording_date,
            subject=self.subject_config.subject_id,
            experiment=self.experiment,
            region=SessionID.derive_region(dict(self.probe_plan)),
        )
```

注：`SessionID` 字段为 `(date, subject, experiment, region)`，其中 `region` 由 `SessionID.derive_region(probe_plan)` 静态方法在构造时派生（见 `docs/specs/session.md` §5.5）。AppState 不存 region，永远从 probe_plan 实时派生。

### 3.2 state.py — ProgressBridge

将 `PipelineRunner.progress_callback` 桥接到 `AppState` 的 param 属性，使 Panel widget 自动响应更新。

```python
class ProgressBridge:
    """线程安全的 progress_callback → param 属性桥接。"""

    def __init__(self, state: AppState):
        self._state = state

    def callback(self, message: str, fraction: float) -> None:
        """传递给 PipelineRunner 的 progress_callback。

        在后台线程中被调用，通过 pn.state.execute 安全更新 UI。
        """
        import panel as pn
        pn.state.execute(lambda: self._update(message, fraction))

    def _update(self, message: str, fraction: float) -> None:
        self._state.current_stage = message
        self._state.stage_progress = fraction
```

### 3.3 session_form.py — Session 配置面板

| Widget | 绑定到 | 类型 | 约束 |
|--------|--------|------|------|
| session_dir 选择器 | `state.session_dir` | `pn.widgets.TextInput` + 浏览按钮 | 目录必须存在且含 `*_g[0-9]*` 子目录 |
| bhv_file 选择器 | `state.bhv_file` | `pn.widgets.TextInput` + 浏览按钮 | 文件必须存在且以 `.bhv2` 结尾 |
| output_dir 选择器 | `state.output_dir` | `pn.widgets.TextInput` + 浏览按钮 | 可以不存在（会自动创建） |
| experiment 输入框 | `state.experiment` | `pn.widgets.TextInput` | 非空字符串（用户手填，如 "ShapeMap"） |
| recording_date 输入框 | `state.recording_date` | `pn.widgets.TextInput` | 6 位数字 YYMMDD；可由 "Detect Date" 按钮自动填充，也可手动覆盖 |
| Detect Date 按钮 | — | `pn.widgets.Button` | 扫描 `data_dir`（或 `session_dir`）下第一个 AP `.meta` 文件，调用 `SpikeGLXLoader.read_recording_date()` 并写回 `state.recording_date` |

验证逻辑：所有路径填写后显示绿色勾；缺失项显示红色提示。

**Detect Date 行为细节（A6）**
- 点击按钮时查找 `session_dir` 下任意 `*.ap.meta`（第一个即可），调用 `SpikeGLXLoader.read_recording_date(meta_path) -> str`（返回 YYMMDD 字符串，见 `docs/specs/spikeglx.md`）。
- 成功 → 写入 `state.recording_date`，文本框同步刷新。
- 失败 / 未找到 `.meta` → 在按钮下方以 `pn.pane.Alert(alert_type="warning")` 展示错误消息，不覆盖已有值。
- 用户仍可直接编辑 `recording_date` 输入框手动覆盖探测结果。

### 3.4 subject_form.py — Subject 元信息表单

| 字段 | Widget 类型 | 默认值 | 约束 |
|------|-------------|--------|------|
| subject_id | TextInput | "" | 必填 |
| description | TextInput | "" | 可选 |
| species | TextInput | "Macaca mulatta" | 必填 |
| sex | Select | "M" | ["M", "F", "U", "O"] |
| age | TextInput | "" | 必填，ISO 8601 duration (如 "P3Y") |
| weight | TextInput | "" | 必填 (如 "10kg") |

支持从 YAML 文件加载预填（`load_subject_config(yaml_path)` → 填充表单）。

#### Save Subject YAML（保存到 monkeys/）

允许用户把当前表单填写的 Subject 信息写回磁盘，默认存入项目根目录的 `monkeys/{subject_id}.yaml`，便于后续 session 通过 YAML loader 一键复用。

**目标**
- 把表单内存态 `SubjectConfig` 持久化为 YAML 文件，格式对齐 `monkeys/MonkeyTemplate.yaml`（顶层 `Subject:` 块）。

**输入**
- 表单当前值（必须先通过 `_rebuild_config` 生成一个合法的 `SubjectConfig`；未通过则按钮禁用 / 报错）。
- 可选用户自定义保存路径（`BrowsableInput`，`only_files=True`）。默认值：`<project_root>/monkeys/<subject_id>.yaml`。`<project_root>` 来自 `Path(__file__).resolve().parents[4]`。

**输出**
- 磁盘上的 YAML 文件，内容示例：
  ```yaml
  Subject:
    subject_id: "MaoDan"
    description: "good monkey"
    species: "Macaca mulatta"
    sex: "M"
    age: "P5Y"
    weight: "10kg"
  ```
- UI 反馈（`pn.pane.Alert`）：`success` / `warning` / `danger` 三态消息。

**处理步骤**
1. 点击 `Save to monkeys/` 按钮 → 读 `state.subject_config`。若为 `None`（必填项未填完）→ 显示 `warning` 消息，直接返回。
2. 读保存路径输入框。空 → 用默认路径 `<project_root>/monkeys/<subject_id>.yaml`。
3. **覆盖保护**：若目标文件已存在且 `_pending_overwrite_path` 未指向同一路径 → 显示 `warning` 消息 `File exists. Click again to overwrite.`，把路径记到 `_pending_overwrite_path`，等用户二次点击。
4. 二次点击（或文件不存在）→ 调用 `save_subject_config(cfg, path)` 写盘；清空 `_pending_overwrite_path`。
5. 任一步抛异常 → 转 `danger` 消息展示 `exc` 文本。

**可配参数**
- `project_root`：构造时注入（默认 `Path(__file__).resolve().parents[4]`），便于测试用 `tmp_path`。
- 文件落盘格式固定（顶层 `Subject:`、`yaml.safe_dump(sort_keys=False, allow_unicode=True)`），不对外暴露。

**新模块函数（`core/config.py`）**
- `save_subject_config(cfg: SubjectConfig, yaml_path: Path) -> None`
  - 写入顶层 `Subject:` 块；缺失父目录自动 `mkdir(parents=True, exist_ok=True)`；使用 `encoding="utf-8"`。
  - 不做覆盖检查（由 UI 层处理）。

**UI 层新增**
- `SubjectForm.save_btn`（`pn.widgets.Button`, name=`"Save to monkeys/"`, button_type=`"success"`）。
- `SubjectForm.save_path_input`（`BrowsableInput`, `file_pattern="*.yaml"`, `only_files=True`）。
- `SubjectForm.save_message`（`pn.pane.Alert`, 初始 `visible=False`）。
- `SubjectForm._on_save_click(event)` 处理 steps 1–5。
- `SubjectForm._pending_overwrite_path: Path | None` 状态位。

**与现有约定的关系**
- 不新增 `state.py` 字段；`SubjectForm` 内部自治。
- 不写 project 级 spec（本功能纯 UI + 一条 `core/config.py` 辅助函数）。
- `load_subject_config` / `save_subject_config` 成对，格式必须互逆（加载后立即保存 → 内容等价）。

### 3.4a probe_region_editor.py — Probe Region Editor（A6 新增）

负责 `state.probe_plan: dict[str, str]` 的编辑（`probe_id → target_area`）。详细设计见 `docs/specs/probe_region_editor.md`。

**目标**
- 让用户为每个 probe 声明目标脑区，用于 NWB 文件名规整（例如 `session_id = 250417_MaoDan_ShapeMap_MSB-V4`，其中 `MSB-V4` 由 `SessionID.derive_region({"imec0": "MSB", "imec1": "V4"})` 派生）。
- `probe_plan` 的键与 `session.probes` 中的 `probe_id` 必须一致（由 discover stage 在运行时校验；不一致将抛 `ProbeDeclarationMismatchError`，见 `docs/specs/discover.md`）。

**UI 行为**
- 初始显示一行 `imec0: [___]`（对应 `state.probe_plan = {"imec0": ""}`）。
- `+ Add probe` 按钮追加 `imec{max+1}` 行；每行右侧 `×` 按钮删除（唯一一行时 disabled）。
- 每次输入变化写入 `state.probe_plan = {**state.probe_plan, probe_id: new_value}`，忽略空 probe_id（probe_id 自动生成不会为空）。
- 空 target_area 允许在编辑过程中存在（仅红框视觉提示），但 `AppState.session_id` 判定为 `None`，RunPanel 会阻止启动。

**恢复**
- `state.probe_plan` 被外部（SessionLoader / 程序）重写时，组件重建行 UI。

### 3.5 pipeline_form.py — Pipeline 参数面板

按分组可折叠 Card 展示 `PipelineConfig` 所有子配置。每个分组对应一个 dataclass，字段类型、默认值严格对齐 `core/config.py`。

#### Resources (`ResourcesConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| n_jobs | TextInput | `"auto"` | `"auto"` 或正整数字符串 | SpikeInterface 并行线程数；auto 由 ResourceDetector 按 CPU/RAM 推算 |
| chunk_duration | TextInput | `"auto"` | `"auto"` 或时间字符串（如 `"1s"`） | 分块处理时间窗；auto 按可用 RAM 推算 |
| max_memory | TextInput | `"auto"` | `"auto"` 或大小字符串（如 `"32G"`） | 内存上限提示（仅日志警告，不强制） |

#### Parallel (`ParallelConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| enabled | Checkbox | `False` | bool | 是否并行处理多个 probe（默认串行） |
| max_workers | TextInput | `"auto"` | `"auto"` 或正整数字符串 | ProcessPoolExecutor 最大 worker 数 |

#### Bandpass Filter (`BandpassConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| freq_min | FloatInput | `300.0` | `> 0`，`< freq_max` | 高通截止频率 (Hz) |
| freq_max | FloatInput | `6000.0` | `> freq_min` | 低通截止频率 (Hz) |

#### Bad Channel Detection (`BadChannelConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| method | TextInput | `"coherence+psd"` | 合法 SI 方法名 | 坏道检测算法 |
| dead_channel_threshold | FloatInput | `0.5` | `0.0–1.0` | 死通道判定阈值 |

#### Common Reference (`CommonReferenceConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| reference | Select | `"global"` | `["global", "local"]` | 共参考作用范围 |
| operator | Select | `"median"` | `["median", "mean"]` | 聚合算子 |

#### Motion Correction (`MotionCorrectionConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| method | Checkbox | `"dredge"` (enabled) | `"dredge"` 或 `None` | **开关**：勾选→`"dredge"` 启用运动校正；不勾选→`None` 跳过 |
| preset | Select | `"dredge"` | SI 合法 preset 名 | 实际算法 preset（传给 `spp.correct_motion(preset=...)`） |

注：method 仅作 enable/disable 开关，算法由 preset 决定。

#### Curation (`CurationConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| use_bombcell | Checkbox | `True` | bool | 启用 SI `bombcell_label_units()` 四分类（SUA/MUA/NON-SOMA/NOISE） |
| isi_violation_ratio_max | FloatInput | `2.0` | `> 0` | ISI 违反率上限（NOISE 过滤阈值） |
| amplitude_cutoff_max | FloatInput | `0.5` | `> 0` | 幅度截断上限（NOISE 过滤阈值） |
| presence_ratio_min | FloatInput | `0.5` | `0.0–1.0` | 在线率下限（NOISE 过滤阈值） |
| snr_min | FloatInput | `0.3` | `> 0` | 信噪比下限（NOISE 过滤阈值） |
| good_isi_max | FloatInput | `0.1` | `> 0` | SUA 分类的 ISI 上限（**仅 use_bombcell=False 时生效**） |
| good_snr_min | FloatInput | `3.0` | `> 0` | SUA 分类的 SNR 下限（**仅 use_bombcell=False 时生效**） |

注：`use_bombcell=True` 时，`isi/amplitude/presence/snr` 四个 max/min 字段作为 NOISE 过滤阈值（bombcell 内部判断 SUA/MUA/NON-SOMA）；`use_bombcell=False` 时改用手动阈值分类，此时 `good_isi_max`、`good_snr_min` 决定 SUA/MUA 边界。

#### Sync (`SyncConfig`)

**Clock Alignment（IMEC↔NIDQ 时钟对齐）**

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| imec_sync_bit | IntInput | `6` | `0–7` | IMEC AP sync 通道的脉冲位（NP 硬件标准 bit 6） |
| nidq_sync_bit | IntInput | `0` | `0–7` | NIDQ digital word 的 sync 脉冲位 |
| max_time_error_ms | FloatInput | `17.0` | `> 0` | IMEC↔NIDQ 允许的最大对齐误差 (ms) |
| generate_plots | Checkbox | `True` | bool | 是否生成同步诊断 PNG 图 |

**Event + Trial（事件码与 trial 匹配）**

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| event_bits | TextInput (逗号分隔) | `[1, 2, 3, 4, 5, 6, 7]` | 各 bit ∈ `0–7` | MonkeyLogic 事件码使用的 bit 位列表 |
| stim_onset_code | IntInput | `64` | `> 0` | NIDQ 上代表 stim onset 的事件码 |
| trial_count_tolerance | IntInput | `2` | `>= 0` | 允许的 trial 数量不匹配容差(自动修复上限) |
| gap_threshold_ms | Checkbox + FloatInput | `1200.0`（nullable） | `> 0` 或 None | Trial 间最小间隔 (ms)；Checkbox 未勾选 → `None` 禁用 gap 修复 |
| trial_start_bit | Checkbox + IntInput | `None` | `0–7` 或 None | Trial 起始 bit 位(可选)；Checkbox 未勾选 → `None` 回退到 event_bits |

**Photodiode Calibration（光电二极管校准）**

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| photodiode_channel_index | IntInput | `0` | `>= 0` | NIDQ 模拟通道 index（光电信号位置） |
| monitor_delay_ms | FloatInput | `-5.0` | 任意 float | 显示器系统延迟补偿 (ms)，60 Hz 约 `-5` |
| pd_window_pre_ms | FloatInput | `10.0` | `>= 0` | 相对事件 onset 的前置搜索窗 (ms) |
| pd_window_post_ms | FloatInput | `100.0` | `>= 0` | 相对事件 onset 的后置搜索窗 (ms) |
| pd_min_signal_variance | FloatInput | `1e-6` | `> 0` | PD 信号有效性最小方差阈值 |

#### Postprocess (`PostprocessConfig` + `EyeValidationConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| slay_pre_s | FloatInput | `0.05` | `>= 0` | SLAy 窗前侧秒数（behavior_events 缺失时的 fallback） |
| slay_post_s | FloatInput | `0.30` | `>= 0` | SLAy 窗后侧秒数（fallback） |
| pre_onset_ms | FloatInput | `50.0` | `>= 0` | 动态 SLAy 窗前置 (ms)，`pre_s = pre_onset_ms / 1000` |
| eye_validation.enabled | Checkbox | `True` | bool | 是否启用眼动验证 |
| eye_validation.eye_threshold | FloatInput | `0.999` | `0.0–1.0` | 注视率阈值，低于此值 trial 判为无效 |

#### Merge (`MergeConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| enabled | Checkbox | `False` | bool | 启用 `auto_merge()`（**opt-in, irreversible** — 合并不可逆，需用户手动勾选确认） |

---

**关键规则**

- **`"auto"|value` 字段模式**：`n_jobs`、`chunk_duration`、`max_memory`、`max_workers` 等字段均用 **TextInput**（而非 IntInput/FloatInput），允许用户输入字符串 `"auto"` 或具体数值字符串。UI 层在 `_rebuild_config` 中按字段类型注解转换（`int | str` → 尝试 int 失败则保留字符串）。
- **nullable 字段模式**（`gap_threshold_ms: float | None`, `trial_start_bit: int | None`）：采用 **Checkbox + 数值输入** 组合。Checkbox 未勾选时数值输入 `disabled=True`，对应 config 字段写入 `None`；勾选后启用数值输入，写入用户输入值。

### 3.6 sorting_form.py — Sorting 参数面板

按分组展示 `SortingConfig` 所有子配置。字段类型、默认值严格对齐 `core/config.py`。

#### Sorter 选择

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| sorter name | Select | `"kilosort4"` | SI 支持的 sorter 名 | `SortingConfig.sorter.name` |
| mode | Select | `"local"` | `["local", "import"]` | `local` 本地运行 sorter；`import` 导入外部结果 |
| import_path | TextInput | `""` | 合法目录路径（**仅 mode=import 可见**） | `SortingConfig.import_cfg.paths`（UI 暂按单 probe 展示） |

#### Sorter Parameters (`SorterParams`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| nblocks | IntInput | `15` | `>= 0` | KS4 drift 校正块数（0 = 禁用） |
| Th_learned | FloatInput | `7.0` | `> 0` | 学习阈值 |
| do_CAR | Checkbox | `False` | bool | KS4 内部是否做 CAR（已预处理时关闭） |
| batch_size | TextInput | `"auto"` | `"auto"` 或正整数字符串 | 每 batch 样本数；auto 由 GPU VRAM 推算 |
| n_jobs | IntInput | `1` | `>= 1` | 内部并行度（GPU 通常为 1） |
| torch_device | Select | `"auto"` | `["auto", "cuda", "cpu"]` | PyTorch 设备；auto 自动选用 CUDA（不可用时回退 CPU） |

#### Analyzer: Random Spikes (`RandomSpikesConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| max_spikes_per_unit | IntInput | `500` | `>= 1` | 每 unit 采样上限 |
| method | Select | `"uniform"` | `["uniform", "all", "smart"]` | 采样方法 |

#### Analyzer: Waveforms (`WaveformConfig`)

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| ms_before | FloatInput | `1.0` | `> 0` | spike 前窗 (ms) |
| ms_after | FloatInput | `2.0` | `> 0` | spike 后窗 (ms) |

#### Analyzer: Template / Similarity

| 字段 | Widget 类型 | 默认值 | 约束 | 说明 |
|------|-------------|--------|------|------|
| template_operators | MultiChoice | `["average", "std"]` | `["average", "std", "median"]` | 模板计算算子（可多选） |
| unit_locations_method | Select | `"monopolar_triangulation"` | `["monopolar_triangulation", "center_of_mass", "grid_convolution"]` | unit 空间定位方法 |
| template_similarity_method | Select | `"cosine_similarity"` | `["cosine_similarity", "l1", "l2"]` | 模板相似度度量 |

GPU 检测状态指示器：调用 `ResourceDetector().detect()` 显示 GPU 可用性（CUDA 设备名 / VRAM / 不可用提示），辅助用户判断 `torch_device="auto"` 的实际回退行为及 `batch_size="auto"` 的推算依据。

### 3.7 stage_selector.py — Stage 选择器

7 个 Checkbox，按 `STAGE_ORDER` 排列。全选/全不选按钮。

```
[✓] discover     [✓] preprocess   [✓] sort
[✓] synchronize  [✓] curate       [✓] postprocess   [✓] export
```

下方显示依赖提示：选了 `export` 但没选 `sort` → 警告"export 依赖 sort 的输出"。

### 3.8 run_panel.py — 执行控制面板

| 按钮/状态 | 行为 |
|-----------|------|
| **Run** 按钮 | 1. 执行 **Pre-execution validation**（见下）<br>2. 从各表单收集参数构建 `SubjectConfig`, `PipelineConfig`, `SortingConfig`<br>3. 调用 `SessionManager.create(session_dir=..., bhv_file=..., output_dir=..., subject=..., experiment=state.experiment, probe_plan=dict(state.probe_plan), date=state.recording_date)` 创建 session（see `docs/specs/session.md`）<br>4. 创建 `PipelineRunner(session, pipeline_config, sorting_config, progress_callback=bridge.callback)`<br>5. 在 `threading.Thread` 中调用 `runner.run(stages=...)`<br>6. 完成后更新 `state.run_status` |
| **Stop** 按钮 | 设置中断标志（需要 pipeline 层支持 — M2 scope 内暂用线程终止） |
| 状态文字 | `idle` → "Ready" / `running` → "Running stage: {name}" / `completed` → "Pipeline complete" / `failed` → "Error: {msg}" |

#### Pre-execution validation（A6 新增）

**校验分工原则**：UI 只做**空值检查**（"字段填了没"），**格式检查**全部交给 `core/session.py` 的 `SessionManager.create()` 及 `SessionID` 校验，RunPanel 捕获 `ValueError` 后以 `pn.pane.Alert(alert_type="danger")` 展示 `str(exc)`。这样同一条格式规则只在一处维护（core 层），UI 只负责"用户填了没 + 把异常友好呈现"。

**Step 1 — UI 空值检查（本地即时反馈）**

按以下顺序检查；任一失败 → 以 `pn.pane.Alert(alert_type="danger")` 显示**具体字段**的消息并 `return`，不启动线程：

1. `state.subject_config is not None` — "Please fill in Subject information."
2. `state.session_dir` 存在且是目录 — "Data directory is invalid or missing."
3. `state.output_dir` 非空 — "Output directory is required."
4. `state.experiment.strip() != ""` — "Experiment name is required."
5. `state.recording_date.strip() != ""` — "Recording date is required. Click 'Detect Date' or enter manually."
6. `state.probe_plan` 非空 — "At least one probe must be declared."
7. `all(v.strip() for v in state.probe_plan.values())` — "All probe target areas must be non-empty."
8. `state.selected_stages` 非空 — "Select at least one stage."
9. （原有检查保留：`pipeline_config` / `sorting_config` 已构建等）

注：**UI 不校验** `recording_date` 是否 6 位数字、`probe_plan` key 是否匹配 `^imec\d+$` — 这些格式约束由 `core/session.py` 负责（`SessionID.date` 6 位数校验、`probe_plan` key 正则校验）。

**Step 2 — Core 格式校验（最后防线 + 错误呈现）**

通过 Step 1 后调用 `SessionManager.create(...)`。该调用内部会对 `experiment` / `probe_plan` key / `date` 做格式校验（见 `docs/specs/session.md` §4.2），若违反约束 raise `ValueError`：

```python
try:
    session = SessionManager.create(
        session_dir=..., bhv_file=..., subject=..., output_dir=...,
        experiment=state.experiment,
        probe_plan=dict(state.probe_plan),
        date=state.recording_date,
    )
except ValueError as exc:
    self._alert.object = f"Invalid configuration: {exc}"
    self._alert.alert_type = "danger"
    self._alert.visible = True
    return
```

好处：
- 同一条格式规则只在 core 层维护，UI 不重复（"date 必须 6 位"、"probe_id 必须 imec{N}" 只在 session.md 里有一份权威描述）
- CLI / Python 脚本直接调用 `SessionManager.create()` 时也享有同样的格式校验
- UI 代码短，只负责"字段填了没 + 把 core 的异常友好呈现"

> **与 discover stage 的关系**：discover stage 会再次校验 `probe_plan` 的键与实际 SpikeGLX 目录中的 probe_id 一致。若不一致抛 `ProbeDeclarationMismatchError`（见 `docs/specs/discover.md`），UI 同样用 try/except 捕获后展示 `str(exc)`。

### 3.9 progress_view.py — 进度可视化

7 行，每行一个 stage：

```
discover      ████████████████████ 100%  ✓  (3.2s)
preprocess    ██████████░░░░░░░░░░  52%  ⏳ (imec0: done, imec1: running)
sort          ░░░░░░░░░░░░░░░░░░░░   0%  -
...
```

每行绑定到 `state.stage_statuses[stage_name]`，通过 `ProgressBridge` 更新。

### 3.10 log_viewer.py — 日志面板

使用 `pn.pane.HTML` 或 `pn.widgets.Terminal` 实时显示 structlog 输出。

实现方式：
1. 添加一个自定义 structlog processor 将日志事件写入 `collections.deque(maxlen=500)`
2. Panel `pn.state.add_periodic_callback(update_log, period=1000)` 定期刷新显示

### 3.11 status_view.py + session_loader.py — 状态查看与恢复

**status_view**：
- 输入：`output_dir` 路径
- 调用 `SessionManager.load(output_dir)` → `PipelineRunner(session, ...).get_status()`
- 渲染状态表（同 CLI `status` 命令的输出格式）
- 每个 stage 行尾有 "Reset" 按钮 → 调用 `CheckpointManager.clear(stage)` + 清理 per-probe checkpoints

**session_loader**：
- 选择已有 output_dir → 读取 `session.json` → 自动填充 session_form + subject_form
- 显示当前状态 → 用户可修改参数后点 Run 断点续跑

**A6 新增回填字段**：`SessionLoader.load_session()` 成功读到 `session.json` 后，除了原有的 `session_dir` / `bhv_file` / `output_dir` / `subject_config` 之外，**必须**按以下映射回填 NWB filename 相关字段：

| AppState 字段 | 数据来源 |
|----------------|----------|
| `state.experiment` | `session.session_id.experiment` |
| `state.recording_date` | `session.session_id.date` |
| `state.probe_plan` | `dict(session.probe_plan)` |

若 `session_id` 或 `probe_plan` 在旧的 `session.json` 中缺失（兼容 A6 之前的数据），保留 `state` 当前值并在 `message_pane` 追加 `"Loaded session lacks NWB filename metadata; please fill before running."`。

---

## 4. 线程模型

```
UI 主线程 (Panel/Tornado)
    │
    ├── 用户交互 → 读写 AppState param 属性
    │
    └── 点击 Run →  创建 threading.Thread(target=_run_pipeline)
                        │
                        ├── PipelineRunner.run() (可能跑数小时)
                        │     └── stage.run() 内部调用 progress_callback
                        │           └── ProgressBridge.callback(msg, frac)
                        │                 └── pn.state.execute(lambda: state.update(...))
                        │                       └── UI 自动刷新（param watch 机制）
                        │
                        └── 完成/异常 → 更新 state.run_status
```

关键点：
- `progress_callback` 在后台线程中调用，必须通过 `pn.state.execute()` 将 param 更新调度回 UI 线程
- `AppState` 上的 `param.watch()` 自动触发 widget 刷新，无需手动管理

---

## 5. 依赖

| 依赖 | 类型 | 说明 |
|------|------|------|
| `panel>=1.0` | 第三方，optional `[ui]` | Web UI 框架 |
| `param` | 第三方（Panel 自带） | 响应式参数系统 |
| `pynpxpipe.pipelines.runner` | 项目内部 | `PipelineRunner`, `STAGE_ORDER` |
| `pynpxpipe.core.session` | 项目内部 | `SessionManager`, `SessionID`, `SubjectConfig` |
| `pynpxpipe.core.config` | 项目内部 | `load_pipeline_config`, `load_sorting_config`, `load_subject_config`, 所有 Config dataclass |
| `pynpxpipe.core.checkpoint` | 项目内部 | `CheckpointManager`（status/reset） |
| `pynpxpipe.core.resources` | 项目内部 | `ResourceDetector`（GPU 检测显示） |
| `pynpxpipe.core.errors` | 项目内部 | `PynpxpipeError`, `ProbeDeclarationMismatchError`（错误分类） |
| `pynpxpipe.io.spikeglx` | 项目内部 | `SpikeGLXLoader.read_recording_date()`（Detect Date 按钮用） |

---

## 6. 入口

```toml
# pyproject.toml
[project.optional-dependencies]
ui = ["panel>=1.0"]

[project.scripts]
pynpxpipe-ui = "pynpxpipe.ui.app:main"
```

启动方式：
- `pynpxpipe-ui` — 直接启动浏览器
- `panel serve src/pynpxpipe/ui/app.py --show` — 开发模式

---

## 7. 测试策略

| 层次 | 方法 | 工具 |
|------|------|------|
| 组件单元测试 | 实例化各 component，mock AppState，验证 param 绑定和回调 | pytest + param |
| ProgressBridge 测试 | 模拟后台线程调用 callback，验证 AppState 属性更新 | pytest + threading |
| 集成测试 | `panel.io.server` 启动临时服务器，mock PipelineRunner，验证完整流程 | pytest + panel.io |
| 端到端（可选） | Playwright 操作浏览器，验证用户交互 | playwright |

### 测试矩阵 — A6 NWB filename regularization

**`tests/test_ui/test_state.py`**

| 测试名 | 覆盖点 |
|--------|--------|
| `test_appstate_has_experiment_recording_date_probe_plan_fields` | `AppState()` 实例拥有 `experiment=""`, `recording_date=""`, `probe_plan={"imec0": ""}` 默认值 |
| `test_session_id_property_returns_none_when_incomplete` | 任一字段（experiment / recording_date / subject_config / 某 probe 的 target_area）缺失时 `state.session_id is None` |
| `test_session_id_property_returns_sessionid_when_complete` | 全部字段齐全时 `state.session_id` 返回 `SessionID(date, subject, experiment, region)`，其中 `region` 由 `SessionID.derive_region(probe_plan)` 派生 |

**`tests/test_ui/test_session_form.py`**

| 测试名 | 覆盖点 |
|--------|--------|
| `test_session_form_has_experiment_input` | `SessionForm` 面板中存在 `experiment` TextInput 并绑定到 `state.experiment` |
| `test_detect_date_button_calls_read_recording_date` | 点击 Detect Date 按钮时用发现到的 `.ap.meta` 路径调用 `SpikeGLXLoader.read_recording_date`（通过 monkeypatch 验证 call args） |
| `test_detect_date_button_writes_to_state` | Detect Date 成功后 `state.recording_date` 被写入 stub 返回值（如 `"250417"`） |

**`tests/test_ui/test_app.py`**

| 测试名 | 覆盖点 |
|--------|--------|
| `test_left_column_includes_probe_region_editor` | `build_app()` 的左列布局在 SubjectForm 与 StageSelector 之间包含 `ProbeRegionEditor` 实例 |
| `test_run_panel_validates_experiment_nonempty` | `experiment=""` 时点击 Run → alert 显示 "Experiment name is required."，不调用 `SessionManager.create` |
| `test_run_panel_validates_recording_date_nonempty` | `recording_date=""` 时点击 Run → alert 显示 "Recording date is required..."，不调用 `SessionManager.create` |
| `test_run_panel_validates_probe_plan_nonempty` | `probe_plan={}` 或存在空 `target_area` → alert 显示对应消息，不调用 `SessionManager.create` |
| `test_session_manager_create_receives_experiment_probe_plan_date` | 全部字段齐全点击 Run 后 `SessionManager.create` 被调用时 `experiment=`/`probe_plan=`/`date=` 参数按 state 值传入 |
| `test_run_panel_displays_core_value_error` | `SessionManager.create` 抛 `ValueError("date must be 6 digits")` → alert 显示 `"Invalid configuration: date must be 6 digits"`，不启动线程（验证格式错误不在 UI 层拦截，而是由 core 抛出后由 UI 呈现） |

**`tests/test_ui/test_session_loader.py`**

| 测试名 | 覆盖点 |
|--------|--------|
| `test_load_session_restores_experiment` | `session.json` 中 `session_id.experiment` 读出后写入 `state.experiment` |
| `test_load_session_restores_recording_date` | `session.json` 中 `session_id.date` 读出后写入 `state.recording_date` |
| `test_load_session_restores_probe_plan` | `session.json` 中 `probe_plan` 读出后以 dict copy 写入 `state.probe_plan` |

---

## 8. 实施阶段对应关系

| 阶段 | Session 数 | 内容 | 产出文件 |
|------|-----------|------|----------|
| **A1** | 1 | pyproject.toml + 目录结构 + spike test（按钮+进度条+mock） | ui/__init__.py, app.py, state.py |
| **A2** | 2 | 5 个表单组件 + Subject YAML 加载 | components/session_form.py ~ stage_selector.py |
| **A3** | 2 | ProgressBridge + 线程执行 + 进度可视化 + 日志面板 | run_panel.py, progress_view.py, log_viewer.py |
| **A4** | 1 | Status 查看 + Reset + Session 恢复 | status_view.py, session_loader.py |
| **A5** | 1 | 布局整合 + 错误处理 + 入口命令 + 测试 | app.py 完善, tests/test_ui/ |
| **A6** | 1 | NWB filename 规整整合：AppState 新增 `experiment` / `recording_date` / `probe_plan` + `session_id` 派生属性；SessionForm 新增 experiment 输入 + Detect Date 按钮 + recording_date 输入；新建 `components/probe_region_editor.py` 并挂在左列 SubjectForm 与 StageSelector 之间；RunPanel 增加预执行校验与 `SessionManager.create(..., experiment=, probe_plan=, date=)` 调用；SessionLoader 回填三个新字段；补齐 §7 测试矩阵 | state.py, components/session_form.py, components/probe_region_editor.py, components/run_panel.py, components/session_loader.py, app.py, tests/test_ui/test_state.py, tests/test_ui/test_session_form.py, tests/test_ui/test_app.py, tests/test_ui/test_session_loader.py |
