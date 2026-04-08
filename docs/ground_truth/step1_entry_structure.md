# Step 1：MATLAB 版本入口结构与调用树分析

> 分析日期：2026-04-03
> 信息来源：仅 MATLAB 源码直接阅读，无推断

---

## 提取任务一：全局参数表

### 来源文件：`process_pipeline_matlab/gen_globaL_par.m`（7 行）

| 参数名 | 值 | 数据类型 | 用途描述 | 硬编码? | 被哪些函数消费 |
|--------|-----|---------|---------|---------|--------------|
| `global_params.pre_onset` | 100 | double | onset 前取多少 ms 数据 | ✅ 硬编码 | `PostProcess_function.m:12` |
| `global_params.post_onset` | 700 | double | onset 后取多少 ms 数据 | ✅ 硬编码 | `PostProcess_function.m:13` |
| `global_params.psth_window_size_ms` | 30 | double | PSTH 滑动窗口大小（ms） | ✅ 硬编码 | `PostProcess_function.m:14` |
| `global_params.base_line_time` | -25:25 | 1×51 double | 基线时间窗（相对 onset，ms） | ✅ 硬编码 | `PostProcess_function.m:15` |
| `global_params.high_line_time1` | 50:250 | 1×201 double | 响应时间窗（相对 onset，ms） | ✅ 硬编码 | `PostProcess_function.m:16` |

**备注**：
- 所有 5 个参数全部硬编码，无一从数据中读取
- 无处理开关参数（无 enable/disable 机制）
- `gen_globaL_par.m` 将 struct 保存为 `global_params.mat`（:2-6）
- 仅 `PostProcess_function.m` 消费这些参数（:11 `load global_params.mat`）

---

## 提取任务二：调用树

### 完整运行顺序

```
0. Analysis_Fast.ipynb (Python/SpikeInterface)
   ├── 预处理 AP 数据 → 保存 binary
   └── 运行 Kilosort4 → 输出到 ./kilosort_def_5block_97/

1. gen_globaL_par.m
   └── 定义 global_params → 保存为 global_params.mat

2. Process_pipeline_2504.m (:11-14, for 循环)
   ├── Load_Data_function(path)        ← Util/Load_Data_function.m
   ├── PostProcess_function_raw(path)  ← Util/PostProcess_function_raw.m
   └── PostProcess_function(path)      ← Util/PostProcess_function.m
```

### Load_Data_function.m 调用树

```
Load_Data_function(data_path)                   ← Util/Load_Data_function.m (266 行)
│
├── mkdir('processed')                           (:4)
│
├── load_NI_data(NIFileName)                     (:11) → Util/load_NI_data.m
│   ├── 输入：NIDQ 文件路径（不含扩展名）
│   ├── 内部调用：load_meta()                    (load_NI_data.m:3) → Util/load_meta.m
│   ├── 主要输出：[NI_META, AIN, DCode_NI]
│   │   ├── NI_META: .meta 文件解析的 struct
│   │   ├── AIN: 模拟输入通道（photodiode），重采样到 1000 Hz
│   │   └── DCode_NI: struct {CodeLoc, CodeVal, CodeTime}，数字事件码
│   └── 写文件：无
│
├── parsing_ML_name(ml_name)                     (:16) → Util/parsing_ML_name.m
│   ├── 输入：BHV2 文件名字符串
│   ├── 主要输出：[exp_day, exp_subject]
│   └── 写文件：无
│
├── mlread(ml_name)                              (:23, 有缓存逻辑 :19-25)
│   │   → Util/mlread.m
│   ├── 内部调用：mlfileopen()                   (mlread.m:22) → Util/mlfileopen.m
│   │   └── 内部调用：mlbhv2()                   (mlfileopen.m:8) → Util/mlbhv2.m
│   │       └── mlbhv2.read_trial()             读取所有 trial 数据
│   ├── 输入：BHV2 文件路径
│   ├── 主要输出：trial_ML (struct array, 每个元素一个 trial)
│   └── 写文件：processed/ML_*.mat               (:24, 缓存 BHV2 解析结果)
│
├── load_IMEC_data(ImecFileName_LF)              (:29) → Util/load_IMEC_data.m
│   ├── 输入：IMEC LF 文件路径（不含扩展名）⚠️ 注意是 LF 不是 AP
│   ├── 内部调用：load_meta()                    (load_IMEC_data.m:2) → Util/load_meta.m
│   ├── 主要输出：[IMEC_META, DCode_IMEC]
│   │   ├── IMEC_META: LF .meta 文件 struct
│   │   └── DCode_IMEC: struct {CodeLoc, CodeVal, CodeTime}，IMEC 同步脉冲
│   └── 写文件：无
│
├── load_meta(ImecFileName_AP.meta)              (:31) → Util/load_meta.m
│   ├── 输入：AP .meta 文件路径
│   ├── 主要输出：IMEC_AP_META struct
│   └── 写文件：无
│
├── examine_and_fix_sync(DCode_NI, DCode_IMEC)   (:37) → Util/examine_and_fix_sync.m
│   ├── 输入：两组数字事件码 struct
│   ├── 主要输出：SyncLine struct {NI_time, imec_time}
│   ├── 写文件：无
│   └── 副作用：绘图到 figure subplot(3,6,13-15)
│
├── [内联逻辑] ML vs NI trial 数量一致性验证     (:43-74)
│   └── 输出：onset_times_by_trial_ML, onset_times_by_trial_SGLX；绘制散点图
│
├── [内联逻辑] 数据集提取                        (:77-85)
│   └── 输出：dataset_pool, img_set_name
│
├── [内联逻辑] 眼动验证（eye validation）        (:87-142)
│   └── 输出：trial_valid_idx, dataset_valid_idx, eye_matrix；绘制眼位密度图
│
├── [内联逻辑] Photodiode onset 检测与校准       (:144-258)
│   └── 输出：onset_time_ms（校准后的实际刺激呈现时间）；绘制诊断图 ×6
│
├── saveas(gcf, 'processed\DataCheck')            (:260-261)
│   └── 输出文件：processed/DataCheck.fig + processed/DataCheck.png
│
└── save(save_name, ...)                          (:262-265)
    └── 输出文件：processed/META_{exp_day}_{exp_subject}_{img_set_name}.mat
        包含变量：eye_matrix, ml_name, trial_valid_idx, dataset_valid_idx,
                  onset_time_ms, NI_META, AIN, DCode_NI, IMEC_META, DCode_IMEC,
                  SyncLine, IMEC_AP_META, img_size, g_number, exp_subject, exp_day
```

### PostProcess_function_raw.m 调用树

```
PostProcess_function_raw(data_path)              ← Util/PostProcess_function_raw.m (24 行)
│
├── load('processed/META_*.mat')                  (:6-7)
│   └── 输入：Load_Data_function 的输出
│
├── load('processed/ML_*.mat')                    (:8-9)
│   └── 输入：Load_Data_function 缓存的 trial_ML
│
├── run_bc(data_path)                             (:11) → Util/run_bc.m
│   ├── 内部调用：Bombcell 库函数 (bc.load.*, bc.dcomp.*, bc.qm.*)
│   ├── 输入：KS4 输出目录 + AP 原始 bin/meta
│   ├── 主要输出：[qMetric, unitType]
│   │   ├── qMetric: 质量指标矩阵
│   │   └── unitType: 单元类型分类向量
│   └── 写文件：processed/BC/ 目录（Bombcell 中间文件）
│
├── load_KS4_output(ks_path, IMEC_AP_META, SyncLine)  (:12) → Util/load_KS4_output.m
│   ├── 输入：
│   │   ├── ks_path: './kilosort_def_5block_97/sorter_output'（⚠️ 硬编码路径）
│   │   ├── IMEC_AP_META: AP meta struct（从 META_*.mat 加载）
│   │   └── SyncLine: 同步映射表（从 META_*.mat 加载）
│   ├── 内部调用：readNPY()（第三方 npy-matlab）
│   ├── 主要输出：UnitStrc (struct array)
│   │   每个元素：{waveform, spiketime_ms, spikepos, amplitudes}
│   │   spiketime_ms 已经过 SyncLine 时钟对齐（interp1）
│   └── 写文件：无
│
├── [内联逻辑] 清理 trial_ML 中不需要的字段       (:14-17)
│   └── 删除 Mouse 和 KeyInput 字段
│
├── saveas(gca, 'processed/BC.png')                (:21)
│   └── 输出文件：processed/BC.png（Bombcell 诊断图）
│
└── save(file_name_LOCAL, ...)                     (:22-23)
    └── 输出文件：processed/GoodUnitRaw_{meta_name}_g{N}.mat
        包含变量：UnitStrc, trial_ML, meta_data, qMetric, unitType
        格式：-v7.3（大文件支持）
```

### PostProcess_function.m 调用树

```
PostProcess_function(data_path)                  ← Util/PostProcess_function.m (93 行)
│
├── load('processed/GoodUnitRaw_*.mat')           (:6-7)
│   └── 输入：PostProcess_function_raw 的输出
│
├── load('global_params.mat')                     (:11)
│   └── 输入：gen_globaL_par 的输出
│
├── load('processed/fscale.mat')                  (:27) ⚠️ 来源不明
│   └── 输出变量：fscale（用于缩放 Bombcell waveform 模板）
│
├── readNPY('processed/BC/templates._bc_rawWaveforms.npy')  (:29)
│   └── 输入：Bombcell 产出的原始波形模板
│
├── [内联逻辑] 主循环：逐 unit 处理               (:31-87)
│   │
│   ├── Raster 构建                                (:32-42)
│   │   └── 对每个 good_trial 的 onset 前后时间窗提取 spike
│   │
│   ├── PSTH 计算（滑动窗口平均）                  (:48-58)
│   │   └── 窗口大小：psth_window_size_ms (30 ms)
│   │
│   ├── Response matrix 按图片平均                 (:59-62)
│   │
│   ├── 统计筛选：ranksum test                     (:63-68)
│   │   └── 条件：p1 < 0.001 && unitType ~= 0 && mean(highline) > mean(baseline)
│   │
│   ├── prune_wf(wf)                              (:70) → Util/prune_wf.m
│   │   ├── 输入：单个 unit 的全通道波形 [384 × T]
│   │   ├── 主要输出：[channels, wf_near_site]
│   │   │   ├── channels: peak channel ± 6 (步长 2) 的通道号
│   │   │   └── wf_near_site: 裁剪后的波形
│   │   └── 写文件：无
│   │
│   └── 组装 GoodUnitStrc                          (:71-84)
│       └── 字段：waveform, waveformchan, KSidx, spiketime_ms,
│                  spikepos, Raster(uint8), response_matrix_img(single),
│                  qm, unittype
│
└── save(file_name_LOCAL, ...)                     (:91-92)
    └── 输出文件：processed/GoodUnit_{name}_g{N}.mat
        包含变量：GoodUnitStrc, trial_ML, global_params, meta_data
        格式：-v7.3
```

### 未被主流程调用的工具函数

| 文件 | 在主流程中被调用？ | 实际用途 |
|------|------------------|---------|
| `Util/load_LFP_data.m` | ❌ 不在主流程中 | 加载 SpikeInterface 预处理后的 LFP 数据（从 LFPprep/ 目录） |
| `Util/PostProcess_function_LFP.m` | ❌ 不在主流程中 | ⚠️ 文件不存在或未扫描到（仅在 todo 中假设存在） |
| `Util/bhv_read.m` | 间接（通过 mlread→fallback） | 读旧格式 .bhv 文件；.bhv2 不走此路径 |
| `Util/parse_name.m` | ❌ 不在主流程中 | 从文件名解析日期/动物/g-number，含硬编码动物名→代号映射 |
| `process_pipeline_matlab/rm_template.m` | ❌ 独立脚本 | 批量删除 Bombcell RawWaveforms 目录（清理磁盘空间） |

---

## 提取任务三：跨阶段的状态传递

### Analysis_Fast.ipynb → Process_pipeline_2504.m

| Analysis_Fast.ipynb 产出 | 被谁消费 | 消费位置 |
|--------------------------|---------|---------|
| `./kilosort_def_5block_97/sorter_output/` 目录 | `load_KS4_output()` | PostProcess_function_raw.m:12 |
| 内含：spike_times.npy, spike_templates.npy, templates.npy, spike_positions.npy, amplitudes.npy, cluster_KSLabel.tsv | `readNPY()` + `textscan()` | load_KS4_output.m:3-15 |
| `./KS_TEMP2/` 目录（保存的预处理 binary） | ⚠️ 不确定是否被主流程消费 | — |

**⚠️ 不确定项**：`Analysis_Fast.ipynb` 中的预处理顺序是 `highpass_filter → detect_bad_channels → remove_channels → phase_shift → common_reference`。phase_shift 不在第一步。这与 CLAUDE.md 中规定的"phase_shift 必须在 bandpass_filter 之前"不一致。代码中写的确实是 highpass_filter 在前。

### gen_globaL_par.m → PostProcess_function.m

| 参数 | 传递方式 | 消费位置 |
|------|---------|---------|
| `global_params.pre_onset` (100) | 通过 `global_params.mat` 文件 | PostProcess_function.m:12 |
| `global_params.post_onset` (700) | 同上 | PostProcess_function.m:13 |
| `global_params.psth_window_size_ms` (30) | 同上 | PostProcess_function.m:14 |
| `global_params.base_line_time` (-25:25) | 同上 | PostProcess_function.m:15 |
| `global_params.high_line_time1` (50:250) | 同上 | PostProcess_function.m:16 |

注意：global_params 仅被 `PostProcess_function.m` 消费，`Load_Data_function.m` 和 `PostProcess_function_raw.m` 均不使用。

### Load_Data_function → PostProcess_function_raw（通过文件）

| 中间文件 | 写入位置 | 消费位置 |
|---------|---------|---------|
| `processed/META_*.mat` | Load_Data_function.m:265 | PostProcess_function_raw.m:6 |
| `processed/ML_*.mat` | Load_Data_function.m:24 | PostProcess_function_raw.m:9 |

### PostProcess_function_raw → PostProcess_function（通过文件）

| 中间文件 | 写入位置 | 消费位置 |
|---------|---------|---------|
| `processed/GoodUnitRaw_*.mat` | PostProcess_function_raw.m:23 | PostProcess_function.m:7 |
| `processed/BC/templates._bc_rawWaveforms.npy` | run_bc (Bombcell 内部) | PostProcess_function.m:29 |
| `processed/fscale.mat` | ⚠️ 来源不明，未在任何已读代码中发现写入逻辑 | PostProcess_function.m:27 |

---

## ⚠️ 不确定项汇总

- [ ] **fscale.mat 来源**：`PostProcess_function.m:27` 加载 `processed/fscale.mat`，但在所有已读 MATLAB 文件中未找到生成此文件的代码。可能由 Analysis_Fast.ipynb 的某个未记录步骤产出，或由其他脚本手动生成。需要确认。
- [ ] **Analysis_Fast.ipynb 预处理顺序**：highpass_filter 在 phase_shift 之前（cell-0），与 CLAUDE.md 规定的 "phase_shift 必须第一步" 不一致。MATLAB 版本代码中写的就是这个顺序。
- [ ] **KS_TEMP2 目录**：Analysis_Fast.ipynb 将预处理数据保存到 `./KS_TEMP2/`，但 Process_pipeline 主流程中未见消费此目录的代码。可能仅是 Kilosort 运行的中间产物。
- [ ] **PostProcess_function_LFP.m 是否存在**：在 Util/ 目录扫描结果中存在此文件名，但未在任何入口脚本中被调用。⚠️ 需要确认是否是遗留文件或独立使用的工具。
- [ ] **load_IMEC_data 读的是 LF 不是 AP**：`Load_Data_function.m:28` 构造的路径是 `*_t0.imec0.lf`，即从 LF 流中提取同步脉冲。AP 的 meta 单独用 `load_meta` 加载（:31）。这是有意为之（LF 文件更小，但也包含同步通道），还是遗留设计选择，需要确认。
- [ ] **硬编码通道号 385**：`load_IMEC_data.m:9` 直接用 `m.Data.x(385,:)` 提取同步通道。此值对 Neuropixels 1.0 的 LF 数据是否正确需要确认（LF 有 385 个通道：384 数据 + 1 sync）。
- [ ] **onset_time_ms 的 -5ms 校正**：`Load_Data_function.m:263` 写着 `onset_time_ms = onset_time_ms-5; % fix monitor time err in 60Hz`。此硬编码校正的物理依据是什么？是否应参数化？
- [ ] **parse_name.m 中的硬编码动物映射**：JianJian→M1, TuTu→M5, FaCai→M2, ZhuangZhuang→M3, MaoDan→M4。此函数未被主流程调用，但映射是硬编码的。

---

## 叶子函数快速参考

| 函数 | 文件 | 签名 | 输入 | 输出 | 写文件 |
|------|------|------|------|------|--------|
| `load_meta` | Util/load_meta.m | `metaData = load_meta(meta_file_name)` | .meta 文件路径 | struct（键值对） | 无 |
| `load_NI_data` | Util/load_NI_data.m | `[NI_META, AIN, DCode] = load_NI_data(NIFileName)` | NIDQ 路径（不含扩展名） | META + 模拟 + 数字 | 无 |
| `load_IMEC_data` | Util/load_IMEC_data.m | `[META_DATA, DCode] = load_IMEC_data(NIFileName)` | IMEC LF 路径（不含扩展名） | META + 数字 | 无 |
| `parsing_ML_name` | Util/parsing_ML_name.m | `[a,b] = parsing_ML_name(ml_name)` | BHV2 文件名 | [日期, 动物名] | 无 |
| `mlread` | Util/mlread.m | `[data,MLConfig,TrialRecord,...] = mlread(filename)` | 数据文件路径 | trial struct array | 无 |
| `mlfileopen` | Util/mlfileopen.m | `fp = mlfileopen(filepath,mode)` | 文件路径 + 模式 | 文件句柄对象 | 无 |
| `mlbhv2` | Util/mlbhv2.m | class（handle） | BHV2 文件路径 | 读写器对象 | 按模式 |
| `bhv_read` | Util/bhv_read.m | `BHV = bhv_read(varargin)` | .bhv 文件路径 | BHV struct | 无 |
| `examine_and_fix_sync` | Util/examine_and_fix_sync.m | `SyncLine = examine_and_fix_sync(DCode_NI, DCode_IMEC)` | 两组 DCode struct | SyncLine struct | 无 |
| `load_KS4_output` | Util/load_KS4_output.m | `[ks_output] = load_KS4_output(ks_path, IMEC_AP_META, SyncLine)` | KS4 目录 + META + SyncLine | UnitStrc array | 无 |
| `run_bc` | Util/run_bc.m | `[qMetric, unitType] = run_bc(data_path)` | 数据根目录 | 质量指标 + 类型 | processed/BC/ |
| `prune_wf` | Util/prune_wf.m | `[channels, wf_near_site] = prune_wf(input_wf)` | [N×T] 波形矩阵 | 裁剪通道+波形 | 无 |
| `parse_name` | Util/parse_name.m | `[day,subject,gnumber] = parse_name(file_name)` | 文件名字符串 | 日期+代号+g号 | 无 |
