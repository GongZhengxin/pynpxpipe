# Baseline — SessionID 重构前测试状态

**快照时间**：2026-04-17
**命令**：`uv run pytest --tb=no -q`
**总数**：1170 passed, 8 failed, 38 warnings in 26.20s

## 已知失败（pre-existing，非本次重构引入）

| # | 测试 | 根因 |
|---|------|------|
| 1 | `tests/test_core/test_config_integration.py::test_load_real_subject_config[MonkeyTemplate]` | `monkeys/MonkeyTemplate.yaml` 的 `age: "P[x]Y"` 是模板占位符，`load_subject_config` 的 ISO 8601 正则 `^P\d+[YMD]$` 判其非法。不应把 template 当真实 config 加载 |
| 2 | `tests/test_stages/test_runner.py::TestBasicExecution::test_run_executes_all_stages_in_order` | `mock.patch("pynpxpipe.pipelines.runner.DiscoverStage")` 失败：符号已移出 `runner.py`，测试未同步更新 |
| 3 | `...TestBasicExecution::test_run_subset_of_stages` | 同上 |
| 4 | `...TestBasicExecution::test_run_subset_maintains_order` | 同上 |
| 5 | `...TestBasicExecution::test_run_stage_by_name` | 同上 |
| 6 | `...TestBasicExecution::test_completed_stage_checkpoint_handled_by_stage` | 同上 |
| 7 | `...TestFailFast::test_stage_error_stops_pipeline` | 同上 |
| 8 | `...TestFailFast::test_non_stage_error_propagates` | 同上 |

## 回归判定规则

SessionID 重构（S1 / S2 / S3）完成后，运行 `uv run pytest --tb=no -q`：

- **通过**：`X failed, Y passed`，`X ≤ 8` 且失败列表与上表**完全一致**
- **失败**：任一新名字出现在失败列表中

## 快速回归命令

改动影响范围集中在 `core/session.py` / `io/spikeglx.py` / `stages/discover.py` / `stages/export.py` / `io/nwb_writer.py` / `ui/`，以下命令 < 10s 跑完，用于每次 commit 前的快速自检：

```bash
uv run pytest \
  tests/test_core/test_session.py \
  tests/test_io/test_spikeglx.py \
  tests/test_io/test_nwb_writer.py \
  tests/test_stages/test_discover.py \
  tests/test_stages/test_export.py \
  tests/test_ui/test_state.py \
  tests/test_ui/test_session_form.py \
  tests/test_ui/test_session_loader.py \
  tests/test_ui/test_run_panel.py \
  --tb=short -q
```

## 契约 harness（S1 完成后建立）

`tests/test_harness/test_sessionid_contract.py`：end-to-end 契约测试，<30s，覆盖
- `SessionManager.create(..., experiment=, probe_plan=, date=)` → `session.session_id.canonical()` 格式正确
- `SpikeGLXLoader.read_recording_date()` 从真实 `.meta` 抽 YYMMDD
- `ProbeInfo.target_area` 在 discover 后已填充
- NWB 文件名等于 `canonical()`
- NWB 的 `session_id` 元数据字段等于 `canonical()`

每个 session 结尾跑一次 harness + 一次完整 pytest。
