# Spec: cli/main.py

## 1. 目标

实现 CLI 薄壳入口，是 `click` 在整个项目中的**唯一导入位置**。

提供三个命令：
- `run`：执行完整（或部分）pipeline
- `status`：显示已有输出目录的 pipeline 状态
- `reset-stage`：删除指定 stage 的 checkpoint 以强制重跑

所有业务逻辑均在 `core/`、`io/`、`stages/`、`pipelines/` 层中；CLI 层只解析参数、构建对象、调用 `PipelineRunner`，不含任何计算逻辑。

**约束**：
- `cli/` 下禁止 `import` 任何业务层以外的包（允许 click、pathlib、sys）
- 业务层不得 `import click`、不得 `print()` 用户信息、不得 `sys.exit()`
- 退出码：`0` = 正常，`1` = `PynpxpipeError`，`2` = 非预期异常

---

## 2. 输入

### `run` 命令

| 参数/选项 | 类型 | 说明 |
|---|---|---|
| `session_dir` | positional `Path` (exists, dir) | SpikeGLX 录制根目录 |
| `bhv_file` | positional `Path` (exists, file) | MonkeyLogic BHV2 文件 |
| `--subject` | option `Path` (exists, file), required | subject YAML 文件（如 `monkeys/MaoDan.yaml`） |
| `--output-dir` | option `Path` (file_okay=False), required | 输出根目录 |
| `--pipeline-config` | option `Path` (exists, file) | pipeline.yaml，默认 `config/pipeline.yaml` |
| `--sorting-config` | option `Path` (exists, file) | sorting.yaml，默认 `config/sorting.yaml` |
| `--stages` | option `click.Choice(STAGE_ORDER)`, multiple=True | 只运行指定 stage，可多次使用 |

### `status` 命令

| 参数 | 类型 | 说明 |
|---|---|---|
| `output_dir` | positional `Path` (exists, dir) | 已有 pipeline 输出目录 |

### `reset-stage` 命令

| 参数/选项 | 类型 | 说明 |
|---|---|---|
| `output_dir` | positional `Path` (exists, dir) | session 输出目录 |
| `stage` | positional `click.Choice(STAGE_ORDER)` | 要重置的 stage 名称 |
| `--yes / -y` | flag | 跳过确认提示 |

---

## 3. 输出

### `run`

- 成功：`click.echo(f"Pipeline complete. Output: {output_dir}")` + 退出 0
- `PynpxpipeError`：`click.echo(f"Error: {e}", err=True)` + 退出 1
- 其他异常：`click.echo(f"Unexpected error: {e}", err=True)` + 退出 2

### `status`

输出格式（`click.echo`）：

```
Pipeline status: /path/to/output

  discover     ✓ completed
  preprocess   ✓ completed
  sort         ✓ completed
  synchronize  ✗ failed
  curate       - pending
  postprocess  - pending
  export       - pending
```

"partial (N/M probes)" 状态直接显示字符串。

### `reset-stage`

```
Reset stage 'sort' (will delete sort checkpoint and per-probe sort checkpoints)?
[y/N]: y
Reset complete.
```

若 `--yes` 跳过确认直接执行。

---

## 4. 处理步骤

### `run` 命令实现

```python
def run(...):
    try:
        subject_config = load_subject_config(subject)        # 从 YAML 加载 SubjectConfig
        session = SessionManager.create(
            session_dir=session_dir,
            output_dir=output_dir,
            subject=subject_config,
            bhv_file=bhv_file,
        )
        pipeline_config = load_pipeline_config(pipeline_config_path)
        sorting_config = load_sorting_config(sorting_config_path)
        runner = PipelineRunner(session, pipeline_config, sorting_config)
        runner.run(stages=list(stages) if stages else None)
        click.echo(f"Pipeline complete. Output: {output_dir}")
    except PynpxpipeError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
        sys.exit(2)
```

### `status` 命令实现

```python
def status(output_dir):
    # 构造一个只用于查询 checkpoint 的最小 session（或直接用 CheckpointManager）
    checkpoint_manager = CheckpointManager(output_dir)
    # 无法完全还原 session.probes，用 session_info.json 中的 probe_ids
    session_info = json.loads((output_dir / "session_info.json").read_text())
    probe_ids = session_info.get("probe_ids", [])
    # 构造最小 session 对象，或直接调用 checkpoint_manager.get_status_all(...)
    runner_status = _get_stage_statuses(checkpoint_manager, probe_ids)
    click.echo(f"Pipeline status: {output_dir}\n")
    for stage, status_str in runner_status.items():
        icon = "✓" if status_str == "completed" else ("✗" if status_str == "failed" else "-")
        click.echo(f"  {stage:<15}{icon} {status_str}")
```

### `reset-stage` 命令实现

```python
def reset_stage(output_dir, stage, yes):
    if not yes:
        click.confirm(f"Reset stage '{stage}'?", abort=True)
    checkpoint_manager = CheckpointManager(output_dir)
    # 删除 stage 级 checkpoint
    checkpoint_manager.clear(stage)
    # 删除 per-probe checkpoints（preprocess/sort/curate/postprocess）
    PER_PROBE_STAGES = {"preprocess", "sort", "curate", "postprocess"}
    if stage in PER_PROBE_STAGES:
        for probe_checkpoint in (output_dir / "checkpoints").glob(f"{stage}_imec*.json"):
            probe_checkpoint.unlink(missing_ok=True)
    click.echo("Reset complete.")
```

---

## 5. 公开 API（CLI 命令签名）

```python
import sys
from pathlib import Path

import click

from pynpxpipe.pipelines.runner import STAGE_ORDER


@click.group()
@click.version_option()
def cli() -> None:
    """pynpxpipe — Neural electrophysiology preprocessing pipeline."""


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("bhv_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--subject", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output-dir", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--pipeline-config", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=Path("config/pipeline.yaml"), show_default=True)
@click.option("--sorting-config", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=Path("config/sorting.yaml"), show_default=True)
@click.option("--stages", multiple=True, type=click.Choice(STAGE_ORDER))
def run(session_dir, bhv_file, subject, output_dir, pipeline_config, sorting_config, stages) -> None:
    """Run the pipeline for SESSION_DIR with behavioral file BHV_FILE."""


@cli.command()
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def status(output_dir: Path) -> None:
    """Show the pipeline status for an existing output directory."""


@cli.command()
@click.argument("output_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("stage", type=click.Choice(STAGE_ORDER))
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation prompt.")
def reset_stage(output_dir: Path, stage: str, yes: bool) -> None:
    """Delete the checkpoint for STAGE to force it to re-run."""
```

---

## 6. 测试范围（TDD 用）

测试文件：`tests/test_cli/test_main.py`

测试策略：全部使用 `click.testing.CliRunner`（`CliRunner.invoke(cli, args)`）；mock `PipelineRunner.run()`、`SessionManager.create()`、`load_pipeline_config()`、`CheckpointManager` 等业务逻辑，不运行真实 pipeline。

### `run` 命令

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_run_success_exits_zero` | 合法参数，PipelineRunner.run() 成功 | exit_code=0 |
| `test_run_outputs_complete_message` | 成功 | output 含 "Pipeline complete" |
| `test_run_pynpxpipe_error_exits_one` | PipelineRunner.run() raise PynpxpipeError | exit_code=1 |
| `test_run_unexpected_error_exits_two` | PipelineRunner.run() raise RuntimeError | exit_code=2 |
| `test_run_error_message_to_stderr` | 任意错误 | 错误信息写到 stderr（err=True） |
| `test_run_stages_option_passed` | `--stages sort --stages curate` | runner.run(stages=["sort","curate"]) 被调用 |
| `test_run_no_stages_passes_none` | 无 --stages | runner.run(stages=None) 被调用 |
| `test_run_requires_subject` | 缺少 --subject | exit_code != 0，帮助信息显示 |
| `test_run_requires_output_dir` | 缺少 --output-dir | exit_code != 0 |

### `status` 命令

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_status_shows_all_stages` | 有效 output_dir（含 session_info.json） | 输出含所有 7 个 stage 名称 |
| `test_status_completed_shows_check` | discover=completed | 输出含 "✓" 或 "completed" |
| `test_status_pending_shows_dash` | 所有 pending | 输出含 "pending" |
| `test_status_failed_shows_x` | 某 stage=failed | 输出含 "✗" 或 "failed" |

### `reset-stage` 命令

| 测试名 | 输入构造 | 预期行为 |
|---|---|---|
| `test_reset_stage_with_yes_skips_prompt` | `--yes` | 直接删除，不等待 stdin |
| `test_reset_stage_deletes_stage_checkpoint` | stage="sort", `--yes` | `checkpoints/sort.json` 被删除 |
| `test_reset_stage_deletes_probe_checkpoints` | stage="preprocess", `--yes` | `checkpoints/preprocess_imec0.json` 被删除 |
| `test_reset_single_checkpoint_stage` | stage="discover", `--yes` | 仅删 stage checkpoint，无 per-probe 清理 |
| `test_reset_confirms_without_yes` | 无 `--yes`，stdin 输入 "y" | 成功删除 |
| `test_reset_aborts_without_yes_and_n` | 无 `--yes`，stdin 输入 "n" | 不删除，输出 "Aborted" |

### CLI 架构约束

| 测试名 | 预期行为 |
|---|---|
| `test_click_not_imported_in_business_layer` | `grep "import click" src/pynpxpipe/{core,io,stages,pipelines}/**` 无结果 |
| `test_sys_exit_not_in_business_layer` | `grep "sys.exit" src/pynpxpipe/{core,io,stages,pipelines}/**` 无结果 |

---

## 7. 依赖

| 依赖 | 类型 | 说明 |
|---|---|---|
| `click` | 第三方 | **唯一导入 click 的模块**；`@click.group`, `@click.command`, `@click.argument`, `@click.option` |
| `sys` | 标准库 | `sys.exit(1)` / `sys.exit(2)` |
| `json` | 标准库 | 读取 session_info.json（status 命令） |
| `pathlib.Path` | 标准库 | 路径操作 |
| `pynpxpipe.pipelines.runner.PipelineRunner` | 项目内部 | 业务编排 |
| `pynpxpipe.pipelines.runner.STAGE_ORDER` | 项目内部 | stage 名称列表，用于 `click.Choice` |
| `pynpxpipe.core.session.SessionManager` | 项目内部 | 创建 session 对象 |
| `pynpxpipe.core.config.load_pipeline_config` | 项目内部 | 加载 pipeline.yaml |
| `pynpxpipe.core.config.load_sorting_config` | 项目内部 | 加载 sorting.yaml |
| `pynpxpipe.core.checkpoint.CheckpointManager` | 项目内部 | status/reset 命令中查询和删除 checkpoint |
| `pynpxpipe.core.errors.PynpxpipeError` | 项目内部 | 捕获业务层异常（exit code 1） |
