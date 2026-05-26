"""NWB-based rerun workflows for copy-on-write unit table updates."""

from __future__ import annotations

import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import h5py
import numpy as np
import pandas as pd
from pynwb import NWBHDF5IO

from pynpxpipe.core.errors import NWBInputError, NWBRerunError
from pynpxpipe.io.nwb_reader import NWBLoader


@dataclass(frozen=True)
class NWBRerunResult:
    """Result metadata for an NWB rerun workflow."""

    mode: str
    input_nwb: Path
    output_nwb: Path
    report_path: Path
    checkpoint_path: Path
    n_units_before: int
    n_units_after: int


def rerun_from_nwb(
    nwb_path: Path,
    output_dir: Path,
    *,
    mode: Literal["rewrite-units", "postprocess", "raw"] = "rewrite-units",
    unit_updates: Path | pd.DataFrame | None = None,
    version: str | None = None,
    overwrite: bool = False,
) -> NWBRerunResult:
    """Run an NWB-based copy-on-write rerun workflow.

    PR1 implements only ``mode="rewrite-units"``.

    Args:
        nwb_path: Input NWB file. It is never modified.
        output_dir: Rerun output root.
        mode: Rerun mode. Only ``rewrite-units`` is implemented.
        unit_updates: CSV path or DataFrame keyed by ``unit_id``.
        version: Optional version suffix such as ``"v001"``.
        overwrite: Whether an existing output NWB may be overwritten.

    Returns:
        Rerun result metadata.

    Raises:
        NWBInputError: If the input NWB lacks required structures.
        NWBRerunError: If validation or writing fails.
    """
    nwb_path = Path(nwb_path)
    output_dir = Path(output_dir)
    rerun_dir = output_dir / "nwb_rerun"
    checkpoint_dir = rerun_dir / "checkpoints"
    checkpoint_path = checkpoint_dir / "nwb_rerun.json"
    report_path = rerun_dir / "nwb_rerun_report.json"
    output_nwb: Path | None = None

    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    try:
        if mode != "rewrite-units":
            raise NWBRerunError("Only mode='rewrite-units' is implemented in Task 2 PR1")
        if unit_updates is None:
            raise NWBRerunError("unit_updates is required for rewrite-units rerun")

        loader = NWBLoader(nwb_path)
        loader.require_capabilities("rewrite-units")
        original_units = loader.load_units()
        updates = _load_unit_updates(unit_updates)
        rewritten_units = _apply_unit_updates(original_units, updates)

        output_nwb = _choose_output_nwb(
            nwb_path,
            rerun_dir,
            version=version,
            overwrite=overwrite,
        )
        output_nwb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(nwb_path, output_nwb)

        report = {
            "mode": mode,
            "input_nwb": str(nwb_path),
            "output_nwb": str(output_nwb),
            "unit_update_source": str(unit_updates) if isinstance(unit_updates, Path) else None,
            "n_units_before": int(len(original_units)),
            "n_units_after": int(len(rewritten_units)),
            "completed_at": _now_iso(),
        }
        _rewrite_units_table(output_nwb, rewritten_units)
        _write_rerun_scratch_report(output_nwb, report)
        _validate_output_nwb(output_nwb, expected_units=len(rewritten_units))

        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _write_checkpoint(
            checkpoint_path,
            {
                "status": "completed",
                **report,
            },
        )
        return NWBRerunResult(
            mode=mode,
            input_nwb=nwb_path,
            output_nwb=output_nwb,
            report_path=report_path,
            checkpoint_path=checkpoint_path,
            n_units_before=len(original_units),
            n_units_after=len(rewritten_units),
        )
    except (NWBInputError, NWBRerunError) as exc:
        if output_nwb is not None and output_nwb.exists():
            output_nwb.unlink(missing_ok=True)
        _write_checkpoint(
            checkpoint_path,
            {
                "status": "failed",
                "mode": mode,
                "input_nwb": str(nwb_path),
                "error": str(exc),
                "failed_at": _now_iso(),
            },
        )
        raise
    except Exception as exc:  # noqa: BLE001
        if output_nwb is not None and output_nwb.exists():
            output_nwb.unlink(missing_ok=True)
        err = NWBRerunError(f"NWB rerun failed: {exc}")
        _write_checkpoint(
            checkpoint_path,
            {
                "status": "failed",
                "mode": mode,
                "input_nwb": str(nwb_path),
                "error": str(err),
                "failed_at": _now_iso(),
            },
        )
        raise err from exc


def _load_unit_updates(unit_updates: Path | pd.DataFrame) -> pd.DataFrame:
    if isinstance(unit_updates, pd.DataFrame):
        updates = unit_updates.copy()
    else:
        updates = pd.read_csv(unit_updates)

    if "unit_id" not in updates.columns:
        raise NWBRerunError("unit_updates must contain a 'unit_id' column")
    if "spike_times" in updates.columns:
        raise NWBRerunError("rewrite-units does not allow updating spike_times in PR1")
    if updates["unit_id"].duplicated().any():
        raise NWBRerunError("unit_updates contains duplicate unit_id values")
    return updates


def _apply_unit_updates(original_units: pd.DataFrame, updates: pd.DataFrame) -> pd.DataFrame:
    original = original_units.copy()
    original["unit_id"] = original["unit_id"].astype(int)
    updates = updates.copy()
    updates["unit_id"] = updates["unit_id"].astype(int)

    unknown = sorted(set(updates["unit_id"]) - set(original["unit_id"]))
    if unknown:
        raise NWBRerunError(f"Unknown unit_id values in updates: {unknown}")

    merged = original.merge(
        updates,
        on="unit_id",
        how="left",
        suffixes=("", "__update"),
    )
    for column in updates.columns:
        if column in {"unit_id", "keep"}:
            continue
        update_column = f"{column}__update" if column in original.columns else column
        if update_column not in merged.columns:
            continue
        if column not in merged.columns:
            merged[column] = pd.NA
        mask = merged[update_column].notna()
        update_values = merged.loc[mask, update_column]
        original_is_bool = column in original.columns and pd.api.types.is_bool_dtype(
            original[column]
        )
        if original_is_bool:
            update_values = update_values.map(_coerce_bool_value).astype(bool)
        merged.loc[mask, column] = update_values

    if "keep" in merged.columns:
        keep_values = merged["keep"].map(_coerce_keep_value)
        keep_mask = pd.Series(
            [True if value is None else bool(value) for value in keep_values],
            index=merged.index,
        )
        merged = merged.loc[keep_mask].copy()

    drop_cols = [col for col in merged.columns if col.endswith("__update") or col == "keep"]
    return merged.drop(columns=drop_cols).reset_index(drop=True)


def _choose_output_nwb(
    input_nwb: Path,
    rerun_dir: Path,
    *,
    version: str | None,
    overwrite: bool,
) -> Path:
    if version is not None:
        candidate = rerun_dir / f"{input_nwb.stem}_rerun_{version}.nwb"
        if candidate.exists() and not overwrite:
            raise NWBRerunError(f"Output NWB already exists: {candidate}")
        return candidate

    for idx in range(1, 1000):
        candidate = rerun_dir / f"{input_nwb.stem}_rerun_v{idx:03d}.nwb"
        if not candidate.exists() or overwrite:
            return candidate
    raise NWBRerunError("Could not choose an unused rerun version below v1000")


def _rewrite_units_table(nwb_path: Path, units: pd.DataFrame) -> None:
    """Replace the HDF5 /units table in an NWB copy."""
    with h5py.File(nwb_path, "r+") as h5:
        if "units" not in h5:
            raise NWBRerunError(f"NWB file has no /units group: {nwb_path}")
        group = h5["units"]
        group_attrs = dict(group.attrs.items())
        dataset_attrs = {
            name: dict(dataset.attrs.items())
            for name, dataset in group.items()
            if isinstance(dataset, h5py.Dataset)
        }

        for name in list(group.keys()):
            del group[name]

        for key, value in group_attrs.items():
            group.attrs[key] = value

        column_names = [col for col in units.columns if col != "unit_id"]
        ordered = [col for col in column_names if col != "spike_times"]
        if "spike_times" in column_names:
            ordered.append("spike_times")
        group.attrs["colnames"] = np.asarray(ordered, dtype=h5py.string_dtype("utf-8"))

        _create_dataset(
            group,
            "id",
            units["unit_id"].to_numpy(dtype=np.int64),
            dataset_attrs.get("id"),
            default_neurodata_type="ElementIdentifiers",
        )
        for column in ordered:
            if column == "spike_times":
                _create_ragged_dataset(
                    group,
                    "spike_times",
                    units[column],
                    dataset_attrs.get("spike_times"),
                    dataset_attrs.get("spike_times_index"),
                    dtype=float,
                )
            elif _is_ragged_column(units[column]):
                _create_ragged_dataset(
                    group,
                    column,
                    units[column],
                    dataset_attrs.get(column),
                    dataset_attrs.get(f"{column}_index"),
                    dtype=None,
                )
            else:
                _create_dataset(group, column, units[column], dataset_attrs.get(column))


def _create_dataset(
    group: h5py.Group,
    name: str,
    values,
    attrs: dict | None,
    *,
    default_neurodata_type: str = "VectorData",
) -> h5py.Dataset:
    data, dtype = _values_to_hdf5_array(values)
    dataset = group.create_dataset(name, data=data, dtype=dtype)
    _apply_dataset_attrs(
        dataset,
        attrs,
        description=f"NWB rerun column {name}",
        neurodata_type=default_neurodata_type,
    )
    return dataset


def _create_ragged_dataset(
    group: h5py.Group,
    name: str,
    values,
    data_attrs: dict | None,
    index_attrs: dict | None,
    *,
    dtype,
) -> None:
    arrays = [_as_array(value, dtype=dtype) for value in values]
    if arrays:
        flat = np.concatenate(arrays) if sum(len(a) for a in arrays) else np.array([], dtype=dtype)
        index = np.cumsum([len(a) for a in arrays], dtype=np.uint64)
    else:
        flat = np.array([], dtype=dtype)
        index = np.array([], dtype=np.uint64)

    data_ds = group.create_dataset(name, data=flat)
    _apply_dataset_attrs(
        data_ds,
        data_attrs,
        description=f"NWB rerun ragged column {name}",
        neurodata_type="VectorData",
    )
    index_ds = group.create_dataset(f"{name}_index", data=index)
    _apply_dataset_attrs(
        index_ds,
        index_attrs,
        description=f"Index for VectorData '{name}'",
        neurodata_type="VectorIndex",
    )
    index_ds.attrs["target"] = data_ds.ref


def _write_rerun_scratch_report(nwb_path: Path, report: dict) -> None:
    with h5py.File(nwb_path, "r+") as h5:
        scratch = h5.require_group("scratch")
        if "nwb_rerun_report" in scratch:
            del scratch["nwb_rerun_report"]
        dataset = scratch.create_dataset(
            "nwb_rerun_report",
            data=json.dumps(report),
            dtype=h5py.string_dtype("utf-8"),
        )
        dataset.attrs["namespace"] = "core"
        dataset.attrs["neurodata_type"] = "ScratchData"
        dataset.attrs["notes"] = "NWB rerun report JSON"
        dataset.attrs["object_id"] = str(uuid.uuid4())


def _validate_output_nwb(nwb_path: Path, *, expected_units: int) -> None:
    try:
        with NWBHDF5IO(nwb_path, "r") as io:
            nwbfile = io.read()
            actual = len(nwbfile.units.id[:]) if nwbfile.units is not None else 0
            if actual != expected_units:
                raise NWBRerunError(
                    f"Output NWB units row count mismatch: expected {expected_units}, got {actual}"
                )
    except NWBRerunError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise NWBRerunError(f"Output NWB validation failed: {exc}") from exc


def _write_checkpoint(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _apply_dataset_attrs(
    dataset: h5py.Dataset,
    attrs: dict | None,
    *,
    description: str,
    neurodata_type: str,
) -> None:
    if attrs:
        for key, value in attrs.items():
            if key == "target":
                continue
            dataset.attrs[key] = value
    dataset.attrs.setdefault("description", description)
    dataset.attrs.setdefault("namespace", "hdmf-common")
    dataset.attrs.setdefault("neurodata_type", neurodata_type)
    dataset.attrs.setdefault("object_id", str(uuid.uuid4()))


def _values_to_hdf5_array(values) -> tuple[np.ndarray, object | None]:
    series = pd.Series(values).map(_decode_if_bytes)
    if series.dtype == bool:
        return series.to_numpy(dtype=bool), None
    if pd.api.types.is_bool_dtype(series):
        return series.to_numpy(dtype=bool), None
    if pd.api.types.is_numeric_dtype(series):
        return series.to_numpy(), None

    non_null = series.dropna()
    if not non_null.empty and all(isinstance(v, (bool, np.bool_)) for v in non_null):
        return series.fillna(False).to_numpy(dtype=bool), None
    if not non_null.empty:
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.notna().sum() == series.notna().sum():
            return numeric.to_numpy(), None
    strings = series.fillna("").astype(str).to_numpy(dtype=object)
    return strings, h5py.string_dtype("utf-8")


def _is_ragged_column(values) -> bool:
    return any(isinstance(v, (list, tuple, np.ndarray)) for v in values)


def _as_array(value, *, dtype) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return value.astype(dtype) if dtype is not None else value
    if isinstance(value, str) and value.startswith("["):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            value = []
    if value is None or (isinstance(value, float) and np.isnan(value)):
        value = []
    return np.asarray(value, dtype=dtype)


def _decode_if_bytes(value: object) -> object:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _coerce_keep_value(value: object) -> bool | None:
    if pd.isna(value):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise NWBRerunError(f"Invalid keep value: {value!r}")


def _coerce_bool_value(value: object) -> bool:
    keep = _coerce_keep_value(value)
    if keep is None:
        return False
    return keep


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
