# pynpxpipe 开发进度

## M1 进度总览 ✅ 已完成

完成：22/22 模块 | 测试：779 passed | 覆盖率：~80%

<details>
<summary>模块依赖图（全部 ✅）</summary>

```
Layer 0 (core):  errors → config → session → checkpoint → logging → resources → base
                   ✅       ✅       ✅         ✅           ✅        ✅        ✅

Layer 1 (io):    spikeglx ──→ imec_nidq_align ──┐
                    ✅              ✅            │
                 bhv ──→ bhv_nidq_align ────────┤
                  ✅          ✅                 │
                      photodiode_calibrate ─────┘
                              ✅
                 nwb_writer              plots (style/sync/curate/
                    ✅                    postprocess/preprocess)
                                               ✅

Layer 2 (stages): discover → preprocess → sort ──→ synchronize → curate → postprocess → export
                     ✅          ✅        ✅           ✅          ✅        ✅         ✅

Layer 3 (orch):  runner → cli_main
                   ✅       ✅
```

</details>

<details>
<summary>已完成模块明细</summary>

| 模块 | 文件 | 测试数 | 备注 |
|------|------|--------|------|
| errors | core/errors.py | 16 | 含 CheckpointError |
| config | core/config.py | 285 | 含集成测试 |
| logging | core/logging.py | 13 | |
| checkpoint | core/checkpoint.py | 38 | |
| resources | core/resources.py | 41 | |
| session | core/session.py | 33 | |
| base | stages/base.py | 20 | |
| spikeglx | io/spikeglx.py | 35 | |
| bhv | io/bhv.py | 27 | 真实 MATLAB Engine，无 mock |
| discover | stages/discover.py | 16 | |
| preprocess | stages/preprocess.py | 19 | |
| sort | stages/sort.py | 16 | |
| synchronize | stages/synchronize.py | 20 | three-level alignment, all IO mocked |
| curate | stages/curate.py | 19 | si.load + create_sorting_analyzer, all SI mocked |
| nwb_writer | io/nwb_writer.py | 32 | add_trial_column API（非 TimeIntervals），含集成写盘 |
| imec_nidq_align | io/sync/imec_nidq_align.py | 11 | |
| bhv_nidq_align | io/sync/bhv_nidq_align.py | 25 | |
| photodiode_calibrate | io/sync/photodiode_calibrate.py | 30 | |
| export | stages/export.py | 15 | NWBWriter + si.load + pynwb.NWBHDF5IO 全 mock，含文件清理 |
| postprocess | stages/postprocess.py | 26 | SLAY Spearman+方向滤波；OOM 重试；眼动 mock；bin 边界浮点修正 |
| runner | pipelines/runner.py | 16 | 7-stage 编排；auto-config via ResourceDetector；get_status |
| cli_main | cli/main.py | 21 | CliRunner 测试；run/status/reset-stage；架构约束测试 |

</details>

M1 遗留项（不阻塞 M2）：集成验证待做。`sync_plots` 已由 M2 Phase Plots 重构为独立 `plots/` 子包实现。

---

## M2 进度总览

目标：Panel Web UI + Pure-Python BHV2 | 详细规划见 `docs/ROADMAP.md`

### 轨道 A — Panel Web UI（主分支）

| 阶段 | 任务 | 状态 | 说明 |
|------|------|------|------|
| A1 | 基础设施搭建 | ✅ | panel 依赖 + ui/__init__.py + state.py + app.py spike（18 tests） |
| A2 | 配置与元信息表单 | ✅ | session_form / subject_form / pipeline_form / sorting_form / stage_selector（30 tests） |
| A3 | 执行与进度追踪 | ✅ | ProgressBridge stage_statuses + run_panel + progress_view + log_viewer（28 tests） |
| A4 | 结果查看与恢复 | ✅ | status_view + session_loader（23 tests） |
| A5 | 整合与打磨 | ✅ | FastListTemplate 布局 + 错误 banner + 导航切换（11 tests） |
| UI S1 | 默认值修复 + Motion/Sync/Postprocess 卡片 | ✅ | sorting_form bug 修复 + pipeline_form 新增 3 张卡片（约 15 tests） |
| UI S2 | SessionForm 简易/高级模式 | ✅ | data_dir 自动发现 + advanced_toggle（约 15 tests） |
| UI S3 | BrowsableInput 组件 + 集成 | ✅ | browsable_input.py（15 tests）+ session_form/subject_form/session_loader 集成（+8 tests） |
| UI S4 | app.py 两列布局 | ✅ | configure_section 改为 pn.Row(left_col, right_col)（5 tests，153 total） |
| UI S5 | Pipeline/Sorting form 与 core/config.py 对齐 | ✅ | pipeline_form +16 widgets, sorting_form +7 analyzer widgets, harness 4 coverage tests（+40 tests，193 total） |
| UI S6 | Chat Help（LLM 助手） | ✅ | src/pynpxpipe/agent/{llm_client,chat_harness}.py + ui/components/chat_help.py，optional `[chat]` extra，self-check harness |
| UI S7 | Figures Viewer | ✅ | ui/components/figs_viewer.py — Review 区浏览 pipeline 产物图表 |
| UI S8 | SubjectForm save-yaml 按钮 | ✅ | subject_form.py — 当前填写的 subject 一键导出为 monkeys/*.yaml |
| feat E-selfheal | export raw 流自动检查并修复(self-heal) | ✅ | 续传升级为自愈:不只补缺失流,还检出并修复**残缺流**。`nwb_writer._repair_incomplete_streams`(写循环前跑)逐条期望流对比 NWB `data.shape[0]` vs 源 `.bin` `get_num_samples()`:缺失→留给写循环;完整→跳过;**残缺→h5py 删掉重写**(源 .bin 是真值,无数据损失,最坏重写一条)。检查深度 `export.repair_verify`:`shape`(默认,样本数,毫秒级)/`full`(长度一致的流再逐 chunk bit-exact 重扫)。`time_range` 子集导出跳过。config `export.repair_incomplete_streams`(默认 true)+`repair_verify`;`_export_phase3_background` 从 config 读取传入 `append_raw_data`;返回加 `streams_repaired`/`repaired_names`。spec `docs/specs/export.md` Phase3 step16;+6 RED→GREEN(test_nwb_writer 截断/完整/full-内容 3 + config defaults/override/invalid 3;UI harness 2 字段→None）（2026-07-01） |
| 修复 E-resume | export Phase 3 断点续传 + checkpoint 时序 bug | ✅ | **时序 bug**:completed checkpoint 原写在 Phase 3(raw 压缩)之前(`export.py` 0.85 处),91% 中断(Phase 3 中)会被静默记成 completed,重跑跳过 export → raw 不完整。修复:completed checkpoint 挪到 **Phase 3 成功之后**写(`_finalize_phase3`,带 `raw_data_verified_at`);Phase 3 抛错写 failed checkpoint 并 re-raise。**真正断点续传(每流粒度)**:(A) `_nwb_phase1_done` — NWB 可只读打开即视为 Phase 1 已完成 → 重跑跳过 Phase 1(否则重建 NWB 抹掉已写 raw);(B) `append_raw_data` 改为每个 raw 流(AP/LF per-probe + NIDQ)各自 `open→write→close` 一个持久周期(新 `_append_one_stream`),写完即落盘,现有"已存在则跳过"幂等此时才真正生效。中断 91% → 重跑跳 Phase 1 + 已完成的流,只补缺失流。粒度=每流(被中断的单条流整条重写,不做流内续传)。spec `docs/specs/export.md` §Phase3/Step0.5;+4 RED→GREEN(test_export 续传/时序 3 + test_nwb_writer `_append_one_stream` 1;2 个 fresh-path 测试补 `_nwb_phase1_done=False`)（2026-07-01） |
| 修复 E-rag | export 多探针 waveform 列 ragged 崩溃 + 失败 traceback 不进日志 | ✅ | 生产 export 崩 `setting an array element with a sequence ... inhomogeneous shape (1019, 88)+...`。根因:preprocess 按数据**移除**每探针不同数量的坏道,故各探针 analyzer 模板宽度不同;`nwb_writer._write_units` 把所有探针 unit 写进同一张 units 表,`waveform_mean`/`waveform_std` 列跨探针 ragged((n_units, n_samples=88, 通道数不齐)),HDMF 写盘时 `np.array` 报错。单探针不触发,双探针坏道数不同必触发。修复:`nwb_writer` 把模板 pad 到 `probe.n_channels`(满通道,NP=384)NaN 填充,列跨探针对齐为矩形(假设同型探针)。**观测性 bug**:`BaseStage._write_failed_checkpoint` 只写 failed checkpoint、不进结构化日志 → 报错只弹 UI;改为同时 `logger.error("stage_failed", traceback=...)` 把完整 traceback 写进 JSON Lines(structlog 链无 format_exc_info,故显式格式化字符串)。+2 RED→GREEN(test_nwb_writer 双探针不同通道数 reproduce / test_base traceback 日志)（2026-06-29） |
| 磁盘 D1 | 预处理 Zarr int16 落盘 + postprocess 后用完即删 | ✅ | 生产撞 `[Errno 28] No space left`(双探针 raw 701G、float32 zarr 1.2T)。根因:开 DREDge 时 `correct_motion` 插值使链变 float32,落盘 2×。源码+实测坐实 int16 安全:`astype` 四舍五入(astype.py round=None→整数 dtype 默认 round)且 `copy_metadata` 保留 `gain_to_uV`,往返误差仅 ½ ADC count(~0.68µV RMS,本底之下);KS4 重白化无感;NWB raw 读原始 .ap.bin 不受影响。`preprocess.save_dtype`(默认 int16,1.2T→~600G)+ `delete_zarr_after_postprocess`(默认 true,runner 在 postprocess 后删每根已完成 probe 的 zarr 给 export 腾盘,resume-safe)。诚实记录:synchronize 是 session 屏障夹在 sort↔postprocess 间,无法把 sort 峰值压到单根,峰值靠 int16 减半。spec `docs/specs/preprocess.md`;+8 RED→GREEN(config_dataclasses +2 / config_load +2 / preprocess +2 / runner +3,UI harness 2 字段映射 None)(2026-06-28) |
| UI S9 | 资源调优 + DREDge advisor 旋钮上 UI | ✅ | pipeline_form Resources/Motion 两卡新增 markdown 分隔的 "Advanced" 子组：资源利用 10 旋钮 + DREDge advisor 10 旋钮（`bytes_per_entry`/`n_matrices` 纯校准常量仍仅 YAML，harness 映射 None）。`n_windows`（int\|None）用 enable-checkbox+disabled-watcher 可空模式。widget 默认全部绑 `_DEFAULTS.<path>` 保证 default_roundtrip 精确。spec `docs/specs/ui.md` §3.5 同步；+7 测试（覆盖 harness 自动校验全字段映射+widget 存在+默认回环）（2026-06-27） |
| SID S1 | SessionID 基础设施（core/session + io/spikeglx） | ✅ | `SessionID` frozen dataclass + `canonical()`/`derive_region()`；`ProbeInfo.target_area` required；`SessionManager.create/from_data_dir` 加 `experiment`/`probe_plan`/`date` kwargs + 校验；`SpikeGLXLoader.read_recording_date()` 解析 YYMMDD（+32 tests） |
| SID S1 contract harness | `tests/test_harness/test_sessionid_contract.py` | ✅ | 18 end-to-end 契约测试 <2s：SessionID invariants / create 校验 / save-load 持久化 / read_recording_date → canonical() 贯通（总 1220 passed） |
| SID S2 | Discover/Export/NWBWriter 贯通 canonical() | ✅ | DiscoverStage 注入 `probe.target_area` + `ProbeDeclarationMismatchError`；ExportStage 输出 `{canonical}.nwb` + target_area pre-flight；NWBWriter `session_id`/`session_description` = canonical（+7 tests；总 1233 passed） |
| SID S2 contract harness | `TestDiscoverInjectionContract` + `TestNWBCanonicalContract` | ✅ | 5 new end-to-end 契约测试（累计 23 tests <2s）：probe_plan→target_area 注入 / 声明-disk mismatch / output path / NWBFile.session_id / empty target_area 拒写 |
| SID S3 | UI 层贯通 canonical（state + form + probe editor + run gate + loader） | ✅ | `AppState` 新增 `experiment`/`recording_date`/`probe_plan` params + `session_id` computed property；`SessionForm` 加 experiment + recording_date 输入 + Detect Date 按钮（扫描 `*.ap.meta`）；新 `ProbeRegionEditor` 组件管理 `probe_plan` 行增删；`RunPanel` 执行前校验六个字段齐全；`SessionLoader` 从 session.json 恢复 experiment/date/probe_plan + legacy 警告；`app.py` mount ProbeRegionEditor（+31 tests） |
| SID S3 contract harness | `TestUIContract` 扩展 | ✅ | 4 new end-to-end 契约测试（累计 27 tests <3s）：AppState.session_id=canonical / 任一字段空→None / SessionLoader 恢复 NWB 字段 / RunPanel 缺字段阻止执行 |
| SID S3 UI polish | 删 probe 的 Bokeh warning + target_area 宽度 + merge 默认对齐 | ✅ | `ProbeRegionEditor` 改增量 add/remove 避免 "reference already known"；area 输入框定宽 140px；`StageSelector` merge 默认 `value=False` 对齐 `MergeConfig.enabled=False`，勾 merge 但参数关时给警告（+2 tests） |
| Plots S1 | Nature 风格 `plots/` 子包 + 5 stage 接入 + figs_viewer 分组 | ✅ | `plots/{style,sync,curate,postprocess,preprocess}.py` 覆盖 MATLAB 诊断图 #1-#13 + 单元波形/location/raster/PSTH + 坏道/CMR traces/motion；`figs_viewer` 按 stage 折叠显示；所有 stage 绘图失败仅 warning 不阻塞 checkpoint（+54 tests，1425 passed，2026-04-18） |
| Output dirs S1 | 按 pipeline 生成顺序给输出目录加数字前缀 | ✅ | `preprocessed→01_preprocessed / sorted→02_sorted / sorter_output→02_sorter_output_KS4 / merged→03_merged / sync→04_sync / curated→05_curated / postprocessed→06_postprocessed / derivatives→07_derivatives`；同步更新 stages/io/harness/validators/ui/tests + docs/specs；不保留旧路径 fallback（全回归 1425 passed，2026-04-18） |
| Output dirs S1 | 按 pipeline 生成顺序给输出目录加数字前缀 | ✅ | `preprocessed→01_preprocessed / sorted→02_sorted / sorter_output→02_sorter_output_KS4 / merged→03_merged / sync→04_sync / curated→05_curated / postprocessed→06_postprocessed / export→07_export`；同步更新 stages/io/harness/validators/ui/tests + docs/specs；不保留旧路径 fallback（全回归 1425 passed，2026-04-18） |
| Task 2 PR1 | NWB 回炉处理最小闭环 | ✅ | `docs/specs/{nwb_reader,nwb_rerun}.md` + `io/nwb_reader.py` + `pipelines/nwb_rerun.py` + CLI `rerun-from-nwb`；copy-on-write `rewrite-units`，不原地修改输入 NWB，不允许改 `spike_times`（18 tests，2026-05-27） |
| Task 2 PR2 | NWB units → per-probe Sorting adapter | ✅ | `NWBLoader.load_sortings()` 将 `/units` 按 `probe_id` 拆为 `spikeinterface.core.NumpySorting`，保留 unit metadata properties，可从 AP acquisition rate 推断 sampling frequency（+5 tests，2026-05-27） |
| Task 2 PR3 | NWB 轻量 postprocess rerun | ✅ | `rerun_from_nwb(..., mode="postprocess")` 从 `/units` + trials 重算 `slay_score/is_visual`，按 `stim_onset_imec_{probe_id}` 处理多 probe 时钟，copy-on-write 写回新 NWB；CLI 支持无 `--unit-updates` 的 postprocess rerun（+4 tests，2026-05-27） |
| Task 2 PR4 | NWB raw Recording adapter | ✅ | `NWBLoader.load_recordings()` 将 acquisition `ElectricalSeriesAP/LF_{probe_id}` 转成 SpikeInterface Recording bundle，`require_capabilities("raw")` 验证 AP streams 可懒加载，为后续 full preprocess/sort orchestration 打通输入层（+3 tests，2026-05-27） |
| Task 2 PR5 | NWB raw preprocess/sort rerun | ✅ | `rerun_from_nwb(..., mode="raw")` 从 NWB AP `ElectricalSeries` 懒加载 Recording，运行 preprocess sequence + SpikeInterface sorter，并将 sorter 输出重写回 copied NWB `/units`；CLI `--mode raw` 接入 pipeline（+2 tests，2026-05-27） |

#### 修复与改进（M2 期间）

| Commit | 说明 |
|--------|------|
| `fix(sync)` | 移除废案 `imec_sync_code` 字段，清理同步接口 |
| `fix(config)` | `SorterParams.nblocks` 默认值 15→0，避免与 DREDge 运动校正的双重漂移校正冲突 |
| `fix(bhv_nidq_align)` | stim_onset 改为直接对齐到 NIDQ rising edge（MATLAB-style `bitand(CodeVal,64)`），替换旧 `trial_anchor + bhv_offset` 公式。旧公式因 BHV 实际 trial-zero 与 NIDQ trial_start rising 不同步，累积 ±120ms per-trial drift，导致光电 flag=3 的无效校准。新增 `stim_onset_bit` / `stim_count_tolerance` 配置项 + auto-detect 回退到旧公式。41 tests（含 9 new RED→GREEN） |
| `fix(export)` | Phase 2.5 spec drift 修复：`io/derivatives.py` 已按 spec 实现但 `ExportStage._export_phase2` 仍写旧版 `07_export/{trials.csv,units.csv,raster_*.h5}` 且从未调 `derivatives` 模块。重写 `_export_phase2` 按 `docs/specs/derivatives.md` §5：读刚写的 NWB → `07_derivatives/{TrialRaster,UnitProp,TrialRecord}_{session_id}.{h5,csv}`；新增 `ExportConfig/DerivativesConfig`（PipelineConfig +1 字段，共 8）+ `pipeline.yaml` 新增 `export.derivatives` 块；PipelineForm 新增 5 个 widgets（Phase 2.5 Card）；旧 `07_export/` 路径严格删光不保留 fallback；+8 新测试 RED→GREEN（TestPhase25Derivatives），全回归 1462 passed（2026-04-18） |
| `fix(curate)` | Bombcell 始终 fallback 根因修复 + 3 张官方诊断图落盘。根因两条：(a) `metric_names` 缺 `amplitude_median` / `num_spikes` / `rp_violation` / `drift`，bombcell 读不到所需列；(b) SI ≥0.104 在 `bombcell_label_units` 内部把 `label` 改名为 `bombcell_label`，旧代码仍读 `label` 静默 KeyError 退回 manual。`_curate_probe` 在 `use_bombcell=True` 下新增 `spike_locations`（monopolar triangulation，分钟级但 `drift` 必需）+ `template_metrics` + 9 项 metric_names；`_classify_bombcell` 改读 `bombcell_label` 列并返回 `(unittype_map, labels_df, thresholds)` 三元组。新增 `src/pynpxpipe/plots/bombcell.py::emit_bombcell_plots` 包装 `sw.plot_unit_labels` / `plot_metric_histograms` / `plot_bombcell_labels_upset`，输出到 `05_curated/{probe_id}/figures/`；bombcell 失败时降级只画 `bombcell_unit_labels.png`（用 manual `unittype_map` 反向映射到 bombcell 词表）。`docs/specs/curate.md` §1/§3/§4/§6/§7 同步更新。+12 新测试 RED→GREEN（test_curate.py Group G/H/I + test_plots/test_bombcell.py 4 tests），全回归 1473 passed（2026-04-18） |
| `feat(resources/runner)` | **motion_memory_advisor**：DREDge 长录制 OOM 预测 + bin_s 自适应。源码实证 DREDge AP 内存峰值是 `xcorr_windows` 的 `(B,T,T)` float32 互相关矩阵（`dredge.py:1014`），∝ `B×(时长/bin_s)²` 且数据无关。`core/resources.py` 新增纯解析 `recommend_motion_strategy()` + `MotionStrategy`：在内存安全上限内解出最高精度（最小）`bin_s`，超 `bin_s_max` 才退 KS4 `nblocks`；`runner._resolve_motion_strategy()`（discover 后调用）按 `fileTimeSecs` 取最长 probe 时长 + psutil 可用 RAM 决策，一致地写回 `bin_s` 或 `method=None`+`nblocks`；`preprocess` 透传 `bin_s` 给 `correct_motion(estimate_motion_kwargs=...)`；`MotionCorrectionConfig` +12 字段（`auto_strategy` 仓库默认开）。spec `docs/specs/motion_memory_advisor.md`；+15 RED→GREEN（test_resources +7 / test_runner +5 / test_preprocess +2 / harness +1）（2026-06-26） |
| `feat(resources)` | **资源利用激进化（打满核+GPU，RAM 留闸）**：旧推算在 128G 机器上只用 ~16% RAM、CPU 卡 16 线程，根因是三个硬上限（n_jobs `min(…,16)`、max_workers `min(…,4)`、保留 2 核），而非 0.6/0.4 等比例因子。关键认知：AP 预处理是 CPU/IO-bound，每 worker 只持一个 chunk（5s≈1.15GB），RAM 天然跑不满——真正杠杆是**核数 + GPU batch_size**，RAM 推到 90% 既做不到又是唯一崩溃向量（`psutil.available` 含可回收缓存、波动）。新增 `ResourceTuning` dataclass（10 个旋钮）由 `recommend()` 接收、`runner` 从 `config.resources` 同名字段构造、`ResourcesConfig`+10 字段映射到 `pipeline.yaml`（零硬编码）：保留核 2→1、n_jobs 上限 16→64、max_workers 上限 4→8、RAM 因子 0.60→0.85 且新增 `ram_reserve_gb=10` 绝对头寸双闸、VRAM 因子 0.80→0.90。spec `docs/specs/resources.md` §7.0 + §7.1-7.4 重写；+11 RED→GREEN（test_resources +8 / test_runner +1 / test_config_dataclasses +1 / test_config_load +2，UI 覆盖 harness +10 字段映射 None）（2026-06-27） |

### 轨道 B — Pure-Python BHV2（feature 分支）

| 阶段 | 任务 | 状态 | 说明 |
|------|------|------|------|
| B1 | 逆向工程 | ✅ | `bhv2_binary_format.md` ✅ + `bhv2_matlab_analysis.md` ✅ + `export_ground_truth.m` ✅ + JSON fixtures ✅ |
| B2 | 解析器实现 | ✅ | B2.1 bhv2_reader.py ✅ (27 tests) — B2.2+B2.3 BHV2Parser 重写 ✅ — B2.4 ground-truth 验证 ✅ — B2.5 回归 ✅ — 合计 52 tests (test_bhv.py) |
| B3 | 集成与合并 | ✅ | B3.1 matlabengine 已在 optional ✅ — B3.2 BHV2_BACKEND 兼容性开关 ✅ — B3.3 merged to master ✅ |

### 已知技术债

| 文件 | 问题 | 优先级 |
|------|------|--------|
| `docs/specs/curate.md` 步骤 2-3 | 写 `si.load_extractor`，但 SI >= 0.104 已移除该 API，实际实现用 `si.load` | 低 |
| `docs/specs/nwb_writer.md` 步骤 add_trials | 写 `TimeIntervals + add_time_intervals`，但 pynwb 2.8 此路径不设置 `nwbfile.trials`，实现改用 `add_trial_column + add_trial` | 低 |

---

**当前全量测试数（2026-07-01 export raw 流自愈 self-heal）**：1630 passed / 0 failed / 46 skipped（`uv run pytest`）。注：2026-04-18 记录的 "8 pre-existing failed" 在 HEAD（含 687f2a3）已全绿，此为重新核实后的基线。

**Phase NWB 完成状态（2026-04-18 核查）**：E1.1 / E2.1-E2.3 / E3.1-E3.3 全部代码实现并测试通过；harness 契约测试 7/7 绿（`test_nwb_clock_contract` / `test_nidq_export_contract` / `test_sync_tables_contract` / `test_export_safety_contract` / `test_verify_safe_contract` / `test_provenance_contract`），相关单元测试 145/145 绿。

**Phase 3 UX（2026-04-18）**：E2.1 `wait_for_raw` 默认改为 `True`（前台阻塞，daemon 路径须显式 opt-in）；`NWBWriter.append_raw_data` 新增 `progress_callback` 参数 + `_Phase3Reporter`（write 段 [0, 0.7]，verify 段 [0.7, 1.0]，含单调性保护）；`ExportStage._export_phase3_background` 将进度映射到 overall stage [0.85, 0.99]；CLI `run` 命令按 `stage:msg` 前缀渲染 per-stage tqdm 进度条并打印 ✅ safe-to-exit；UI `AppState.safe_to_exit` + `RunPanel` 完成后置 True + `app.py` 成功横幅。相关单测 +11（`test_nwb_writer.py` / `test_export.py` / `test_run_panel.py` / `test_cli/test_main.py`），全绿。

---

## M2 Phase NWB — Completeness & Shareability（2026-04-17 立项）

**动因**：2026-04-17 评审发现当前 NWB 存在三类缺陷，阻碍对外共享与原始 `.bin` 的安全删除：
1. **数据正确性**：`add_trials` 用 NIDQ 时钟，与 `units.spike_times` (IMEC) 不同；NIDQ 原始通道（photodiode / event bits）未入 NWB；`sync_tables.json` 未入 NWB，无从反算时钟互转
2. **删 bin 可靠性闭环缺失**：Phase 3 是 daemon 后台线程，无验证、无 checkpoint 标记、`gain_to_uV` 缺失时静默 fallback
3. **Provenance 不完整**：pipeline config、merge_log、condition→stim_name 映射均未入 NWB

**流程纪律（每个任务必须依次满足）**：
1. **Spec-first**：先改 `docs/specs/*.md`，用户确认后开工
2. **TDD-RED**：先写 unit tests + harness 契约测试，确认全部失败（功能缺失，非语法错误）
3. **TDD-GREEN**：写最小实现通过所有测试
4. **Harness 必过**：新增 `tests/test_harness/*` 契约测试全绿且 <5s/文件
5. **基线不退化**：`uv run pytest --tb=no -q` 保持 ≥1266 passed / 8 pre-existing failed；`ruff check` 保持 13 errors 基线
6. **Spec MATLAB 对照**：如有改动同步更新

缺任一条 → 状态停留在 🚧，不得标 ✅。

### 轨道 E1 — 数据正确性（阻断共享，最高优先级）

| ID | 任务 | Harness 契约测试 | TDD 单测（最少条数） | 状态 |
|----|------|-----------------|--------------------|------|
| E1.1 | `NWBWriter.add_trials` 改用 IMEC 时钟：`start_time` / `stop_time` / `stim_onset_time` 取 `stim_onset_imec_s` 中的 **reference probe `imec0`**（模块常量 `_REFERENCE_PROBE = "imec0"`，不配置化）；多 probe 额外写 per-probe 列 `stim_onset_imec_{probe_id}`；保留 `stim_onset_nidq_s` 为诊断列 | `tests/test_harness/test_nwb_clock_contract.py`：合成 2-probe session，已知 `(a,b)` → 全流程导出 → NWB 回读断言 `units.spike_times` 与 `trials.start_time` 在同一 IMEC 时钟（用 (a,b) 正向/反向映射互验） | `test_io/test_nwb_writer.py` **+5**：primary_is_imec0 / per_probe_columns / nidq_kept_as_diagnostic / raises_if_imec_column_missing / start_stop_same_clock | ✅ |
| E1.2 | `append_raw_data` 新增 NIDQ 流：**单个 `acquisition/NIDQ_raw`**（`pynwb.TimeSeries`），完整保留 int16 原始数组（所有模拟 + 数字通道，不拆分、不解码）；`conversion = niAiRangeMax / 32768.0`；`unit = "V"`（SpikeGLX 标注模拟通道物理电压，数字通道读者自行按 description 解码）；`description` 内嵌 `niAiRangeMax` / `niMNGain` / `niMAGain` / `snsMnMaXaDw` 通道切片 / 数字 bit 定义（从 `nidq.meta` 抄过来）。无 nidq.bin 时 warning 日志 skip，不 raise | `tests/test_harness/test_nidq_export_contract.py`：合成 1s 小 nidq.bin（含模拟 + 数字列） → `append_raw_data` → NWB 回读 → `data.shape`/`dtype=int16`/`conversion`/`rate`/`starting_time` 全部匹配；`description` 含 `niAiRangeMax` / 通道切片 / bit 定义字段；二次调用幂等；源 int16 全数组 `np.array_equal` 与 NWB 回读一致 | `test_io/test_nwb_writer.py` **+6**：single_timeseries_written / int16_preserved / conversion_from_meta / description_contains_channel_map / skip_when_nidq_missing / idempotent | ✅ |
| E1.3 | 新增 `NWBWriter.add_sync_tables(nwbfile, sync_dir, behavior_events=...)`：聚合 `sync_dir/*_imec_nidq.json`（per-probe 线性拟合）+ behavior_events 的 `pd_onset_nidq_s` / `ec_onset_nidq_s` / event-code 三元组，序列化为 JSON 写入 `nwbfile.scratch["sync_tables"]`；`export.py` Phase 1 `add_trials` 之后调用之；缺源文件 → `{"_missing": true}` 哨兵 + WARNING，不 raise；幂等 | `tests/test_harness/test_sync_tables_contract.py::test_roundtrip_reconstructs_imec_nidq`：写盘→重开→JSON 解码；断言 `imec_nidq.imec0.{a,b}` + 3 条 photodiode 条目 latency 正确 + event_codes stim_onset 保留 + 用时 < 3s | `test_io/test_nwb_writer.py` **+4**（TestAddSyncTables: single_probe / two_probes / photodiode_from_events / missing_files_marked）、`test_stages/test_export.py` **+2**（TestSyncTablesWiring: phase1_calls_add_sync_tables / phase1_survives_missing_sync_dir） | ✅ |

### 轨道 E2 — 删 .bin 前置条件（可靠性闭环）

| ID | 任务 | Harness 契约测试 | TDD 单测（最少条数） | 状态 |
|----|------|-----------------|--------------------|------|
| E2.1 | `ExportStage` 新增 `wait_for_raw: bool = False` 参数；True 时 Phase 3 前台阻塞；`append_raw_data` 返回前调用 `verify_nwb()` + **对每 probe 的 AP/LF/NIDQ 全文件 chunk-wise bit-exact 扫描**（`verify_policy: Literal["full", "sample"] = "full"` 可配，默认 `"full"`；"sample" 模式为性能逃生门：仅扫首/中/尾各 1 chunk）；checkpoint 新字段 `raw_data_verified_at: str \| None` + `verify_policy: str` | `tests/test_harness/test_export_safety_contract.py`：合成小 session（1s 数据） → `export(wait_for_raw=True)` → checkpoint.`raw_data_verified_at` 非空 + `verify_policy == "full"` + NWB 可读 + 全扫通过；篡改 NWB 某中段 chunk → 重跑 verify raise `ExportError` 并指出第一个不匹配的 `(probe, stream, chunk_idx)`；`verify_policy="sample"` 仅扫 3 个 chunk，中段篡改可能漏检（文档化此限制） | `test_stages/test_export.py` **+6**：wait_flag_blocks / wait_flag_nonblock_default / verify_full_reads_all_chunks / verify_sample_reads_three_chunks / bit_exact_mismatch_raises_with_location / verified_field_written_with_policy | ✅ |
| E2.2 | `_append_recording_stream` 中 `gain_to_uV` 缺失的 `conversion=1.0` 静默 fallback 改 raise `ExportError(f"{probe_id} {stream_type} missing gain_to_uV")` | 无独立 harness（由 E2.1 覆盖异常分支） | `test_io/test_nwb_writer.py` **+2**：raises_when_gain_missing / raise_message_contains_probe_id | ✅ |
| E2.3 | 新 CLI `pynpx verify-safe-to-delete {session_dir}`：检查 `checkpoints/export.json` 的 `raw_data_verified_at` 非空 + NWB 存在 + NWB `NWBHDF5IO` 可打开。通过 → exit 0 + 打印每个 `.bin` 路径（提示可删）；失败 → exit 非 0 + 打印原因 | `tests/test_harness/test_verify_safe_contract.py`：三支路——全齐全 exit 0 / 缺 `raw_data_verified_at` exit 非 0 / NWB 损坏 exit 非 0 | `test_cli/test_main.py` **+4**：exits_zero_when_safe / exits_nonzero_missing_verified / exits_nonzero_missing_nwb / prints_bin_paths_on_success | ✅ |

### 轨道 E3 — Provenance 与合并痕迹（共享完备性）

| ID | 任务 | Harness 契约测试 | TDD 单测（最少条数） | 状态 |
|----|------|-----------------|--------------------|------|
| E3.1 | 新增 `NWBWriter.add_pipeline_metadata(config: PipelineConfig)`：把 `session.config` 用 `dataclasses.asdict` + `json.dumps` 序列化后写入 `nwbfile.scratch["pipeline_config"]` | `tests/test_harness/test_provenance_contract.py::test_pipeline_config_roundtrip`：构造完整 `PipelineConfig` → NWB → 反序列化 dict == `asdict(config)` | `test_io/test_nwb_writer.py` **+3**：roundtrip_full_config / scratch_key_name / raises_if_not_created | ✅ |
| E3.2 | `NWBWriter.add_probe_data` 增加 `merged_from: list[int]` unit 列（空 list 为默认）；值从 `merged/{probe_id}/merge_log.json` 读取 `new_id → merged_ids` 映射；同时把原始日志存 `scratch/merge_log_{probe_id}`；merge 未运行时列全为 `[]` | `tests/test_harness/test_provenance_contract.py::test_merged_from_populated`：fake `merge_log.json` 含 `{merges: [{new_id: 5, merged_ids: [5,7,9]}]}` → export → `units` 中 `ks_id=5` 行的 `merged_from == [5,7,9]` | `test_io/test_nwb_writer.py` **+4**：column_always_present / populated_from_log / empty_when_merge_off / scratch_log_preserved | ✅ |
| E3.3 | `NWBWriter.add_trials` 补 `stim_name` 列（从 `BHV2Parser` condition metadata 映射 `condition_id → 图片/文件名`）；映射缺失 fallback 为空串 | `tests/test_harness/test_provenance_contract.py::test_stim_name_present`：fake BHV parser 返回 `{1: "face_01.png", 2: "obj_03.png"}` → export → trials 表含 `stim_name`，condition_id=1 行值 == `"face_01.png"` | `test_io/test_nwb_writer.py` **+3**：stim_name_column / mapping_resolved / fallback_empty_on_unknown | ✅ |

### 🔒 已锁定的设计决策（2026-04-17 用户确认）

| 决策点 | 结论 | 归属任务 |
|--------|------|---------|
| Trials 主时钟 reference probe | **硬编码 `imec0`**（模块常量 `_REFERENCE_PROBE`，不经 config） | E1.1 |
| NIDQ 入 NWB 的形式 | **最贴原始**：单个 `TimeSeries("NIDQ_raw", ...)`，int16 原数组，不拆 bit、不解码、不分流；`conversion=niAiRangeMax/32768`；`description` 抄 `nidq.meta` 关键字段 + bit 定义 | E1.2 |
| Bit-exact 验证严格度 | **默认全文件扫描**（`verify_policy="full"`）；"sample" 仅作逃生门。接受 Phase 3 耗时翻倍代价 | E2.1 |

### 🧭 Subagent 并行分发规划

所有 wave 内任务各自独立，但同 wave 多个任务会同时编辑 `nwb_writer.py`。**必须用 `isolation: "worktree"` 隔离**，主 agent 收到三份 diff 后统一合并、解决 conflict、跑全量回归后单次提交。

| Wave | 任务 | 执行模式 | 依赖 |
|------|------|---------|------|
| **Wave 1** | E1.1 / E1.2 / E1.3 | **并行 3 路 subagent（worktree）** | 无前置依赖 |
| **Wave 2** | E2.1 → E2.2 → E2.3 | **串行**（同一 subagent 或主 agent） | E2.3 读 E2.1 引入的 checkpoint 字段 |
| **Wave 3** | E3.1 / E3.2 / E3.3 | **并行 3 路 subagent（worktree）** | Wave 1 的 `add_sync_tables` 模式已确立 scratch 写法，E3.1/E3.2 可复用 |

**Subagent prompt 模板（每个任务必含）**：
1. 目标 ID 与 spec 路径（先读，再改）
2. Harness 契约文件名 + 至少 N 条 TDD 单测要求
3. 基线数字：≥1266 passed / 13 ruff errors
4. 禁止修改清单：其他 wave 任务的 scope
5. 返回格式：改动文件列表 + 新增测试数 + 最终 pytest/ruff 输出摘要

### Harness 时效预算

| Harness 文件 | 归属 | 最大时长 |
|-------------|------|---------|
| `test_nwb_clock_contract.py` | E1.1 | 3s |
| `test_nidq_export_contract.py` | E1.2 | 3s |
| `test_sync_tables_contract.py` | E1.3 | 2s |
| `test_export_safety_contract.py` | E2.1 | 5s |
| `test_verify_safe_contract.py` | E2.3 | 3s |
| `test_provenance_contract.py` | E3.1+E3.2+E3.3 合并 | 5s |

Phase NWB 完成后 harness 累计预期：**27 → ~36 tests，总执行时间 < 25s**。
