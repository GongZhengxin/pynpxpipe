"""Resolve MonkeyLogic DatasetName paths to a stim_index → filename map.

Takes ``UserVars.DatasetName`` (typically a Windows absolute path stored in
the BHV2 file) plus optional user-configured image vault roots, locates the
real tsv on the current machine, and parses it into a 1-based integer keyed
mapping aligned with ``UserVars.Current_Image_Train``.

This module is pure I/O. It has no dependency on session / NWB / stage
layers so it can be mocked independently from both ``BHV2Parser`` and
``NWBWriter.add_trials``.

References:
  docs/specs/stim_resolver.md
"""

from __future__ import annotations

import logging
from pathlib import Path, PureWindowsPath

import pandas as pd

logger = logging.getLogger(__name__)


def resolve_dataset_tsv(
    dataset_name: str | None,
    image_vault_paths: list[Path] | None = None,
) -> tuple[Path | None, str]:
    """Resolve a BHV2 DatasetName to an accessible tsv path on this machine.

    Attempts a direct ``Path.exists()`` check first; if that fails, falls
    back to ``rglob`` under each provided image vault root. Windows-style
    backslash paths are normalized via ``PureWindowsPath`` before probing.

    Args:
        dataset_name: Raw ``UserVars.DatasetName`` string from the BHV2
            file. Can be a Windows absolute path (``C:\\...\\x.tsv``), a
            POSIX path, ``None``, or empty / whitespace-only.
        image_vault_paths: Optional list of directory roots to search
            recursively when the direct path is unreachable. ``None`` or an
            empty list disables the fallback.

    Returns:
        Tuple of ``(resolved_path, source_tag)``.

        ``source_tag`` is one of:

        - ``"direct"`` — ``dataset_name`` itself exists as a file.
        - ``"vault:<path>"`` — found exactly one match under ``<path>``.
        - ``"vault:<path>(multi)"`` — multiple matches; first returned
          and a WARN is logged listing all hits.
        - ``"vault_miss"`` — direct failed and vault search found nothing.
        - ``"no_dataset_name"`` — ``dataset_name`` is ``None`` or blank.

        ``resolved_path`` is an absolute :class:`~pathlib.Path` when
        ``source_tag`` starts with ``"direct"`` or ``"vault:"``, otherwise
        ``None``.
    """
    if dataset_name is None or dataset_name.strip() == "":
        return None, "no_dataset_name"

    if "\\" in dataset_name:
        raw = Path(PureWindowsPath(dataset_name).as_posix())
    else:
        raw = Path(dataset_name)

    if raw.exists() and raw.is_file():
        return raw.resolve(), "direct"

    tsv_name = raw.name

    if not image_vault_paths:
        return None, "vault_miss"

    vault_hits: list[tuple[Path, list[Path]]] = []
    for vault in image_vault_paths:
        if not vault.exists():
            logger.debug("Vault path does not exist, skipping: %s", vault)
            continue
        hits = [p for p in sorted(vault.rglob(tsv_name)) if p.is_file()]
        if hits:
            vault_hits.append((vault, hits))

    if not vault_hits:
        return None, "vault_miss"

    total_hits: list[Path] = [h for _, hs in vault_hits for h in hs]
    first_vault, first_hits = vault_hits[0]
    first_hit = first_hits[0]

    if len(total_hits) == 1:
        return first_hit.resolve(), f"vault:{first_vault}"

    logger.warning(
        "Multiple vault hits for %s (%d): %s",
        tsv_name,
        len(total_hits),
        [str(p) for p in total_hits],
    )
    return first_hit.resolve(), f"vault:{first_vault}(multi)"


def load_stim_map(tsv_path: Path) -> dict[int, str]:
    """Parse a stim tsv into a 1-based stim_index → FileName mapping.

    Reads the tsv with ``dtype=str`` and ``keep_default_na=False`` to
    preserve filenames verbatim (no NaN coercion, no numeric parsing). The
    ``FileName`` column is mandatory; all other columns are discarded.

    Args:
        tsv_path: Path to a tab-separated stim index table. Must contain
            a header row with at least a ``FileName`` column (exact, case
            sensitive).

    Returns:
        Mapping of 1-based row number to the corresponding ``FileName``
        cell. An empty tsv (header only) returns an empty dict.

    Raises:
        ValueError: If the ``FileName`` column is missing from the header.
    """
    df = pd.read_csv(tsv_path, sep="\t", dtype=str, keep_default_na=False)
    if "FileName" not in df.columns:
        raise ValueError(f"{tsv_path}: missing FileName column")
    return {i + 1: name for i, name in enumerate(df["FileName"].tolist())}
