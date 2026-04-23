# Spec: stages/discover.py

## 1. 目标

实现 pipeline 第一个 stage：**发现（Discover）**。

扫描 SpikeGLX 录制目录，发现所有 IMEC probe 子目录，验证每个 probe 的 AP/LF bin+meta 文件完整性（文件大小与 meta 中记录的样本数匹配），定位 NIDQ 数据，验证 BHV2 文件头魔术字节，**将用户在 UI 预声明的 `session.probe_plan` 与磁盘发现结果做一致性校验（mismatch 即 raise）**，**将 `probe_plan` 中声明的 `target_area` 填入每个 `ProbeInfo`**，将探针信息写入 `session.probes`，并向 `{output_dir}` 写 `session_info.json`。

本模块属于 stages 层，无 UI 依赖。所有业务逻辑在 `io/spikeglx.py`（`SpikeGLXDiscovery`、`SpikeGLXLoader`）中，`DiscoverStage` 仅作编排层（调用 IO 层函数 + checkpoint/logging + probe_plan 校验）。

---

## 2. 输入

### `DiscoverStage.__init__` 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session` | `Session` | 含 `session_dir`、`output_dir`、`bhv_file`、`probe_plan` |
| `progress_callback` | `Callable[[str, float], None] \| None` | 进度回调，CLI 模式为 `None` |

### `run()` 依赖的 session 字段

| 字段 | 说明 |
|---|---|
| `session.session_dir` | SpikeGLX 录制根目录（必须存在） |
| `session.output_dir` | 输出根目录（由 runner 提前创建） |
| `session.bhv_file` | MonkeyLogic BHV2 文件路径 |
| `session.probe_plan` | `dict[str, str]`：用户预声明的 `probe_id → target_area` 映射，非空，由 UI/CLI 在 Session 构造时填入 |

---

## 3. 输出

### 副作用

1. `session.probes` 填充为 `list[ProbeInfo]`（按 probe_id 字母序排列），每个 ProbeInfo 的 `target_area` 从 `session.probe_plan[probe_id]` 填入
2. `{output_dir}/session_info.json` 写出（UTF-8，缩进 2）
3. `{output_dir}/checkpoints/discover.json` 写出完成 checkpoint

### `session_info.json` 结构

```json
{
  "session_dir": "/path/to/session",
  "n_probes": 2,
  "probe_ids": ["imec0", "imec1"],
  "probe_sample_rates": {"imec0": 30000.0, "imec1": 30000.0},
  "probe_target_areas": {"imec0": "MSB", "imec1": "V4"},
  "nidq_found": true,
  "lf_found": true,
  "bhv_file": "/path/to/session.bhv2",
  "warnings": []
}
```

### checkpoint payload

```json
{
  "n_probes": 2,
  "probe_ids": ["imec0", "imec1"],
  "nidq_found": true,
  "lf_found": true,
  "warnings": []
}
```

---

## 4. 处理步骤

### `run()`

1. **检查 checkpoint**：调用 `_is_complete()`；若已完成 → `_report_progress("Discover already complete", 1.0)` 并 return
2. **校验 probe_plan 非空**：若 `session.probe_plan` 为空 dict → raise `DiscoverError("session.probe_plan is empty; at least one probe must be declared")`
3. **报告进度**：`_report_progress("Scanning session directory", 0.0)`
4. **扫描 probe 目录**：调用 `SpikeGLXDiscovery(session.session_dir).discover_probes()`，返回 `list[ProbeInfo]`（各 `target_area="unknown"` 占位）；若返回空列表 → raise `DiscoverError("No IMEC probes found in {session.session_dir}")`
5. **probe_plan ↔ disk 一致性校验**：
   - `declared = set(session.probe_plan.keys())`
   - `found = {p.probe_id for p in discovered_probes}`
   - 若 `declared != found` → raise `ProbeDeclarationMismatchError(declared, found)`（异常 `__str__` 给出 `missing_on_disk = declared - found` 和 `unexpected_on_disk = found - declared` 的详细差集）
6. **注入 target_area**：遍历 `discovered_probes`，将 `probe.target_area = session.probe_plan[probe.probe_id]` 原地赋值
7. **验证各 probe 文件完整性**：对每个 probe，调用 `SpikeGLXDiscovery.validate_probe(probe_id)` 返回 `list[str]`（警告列表）；将警告追加到 `warnings` 列表；若所有 probe 均验证失败 → raise `DiscoverError`
8. **发现 NIDQ 数据**：调用 `SpikeGLXDiscovery.discover_nidq()`；若未发现 NIDQ → raise `DiscoverError("NIDQ data not found in {session.session_dir}")`
9. **检查 LF 数据（可选）**：调用 `SpikeGLXDiscovery.discover_lf_streams()`，记录 `lf_found` 布尔值（缺失不 raise，仅记录）
10. **验证 BHV2 文件头**：以二进制读取 `session.bhv_file` 前 21 字节，验证 == `BHV2_MAGIC = b'\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition'`；不匹配 → raise `DiscoverError("BHV2 file {session.bhv_file} has invalid magic bytes")`；文件不存在 → raise `DiscoverError`
11. **填充 session.probes**：将步骤 4–6 返回的 `list[ProbeInfo]`（按 probe_id 排序）赋给 `session.probes`
12. **写 session_info.json**：构造 dict（含 `probe_target_areas`），`json.dump` 到 `output_dir / "session_info.json"`
13. **写 checkpoint**：`_write_checkpoint(data)` 其中 data 含 n_probes、probe_ids、nidq_found、lf_found、warnings
14. **报告进度**：`_report_progress("Discover complete", 1.0)`

若步骤 2-10 中任何一步 raise，调用 `_write_failed_checkpoint(error)` 后 re-raise。

---

## 5. 公开 API

```python
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pynpxpipe.stages.base import BaseStage

if TYPE_CHECKING:
    from pynpxpipe.core.session import Session

BHV2_MAGIC = b'\x0d\x00\x00\x00\x00\x00\x00\x00IndexPosition'


class DiscoverStage(BaseStage):
    """Scans the SpikeGLX recording folder and validates all data files.

    After this stage completes, session.probes is populated with one ProbeInfo
    per discovered IMEC probe, each with target_area filled from
    session.probe_plan, and session_info.json is written to output_dir.

    Raises:
        DiscoverError: If no probes found, NIDQ missing, BHV2 file invalid, or
            probe_plan is empty.
        ProbeDeclarationMismatchError: If session.probe_plan keys do not
            exactly match the probe_ids discovered on disk.
    """

    STAGE_NAME = "discover"

    def __init__(
        self,
        session: Session,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> None: ...

    def run(self) -> None:
        """Scan session_dir for all probes and validate data integrity.

        Steps:
        1. Check checkpoint; skip if complete.
        2. Validate session.probe_plan is non-empty.
        3. Use SpikeGLXDiscovery to discover probes (raises if none found).
        4. Validate probe_plan keys match discovered probe_ids exactly.
        5. Inject target_area from probe_plan into each ProbeInfo.
        6. Validate each probe's bin/meta file size.
        7. Locate NIDQ (raises if not found).
        8. Check LF presence (non-fatal).
        9. Validate BHV2 magic bytes (raises if invalid).
        10. Populate session.probes and write session_info.json.
        11. Write completed checkpoint.
        """
```

### 新增异常 `ProbeDeclarationMismatchError`

**放在 `src/pynpxpipe/core/errors.py`**，继承 `DiscoverError`（保留既有 `except DiscoverError` 捕获面）。

```python
class ProbeDeclarationMismatchError(DiscoverError):
    """Raised when session.probe_plan does not match probes found on disk.

    Attributes:
        declared: Set of probe_ids declared by the user via probe_plan.
        found: Set of probe_ids actually discovered in session_dir.
        missing_on_disk: declared - found (user declared but disk lacks).
        unexpected_on_disk: found - declared (disk has but user did not declare).
    """

    def __init__(self, declared: set[str], found: set[str]) -> None:
        self.declared = declared
        self.found = found
        self.missing_on_disk = declared - found
        self.unexpected_on_disk = found - declared
        parts = []
        if self.missing_on_disk:
            parts.append(f"declared but not on disk: {sorted(self.missing_on_disk)}")
        if self.unexpected_on_disk:
            parts.append(f"on disk but not declared: {sorted(self.unexpected_on_disk)}")
        super().__init__(
            f"probe_plan mismatch — {'; '.join(parts)}. "
            f"declared={sorted(declared)}, found={sorted(found)}"
        )
```

### 可配参数

本 stage 无配置参数——所有发现逻辑由目录结构驱动，所有 `target_area` 由 `session.probe_plan` 驱动。BHV2 魔术字节 `BHV2_MAGIC`（前 21 字节：uint64 LE 值 13 + "IndexPosition"）是 MonkeyLogic BHV2 格式固定值，不可配置。

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_stages/test_discover.py`

测试策略：用 `tmp_path` 构造伪 SpikeGLX 目录结构（创建 `.ap.meta`、`.ap.bin`、`.lf.meta`、`.lf.bin`、`nidq.meta`、`nidq.bin`），`session.bhv_file` 指向含正确魔术字节的临时文件。`SpikeGLXDiscovery` 用 mock 替换（不依赖真实 SpikeGLX 文件格式细节）。所有测试的 `session` fixture 必须带有 `probe_plan`（默认值与发现的 probes 匹配）。

### 正常流程

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_populates_session_probes` | 2 probe 目录 + NIDQ + 有效 BHV2，probe_plan={imec0:MSB, imec1:V4} | `session.probes` 有 2 个 ProbeInfo |
| `test_run_injects_target_area_from_probe_plan` | 同上 | `session.probes[0].target_area=="MSB"`、`session.probes[1].target_area=="V4"` |
| `test_run_writes_session_info_json` | 同上 | `output_dir/session_info.json` 存在且含 `probe_target_areas` 字段 |
| `test_session_info_json_contains_target_areas` | 同上 | `probe_target_areas == {"imec0":"MSB","imec1":"V4"}` |
| `test_run_writes_completed_checkpoint` | 同上 | `checkpoints/discover.json` status=completed |
| `test_session_info_json_probe_ids_sorted` | probe 目录 imec1、imec0（乱序） | `probe_ids == ["imec0","imec1"]` |
| `test_session_info_json_nidq_found_true` | NIDQ 存在 | `nidq_found: true` |
| `test_lf_found_false_does_not_raise` | 无 LF 文件 | 不 raise，`lf_found: false` |
| `test_probe_warnings_included_in_output` | validate_probe 返回 1 条警告 | `session_info.json` warnings 非空 |

### 已完成 checkpoint 跳过

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_skips_if_checkpoint_complete` | discover checkpoint 已存在且 complete | `run()` 立即返回，不调用 SpikeGLXDiscovery |
| `test_run_still_returns_none_on_skip` | 同上 | 返回 None（无异常） |

### probe_plan 校验

| 测试名 | 输入构造 | 预期异常 |
|---|---|---|
| `test_empty_probe_plan_raises_discover_error` | probe_plan={}  | raise `DiscoverError`，消息含 "probe_plan is empty" |
| `test_probe_plan_declared_not_on_disk_raises_mismatch` | probe_plan={imec0:MSB, imec1:V4}，磁盘只有 imec0 | raise `ProbeDeclarationMismatchError`，`missing_on_disk=={"imec1"}` |
| `test_probe_plan_unexpected_on_disk_raises_mismatch` | probe_plan={imec0:MSB}，磁盘有 imec0、imec1 | raise `ProbeDeclarationMismatchError`，`unexpected_on_disk=={"imec1"}` |
| `test_mismatch_error_message_lists_both_sides` | probe_plan={imec0:MSB, imec2:V4}，磁盘有 imec0、imec1 | 错误消息同时含 `imec2` 和 `imec1` |
| `test_probe_mismatch_is_subclass_of_discover_error` | 同上 | `isinstance(exc, DiscoverError)` == True |

### 其他错误处理

| 测试名 | 输入构造 | 预期异常 |
|---|---|---|
| `test_no_probes_found_raises_discover_error` | discover_probes 返回空列表 | raise `DiscoverError`，消息含 "No IMEC probes" |
| `test_nidq_not_found_raises_discover_error` | discover_nidq 返回 None | raise `DiscoverError`，消息含 "NIDQ" |
| `test_bhv2_wrong_magic_raises_discover_error` | BHV2 文件前 21 字节不匹配 | raise `DiscoverError`，消息含 "invalid magic bytes" |
| `test_bhv2_not_found_raises_discover_error` | session.bhv_file 不存在 | raise `DiscoverError` |
| `test_failed_checkpoint_written_on_error` | discover_probes raise | `checkpoints/discover.json` status=failed |
| `test_failed_checkpoint_written_on_probe_plan_mismatch` | probe_plan 不匹配 | `checkpoints/discover.json` status=failed |

### progress_callback

| 测试名 | 预期行为 |
|---|---|
| `test_progress_callback_called_at_start` | callback 以 fraction=0.0 被调用 |
| `test_progress_callback_called_at_end` | callback 以 fraction=1.0 被调用 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类，提供 checkpoint/logging/callback |
| `pynpxpipe.core.session.Session` | 项目内部 | TYPE_CHECKING，运行时通过 session 对象访问 |
| `pynpxpipe.core.session.ProbeInfo` | 项目内部 | 探针信息结构（target_area 字段必填） |
| `pynpxpipe.core.errors.DiscoverError` | 项目内部 | 发现失败时抛出 |
| `pynpxpipe.core.errors.ProbeDeclarationMismatchError` | 项目内部 | probe_plan 与磁盘不一致时抛出，继承 DiscoverError |
| `pynpxpipe.io.spikeglx.SpikeGLXDiscovery` | 项目内部 | 实际扫描逻辑 |
| `json` | 标准库 | 写 session_info.json |
| `pathlib.Path` | 标准库 | 文件路径操作 |

---

## 8. MATLAB 对照

| 项目 | 说明 |
|------|------|
| **对应 MATLAB 步骤** | step #0（SpikeGLX 文件夹发现）, #2（BHV2 发现）, #5（IMEC AP metadata） |
| **Ground Truth 详情** | `docs/ground_truth/step4_full_pipeline_analysis.md` step #0, #2, #5 |

### 有意偏离

| 偏离 | 理由 |
|------|------|
| 统一的 discover stage 而非分散的发现逻辑 | MATLAB 在各步骤中分别发现不同文件类型；Python 集中在一个 stage 完成所有发现和验证 |
| BHV2 存在性验证使用 magic bytes | MATLAB 仅检查文件扩展名；Python 额外验证文件头确保不是损坏文件 |
| 输出 session_info.json | MATLAB 无持久化的 session info；Python 写 JSON 供其他 stage 和工具消费 |
| 自动填充 Session 对象 | MATLAB 使用松散的工作区变量；Python 用结构化 Session dataclass 确保类型安全 |
| 预声明 probe_plan + 硬校验 | MATLAB 无 target_area 概念；Python 要求用户在 UI 预声明每个 probe 的脑区，discover 时硬校验并注入，作为下游 NWB ElectrodeGroup.location 的单一真源 |
