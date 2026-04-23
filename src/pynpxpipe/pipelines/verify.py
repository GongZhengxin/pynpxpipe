"""Safe-to-delete verification for raw SpikeGLX bins (E2.3).

Answers "can the raw `.ap.bin` / `.lf.bin` / `.nidq.bin` files be deleted?"
by checking three preconditions in order:

1. ``checkpoints/export.json`` exists, is valid JSON, and carries a non-empty
   ``raw_data_verified_at`` key (set by the export stage only after the
   bit-exact verification scan completes).
2. The NWB file referenced by that checkpoint (``nwb_path``) exists on disk.
3. The NWB file opens cleanly in read mode (HDF5 not corrupted).

The module is CLI-free; ``cli/main.py`` formats the result for the user.
No UI dependencies.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from pynpxpipe.core.session import SessionManager

logger = logging.getLogger(__name__)


# Distinct exit codes so callers (CLI + tests) can disambiguate the failure
# mode without parsing text messages.
EXIT_OK = 0
EXIT_MISSING_VERIFIED_AT = 2
EXIT_MISSING_NWB = 3
EXIT_NWB_CORRUPT = 4
EXIT_MISSING_CHECKPOINT = 5
EXIT_NO_RAW_FILES_FOUND = 6


@dataclass
class VerifySafeResult:
    """Outcome of a safe-to-delete check.

    Attributes:
        safe: True iff all three preconditions passed.
        exit_code: 0 on success, otherwise one of ``EXIT_*`` in this module.
        reason: Human-readable explanation (empty string when ``safe`` is True).
        nwb_path: Path to the NWB referenced by the checkpoint, when resolvable.
        deletable: Paths to the raw .bin/.meta files that are provably
            redundant. Empty when ``safe`` is False.
    """

    safe: bool
    exit_code: int
    reason: str = ""
    nwb_path: Path | None = None
    deletable: list[Path] = field(default_factory=list)


def verify_safe_to_delete(output_dir: Path) -> VerifySafeResult:
    """Check whether the raw SpikeGLX bins for ``output_dir`` can be deleted.

    Args:
        output_dir: Pipeline output directory (contains ``checkpoints/`` and
            ``session.json``).

    Returns:
        A ``VerifySafeResult`` populated with either the list of safe-to-delete
        paths (on success) or a non-zero ``exit_code`` + reason (on failure).
    """
    cp_path = output_dir / "checkpoints" / "export.json"
    if not cp_path.exists():
        return VerifySafeResult(
            safe=False,
            exit_code=EXIT_MISSING_CHECKPOINT,
            reason=f"export checkpoint missing: {cp_path}",
        )

    try:
        cp_data = json.loads(cp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return VerifySafeResult(
            safe=False,
            exit_code=EXIT_MISSING_CHECKPOINT,
            reason=f"export checkpoint unreadable ({cp_path}): {exc}",
        )

    verified_at = cp_data.get("raw_data_verified_at")
    if not verified_at:
        return VerifySafeResult(
            safe=False,
            exit_code=EXIT_MISSING_VERIFIED_AT,
            reason=(
                "export checkpoint has no raw_data_verified_at — raw data has "
                "not been verified bit-exact yet; do not delete"
            ),
        )

    # Resolve the NWB file. Prefer the checkpoint's recorded path (authoritative
    # — the export stage wrote it). Fall back to the canonical SessionID path
    # if the checkpoint predates the nwb_path field.
    nwb_path_str = cp_data.get("nwb_path")
    nwb_path: Path | None = Path(nwb_path_str) if nwb_path_str else None
    if nwb_path is None:
        try:
            session = SessionManager.load(output_dir)
            nwb_path = output_dir / f"{session.session_id.canonical()}.nwb"
        except Exception as exc:
            return VerifySafeResult(
                safe=False,
                exit_code=EXIT_MISSING_NWB,
                reason=f"cannot resolve NWB path from session.json: {exc}",
            )

    if not nwb_path.exists():
        return VerifySafeResult(
            safe=False,
            exit_code=EXIT_MISSING_NWB,
            reason=f"NWB file not found: {nwb_path}",
            nwb_path=nwb_path,
        )

    # Lazy import: pynwb pulls the full scientific stack; keep the module
    # importable from thin contexts (tests, CLI --help) without paying the cost.
    try:
        from pynwb import NWBHDF5IO

        with NWBHDF5IO(str(nwb_path), "r") as io:
            io.read()
    except Exception as exc:
        return VerifySafeResult(
            safe=False,
            exit_code=EXIT_NWB_CORRUPT,
            reason=f"NWB file cannot be opened: {nwb_path}: {exc}",
            nwb_path=nwb_path,
        )

    # All three gates passed — enumerate the raw files that can be reclaimed.
    deletable = _collect_raw_files(output_dir)
    if not deletable:
        # Refuse to claim "safe to delete" when we cannot identify a single raw
        # file to name. Either session.json is broken or the bins have already
        # been removed; in both cases the honest answer is "I can't tell you
        # what's safe" rather than exit 0 with an empty list that looks like
        # success but tells the user nothing actionable.
        return VerifySafeResult(
            safe=False,
            exit_code=EXIT_NO_RAW_FILES_FOUND,
            reason=(
                "NWB is verified but no raw .bin/.meta files were located "
                "(session.json unreadable or bins already removed); refusing "
                "to print an empty safe-to-delete list"
            ),
            nwb_path=nwb_path,
        )
    return VerifySafeResult(
        safe=True,
        exit_code=EXIT_OK,
        reason="",
        nwb_path=nwb_path,
        deletable=deletable,
    )


def _collect_raw_files(output_dir: Path) -> list[Path]:
    """Enumerate .ap.bin/.lf.bin/.nidq.bin + matching .meta files for a session.

    Uses ``session.json`` as the authoritative source of probe paths; if it
    is missing, returns an empty list (the caller has already verified the
    NWB is sound, but we cannot safely claim ownership of arbitrary ``*.bin``
    under ``session_dir`` without a canonical probe list).

    Args:
        output_dir: Pipeline output directory.

    Returns:
        Sorted list of existing .bin/.meta file paths.
    """
    try:
        session = SessionManager.load(output_dir)
    except Exception as exc:
        logger.warning("cannot load session.json for raw-file enumeration: %s", exc)
        return []

    paths: list[Path] = []
    for probe in session.probes:
        for candidate in (probe.ap_bin, probe.ap_meta, probe.lf_bin, probe.lf_meta):
            if candidate is not None and Path(candidate).exists():
                paths.append(Path(candidate))

    # NIDQ lives at session_dir level, discovered by walking the directory.
    session_dir = session.session_dir
    if session_dir.exists():
        for nidq in sorted(session_dir.glob("*.nidq.bin")):
            paths.append(nidq)
        for nidq_meta in sorted(session_dir.glob("*.nidq.meta")):
            paths.append(nidq_meta)

    # Dedupe while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique
