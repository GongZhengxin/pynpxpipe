# ADR-002: SpikeInterface API 验证与修正

## 状态
接受

## 上下文

在编写 architecture.md 和各 stage spec 时，使用了 9 个 SpikeInterface API 调用，但这些调用未经实际验证。存在以下问题：

1. **版本不匹配**：当前环境安装 spikeinterface==0.103.2，但 pyproject.toml 声明依赖 >=0.104.0
2. **API 调用未验证**：architecture.md 中的函数签名、参数名、返回值结构均基于假设，未查阅官方文档或实际测试
3. **Bombcell 集成不明确**：不确定 SI 0.104+ 是否原生支持 `bombcell_label_units`，还是需要手动实现阈值过滤
4. **SLAY 定义错误**：postprocess.md 将 SLAY 定义为"有响应的 trial 比例"（trial response rate），但实际应为"trial-to-trial correlation"（响应可靠性）

这些问题如果不在 Layer 1 实现前解决，会导致大量返工。

## 决策

我们决定：

1. **升级 SpikeInterface 到 0.104.0**：
   - 运行 `uv pip install --upgrade 'spikeinterface[full]>=0.104.0'`
   - 确保环境与 pyproject.toml 声明一致

2. **使用 SpikeInterface 原生 Bombcell 集成**：
   - 确认 `spikeinterface.curation.bombcell_label_units` 在 0.104+ 中存在
   - curate.md 中使用该函数，不手动实现阈值过滤

3. **修正 SLAY 定义为 trial-to-trial correlation**：
   - 算法：将 [pre_s, post_s] 窗口分成 10ms bins，计算每个 trial 的 spike count 向量，计算所有 trial 对之间的 Spearman 相关系数（对低发放率更稳健），取平均值
   - 公式：`SLAY = mean(spearmanr(trial_i, trial_j) for all i < j)`
   - 更新 postprocess.md 第 125-140 行

4. **创建 API 验证脚本**：
   - `scripts/verify_spikeinterface_api.py`
   - 验证 9 个 API 调用的存在性、签名、返回值结构
   - 打印 docstring 供人工检查

5. **更新文档**：
   - architecture.md：修正所有 API 调用（import 路径、参数名、返回值）
   - curate.md：确认 Bombcell API 调用正确
   - postprocess.md：替换 SLAY 算法实现

## 理由

### 为什么升级到 0.104.0？
- pyproject.toml 已声明此依赖，当前环境不一致会导致 CI/CD 失败
- 0.104+ 原生集成 Bombcell 和 SLAY presets，避免手动实现

### 为什么使用原生 Bombcell？
- 根据用户确认，SI 0.104 文档中存在 `sc.bombcell_label_units`
- 原生集成比手动阈值过滤更可靠，且与 SI 生态系统兼容
- 减少维护负担（不需要跟踪 Bombcell 论文的阈值更新）

### 为什么 SLAY 用 trial-to-trial correlation？
- **原定义问题**：trial response rate（有 spike 的 trial 比例）无法区分"每个 trial 都有 1 个 spike"和"每个 trial 都有稳定的 burst pattern"
- **新定义优势**：trial-to-trial correlation 衡量响应模式的一致性，更准确反映神经元对刺激的可靠编码
- **Spearman vs Pearson**：Spearman 对低发放率和异常值更稳健，不假设正态分布

### 为什么用 10ms bins？
- 平衡时间分辨率和统计稳健性
- 对于典型的 [50ms pre, 300ms post] 窗口，产生 35 个 bins，足够计算相关系数
- 与神经生理学常用的 PSTH bin size 一致

## 考虑过但拒绝的方案

### 方案 A：保持 0.103.2，手动实现 Bombcell
**拒绝原因**：
- 与 pyproject.toml 声明不一致
- 手动实现增加维护负担
- 0.104+ 已原生支持，无需重复造轮

### 方案 B：SLAY 保持为 trial response rate
**拒绝原因**：
- 不反映响应可靠性（reliability），只反映响应存在性（presence）
- 无法区分"偶尔有大量 spike"和"每次都有稳定响应"
- 用户明确要求使用 response reliability

### 方案 C：SLAY 使用 Fano Factor 或 CV
**拒绝原因**：
- Fano Factor 和 CV 衡量 spike count 变异性，但不考虑时间结构
- trial-to-trial correlation 保留了时间信息（通过 binning）
- correlation 更直观（0-1 范围，1 表示完全可靠）

### 方案 D：先实现再验证 API
**拒绝原因**：
- 高风险：如果 API 签名错误，需要重写所有测试和实现
- 验证成本低（1-2 小时），返工成本高（3-5 天）
- 违反"先验证假设再编码"的工程原则

## 影响

### 正面影响
1. **消除技术债务**：所有 API 调用经过验证，减少未来 bug
2. **版本一致性**：开发环境与 pyproject.toml 声明一致
3. **SLAY 语义正确**：输出指标真实反映神经元响应可靠性
4. **可复现性**：验证脚本可在 CI 中运行，防止版本漂移

### 需要的工作
1. **升级依赖**：`uv pip install --upgrade 'spikeinterface[full]>=0.104.0'`（5 分钟）
2. **编写验证脚本**：`scripts/verify_spikeinterface_api.py`（30 分钟）
3. **运行验证**：检查 9 个 API 调用（10 分钟）
4. **更新文档**：
   - architecture.md：修正 API 调用（Section 2.2, 2.3, 2.5, 2.6）
   - curate.md：确认 Bombcell API
   - postprocess.md：重写 SLAY 算法（第 125-140 行）
   - 预计 1-2 小时

### 风险
- **SI 0.104.0 可能引入 breaking changes**：缓解措施：验证脚本会捕获 API 不兼容
- **SLAY 计算复杂度增加**：缓解措施：使用 numpy 向量化操作，复杂度仍为 O(n_trials^2 * n_bins)，可接受

### 依赖关系
- **阻塞 Layer 1 实现**：必须在开始 io/spikeglx.py TDD 之前完成
- **不阻塞 Layer 0**：Layer 0 已完成，不受影响
