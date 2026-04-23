"""Tests for io/stim_resolver.py.

Covers spec §8 test list: nine ``resolve_dataset_tsv`` cases plus five
``load_stim_map`` cases.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from pynpxpipe.io.stim_resolver import load_stim_map, resolve_dataset_tsv


def _write_tsv(path: Path, content: str) -> Path:
    """Helper: write utf-8 tsv content at ``path`` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# resolve_dataset_tsv
# ---------------------------------------------------------------------------


def test_direct_hit_posix(tmp_path: Path) -> None:
    """Spec §3: direct POSIX path exists → (path, "direct")."""
    tsv = _write_tsv(tmp_path / "nsd1w.tsv", "FileName\nA.png\n")
    resolved, tag = resolve_dataset_tsv(str(tsv), image_vault_paths=None)
    assert resolved == tsv.resolve()
    assert tag == "direct"


def test_direct_hit_windows_path(tmp_path: Path) -> None:
    """Spec §4 step 2: Windows-style path unreachable, vault fallback wins."""
    vault = tmp_path / "vault"
    actual = _write_tsv(vault / "sub" / "nsd1w.tsv", "FileName\nA.png\n")
    dataset_name = "C:\\fake\\path\\nsd1w.tsv"
    resolved, tag = resolve_dataset_tsv(dataset_name, image_vault_paths=[vault])
    assert resolved == actual.resolve()
    assert tag.startswith("vault:")


def test_none_dataset_name() -> None:
    """Spec §6: None dataset_name → (None, "no_dataset_name")."""
    resolved, tag = resolve_dataset_tsv(None, image_vault_paths=None)
    assert resolved is None
    assert tag == "no_dataset_name"


def test_empty_dataset_name() -> None:
    """Spec §4 step 1: whitespace-only dataset_name → no_dataset_name."""
    resolved, tag = resolve_dataset_tsv("   ", image_vault_paths=None)
    assert resolved is None
    assert tag == "no_dataset_name"


def test_vault_single_hit(tmp_path: Path) -> None:
    """Spec §3: single vault match → source_tag == "vault:<vault>"."""
    vault = tmp_path / "vault"
    actual = _write_tsv(vault / "nested" / "nsd1w.tsv", "FileName\nA.png\n")
    resolved, tag = resolve_dataset_tsv("/missing/nsd1w.tsv", image_vault_paths=[vault])
    assert resolved == actual.resolve()
    assert tag == f"vault:{vault}"


def test_vault_multi_hit_warns(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Spec §3: multiple hits → WARN log, first returned, tag ends with "(multi)"."""
    vault_a = tmp_path / "a"
    vault_b = tmp_path / "b"
    first = _write_tsv(vault_a / "nsd1w.tsv", "FileName\nA.png\n")
    _write_tsv(vault_b / "nsd1w.tsv", "FileName\nB.png\n")
    with caplog.at_level(logging.WARNING, logger="pynpxpipe.io.stim_resolver"):
        resolved, tag = resolve_dataset_tsv(
            "/missing/nsd1w.tsv", image_vault_paths=[vault_a, vault_b]
        )
    assert resolved == first.resolve()
    assert tag.endswith("(multi)")
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warn_records, "expected a WARNING record for multi vault hit"


def test_vault_miss(tmp_path: Path) -> None:
    """Spec §3: no direct, no vault match → (None, "vault_miss")."""
    vault = tmp_path / "vault"
    vault.mkdir()
    resolved, tag = resolve_dataset_tsv("/missing/nsd1w.tsv", image_vault_paths=[vault])
    assert resolved is None
    assert tag == "vault_miss"


def test_vault_nonexistent_dir_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Spec §6: missing vault dir → DEBUG log, continue with remaining vaults."""
    missing_vault = tmp_path / "does_not_exist"
    good_vault = tmp_path / "good"
    actual = _write_tsv(good_vault / "nsd1w.tsv", "FileName\nA.png\n")
    with caplog.at_level(logging.DEBUG, logger="pynpxpipe.io.stim_resolver"):
        resolved, tag = resolve_dataset_tsv(
            "/missing/nsd1w.tsv",
            image_vault_paths=[missing_vault, good_vault],
        )
    assert resolved == actual.resolve()
    assert tag == f"vault:{good_vault}"
    skip_logs = [
        r
        for r in caplog.records
        if r.levelno == logging.DEBUG and str(missing_vault) in r.getMessage()
    ]
    assert skip_logs, "expected a DEBUG skip log for missing vault"


def test_resolved_path_is_absolute(tmp_path: Path) -> None:
    """Spec §4 step 5: resolved paths are always absolute."""
    tsv = _write_tsv(tmp_path / "nsd1w.tsv", "FileName\nA.png\n")
    resolved, _ = resolve_dataset_tsv(str(tsv), image_vault_paths=None)
    assert resolved is not None
    assert resolved.is_absolute()


# ---------------------------------------------------------------------------
# load_stim_map
# ---------------------------------------------------------------------------


def test_roundtrip_small(tmp_path: Path) -> None:
    """Spec §3: 3-row tsv → 1-based dict keyed by row number."""
    tsv = _write_tsv(
        tmp_path / "small.tsv",
        "FileName\tCategory\nA.png\tc1\nB.png\tc2\nC.png\tc1\n",
    )
    assert load_stim_map(tsv) == {1: "A.png", 2: "B.png", 3: "C.png"}


def test_missing_filename_column_raises(tmp_path: Path) -> None:
    """Spec §3: missing FileName header → ValueError."""
    tsv = _write_tsv(tmp_path / "bad.tsv", "Image\tCategory\nA.png\tc1\n")
    with pytest.raises(ValueError, match="missing FileName column"):
        load_stim_map(tsv)


def test_empty_tsv_returns_empty_dict(tmp_path: Path) -> None:
    """Spec §3: header-only tsv → empty dict (legal)."""
    tsv = _write_tsv(tmp_path / "empty.tsv", "FileName\tCategory\n")
    assert load_stim_map(tsv) == {}


def test_filename_with_special_chars(tmp_path: Path) -> None:
    """Spec §3: parentheses / spaces preserved verbatim via dtype=str."""
    tsv = _write_tsv(
        tmp_path / "weird.tsv",
        "FileName\tCategory\nweird name (1).png\tc1\n",
    )
    assert load_stim_map(tsv) == {1: "weird name (1).png"}


def test_extra_columns_ignored(tmp_path: Path) -> None:
    """Spec §3: only FileName retained, extra columns discarded."""
    tsv = _write_tsv(
        tmp_path / "extra.tsv",
        "FileName\tCategory\tNotes\nA.png\tc1\tfoo\nB.png\tc2\tbar\n",
    )
    assert load_stim_map(tsv) == {1: "A.png", 2: "B.png"}
