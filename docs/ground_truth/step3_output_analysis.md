# Step 3：MATLAB 预处理流程输出端完整分析

> 分析日期：2026-04-03
> 信息来源：仅 MATLAB 源码直接阅读，无推断
> 已有材料：`step1_entry_structure.md`（调用树）、`step2_input_consumption.md`（输入消费点）

---

## 第一部分：所有写文件操作

### 写操作 #1
- **位置**：`gen_globaL_par.m:7`
- **输出文件路径**：`global_params.mat`（当前工作目录，即运行脚本的根目录）
- **文件格式**：.mat（MATLAB 默认 v7 格式）
- **内容描述**：`global_params` struct，包含 5 个字段：`pre_onset`(100), `post_onset`(700), `psth_window_size_ms`(30), `base_line_time`(-25:25), `high_line_time1`(50:250)
- **写入时机**：在整个 pipeline 运行之前，作为参数定义步骤
- **下游消费者**：`PostProcess_function.m:11`（`load global_params.mat`）
- **是临时文件还是最终输出**：临时（配置参数中间产物）

---

### 写操作 #2
- **位置**：`Load_Data_function.m:4`
- **输出文件路径**：`processed/`（在 `data_path` 下创建目录）
- **文件格式**：目录（`mkdir`）
- **内容描述**：创建 `processed` 子目录，用于存放所有中间和最终输出
- **写入时机**：Load_Data_function 最开始
- **下游消费者**：后续所有 save 操作的目标目录
- **是临时文件还是最终输出**：目录结构

---

### 写操作 #3
- **位置**：`Load_Data_function.m:24`
- **输出文件路径**：`processed/ML_{bhv2文件名去扩展名}.mat`（路径构造：`:18` `fullfile('processed',sprintf('ML_%s.mat',ml_name(1:end-5)))`）
- **文件格式**：.mat（MATLAB 默认格式）
- **内容描述**：`trial_ML` — mlread 解析 BHV2 文件后的 struct array（每个元素一个 trial），包含 BehavioralCodes、AnalogData、UserVars 等字段
- **写入时机**：BHV2 首次解析后（带缓存逻辑：`:19-25`，若文件已存在则跳过解析直接 load）
- **下游消费者**：`PostProcess_function_raw.m:9`（`load(fullfile('processed',ML_FILE(1).name)).trial_ML`）
- **是临时文件还是最终输出**：临时（BHV2 解析缓存，避免重复调用 MATLAB BHV2 读取器）

---

### 写操作 #4
- **位置**：`Load_Data_function.m:260`
- **输出文件路径**：`processed/DataCheck.fig`（MATLAB figure 格式）
- **文件格式**：.fig（MATLAB 可交互 figure 文件）
- **内容描述**：整个 `Load_Data_function` 中累积的诊断 figure（3×6 subplot 布局），包含同步检查图、trial 验证图、photodiode 校准图、眼位密度图等（详见第二部分图表清单）
- **写入时机**：Load_Data_function 末尾，所有检查完成后
- **下游消费者**：无代码消费；供人工查看
- **是临时文件还是最终输出**：最终输出（诊断图）

---

### 写操作 #5
- **位置**：`Load_Data_function.m:261`
- **输出文件路径**：`processed/DataCheck.png`（路径：`saveas(gcf,'processed\DataCheck.png')`）
- **文件格式**：.png
- **内容描述**：与写操作 #4 相同的 figure，PNG 光栅格式导出
- **写入时机**：紧接写操作 #4 之后
- **下游消费者**：无代码消费；供人工查看
- **是临时文件还是最终输出**：最终输出（诊断图）

---

### 写操作 #6
- **位置**：`Load_Data_function.m:262-265`
- **输出文件路径**：`processed/META_{exp_day}_{exp_subject}_{img_set_name}.mat`（路径构造：`:262` `fullfile('processed',sprintf('META_%s_%s_%s.mat', exp_day, exp_subject, img_set_name))`）
- **文件格式**：.mat（MATLAB 默认格式）
- **内容描述**：包含以下变量：
  - `eye_matrix` — 眼动数据矩阵 [2 × onset_times × time_points]
  - `ml_name` — BHV2 文件名
  - `trial_valid_idx` — 眼动验证通过的 onset 标记 [1 × onset_times]
  - `dataset_valid_idx` — 数据集有效索引 [1 × onset_times]
  - `onset_time_ms` — photodiode 校准后的 onset 时间（已含 -5ms 校正）[1 × onset_times]
  - `NI_META` — NIDQ meta struct
  - `AIN` — photodiode 模拟信号（已重采样到 1000 Hz）
  - `DCode_NI` — NIDQ 数字事件码 struct
  - `IMEC_META` — IMEC LF meta struct
  - `DCode_IMEC` — IMEC sync 脉冲 struct
  - `SyncLine` — IMEC↔NIDQ 时钟映射 struct {NI_time, imec_time}
  - `IMEC_AP_META` — IMEC AP meta struct
  - `img_size` — 图片集中图片总数
  - `g_number` — SpikeGLX 录制的 g 编号
  - `exp_subject` — 实验动物名
  - `exp_day` — 实验日期
- **写入时机**：Load_Data_function 末尾，`onset_time_ms` 已经过 -5ms 校正（`:263`）之后
- **下游消费者**：`PostProcess_function_raw.m:6-7`（`load(fullfile(pwd,'processed',meta_file(1).name))`）
- **是临时文件还是最终输出**：临时（核心中间产物，连接 Load_Data_function → PostProcess_function_raw）

---

### 写操作 #7
- **位置**：`run_bc.m:8`
- **输出文件路径**：`processed/BC/`（在 `data_path` 下创建目录：`:7` `fullfile(data_path, "processed","BC")`）
- **文件格式**：目录（`mkdir`）
- **内容描述**：Bombcell 质控输出目录
- **写入时机**：Bombcell 运行之前创建
- **下游消费者**：Bombcell 内部函数写入此目录
- **是临时文件还是最终输出**：目录结构

---

### 写操作 #8
- **位置**：`run_bc.m:16,24-25`（Bombcell 库内部）
- **输出文件路径**：`processed/BC/` 目录下的文件，由 `bc.load.loadEphysData` 和 `bc.qm.runAllQualityMetrics` 写入。已知文件包括：
  - `templates._bc_rawWaveforms.npy`（被 `PostProcess_function.m:29` 消费）
  - 其他 Bombcell 内部输出文件（具体文件列表由 Bombcell 库决定，MATLAB 源码中未直接控制）
- **文件格式**：.npy + Bombcell 库内部格式
- **内容描述**：
  - `templates._bc_rawWaveforms.npy`：原始波形模板，shape 推断为 [n_units × n_channels × n_timepoints]
  - 其他质量指标相关文件
- **写入时机**：`PostProcess_function_raw.m:11` 调用 `run_bc(data_path)` 时
- **下游消费者**：`PostProcess_function.m:29`（`readNPY(fullfile('processed/BC/templates._bc_rawWaveforms.npy'))`）
- **是临时文件还是最终输出**：临时（中间质控产物）

---

### 写操作 #9
- **位置**：`PostProcess_function_raw.m:21`
- **输出文件路径**：`processed/BC.png`（路径：`saveas(gca,fullfile("processed/",'BC.png'))`）
- **文件格式**：.png
- **内容描述**：Bombcell 质控诊断图。注意：`:19-20` 先 `drawnow` 再 `figure(8)`，说明 Bombcell 库内部在运行过程中创建了 figure，这里是将 Bombcell 生成的 figure 8 保存为 PNG
- **写入时机**：Bombcell 运行完毕后（`run_bc` 返回后）
- **下游消费者**：无代码消费；供人工查看
- **是临时文件还是最终输出**：最终输出（诊断图）

---

### 写操作 #10
- **位置**：`PostProcess_function_raw.m:22-23`
- **输出文件路径**：`processed/GoodUnitRaw_{META文件名去前缀去扩展名}_g{N}.mat`（路径构造：`:22` `fullfile('processed',sprintf('GoodUnitRaw_%s_g%s.mat',meta_file(1).name(6:end-4), meta_data.g_number))`）
- **文件格式**：.mat（`-v7.3`，HDF5 格式，支持大文件 >2GB）
- **内容描述**：
  - `UnitStrc` — struct array，每个元素一个 unit：{waveform, spiketime_ms（已 SyncLine 对齐）, spikepos, amplitudes}
  - `trial_ML` — BHV2 trial struct array（已清理 Mouse 和 KeyInput 字段）
  - `meta_data` — META_*.mat 的完整内容（即写操作 #6 的所有变量）
  - `qMetric` — Bombcell 质量指标矩阵
  - `unitType` — Bombcell 单元类型分类向量
- **写入时机**：PostProcess_function_raw 末尾
- **下游消费者**：`PostProcess_function.m:6-7`（`load(fullfile('processed',meta_file(1).name))`）
- **是临时文件还是最终输出**：临时（核心中间产物，连接 PostProcess_function_raw → PostProcess_function）

---

### 写操作 #11
- **位置**：`PostProcess_function.m:91-92`
- **输出文件路径**：`processed/GoodUnit_{name}_g{N}.mat`（路径构造：`:91` `fullfile('processed',sprintf('GoodUnit_%s_g%s.mat',meta_file(1).name(13:end-7), meta_data.g_number))`）
- **文件格式**：.mat（`-v7.3`，HDF5 格式）
- **内容描述**：
  - `GoodUnitStrc` — struct array，仅含通过统计筛选的 "good" units，每个元素包含：
    - `waveform` — 裁剪后的波形 [channels × T]（prune_wf 输出）
    - `waveformchan` — 裁剪的通道号（peak ± 6，步长 2）
    - `KSidx` — 原始 KS4 unit 编号
    - `spiketime_ms` — spike 时间序列（NI 时钟域）
    - `spikepos` — spike 位置
    - `Raster` — raster 矩阵 uint8 [n_good_trials × (pre_onset+post_onset)]
    - `response_matrix_img` — 按图片平均的 PSTH single [img_size × (pre_onset+post_onset)]
    - `qm` — 该 unit 的 Bombcell 质量指标行
    - `unittype` — 该 unit 的 Bombcell 类型
  - `trial_ML` — BHV2 trial struct array
  - `global_params` — 全局参数 struct（含新增字段 `PsthRange`，`:89`）
  - `meta_data` — META 数据
- **写入时机**：PostProcess_function 末尾，所有 unit 筛选完成后
- **下游消费者**：无（最终输出，供后续分析脚本或手动加载使用）
- **是临时文件还是最终输出**：**最终输出**（pipeline 的核心最终产物）

---

### 写操作 #12（Analysis_Fast.ipynb — Python/SpikeInterface）
- **位置**：`Analysis_Fast.ipynb:cell-1`
- **输出文件路径**：`./KS_TEMP2/`（`rec3.save(folder='./KS_TEMP2', format='binary', ...)`）
- **文件格式**：SpikeInterface binary 格式（binary.json + traces_cached_seg0.raw）
- **内容描述**：预处理后的 AP 数据，binary 格式保存。包含：
  - `traces_cached_seg0.raw` — int16 二进制数据
  - `binary.json` — 元信息（采样率、通道数等）
  - 其他 SpikeInterface 元数据文件
- **写入时机**：AP 预处理（highpass → bad channel detect → remove channels → phase_shift → CMR）完成后
- **下游消费者**：同一 cell 中的 `run_sorter` 使用 `corrected_rec` 作为输入（`corrected_rec` 是 `rec3.save()` 的返回值，指向已保存的数据）
- **是临时文件还是最终输出**：临时（预处理中间产物，供 KS4 读取）

---

### 写操作 #13（Analysis_Fast.ipynb — Python/SpikeInterface）
- **位置**：`Analysis_Fast.ipynb:cell-1`
- **输出文件路径**：`./kilosort_def_5block_97/`（`run_sorter(..., folder="./kilosort_def_5block_97", ...)`）
- **文件格式**：Kilosort4 输出格式（.npy + .tsv）
- **内容描述**：KS4 sorting 输出，已知被消费的文件：
  - `sorter_output/spike_times.npy`（`load_KS4_output.m:5`）
  - `sorter_output/spike_templates.npy`（`load_KS4_output.m:5`）
  - `sorter_output/templates.npy`（`load_KS4_output.m:5`）
  - `sorter_output/spike_positions.npy`（`load_KS4_output.m:5`）
  - `sorter_output/amplitudes.npy`（`load_KS4_output.m:5`）
  - `sorter_output/cluster_KSLabel.tsv`（`load_KS4_output.m:12`）
- **写入时机**：Kilosort4 运行完毕后
- **下游消费者**：`load_KS4_output.m`（被 `PostProcess_function_raw.m:12` 调用）+ `run_bc.m:3`（Bombcell 也读此目录）
- **是临时文件还是最终输出**：临时（sorting 中间产物）

---

### 写操作 #14（不在主流程中 — rm_template.m）
- **位置**：`rm_template.m:16`
- **输出文件路径**：删除 `processed/BC/RawWaveforms/` 目录（`rmdir(wm_dir,'s')`）
- **文件格式**：N/A（删除操作）
- **内容描述**：批量删除 Bombcell 产出的 RawWaveforms 目录以释放磁盘空间
- **写入时机**：独立脚本，手动执行
- **下游消费者**：无
- **是临时文件还是最终输出**：清理脚本

---

## 第二部分：所有绘图操作

### 图表 #1
- **位置**：`Load_Data_function.m:34-35`（创建 figure）+ `examine_and_fix_sync.m:16-21`（绘图）
- **图表类型**：折线图（时间序列）
- **数据来源**：`d1 = diff(SyncLine.imec_time)` — IMEC sync 脉冲间隔
- **图表用途**：检查 IMEC 端 sync 脉冲间隔是否稳定（预期 ~1000 ms），检测丢脉冲
- **保存路径**：作为 `processed/DataCheck.fig` + `.png` 的 subplot(3,6,13) 部分
- **是否交互式**：否（嵌入 subplot）

---

### 图表 #2
- **位置**：`examine_and_fix_sync.m:19-21`
- **图表类型**：折线图（时间序列）
- **数据来源**：`d2 = diff(SyncLine.NI_time)` — NIDQ sync 脉冲间隔
- **图表用途**：检查 NIDQ 端 sync 脉冲间隔是否稳定，对称地检查另一端
- **保存路径**：subplot(3,6,14)
- **是否交互式**：否

---

### 图表 #3
- **位置**：`examine_and_fix_sync.m:61-65`
- **图表类型**：折线图（时间序列）
- **数据来源**：`terr(ii) = SyncLine.NI_time(ii) - SyncLine.imec_time(ii)` — NI 与 IMEC 时钟偏移
- **图表用途**：检查两个设备的时钟漂移量是否在合理范围内（ylim [-10, 10] 秒）
- **保存路径**：subplot(3,6,15)
- **是否交互式**：否

---

### 图表 #3b（条件性——仅 sync 失败时）
- **位置**：`examine_and_fix_sync.m:44-51`
- **图表类型**：折线图（时间序列）× 2
- **数据来源**：修复后的 `d1`、`d2`
- **图表用途**：sync 脉冲数量不匹配时，修复后重新绘制间隔图以验证修复效果
- **保存路径**：`nexttile`（追加到当前 figure）
- **是否交互式**：否
- **⚠️ 注意**：此分支包含 `keyboard` 命令（`:28`），会暂停执行等待人工干预

---

### 图表 #4
- **位置**：`Load_Data_function.m:68-74`
- **图表类型**：散点图
- **数据来源**：`onset_times_by_trial_SGLX`（X 轴）vs `onset_times_by_trial_ML`（Y 轴）— 每 trial 的 onset 次数
- **图表用途**：检查 MonkeyLogic 和 SpikeGLX 记录的每 trial onset 数量是否一致
- **保存路径**：subplot(3,6,1)
- **是否交互式**：否
- **备注**：title 显示最大误差 `MaxErr`

---

### 图表 #5
- **位置**：`Load_Data_function.m:127-142`
- **图表类型**：热图（imagesc，伪彩色密度图）
- **数据来源**：`density_plot` — 由 `eye_matrix` 均值（每 onset 平均眼位）按 [-8,8] × [-8,8] 度 bin 计数
- **图表用途**：检查眼位分布是否集中在注视点附近，检测系统性偏移
- **保存路径**：subplot(3,6,12)
- **是否交互式**：否

---

### 图表 #6
- **位置**：`Load_Data_function.m:159-163`
- **图表类型**：热图（imagesc，时间×trial 矩阵）
- **数据来源**：`po_dis` — 每 trial 的 photodiode 信号（zscore 归一化），时间范围 [-10, +100] ms 相对于数字 onset
- **图表用途**：检查原始 photodiode 信号的 onset 响应模式
- **保存路径**：subplot(3,6,2)
- **是否交互式**：否
- **备注**：title = "Original Signal"

---

### 图表 #7
- **位置**：`Load_Data_function.m:169-173`
- **图表类型**：热图（imagesc，时间×trial 矩阵）
- **数据来源**：`diff_data = diff(po_dis')` — photodiode 信号的一阶差分
- **图表用途**：检查 photodiode 的变化点是否清晰
- **保存路径**：subplot(3,6,3)
- **是否交互式**：否
- **备注**：title = "Diff Signal"

---

### 图表 #8
- **位置**：`Load_Data_function.m:175-179`
- **图表类型**：热图（imagesc，时间×trial 矩阵）
- **数据来源**：`diff_abs_data = abs(diff(po_dis'))` — photodiode 差分的绝对值
- **图表用途**：检查极性无关的变化点幅度
- **保存路径**：subplot(3,6,4)
- **是否交互式**：否
- **备注**：title = "Diff Abs Signal"

---

### 图表 #9
- **位置**：`Load_Data_function.m:194-198`
- **图表类型**：热图（imagesc，时间×trial 矩阵）
- **数据来源**：`po_dis` — 极性校正后的 photodiode 信号（`:186-191` 检测差分方向，反转负向 trial）
- **图表用途**：验证极性校正是否成功，校正后所有 trial 应在 onset 处上升
- **保存路径**：subplot(3,6,5)
- **是否交互式**：否
- **备注**：title = "New Signal"

---

### 图表 #10
- **位置**：`Load_Data_function.m:205-208`
- **图表类型**：均值±标准差折线图（shadedErrorBar）
- **数据来源**：`mean(po_dis)` ± `std(po_dis)` — 所有 trial 的 photodiode 信号均值；`thres` 水平线
- **图表用途**：检查校准前的 photodiode 平均响应，显示阈值线
- **保存路径**：subplot(3,6,7)
- **是否交互式**：否
- **备注**：title = "Before time calibration"；`shadedErrorBar` 是第三方绘图函数

---

### 图表 #11
- **位置**：`Load_Data_function.m:215-217`
- **图表类型**：直方图 + 垂直线
- **数据来源**：`onset_latency` — 每 trial 的 photodiode onset 延迟（相对于数字 onset，ms）
- **图表用途**：检查 onset 延迟分布，两条 xline 标示最小和最大延迟
- **保存路径**：subplot(3,6,10)
- **是否交互式**：否

---

### 图表 #12
- **位置**：`Load_Data_function.m:219-227`
- **图表类型**：均值±标准差折线图（shadedErrorBar）
- **数据来源**：校准后重新提取的 `po_dis` — 使用 `onset_time_ms`（已加 onset_latency）重新对齐 AIN 信号
- **图表用途**：验证时间校准后的 photodiode 信号是否在 time=0 处更尖锐对齐
- **保存路径**：subplot(3,6,8)
- **是否交互式**：否
- **备注**：title = "After time calibration"

---

### 图表 #13
- **位置**：`Load_Data_function.m:229-241`
- **图表类型**：均值±标准差折线图（shadedErrorBar）
- **数据来源**：仅含 `dataset_valid_idx > 0` 的 trial 的校准后 photodiode 信号
- **图表用途**：验证排除非注视 trial 后的 photodiode 信号质量
- **保存路径**：subplot(3,6,9)
- **是否交互式**：否
- **备注**：title = "Exclude Non-Look Trial"

---

### 图表 #14
- **位置**：`Load_Data_function.m:242`
- **图表类型**：sgtitle（figure 全局标题）
- **数据来源**：`pwd` — 当前工作目录路径
- **图表用途**：标识该 figure 对应哪个 session 数据
- **保存路径**：附着在整个 figure 上
- **是否交互式**：否

---

### 图表 #15
- **位置**：`Load_Data_function.m:246-258`
- **图表类型**：折线图
- **数据来源**：`onset_t(img) = sum(valid_onset==img)` — 第一个数据集中每张图片的有效 trial 数
- **图表用途**：检查各图片的 trial 覆盖是否均匀
- **保存路径**：subplot(3,6,11)
- **是否交互式**：否

---

### 图表 #16（Bombcell 内部生成）
- **位置**：`run_bc.m` 内部，由 Bombcell 库函数 `bc.qm.runAllQualityMetrics` 生成
- **图表类型**：未知（Bombcell 库内部行为）
- **数据来源**：质量指标计算过程
- **图表用途**：Bombcell 质控诊断
- **保存路径**：由 `PostProcess_function_raw.m:19-21` 保存为 `processed/BC.png`
- **是否交互式**：否
- **⚠️ 注意**：`PostProcess_function_raw.m:19` 先 `drawnow`，`:20` 再 `figure(8)` 获取 Bombcell 创建的 figure 句柄。这表明 Bombcell 库在运行时内部创建了 figure 8，代码中未直接控制其内容。

---

## 第三部分：文件输出依赖图

```
Analysis_Fast.ipynb (Python/SpikeInterface)
├── 产出：./KS_TEMP2/ (预处理 binary)                    [写操作 #12]
│     └── 被消费：Analysis_Fast.ipynb:cell-1 (run_sorter 的 corrected_rec 输入)
└── 产出：./kilosort_def_5block_97/sorter_output/         [写操作 #13]
      ├── spike_times.npy
      ├── spike_templates.npy
      ├── templates.npy
      ├── spike_positions.npy
      ├── amplitudes.npy
      └── cluster_KSLabel.tsv
            ├── 被消费：load_KS4_output.m:2-15 (via PostProcess_function_raw.m:12)
            └── 被消费：run_bc.m:3 (Bombcell ephysKilosortPath)

gen_globaL_par.m
└── 产出：global_params.mat                               [写操作 #1]
      └── 被消费：PostProcess_function.m:11

Process_pipeline_2504.m (per session 循环)
│
├── Load_Data_function(path)
│     ├── 产出：processed/ (目录)                          [写操作 #2]
│     ├── 产出：processed/ML_*.mat (BHV2 解析缓存)        [写操作 #3]
│     │     └── 被消费：PostProcess_function_raw.m:9
│     ├── 产出：processed/DataCheck.fig                    [写操作 #4]
│     │     └── 被消费：无（人工查看）
│     ├── 产出：processed/DataCheck.png                    [写操作 #5]
│     │     └── 被消费：无（人工查看）
│     └── 产出：processed/META_*.mat                       [写操作 #6]
│           └── 被消费：PostProcess_function_raw.m:6-7
│
├── PostProcess_function_raw(path)
│     ├── 产出：processed/BC/ (目录)                       [写操作 #7]
│     ├── 产出：processed/BC/*.npy + 内部文件              [写操作 #8]
│     │     └── 被消费：PostProcess_function.m:29 (templates._bc_rawWaveforms.npy)
│     ├── 产出：processed/BC.png                           [写操作 #9]
│     │     └── 被消费：无（人工查看）
│     └── 产出：processed/GoodUnitRaw_*.mat                [写操作 #10]
│           └── 被消费：PostProcess_function.m:6-7
│
└── PostProcess_function(path)
      └── 产出：processed/GoodUnit_*.mat                   [写操作 #11]
            └── 被消费：无（★ 最终输出）

⚠️ 来源不明的输入文件：
   processed/fscale.mat
      └── 被消费：PostProcess_function.m:27
      └── 未在任何已分析代码中找到生成逻辑
```

---

## 第四部分：质检图清单（按流程顺序）

| 图表# | subplot 位置 | 生成位置 | 检查内容 | 对应处理步骤 |
|-------|-------------|---------|---------|------------|
| #1 | (3,6,13) | `examine_and_fix_sync.m:16-18` | IMEC sync 脉冲间隔稳定性 | IMEC↔NIDQ 时钟对齐 |
| #2 | (3,6,14) | `examine_and_fix_sync.m:19-21` | NIDQ sync 脉冲间隔稳定性 | IMEC↔NIDQ 时钟对齐 |
| #3 | (3,6,15) | `examine_and_fix_sync.m:61-65` | NI-IMEC 时钟偏移量 | IMEC↔NIDQ 时钟对齐 |
| #4 | (3,6,1) | `Load_Data_function.m:68-74` | ML vs SGLX trial onset 一致性 | ML↔NI trial 验证 |
| #5 | (3,6,12) | `Load_Data_function.m:139-142` | 眼位空间分布密度 | 眼动验证 |
| #6 | (3,6,2) | `Load_Data_function.m:159-163` | 原始 photodiode 信号热图 | Photodiode 校准 |
| #7 | (3,6,3) | `Load_Data_function.m:169-173` | Photodiode 差分信号 | Photodiode 校准 |
| #8 | (3,6,4) | `Load_Data_function.m:175-179` | Photodiode 差分绝对值 | Photodiode 校准 |
| #9 | (3,6,5) | `Load_Data_function.m:194-198` | 极性校正后信号 | Photodiode 校准 |
| #10 | (3,6,7) | `Load_Data_function.m:205-208` | 校准前均值±std + 阈值线 | Photodiode 校准 |
| #11 | (3,6,10) | `Load_Data_function.m:215-217` | Onset 延迟分布直方图 | Photodiode 校准 |
| #12 | (3,6,8) | `Load_Data_function.m:219-227` | 校准后均值±std | Photodiode 校准 |
| #13 | (3,6,9) | `Load_Data_function.m:229-241` | 排除非注视 trial 后均值±std | Photodiode 校准 |
| #14 | sgtitle | `Load_Data_function.m:242` | Session 路径标识 | — |
| #15 | (3,6,11) | `Load_Data_function.m:246-258` | 每图片有效 trial 数分布 | 数据集验证 |
| #16 | figure(8) | `run_bc.m` (Bombcell 内部) | Bombcell 质控指标 | Bombcell 质控 |

**Figure 布局说明**：
- `Load_Data_function.m:34-35` 创建一个 3×6 subplot 布局的 figure（`set(gcf,'Position',[100 80 1800 950])`）
- subplot 占用情况：(3,6,1) (3,6,2) (3,6,3) (3,6,4) (3,6,5) (3,6,7) (3,6,8) (3,6,9) (3,6,10) (3,6,11) (3,6,12) (3,6,13) (3,6,14) (3,6,15)
- subplot(3,6,6)、(3,6,16)、(3,6,17)、(3,6,18) 未使用
- 该 figure 保存为 `processed/DataCheck.fig` + `processed/DataCheck.png`

---

## 第五部分：输出文件汇总表

### 按类型分类

| 文件路径模式 | 格式 | 类型 | 大小估计 | 生成位置 | 写操作# |
|-------------|------|------|---------|---------|---------|
| `global_params.mat` | .mat v7 | 配置参数 | ~1 KB | `gen_globaL_par.m:7` | #1 |
| `processed/ML_*.mat` | .mat v7 | BHV2 缓存 | ~数 MB | `Load_Data_function.m:24` | #3 |
| `processed/META_*.mat` | .mat v7 | 核心中间产物 | ~数十 MB（含 AIN、eye_matrix） | `Load_Data_function.m:265` | #6 |
| `processed/BC/` 目录 | 目录 + .npy | Bombcell 输出 | ~数百 MB（含 RawWaveforms） | `run_bc.m:8,16,24-25` | #7, #8 |
| `processed/GoodUnitRaw_*.mat` | .mat v7.3 | 核心中间产物 | ~数百 MB-GB | `PostProcess_function_raw.m:23` | #10 |
| `processed/GoodUnit_*.mat` | .mat v7.3 | **最终输出** | ~数十-数百 MB | `PostProcess_function.m:92` | #11 |
| `./KS_TEMP2/` 目录 | binary | 预处理中间产物 | ~数百 GB | `Analysis_Fast.ipynb:cell-1` | #12 |
| `./kilosort_def_5block_97/` 目录 | .npy + .tsv | KS4 输出 | ~数十 MB | `Analysis_Fast.ipynb:cell-1` | #13 |

### 诊断图文件

| 文件路径 | 格式 | 内容 | 生成位置 | 写操作# |
|---------|------|------|---------|---------|
| `processed/DataCheck.fig` | .fig | 3×6 subplot 诊断大图 | `Load_Data_function.m:260` | #4 |
| `processed/DataCheck.png` | .png | 同上 PNG 版本 | `Load_Data_function.m:261` | #5 |
| `processed/BC.png` | .png | Bombcell 质控图 | `PostProcess_function_raw.m:21` | #9 |

---

## ⚠️ 不确定项

- [ ] **Bombcell 内部写了哪些文件到 `processed/BC/`**：已知 `templates._bc_rawWaveforms.npy` 被 `PostProcess_function.m:29` 消费。`rm_template.m` 中删除 `processed/BC/RawWaveforms/` 目录，说明 Bombcell 还创建了 `RawWaveforms/` 子目录。其他文件由 Bombcell 库内部控制，代码中未直接列出完整文件列表。
- [ ] **`fscale.mat` 的生成来源**：`PostProcess_function.m:27` 加载 `processed/fscale.mat`，但在所有已分析的 MATLAB 文件中（包括 Analysis_Fast.ipynb）均未找到生成此文件的代码。此文件可能由：(a) 未被包含在代码库中的脚本生成；(b) 手动从其他来源拷贝；(c) 某个未记录的 Bombcell 后处理步骤产出。需要向原作者确认。
- [ ] **Bombcell figure 句柄号**：`PostProcess_function_raw.m:20` 使用 `figure(8)` 获取 Bombcell 内部创建的图。此 figure 编号 8 是否在所有 Bombcell 版本中一致，还是依赖特定 Bombcell 版本行为。
- [ ] **`-v7.3` 格式选择的原因**：`GoodUnitRaw_*.mat` 和 `GoodUnit_*.mat` 使用 `-v7.3`（HDF5 格式），推测是因为文件可能超过 2GB。但代码中没有显式注释说明。
- [ ] **`KS_TEMP2` 是否在流程结束后被清理**：`Analysis_Fast.ipynb` 产出 `KS_TEMP2` 目录，但 `Process_pipeline_2504.m` 主流程中未见清理逻辑。`rm_template.m` 仅删除 `BC/RawWaveforms/`。此大目录（可达数百 GB）的生命周期管理方式不明。
