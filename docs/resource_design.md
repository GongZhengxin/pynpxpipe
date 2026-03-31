# pynpxpipe 自动资源探测机制设计文档

> 版本：0.1.0  
> 日期：2026-03-31  
> 适用文件：`core/resources.py`，`config/pipeline.yaml`

---

## 1. 探测项目清单

### 1.1 CPU

| 指标 | Python API | 返回值 | Windows 注意事项 |
|------|-----------|--------|-----------------|
| 物理核心数 | `psutil.cpu_count(logical=False)` | `int \| None` | Intel 12代+ 大小核混合架构下可能返回总核心数（含 E 核），语义模糊；返回 None 时 fallback 到 `os.cpu_count()` |
| 逻辑处理器数 | `psutil.cpu_count(logical=True)` | `int` | 超线程下 = 物理核×2，可靠 |
| 最大频率 (MHz) | `psutil.cpu_freq().max` | `float \| None` | **Windows 上可返回 None**（尤其在 VM 或频率缩放被 BIOS 禁用时）；返回 None 时跳过，不影响参数推算 |
| CPU 名称 | `platform.processor()` | `str` | Windows 返回详细字符串（如 "Intel64 Family 6..."），可用；Linux 常返回空字符串 |
| 当前负载 | `psutil.cpu_percent(interval=0.5)` | `float` | 探测前采样 0.5s，若负载 >70% 记录警告 |

### 1.2 内存 (RAM)

| 指标 | Python API | 返回值 | 备注 |
|------|-----------|--------|------|
| 总物理内存 | `psutil.virtual_memory().total` | `int` (bytes) | 可靠，全平台一致 |
| 当前可用内存 | `psutil.virtual_memory().available` | `int` (bytes) | 包含可回收缓存，比 `free` 更准确 |
| 内存使用率 | `psutil.virtual_memory().percent` | `float` | 供警告阈值判断 |

> **注意**：不使用 `psutil.swap_memory()`——swap 不适合用于推算 SI 的 chunk_duration，SI 在 swap 上运行会导致严重性能下降。

### 1.3 GPU

GPU 探测采用**三级 fallback 策略**，以降低依赖：

```
Level 1: pynvml (nvidia-ml-py)   ← 最轻量，仅需 NVIDIA 驱动
Level 2: nvidia-smi subprocess   ← 无需 Python 包，需 PATH 中有 nvidia-smi.exe
Level 3: torch.cuda              ← 最重，仅当 torch 已安装时使用
Level 4: 无 GPU                  ← 返回空列表，sorting 只能用 CPU 模式
```

| 指标 | pynvml API | 备注 |
|------|-----------|------|
| GPU 名称 | `pynvml.nvmlDeviceGetName(handle)` | 返回 bytes，需 .decode() |
| VRAM 总量 | `pynvml.nvmlDeviceGetMemoryInfo(handle).total` | bytes |
| VRAM 空闲 | `pynvml.nvmlDeviceGetMemoryInfo(handle).free` | bytes |
| CUDA 驱动版本 | `pynvml.nvmlSystemGetDriverVersion()` | str |
| GPU 数量 | `pynvml.nvmlDeviceGetCount()` | int |

**nvidia-smi fallback 命令**：
```
nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version
           --format=csv,noheader,nounits
```
解析 CSV 输出，单位为 MiB。

**Windows 兼容性**：
- `nvidia-smi.exe` 通常在 `C:\Windows\System32\DriverStore\FileRepository\nv_dispi.inf_xxx\` 或 `C:\Program Files\NVIDIA Corporation\NVSMI\`，较新版驱动会自动加入 PATH
- 若以上均失败，应记录"GPU 未检测到，sorting 将使用 CPU 模式"并继续，**不报错**

### 1.4 磁盘

| 指标 | Python API | 备注 |
|------|-----------|------|
| 输出目录可用空间 | `psutil.disk_usage(str(output_dir)).free` | 必须等 output_dir 创建后调用 |
| 原始数据目录可用空间 | `psutil.disk_usage(str(session_dir)).free` | 预检查是否有足够读取空间 |
| 估算所需空间 | 自定义计算（见下方公式） | — |

**磁盘类型（SSD vs HDD）**：
- Windows 下检测需要 WMI（管理员权限）或 `ctypes.windll`（复杂），**不实现**
- 改为通过**随机读写测速**估算：写入 100MB 临时文件测量带宽
  - > 200 MB/s → 推测为 SSD，记录日志
  - ≤ 200 MB/s → 推测为 HDD，警告可能影响 Zarr 写入性能
  - 此测速为**可选**，默认关闭（`detect_disk_type: false`）

**预估所需磁盘空间**（探测时输出警告）：

```
raw_ap_size_gb  = bin_file_size / 1e9
zarr_size_gb    = raw_ap_size_gb × 0.4     # 预处理后 Zarr（float32 + 压缩 ≈ 40%）
sorting_size_gb = 2                         # kilosort4 输出（固定约 1-2 GB）
nwb_size_gb     = raw_ap_size_gb × 0.05    # waveforms + units + behavior（约 5%）

required_gb = (zarr_size_gb + sorting_size_gb + nwb_size_gb) × n_probes
```

若 `disk_free_gb < required_gb × 1.2`（留 20% 余量），记录 **WARNING**。

### 1.5 Windows 特有兼容性问题汇总

| 问题 | 影响项 | 处理方式 |
|------|-------|---------|
| `psutil.cpu_count(logical=False)` 返回 None | 物理核心数 | Fallback: `os.cpu_count() // 2`（假设超线程） |
| `psutil.cpu_freq()` 返回 None | CPU 频率 | 跳过频率字段，不影响参数推算 |
| 长路径限制（MAX_PATH = 260）| Zarr 写入路径 | 在 explore 阶段检查 `len(str(output_dir)) + 50`，超限时警告 |
| `nvidia-smi.exe` 不在 PATH | GPU 探测 | 尝试两个固定路径后 fallback 到 torch |
| `psutil.disk_io_counters()` 在某些 Windows 版本返回 None | 磁盘 I/O 统计 | 捕获异常，跳过磁盘速度测试 |
| 进程权限不足（WMI 查询） | 磁盘类型 | 不实现 WMI，改用测速估算（可选） |

---

## 2. 参数推算规则

### 2.1 数据参数基准

本 pipeline 处理 Neuropixels 1.0 数据，在推算前先读取 `ProbeInfo` 获取实际参数（不硬编码）：

```
n_channels  = probe.n_channels      # 通常 384（imec0.ap 的 saved channels）
sample_rate = probe.sample_rate     # 从 meta 读取，通常 30000 Hz
bytes_per_sample = 4                # float32（SpikeInterface 内部表示）
```

**内存估算基准（SI 预处理链，每秒数据每个工作线程）**：

```
pipeline_depth = 5   # raw → filter → CMR → motion → zarr_buffer，粗估 5 个内存副本
bytes_per_sec_per_job = n_channels × sample_rate × bytes_per_sample × pipeline_depth
                      = 384 × 30000 × 4 × 5
                      = 230,400,000 bytes/s  ≈ 220 MB/s (per worker)
```

这是保守上限；实际 SI lazy recording 通过生成器传递，峰值通常为 2-3×（而不是 5×）。**使用 5× 作为安全系数**。

---

### 2.2 `chunk_duration` 推算

**核心约束**：n_jobs 个工作线程同时处于内存中的数据量 ≤ available_RAM × 40%

```
memory_budget_bytes = available_ram_bytes × 0.40
# 各工作线程独立处理一个 chunk，同时有 n_jobs 个 chunk 在内存
bytes_per_chunk = memory_budget_bytes / n_jobs
chunk_duration_s = bytes_per_chunk / bytes_per_sec_per_job
```

**对 n_jobs=8 的典型计算**（384ch, 30kHz）：

| 可用 RAM | memory_budget | bytes_per_chunk | chunk_duration_s | 最终取值 |
|---------|-------------|----------------|-----------------|---------|
| 8 GB  | 3.2 GB | 400 MB | 1.8s | **1s** |
| 16 GB | 6.4 GB | 800 MB | 3.6s | **2s** |
| 32 GB | 12.8 GB | 1.6 GB | 7.3s | **5s** |
| 64 GB | 25.6 GB | 3.2 GB | 14.5s | **5s** |

**取值规则**（离散化，减少配置复杂性）：

```
chunk_raw_s = memory_budget_bytes / (n_jobs × bytes_per_sec_per_job)
chunk_raw_s = clamp(chunk_raw_s, min=0.5, max=5.0)

if   chunk_raw_s >= 4.0: chunk_str = "5s"
elif chunk_raw_s >= 1.5: chunk_str = "2s"
elif chunk_raw_s >= 0.8: chunk_str = "1s"
else:                    chunk_str = "0.5s"
```

**与数据文件大小的关系**：
- 文件大小不影响 chunk_duration 的计算（chunk_duration 只控制单次读取量）
- 大文件唯一的影响是运行时间更长，不需要调整 chunk 大小
- 例外：若文件极大（>400GB）且 RAM 极小（<8GB），可能需要减小 chunk 以避免 Zarr 写入超时，此时记录警告提示用户减小 n_jobs

---

### 2.3 `n_jobs` 推算

SpikeInterface 的 n_jobs 控制预处理和 waveform 提取的内部并行线程数。

**推算步骤**：

```python
# Step 1: CPU 约束
physical_cores = psutil.cpu_count(logical=False) or (cpu_count() // 2) or 1
n_jobs_cpu = max(1, physical_cores - 2)   # 留 2 个核给 OS 和 I/O

# Step 2: 内存约束（基于已确定的 chunk_duration）
chunk_s = parse_duration(chunk_str)   # e.g. "2s" → 2.0
memory_per_job = bytes_per_sec_per_job × chunk_s  # ≈ 440 MB for 2s
n_jobs_mem = max(1, int(available_ram_bytes × 0.60 / memory_per_job))
# 0.60 而不是 0.40：内存预算更宽松（0.40 是上限，0.60 的余量包含了 OS、Zarr 缓冲等）

# Step 3: 取较小值
n_jobs = min(n_jobs_cpu, n_jobs_mem)

# Step 4: 上限
n_jobs = min(n_jobs, 16)  # SpikeInterface 超过 16 线程几乎无收益
```

**数据文件大小对 n_jobs 的影响**：
- 小文件（20-60GB，约 900-2600 秒）：n_jobs 主要受 CPU 限制，可用全部核心
- 大文件（400-500GB，约 17000-21700 秒）：I/O 可能成为瓶颈，n_jobs 超过 SSD 带宽饱和点（通常 4-8 核）无益；但 SpikeInterface 内部已有 I/O 调度，无需额外限制

---

### 2.4 `max_workers`（多 probe 并行）推算

每个 probe 的 worker 进程在 preprocess 阶段的峰值内存估算：

```
per_probe_peak_gb ≈ zarr_read_buffer(2GB) + SI_processing(2GB) + zarr_write_buffer(1GB)
                  = 5 GB
```

**推算规则**：

```python
PER_PROBE_PEAK_GB = 5.0

max_by_memory = max(1, int(available_ram_gb × 0.70 / PER_PROBE_PEAK_GB))
max_by_probes = len(session.probes)
max_workers = min(max_by_memory, max_by_probes, 4)   # 硬上限 4

# sort stage 特殊处理：始终强制 max_workers = 1（GPU 排他）
# 这由 SortStage 自身实现，ResourceDetector 只输出 preprocess/curate/postprocess 的建议值
```

**示例**（2 探针会话）：

| 可用 RAM | max_by_memory | max_by_probes | max_workers | 备注 |
|---------|-------------|-------------|-----------|------|
| 8 GB  | 1 | 2 | 1 | 内存不足，强制串行 |
| 16 GB | 2 | 2 | 2 | 刚好能并行 2 探针 |
| 32 GB | 4 | 2 | 2 | 受探针数限制 |
| 64 GB | 8 | 4 | 4 | 上限 4 |

---

### 2.5 Kilosort4 `batch_size` 推算

Kilosort4 的 `NT`（batch_size 参数，单位：采样点数）直接决定 GPU VRAM 消耗。

**VRAM 使用估算**（384ch，NT 样本数）：

```
vram_per_batch_bytes ≈ NT × n_channels × 4 bytes × internal_buffer_factor(≈10)
                     = NT × 384 × 4 × 10
                     = NT × 15,360 bytes

For NT=60000: 60000 × 15360 = 921,600,000 bytes ≈ 880 MB
```

实际 Kilosort4 在 384ch 下消耗约 5-8 GB VRAM（包含模型权重、临时缓冲等）。

**推算公式**：

```python
VRAM_OVERHEAD_GB = 2.0   # 模型权重 + 固定缓冲（与 batch_size 无关）
BYTES_PER_SAMPLE_VRAM = 384 × 4 × 10  # ≈ 15.4 KB per sample

# 可用于 batch 的 VRAM
vram_for_batch_bytes = max(0, vram_free_gb - VRAM_OVERHEAD_GB) × 1024**3 × 0.80
# 0.80 是安全系数：VRAM 接近满时 CUDA 内存碎片导致 OOM

batch_size_raw = int(vram_for_batch_bytes / BYTES_PER_SAMPLE_VRAM)

# 离散化到 Kilosort4 推荐档位
if   batch_size_raw >= 60000: batch_size = 60000   # 官方默认，最佳性能
elif batch_size_raw >= 40000: batch_size = 40000
elif batch_size_raw >= 30000: batch_size = 30000   # 减半
elif batch_size_raw >= 15000: batch_size = 15000   # 最小可用
else:
    batch_size = 60000                              # 无 GPU，CPU 模式，batch_size 无意义
    # CPU fallback: 在 sorting_config 中设置 use_gpu=False
```

**参考档位对应机器**：

| VRAM 空闲 | batch_size | 典型 GPU |
|---------|-----------|---------|
| ≥ 8 GB  | 60000 | RTX 3090/4090, A100, V100 16G+ |
| 5-8 GB  | 40000 | RTX 3080, RTX 4070 |
| 3-5 GB  | 30000 | RTX 3070, T4 |
| 1.5-3 GB | 15000 | GTX 1080, 低显存 GPU |
| < 1.5 GB 或无 GPU | 60000 (CPU) | 无 CUDA 机器 |

---

## 3. 配置优先级设计

### 3.1 三级优先级

```
优先级 1（最高）：用户在 pipeline.yaml 中显式设置的整数/字符串值
优先级 2         ：ResourceDetector 自动探测推算的值（config 值为 "auto" 时触发）  
优先级 3（兜底）：硬编码的保守默认值（在代码中定义，不在配置文件中）
```

### 3.2 `pipeline.yaml` 中的 "auto" 表示方式

```yaml
# config/pipeline.yaml

resources:
  n_jobs: auto          # "auto" 或整数（如 8）
  chunk_duration: auto  # "auto" 或时长字符串（如 "1s", "2s", "0.5s"）
  max_memory: auto      # "auto" 或大小字符串（如 "32G"）— 仅用于日志警告，不强制
                        # 注：max_memory 不影响实际内存分配，由 chunk_duration + n_jobs 控制

parallel:
  enabled: false        # 只有布尔值，无 auto（安全起见，并行默认关闭）
  max_workers: auto     # "auto" 或整数
```

**YAML 解析规则**：字符串 `"auto"` 在 Python 端以 `str` 类型存储；推算时：

```python
def resolve(config_value: int | str, detected: int | str, hardcoded_default: int | str):
    """Three-level priority resolution."""
    if config_value != "auto":          # 用户显式设置
        return type(hardcoded_default)(config_value)
    if detected is not None:            # 自动探测成功
        return detected
    return hardcoded_default            # 兜底
```

### 3.3 硬编码兜底值

兜底值设计为"保守但可用"，在资源探测完全失败时不会 OOM：

| 参数 | 兜底值 | 设计理由 |
|------|-------|---------|
| `n_jobs` | `4` | 适合 8 核以下机器 |
| `chunk_duration` | `"1s"` | 384ch×30kHz×1s×float32 ≈ 44MB，任何系统都能承受 |
| `max_workers` | `1` | 串行最安全 |
| `sorting.batch_size` | `60000` | Kilosort4 官方默认值，适配 ≥8GB VRAM |

### 3.4 冲突与警告

当用户设置的值超出探测到的硬件能力时，**不拒绝，只警告**：

```
WARNING: n_jobs=16 set in config, but only 8 physical cores detected.
         This may cause CPU oversubscription and reduced performance.
         Consider setting n_jobs: auto or n_jobs: 6.

WARNING: sorting.batch_size=60000 set in config, but GPU has only 3.2GB VRAM free.
         Kilosort4 may OOM. Consider setting sorting.params.batch_size: 30000.
```

---

## 4. 输出格式

### 4.1 结构化日志（JSON Lines，写入 session log 文件）

探测完成后，向 structlog 写入一条 `resource_detection` 事件：

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
    "gpus": [
      {
        "index": 0,
        "name": "NVIDIA GeForce RTX 3090",
        "vram_total_gb": 24.0,
        "vram_free_gb": 22.1,
        "cuda_driver_version": "535.104.05"
      }
    ],
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
    "notes": []
  },
  "applied": {
    "n_jobs": 12,
    "chunk_duration": "2s",
    "max_workers": 1,
    "sorting_batch_size": 60000,
    "sources": {
      "n_jobs": "auto_detected",
      "chunk_duration": "auto_detected",
      "max_workers": "hardcoded_default",
      "sorting_batch_size": "user_config"
    }
  },
  "warnings": [
    "Disk: estimated required 480GB, only 1240GB free (OK)",
    "GPU detection: pynvml succeeded (method=pynvml)"
  ]
}
```

**`applied.sources` 取值**：
- `"user_config"` — 用户在 yaml 中显式设置
- `"auto_detected"` — ResourceDetector 推算
- `"hardcoded_default"` — 兜底值

### 4.2 启动时的资源摘要（CLI 模式专用）

资源摘要**只在 `cli/main.py` 中输出**，使用 `click.echo()`，格式为人类可读表格。`core/resources.py` 不含任何 print/echo。

```
─────────────────────────────────────────────────
  pynpxpipe resource check
─────────────────────────────────────────────────
  CPU   │ Intel Core i9-13900K
        │ 14 physical cores (20 logical)  @  5.2 GHz
  RAM   │ 64.0 GB total  │  47.3 GB available
  GPU   │ NVIDIA RTX 3090  │  24.0 GB VRAM  │  22.1 GB free
  Disk  │ output → F:\data\session_01\out  │  1240 GB free
─────────────────────────────────────────────────
  Auto settings (from resource detection):
    n_jobs          =  12   (CPU: 14 physical cores)
    chunk_duration  =  2s   (RAM: 47.3 GB available)
    max_workers     =   2   (parallel probes, if enabled)
    batch_size      =  60000  (GPU: 22.1 GB VRAM free)
─────────────────────────────────────────────────
  ⚠  Windows: ensure output path length ≤ 200 chars
     Current: F:\data\session_01\output  (37 chars, OK)
─────────────────────────────────────────────────
```

**是否默认显示**：
- CLI 的 `run` 命令默认显示（除非加 `--quiet` flag）
- `status` 和 `reset-stage` 命令不显示（无关）
- GUI 模式：由 GUI 层决定是否显示，core/resources.py 提供 `HardwareProfile.to_display_dict()` 方法供 GUI 使用

---

## 5. 依赖与安装

新增依赖（`pyproject.toml` 中）：

```toml
[project.dependencies]
# 新增
"psutil>=5.9.0",          # CPU/RAM/Disk，必选
"nvidia-ml-py>=12.535.0", # GPU 探测，可选（安装后自动启用）

[project.optional-dependencies]
gpu = [
    "nvidia-ml-py>=12.535.0",
]
```

**psutil** 是强依赖（探测 CPU/RAM 是核心功能，不可跳过）。
**pynvml** 是弱依赖，`ImportError` 时自动降级到 `nvidia-smi subprocess`。

---

## 6. 探测时机与性能

- **探测时机**：`PipelineRunner.__init__()` 调用，在任何 stage 开始前
- **探测耗时目标**：< 2 秒（含 GPU 初始化）
- **缓存**：同一 Python 进程内缓存探测结果（`_cached_profile`），避免重复探测
- **探测失败处理**：每个子探测项独立 try/except，单项失败不影响其他项；全部失败则使用兜底值并记录 WARNING

---

## 7. `pipeline.yaml` 更新方案

在现有 `config/pipeline.yaml` 基础上，将固定值改为 `auto`：

```yaml
resources:
  n_jobs: auto            # 改动：原为 8
  chunk_duration: auto    # 改动：原为 "1s"
  max_memory: auto        # 改动：原为 "32G"（仅警告用）

parallel:
  enabled: false
  max_workers: auto       # 改动：原为 2
```

`config/sorting.yaml` 中的 `batch_size` 同样支持 `auto`：

```yaml
sorter:
  params:
    batch_size: auto      # 改动：原为 60000
```
