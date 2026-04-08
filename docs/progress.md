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
                  ✅          ✅                 ├──→ sync_plots
                      photodiode_calibrate ─────┘        🟡
                              ✅
                 nwb_writer
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

M1 遗留项（不阻塞 M2）：`io/sync_plots.py` 未实现（优先级低）；集成验证待做。

---

## M2 进度总览

目标：Panel Web UI + Pure-Python BHV2 | 详细规划见 `docs/ROADMAP.md`

### 轨道 A — Panel Web UI（主分支）

| 阶段 | 任务 | 状态 | 说明 |
|------|------|------|------|
| A1 | 基础设施搭建 | ✅ | panel 依赖 + ui/__init__.py + state.py + app.py spike（18 tests） |
| A2 | 配置与元信息表单 | ✅ | session_form / subject_form / pipeline_form / sorting_form / stage_selector（30 tests） |
| A3 | 执行与进度追踪 | ✅ | ProgressBridge stage_statuses + run_panel + progress_view + log_viewer（28 tests） |
| A4 | 结果查看与恢复 | ⬜ | status 面板 + reset-stage + 断点续跑 |
| A5 | 整合与打磨 | ⬜ | 布局 + 错误处理 + 入口命令 + 测试 |

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
