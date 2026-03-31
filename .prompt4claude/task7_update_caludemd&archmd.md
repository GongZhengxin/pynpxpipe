具体改动如下：

==========================================================
## 一、CLAUDE.md 更新
==========================================================

### 1. synchronize 详细设计 — 替换现有 "synchronize 详细设计" 整节

替换为以下内容：

同步架构（以 NIDQ 为中介的三级对齐）：

- 第一级：IMEC ↔ NIDQ 时钟对齐。每个 IMEC probe 的 AP 数据流通过
  SpikeGLX 内置的同步脉冲（数字口）与 NIDQ 时钟对齐。提取双方 sync 脉冲
  上升沿时间序列，线性回归建立校正函数 t_nidq = a × t_imec + b，
  验证残差 < max_time_error_ms。

- 第二级：BHV2 ↔ NIDQ 事件对齐。MonkeyLogic 在每个行为事件发生时，
  通过数字口向 NIDQ 发送特定的数字编码信号。从 NIDQ 数字通道解码事件码序列，
  与 BHV2 文件中的事件时间戳按 trial 匹配对齐。自动检测并修复 trial_start_bit
  映射错误（遍历 bit 0-7 找匹配）。同时提取 BHV2 元信息（DatasetName 等）。
  注意：BHV2 解析需要 MATLAB 引擎（通过 Python 调用），因此 BHV2 相关的
  所有读取操作（包括元信息提取）统一在 synchronize 阶段完成，不拆到 discover。

- 第三级：Photodiode 模拟信号校准。NIDQ 模拟通道中的 photodiode 信号
  精确检测每个 stimulus 的实际显示时刻，校正数字事件码与实际显示的延迟差。
  算法流程：
  1. 从 NIDQ 模拟通道（索引由 config sync.photodiode_channel_index 指定）
     读取 photodiode 信号，int16 转电压（量程从 nidq.meta 读取）
  2. 重采样到 1ms 分辨率（resample_poly，比率从采样率精确计算）
  3. 以数字事件码 stim onset 为参考，提取 [-10ms, +100ms] 窗口
  4. 逐 trial 独立 z-score 归一化
  5. 计算全局阈值（跨 trial 共享）：0.1×baseline_mean + 0.9×stimulus_period_mean
  6. 逐 trial 首次超阈值检测确定 onset_latency（相对数字触发的延迟 ms）
  7. 校正显示器系统延迟（monitor_delay_ms，从配置读取，60Hz 约 -5ms）
  8. 通过 np.interp 将校准后的 onset 时间从 NI 时钟转换到 IMEC 时钟
  边界情况处理（旧代码未覆盖，新架构必须处理）：
  - onset_latency < 0（信号在触发前超阈）：记录警告，标记该 trial 为可疑
  - photodiode 信号接近零（接头松动）：检测信号方差，过低时 raise SyncError
  - 窗口越界（录制起始附近的 onset）：跳过该 trial，记录警告

同步验证（诊断图）：
- 每个对齐步骤完成后生成诊断图，保存到 {output_dir}/sync/figures/
- 由配置项 sync.generate_plots 控制（默认 true）
- 必须包含的图表：
  1. sync_drift_{probe_id}.png — IMEC↔NIDQ 时钟漂移散点图 + 线性回归拟合线
  2. event_alignment.png — BHV2 vs NIDQ 逐 trial onset 数量散点图
  3. photodiode_heatmap.png — 所有 trial 的校准后 photodiode 信号热力图
  4. onset_latency_histogram.png — 逐 trial photodiode 延迟分布直方图
  5. photodiode_mean_signal.png — 校准前 vs 校准后平均 photodiode 信号叠加对比
  6. sync_pulse_interval.png — 相邻 sync 脉冲间隔 vs 期望间隔（检测时钟不稳定）
- 诊断图生成逻辑独立为 io/sync_plots.py，stages 层不 import matplotlib

同步结果：
- 所有数据流的时间戳统一到 NIDQ 时钟
- 每个 probe 的时间校正函数参数
- Photodiode 校准后的精确 stimulus onset 时间（IMEC 时钟）
- BHV2 行为事件表（统一时间轴）
- BHV2 元信息（dataset_name 等）
- 输出文件：sync_tables.json + behavior_events.parquet + figures/

### 2. 核心设计原则第3条 "资源感知" — 在现有三个子项后追加第四个子项

追加：
   - **自动资源探测**：core/resources.py 中的 ResourceDetector 在 pipeline
     启动时自动探测 CPU 核心数、可用内存、GPU 显存、磁盘空间，
     推算 n_jobs、chunk_duration、max_workers、sorting batch_size 的最优值。
     pipeline.yaml 中支持 "auto" 关键字表示使用自动探测值。
     优先级：用户显式配置 > 自动探测 > 硬编码兜底值。
     探测结果写入结构化日志。GPU 探测优先使用 torch.cuda（若已安装），
     fallback 到 nvidia-smi subprocess。不实现磁盘测速。

### 3. postprocess 阶段描述 — 追加眼动验证

在 CLAUDE.md 中 postprocess 的描述（"SpikeInterface SortingAnalyzer：
waveforms, templates, unit locations；包含 SLAY 计算"）后追加：
"；包含眼动验证（逐 trial 检查注视有效性，结果写入 behavior_events 的 trial_valid 列）"

注意：眼动验证是必须步骤，不是可选步骤。但可通过配置跳过（用于没有眼动数据的 session）。

### 4. 目录结构更新

在 io/ 下添加：
    sync/               # 同步子模块（按对齐级别拆分）
      __init__.py
      imec_nidq_align.py    # 第一级：IMEC↔NIDQ 时钟对齐
      bhv_nidq_align.py     # 第二级：BHV2↔NIDQ 事件匹配 + BHV2 元信息提取
      photodiode_calibrate.py  # 第三级：Photodiode 校准
    sync_plots.py       # 同步诊断图生成（独立于 stage 层，可选依赖 matplotlib）

在 core/ 下添加：
    resources.py        # 自动资源探测（ResourceDetector）

### 5. 技术栈更新

追加：
- psutil（系统资源探测，必选依赖）
注意：不添加 pynvml/nvidia-ml-py，GPU 探测优先用 torch.cuda

### 6. 从旧代码迁移的注意事项 — 追加以下条目

- synchronizer.py 行 201 的 CodeVal==64 硬编码必须参数化为 config 中的 sync.imec_sync_code
  （或从信号自动检测：找频率约 1Hz 的码值）
- synchronizer.py 行 397 的 trial_codes==64 必须使用 config.sync.stim_onset_code
- photodiode np.squeeze 假设单列的问题，改为按 sync.photodiode_channel_index 显式索引
- eye_matrix 3D 预分配改为按 trial 分块处理，移至 postprocess 阶段
- matplotlib.use('Agg') 移除，图表生成独立到 io/sync_plots.py
- synchronizer 中 BHV2 文件名解析（split('_')[1:3]）改为从 BHV2 内容或 Session 对象读取
- monitor_delay_correction 硬编码 -5 改为从 config.sync.monitor_delay_ms 读取

==========================================================
## 二、architecture.md 更新
==========================================================

### 1. 重写 2.4 synchronize 部分

基于 sync_analysis.md 的 8 个步骤，重写为新架构的处理逻辑：

处理逻辑：

步骤 1 — IMEC↔NIDQ 时钟对齐（对每个 probe 循环）：
  - 从 AP 数据数字通道提取 sync 脉冲上升沿时间序列
  - 从 NIDQ 数字通道提取对应 sync 脉冲上升沿时间序列
  - 验证双方 sync 事件数量一致
  - 线性回归建立校正函数，验证残差 < max_time_error_ms
  - 输出：每个 probe 的 {a, b, residual_ms}

步骤 2 — BHV2↔NIDQ 事件匹配：
  - 解析 BHV2 文件（通过 MATLAB 引擎），提取 trial 事件码序列和时间戳
  - 同时提取 BHV2 元信息：DatasetName、刺激参数等
  - 从 NIDQ 数字通道解码事件码序列及时间
  - 按 trial 数量和 onset 事件码匹配；自动修复 trial_start_bit 映射错误
  - 验证逐 trial onset 数量一致性
  - 输出：trial 级事件对应表

步骤 3 — Photodiode 校准：
  - 从 NIDQ 模拟通道读取 photodiode 信号（通道索引从配置读取）
  - int16 → 电压转换（量程从 nidq.meta 的 niAiRangeMax 读取，不用 fallback）
  - 重采样到 1ms 分辨率
  - 以数字 stim onset 为参考提取窗口，逐 trial z-score，全局阈值首次超阈检测
  - 加 monitor_delay_ms 校正（从配置读取）
  - NI 时钟 → IMEC 时钟转换（np.interp，对每个 probe 各一个插值函数）
  - 边界情况：onset_latency<0 记警告、信号方差过低 raise SyncError、窗口越界跳过
  - 输出：校准后的 stimulus onset 时间序列（IMEC 时钟，每 probe 一份）

步骤 4 — 诊断图生成（可选，sync.generate_plots 控制）：
  - 调用 io/sync_plots.py 生成全部诊断图
  - 保存到 {output_dir}/sync/figures/

输入部分更新：
- 追加：MATLAB Engine（BHV2 解析需要）

输出部分更新：
- 追加：{output_dir}/sync/figures/*.png（诊断图）
- 追加：session metadata 中的 dataset_name

checkpoint 更新：
- 追加字段：photodiode_calibrated: true, monitor_delay_ms: -5, dataset_name: "..."

### 2. 新增 "2.4a synchronize 子模块拆分" 小节

在 2.4 后添加：

synchronize stage 内部模块划分（每个子模块可独立测试）：
- stages/synchronize.py — 主调度，按顺序调用下面的子模块
- io/sync/imec_nidq_align.py — 第一级：IMEC↔NIDQ 时钟对齐
  - 输入：AP 数字通道数据、NIDQ 数字通道数据、采样率
  - 输出：SyncResult(a, b, residual_ms)
  - 可独立调用和测试
- io/sync/bhv_nidq_align.py — 第二级：BHV2↔NIDQ 事件匹配
  - 输入：BHV2 文件路径、NIDQ 数字事件码序列
  - 输出：TrialAlignment(trial_events_df, dataset_name, bhv_metadata)
  - 依赖 MATLAB 引擎
- io/sync/photodiode_calibrate.py — 第三级：Photodiode 校准
  - 输入：NIDQ 模拟信号、数字 stim onset 时间、sync 校正函数
  - 输出：CalibratedOnsets(onset_times_imec_ms, onset_latencies, quality_flags)
- io/sync_plots.py — 诊断图生成
  - 输入：以上三个子模块的输出
  - 输出：PNG 文件到指定目录
  - 可选依赖 matplotlib（缺失时跳过，记录警告）

### 3. 更新 2.6 postprocess — 追加眼动验证

在现有处理逻辑的 SLAY 计算之后，追加：

步骤 N — 眼动验证（必须步骤，可通过 postprocess.eye_validation.enabled=false 跳过）：
  - 加载 BHV2 眼动数据（AnalogData.Eye）和固视窗口参数
  - 逐 trial、逐 stimulus onset 检查注视有效性：
    计算刺激