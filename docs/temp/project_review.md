# pynpxpipe 项目状态审查报告

> 审查日期：2026-04-01  
> 审查范围：CLAUDE.md, architecture.md, progress.md, legacy_analysis.md

---

## 1. 文档一致性检查

### 1.1 发现的不一致之处

#### ✅ 无重大矛盾
经过交叉验证，四份文档之间**不存在逻辑矛盾或冲突**。各文档职责明确：
- **CLAUDE.md**：项目规范和开发流程（精简版）
- **architecture.md**：技术实现细节和算法设计（详尽版）
- **progress.md**：开发进度追踪
- **legacy_analysis.md**：旧代码问题清单和迁移参考

#### ⚠️ 需要注意的细节差异

1. **眼动验证的位置描述**
   - **CLAUDE.md**：将眼动验证归入 `postprocess` stage（第 38 行）
   - **architecture.md**：眼动验证实际在 `synchronize` stage 的 `bhv_nidq_align.py` 中执行（第 2.4.2 节）
   - **判断**：这不是矛盾，而是描述粒度不同。architecture.md 更准确：眼动验证在同步阶段完成，结果写入 `behavior_events.parquet` 的 `trial_valid` 列，供 postprocess 使用。
   - **建议**：CLAUDE.md 第 38 行应修正为："包含眼动验证结果的使用（trial_valid 列由 synchronize stage 生成）"

2. **Bombcell 集成方式**
   - **CLAUDE.md**：描述使用 SpikeInterface 0.104+ 原生集成（第 107-116 行）
   - **legacy_analysis.md**：旧代码使用独立的 Bombcell MATLAB/Python 实现
   - **判断**：这是**升级改进**，不是矛盾。新版本利用 SI 原生支持，避免了旧代码的外部依赖问题。

3. **LFP 处理的当前状态**
   - **CLAUDE.md**：明确"当前版本不实现 LFP 专项处理"（第 118-122 行）
   - **architecture.md**：未提及 LFP（符合"不实现"的决策）
   - **progress.md**：未列出 LFP 相关模块
   - **判断**：三份文档一致，LFP 处理预留接口但不实现。

---

## 2. 新版本相比旧版本的改进

### 2.1 架构层面的升级

| 改进项 | 旧版本问题 | 新版本方案 | 影响 |
|--------|-----------|-----------|------|
| **多探针支持** | 硬编码 `imec0`，多探针需手动循环 | 设计层面支持 N 个探针，probe_id 作为核心参数 | 可扩展性 ↑↑ |
| **断点续跑** | 无 checkpoint 机制，中断后需重跑 | 每个 stage 写 checkpoint，自动跳过已完成步骤 | 鲁棒性 ↑↑ |
| **资源管理** | 硬编码 `n_jobs=8`，无内存监控 | 自动资源探测（ResourceDetector）+ 可配置参数 | 适应性 ↑↑ |
| **前后端分离** | 业务逻辑与 Jupyter Notebook 耦合 | CLI/GUI 只是薄壳，业务逻辑零 UI 依赖 | 可维护性 ↑↑ |
| **配置管理** | 散落在多个 YAML + 代码中硬编码 | 统一配置加载（config.py）+ 零硬编码原则 | 可配置性 ↑↑ |

### 2.2 预处理流程的关键修正

#### ❌ 旧版本错误顺序（legacy_analysis.md 第 31 行）
```
highpass_filter → phase_shift → bad_channel_detection → common_reference
```

#### ✅ 新版本正确顺序（CLAUDE.md 第 34 行，architecture.md 第 2.2 节）
```
phase_shift → bandpass_filter → bad_channel_detection → CMR → motion_correction
```

**修正理由**（architecture.md 附录 A）：
- Phase shift 必须在**原始数据**上执行，否则滤波器的相位响应会与 ADC 时间偏移的相位校正叠加，引入系统误差
- 对于 30kHz 采样率、12 路 ADC 复用的 Neuropixels，相位误差可达数十微秒，超过 spike 检测精度要求
- 这是 SpikeInterface 官方推荐的 Neuropixels 预处理顺序

### 2.3 新增功能

| 功能 | 旧版本 | 新版本 | 价值 |
|------|--------|--------|------|
| **DREDge 运动校正** | 无 | 可选启用（与 KS4 nblocks 互斥） | 提高长时程记录的 spike 检测质量 |
| **SLAY 合并算法** | 无 | 集成 SI 原生 SLAY preset | 自动合并过度分割的单元 |
| **并行处理选项** | 串行处理所有探针 | 可配置并行（ProcessPoolExecutor） | 多探针 session 加速 2-4 倍 |
| **结构化日志** | print 输出 + 部分 logging | 统一 structlog（JSON Lines） | 可解析、可追溯、可监控 |
| **进度回调接口** | 无 | BaseStage 提供 progress_callback | 为 GUI 预留实时进度更新 |

### 2.4 质量保证的提升

| 方面 | 旧版本 | 新版本 |
|------|--------|--------|
| **测试覆盖** | 无自动化测试 | TDD 开发，Layer 0 已有 446 个测试 |
| **类型安全** | 部分函数无类型标注 | 强制 type hints + dataclass |
| **代码规范** | 无统一 linter | ruff check + format（强制通过） |
| **文档完整性** | README + 开发计划 | spec → TDD → 进度追踪（harness 流程） |

---

## 3. 当前版本预处理流程总结

### 3.1 输入（Input）

#### 必需输入
1. **SpikeGLX 数据目录**（`session_dir`）
   - 结构：`{session_dir}/imec{N}/*.ap.bin` + `*.ap.meta`（N 个探针）
   - 结构：`{session_dir}/*.nidq.bin` + `*.nidq.meta`（NIDQ 同步数据）
   - 可选：`*.lf.bin` + `*.lf.meta`（LFP 数据，当前版本不处理）

2. **MonkeyLogic 行为文件**（`bhv_file`）
   - 格式：`.bhv2`（MonkeyLogic 自定义二进制格式）
   - 内容：trial 时间戳、事件码、眼动轨迹、任务参数

3. **Subject 配置文件**（`monkeys/{subject_id}.yaml`）
   - 字段：subject_id, species, sex, age, weight, description
   - 用途：写入 NWB 的 Subject 元数据（DANDI 归档标准）

4. **Pipeline 配置文件**（`config/pipeline.yaml`）
   - 资源参数：n_jobs, chunk_duration, max_workers, parallel
   - 预处理参数：滤波频率、坏道检测阈值、运动校正方法
   - Sorting 参数：sorter_name, sorter_params, import_mode

#### 可选输入
- **外部 sorting 结果**（用于远程 sorting 模式）
  - 格式：Kilosort 输出目录（spike_times.npy, spike_clusters.npy 等）
  - 用途：跳过本地 sorting，直接导入已完成的结果

### 3.2 处理流程（Processing Pipeline）

#### Stage 1: discover
**目标**：扫描数据文件，验证完整性，构建 Session 对象

```
输入：session_dir, bhv_file, subject_yaml
  │
  ├─ 扫描 imec{N} 目录 → 发现 N 个探针
  ├─ 验证 .ap.bin 文件大小 = .ap.meta 中 fileSizeBytes
  ├─ 提取采样率、通道数、探针型号（从 .meta）
  ├─ 验证 NIDQ 数据存在
  ├─ 验证 BHV2 文件魔数（前 21 字节）
  │
输出：session.probes (list[ProbeInfo])
      session_info.json（元信息快照）
      checkpoint: discover.json
```

#### Stage 2: preprocess（对每个 probe）
**目标**：信号预处理，输出干净的 AP 数据供 sorting

```
输入：{session_dir}/imec{N}/*.ap.bin（lazy loading）
  │
  ├─ [1] Phase Shift（Neuropixels ADC 时序校正）
  │    └─ si.phase_shift(recording)
  │       必须第一步，校正多路复用 ADC 的通道采样时间偏移
  │
  ├─ [2] Bandpass Filter（带通滤波）
  │    └─ si.bandpass_filter(freq_min=300, freq_max=6000)
  │       保留 AP 频段，为坏道检测提供干净信号
  │
  ├─ [3] Bad Channel Detection（坏道检测）
  │    └─ si.detect_bad_channels(method="coherence+psd")
  │       在已滤波数据上检测，结果更可靠
  │
  ├─ [4] Remove Bad Channels（剔除坏道）
  │    └─ recording.remove_channels(bad_ids)
  │       在 CMR 之前剔除，防止污染全局参考
  │
  ├─ [5] Common Median Reference（公共中位参考）
  │    └─ si.common_reference(reference="global", operator="median")
  │       去除共模噪声（电极贴合不稳、运动伪迹）
  │
  ├─ [6] Motion Correction（运动校正，可选）
  │    └─ si.correct_motion(preset="nonrigid_accurate")
  │       仅在 config.motion_correction.method="dredge" 时执行
  │       与 KS4 内部 nblocks 互斥（二选一）
  │
  └─ 保存为 Zarr 格式
     └─ recording.save(format="zarr", n_jobs=n_jobs, chunk_duration=chunk_duration)
        分块写入，避免内存溢出
  │
输出：{output_dir}/preprocessed/{probe_id}/recording.zarr
      checkpoint: preprocess_{probe_id}.json
```

**内存管理**：
- 全程使用 SpikeInterface lazy recording（Recording 对象仅存指针）
- 每个 probe 处理完后 `del recording; gc.collect()`
- 默认串行处理（安全），可配置并行（需充足内存）

#### Stage 3: sort（对每个 probe）
**目标**：Spike sorting，输出单元活动

```
输入：{output_dir}/preprocessed/{probe_id}/recording.zarr
  │
  ├─ 模式 A：本地 sorting
  │   └─ si.run_sorter("kilosort4", recording, output_folder, **params)
  │      参数：nblocks（与 DREDge 互斥）、batch_size（GPU 显存相关）
  │
  ├─ 模式 B：导入外部结果
  │   └─ si.read_sorter_folder(external_ks_output_path)
  │      用于从 Windows 实验室电脑拷贝的 KS 输出
  │
  └─ 创建 SortingAnalyzer
     └─ si.create_sorting_analyzer(sorting, recording)
  │
输出：{output_dir}/sorting/{probe_id}/sorter_output/
      checkpoint: sort_{probe_id}.json
```

#### Stage 4: synchronize
**目标**：多层时间对齐 + 行为事件解析

```
输入：所有 probe 的 IMEC 同步信号（imec*.lf#SY0）
      NIDQ 数字信号（nidq#XD0）+ 模拟信号（nidq#XA0，光敏二极管）
      BHV2 文件
  │
  ├─ [Level 1] IMEC ↔ NIDQ 时钟对齐
  │   └─ 线性回归：IMEC_time = a * NIDQ_time + b
  │      输入：IMEC 和 NIDQ 的数字事件上升沿时间戳
  │      输出：每个 probe 的时钟转换参数（a, b）
  │
  ├─ [Level 2] BHV2 ↔ NIDQ 事件匹配
  │   ├─ 通过 MATLAB Engine 调用 mlread() 解析 BHV2
  │   ├─ 匹配 BHV2 trial onset 与 NIDQ 事件码
  │   ├─ 提取眼动数据（逐 trial）
  │   └─ 眼动验证：计算注视比例 > 0.999（阈值可配置）
  │      结果写入 behavior_events 的 trial_valid 列
  │
  ├─ [Level 3] Photodiode 校准（可选）
  │   └─ 光敏二极管模拟信号峰值检测 → 精确到 ms 级的刺激呈现时间
  │
  └─ 生成诊断图（io/sync_plots.py）
     └─ 时钟对齐残差图、事件匹配图、眼动轨迹图
  │
输出：{output_dir}/sync_tables.json（时钟转换参数）
      {output_dir}/behavior_events.parquet（trial 级行为数据 + trial_valid）
      {output_dir}/sync/figures/*.png（诊断图）
      checkpoint: synchronize.json
```

**关键约束**：
- BHV2 解析必须通过 MATLAB Engine（不能用 h5py 直接读）
- 眼动验证在此阶段完成（不是 postprocess）

#### Stage 5: curate（对每个 probe）
**目标**：质控与自动筛选

```
输入：SortingAnalyzer（含 sorting + recording）
  │
  ├─ 计算 quality metrics
  │   └─ analyzer.compute("quality_metrics")
  │      指标：ISI violation, amplitude cutoff, presence ratio, SNR 等
  │
  ├─ Bombcell 分类（SpikeInterface 原生集成）
  │   ├─ thresholds = sc.bombcell_get_default_thresholds()
  │   └─ labels = sc.bombcell_label_units(analyzer, thresholds)
  │      输出：noise / mua / good / non_soma_mua
  │
  └─ 应用筛选规则（可配置）
     └─ analyzer.select_units(labels == "good")
  │
输出：{output_dir}/curated/{probe_id}/analyzer_curated/
      checkpoint: curate_{probe_id}.json
```

#### Stage 6: postprocess（对每个 probe）
**目标**：计算单元特征 + SLAY 合并

```
输入：curated SortingAnalyzer
  │
  ├─ 计算 waveforms
  │   └─ analyzer.compute("waveforms", ms_before=1.5, ms_after=2.0)
  │
  ├─ 计算 templates
  │   └─ analyzer.compute("templates")
  │
  ├─ 计算 unit locations
  │   └─ analyzer.compute("unit_locations", method="monopolar_triangulation")
  │
  ├─ SLAY 合并（检测过度分割）
  │   ├─ merge_groups = sc.compute_merge_unit_groups(analyzer, preset="slay")
  │   └─ analyzer_merged = analyzer.merge_units(merge_groups)
  │
  └─ 使用 behavior_events 的 trial_valid 列
     └─ 筛选有效 trial 的 spike 用于后续分析
  │
输出：{output_dir}/postprocessed/{probe_id}/analyzer_final/
      checkpoint: postprocess_{probe_id}.json
```

#### Stage 7: export
**目标**：整合所有数据写入 NWB

```
输入：所有 probe 的 analyzer_final
      behavior_events.parquet
      sync_tables.json
      session.subject（SubjectConfig）
  │
  ├─ 创建 NWBFile
  │   ├─ session_description, identifier, session_start_time
  │   └─ subject（从 SubjectConfig 映射）
  │
  ├─ 写入 ElectricalSeries（原始 AP 数据，可选）
  │   └─ 每个 probe 一个 ElectrodeGroup
  │
  ├─ 写入 Units 表
  │   ├─ spike_times（已对齐到 NIDQ 时钟）
  │   ├─ quality_metrics（ISI violation, SNR 等）
  │   ├─ waveforms, templates
  │   └─ electrode_group（关联到 probe）
  │
  ├─ 写入 Trials 表
  │   ├─ start_time, stop_time（已对齐）
  │   ├─ trial_valid（来自 synchronize stage）
  │   └─ 任务参数（从 BHV2 提取）
  │
  ├─ 写入 EyeTracking（可选）
  │   └─ SpatialSeries（x, y 坐标，时间戳已对齐）
  │
  └─ 写入 Stimulus（可选）
  │
输出：{output_dir}/{session_id}.nwb
      checkpoint: export.json
```

### 3.3 输出（Output）

#### 主要输出文件
1. **NWB 文件**（`{output_dir}/{session_id}.nwb`）
   - 符合 DANDI 归档标准
   - 包含所有 probe 的数据（多 ElectrodeGroup）
   - 包含行为数据、眼动数据、质控指标

2. **中间数据**（可用于调试或重跑部分 stage）
   - `preprocessed/{probe_id}/recording.zarr`（预处理后的 AP 数据）
   - `sorting/{probe_id}/sorter_output/`（Kilosort 输出）
   - `curated/{probe_id}/analyzer_curated/`（质控后的 analyzer）
   - `postprocessed/{probe_id}/analyzer_final/`（最终 analyzer）

3. **同步数据**
   - `sync_tables.json`（时钟转换参数）
   - `behavior_events.parquet`（trial 级行为数据）
   - `sync/figures/*.png`（诊断图）

4. **日志与 checkpoint**
   - `logs/{session_id}.jsonl`（结构化日志）
   - `checkpoints/{stage_name}[_{probe_id}].json`（断点续跑）

#### 输出数据特点
- **时间对齐**：所有时间戳统一到 NIDQ 时钟（ms 精度）
- **质量保证**：所有单元经过 Bombcell 分类 + quality metrics 筛选
- **可追溯**：日志记录所有参数、耗时、成功/失败状态
- **可重现**：配置文件 + checkpoint 机制保证流程可重现

---

## 4. 当前开发状态

### 4.1 已完成模块（Layer 0 基础设施）

| 模块 | 测试数量 | 状态 |
|------|---------|------|
| core/errors.py | 16 | ✅ 已提交 |
| core/config.py | 285 | ✅ 已提交 |
| core/logging.py | 13 | ✅ 已提交 |
| core/checkpoint.py | 38 | ✅ 已提交 |
| core/resources.py | 41 | ✅ 已提交 |
| core/session.py | 33 | ✅ 已提交 |
| stages/base.py | 20 | ✅ 已提交 |
| **总计** | **446** | **Layer 0 完成** |

### 4.2 待实现模块（Layer 1-3）

#### Layer 1: IO 层（7 个模块，spec 已完成）
- io/spikeglx.py
- io/bhv.py
- io/nwb_writer.py
- io/sync/imec_nidq_align.py
- io/sync/bhv_nidq_align.py
- io/sync/photodiode_calibrate.py
- io/sync_plots.py

#### Layer 2: Stages 层（7 个模块，spec 已完成）
- stages/discover.py
- stages/preprocess.py
- stages/sort.py
- stages/synchronize.py
- stages/curate.py
- stages/postprocess.py
- stages/export.py

#### Layer 3: 编排与入口（2 个模块，spec 已完成）
- pipelines/runner.py
- cli/main.py

### 4.3 下一步行动

**优先级 1**：实现 IO 层（Layer 1）
- 这些模块是 stages 层的依赖
- spec 已完成，可直接进入 TDD

**优先级 2**：实现 Stages 层（Layer 2）
- 依赖 IO 层完成
- 按 stage 顺序实现（discover → preprocess → ... → export）

**优先级 3**：实现编排层（Layer 3）
- 依赖 Stages 层完成
- 最后实现 CLI 入口

---

## 5. 风险与建议

### 5.1 技术风险

| 风险项 | 影响 | 缓解措施 |
|--------|------|---------|
| **MATLAB Engine 依赖** | BHV2 解析依赖 MATLAB，增加部署复杂度 | 提供 Docker 镜像（含 MATLAB Runtime）；文档说明安装步骤 |
| **大文件内存管理** | 400-500GB AP 文件可能导致 OOM | 强制使用 lazy loading；测试用例覆盖大文件场景 |
| **Windows 长路径限制** | SpikeGLX 输出路径可能超过 260 字符 | 文档警告；考虑使用 `\\?\` 前缀绕过限制 |
| **GPU 资源竞争** | 多探针并行 sorting 可能超出 GPU 显存 | sorting stage 默认串行；并行选项仅用于 preprocess/curate/postprocess |

### 5.2 开发建议

1. **保持 harness 纪律**
   - 严格执行 spec → TDD → 进度追踪流程
   - 不跳步，不省略测试

2. **优先实现关键路径**
   - 先实现单探针、无眼动、无 photodiode 的最小可行流程
   - 再逐步添加多探针、眼动验证、photodiode 校准

3. **及时更新文档**
   - 实现过程中发现的问题及时反馈到 architecture.md
   - CLAUDE.md 保持精简，细节放 architecture.md

4. **集成测试优先**
   - Layer 1 完成后立即编写端到端集成测试
   - 使用小规模真实数据（如 10 秒录制）验证流程

---

## 6. 总结

### 6.1 文档质量评估
- ✅ **一致性**：四份文档逻辑一致，无重大矛盾
- ✅ **完整性**：覆盖架构、实现、进度、迁移参考
- ⚠️ **需微调**：CLAUDE.md 中眼动验证位置描述需更正

### 6.2 新版本核心优势
1. **架构升级**：多探针原生支持、断点续跑、资源感知
2. **流程修正**：预处理顺序正确（phase_shift 第一步）
3. **质量保证**：TDD 开发、446 个测试、强制类型标注
4. **可扩展性**：前后端分离、进度回调接口、配置驱动

### 6.3 当前进度
- **Layer 0**：✅ 完成（7/7 模块，446 测试）
- **Layer 1-3**：🟡 spec 已完成，待实现（16 个模块）

### 6.4 推荐下一步
**立即开始 Layer 1 的 TDD 实现**，按以下顺序：
1. io/spikeglx.py（discover 依赖）
2. io/sync/imec_nidq_align.py（synchronize 依赖）
3. io/sync/bhv_nidq_align.py（synchronize 依赖）
4. io/sync/photodiode_calibrate.py（synchronize 依赖）
5. io/sync_plots.py（synchronize 依赖）
6. io/nwb_writer.py（export 依赖）
7. io/bhv.py（synchronize 依赖，需 MATLAB Engine）

---

**审查结论**：项目文档完备、设计合理、进度清晰。Layer 0 基础设施已稳固，可以开始 Layer 1 实现。
