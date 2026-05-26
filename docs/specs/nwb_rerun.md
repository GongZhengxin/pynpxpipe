# Spec: pipelines/nwb_rerun.py

## 1. 目标

`pipelines/nwb_rerun.py` 编排任务 2 的 NWB 回炉处理，把已导出的 NWB 文件作为输入，按用户选择的粒度重新生成或替换下游结果。

任务 2 总目标包含三种粒度：

| 模式 | 用户需求 | 输入 | 起点 | 输出 |
|------|----------|------|------|------|
| A. raw rerun | 从原始数据开始的 filtering + sorting | NWB acquisition 中的 raw AP/LF/NIDQ | preprocess | 新 NWB |
| B. postprocess rerun | 从 sorting 输出开始的 metric computation / curation / merging | NWB `/units` + trials/provenance，必要时 raw AP | merge/curate/postprocess | 新 NWB |
| C. rewrite units | 对 `NWB.Units` 的覆盖重写 | NWB `/units` + 用户提供的 unit 更新表 | export-lite | 新 NWB |

首个实现范围（Task 2 PR1）只做 C 的最小闭环：

```text
input.nwb + units update table/rules
  -> validate input
  -> copy original NWB to rerun output
  -> replace/rewrite /units in the copied NWB
  -> validate copied NWB opens
  -> write rerun checkpoint/report
```

A/B 在 spec 中保留设计边界，但不在 PR1 实现。

Task 2 PR3（本地后续提交）实现 B 的轻量入口：

```text
input.nwb (/units + trials)
  -> validate input
  -> recompute per-unit slay_score / is_visual from spike_times and stimulus onsets
  -> copy original NWB to rerun output
  -> replace/rewrite /units in the copied NWB
  -> validate copied NWB opens
  -> write rerun checkpoint/report
```

该入口只依赖 NWB `/units` 与 `trials`，不要求 raw AP recording，因此不计算 waveform/template/unit_locations/Bombcell 等需要 `SortingAnalyzer` 或原始 recording 的指标。full postprocess rerun 与 raw rerun 仍保留为后续工作。

## 2. 关键设计决策

### 2.1 输出策略：copy-on-write

推荐并作为 PR1 默认：**不原地修改输入 NWB**，始终写出新的 rerun NWB。

默认路径：

```text
{output_dir}/
  nwb_rerun/
    {input_stem}_rerun_v001.nwb
    nwb_rerun_report.json
    checkpoints/
      nwb_rerun.json
```

理由：

- DANDI/共享后的 NWB 不应被静默 in-place 改写。
- 原文件可作为审计和回滚基线。
- 用户可以多次尝试 curation/merge 规则，保留版本。
- 任务 3 的 merge rollback 和任务 5 的手动 curation 更容易接入。

保留未来选项：

| 策略 | 是否 PR1 实现 | 说明 |
|------|---------------|------|
| `copy` | 是 | 复制原 NWB，改副本 |
| `in-place` | 否 | 未来只允许显式 `--in-place --yes-i-know` |
| `new-from-scratch` | 否 | 未来用 `NWBWriter` 从中间对象重建完整 NWB |

### 2.2 checkpoint 策略

NWB 输入模式不复用常规 pipeline 的 `{output_dir}/checkpoints/{stage}.json`，避免和 SpikeGLX 直跑 session 混淆。

PR1 使用独立目录：

```text
{output_dir}/nwb_rerun/checkpoints/nwb_rerun.json
```

checkpoint payload：

```json
{
  "status": "completed",
  "mode": "rewrite-units",
  "input_nwb": ".../input.nwb",
  "output_nwb": ".../nwb_rerun/input_rerun_v001.nwb",
  "n_units_before": 142,
  "n_units_after": 118,
  "unit_update_source": ".../updates.csv",
  "completed_at": "2026-05-27T..."
}
```

失败时写：

```json
{
  "status": "failed",
  "mode": "rewrite-units",
  "input_nwb": ".../input.nwb",
  "error": "...",
  "failed_at": "..."
}
```

### 2.3 Units rewrite 语义

PR1 的 rewrite 是"覆盖副本里的 `/units` 内容"，不是修改原文件。

推荐输入格式：CSV/Parquet/DataFrame，按 `unit_id` 匹配原 units。

支持两类更新：

1. **列更新**：例如修改 `unittype_string`、`is_visual`、`slay_score`、`merged_from`。
2. **行过滤/保留**：例如只保留 `keep == true` 的 unit。

PR1 不允许用户改 `spike_times`。原因：

- spike_times 是数值核心输出，任意改写需要更强 provenance 与一致性校验。
- 任务 3/5 的近期需求主要是 curation label、merge provenance、unit inclusion/exclusion。

未来可以新增显式 `allow_spike_time_rewrite=True`，并要求 `<0.1 ms` 对比报告。

## 3. 输入

### `rerun_from_nwb`

建议 API：

```python
def rerun_from_nwb(
    nwb_path: Path,
    output_dir: Path,
    *,
    mode: Literal["rewrite-units", "postprocess", "raw"] = "rewrite-units",
    unit_updates: Path | pd.DataFrame | None = None,
    version: str | None = None,
    overwrite: bool = False,
) -> NWBRerunResult:
    ...
```

### CLI

新增命令：

```bash
pynpxpipe rerun-from-nwb INPUT_NWB --mode rewrite-units --output-dir OUTPUT_DIR --unit-updates updates.csv
```

PR1 CLI 参数：

| 参数 | 类型 | 说明 |
|------|------|------|
| `INPUT_NWB` | path exists file | 输入 NWB |
| `--mode` | choice | PR1 只允许 `rewrite-units`，其他 mode 报清晰错误 |
| `--output-dir` | dir path | rerun 输出根目录 |
| `--unit-updates` | file path | CSV/Parquet，按 `unit_id` 更新 units |
| `--overwrite` | flag | 允许覆盖已存在的同名 rerun NWB |

### Unit updates 表

PR1 支持 CSV；Parquet 可作为后续增强。

必需列：

| 列 | 说明 |
|----|------|
| `unit_id` | 匹配 NWB units row id |

可选列：

| 列 | 行为 |
|----|------|
| `keep` | bool；False 的 unit 从输出 units 中移除 |
| `unittype_string` | 覆盖 unit 分类 |
| `is_visual` | 覆盖视觉响应布尔值 |
| `slay_score` | 覆盖 SLAY 分数 |
| `merged_from` | JSON list 或分号分隔整数；写回 ragged list |

未知列默认追加/覆盖到输出 units，前提是长度与最终 unit 行数一致且类型可序列化。

## 4. 输出

### `NWBRerunResult`

建议 dataclass：

```python
@dataclass(frozen=True)
class NWBRerunResult:
    mode: str
    input_nwb: Path
    output_nwb: Path
    report_path: Path
    checkpoint_path: Path
    n_units_before: int
    n_units_after: int
```

### 文件输出

| 文件 | 说明 |
|------|------|
| `{output_dir}/nwb_rerun/{stem}_rerun_vNNN.nwb` | 修改后的 NWB 副本 |
| `{output_dir}/nwb_rerun/nwb_rerun_report.json` | 人类/机器可读报告 |
| `{output_dir}/nwb_rerun/checkpoints/nwb_rerun.json` | rerun checkpoint |

## 5. 处理步骤

### PR1: rewrite-units

1. `NWBLoader(nwb_path).require_capabilities("rewrite-units")`。
2. 读取原 units：`original_units = loader.load_units()`。
3. 读取 `unit_updates`。
4. 校验：
   - `unit_id` 唯一。
   - 所有 update `unit_id` 都存在于原 units。
   - 不允许更新 `spike_times`。
   - `keep` 若存在必须可转 bool。
   - `merged_from` 若存在必须可解析为 list[int]。
5. 生成 `new_units`：
   - 先按 `unit_id` left join 更新列。
   - 对提供的列覆盖原值。
   - 若 `keep` 存在，过滤 `keep == False`。
6. 选择输出路径：
   - 若 `version is None`，自动递增 `_rerun_v001`、`_rerun_v002`。
   - 若目标存在且 `overwrite=False`，raise `NWBRerunError`。
7. 复制输入 NWB 到输出路径。
8. 在副本中替换 `/units`。
9. 写 provenance：
   - `scratch["nwb_rerun_report"]` 写 JSON 摘要。
   - 保留输入文件原有 scratch keys。
10. 用 `NWBHDF5IO(output_nwb, "r")` 验证可打开，units 行数匹配。
11. 写 report + completed checkpoint。

### 替换 `/units` 的实现选择

PR1 推荐先实现为内部 helper：

```python
rewrite_units_table(output_nwb: Path, units_df: pd.DataFrame, report: dict) -> None
```

实现上允许两种路径，TDD 时根据 PyNWB/HDF5 可行性选择：

| 方案 | 优点 | 风险 |
|------|------|------|
| HDF5 低层删除 `/units` 后写新 DynamicTable | 保留原 NWB 绝大部分内容 | PyNWB 对 DynamicTable in-place 替换支持有限 |
| 读原 NWB -> 构造新 NWBFile -> 拷贝核心字段 -> 写新文件 | PyNWB 语义更正统 | PR1 要复制的对象较多，工作量变大 |

若低层替换在测试中不稳定，PR1 应退回"新建 NWBFile + 复制核心对象"而不是引入脆弱 hack。无论采用哪种，输入 NWB 原文件都不能改变。

### PR2/PR3: postprocess rerun

PR3 先实现 `mode="postprocess"` 的轻量版本：

1. `NWBLoader(nwb_path).require_capabilities("postprocess")`，要求 `/units` 与非空 `trials`。
2. 读取 `/units`，按 `probe_id` 分组。
3. 对每个 probe 读取 stimulus onset：
   - 优先使用 `trials["stim_onset_imec_{probe_id}"]`。
   - 对 reference probe `imec0`，若 per-probe 列不存在，可 fallback 到 `stim_onset_time`。
   - 若 `trial_valid` 存在，`False/0/no` trial 视为无效 onset；`NaN` 视为尚未验证，保留为有效 trial。
4. 对每个 unit 用 NWB 中的 `spike_times`（秒，probe local IMEC clock）重算：
   - `slay_score`：复用 `PostprocessStage._compute_slay` 的 10 ms bin + trial-to-trial Spearman 语义。
   - `is_visual`：复用 Mann-Whitney U `p < 0.001` + response > baseline 的语义。
5. 将计算结果作为 unit update table 写回 copied NWB 的 `/units`。
6. report/checkpoint 的 `mode` 写为 `"postprocess"`。

后续 full postprocess 版本保留以下扩展点：

1. 从 `/units` 拆 per-probe sorting。
2. 若需要 waveform/template/unit_locations，要求 AP raw stream 存在。
3. 重建或加载 SpikeInterface SortingAnalyzer。
4. 运行 merge/curate/postprocess 相关逻辑。
5. 写新的 NWB units 和 rerun provenance。

开放问题：

- 仅 `/units` 是否足够做 metric computation？大多数 waveform/template metric 需要 recording，因此 B 模式可能分成 `labels-only` 与 `full-postprocess` 两档。

### PR3: raw rerun（设计保留）

1. 从 acquisition `ElectricalSeriesAP_{probe_id}` 生成 Recording-like 适配器。
2. 接入 preprocess/sort stage，避免 stage 直接绑定 `SpikeGLXLoader`。
3. 对 raw AP/LF/NIDQ 做必要 metadata 恢复。
4. 输出新 NWB。

开放问题：

- NWB 中 raw AP 是否包含足够 channel geometry / gain / sampling metadata，能否完全重建 SpikeInterface Recording。
- 如果原 NWB 没有 Phase 3 raw append，应明确报错，不 fallback 到原 SpikeGLX 路径。

## 6. 可配参数

PR1 不改 `pipeline.yaml`。

未来若 UI 接入，可新增 rerun panel 表单字段，不进入主 pipeline config：

| 参数 | 默认 | 说明 |
|------|------|------|
| `mode` | `rewrite-units` | 回炉模式 |
| `output_strategy` | `copy` | copy/in-place/new-from-scratch |
| `version` | auto | rerun 版本后缀 |
| `strict` | `True` | 严格要求 pynpxpipe NWB 结构 |

## 7. 错误处理

新增错误类型建议：

```python
class NWBRerunError(PynpxpipeError):
    """NWB rerun workflow failed."""
```

错误原则：

- 所有业务错误包装为 `NWBRerunError` 或 `NWBInputError`。
- 失败时写 failed checkpoint。
- 若输出文件写到一半失败，删除不完整输出副本，保留原输入 NWB。
- CLI 捕获 `PynpxpipeError` 后 exit code 1，未知异常 exit code 2，延续现有 CLI 风格。

## 8. 测试计划

测试文件：

- `tests/test_io/test_nwb_reader.py`
- `tests/test_pipelines/test_nwb_rerun.py`
- `tests/test_cli/test_main.py`

### Pipeline tests

| 测试名 | 构造 | 预期 |
|--------|------|------|
| `test_rewrite_units_creates_copy` | tiny NWB + update CSV | 输出新 NWB，输入文件 hash 不变 |
| `test_rewrite_units_updates_unittype` | 修改 `unittype_string` | 输出 units 对应行更新 |
| `test_rewrite_units_filters_keep_false` | `keep=False` | 输出 units 行数减少 |
| `test_rewrite_units_rejects_unknown_unit_id` | update 含不存在 id | raise `NWBRerunError` |
| `test_rewrite_units_rejects_spike_times_update` | update 含 `spike_times` | raise `NWBRerunError` |
| `test_rewrite_units_writes_checkpoint` | 成功 | checkpoint status=completed |
| `test_rewrite_units_failed_checkpoint` | 强制写出失败 | checkpoint status=failed |
| `test_rewrite_units_report_in_scratch` | 成功 | output NWB scratch 含 rerun report |
| `test_auto_version_increments` | v001 已存在 | 输出 v002 |

### CLI tests

| 测试名 | 构造 | 预期 |
|--------|------|------|
| `test_rerun_from_nwb_cli_calls_pipeline` | mock `rerun_from_nwb` | 参数传递正确 |
| `test_rerun_from_nwb_cli_rejects_unimplemented_mode` | `--mode raw` | exit 非 0，message 清楚 |
| `test_rerun_from_nwb_cli_success_message` | mock result | 输出 output NWB 路径 |

## 9. 与 MATLAB 参考实现的关系

legacy MATLAB 没有 NWB 回炉入口。本模块是围绕 pynpxpipe/DANDI 产物的新能力。

与 MATLAB 的概念对应：

| MATLAB 中间产物 | pynpxpipe NWB 对应 |
|-----------------|-------------------|
| `GoodUnitRaw_*.mat` | `/units` + pre-curation/provenance columns |
| `GoodUnit_*.mat` | `/units` filtered/curated rows + `unittype_string` |
| `META_*.mat` | `trials` + `scratch["sync_tables"]` |
| `Raster` / `UnitProp` / `TrialRecord` | `07_derivatives`，可由 NWB 重新导出 |

有意偏离：

- MATLAB 可以直接覆盖 `.mat` 中间文件；pynpxpipe 默认 copy-on-write 生成 rerun NWB。
- MATLAB 后处理常以 NIDQ/ms 时钟组织 spike time；pynpxpipe NWB units 保持 IMEC 秒，trial anchor 按 reference probe `imec0` 约定。
- MATLAB 单/多 probe 逻辑混杂；NWB 回炉必须以 `probe_id` 列为一等公民。

## 10. 验收标准

PR1 完成条件：

1. spec 经用户确认。
2. `NWBLoader.inspect()` / `load_units()` 单元测试通过。
3. `rerun_from_nwb(..., mode="rewrite-units")` 能对 synthetic NWB 生成新 NWB，输入文件不变。
4. 输出 NWB 可被 `pynwb.NWBHDF5IO` 打开，units 更新可读。
5. CLI `rerun-from-nwb` 有测试覆盖。
6. `ruff check`、`ruff format --check`、目标测试通过。

非 PR1 验收项：

- 不要求 raw AP rerun。
- 不要求 full postprocess rerun。
- 不要求真实 5h session E2E。
- 不要求 UI 接入。
