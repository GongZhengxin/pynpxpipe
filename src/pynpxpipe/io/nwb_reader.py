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


@dataclass(frozen=True)
class NWBSortingBundle:
    """Per-probe SpikeInterface sorting reconstructed from NWB units."""

    probe_id: str
    sorting: object
    units: pd.DataFrame
    sampling_frequency: float


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

    def load_sortings(
        self,
        sampling_frequency: float | None = None,
    ) -> dict[str, NWBSortingBundle]:
        """Load per-probe SpikeInterface ``NumpySorting`` objects from NWB units.

        Args:
            sampling_frequency: Optional frequency used to convert seconds to
                sample indices. If omitted, each probe's AP acquisition rate is
                read from ``ElectricalSeriesAP_{probe_id}``.

        Returns:
            Mapping of probe id to sorting bundle.

        Raises:
            NWBInputError: If sampling frequency cannot be determined.
        """
        import spikeinterface.core as si

        units = self.load_units()
        ap_rates = self._ap_sampling_frequencies()
        bundles: dict[str, NWBSortingBundle] = {}
        for probe_id, probe_units in units.groupby("probe_id", sort=True):
            fs = (
                float(sampling_frequency)
                if sampling_frequency is not None
                else ap_rates.get(probe_id)
            )
            if fs is None:
                raise NWBInputError(
                    "Cannot build sorting for "
                    f"{probe_id}: sampling_frequency was not provided and "
                    f"ElectricalSeriesAP_{probe_id} is absent or lacks rate"
                )
            unit_dict = {}
            for row in probe_units.itertuples(index=False):
                spike_times = np.asarray(row.spike_times, dtype=float)
                unit_dict[int(row.unit_id)] = np.rint(spike_times * fs).astype(np.int64)

            sorting = si.NumpySorting.from_unit_dict([unit_dict], sampling_frequency=fs)
            self._attach_sorting_properties(sorting, probe_units)
            bundles[str(probe_id)] = NWBSortingBundle(
                probe_id=str(probe_id),
                sorting=sorting,
                units=probe_units.reset_index(drop=True),
                sampling_frequency=fs,
            )
        return bundles

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
            if not summary.has_units or not summary.has_trials or summary.n_trials == 0:
                raise NWBInputError(
                    "postprocess rerun requires /units and trials; this NWB is incomplete"
                )
            self.load_units()
            return
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

    def _ap_sampling_frequencies(self) -> dict[str, float]:
        self._validate_path()
        rates: dict[str, float] = {}
        try:
            with NWBHDF5IO(self.nwb_path, "r") as io:
                nwbfile = io.read()
                for name, series in nwbfile.acquisition.items():
                    if name.startswith("ElectricalSeriesAP_"):
                        rate = getattr(series, "rate", None)
                        if rate is not None:
                            rates[name.removeprefix("ElectricalSeriesAP_")] = float(rate)
        except Exception as exc:  # noqa: BLE001
            raise NWBInputError(
                f"Failed to inspect AP sampling frequencies in {self.nwb_path}: {exc}"
            ) from exc
        return rates

    @staticmethod
    def _attach_sorting_properties(sorting, probe_units: pd.DataFrame) -> None:  # noqa: ANN001
        skip = {"unit_id", "spike_times"}
        for column in probe_units.columns:
            if column in skip:
                continue
            values = probe_units[column].map(_decode_scalar).to_numpy()
            try:
                sorting.set_property(column, values)
            except Exception as exc:  # noqa: BLE001
                raise NWBInputError(f"Failed to attach sorting property {column!r}: {exc}") from exc

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
