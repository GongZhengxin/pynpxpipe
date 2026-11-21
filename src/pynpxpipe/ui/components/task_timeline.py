"""Two-track task-window preview on the acquisition timeline."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path

import pandas as pd
import panel as pn
import pyarrow.parquet as pq
from bokeh.models import ColumnDataSource, FixedTicker, HoverTool, Range1d
from bokeh.plotting import figure

from pynpxpipe.core.config import TaskWindowConfig
from pynpxpipe.core.segments import (
    Segment,
    SegmentManifest,
    presented_events,
    select_task_windows,
    window_frames,
)


@dataclass
class SourceTimeline:
    """One reference probe and its complete trials in the source's NIDQ clock."""

    id: str
    start: float
    duration: float
    rate: float
    a: float
    b: float
    nidq_duration: float | None
    intervals: list[tuple[float, float]]
    empty_intervals: list[tuple[float, float]]


@dataclass
class TimelineData:
    """Small, saved alignment artifacts; changing a window never opens a raw stream."""

    sources: list[SourceTimeline]
    trials: pd.DataFrame
    saved: list[Segment]

    @classmethod
    def load(cls, output: Path, manifest: SegmentManifest, summary: dict) -> TimelineData:
        """Load aligned trial boundaries and the clocks used for the formal preview."""
        legacy = "n_empty_trials" not in summary
        trials = pd.read_parquet(
            output / "04_sync" / "full_trials.parquet",
            columns=[
                "source_id",
                "trial_key",
                "start_time",
                "stop_time",
                "source_start_time",
                "source_stop_time",
                *([] if legacy else ["n_presentations"]),
            ],
        )
        if legacy:
            # Historical blue bars are immutable. Derive today's candidate from
            # recorded onsets, never from the old all-trial selection.
            path = output / "04_sync" / "behavior_events.parquet"
            columns = pq.read_schema(path).names
            events = pd.read_parquet(
                path,
                columns=[
                    "trial_key",
                    *(c for c in ("stim_onset_bhv_ms", "stim_onset_nidq_s") if c in columns),
                ],
            )
            counts = presented_events(events).trial_key.value_counts()
            if not counts.index.isin(trials.trial_key).all():
                raise ValueError("刺激事件和 trial 表不匹配。")
            trials["n_presentations"] = trials.trial_key.map(counts).fillna(0).astype(int)
        saved = manifest.for_probe("imec0")
        rates = {seg.source_id: seg.sample_rate for seg in saved}
        sources = []
        for meta in manifest.sources:
            sid = meta["source_id"]
            rows = trials.loc[trials.source_id == sid]
            if len(rows) != meta["n_trials"]:
                raise ValueError(f"{sid}: 完整 trial 表与已保存选区不符")
            if legacy:
                empty = rows.loc[rows.n_presentations == 0]
                empty_intervals = list(
                    zip(empty.source_start_time, empty.source_stop_time, strict=True)
                )
                rows = rows.loc[rows.n_presentations > 0]
            else:
                empty_intervals = meta["empty_trials_nidq_s"]
            ni = meta["nidq_metadata"]
            duration = summary.get("nidq_durations_s", {}).get(sid)
            if duration is None and ni.get("fileSizeBytes"):
                # Pre-timeline outputs already embedded the SpikeGLX header.
                duration = (int(ni["fileSizeBytes"]) // (2 * int(ni["nSavedChans"]))) / float(
                    ni["niSampRate"]
                )
            fit = meta["sync"]["imec0"]
            sources.append(
                SourceTimeline(
                    sid,
                    meta["offset_s"],
                    meta["original_duration_s"],
                    rates[sid]
                    if sid in rates
                    else float(meta["probe_metadata"]["imec0"]["ap"]["imSampRate"]),
                    fit["a"],
                    fit["b"],
                    duration,
                    list(zip(rows.source_start_time, rows.source_stop_time, strict=True)),
                    empty_intervals,
                )
            )
        if len(trials) != sum(s["n_trials"] for s in manifest.sources):
            raise ValueError("完整 trial 表包含未识别的记录")
        return cls(sources, trials.loc[trials.n_presentations > 0], saved)

    def select(self, cfg: TaskWindowConfig) -> list[Segment]:
        """Re-select imec0 AP frames in memory, including NIDQ clipping and join checks."""
        selected = []
        concat = 0
        for src in self.sources:
            n_frames = round(src.duration * src.rate)
            if not cfg.enabled and len(self.sources) == 1:
                # Single-source runs without task selection process the entire AP file.
                return [Segment(src.id, "imec0", 0, n_frames, 0, src.rate, 1.0, src.start)]
            if src.nidq_duration is None:
                raise ValueError(f"{src.id} 缺少原始 NIDQ 时长，无法试算。")
            windows = select_task_windows(
                src.intervals, src.nidq_duration, cfg, empty_trials=src.empty_intervals
            )
            empty_stops = sorted(stop for _, stop in src.empty_intervals) if cfg.enabled else []
            for start, stop in windows:
                lo, hi = window_frames(
                    start, stop, src.rate, n_frames, src.a, src.b, empty_stops=empty_stops
                )
                selected.append(Segment(src.id, "imec0", lo, hi, concat, src.rate, 1.0, src.start))
                concat += hi - lo
        SegmentManifest(selected, cfg.join_guard_s).analysis_ranges("imec0")
        return selected


def _block_bars(segments: list[Segment]) -> dict[str, list]:
    return {
        "source": [s.source_id for s in segments],
        "start": [s.time(s.start_frame) for s in segments],
        "stop": [s.time(s.stop_frame) for s in segments],
        "duration": [s.length / s.sample_rate for s in segments],
    }


class TaskTimeline:
    """A saved selection and a configurable candidate share one zoomable time axis."""

    def __init__(self, controls: list[pn.widgets.Widget] | None = None) -> None:
        self.data: TimelineData | None = None
        self.candidate = ColumnDataSource(_block_bars([]))
        self._revision = 0
        self.stats = pn.pane.Markdown("")
        self.plot = pn.pane.Bokeh(None, sizing_mode="stretch_width")
        self.layout = pn.Column(
            pn.FlexBox(*(controls or []), sizing_mode="stretch_width"),
            self.stats,
            self.plot,
            sizing_mode="stretch_width",
            visible=False,
        )

    def clear(self) -> None:
        """Discard this session's plot and any pending trial-window experiment."""
        self.data = None
        self.layout.visible = False
        self.plot.object = None
        self.stats.object = ""
        self._revision += 1
        self.candidate = ColumnDataSource(_block_bars([]))

    def show(self, data: TimelineData, config: TaskWindowConfig) -> None:
        """Draw interval glyphs once; updating candidates preserves the zoom and trials."""
        self.data = data
        self.candidate = ColumnDataSource(_block_bars([]))
        extent = max(s.start + s.duration for s in data.sources)
        fig = figure(
            height=235,
            sizing_mode="stretch_width",
            x_range=Range1d(0, extent, bounds=(0, extent)),
            y_range=Range1d(-0.48, 1.58),
            tools="xpan,xwheel_zoom,xbox_zoom,reset,save",
            active_drag="xpan",
            active_scroll="xwheel_zoom",
            toolbar_location="above",
            x_axis_label="实验时间（秒，自第一段神经记录开始）",
        )
        fig.toolbar.logo = None
        fig.yaxis.ticker = FixedTicker(ticks=[0, 1])
        fig.yaxis.major_label_overrides = {0: "行为 trial", 1: "神经 AP"}
        fig.yaxis.major_tick_line_color = None
        fig.ygrid.grid_line_color = None
        raw = {
            "source": [s.id for s in data.sources],
            "start": [s.start for s in data.sources],
            "stop": [s.start + s.duration for s in data.sources],
            "duration": [s.duration for s in data.sources],
        }
        bhv = data.trials
        trials = {
            "source": bhv.source_id.tolist(),
            "start": bhv.start_time.tolist(),
            "stop": bhv.stop_time.tolist(),
            "duration": (bhv.stop_time - bhv.start_time).tolist(),
            "trial": bhv.trial_key.tolist(),
            "images": bhv.n_presentations.tolist(),
        }
        for label, source, level, height, color in (
            ("原始记录", raw, 1, 0.78, "#a6afb7"),
            ("已保存", _block_bars(data.saved), 1.17, 0.28, "#2777ab"),
            ("当前试算", self.candidate, 0.83, 0.28, "#db852c"),
            ("有刺激的 trial", trials, 0, 0.48, "#26967c"),
        ):
            renderer = fig.hbar(
                y=level,
                height=height,
                left="start",
                right="stop",
                source=source,
                color=color,
                line_color=None,
                name=label,
                legend_label=label,
            )
            fields = [
                ("区间", label),
                ("记录", "@source"),
                ("起止 (s)", "@start{0.000} ～ @stop{0.000}"),
                ("时长 (s)", "@duration{0.000}"),
            ]
            if label == "有刺激的 trial":
                fields.insert(1, ("Trial", "@trial"))
                fields.insert(2, ("呈现张数", "@images"))
            fig.add_tools(HoverTool(renderers=[renderer], tooltips=fields))
        fig.legend.orientation = "horizontal"
        fig.legend.spacing = 6
        fig.legend.glyph_width = 12
        fig.legend.label_text_font_size = "10px"
        legend = fig.legend[0]
        fig.center.remove(legend)
        fig.add_layout(legend, "below")
        self.update(config)
        self.plot.object = fig
        self.layout.visible = True

    def update(self, config: TaskWindowConfig) -> None:
        """Replace only the candidate spans and totals; never write a checkpoint."""
        self._revision += 1
        render = partial(self._render_candidate, config, self._revision)
        doc = self.candidate.document
        if doc is not None and doc.session_context is not None:
            # Widget events can run without the Bokeh lock. Update the glyphs and
            # the text together on the document that owns this particular plot.
            doc.add_next_tick_callback(render)
        else:
            render()

    def _render_candidate(self, config: TaskWindowConfig, revision: int) -> None:
        if self.data is None or revision != self._revision:
            return
        try:
            blocks = self.data.select(config)
        except ValueError as exc:
            self.candidate.data = _block_bars([])
            self.stats.object = f"**当前参数无法试算：** {exc}（上次正式预览仍保留）"
            return
        self.candidate.data = bars = _block_bars(blocks)
        original = sum(s.duration for s in self.data.sources)
        kept = sum(bars["duration"])
        saved = sum(s.length / s.sample_rate for s in self.data.saved)
        trials = self.data.trials
        trial_seconds = (trials.stop_time - trials.start_time).sum()
        difference = kept - saved
        empty_count = sum(len(s.empty_intervals) for s in self.data.sources)
        change = (
            "与已保存选区时长相同"
            if abs(difference) < 0.05
            else f"比已保存选区{('多' if difference > 0 else '少')} {abs(difference):,.1f} s"
        )
        self.stats.object = (
            f"**当前试算（未写入）**：最大连续空闲 **{config.max_idle_s:g} s**，前 / 后保留 {config.padding_before_s:g} / {config.padding_after_s:g} s。"
            f"{'' if config.enabled else '截取已关闭，'}{len(blocks)} 块，保留 **{kept:,.1f} s**，减少 **{100 * (1 - kept / original):.1f}%**；"
            f"{change}。有刺激的 trial：{len(trials)} 个，共 {trial_seconds:,.1f} s（占原始记录 {100 * trial_seconds / original:.1f}%）；空 trial：{empty_count} 个。"
        )
