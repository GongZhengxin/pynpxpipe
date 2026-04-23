"""ui/components/browsable_input.py — TextInput + Browse button + FileSelector.

A reusable path-input widget that combines:
  - A TextInput for typing/pasting a path
  - A Browse button that toggles a Panel FileSelector
  - When the user selects a path in the FileSelector, it is written to the
    TextInput and the FileSelector is collapsed.

Usage in forms::

    from pynpxpipe.ui.components.browsable_input import BrowsableInput

    self.data_dir_input = BrowsableInput(
        name="Data Directory",
        placeholder="/path/to/experiment",
        file_pattern="*",
        only_files=False,
        root_directory="/some/root",
    )

    # Read / write the current path:
    current = self.data_dir_input.value
    self.data_dir_input.value = "/new/path"

    # Watch for changes (delegates to the inner TextInput's param):
    self.data_dir_input.text_input.param.watch(callback, "value")

    # Embed in a layout:
    pn.Column(self.data_dir_input.panel(), ...)
"""

from __future__ import annotations

import os
import platform
import string
from pathlib import Path

import panel as pn

# Default starting directory for the FileSelector.
# Components are in src/pynpxpipe/ui/components/, so parents[4] is the
# project root (F:/tools/pynpxpipe).
_DEFAULT_ROOT: Path = Path(__file__).resolve().parents[4]


def _detect_drives() -> list[str]:
    """Return available filesystem roots.

    On Windows: scans A-Z for existing drive letters (e.g. ``["C:\\\\", "D:\\\\"]``).
    On other platforms: returns ``["/"]``.
    """
    if platform.system() != "Windows":
        return ["/"]
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


# ---------------------------------------------------------------------------
# Workaround for Panel FileSelector bug on Windows.
#
# Panel's BaseFileNavigator._go_up splits the path by os.sep and joins all
# but the last element.  On Windows this turns "F:\tools" into "F:" (a
# *relative* path meaning "CWD on drive F") instead of the drive root "F:\".
#
# We patch at the CLASS level so that the _up button callback (bound during
# __init__) picks up the fix via normal method resolution.
# ---------------------------------------------------------------------------
if platform.system() == "Windows":

    def _fixed_go_up(self, event=None):  # noqa: ANN001
        path = self._cwd.split(os.sep)
        new_dir = os.sep.join(path[:-1]) or os.sep
        # "F:" -> "F:\" — bare drive letter is relative on Windows
        if len(new_dir) == 2 and new_dir[1] == ":":
            new_dir += os.sep
        self.directory = new_dir
        self._update_files(True)

    for _cls in pn.widgets.FileSelector.__mro__:
        if "_go_up" in _cls.__dict__:
            _cls._go_up = _fixed_go_up
            break


class BrowsableInput:
    """Path input widget with an integrated file-system browser.

    Args:
        name: Label shown on the TextInput.
        placeholder: Placeholder text shown when TextInput is empty.
        file_pattern: Glob pattern for the FileSelector (e.g. ``"*.bhv2"``).
        only_files: If ``True``, the FileSelector restricts selection to files
            only.  If ``False`` (default), directories can also be selected.
        root_directory: Starting directory for the FileSelector.  Defaults to
            the pynpxpipe project root.
    """

    def __init__(
        self,
        name: str,
        placeholder: str = "",
        file_pattern: str = "*",
        only_files: bool = False,
        root_directory: str | Path | None = None,
    ) -> None:
        root = str(root_directory) if root_directory is not None else str(_DEFAULT_ROOT)
        initial_drive = str(Path(root).anchor)

        self.text_input = pn.widgets.TextInput(name=name, placeholder=placeholder)
        self.browse_btn = pn.widgets.Button(name="Browse", button_type="default", width=90)
        self.file_selector = pn.widgets.FileSelector(
            directory=root,
            root_directory=initial_drive,
            file_pattern=file_pattern,
            only_files=only_files,
            visible=False,
        )

        # Drive selector — only shown when multiple drives are available (Windows)
        drives = _detect_drives()
        if len(drives) > 1:
            self.drive_select: pn.widgets.Select | None = pn.widgets.Select(
                name="Drive",
                options=drives,
                value=initial_drive,
                width=80,
            )
            self.drive_select.param.watch(self._on_drive_change, "value")
        else:
            self.drive_select = None

        # Stable panel layout (cached so visibility is shared across callers)
        header_widgets = [self.text_input, self.browse_btn]
        if self.drive_select is not None:
            header_widgets.insert(0, self.drive_select)
        self._panel = pn.Column(
            pn.Row(*header_widgets),
            self.file_selector,
        )

        self.browse_btn.on_click(self._on_browse_click)
        self.file_selector.param.watch(self._on_file_selected, "value")

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def value(self) -> str:
        """Current path string (reads TextInput.value)."""
        return self.text_input.value

    @value.setter
    def value(self, v: str) -> None:
        """Set the path string (writes to TextInput.value, triggers watchers)."""
        self.text_input.value = v

    @property
    def visible(self) -> bool:
        """Whether the entire widget (TextInput + Browse + FileSelector) is visible."""
        return self._panel.visible

    @visible.setter
    def visible(self, v: bool) -> None:
        self._panel.visible = v

    # ── Event handlers ───────────────────────────────────────────────────────

    def _on_browse_click(self, event) -> None:  # noqa: ANN001
        self.file_selector.visible = not self.file_selector.visible

    def _on_drive_change(self, event) -> None:  # noqa: ANN001
        """Switch FileSelector to the selected drive root by recreating it."""
        drive = event.new
        new_fs = pn.widgets.FileSelector(
            directory=drive,
            root_directory=drive,
            file_pattern=self.file_selector.file_pattern,
            only_files=self.file_selector.only_files,
            visible=self.file_selector.visible,
        )
        new_fs.param.watch(self._on_file_selected, "value")
        self._panel.objects[1] = new_fs
        self.file_selector = new_fs

    def _on_file_selected(self, event) -> None:  # noqa: ANN001
        selection = event.new
        if not selection:
            return
        chosen = selection[0] if isinstance(selection, list) else selection
        self.text_input.value = str(chosen)
        self.file_selector.visible = False

    # ── Layout ───────────────────────────────────────────────────────────────

    def panel(self) -> pn.viewable.Viewable:
        """Return the Panel layout for embedding in a parent component."""
        return self._panel
