# Spec: core/config.py — YAML 配置加载与验证

> 版本：0.1.0  
> 日期：2026-03-31  
> 状态：待实现

---

## 1. 目标

提供类型安全的 YAML 配置加载机制。

- 从 `config/pipeline.yaml` 和 `config/sorting.yaml` 加载配置
- 填充带默认值的 dataclass 对象返回给调用方
- `"auto"` 值**原样保留**（字符串存储），不在本模块解析，由后续 `ResourceDetector` 替换
- 验证字段合法性，非法时 raise `ConfigError`
- 配置文件缺失时**不报错**，使用内置默认值并记录 INFO 日志
- 支持通过 `merge_with_overrides()` 将 CLI 覆盖参数应用到已加载的 config

---

## 2. 依赖

```
core/errors.py      ← PynpxpipeError, ConfigError（本 spec 同步定义）
pyyaml              ← yaml.safe_load()
structlog           ← 结构化日志
```

**注意**：`core/errors.py` 是新文件，与 `core/config.py` 同时实现。`ConfigError` 定义在 `errors.py`，`config.py` 从那里 import。

---

## 3. core/errors.py — 异常类定义

```python
class PynpxpipeError(Exception):
    """所有 pynpxpipe 自定义异常的基类。"""

class ConfigError(PynpxpipeError):
    """配置字段值非法或结构错误。

    Attributes:
        field: 出错的字段路径，如 "resources.n_jobs"
        value: 出错的值
        reason: 人类可读的错误原因
    """
    def __init__(self, field: str, value: object, reason: str) -> None:
        self.field = field
        self.value = value
        self.reason = reason
        super().__init__(f"ConfigError [{field}={value!r}]: {reason}")
```

---

## 4. 公开 API

```python
def load_pipeline_config(config_path: Path | None = None) -> PipelineConfig:
    """从 pipeline.yaml 加载配置。文件缺失时使用内置默认值。"""

def load_sorting_config(config_path: Path | None = None) -> SortingConfig:
    """从 sorting.yaml 加载配置。文件缺失时使用内置默认值。"""

def load_subject_config(yaml_path: Path) -> SubjectConfig:
    """从 monkeys/*.yaml 加载实验动物信息。文件必须存在。"""

def merge_with_overrides(
    config: PipelineConfig | SortingConfig,
    overrides: dict,
) -> PipelineConfig | SortingConfig:
    """将 CLI 覆盖参数深度合并到已加载的 config 中，返回新对象。

    overrides 格式为嵌套 dict，键路径与 YAML 结构一致：
        {"resources": {"n_jobs": 8}, "parallel": {"enabled": True}}
    合并后执行相同的字段验证，验证失败 raise ConfigError。
    """
```

---

## 5. 完整数据类定义

所有 dataclass 均使用 `@dataclass`，字段都有 type hint 和默认值。

### 5.1 core/errors.py 中导入的基类（见第 3 节）

### 5.2 Pipeline 配置层级

```python
@dataclass
class ResourcesConfig:
    n_jobs: int | str = "auto"      # int ≥ 1 或 "auto"
    chunk_duration: str = "auto"    # "auto" 或 "{正数}s" 如 "1s"、"0.5s"
    max_memory: str = "auto"        # "auto" 或 "{正整数}G"/"M" 如 "32G"

@dataclass
class ParallelConfig:
    enabled: bool = False
    max_workers: int | str = "auto" # int ≥ 1 或 "auto"

@dataclass
class BandpassConfig:
    freq_min: float = 300.0         # Hz，> 0 且 < freq_max
    freq_max: float = 6000.0        # Hz，> freq_min

@dataclass
class BadChannelConfig:
    method: str = "coherence+psd"          # 仅接受 "coherence+psd"（当前版本）
    dead_channel_threshold: float = 0.5    # 0 < x < 1

@dataclass
class CommonReferenceConfig:
    reference: str = "global"   # "global" | "local"
    operator: str = "median"    # "median" | "average"

@dataclass
class MotionCorrectionConfig:
    method: str | None = "dredge"       # "dredge" | "kilosort" | null（跳过）
    preset: str = "nonrigid_accurate"   # "rigid_fast" | "nonrigid_accurate"

@dataclass
class PreprocessConfig:
    bandpass: BandpassConfig = field(default_factory=BandpassConfig)
    bad_channel_detection: BadChannelConfig = field(default_factory=BadChannelConfig)
    common_reference: CommonReferenceConfig = field(default_factory=CommonReferenceConfig)
    motion_correction: MotionCorrectionConfig = field(default_factory=MotionCorrectionConfig)

@dataclass
class CurationConfig:
    isi_violation_ratio_max: float = 2.0   # NOISE 阈值：ISI violation ratio 上限
    amplitude_cutoff_max: float = 0.5      # NOISE 阈值：amplitude cutoff 上限
    presence_ratio_min: float = 0.5        # NOISE 阈值：presence ratio 下限
    snr_min: float = 0.3                   # NOISE 阈值：SNR 下限
    good_isi_max: float = 0.1             # SUA 分类：ISI violation ratio 上限
    good_snr_min: float = 3.0             # SUA 分类：SNR 下限
    use_bombcell: bool = True             # True: bombcell_label_units() 四分类；False: 手动阈值 fallback

@dataclass
class SyncConfig:
    imec_sync_bit: int = 6                                     # IMEC AP 数字通道 sync bit（0–7）
    nidq_sync_bit: int = 0                                     # NIDQ 数字通道 sync bit（0–7）
    event_bits: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5, 6, 7])
    max_time_error_ms: float = 17.0                            # > 0
    trial_count_tolerance: int = 2                             # ≥ 0
    photodiode_channel_index: int = 0                          # ≥ 0
    monitor_delay_ms: float = -5.0                             # 无约束，通常 -20 ~ 0
    stim_onset_code: int = 64                                  # 0–255
    imec_sync_code: int = 64                                   # 0–255
    generate_plots: bool = True
    gap_threshold_ms: float | None = 1200.0                    # 丢脉冲检测阈值，None 禁用修复
    trial_start_bit: int | None = None                         # trial start 的 NIDQ bit；None 时自动检测
    pd_window_pre_ms: float = 10.0                             # Photodiode 基线窗口（ms）
    pd_window_post_ms: float = 100.0                           # Photodiode 检测窗口（ms）
    pd_min_signal_variance: float = 1e-6                       # Photodiode 无信号判定阈值

@dataclass
class EyeValidationConfig:
    enabled: bool = True
    eye_threshold: float = 0.999                               # 注视比例阈值（cf. MATLAB eye_thres=0.999）

@dataclass
class PostprocessConfig:
    slay_pre_s: float = 0.05                                   # SLAY 预刺激窗口（秒），fallback 默认值
    slay_post_s: float = 0.30                                  # SLAY 刺激后窗口（秒），fallback 默认值
    pre_onset_ms: float = 50.0                                 # 动态 SLAY 窗口的 pre-stimulus（ms）
    eye_validation: EyeValidationConfig = field(default_factory=EyeValidationConfig)

@dataclass
class MergeConfig:
    enabled: bool = False                                      # auto-merge 默认关闭

@dataclass
class PipelineConfig:
    resources: ResourcesConfig = field(default_factory=ResourcesConfig)
    parallel: ParallelConfig = field(default_factory=ParallelConfig)
    preprocess: PreprocessConfig = field(default_factory=PreprocessConfig)
    curation: CurationConfig = field(default_factory=CurationConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    postprocess: PostprocessConfig = field(default_factory=PostprocessConfig)
    merge: MergeConfig = field(default_factory=MergeConfig)
```

### 5.3 Sorting 配置层级

```python
@dataclass
class SorterParams:
    nblocks: int = 0            # ≥ 0；默认 0（与 DREDge 互斥，精度优先）
    Th_learned: float = 7.0     # > 0
    do_CAR: bool = False
    batch_size: int | str = "auto"  # int ≥ 1 或 "auto"
    n_jobs: int = 1             # ≥ 1

@dataclass
class SorterConfig:
    name: str = "kilosort4"     # 非空字符串，SpikeInterface 可识别的 sorter 名称
    params: SorterParams = field(default_factory=SorterParams)

@dataclass
class ImportConfig:
    format: str = "kilosort4"           # "kilosort4" | "phy"
    paths: dict[str, Path] = field(default_factory=dict)  # probe_id → 外部 sorting 目录

@dataclass
class RandomSpikesConfig:
    max_spikes_per_unit: int = 500      # ≥ 1
    method: str = "uniform"             # "uniform" | "all" | "smart"

@dataclass
class WaveformConfig:
    ms_before: float = 1.0              # > 0
    ms_after: float = 2.0               # > 0

@dataclass
class AnalyzerConfig:
    random_spikes: RandomSpikesConfig = field(default_factory=RandomSpikesConfig)
    waveforms: WaveformConfig = field(default_factory=WaveformConfig)
    template_operators: list[str] = field(default_factory=lambda: ["average", "std"])
    unit_locations_method: str = "monopolar_triangulation"
    template_similarity_method: str = "cosine_similarity"

@dataclass
class SortingConfig:
    mode: str = "local"                         # "local" | "import"
    sorter: SorterConfig = field(default_factory=SorterConfig)
    import_cfg: ImportConfig = field(default_factory=ImportConfig)
    analyzer: AnalyzerConfig = field(default_factory=AnalyzerConfig)
```

### 5.4 Subject 配置

```python
@dataclass
class SubjectConfig:
    subject_id: str             # 必填，DANDI required
    description: str            # 必填
    species: str                # 必填，DANDI required，如 "Macaca mulatta"
    sex: str                    # 必填，"M" | "F" | "U" | "O"
    age: str                    # 必填，ISO 8601 duration 如 "P4Y"
    weight: str                 # 可选，含单位，如 "12.8kg"；缺失时为空字符串 ""
```

---

## 6. 验证规则（字段级）

验证在 `_validate_pipeline_config()` 和 `_validate_sorting_config()` 私有函数中实现，`load_*` 函数在填充 dataclass 后调用。

| 字段 | 规则 | 触发条件举例 |
|------|------|------------|
| `resources.n_jobs` | 若非 "auto"，则 `isinstance(v, int) and v >= 1` | `n_jobs: 0` |
| `resources.chunk_duration` | 若非 "auto"，则匹配 `r"^\d+\.?\d*s$"` | `chunk_duration: "abc"` |
| `resources.max_memory` | 若非 "auto"，则匹配 `r"^\d+[GM]$"` | `max_memory: "32GB"` |
| `parallel.max_workers` | 若非 "auto"，则 `isinstance(v, int) and v >= 1` | `max_workers: -1` |
| `bandpass.freq_min` | `> 0` 且 `< freq_max` | `freq_min: 0` 或 `freq_min >= freq_max` |
| `bandpass.freq_max` | `> freq_min` | `freq_max: 100` 当 `freq_min: 300` |
| `bad_channel_detection.dead_channel_threshold` | `0 < x < 1` | `threshold: 1.5` |
| `common_reference.reference` | `in {"global", "local"}` | `reference: "all"` |
| `common_reference.operator` | `in {"median", "average"}` | `operator: "mean"` |
| `motion_correction.method` | `in {"dredge", "kilosort", None}` | `method: "dredge2"` |
| `motion_correction.preset` | `in {"rigid_fast", "nonrigid_accurate"}` | `preset: "fast"` |
| `curation.*_max` | `0.0 ≤ x ≤ 1.0` | `isi_violation_ratio_max: 1.5` |
| `curation.*_min` | `0.0 ≤ x ≤ 1.0` | `presence_ratio_min: -0.1` |
| `curation.snr_min` | `≥ 0.0` | `snr_min: -1` |
| `sync.sync_bit` | `0 ≤ x ≤ 7` | `sync_bit: 8` |
| `sync.event_bits` | 每个元素 `0 ≤ x ≤ 7`，非空 | `event_bits: [8]` |
| `sync.max_time_error_ms` | `> 0` | `max_time_error_ms: 0` |
| `sync.trial_count_tolerance` | `≥ 0` | `trial_count_tolerance: -1` |
| `sync.stim_onset_code` | `0 ≤ x ≤ 255` | `stim_onset_code: 300` |
| `sync.imec_sync_code` | `0 ≤ x ≤ 255` | `imec_sync_code: 300` |
| `sorter.params.nblocks` | `≥ 0` | `nblocks: -1` |
| `sorter.params.Th_learned` | `> 0` | `Th_learned: 0` |
| `sorter.params.batch_size` | 若非 "auto"，则 `isinstance(v, int) and v >= 1` | `batch_size: 0` |
| `sorter.params.n_jobs` | `≥ 1` | `n_jobs: 0` |
| `sorting.mode` | `in {"local", "import"}` | `mode: "both"` |
| `import_cfg.format` | `in {"kilosort4", "phy"}` | `format: "kilosort3"` |
| `analyzer.random_spikes.max_spikes_per_unit` | `≥ 1` | `max_spikes_per_unit: 0` |
| `analyzer.random_spikes.method` | `in {"uniform", "all", "smart"}` | `method: "random"` |
| `analyzer.waveforms.ms_before` | `> 0` | `ms_before: 0` |
| `analyzer.waveforms.ms_after` | `> 0` | `ms_after: -1` |
| `subject.sex` | `in {"M", "F", "U", "O"}` | `sex: "Male"` |
| `subject.age` | 匹配 `r"^P\d+[YMD]$"` (ISO 8601 duration) | `age: "4years"` |

**所有验证失败均 raise `ConfigError(field, value, reason)`**，其中 `field` 为点分路径如 `"resources.n_jobs"`。

---

## 7. 处理步骤

### 7.1 `load_pipeline_config(config_path)`

```
1. 若 config_path is None 或 文件不存在：
       log.info("pipeline.yaml not found, using defaults", path=config_path)
       raw = {}
   否则：
       raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

2. 逐层构建 dataclass（深度合并 raw 与 dataclass 默认值）：
   - _build_resources(raw.get("resources", {}))
   - _build_parallel(raw.get("parallel", {}))
   - _build_preprocess(raw.get("preprocess", {}))
   - _build_curation(raw.get("curation", {}))
   - _build_sync(raw.get("sync", {}))
   YAML 中存在但 dataclass 未定义的键：忽略（不 raise，记录 DEBUG 日志）

3. _validate_pipeline_config(config)  ← raise ConfigError on violation

4. return PipelineConfig(...)
```

### 7.2 `load_sorting_config(config_path)`

```
1. 同 7.1 步骤 1，文件缺失使用默认值

2. 逐层构建：
   - mode = raw.get("mode", "local")
   - _build_sorter(raw.get("sorter", {}))
   - _build_import_cfg(raw.get("import", {}))   # YAML key is "import" → Python attr import_cfg
   - _build_analyzer(raw.get("analyzer", {}))

3. _validate_sorting_config(config)

4. return SortingConfig(...)
```

**YAML 键名映射注意**：sorting.yaml 中 `import:` 键是 Python 保留字，加载时映射到 `import_cfg` 字段。

### 7.3 `load_subject_config(yaml_path)`

```
1. 若文件不存在：raise FileNotFoundError(yaml_path)

2. raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
   subject_raw = raw.get("Subject", raw)   # 兼容有/无顶层 "Subject:" 键的两种格式

3. 校验必填字段存在（缺失则 raise ConfigError）：
   必填：subject_id, description, species, sex, age
   可选：weight（缺失时默认 ""）

4. _validate_subject(subject_raw)

5. return SubjectConfig(...)
```

### 7.4 `merge_with_overrides(config, overrides)`

```
1. 将 config 深度转为 dict：_config_to_dict(config)

2. 深度合并 overrides 到 config_dict
   （overrides 中的叶节点覆盖 config_dict 中对应值；
    overrides 中的中间节点递归合并，不整体替换）

3. 根据 config 的类型（PipelineConfig 或 SortingConfig）重新构建 dataclass

4. 执行相同的 validate 步骤

5. return 新的 config 对象
```

---

## 8. "auto" 值的处理规则

`"auto"` 是字符串字面量，允许出现在以下字段：
- `resources.n_jobs`（类型 `int | str`）
- `resources.chunk_duration`（类型 `str`）
- `resources.max_memory`（类型 `str`）
- `parallel.max_workers`（类型 `int | str`）
- `sorter.params.batch_size`（类型 `int | str`）

**config.py 的职责**：将 `"auto"` 原样存储到 dataclass 字段，**不解析、不替换**。  
**ResourceDetector 的职责**（不在本模块）：稍后读取这些 `"auto"` 值并替换为实际整数/字符串。

验证逻辑对 `"auto"` 的处理：若字段类型为 `int | str`，当值为 `"auto"` 时直接跳过数值范围检查。

---

## 9. 未知键处理

YAML 文件中出现 dataclass 未定义的键时：
- **不报错，不 raise**
- 记录 `log.debug("unknown config key ignored", key=..., section=...)`
- 丢弃该键

这保证向后兼容：用户的旧配置文件包含已废弃字段时 pipeline 仍正常运行。

---

## 10. `_build_*` 辅助函数签名

实现时各 `_build_*` 函数应独立，方便单元测试：

```python
def _build_resources(raw: dict) -> ResourcesConfig: ...
def _build_parallel(raw: dict) -> ParallelConfig: ...
def _build_bandpass(raw: dict) -> BandpassConfig: ...
def _build_bad_channel(raw: dict) -> BadChannelConfig: ...
def _build_common_reference(raw: dict) -> CommonReferenceConfig: ...
def _build_motion_correction(raw: dict) -> MotionCorrectionConfig: ...
def _build_preprocess(raw: dict) -> PreprocessConfig: ...
def _build_curation(raw: dict) -> CurationConfig: ...
def _build_sync(raw: dict) -> SyncConfig: ...
def _build_sorter(raw: dict) -> SorterConfig: ...
def _build_import_cfg(raw: dict) -> ImportConfig: ...
def _build_analyzer(raw: dict) -> AnalyzerConfig: ...

def _validate_pipeline_config(config: PipelineConfig) -> None: ...  # raise ConfigError
def _validate_sorting_config(config: SortingConfig) -> None: ...    # raise ConfigError
def _validate_subject(raw: dict) -> None: ...                       # raise ConfigError

def _config_to_dict(config: PipelineConfig | SortingConfig) -> dict: ...
def _deep_merge(base: dict, override: dict) -> dict: ...
```

---

## 11. 测试要点（给实现者参考）

以下行为**每条都必须有对应的单元测试**：

1. `load_pipeline_config(None)` → 返回全默认值的 `PipelineConfig`，不抛异常
2. `load_pipeline_config(path)` 文件存在 → 正确加载每个字段（取 pipeline.yaml 中的值）
3. `load_pipeline_config(path)` 文件存在但字段缺失 → 该字段使用默认值
4. `"auto"` 字符串保留在 `n_jobs`、`chunk_duration`、`batch_size` 等字段中，不被替换
5. `n_jobs: 0` → raise `ConfigError(field="resources.n_jobs", ...)`
6. `freq_min: 8000, freq_max: 6000` → raise `ConfigError(field="preprocess.bandpass.freq_max", ...)` （freq_max 不满足 > freq_min 条件）
7. YAML 中出现未知键 → 静默忽略，不报错
8. YAML `import:` 键 → 正确映射到 `SortingConfig.import_cfg`
9. `merge_with_overrides(config, {"resources": {"n_jobs": 8}})` → 新对象中 `n_jobs == 8`，其他字段不变
10. `merge_with_overrides(config, {"resources": {"n_jobs": 0}})` → raise `ConfigError`
11. `load_subject_config(path)` 缺 `subject_id` → raise `ConfigError`
12. `load_subject_config(nonexistent)` → raise `FileNotFoundError`
13. `merge_with_overrides` 返回**新对象**，不修改原 config 对象

---

## 12. 与其他模块的接口

| 调用方 | 调用方式 |
|--------|---------|
| `pipelines/runner.py` | `load_pipeline_config(project_root / "config/pipeline.yaml")` |
| `pipelines/runner.py` | `load_sorting_config(project_root / "config/sorting.yaml")` |
| `cli/main.py` | `merge_with_overrides(config, cli_overrides_dict)` |
| `core/resources.py` | 读取 `config.resources.n_jobs` 等字段判断是否为 `"auto"` |
| `stages/*/` | 经由 `Session` 对象访问，不直接调用 load 函数 |

---

## 13. 与现有 skeleton 的差异（实现时需同步修改）

当前 `src/pynpxpipe/core/config.py` skeleton 与本 spec 的差异：

| 差异 | skeleton 现状 | spec 要求 |
|------|--------------|----------|
| `BadChannelConfig` | 缺失 | 新增 |
| `CommonReferenceConfig` | 缺失 | 新增 |
| `PreprocessConfig` 字段 | 仅有 bandpass + motion_correction | 补充 bad_channel_detection + common_reference |
| `RandomSpikesConfig` | 缺失（字段混在 WaveformConfig） | 新增，AnalyzerConfig 引用 |
| `WaveformConfig` | 含 max_spikes_per_unit | 移出到 RandomSpikesConfig |
| `AnalyzerConfig` | 缺失 template_operators | 新增 |
| `load_*` 函数体 | `raise NotImplementedError` | 按本 spec 实现 |
| `core/errors.py` | 不存在 | 新建，定义 PynpxpipeError + ConfigError |
| `merge_with_overrides` | 不存在 | 新增 |
