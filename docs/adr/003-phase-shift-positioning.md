# ADR-003: Phase shift 在预处理链中的定位

## 状态
接受（supersedes architecture.md § ADR-002 phase-shift 条目）

## 上下文

在 M0 架构设计阶段，`docs/architecture.md § ADR-002` 断言：

> `si.phase_shift()` 必须是 preprocess 链中的**第一个操作**，在任何滤波（包括 bandpass、notch、high-pass）之前执行。
>
> 如果先做带通滤波再做 phase shift，FIR 滤波器的群延迟和相位响应已经修改了各频率分量的相位。此时再叠加 phase_shift 的相位旋转，两者的相位贡献不可分离，导致 phase shift 校正量与真实时间偏移不匹配。

这一断言被编码进 `src/pynpxpipe/stages/preprocess.py` docstring、`docs/specs/preprocess.md`、`CLAUDE.md` 的"从旧代码迁移"一节，并在 `docs/legacy_analysis.md:163` 将旧代码的 `highpass → phase_shift` 顺序判定为"错误"。

Round 7 validation 过程中（详见 `docs/validation/pipeline_diff_audit.md`），用户指出 SpikeInterface 官方 Neuropixels 教程与 MATLAB REF（`Analysis_Fast.ipynb cell-0`）均采用 `highpass → detect_bad → phase_shift → CMR`，与项目当前约束相反。这迫使我们重新审视原论据。

## 决策

**phase_shift 只需在 CMR（common median reference）之前。相对 bandpass 的位置不敏感。**

本项目当前 preprocess 链为 `phase_shift → bandpass → detect_bad → remove → CMR → (DREDge)`，该顺序**继续保留**。原因：已有大量测试覆盖，round 7 的差距已归因到其它参数（`Th_learned`、漂移校正算法），调整 phase_shift 位置无收益。

未来如需与 SI 官方/IBL destripe/MATLAB REF 对齐，可改为 `highpass → detect_bad → remove → phase_shift → CMR`；此改动应视为"风格调整"而非"修复 bug"，且不应在现有稳定分支上做。

## 理由

### 为什么原论据过强（LTI 可交换性）

- `si.bandpass_filter` 对每个通道应用**同一个** FIR/IIR 滤波器 `H(ω)`。
- `si.phase_shift` 对通道 `c` 在频域乘以 `exp(-jω·Δt_c)`，其中 `Δt_c` 是 TDM-ADC 的 sub-sample 偏移。
- 两者都是通道独立、频率相关的线性时不变（LTI）操作：
  ```
  bandpass( phase_shift(x) )[c, ω] = H(ω) · exp(-jω·Δt_c) · X[c, ω]
  phase_shift( bandpass(x) )[c, ω] = exp(-jω·Δt_c) · H(ω) · X[c, ω]
  ```
- 二者频域响应完全相等；"相位贡献不可分离"在数学上没有解释力（复数乘法可交换）。

### 为什么约束必须收敛到 "CMR 之前"

- CMR 按样本点 `s` 做 `x[c,s] - median(x[:,s])`，要求各通道在时间上已对齐到统一参考时刻。
- 若 phase_shift 放在 CMR 之后，通道间 0.83 µs × {0..11} 的 ADC 偏移会进入 median 参考，CMR 对共模噪声的抵消效果下降。

### 为什么选择保留现状而非改为 REF 顺序

- 行为等价（LTI），改与不改对数值结果影响 <1%。
- 现有测试、docstring、spec 均基于 phase_shift 先行；调整需级联改动。
- Round 7 的质量差距来源已定位到 `Th_learned` 与漂移校正算法，phase_shift 位置不在因果链上。
- 若 Round VIII E4 实验证明顺序可互换（预期结果），则作为文档更新足够，不必改实际代码顺序。

## 考虑过但拒绝的方案

### 方案 A：改为 SI/REF 顺序 `highpass → detect_bad → phase_shift → CMR`
**拒绝原因**：
- 等价的数值结果却需要级联修改 preprocess.py、spec、测试、docstring。
- 与旧 Python 代码顺序相同，失去"已从 legacy 迁移"的明确标记。
- 无实质收益。

### 方案 B：删除 ADR 条目，让顺序变成隐式约定
**拒绝原因**：
- 项目已有多处文档断言 phase_shift 必须第一，直接删除会造成维护者困惑。
- 显式 ADR 记录"为什么原断言过强，以及当前顺序为何保留"更有信息量。

## 影响

### 文档修正（当前本 ADR 生效后即做）

- `docs/architecture.md § ADR-002`（phase_shift 一节）：改写，引用本 ADR。
- `src/pynpxpipe/stages/preprocess.py` class docstring：措辞由"MUST be first"改为"must precede CMR"。
- `docs/specs/preprocess.md` step 3 描述同步修正。
- `CLAUDE.md` "从旧代码迁移"一节中 phase_shift 条目改写。

### 不改变的内容

- `src/pynpxpipe/stages/preprocess.py` 代码顺序不动。
- 测试 `test_phase_shift_before_bandpass` 保留（它验证当前实现确实把 phase_shift 放第一；改名为 `test_phase_shift_positioning_matches_spec` 可能更准确，但非必要）。

### 关联工作

- Round VIII E4（`docs/validation/pipeline_diff_audit.md § 5`）将用真数据验证两种顺序数值等价（waveform cosine ≥ 0.99）。结果写入 `docs/validation/round8_E4.md`。
