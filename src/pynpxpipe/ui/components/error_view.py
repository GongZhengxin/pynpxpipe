"""ui/components/error_view.py — Why a stage failed and what to do (ui_redesign.md §4.3 P1-6).

Reads the failed checkpoint (error text) and the JSON Lines log (traceback),
classifies it with ``harness.classifier.Classifier`` and, for known fixable
failures, offers "按建议修改并重跑" which goes through the P0-4 rerun dialog.
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable
from pathlib import Path

import panel as pn

from pynpxpipe.harness.classifier import Classifier
from pynpxpipe.ui.state import AppState

# Chinese reason and advice per known error class.
_REASONS = {
    "cuda_oom": "GPU 显存不足",
    "cuda_unavailable": "CUDA 不可用",
    "sorter_not_found": "没有安装 Kilosort4",
    "no_probes": "没有找到探针",
    "sync_failure": "同步失败",
    "motion_oom": "运动校正内存不足",
}
_ADVICE = {
    "cuda_unavailable": "把 sorting 参数里的计算设备改为 auto 或 cpu，或检查显卡驱动与 CUDA 版 torch。",
    "sorter_not_found": "运行 `uv run python tools/install_sort_stack.py` 安装 torch 与 Kilosort4。",
    "no_probes": "确认数据目录下有 SpikeGLX gate 目录和 `_imec*` 子目录。",
    "sync_failure": "查看同步诊断图，核对事件码与 BHV2 是否对应。",
}


class _Failure:
    def __init__(self, stage: str, probe: str | None, error: str) -> None:
        self.stage, self.probe, self.error = stage, probe, error


def _find_failure(output_dir: Path, stage: str) -> _Failure | None:
    cp_dir = output_dir / "checkpoints"
    candidates = [(cp_dir / f"{stage}.json", None)]
    candidates += [(p, p.stem[len(stage) + 1 :]) for p in sorted(cp_dir.glob(f"{stage}_*.json"))]
    for path, probe in candidates:
        try:
            data = json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("status") == "failed":
            return _Failure(stage, probe, str(data.get("error", "")))
    return None


def _find_traceback(output_dir: Path, stage: str, probe: str | None) -> str:
    found = ""
    for log in sorted((output_dir / "logs").glob("*.log")):
        try:
            lines = log.read_text("utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(rec, dict)
                and rec.get("event") == "stage_failed"
                and rec.get("stage") == stage
                and rec.get("probe_id") == probe
            ):
                found = str(rec.get("traceback", ""))
    return found


class ErrorView:
    """Failure title, cause, advice, actions and the raw traceback.

    Args:
        state: Shared AppState (current configs for the suggested change).
        apply_fn: ``(changes, stage, probe_id)`` — apply and open the rerun dialog.
        open_params_fn: Show the parameter forms.
        help_fn: Open the AI help assistant.
        min_batch_size: Floor for a suggested Kilosort batch_size.
    """

    def __init__(
        self,
        state: AppState,
        *,
        apply_fn: Callable[[tuple, str, str | None], None],
        open_params_fn: Callable[[], None],
        help_fn: Callable[[], None],
        min_batch_size: int,
    ) -> None:
        self._state = state
        self._apply_fn = apply_fn
        self._min_batch_size = min_batch_size
        self._changes: tuple = ()
        self._failure: _Failure | None = None

        self.title = pn.pane.Markdown("", sizing_mode="stretch_width")
        self.advice = pn.pane.Markdown("", sizing_mode="stretch_width")
        self.apply_btn = pn.widgets.Button(name="按建议修改并重跑", button_type="primary")
        self.params_btn = pn.widgets.Button(name="改其他参数…")
        self.help_btn = pn.widgets.Button(name="问 AI 助手")
        self.traceback = pn.pane.HTML("", sizing_mode="stretch_width")
        self.tb_card = pn.Card(self.traceback, title="完整报错", collapsed=True)

        self.apply_btn.on_click(
            lambda event: self._apply_fn(self._changes, self._failure.stage, self._failure.probe)
        )
        self.params_btn.on_click(lambda event: open_params_fn())
        self.help_btn.on_click(lambda event: help_fn())

    def load(self, output_dir: str | Path, stage: str) -> bool:
        """Show the failure of *stage*; returns False when the stage did not fail."""
        root = Path(str(output_dir))
        failure = _find_failure(root, stage)
        self._failure = failure
        if failure is None:
            return False
        tb = _find_traceback(root, stage, failure.probe)
        result = Classifier.classify(RuntimeError(failure.error), tb)
        self._changes = Classifier.suggest_changes(
            result,
            self._state.pipeline_config,
            self._state.sorting_config,
            min_batch_size=self._min_batch_size,
        )
        reason = _REASONS.get(result.error_class)
        who = f"{failure.probe} 的 " if failure.probe else ""
        title = f"#### {who}{stage} 因 {reason}停止" if reason else f"#### {who}{stage} 出错"

        others = self._other_probes(root, stage, failure.probe)
        if others:
            title += "\n\n" + "；".join(f"{p} 已完成，结果保留，不受影响" for p in others) + "。"
        self.title.object = title

        lines = [
            f"**可能原因：** {html.escape(failure.error.splitlines()[0] if failure.error else '—')}"
        ]
        if self._changes:
            parts = [
                f"`{key.rsplit('.', 1)[-1]}` {self._current_value(key)} → {value}"
                for key, value in self._changes
            ]
            lines.append("**建议：** 把 " + "，".join(parts) + "。")

        elif result.error_class in _ADVICE:
            lines.append("**建议：** " + _ADVICE[result.error_class])
        else:
            lines.append("**建议：** 没有已知的自动修改。可以查看完整报错，或问 AI 助手。")
        self.advice.object = "\n\n".join(lines)

        self.apply_btn.visible = bool(self._changes)
        self.apply_btn.name = "按建议修改并重跑" + (f" {failure.probe}" if failure.probe else "")
        self.traceback.object = (
            f"<pre style='white-space:pre-wrap;font-size:12px'>{html.escape(tb)}</pre>"
            if tb
            else "日志中没有记录 traceback。"
        )
        return True

    def _current_value(self, key: str):
        st = self._state
        obj = (
            st.sorting_config
            if key.startswith(("sorter.", "analyzer.", "mode"))
            else st.pipeline_config
        )
        for part in key.split("."):
            obj = getattr(obj, part, None)
        return obj

    def _other_probes(self, root: Path, stage: str, failed_probe: str | None) -> list[str]:
        if failed_probe is None:
            return []
        done = []
        for probe in sorted((self._state.probe_plan or {}).keys()):
            if probe == failed_probe:
                continue
            try:
                data = json.loads(
                    (root / "checkpoints" / f"{stage}_{probe}.json").read_text("utf-8")
                )
            except (OSError, ValueError):
                continue
            if data.get("status") == "completed":
                done.append(probe)
        return done

    def panel(self) -> pn.viewable.Viewable:
        """Return the failure layout."""
        return pn.Column(
            self.title,
            self.advice,
            pn.Row(self.apply_btn, self.params_btn, self.help_btn),
            self.tb_card,
            styles={"border": "1px solid #F0C9C4", "border-radius": "10px", "padding": "8px"},
            sizing_mode="stretch_width",
        )
