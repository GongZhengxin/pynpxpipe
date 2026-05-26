"""NWB-based rerun workflows for copy-on-write unit table updates."""

from __future__ import annotations

import json
import math
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import h5py
import numpy as np
import pandas as pd
import spikeinterface.preprocessing as spp
import spikeinterface.sorters as ss
from pynwb import NWBHDF5IO
from scipy.stats import mannwhitneyu, rankdata

from pynpxpipe.core.config import PipelineConfig, SortingConfig
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
    pipeline_config: PipelineConfig | None = None,
    sorting_config: SortingConfig | None = None,
) -> NWBRerunResult:
    """Run an NWB-based copy-on-write rerun workflow.

    Args:
        nwb_path: Input NWB file. It is never modified.
        output_dir: Rerun output root.
        mode: Rerun mode. ``postprocess`` recomputes lightweight unit metrics.
        unit_updates: CSV path or DataFrame keyed by ``unit_id``.
        version: Optional version suffix such as ``"v001"``.
        overwrite: Whether an existing output NWB may be overwritten.
        pipeline_config: Optional preprocessing config for ``mode="raw"``.
        sorting_config: Optional sorter config for ``mode="raw"``.

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
        loader = NWBLoader(nwb_path)
        extra_report: dict[str, object] = {}
        if mode == "rewrite-units":
            if unit_updates is None:
                raise NWBRerunError("unit_updates is required for rewrite-units rerun")
            loader.require_capabilities("rewrite-units")
            original_units = loader.load_units()
            updates = _load_unit_updates(unit_updates)
            unit_update_source = str(unit_updates) if isinstance(unit_updates, Path) else None
            rewritten_units = _apply_unit_updates(original_units, updates)
        elif mode == "postprocess":
            if unit_updates is not None:
                raise NWBRerunError("unit_updates is not supported for postprocess rerun")
            loader.require_capabilities("postprocess")
            original_units = loader.load_units()
            trials = _load_trials(nwb_path)
            updates = _compute_postprocess_unit_updates(original_units, trials)
            unit_update_source = "computed:postprocess-lite"
            rewritten_units = _apply_unit_updates(original_units, updates)
        elif mode == "raw":
            if unit_updates is not None:
                raise NWBRerunError("unit_updates is not supported for raw rerun")
            loader.require_capabilities("raw")
            original_units = loader.load_units()
            rewritten_units, extra_report = _run_raw_rerun_units(
                loader,
                rerun_dir,
                pipeline_config=pipeline_config,
                sorting_config=sorting_config,
            )
            unit_update_source = "computed:raw-sorter"
        else:
            raise NWBRerunError(f"Unsupported NWB rerun mode: {mode!r}")

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
            "unit_update_source": unit_update_source,
            "n_units_before": int(len(original_units)),
            "n_units_after": int(len(rewritten_units)),
            "completed_at": _now_iso(),
            **extra_report,
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
    updates["__has_update"] = True

    unknown = sorted(set(updates["unit_id"]) - set(original["unit_id"]))
    if unknown:
        raise NWBRerunError(f"Unknown unit_id values in updates: {unknown}")

    merged = original.merge(
        updates,
        on="unit_id",
        how="left",
        suffixes=("", "__update"),
    )
    has_update = merged["__has_update"].eq(True)
    for column in updates.columns:
        if column in {"unit_id", "keep", "__has_update"}:
            continue
        update_column = f"{column}__update" if column in original.columns else column
        if update_column not in merged.columns:
            continue
        if column not in merged.columns:
            merged[column] = pd.NA
        mask = has_update
        update_values = merged.loc[mask, update_column]
        original_is_bool = column in original.columns and pd.api.types.is_bool_dtype(
            original[column]
        )
        if original_is_bool:
            update_values = update_values.map(_coerce_bool_value).astype(bool)
        merged.loc[mask, column] = update_values

    if "keep" in merged.columns:
        keep_values = merged["keep"].where(has_update, pd.NA).map(_coerce_keep_value)
        keep_mask = pd.Series(
            [True if value is None else bool(value) for value in keep_values],
            index=merged.index,
        )
        merged = merged.loc[keep_mask].copy()

    drop_cols = [
        col for col in merged.columns if col.endswith("__update") or col in {"keep", "__has_update"}
    ]
    return merged.drop(columns=drop_cols).reset_index(drop=True)


def _load_trials(nwb_path: Path) -> pd.DataFrame:
    try:
        with NWBHDF5IO(nwb_path, "r") as io:
            nwbfile = io.read()
            if nwbfile.trials is None:
                raise NWBInputError(f"NWB file has no trials table: {nwb_path}")
            trials = nwbfile.trials.to_dataframe().reset_index(names="trial_row")
    except NWBInputError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise NWBInputError(f"Failed to load trials from {nwb_path}: {exc}") from exc

    if trials.empty:
        raise NWBInputError(f"NWB file has no trials rows: {nwb_path}")
    for column in trials.columns:
        if pd.api.types.is_object_dtype(trials[column]):
            trials[column] = trials[column].map(_decode_if_bytes)
    return trials


def _compute_postprocess_unit_updates(
    units: pd.DataFrame,
    trials: pd.DataFrame,
    *,
    pre_s: float = 0.05,
    post_s: float = 0.30,
) -> pd.DataFrame:
    if units.empty:
        raise NWBRerunError("postprocess rerun requires at least one unit")

    rows: list[dict[str, object]] = []
    for probe_id, probe_units in units.groupby("probe_id", sort=True):
        onset_times = _stim_onsets_for_probe(trials, str(probe_id))
        for row in probe_units.itertuples(index=False):
            spike_times = np.asarray(row.spike_times, dtype=float)
            slay_score = _compute_slay(spike_times, onset_times, pre_s, post_s)
            rows.append(
                {
                    "unit_id": int(row.unit_id),
                    "slay_score": None if math.isnan(slay_score) else slay_score,
                    "is_visual": _compute_ranksum(spike_times, onset_times, pre_s, post_s),
                }
            )
    return pd.DataFrame(rows)


def _stim_onsets_for_probe(trials: pd.DataFrame, probe_id: str) -> np.ndarray:
    probe_column = f"stim_onset_imec_{probe_id}"
    if probe_column in trials.columns:
        source_column = probe_column
    elif probe_id == "imec0" and "stim_onset_time" in trials.columns:
        source_column = "stim_onset_time"
    else:
        raise NWBRerunError(
            f"postprocess rerun requires trials column {probe_column!r} for {probe_id}"
        )

    onsets = pd.to_numeric(trials[source_column], errors="coerce").to_numpy(dtype=float)
    if "trial_valid" in trials.columns:
        valid = trials["trial_valid"].map(_coerce_trial_valid).to_numpy(dtype=bool)
        onsets = onsets.copy()
        onsets[~valid] = np.nan
    return onsets


def _compute_slay(
    spike_times: np.ndarray,
    stim_onset_times: np.ndarray,
    pre_s: float = 0.05,
    post_s: float = 0.30,
) -> float:
    valid_onsets = stim_onset_times[~np.isnan(stim_onset_times)]
    if len(valid_onsets) < 5:
        return float("nan")

    n_bins = int((pre_s + post_s) / 0.01)
    pre_bins = int(pre_s / 0.01)

    trial_vectors = []
    for onset in valid_onsets:
        window_start = onset - pre_s
        window_end = onset + post_s
        spikes_in = spike_times[(spike_times >= window_start) & (spike_times < window_end)]
        counts, _ = np.histogram(
            spikes_in - window_start,
            bins=n_bins,
            range=(0, pre_s + post_s),
        )
        trial_vectors.append(counts)
    trial_mat = np.asarray(trial_vectors, dtype=float)

    baseline_rate = trial_mat[:, :pre_bins].mean(axis=1)
    response_rate = trial_mat[:, pre_bins:].mean(axis=1)
    if response_rate.mean() <= baseline_rate.mean():
        return float("nan")

    row_var = trial_mat.var(axis=1)
    non_constant = trial_mat[row_var > 0]
    if non_constant.shape[0] < 2:
        return float("nan")

    ranks = rankdata(non_constant, axis=1)
    corr_matrix = np.corrcoef(ranks)
    iu = np.triu_indices_from(corr_matrix, k=1)
    corrs = corr_matrix[iu]
    corrs = corrs[~np.isnan(corrs)]
    if corrs.size == 0:
        return float("nan")
    return float(np.mean(corrs))


def _compute_ranksum(
    spike_times: np.ndarray,
    stim_onset_times: np.ndarray,
    pre_s: float = 0.05,
    post_s: float = 0.30,
) -> bool:
    valid_onsets = stim_onset_times[~np.isnan(stim_onset_times)]
    if len(valid_onsets) < 5:
        return False

    baseline_counts: list[int] = []
    response_counts: list[int] = []
    for onset in valid_onsets:
        baseline = spike_times[(spike_times >= onset - pre_s) & (spike_times < onset)]
        response = spike_times[(spike_times >= onset) & (spike_times < onset + post_s)]
        baseline_counts.append(len(baseline))
        response_counts.append(len(response))

    mean_baseline = float(np.mean(baseline_counts))
    mean_response = float(np.mean(response_counts))
    if mean_response <= mean_baseline:
        return False

    try:
        _, p = mannwhitneyu(baseline_counts, response_counts, alternative="less")
        return bool(p < 0.001)
    except Exception:
        return False


def _run_raw_rerun_units(
    loader: NWBLoader,
    rerun_dir: Path,
    *,
    pipeline_config: PipelineConfig | None,
    sorting_config: SortingConfig | None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    pipeline_config = pipeline_config or PipelineConfig()
    sorting_config = sorting_config or SortingConfig()
    if sorting_config.mode != "local":
        raise NWBRerunError("raw rerun requires SortingConfig.mode='local'")

    recording_bundles = loader.load_recordings(stream_type="ap")
    sorter_output_root = rerun_dir / "02_sorter_output_from_nwb"
    rows: list[dict[str, object]] = []
    probe_reports: list[dict[str, object]] = []
    next_unit_id = 1

    for probe_id, bundle in recording_bundles.items():
        recording = _preprocess_raw_recording(bundle.recording, pipeline_config)
        sorter_folder = sorter_output_root / probe_id
        params = asdict(sorting_config.sorter.params)
        try:
            sorting = ss.run_sorter(
                sorting_config.sorter.name,
                recording,
                folder=sorter_folder,
                remove_existing_folder=True,
                **params,
            )
        except Exception as exc:  # noqa: BLE001
            raise NWBRerunError(f"raw rerun sorter failed for {probe_id}: {exc}") from exc

        fs = float(sorting.get_sampling_frequency())
        probe_unit_ids = list(sorting.get_unit_ids())
        for sorter_unit_id in probe_unit_ids:
            spike_samples = sorting.get_unit_spike_train(sorter_unit_id, segment_index=0)
            rows.append(
                {
                    "unit_id": next_unit_id,
                    "probe_id": probe_id,
                    "ks_id": _json_safe_unit_id(sorter_unit_id),
                    "spike_times": np.asarray(spike_samples, dtype=float) / fs,
                    "unittype_string": "UNCLASSIFIED",
                    "is_visual": False,
                    "slay_score": np.nan,
                }
            )
            next_unit_id += 1
        probe_reports.append(
            {
                "probe_id": probe_id,
                "series_path": bundle.series_path,
                "sampling_frequency": bundle.sampling_frequency,
                "sorter_name": sorting_config.sorter.name,
                "sorter_output": str(sorter_folder),
                "n_units": len(probe_unit_ids),
            }
        )

    if not rows:
        raise NWBRerunError("raw rerun produced zero units across all probes")

    report = {
        "raw_rerun": {
            "probe_reports": probe_reports,
            "n_probes": len(probe_reports),
            "sorter_name": sorting_config.sorter.name,
        }
    }
    return pd.DataFrame(rows), report


def _preprocess_raw_recording(recording, pipeline_config: PipelineConfig):  # noqa: ANN001
    cfg = pipeline_config
    processed = spp.phase_shift(recording)
    processed = spp.bandpass_filter(
        processed,
        freq_min=cfg.preprocess.bandpass.freq_min,
        freq_max=cfg.preprocess.bandpass.freq_max,
    )
    bad_channel_ids, _ = spp.detect_bad_channels(
        processed,
        method=cfg.preprocess.bad_channel_detection.method,
    )
    if len(bad_channel_ids) > 0:
        processed = processed.remove_channels(bad_channel_ids)
    processed = spp.common_reference(
        processed,
        reference=cfg.preprocess.common_reference.reference,
        operator=cfg.preprocess.common_reference.operator,
    )
    if cfg.preprocess.motion_correction.method is not None:
        processed = spp.correct_motion(
            processed,
            preset=cfg.preprocess.motion_correction.preset,
        )
    return processed


def _json_safe_unit_id(unit_id: object) -> int | str:
    try:
        return int(unit_id)
    except (TypeError, ValueError):
        return str(unit_id)


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


def _coerce_trial_valid(value: object) -> bool:
    if pd.isna(value):
        return True
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer, float, np.floating)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    raise NWBRerunError(f"Invalid trial_valid value: {value!r}")


def _coerce_bool_value(value: object) -> bool:
    keep = _coerce_keep_value(value)
    if keep is None:
        return False
    return keep


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
