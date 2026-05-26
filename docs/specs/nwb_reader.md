# Spec: io/nwb_reader.py

## 1. 目标

`io/nwb_reader.py` 提供从 pynpxpipe 产出的 NWB 文件反向读取 pipeline 所需数据的能力，是任务 2 "NWB 回炉处理" 的底层 IO 模块。

本模块只负责读取、校验和转换 NWB 内容，不执行 curation、postprocess、export，也不修改 NWB 文件。业务编排放在 `pipelines/nwb_rerun.py`，CLI 只做薄壳调用。

首个实现范围（Task 2 PR1）聚焦最小闭环：

1. 打开 NWB 并生成结构摘要。
2. 读取 `/units` 表，保留 spike_times、probe_id、unit 分类和 provenance 列。
3. 检查是否具备后续 B/C 回炉所需的输入条件。

未来范围（PR2+）才加入 raw AP/LF `ElectricalSeries` 到 SpikeInterface Recording-like 接口、以及 `/units` 到 Sorting-like 接口的完整适配。

## 2. 输入

### `NWBLoader.__init__`

| 参数 | 类型 | 说明 |
|------|------|------|
| `nwb_path` | `Path` | 已存在的 `.nwb` 文件路径 |

### 支持的 NWB 来源

首版只承诺支持 pynpxpipe 自己写出的 NWB，依据：

- `docs/specs/nwb_writer.md`
- `docs/specs/export.md`
- `NWBWriter.add_probe_data()`
- `NWBWriter.add_sync_tables()`
- `NWBWriter.add_pipeline_metadata()`
- `NWBWriter.append_raw_data()`

外部工具生成的 NWB 可以尝试读取，但如果缺少 pynpxpipe 约定列或 scratch metadata，应返回明确错误，而不是猜测补齐。

### 必读 NWB 结构

| NWB 位置 | PR1 用途 | 是否必需 |
|----------|----------|----------|
| `nwbfile.session_id` | 生成 rerun 输出命名、摘要 | 必需 |
| `nwbfile.subject` | 回炉输出继承 subject metadata | PR1 可选，缺失时报 warning |
| `nwbfile.units` | Units rewrite / postprocess rerun 输入 | C/B 必需 |
| `nwbfile.units["spike_times"]` | 每个 unit 的 spike times，单位秒 | C/B 必需 |
| `nwbfile.units["probe_id"]` | 多 probe 拆分 | C/B 必需 |
| `nwbfile.trials` | 保留 trials；未来重算 derivatives/raster | C 可保留，B 建议必需 |
| `nwbfile.scratch["sync_tables"]` | 时钟 provenance；未来 raw/postprocess 对齐 | B/A 建议必需 |
| `nwbfile.scratch["pipeline_config"]` | 恢复配置默认值 | 可选 |
| `nwbfile.scratch["merge_log_{probe_id}"]` | merge provenance | 可选 |
| `nwbfile.acquisition["ElectricalSeriesAP_{probe_id}"]` | 未来 A：从 raw AP 回炉 | A 必需 |
| `nwbfile.acquisition["ElectricalSeriesLF_{probe_id}"]` | 未来 A：LFP/raw provenance | A 可选 |
| `nwbfile.acquisition["NIDQ_raw"]` | 未来 A：同步/行为重建 | A 建议必需 |

### Units 表列

PR1 至少读取并往返保留这些列：

| 列 | 说明 |
|----|------|
| `id` / row id | NWB unit id；作为内部 `unit_id` |
| `spike_times` | ragged float seconds；保持每个 probe 自己的 IMEC clock |
| `probe_id` | 例如 `imec0`、`imec1` |
| `ks_id` | Kilosort 原始 id；若存在必须保留 |
| `unittype_string` | `SUA` / `MUA` / `NON-SOMA` / `NOISE` 等分类 |
| `is_visual` | postprocess 视觉响应判定 |
| `slay_score` | 当前兼容名，未来可能改为 `response_consistency_score` |
| `merged_from` | 合并 provenance；空列表合法 |

未知列默认按原样保留，除非用户提供的 rewrite 规则明确要求删除或替换。

## 3. 输出

### `NWBInputSummary`

建议新增 dataclass：

```python
@dataclass(frozen=True)
class NWBInputSummary:
    nwb_path: Path
    session_id: str
    subject_id: str | None
    probe_ids: tuple[str, ...]
    n_units: int
    n_trials: int
    has_units: bool
    has_trials: bool
    has_sync_tables: bool
    has_pipeline_config: bool
    raw_ap_streams: dict[str, str]
    raw_lf_streams: dict[str, str]
    has_nidq_raw: bool
```

其中 `raw_ap_streams` 映射 `probe_id -> acquisition key`，例如 `{"imec0": "ElectricalSeriesAP_imec0"}`。

### `UnitsTable`

建议用 `pandas.DataFrame` 作为 PR1 的交换格式：

- 一行一个 NWB unit。
- `unit_id` 为普通列，来自 NWB units row id。
- `spike_times` 为 `np.ndarray`，不展开成长表。
- `probe_id` 必须存在。
- 其他列按 NWB DynamicTable 列名保留。

理由：C 模式的 rewrite 主要是表级分类/列更新，DataFrame 最便于测试和人工检查；B 模式后续需要 SpikeInterface Sorting-like 对象时，再新增转换方法。

## 4. 处理步骤

### `inspect() -> NWBInputSummary`

1. 验证 `nwb_path.exists()` 且后缀为 `.nwb`。
2. 用 `pynwb.NWBHDF5IO(nwb_path, "r")` 打开。
3. 读取 `session_id`、subject、units/trials 行数。
4. 从 `units["probe_id"]` 收集 probe ids；若 units 缺失但 raw AP 存在，则从 acquisition key 推断 probe ids。
5. 检查 scratch keys：`sync_tables`、`pipeline_config`。
6. 扫描 acquisition keys：
   - `ElectricalSeriesAP_{probe_id}` -> AP raw stream
   - `ElectricalSeriesLF_{probe_id}` -> LF raw stream
   - `NIDQ_raw` -> session-level NIDQ stream
7. 返回摘要；不做重计算，不加载大数组。

### `load_units() -> pd.DataFrame`

1. 打开 NWB。
2. 若 `nwbfile.units is None`，raise `NWBInputError("NWB file has no /units table")`。
3. 将 units DynamicTable 转成 DataFrame。
4. 将 row id 暴露为 `unit_id`。
5. 对 `spike_times` ragged 列逐行转成 `np.ndarray(dtype=float)`。
6. 验证 `probe_id` 列存在且非空。
7. 返回 DataFrame。

### `require_capabilities(mode: Literal["rewrite-units", "postprocess", "raw"])`

按回炉模式做前置检查：

| mode | 必需能力 |
|------|----------|
| `rewrite-units` | units + probe_id + spike_times |
| `postprocess` | units + probe_id + spike_times + trials；若需 waveform/template/unit_locations，则还需 AP raw |
| `raw` | per-probe AP raw；建议 sync_tables + NIDQ_raw |

PR1 只实现 `rewrite-units` 检查；其他 mode 可以返回结构化 `NWBInputError`，说明尚未实现或缺少能力。

## 5. 可配参数

PR1 不引入 YAML 配置。所有选项由 `pipelines/nwb_rerun.py` 或 CLI 传入。

未来可选项：

| 参数 | 默认 | 说明 |
|------|------|------|
| `strict` | `True` | 是否要求 pynpxpipe 约定列完整存在 |
| `load_raw` | `False` | 是否允许加载 raw ElectricalSeries 数据 |
| `copy_unknown_unit_columns` | `True` | rewrite units 时是否保留未知列 |

## 6. 错误处理

新增错误类型建议：

```python
class NWBInputError(PynpxpipeError):
    """Invalid or unsupported NWB input for rerun workflows."""
```

错误原则：

- 文件不存在、打不开、不是 NWB：raise `NWBInputError`。
- 缺少当前 mode 必需结构：raise `NWBInputError`，message 包含缺失 key/列名。
- 缺少可选 provenance：记录 warning，summary 中对应 bool 为 False。
- 不吞掉 `pynwb` 原始异常；用 `raise ... from exc` 保留 traceback。

## 7. 测试计划

测试文件：`tests/test_io/test_nwb_reader.py`

测试使用 synthetic tiny NWB，不依赖真实数据，不读大型 raw。

| 测试名 | 构造 | 预期 |
|--------|------|------|
| `test_inspect_basic_pynpxpipe_nwb` | 最小 NWB + subject + units | summary 含 session_id、n_units、probe_ids |
| `test_inspect_detects_raw_streams` | acquisition 含 `ElectricalSeriesAP_imec0`、`NIDQ_raw` | summary 标记 AP/NIDQ 存在 |
| `test_load_units_returns_dataframe` | units 含 2 个 probe | DataFrame 含 `unit_id`、`probe_id`、`spike_times` |
| `test_load_units_preserves_unknown_columns` | 添加自定义 unit 列 | DataFrame 保留列 |
| `test_load_units_requires_probe_id` | units 无 `probe_id` | raise `NWBInputError` |
| `test_require_rewrite_units_capability` | 完整 units | 不 raise |
| `test_require_raw_capability_reports_missing_ap` | 无 AP acquisition | raise `NWBInputError`，message 含 `ElectricalSeriesAP` |
| `test_missing_file_raises_nwb_input_error` | 路径不存在 | raise `NWBInputError` |

## 8. 与 MATLAB 参考实现的关系

legacy MATLAB pipeline 没有 NWB 输入模式；其回炉通常围绕 `.mat` 中间结果（`META_*.mat`、`GoodUnitRaw_*.mat`、`GoodUnit_*.mat`）进行。因此本模块是 pynpxpipe 的功能扩展，不是 MATLAB 函数的逐行移植。

与 ground truth 的对应关系：

- `docs/ground_truth/step2_input_consumption.md` 说明原流程的输入来自 SpikeGLX `.bin/.meta` 与 BHV2。NWB 回炉模式把这些消费点折叠为一个已归档容器：raw AP/LF/NIDQ 在 `acquisition`，行为与同步结果在 `trials` / `scratch["sync_tables"]`，sorting 结果在 `/units`。
- `docs/ground_truth/bhv2_consumption_analysis.md` 说明后处理依赖 trial/onset/eye/stimulus 信息。NWB reader 不重新解析 BHV2，而是读取 export stage 已写入的 trials 与 provenance；若这些信息缺失，B/A 回炉不得猜测。

有意偏离：

| 方面 | MATLAB | NWB reader |
|------|--------|------------|
| 输入容器 | 分散的 `.bin/.meta/.bhv2/.mat` | 单个 NWB 文件 |
| spike time clock | MATLAB 后期转到 NIDQ/ms | 保留 pynpxpipe NWB 中的 IMEC 秒，按 probe 解释 |
| 回炉方式 | 修改中间 `.mat` 或重跑脚本 | 读取 NWB 后 copy-on-write 生成新回炉输出 |
| 多 probe | legacy 存在 `imec0` 偏置风险 | 必须以 `probe_id` 列拆分，不允许默认 imec0 |

## 9. 已知限制

- `graphify-out/GRAPH_REPORT.md` 当前缺失，本 spec 依据 `CLAUDE.md`、`docs/architecture.md`、现有 specs 和源码阅读制定。
- PR1 不实现 raw ElectricalSeries 到 SpikeInterface Recording 的适配。
- PR1 不实现 SortingAnalyzer/waveform/template 的重建。
- PR1 不原地修改输入 NWB 文件。
