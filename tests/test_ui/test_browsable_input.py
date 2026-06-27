"""Tests for ui/components/browsable_input.py — BrowsableInput reusable component.

Scenarios:
  1. Is a Panel Viewable
  2. Exposes text_input (TextInput), browse_btn (Button), file_selector (FileSelector)
  3. FileSelector is initially hidden
  4. Browse button click shows the FileSelector
  5. Browse button click again hides the FileSelector (toggle)
  6. FileSelector value change fills text_input with selected path
  7. FileSelector value change hides the FileSelector
  8. Empty selection does not update text_input
  9. .value property reads text_input.value
 10. .value setter updates text_input.value
 11. file_pattern is passed through to FileSelector
 12. only_files is passed through to FileSelector
 13. .value setter change triggers param watchers on text_input
"""

from __future__ import annotations

import panel as pn
import pytest

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def bi(tmp_path):
    """BrowsableInput with a safe root_directory for tests."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput

    return BrowsableInput(name="Test Input", root_directory=str(tmp_path))


# ---------------------------------------------------------------------------
# 1-5: Construction and browse-toggle
# ---------------------------------------------------------------------------


def test_browsable_input_is_viewable(bi):
    """panel() returns a Panel Viewable."""
    assert isinstance(bi.panel(), pn.viewable.Viewable)


def test_browsable_input_has_text_input(bi):
    """Has text_input attribute that is a TextInput widget."""
    assert isinstance(bi.text_input, pn.widgets.TextInput)


def test_browsable_input_has_browse_btn(bi):
    """Has browse_btn attribute that is a Button widget."""
    assert isinstance(bi.browse_btn, pn.widgets.Button)


def test_browsable_input_has_file_selector(bi):
    """Has file_selector attribute that is a FileSelector widget."""
    assert isinstance(bi.file_selector, pn.widgets.FileSelector)


def test_browsable_input_file_selector_initially_hidden(bi):
    """FileSelector.visible is False on construction."""
    assert bi.file_selector.visible is False


def test_browsable_input_browse_btn_shows_file_selector(bi):
    """Clicking browse_btn once makes FileSelector visible."""
    bi.browse_btn.clicks += 1
    assert bi.file_selector.visible is True


def test_browsable_input_browse_btn_toggles_file_selector(bi):
    """Clicking browse_btn twice restores FileSelector to hidden."""
    bi.browse_btn.clicks += 1
    bi.browse_btn.clicks += 1
    assert bi.file_selector.visible is False


# ---------------------------------------------------------------------------
# 6-8: FileSelector value → text_input
# ---------------------------------------------------------------------------


def test_browsable_input_file_selection_fills_text_input(tmp_path):
    """Setting file_selector.value fills text_input with first selected path."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput

    bi = BrowsableInput(name="Test", root_directory=str(tmp_path))
    chosen = tmp_path / "session.bhv2"
    chosen.write_text("")

    bi.file_selector.value = [str(chosen)]
    assert bi.text_input.value == str(chosen)


def test_browsable_input_file_selection_hides_file_selector(tmp_path):
    """Setting file_selector.value hides the FileSelector."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput

    bi = BrowsableInput(name="Test", root_directory=str(tmp_path))
    chosen = tmp_path / "data.yaml"
    chosen.write_text("")

    bi.browse_btn.clicks += 1  # open it first
    bi.file_selector.value = [str(chosen)]
    assert bi.file_selector.visible is False


def test_browsable_input_empty_selection_does_not_update(tmp_path):
    """Setting file_selector.value to [] leaves text_input unchanged."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput

    bi = BrowsableInput(name="Test", root_directory=str(tmp_path))
    bi.text_input.value = "/original/path"
    bi.file_selector.value = []
    assert bi.text_input.value == "/original/path"


# ---------------------------------------------------------------------------
# 9-10: value property
# ---------------------------------------------------------------------------


def test_browsable_input_value_property_returns_text_input_value(bi):
    """.value returns the current text_input.value."""
    bi.text_input.value = "/some/path"
    assert bi.value == "/some/path"


def test_browsable_input_value_setter_updates_text_input(bi):
    """Setting .value updates text_input.value."""
    bi.value = "/other/path"
    assert bi.text_input.value == "/other/path"


# ---------------------------------------------------------------------------
# 11-12: Constructor params passed to FileSelector
# ---------------------------------------------------------------------------


def test_browsable_input_file_pattern_passed_to_selector(tmp_path):
    """file_pattern is passed to FileSelector."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput

    bi = BrowsableInput(name="Test", file_pattern="*.bhv2", root_directory=str(tmp_path))
    assert bi.file_selector.file_pattern == "*.bhv2"


def test_browsable_input_only_files_passed_to_selector(tmp_path):
    """only_files=True is passed to FileSelector."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput

    bi = BrowsableInput(name="Test", only_files=True, root_directory=str(tmp_path))
    assert bi.file_selector.only_files is True


# ---------------------------------------------------------------------------
# 13: value setter triggers text_input watchers
# ---------------------------------------------------------------------------


def test_browsable_input_value_setter_triggers_text_input_watchers(tmp_path):
    """Setting .value propagates to watchers registered on text_input.param."""
    from pynpxpipe.ui.components.browsable_input import BrowsableInput

    bi = BrowsableInput(name="Test", root_directory=str(tmp_path))

    received: list[str] = []

    def on_change(event):
        received.append(event.new)

    bi.text_input.param.watch(on_change, "value")
    bi.value = "/triggered/path"

    assert received == ["/triggered/path"]


# ---------------------------------------------------------------------------
# 14: Windows multi-drive switch (drive_select + _on_drive_change)
#
# Exercised on Linux by patching _detect_drives to report >1 drive so the
# drive_select dropdown is created. Regression for the in-place
# `self._panel.objects[1] = new_fs` mutation, which did NOT trigger a Panel
# re-render — so switching the Drive dropdown silently did nothing on Windows.
# ---------------------------------------------------------------------------


class TestDriveSwitch:
    def test_drive_change_remounts_file_selector_and_rerenders(self, tmp_path, monkeypatch):
        from pynpxpipe.ui.components import browsable_input as bi_mod

        sub = tmp_path / "drive_e"
        sub.mkdir()
        # "/" matches the anchor of root_directory=tmp_path; second entry makes len>1.
        monkeypatch.setattr(bi_mod, "_detect_drives", lambda: ["/", str(sub)])

        bi = bi_mod.BrowsableInput(name="x", root_directory=str(tmp_path))
        assert bi.drive_select is not None  # multi-drive → dropdown created

        fired: list[str] = []
        bi._panel.param.watch(lambda e: fired.append(e.name), "objects")

        class _Ev:
            new = str(sub)

        bi._on_drive_change(_Ev())

        # The fix uses Panel __setitem__ (reassigns `objects` → re-render fires).
        # The buggy `objects[1] = ...` mutates in place and leaves `fired` empty.
        assert fired, "drive switch must trigger a _panel re-render"
        assert bi.file_selector is bi._panel[1]
        assert str(sub) in str(bi.file_selector.directory)
