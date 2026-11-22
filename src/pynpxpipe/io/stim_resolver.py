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

import hashlib
import logging
import re
from pathlib import Path, PureWindowsPath

import pandas as pd

logger = logging.getLogger(__name__)


def resolve_target_stimuli(
    dataset: str | None, roots: list[Path], events: pd.DataFrame, source_id: str
) -> tuple[Path, dict[int, str]]:
    """Identify the target package by both recorded digests, independent of its location."""

    def digest(column: str) -> str:
        values = events[column].unique() if column in events else []
        if len(values) != 1 or not re.fullmatch(r"[0-9a-fA-F]{64}", str(values[0])):
            raise ValueError(f"{source_id}: missing or inconsistent {column} in recorded events")
        return str(values[0]).lower()

    table_hash = digest("stimulus_table_sha256")
    manifest_hash = digest("stimulus_manifest_sha256")
    if not dataset or not dataset.strip():
        raise ValueError(f"{source_id}: BHV2 has no DatasetName for its target events")
    direct = Path(PureWindowsPath(dataset).as_posix())
    roots = [Path(root) for root in roots]

    def candidates():
        yield direct
        for root in roots:
            yield root / direct.name
        for root in roots:
            if root.is_dir():
                yield from root.rglob(direct.name)

    seen, failures = set(), []
    for path in candidates():
        if not path.is_file() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        manifest = path.with_name("manifest.tsv")
        if hashlib.sha256(path.read_bytes()).hexdigest() != table_hash:
            failures.append(f"{path}: table SHA-256 mismatch")
        elif not manifest.is_file():
            failures.append(f"{manifest}: missing")
        elif hashlib.sha256(manifest.read_bytes()).hexdigest() != manifest_hash:
            failures.append(f"{manifest}: manifest SHA-256 mismatch")
        else:
            mapping = load_stim_map(path)
            if not mapping or not events.stim_index.isin(mapping).all():
                raise ValueError(f"{source_id}: stimulus index absent from verified TSV {path}")
            return path.resolve(), mapping
    details = "; ".join(failures) or "no matching filename found"
    raise ValueError(
        f"{source_id}: cannot verify stimulus package for DatasetName={dataset!r}; {details}. "
        f"Vaults: {[str(root) for root in roots]}. Expected {direct.name} SHA-256={table_hash} "
        f"and adjacent manifest.tsv SHA-256={manifest_hash}. "
        "Specify the original package directory with --image-vault."
    )


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
