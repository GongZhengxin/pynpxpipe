"""ui/components/log_viewer.py — Real-time log display panel.

Uses a bounded deque to buffer log lines and a Panel HTML pane for display.
Provides a structlog processor that appends formatted entries to the buffer.
"""

from __future__ import annotations

import html
from collections import deque

import panel as pn

_PLACEHOLDER = '<span style="color: #888;">Waiting for log output...</span>'


class LogViewer:
    """Deque-buffered, structlog-compatible log display.

    Args:
        maxlen: Maximum number of log lines to retain in the buffer.
    """

    def __init__(self, maxlen: int = 500) -> None:
        self.buffer: deque[str] = deque(maxlen=maxlen)
        self.display = pn.pane.HTML(
            _PLACEHOLDER,
            styles={
                "font-family": "monospace",
                "font-size": "12px",
                "overflow-y": "auto",
                "max-height": "400px",
                "background": "#1e1e1e",
                "color": "#d4d4d4",
                "padding": "8px",
                "border-radius": "4px",
            },
            sizing_mode="stretch_width",
        )
        # Filters (ui_redesign P1-5): level, current stage only, text search, autoscroll.
        self.current_stage = ""
        self.level = pn.widgets.RadioButtonGroup(
            options={"全部": "all", "警告 0": "warn", "错误 0": "error"},
            value="all",
            button_type="light",
        )
        self.stage_only = pn.widgets.Checkbox(name="仅本阶段", value=False)
        self.search = pn.widgets.TextInput(placeholder="搜索日志", width=180)
        self.autoscroll = pn.widgets.Checkbox(name="自动滚动", value=True)
        for widget in (self.level, self.stage_only, self.search, self.autoscroll):
            widget.param.watch(lambda event: self.refresh(), "value")

    @staticmethod
    def _is_error(line: str) -> bool:
        return "ERROR" in line or "CRITICAL" in line

    @staticmethod
    def _is_warning(line: str) -> bool:
        return "WARNING" in line or " WARN " in line

    def _visible(self, line: str) -> bool:
        if self.level.value == "error" and not self._is_error(line):
            return False
        if self.level.value == "warn" and not self._is_warning(line):
            return False
        if self.stage_only.value and self.current_stage and self.current_stage not in line:
            return False
        query = (self.search.value or "").strip().lower()
        return not query or query in line.lower()

    def append(self, line: str) -> None:
        """Add a log line to the buffer.

        Args:
            line: Pre-formatted log line string.
        """
        self.buffer.append(line)

    def replace_last(self, line: str) -> None:
        """Replace the most recent line in the buffer (for tqdm-style in-place updates).

        Args:
            line: New content to overwrite the last buffer entry.
        """
        if self.buffer:
            self.buffer[-1] = line
        else:
            self.buffer.append(line)

    def refresh(self) -> None:
        """Update the display pane from the current buffer contents and filters."""
        lines = list(self.buffer)
        n_warn = sum(self._is_warning(line) for line in lines)
        n_err = sum(self._is_error(line) for line in lines)
        options = {"全部": "all", f"警告 {n_warn}": "warn", f"错误 {n_err}": "error"}
        if list(self.level.options) != list(options):
            self.level.options = options
        if not lines:
            self.display.object = _PLACEHOLDER
            return

        lines_html = []
        for line in lines:
            if not self._visible(line):
                continue
            escaped = html.escape(line)
            # Highlight ERROR/CRITICAL lines
            if self._is_error(line):
                lines_html.append(f'<span style="color: #f44;">{escaped}</span>')
            elif self._is_warning(line):
                lines_html.append(f'<span style="color: #fa0;">{escaped}</span>')
            else:
                lines_html.append(escaped)

        scroll_tag = ""
        if self.autoscroll.value:
            # Auto-scroll: img onerror executes even via innerHTML updates
            _scroll_js = (
                "this.parentElement.scrollTop=this.parentElement.scrollHeight;this.remove();"
            )
            scroll_tag = f'<img src="" onerror="{_scroll_js}" style="display:none">'
        self.display.object = "<br>".join(lines_html) + scroll_tag

    def get_processor(self):
        """Return a structlog processor that appends to this viewer's buffer.

        The processor formats the event dict as a single-line string and appends
        it. It returns the event_dict unchanged so it can be chained.

        Returns:
            A callable(logger, method_name, event_dict) -> event_dict.
        """

        def processor(logger, method_name, event_dict):
            level = event_dict.get("level", method_name).upper()
            event = event_dict.get("event", "")
            extras = {k: v for k, v in event_dict.items() if k not in ("event", "level")}
            parts = [f"[{level}] {event}"]
            for k, v in extras.items():
                parts.append(f"{k}={v}")
            self.append(" | ".join(parts))
            return event_dict

        return processor

    def panel(self) -> pn.viewable.Viewable:
        """Return the Panel layout for this component."""
        return pn.Column(
            pn.Row(
                pn.pane.Markdown("### 日志"),
                self.level,
                self.stage_only,
                pn.layout.HSpacer(),
                self.search,
                self.autoscroll,
                sizing_mode="stretch_width",
            ),
            self.display,
            sizing_mode="stretch_width",
        )
