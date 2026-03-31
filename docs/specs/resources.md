# Spec: core/resources.py — 自动资源探测与参数推算

> 版本：0.1.0  
> 日期：2026-03-31  
> 状态：待实现  
> 设计依据：docs/resource_design.md

---

## 1. 目标

在 pipeline 启动时自动探测当前机器的硬件资源，推算最优参数值，替换 `pipeline.yaml` 中的 `"auto"` 字段。

- 自动探测 CPU 核心数、可用 RAM、GPU 显存、磁盘剩余空间
- 基于探测结果推算 `n_jobs`、`chunk_duration`、`max_workers`、`sorting_batch_size`
- 实现三级优先级：用户显式配置 > 自动探测值 > 硬编码兜底值
- 探测失败时**不 raise**，使用兜底值并写 WARNING 日志
- 探测结果写入结构化日志（JSON Lines），供审计追踪
- 无 UI 依赖：不含 print()，不含 click；CLI 层负责格式化显示

---

## 2. 依赖

```
psutil >= 5.9.0         ← CPU / RAM / Disk，必选依赖
pynvml (nvidia-ml-py)   ← GPU 探测，可选（ImportError 时降级到 nvidia-smi）
structlog               ← 结构化日志
subprocess              ← nvidia-smi fallback，标准库
platform, os            ← CPU 名称 / 核心数 fallback，标准库
datetime                ← 探测时间戳，标准库
```

**pyproject.toml 依赖配置**：
```toml
[project.dependencies]
"psutil>=5.9.0",

[project.optional-dependencies]
gpu = ["nvidia-ml-py>=12.535.0"]
```

---

## 3. 硬编码兜底值

```python
FALLBACK_N_JOBS: int = 4           # 适合 8 核以下机器
FALLBACK_CHUNK_DURATION: str = "1s"  # 44MB/chunk，任何系统都能承受
FALLBACK_MAX_WORKERS: int = 1       # 串行最安全
FALLBACK_BATCH_SIZE: int = 60000    # Kilosort4 官方默认值
```

---

## 4. 数据类定义

### 4.1 CPUInfo

```python
@dataclass
class CPUInfo:
    physical_cores: int | None   # 物理核心数，探测失败时为 None
    logical_processors: int      # 逻辑处理器数（含超线程），可靠
    frequency_max_mhz: float | None  # 最大频率 MHz，Windows VM 可能为 None
    name: str                    # CPU 型号字符串（platform.processor()）
```

### 4.2 RAMInfo

```python
@dataclass
class RAMInfo:
    total_gb: float       # 总物理 RAM（GB）
    available_gb: float   # 当前可用 RAM，含可回收缓存（比 free 准确）
    used_percent: float   # 当前使用率（%）
```

### 4.3 GPUInfo

```python
@dataclass
class GPUInfo:
    index: int                    # GPU 设备索引（0-based）
    name: str                     # GPU 型号名
    vram_total_gb: float          # VRAM 总量（GB）
    vram_free_gb: float           # 当前空闲 VRAM（GB）
    cuda_available: bool          # CUDA 是否可用
    driver_version: str | None    # NVIDIA 驱动版本字符串
    detection_method: str         # "pynvml" | "nvidia-smi" | "torch"
```

### 4.4 DiskInfo

```python
@dataclass
class DiskInfo:
    session_dir: Path
    session_dir_free_gb: float
    output_dir: Path
    output_dir_free_gb: float
    estimated_required_gb: float | None  # 预估所需磁盘空间
```

### 4.5 HardwareProfile

```python
@dataclass
class HardwareProfile:
    cpu: CPUInfo
    ram: RAMInfo
    gpus: list[GPUInfo]       # 空列表 = 无 CUDA GPU
    disk: DiskInfo
    detection_timestamp: str  # ISO 8601
    warnings: list[str] = field(default_factory=list)

    @property
    def primary_gpu(self) -> GPUInfo | None:
        """返回第一个 GPU，无 GPU 时返回 None。"""

    def to_log_dict(self) -> dict:
        """序列化为 JSON 友好的嵌套 dict，用于结构化日志。"""

    def to_display_lines(self) -> list[str]:
        """格式化为人类可读行列表（无 ANSI 代码），供 CLI 层使用。"""
```

### 4.6 RecommendedParams

```python
@dataclass
class RecommendedParams:
    n_jobs: int
    chunk_duration: str      # 如 "2s"
    max_workers: int
    sorting_batch_size: int
    notes: list[str] = field(default_factory=list)  # 推算依据说明
```

---

## 5. 主要类 API

### 5.1 ResourceDetector

```python
class ResourceDetector:
    def __init__(self, session_dir: Path, output_dir: Path) -> None: ...
    def detect(self) -> HardwareProfile: ...
    def recommend(self, profile: HardwareProfile, probes: list[ProbeInfo] | None = None) -> RecommendedParams: ...
    @classmethod
    def cached_detect(cls, session_dir: Path, output_dir: Path) -> HardwareProfile: ...
```

### 5.2 ResourceConfig

```python
class ResourceConfig:
    def __init__(self, profile: HardwareProfile, recommended: RecommendedParams) -> None: ...
    def resolve_pipeline_config(self, config: PipelineConfig) -> PipelineConfig: ...
    def resolve_sorting_config(self, config: SortingConfig) -> SortingConfig: ...
    def validate_user_config(self, config: PipelineConfig, sorting_config: SortingConfig) -> list[str]: ...
    @staticmethod
    def _resolve_value(config_value, detected_value, fallback, field_name) -> tuple[int | str, str]: ...
```

---

## 6. 探测子步骤实现

### 6.1 `_detect_cpu()` → CPUInfo

```python
import psutil, platform, os

physical_cores = psutil.cpu_count(logical=False)
if physical_cores is None:
    physical_cores = (os.cpu_count() or 2) // 2  # Windows fallback

logical_processors = psutil.cpu_count(logical=True) or 1

try:
    freq = psutil.cpu_freq()
    frequency_max_mhz = freq.max if freq else None
except Exception:
    frequency_max_mhz = None  # 不影响参数推算

name = platform.processor() or "unknown"

# 可选警告：当前负载 > 70%
try:
    current_load = psutil.cpu_percent(interval=0.1)
    if current_load > 70:
        warnings.append(f"CPU load is {current_load:.0f}%, recommendations may be conservative")
except Exception:
    pass

return CPUInfo(physical_cores, logical_processors, frequency_max_mhz, name)
```

**Windows 特有问题**：
- Intel 12代+大小核混合架构：`cpu_count(logical=False)` 可能返回总核心数（含 E 核），语义模糊，但无需特殊处理
- VM 环境：`cpu_count(logical=False)` 可能返回 None → fallback 到 `os.cpu_count() // 2`

### 6.2 `_detect_ram()` → RAMInfo

```python
mem = psutil.virtual_memory()
return RAMInfo(
    total_gb=mem.total / 1e9,
    available_gb=mem.available / 1e9,
    used_percent=mem.percent,
)
```

**注意**：不使用 `psutil.swap_memory()`——swap 不适合用于推算 chunk_duration。

### 6.3 `_detect_gpus()` → list[GPUInfo]

GPU 探测采用三级 fallback 策略：

```python
def _detect_gpus(self) -> list[GPUInfo]:
    result = self._try_detect_gpu_pynvml()
    if result is not None:
        return result

    result = self._try_detect_gpu_nvidia_smi()
    if result is not None:
        return result

    result = self._try_detect_gpu_torch()
    if result is not None:
        return result

    self._warnings.append("No CUDA GPU detected; sorting will use CPU mode")
    return []
```

**Level 1 — pynvml**：
```python
def _try_detect_gpu_pynvml(self) -> list[GPUInfo] | None:
    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        gpus = []
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            name = pynvml.nvmlDeviceGetName(h)
            if isinstance(name, bytes):
                name = name.decode()
            driver = pynvml.nvmlSystemGetDriverVersion()
            if isinstance(driver, bytes):
                driver = driver.decode()
            gpus.append(GPUInfo(i, name, mem.total/1e9, mem.free/1e9, True, driver, "pynvml"))
        pynvml.nvmlShutdown()
        return gpus
    except Exception:
        return None
```

**Level 2 — nvidia-smi subprocess**：
```
nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version
           --format=csv,noheader,nounits
```
解析 CSV 输出（单位 MiB），转换为 GB。Windows 路径：优先系统 PATH，再尝试
`C:\Windows\System32\DriverStore\FileRepository\` 和
`C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe`。

**Level 3 — torch.cuda**：
```python
def _try_detect_gpu_torch(self) -> list[GPUInfo] | None:
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        # 只在 torch 已安装时尝试
        ...
    except ImportError:
        return None
```

### 6.4 `_detect_disk()` → DiskInfo

```python
session_usage = psutil.disk_usage(str(self._session_dir))
output_usage = psutil.disk_usage(str(self._output_dir))

# 预估所需空间（见 docs/resource_design.md §1.4）
try:
    raw_ap_size_gb = sum(p.stat().st_size for p in session_dir.rglob("*.ap.bin")) / 1e9
    n_probes = max(1, len(list(session_dir.glob("imec*"))))
    estimated_required_gb = (raw_ap_size_gb * 0.4 + 2 + raw_ap_size_gb * 0.05) * n_probes
except Exception:
    estimated_required_gb = None

# 磁盘空间警告
if estimated_required_gb and output_usage.free/1e9 < estimated_required_gb * 1.2:
    warnings.append(f"Low disk space: need ~{estimated_required_gb:.0f}GB, only {output_usage.free/1e9:.0f}GB free")
```

---

## 7. 参数推算规则

推算基准常量（从 ProbeInfo 读取，ProbeInfo 为 None 时用保守默认值）：

```python
n_channels  = probes[0].n_channels if probes else 384
sample_rate = probes[0].sample_rate if probes else 30000.0
bytes_per_sample = 4   # float32
pipeline_depth = 5     # 保守上限（5 个内存副本）
bytes_per_sec_per_job = n_channels * sample_rate * bytes_per_sample * pipeline_depth
```

### 7.1 `_recommend_chunk_duration()` → (str, str)

```
memory_budget_bytes = available_ram_bytes × 0.40
bytes_per_chunk = memory_budget_bytes / n_jobs_estimate
chunk_raw_s = bytes_per_chunk / bytes_per_sec_per_job
chunk_raw_s = clamp(chunk_raw_s, min=0.5, max=5.0)

离散化规则：
  chunk_raw_s >= 4.0  → "5s"
  chunk_raw_s >= 1.5  → "2s"
  chunk_raw_s >= 0.8  → "1s"
  否则               → "0.5s"
```

### 7.2 `_recommend_n_jobs()` → (int, str)

```
# CPU 约束
physical = cpu.physical_cores or (os.cpu_count() // 2) or 1
n_jobs_cpu = max(1, physical - 2)

# 内存约束
chunk_s = float(chunk_str[:-1])  # "2s" → 2.0
memory_per_job = bytes_per_sec_per_job × chunk_s
n_jobs_mem = max(1, int(available_ram_bytes × 0.60 / memory_per_job))

# 取较小值，上限 16
n_jobs = min(n_jobs_cpu, n_jobs_mem, 16)
```

note_string 说明限制因素（CPU 还是内存）。

### 7.3 `_recommend_max_workers()` → (int, str)

```
PER_PROBE_PEAK_GB = 5.0
max_by_memory = max(1, int(available_ram_gb × 0.70 / PER_PROBE_PEAK_GB))
max_by_probes = len(probes) if probes else 1
max_workers = min(max_by_memory, max_by_probes, 4)
```

**注意**：sort stage 始终强制串行（max_workers=1），由 SortStage 自身实现，ResourceDetector 推算的是 preprocess/curate/postprocess 阶段的建议值。

### 7.4 `_recommend_batch_size()` → (int, str)

```
VRAM_OVERHEAD_GB = 2.0
BYTES_PER_SAMPLE_VRAM = 384 × 4 × 10  # ≈ 15,360 bytes/sample

vram_for_batch_bytes = max(0, vram_free_gb - VRAM_OVERHEAD_GB) × 1024**3 × 0.80
batch_size_raw = int(vram_for_batch_bytes / BYTES_PER_SAMPLE_VRAM)

离散化规则：
  >= 60000 → 60000  (官方默认，≥8GB VRAM)
  >= 40000 → 40000  (5-8GB VRAM)
  >= 30000 → 30000  (3-5GB VRAM)
  >= 15000 → 15000  (1.5-3GB VRAM)
  否则     → 60000  (无 GPU，CPU 模式，batch_size 无实际意义)
```

---

## 8. 三级优先级：`ResourceConfig._resolve_value()`

```python
@staticmethod
def _resolve_value(
    config_value: int | str,
    detected_value: int | str | None,
    fallback: int | str,
    field_name: str,
) -> tuple[int | str, str]:
    """
    Returns: (resolved_value, source) where source is one of:
        "user_config"       - 用户在 yaml 中显式设置（非 "auto"）
        "auto_detected"     - ResourceDetector 推算成功
        "hardcoded_default" - 兜底值
    """
    if config_value != "auto":
        return config_value, "user_config"
    if detected_value is not None:
        return detected_value, "auto_detected"
    return fallback, "hardcoded_default"
```

`resolve_pipeline_config()` 和 `resolve_sorting_config()` 对每个 "auto" 字段调用此方法，返回**新的** config 对象（不修改原对象）。

---

## 9. 日志输出格式

`detect()` 完成后写入一条 `resource_detection` 事件（通过 structlog）：

```json
{
  "event": "resource_detection",
  "timestamp": "2026-03-31T10:00:00.000000",
  "hardware": {
    "cpu": {
      "physical_cores": 14,
      "logical_processors": 20,
      "frequency_max_mhz": 5200.0,
      "name": "Intel Core i9-13900K"
    },
    "ram": {
      "total_gb": 64.0,
      "available_gb": 47.3,
      "used_percent": 26.1
    },
    "gpus": [{
      "index": 0,
      "name": "NVIDIA GeForce RTX 3090",
      "vram_total_gb": 24.0,
      "vram_free_gb": 22.1,
      "cuda_available": true,
      "driver_version": "535.104.05",
      "detection_method": "pynvml"
    }],
    "disk": {
      "session_dir_free_gb": 3200.0,
      "output_dir_free_gb": 1240.5,
      "estimated_required_gb": 480.0
    }
  },
  "recommended": {
    "n_jobs": 12,
    "chunk_duration": "2s",
    "max_workers": 2,
    "sorting_batch_size": 60000,
    "notes": ["n_jobs: CPU-bound (14 physical cores → 12)", "chunk_duration: RAM-bound (47.3GB → 2s)"]
  },
  "warnings": []
}
```

`HardwareProfile.to_log_dict()` 输出的格式与 `"hardware"` 键下的嵌套 dict 相同。

---

## 10. `to_display_lines()` 格式（CLI 专用）

`HardwareProfile.to_display_lines()` 返回字符串列表，不含 ANSI，不含 print()：

```
─────────────────────────────────────────────────
  pynpxpipe resource check
─────────────────────────────────────────────────
  CPU   │ Intel Core i9-13900K
        │ 14 physical cores (20 logical)  @  5.2 GHz
  RAM   │ 64.0 GB total  │  47.3 GB available
  GPU   │ NVIDIA RTX 3090  │  24.0 GB VRAM  │  22.1 GB free
  Disk  │ output → F:\data\out  │  1240 GB free
─────────────────────────────────────────────────
```

CLI 层（`cli/main.py`）负责 `click.echo("\n".join(profile.to_display_lines()))`。

---

## 11. 探测时机与缓存

- **探测时机**：`PipelineRunner.__init__()` 中调用，在任何 stage 开始前
- **缓存**：`cached_detect()` 类方法，同一 Python 进程内缓存探测结果（`_cache: dict[tuple, HardwareProfile]`）
- **探测耗时目标**：< 2 秒（含 GPU 初始化）
- 缓存键：`(session_dir, output_dir)`（均转为 `Path` 再 hash）

---

## 12. 测试要点

以下行为**每条都必须有对应的单元测试**（使用 `unittest.mock.patch` 模拟 psutil）：

1. `_detect_cpu()` — `psutil.cpu_count(logical=False)` 返回 None 时 fallback 到 `os.cpu_count() // 2`
2. `_detect_cpu()` — `psutil.cpu_freq()` 返回 None 时 `frequency_max_mhz` 为 None，不 raise
3. `_detect_ram()` — 正常返回，total_gb 单位正确（bytes → GB）
4. `_detect_gpus()` — pynvml 可用时返回 GPUInfo 列表，detection_method="pynvml"
5. `_detect_gpus()` — pynvml 不可用（ImportError），降级到 nvidia-smi
6. `_detect_gpus()` — pynvml 和 nvidia-smi 均失败，降级到 torch
7. `_detect_gpus()` — 三级全部失败，返回空列表，warnings 中含相关消息
8. `_detect_disk()` — 估算所需空间低于可用空间时不产生警告
9. `_detect_disk()` — 估算所需空间 > 可用 × 1.2 时 warnings 非空
10. `detect()` 中某个子步骤 raise → 该字段用保守默认，其余字段正常探测（不整体失败）
11. `_recommend_chunk_duration()` — 64GB RAM 推算结果为 "5s"
12. `_recommend_n_jobs()` — 验证 CPU 约束和内存约束各自为瓶颈时的正确取值
13. `_recommend_max_workers()` — 上限 4，不超过探针数
14. `_recommend_batch_size()` — 无 GPU 时返回 FALLBACK_BATCH_SIZE=60000
15. `_recommend_batch_size()` — 3GB 空闲 VRAM 对应 batch_size=30000
16. `ResourceConfig._resolve_value()` — config_value 非 "auto" → source="user_config"
17. `ResourceConfig._resolve_value()` — config_value="auto", detected=None → source="hardcoded_default"
18. `ResourceConfig.resolve_pipeline_config()` — 返回新对象，不修改原 config
19. `ResourceConfig.validate_user_config()` — n_jobs > physical_cores 时返回非空 warnings 列表
20. `cached_detect()` — 第二次调用不触发实际探测（mock detect 只被调用一次）

---

## 13. 与其他模块的接口

| 调用方 | 调用方式 |
|--------|---------|
| `pipelines/runner.py` | `ResourceDetector(session_dir, output_dir).detect()` → `ResourceConfig(...).resolve_pipeline_config(config)` |
| `cli/main.py` | `profile.to_display_lines()` → `click.echo()` |
| `stages/preprocess.py` | 通过 Session 访问已解析的 config（n_jobs, chunk_duration），不直接调用 ResourceDetector |
| `stages/sort.py` | 同上（batch_size 已在 runner.py 中解析到 sorting_config） |
| `core/config.py` | `config.resources.n_jobs == "auto"` 时 ResourceConfig 替换为实际值 |

---

## 14. 与现有 skeleton 的差异（实现时需同步修改）

| 差异 | skeleton 现状 | spec 要求 |
|------|--------------|----------|
| `ResourceDetector.__init__` 缓存机制 | 未定义 | 新增类变量 `_cache: dict = {}` 用于 `cached_detect` |
| `HardwareProfile.to_log_dict()` | raise NotImplementedError | 按第 9 节格式实现 |
| `HardwareProfile.to_display_lines()` | raise NotImplementedError | 按第 10 节格式实现 |
| `nvidia-smi` Windows 固定路径 fallback | 未定义 | 见第 6.3 节 Level 2 |
| `probes=None` 时 recommend() 使用保守默认 | 未定义 | 384ch, 30kHz |
| `_resolve_value` 返回值 | 类型注解为 `tuple[int | str, str]` | source 字符串枚举值须固定为三个值之一 |
