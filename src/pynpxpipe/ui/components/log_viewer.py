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
        """Update the display pane from the current buffer contents."""
        if not self.buffer:
            self.display.object = _PLACEHOLDER
            return

        lines_html = []
        for line in self.buffer:
            escaped = html.escape(line)
            # Highlight ERROR/CRITICAL lines
            if "ERROR" in line or "CRITICAL" in line:
                lines_html.append(f'<span style="color: #f44;">{escaped}</span>')
            elif "WARNING" in line:
                lines_html.append(f'<span style="color: #fa0;">{escaped}</span>')
            else:
                lines_html.append(escaped)

        # Auto-scroll: img onerror executes even via innerHTML updates
        _scroll_js = "this.parentElement.scrollTop=this.parentElement.scrollHeight;this.remove();"
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
            pn.pane.Markdown("### Log"),
            self.display,
            sizing_mode="stretch_width",
        )
