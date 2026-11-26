"""ui/components/top_bar.py — Header shell: logo, navigation, machine status, run badge.

ui_redesign.md §4.3 P1-1 replaces the sidebar with this bar. The run badge moved
here from app.py (P0-5).
"""

from __future__ import annotations

import html
from collections.abc import Callable
from pathlib import Path

import panel as pn

from pynpxpipe.ui.router import Router
from pynpxpipe.ui.state import AppState

# Header badge per run status: (label, text colour, background) — docs/design/ui_redesign/README.md.
_STATUS_BADGES: dict[str, tuple[str, str, str]] = {
    "idle": ("空闲", "#5B606B", "#EEEEEA"),
    "running": ("运行中", "#0B6E8E", "#E3F0F5"),
    "checking_export": ("检查导出", "#0B6E8E", "#E3F0F5"),
    "exporting": ("导出中", "#0B6E8E", "#E3F0F5"),
    "completed": ("已完成", "#2E8B57", "#E4F2E9"),
    "failed": ("失败", "#C8372D", "#FBE6E4"),
}
_BADGE_REASON_CHARS = 80
_NAV = (("sessions", "Sessions"), ("new", "新建"), ("help", "帮助"))
_GPU_VENDOR_PREFIXES = ("NVIDIA GeForce ", "NVIDIA ")


def status_badge_html(run_status: str, error_message: str = "") -> str:
    """Render the run-status badge; failures carry the first error line, truncated."""
    label, color, background = _STATUS_BADGES.get(run_status, (run_status, "#5B606B", "#EEEEEA"))
    if run_status == "failed" and error_message.strip():
        reason = error_message.strip().splitlines()[0]
        if len(reason) > _BADGE_REASON_CHARS:
            reason = reason[: _BADGE_REASON_CHARS - 1] + "…"
        label = f"{label}：{html.escape(reason)}"
    return (
        f'<span style="display:inline-block;padding:4px 12px;border-radius:999px;'
        f'font-size:13px;font-weight:500;color:{color};background:{background}">{label}</span>'
    )


def _fmt_disk(free_gb: float) -> str:
    return f"{free_gb / 1024:.1f} TB" if free_gb >= 1024 else f"{free_gb:.0f} GB"


def machine_status_text(gpu, *, ram_percent: float, disk_free_gb: float) -> str:
    """One-line machine summary, e.g. ``RTX 4090 · 24 GB · RAM 71% · 磁盘 1.2 TB 可用``.

    Args:
        gpu: Object with ``name`` and ``vram_total_gb`` (GPUInfo), or None.
        ram_percent: Used RAM in percent.
        disk_free_gb: Free space on the working volume.
    """
    if gpu is None:
        gpu_text = "无 GPU"
    else:
        name = gpu.name
        for prefix in _GPU_VENDOR_PREFIXES:
            name = name.removeprefix(prefix)
        gpu_text = f"{name} · {gpu.vram_total_gb:.0f} GB"
    return f"{gpu_text} · RAM {ram_percent:.0f}% · 磁盘 {_fmt_disk(disk_free_gb)} 可用"


def _default_machine_text() -> str:
    import psutil

    from pynpxpipe.core.resources import ResourceDetector

    cwd = Path.cwd()
    profile = ResourceDetector.cached_detect(cwd, cwd)  # GPU probe runs once per process
    return machine_status_text(
        profile.primary_gpu,
        ram_percent=psutil.virtual_memory().percent,
        disk_free_gb=psutil.disk_usage(str(cwd)).free / 1024**3,
    )


class TopBar:
    """Header with navigation, machine status and the run-status badge.

    Args:
        state: Shared AppState (run status for the badge).
        router: Router whose view the nav buttons switch.
        machine_fn: Returns the machine status line; failures hide it.
    """

    def __init__(
        self,
        state: AppState,
        router: Router,
        machine_fn: Callable[[], str] | None = None,
    ) -> None:
        self._state = state
        self._router = router
        self._machine_fn = machine_fn or _default_machine_text

        self.logo = pn.pane.HTML(
            '<span style="font-weight:600;font-size:16px">pynpxpipe</span>', margin=(8, 12)
        )
        self.nav_buttons: dict[str, pn.widgets.Button] = {}
        for view, label in _NAV:
            btn = pn.widgets.Button(name=label, button_type="light", width=90)
            btn.on_click(lambda event, v=view: self._router.go(v))
            self.nav_buttons[view] = btn
        self.machine = pn.pane.HTML("", margin=(10, 12), styles={"font-size": "12px"})
        self.status_badge = pn.pane.HTML(status_badge_html(state.run_status), margin=(8, 12))

        router.param.watch(self._on_view, "view")
        state.param.watch(self._on_run_status, ["run_status", "error_message"])
        self._on_view()
        self.refresh_machine()

    def _on_view(self, event=None) -> None:
        for view, btn in self.nav_buttons.items():
            btn.button_type = "primary" if view == self._router.view else "light"

    def _on_run_status(self, event=None) -> None:
        self.status_badge.object = status_badge_html(
            self._state.run_status, self._state.error_message
        )

    def refresh_machine(self) -> None:
        """Re-read machine status (called periodically while a page is open)."""
        try:
            text = self._machine_fn()
        except Exception:  # noqa: BLE001 — status probe must never break the page
            self.machine.visible = False
            return
        self.machine.object = html.escape(text)
        self.machine.visible = True

    def start_polling(self, period_s: float) -> None:
        """Refresh machine status every *period_s* seconds on the current document."""
        pn.state.add_periodic_callback(self.refresh_machine, period=int(period_s * 1000))

    def panel(self) -> pn.Row:
        """Return the header row."""
        # The template title already shows "pynpxpipe"; ``self.logo`` stays for embedding.
        return pn.Row(
            *self.nav_buttons.values(),
            pn.layout.HSpacer(),
            self.machine,
            self.status_badge,
            sizing_mode="stretch_width",
        )
