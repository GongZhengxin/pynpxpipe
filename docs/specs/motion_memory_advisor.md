# Spec: motion_memory_advisor（DREDge 内存预测 + bin_s 自适应 + 运动策略决策）

> 状态：草案 v2（按源码调研修正），待用户确认。用户请求新增（2026-06-26）。
> 作为 `core/resources.py` "资源感知"职责的延伸，不改动里程碑范围。

## 背景与源码依据（v2 修正核心）

v1 的 `peak_count × bytes_per_peak` 线性模型**错了**。读 SpikeInterface 0.104
`sortingcomponents/motion/dredge.py` 源码后确认，DREDge AP 注册的内存峰值来自
`xcorr_windows()` 里的成对互相关矩阵（`dredge.py:1014-1015`）：

```python
Ds = np.zeros((B, T0, T1), dtype=np.float32)   # T0 = T1 = T
Cs = np.zeros((B, T0, T1), dtype=np.float32)
```

- **B** = 非刚性窗口数 ≈ 探针深度跨度 / `win_step_um`(默认 400) ≈ NP1.0 约 10
- **T** = 时间 bin 数 = `时长_s / bin_s`，DREDge 默认 `bin_s=1.0` → T = 录制秒数
- 内存 ∝ **B × T² ∝ 时长² / bin_s²**，且**几乎与放电率/峰数无关**（峰已被 binning
  成 raster）。`time_horizon_s`/`max_dt_bins` 只裁剪**计算**范围，不缩小分配（T0=T1=T 满阵）。
- solver 内 `Ds` 被转 float64（`dredge.py:830`），加上 `Cs`，实际倍率 > 单个 f32 矩阵。

**关键推论**：主导项是**确定性的、数据无关的**——可直接由 `时长 / bin_s / B` 解析算出，
**无需运行 DREDge、无需采样 peaks、无需标定 bytes_per_peak**。且 `bin_s` 是连续可调旋钮，
内存 ∝ `1/bin_s²`（`bin_s` 1→2 省 4×），代价是漂移估计的时间分辨率变粗（逐样本空间校正不变）。

## 五个问题

### 1. 目标

在 preprocess 运行 DREDge 前，**解析预测**其峰值内存随 `bin_s` 的变化；在内存安全上限内
求出**最高时间精度（最小 bin_s）**的 DREDge 参数；若连最粗可接受的 `bin_s_max` 都装不下，
才回退 KS4 `nblocks`。决策可解释、连续优化、零硬编码、有日志。

### 2. 输入（全部来自元数据，不加载 SI recording）

| 输入 | 来源 | 说明 |
|------|------|------|
| `duration_s` | `.ap.meta` 的 `fileTimeSecs`（或 fileSizeBytes/nSavedChans/2/imSampRate） | T = duration_s/bin_s |
| 探针深度跨度 → `B` | `ProbeInfo` 触点 y 跨度 / `win_step_um`；缺失则按探针型号默认 | 非刚性窗口数 |
| 可用 RAM | `psutil.virtual_memory().available` | 预算基数（系统 RAM，非 VRAM——Ds/Cs 是 numpy） |
| `MotionCorrectionConfig` 新字段 | `config/pipeline.yaml` | 见 §5 |

### 3. 输出

新 dataclass `MotionStrategy`（`core/resources.py`）：

```python
@dataclass
class MotionStrategy:
    use_dredge: bool            # True: 用 DREDge@resolved_bin_s；False: 退回 nblocks
    bin_s: float | None         # use_dredge 时解出的最高精度 bin_s（连续值，可为小数）
    n_windows: int              # B
    n_time_bins: int            # T at resolved bin_s
    predicted_peak_bytes: int   # 在 resolved bin_s 下的预测主导内存
    available_bytes: int
    budget_bytes: int           # available*safety - overhead_reserve
    fallback_nblocks: int       # use_dredge=False 时 sort 采用的 nblocks
    reason: str                 # 含数值的一句话决策理由
    notes: list[str]            # 预算/曲线/选择，供日志
```

**副作用（由 runner 施加）**：
- `use_dredge=True` → 把解出的 `bin_s` 写回 `pipeline_config.preprocess.motion_correction.bin_s`，
  preprocess 转发给 `correct_motion(..., estimate_motion_kwargs={"bin_s": bin_s})`。
- `use_dredge=False` → `motion_correction.method=None` + `sorting_config.sorter.params.nblocks=fallback_nblocks`，
  WARNING 日志。
- 两种情况都把 `MotionStrategy` 记入结构化日志 provenance。

### 4. 处理步骤

两层（严守 `core/` 零业务依赖；本设计**不再需要 io/spikeglx 采样层**）：

**L0 纯解析决策（`core/resources.py`，无 SI、无 psutil 实参传入）**

```
recommend_motion_strategy(*, duration_s, n_windows, available_bytes,
                          bin_s_floor=1.0, bin_s_max=3.0,
                          bytes_per_entry=4, n_matrices=4,
                          overhead_reserve_bytes, ram_safety_factor=0.6,
                          fallback_nblocks=5) -> MotionStrategy

  budget = available_bytes*ram_safety_factor - overhead_reserve_bytes
  若 budget <= 0: return nblocks 策略（连 overhead 都不够）
  # M(bin_s) = bytes_per_entry * n_matrices * n_windows * (duration_s/bin_s)^2
  coef        = bytes_per_entry * n_matrices * n_windows * duration_s**2
  bin_s_min   = sqrt(coef / budget)           # 装得下的最小 bin_s = 最高精度
  bin_s_opt   = clamp(bin_s_min, bin_s_floor, bin_s_max)
  若 bin_s_min <= bin_s_max:
      use_dredge=True; bin_s=bin_s_opt; predicted = coef / bin_s_opt**2
  否则:
      use_dredge=False; bin_s=None        # 太粗也无意义 → 退 nblocks
```
纯函数，完全可单测，不 import SI/psutil。`clamp` 含义：内存富裕(bin_s_min<floor)→用 floor
(不比 DREDge 默认更细，避免每 bin 峰太少噪声大)；内存紧→用恰好装下的连续 bin_s_min。

**L1 编排（`pipelines/runner.py`）** —— discover 之后、preprocess 之前调用一次

```
_resolve_motion_strategy():
  guard: 'preprocess' in to_run 且 motion.method=='dredge' 且 motion.auto_strategy 且 probes 已知
  duration = max(probe 的 fileTimeSecs)            # 取最长 probe（最坏情况）
  若 duration < probe_threshold_s: return（短录制必装得下，跳过，记一条）
  n_windows = B(由探针 y 跨度/win_step_um；缺失用 n_windows 配置或型号默认)
  available = psutil.virtual_memory().available
  strategy = recommend_motion_strategy(duration, n_windows, available, ...config...)
  log(strategy.notes)
  施加副作用（见 §3）
  记 provenance
异常处理：任一步失败 → WARNING 并保留 DREDge 原配置（不阻塞、不误退）。
```

**preprocess 改动（`stages/preprocess.py`）**：step 7 把 `motion_correction.bin_s`
透传给 `spp.correct_motion(recording, preset=..., estimate_motion_kwargs={"bin_s": bin_s})`
（当前仅传 `preset`）。`method=None` 时仍照常跳过。

### 5. 可配参数（`MotionCorrectionConfig` 新增）

| 字段 | dataclass 默认 | pipeline.yaml | 说明 |
|------|------|------|------|
| `auto_strategy` | `False` | **`True`** | 总开关。dataclass 保守关（向后兼容/测试稳定），仓库 config 开 |
| `bin_s` | `1.0` | `1.0` | DREDge 估计时间 bin；auto_strategy 时由 advisor 改写 |
| `bin_s_floor` | `1.0` | `1.0` | 最细允许值（不低于 DREDge 默认，避免每 bin 峰太少） |
| `bin_s_max` | `3.0` | `3.0` | 最粗可接受值；超过 → 退 nblocks |
| `ram_safety_factor` | `0.6` | `0.6` | 预算 = 可用RAM×此值 − overhead |
| `overhead_reserve_gb` | `16.0` | `16.0` | 非二次项（peaks/recording/solver 杂项）的平摊预留；**校准旋钮** |
| `bytes_per_entry` | `4` | `4` | f32 矩阵每元素字节（校准内部，一般不动） |
| `n_matrices` | `4` | `4` | Ds+Cs+f64 转换+solver 的有效倍率；**校准旋钮** |
| `win_step_um` | `400.0` | `400.0` | 由探针深度推 B 用；与 DREDge 默认一致 |
| `n_windows` | `None` | `null` | 显式覆盖 B；null=由几何推 |
| `probe_threshold_s` | `7200.0` | `7200.0` | <此时长跳过 advisor（必装得下） |
| `fallback_nblocks` | `5` | `5` | 退回时 KS4 nblocks（cf. Round VIII：nblocks=5 优于 DREDge） |

### 标定（用真实锚点，非凭空）

`5.2h@91G OOM` 与 `4.2h@128G` 作为验证锚点。结构默认 `bytes_per_entry×n_matrices=16`
B≈10：
- 5.2h(T=18720)：M=16×10×18720²≈56 GB，+overhead → 超 91G 可用 → **预测 OOM ✅吻合**
- 4.2h(T=15120)：M=16×10×15120²≈37 GB，+overhead≈16 → ~53 GB < 0.6×128=77 → **预测 bin_s=floor 直接跑 ✅**

`# TODO(user): 拿真实 RSS 曲线回归 overhead_reserve_gb 与 n_matrices，把验证锚点变成拟合点。`

## 与 MATLAB 参考实现的关系

**无对应**。MATLAB 参考 pipeline 不含 DREDge 内存预测/bin_s 自适应/运动策略自动决策，
本模块为 pynpxpipe 新增资源感知能力，不偏离任何 MATLAB 算法。

## 集成契约与测试计划（TDD-RED 先行）

| 文件 | 测试要点（最少条数） |
|------|------|
| `tests/test_core/test_resources.py` **+7** | 内存富裕→bin_s=floor / 内存紧→解出分数 bin_s 且 M≤budget / 超 bin_s_max→退 nblocks / budget≤0→退 nblocks / 边界 bin_s_min==bin_s_max / safety_factor 改变预算 / notes 含数值 |
| `tests/test_stages/test_runner.py` **+5** | method≠dredge 跳过 / auto_strategy=off 跳过 / 短录制(<阈值)跳过 / 紧内存→写回 bin_s 且不退 / 极端→method=None+nblocks 改写 |
| `tests/test_stages/test_preprocess.py` **+2** | bin_s 透传进 correct_motion 的 estimate_motion_kwargs / method=None 仍跳过 |
| `tests/test_harness/test_motion_strategy_contract.py` **+1** | 合成长录制元数据 → 决策一致地设 bin_s 或退 nblocks，<3s |

基线不退化：保持 `1576 passed / 0 failed`；`ruff check src/ tests/` 干净。

## 改动文件清单（≤5 实现文件）

1. `core/resources.py` — `MotionStrategy` + `recommend_motion_strategy()`（纯解析）
2. `pipelines/runner.py` — `_resolve_motion_strategy()` + discover 后调用
3. `core/config.py` — `MotionCorrectionConfig` 新字段 + 校验
4. `stages/preprocess.py` — step 7 透传 `bin_s` 给 `correct_motion`
5. `config/pipeline.yaml` — `motion_correction` 块新增默认

（测试文件 + `docs/progress.md` 不计入 5 文件上限。`io/spikeglx` 采样层 v2 已删除。）

## 已知近似与边界

- 模型只算**bin_s 可控的二次主导项**；非二次杂项（peaks O(N)、recording 缓冲、solver
  临时量）折进 `overhead_reserve_gb` 平摊预留，**保守取值 + 锚点校准**，留 TODO 精修。
- `B` 由探针几何估计；rigid 模式 B=1（内存×1/10），本 spec 默认 nonrigid（preset "dredge"）。
- 若未来 SI 把 AP 注册改成 online/分块路径，主导项形状会变，需重核源码（当前 0.104 是满阵）。
- `bin_s` 增大牺牲漂移**时间**分辨率；有急动伪影的录制慎用大 bin_s，advisor 在 notes 里提示。
