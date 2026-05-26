"""Read pynpxpipe-generated NWB files for rerun workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from pynwb import NWBHDF5IO

from pynpxpipe.core.errors import NWBInputError


@dataclass(frozen=True)
class NWBInputSummary:
    """Summary of NWB contents relevant to rerun workflows."""

    nwb_path: Path
    session_id: str
    subject_id: str | None
    probe_ids: tuple[str, ...]
    n_units: int
    n_trials: int
    has_units: bool
    has_trials: bool
    has_sync_tables: bool
    has_pipeline_config: bool
    raw_ap_streams: dict[str, str]
    raw_lf_streams: dict[str, str]
    has_nidq_raw: bool


class NWBLoader:
    """Inspect and load pynpxpipe NWB files without mutating them."""

    def __init__(self, nwb_path: Path) -> None:
        """Store the NWB path for subsequent inspection/loading.

        Args:
            nwb_path: Path to an existing NWB file.
        """
        self.nwb_path = Path(nwb_path)

    def inspect(self) -> NWBInputSummary:
        """Return a lightweight summary without reading raw acquisition arrays.

        Raises:
            NWBInputError: If the file is absent or cannot be opened as NWB.
        """
        self._validate_path()
        try:
            with NWBHDF5IO(self.nwb_path, "r") as io:
                nwbfile = io.read()
                has_units = nwbfile.units is not None
                has_trials = nwbfile.trials is not None
                n_units = len(nwbfile.units.id[:]) if has_units else 0
                n_trials = len(nwbfile.trials.id[:]) if has_trials else 0
                probe_ids = self._probe_ids_from_nwb(nwbfile)
                raw_ap, raw_lf = self._raw_streams_from_nwb(nwbfile)
                scratch = nwbfile.scratch
                subject = nwbfile.subject
                return NWBInputSummary(
                    nwb_path=self.nwb_path,
                    session_id=nwbfile.session_id or "",
                    subject_id=getattr(subject, "subject_id", None),
                    probe_ids=probe_ids,
                    n_units=n_units,
                    n_trials=n_trials,
                    has_units=has_units,
                    has_trials=has_trials,
                    has_sync_tables="sync_tables" in scratch,
                    has_pipeline_config="pipeline_config" in scratch,
                    raw_ap_streams=raw_ap,
                    raw_lf_streams=raw_lf,
                    has_nidq_raw="NIDQ_raw" in nwbfile.acquisition,
                )
        except NWBInputError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise NWBInputError(f"Failed to open NWB file {self.nwb_path}: {exc}") from exc

    def load_units(self) -> pd.DataFrame:
        """Load the NWB units table as a DataFrame for rewrite workflows.

        Returns:
            A DataFrame with ``unit_id`` and ``spike_times`` as ordinary columns.

        Raises:
            NWBInputError: If the units table is absent or missing ``probe_id``.
        """
        self._validate_path()
        try:
            with NWBHDF5IO(self.nwb_path, "r") as io:
                nwbfile = io.read()
                if nwbfile.units is None:
                    raise NWBInputError(f"NWB file has no /units table: {self.nwb_path}")

                units = nwbfile.units.to_dataframe().reset_index(names="unit_id")
        except NWBInputError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise NWBInputError(f"Failed to load /units from {self.nwb_path}: {exc}") from exc

        if "probe_id" not in units.columns:
            raise NWBInputError("NWB /units table is missing required column 'probe_id'")
        if "spike_times" not in units.columns:
            raise NWBInputError("NWB /units table is missing required column 'spike_times'")

        units["probe_id"] = units["probe_id"].map(_decode_scalar)
        units["spike_times"] = units["spike_times"].map(
            lambda value: np.asarray(value, dtype=float)
        )
        if units["probe_id"].isna().any() or (units["probe_id"].astype(str) == "").any():
            raise NWBInputError("NWB /units column 'probe_id' contains empty values")
        return units

    def require_capabilities(self, mode: Literal["rewrite-units", "postprocess", "raw"]) -> None:
        """Validate that the NWB contains inputs required by a rerun mode.

        Raises:
            NWBInputError: If the requested mode is unsupported or lacks inputs.
        """
        if mode == "rewrite-units":
            self.load_units()
            return
        if mode == "postprocess":
            summary = self.inspect()
            if not summary.has_units or not summary.has_trials:
                raise NWBInputError(
                    "postprocess rerun requires /units and trials; this NWB is incomplete"
                )
            raise NWBInputError("postprocess rerun from NWB is not implemented in PR1")
        if mode == "raw":
            summary = self.inspect()
            if not summary.raw_ap_streams:
                raise NWBInputError("raw rerun requires ElectricalSeriesAP_* acquisition streams")
            raise NWBInputError("raw rerun from NWB is not implemented in PR1")
        raise NWBInputError(f"Unsupported NWB rerun mode: {mode!r}")

    def _validate_path(self) -> None:
        if not self.nwb_path.exists():
            raise NWBInputError(f"NWB file not found: {self.nwb_path}")
        if self.nwb_path.suffix.lower() != ".nwb":
            raise NWBInputError(f"Expected a .nwb file: {self.nwb_path}")

    @staticmethod
    def _probe_ids_from_nwb(nwbfile) -> tuple[str, ...]:  # noqa: ANN001
        if nwbfile.units is not None and "probe_id" in nwbfile.units.colnames:
            values = nwbfile.units["probe_id"].data[:]
            return tuple(sorted({_decode_scalar(v) for v in values if _decode_scalar(v)}))

        probe_ids: set[str] = set()
        for name in nwbfile.acquisition:
            if name.startswith("ElectricalSeriesAP_"):
                probe_ids.add(name.removeprefix("ElectricalSeriesAP_"))
            elif name.startswith("ElectricalSeriesLF_"):
                probe_ids.add(name.removeprefix("ElectricalSeriesLF_"))
        return tuple(sorted(probe_ids))

    @staticmethod
    def _raw_streams_from_nwb(nwbfile) -> tuple[dict[str, str], dict[str, str]]:  # noqa: ANN001
        raw_ap: dict[str, str] = {}
        raw_lf: dict[str, str] = {}
        for name in nwbfile.acquisition:
            if name.startswith("ElectricalSeriesAP_"):
                raw_ap[name.removeprefix("ElectricalSeriesAP_")] = name
            elif name.startswith("ElectricalSeriesLF_"):
                raw_lf[name.removeprefix("ElectricalSeriesLF_")] = name
        return raw_ap, raw_lf


def _decode_scalar(value: object) -> object:
    """Decode HDF5 byte strings while leaving other scalars unchanged."""
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value
