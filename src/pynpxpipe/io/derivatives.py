"""Session-level derivative exports for Phase 2.5.

Three outputs land under ``{output_dir}/07_derivatives/``:

- ``TrialRaster_{session_id}.h5`` — (n_units, n_trials, n_timebins) uint8 raster.
- ``UnitProp_{session_id}.csv``   — reduced unit properties (ks_id, unit_location, unittype_string).
- ``TrialRecord_{session_id}.csv``— full NWB trials table copy.

All inputs come from the NWB file that Phase 2 just wrote
(``nwbfile.units.to_dataframe()`` / ``nwbfile.trials.to_dataframe()``), so
the derivatives are always consistent with the canonical NWB.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import h5py
import numpy as np
import pandas as pd
from scipy import sparse

if TYPE_CHECKING:
    from pynpxpipe.io.bhv import BHV2Parser


# ────────────────────────────────────────────────────────────────────────
# spike_times_to_raster
# ────────────────────────────────────────────────────────────────────────


def spike_times_to_raster(
    unit_df: pd.DataFrame,
    trial_df: pd.DataFrame,
    pre_onset: float,
    post_onset: float,
    bin_size: float = 1.0,
    n_jobs: int = 1,
    verbose: bool = False,
    chunk_size: int = 50,
) -> np.ndarray:
    """Build a (n_units, n_trials, n_timebins) uint8 spike raster.

    Window = ``[-pre_onset, +post_onset]`` ms relative to
    ``trial_df['start_time']`` (seconds).

    Args:
        unit_df: DataFrame with a ``spike_times`` column of per-unit
            array-likes (spike times in seconds).
        trial_df: DataFrame with a ``start_time`` column (trial reference
            time in seconds).
        pre_onset: Pre-stimulus window in milliseconds.
        post_onset: Post-stimulus window in milliseconds.
        bin_size: Bin width in milliseconds (default 1).
        n_jobs: joblib parallelism. ``1`` runs chunked serial.
        verbose: Emit a tqdm progress bar when ``True``.
        chunk_size: Number of units per chunk in the serial path.

    Returns:
        ``np.ndarray`` of shape ``(n_units, n_trials, n_timebins)``,
        dtype ``np.uint8`` (counts clip at 255).

    Raises:
        ValueError: If the required columns are missing.
    """
    if "spike_times" not in unit_df.columns:
        raise ValueError("unit_df must contain a 'spike_times' column")
    if "start_time" not in trial_df.columns:
        raise ValueError("trial_df must contain a 'start_time' column")

    n_units = len(unit_df)
    n_trials = len(trial_df)
    n_timebins = int(np.ceil((pre_onset + post_onset) / bin_size))

    pre_s = pre_onset / 1000.0
    post_s = post_onset / 1000.0
    bin_s = bin_size / 1000.0

    spike_times_list = [np.asarray(st, dtype=np.float64) for st in unit_df["spike_times"].values]
    ref_times = trial_df["start_time"].to_numpy(dtype=np.float64)

    raster = np.zeros((n_units, n_trials, n_timebins), dtype=np.uint8)

    if n_jobs == 1:
        _chunked_raster(
            raster,
            spike_times_list,
            ref_times,
            n_trials,
            n_timebins,
            pre_s,
            post_s,
            bin_s,
            chunk_size,
            verbose,
        )
    else:
        from joblib import Parallel, delayed

        results = Parallel(n_jobs=n_jobs, verbose=10 if verbose else 0)(
            delayed(_process_unit)(
                spike_times_list[uid],
                ref_times,
                n_trials,
                n_timebins,
                pre_s,
                post_s,
                bin_s,
            )
            for uid in range(n_units)
        )
        for uid, res in enumerate(results):
            raster[uid] = res

    return raster


def _chunked_raster(
    raster: np.ndarray,
    spike_times_list: list[np.ndarray],
    ref_times: np.ndarray,
    n_trials: int,
    n_timebins: int,
    pre_s: float,
    post_s: float,
    bin_s: float,
    chunk_size: int,
    verbose: bool,
) -> None:
    """Fill ``raster`` in-place, chunk_size units at a time (peak buffer tiny)."""
    n_units = raster.shape[0]
    unit_iter: Any = range(0, n_units, chunk_size)
    if verbose:
        try:
            from tqdm import tqdm

            unit_iter = tqdm(list(unit_iter), desc="Raster chunks", ncols=100)
        except ImportError:
            pass

    for chunk_start in unit_iter:
        chunk_end = min(chunk_start + chunk_size, n_units)
        actual_size = chunk_end - chunk_start
        buf = np.zeros((actual_size, n_trials, n_timebins), dtype=np.uint8)

        for i, unit_idx in enumerate(range(chunk_start, chunk_end)):
            spike_times = spike_times_list[unit_idx]
            if len(spike_times) == 0:
                continue
            if not np.all(spike_times[:-1] <= spike_times[1:]):
                spike_times = np.sort(spike_times)

            for trial_idx in range(n_trials):
                t_start = ref_times[trial_idx] - pre_s
                t_end = ref_times[trial_idx] + post_s
                lo = np.searchsorted(spike_times, t_start, side="left")
                hi = np.searchsorted(spike_times, t_end, side="left")
                if hi <= lo:
                    continue
                relative = spike_times[lo:hi] - t_start
                bins = (relative / bin_s).astype(np.int32)
                valid = bins[(bins >= 0) & (bins < n_timebins)]
                if len(valid) == 0:
                    continue
                counts = np.bincount(valid, minlength=n_timebins)
                buf[i, trial_idx, :] = np.minimum(counts[:n_timebins], 255)

        raster[chunk_start:chunk_end] = buf


def _process_unit(
    spike_times: np.ndarray,
    ref_times: np.ndarray,
    n_trials: int,
    n_timebins: int,
    pre_s: float,
    post_s: float,
    bin_s: float,
) -> np.ndarray:
    """Per-unit raster computation (joblib parallel path)."""
    out = np.zeros((n_trials, n_timebins), dtype=np.uint8)
    if len(spike_times) == 0:
        return out
    spike_times = np.sort(spike_times)
    for trial_idx in range(n_trials):
        t_start = ref_times[trial_idx] - pre_s
        t_end = ref_times[trial_idx] + post_s
        lo = np.searchsorted(spike_times, t_start, side="left")
        hi = np.searchsorted(spike_times, t_end, side="left")
        if hi <= lo:
            continue
        relative = spike_times[lo:hi] - t_start
        bins = (relative / bin_s).astype(np.int32)
        valid = bins[(bins >= 0) & (bins < n_timebins)]
        if len(valid) == 0:
            continue
        counts = np.bincount(valid, minlength=n_timebins)
        out[trial_idx, :] = np.minimum(counts[:n_timebins], 255)
    return out


# ────────────────────────────────────────────────────────────────────────
# save_raster_h5
# ────────────────────────────────────────────────────────────────────────


def save_raster_h5(
    filepath: str,
    raster: np.ndarray,
    metadata: dict[str, Any] | None = None,
    compression: str = "gzip",
    compression_opts: int = 4,
    use_sparse: bool = True,
    sparsity_threshold: float = 0.5,
) -> dict[str, Any]:
    """Write a 3D raster to HDF5, choosing sparse/dense by sparsity.

    Args:
        filepath: Destination file (``.h5`` / ``.hdf5``; extension appended if missing).
        raster: ``(n_units, n_trials, n_timebins)`` uint8 array.
        metadata: Optional scalar metadata written as attrs under ``/metadata``.
        compression: HDF5 compression name (``"gzip"``, ``"lzf"``, or ``None``).
        compression_opts: gzip level (1-9).
        use_sparse: Enable scipy.sparse COO storage when sparsity exceeds threshold.
        sparsity_threshold: Zero fraction above which sparse format kicks in.

    Returns:
        Stats dict with ``filepath``, ``storage_format``, shape and size info.
    """
    if not filepath.endswith((".h5", ".hdf5")):
        filepath = filepath + ".h5"

    sparsity = float(np.sum(raster == 0) / raster.size) if raster.size else 0.0
    original_size_mb = raster.nbytes / (1024**2)
    use_sparse_fmt = bool(use_sparse and sparsity >= sparsity_threshold)

    with h5py.File(filepath, "w") as f:
        f.attrs["storage_format"] = "sparse" if use_sparse_fmt else "dense"
        f.attrs["original_shape"] = raster.shape
        f.attrs["sparsity"] = sparsity
        f.attrs["dtype"] = str(raster.dtype)

        if use_sparse_fmt:
            n_units, n_trials, n_timebins = raster.shape
            raster_2d = raster.reshape(n_units * n_trials, n_timebins)
            coo = sparse.coo_matrix(raster_2d)
            for name, arr in (("data", coo.data), ("row", coo.row), ("col", coo.col)):
                f.create_dataset(
                    name,
                    data=arr,
                    compression=compression,
                    compression_opts=compression_opts,
                )
        else:
            f.create_dataset(
                "raster",
                data=raster,
                compression=compression,
                compression_opts=compression_opts,
            )

        if metadata is not None:
            meta_group = f.create_group("metadata")
            for key, value in metadata.items():
                if isinstance(value, int | float | str | bool):
                    meta_group.attrs[key] = value
                elif isinstance(value, np.ndarray):
                    meta_group.create_dataset(key, data=value)
                else:
                    meta_group.attrs[key] = str(value)

    file_size_mb = os.path.getsize(filepath) / (1024**2)
    ratio = original_size_mb / file_size_mb if file_size_mb > 0 else 0.0

    return {
        "filepath": filepath,
        "storage_format": "sparse" if use_sparse_fmt else "dense",
        "original_size_mb": original_size_mb,
        "file_size_mb": file_size_mb,
        "compression_ratio": ratio,
        "sparsity": sparsity,
        "shape": raster.shape,
    }


# ────────────────────────────────────────────────────────────────────────
# CSV exports
# ────────────────────────────────────────────────────────────────────────


# SUA/GOOD → 1, MUA → 2, NON-SOMA/NOISE → 3, anything else → 0.
_UNITTYPE_ENUM: dict[str, int] = {
    "SUA": 1,
    "GOOD": 1,
    "MUA": 2,
    "NON-SOMA": 3,
    "NOISE": 3,
}


def export_unit_prop(units_df: pd.DataFrame, out_path: Path) -> Path:
    """Write the 5-column UnitProp CSV aligned to the MATLAB reference layout.

    See ``docs/todo.md`` §III. Columns (in order):
    ``id, ks_id, unitpos, unittype, unittype_string``.

    Args:
        units_df: NWB ``units.to_dataframe()`` output. Must contain ``ks_id``,
            ``unit_location`` (shape ``(3,)`` per row, [x, y, z] in μm), and
            ``unittype_string``. Other columns (``spike_times``, waveforms,
            SortingAnalyzer extensions) are ignored — they stay in the NWB
            units table.
        out_path: Destination CSV path.

    Returns:
        The ``out_path`` written. ``unitpos`` is serialized as a Python-list
        literal ``"[x, y]"``; downstream readers can recover the 2-vector via
        ``ast.literal_eval``. ``unittype`` enum: SUA/GOOD→1, MUA→2,
        NON-SOMA/NOISE→3, unknown/empty→0.
    """
    unit_location = np.asarray(list(units_df["unit_location"]))  # (N, 3)
    unitpos = [[float(xy[0]), float(xy[1])] for xy in unit_location[:, :2]]
    unittype_string = units_df["unittype_string"].to_list()
    unittype = [_UNITTYPE_ENUM.get(str(s).upper(), 0) for s in unittype_string]

    out = pd.DataFrame(
        {
            "id": list(range(len(units_df))),
            "ks_id": units_df["ks_id"].to_numpy(),
            "unitpos": unitpos,
            "unittype": unittype,
            "unittype_string": unittype_string,
        }
    )
    out.to_csv(out_path, index=False)
    return out_path


def export_trial_record(trials_df: pd.DataFrame, out_path: Path) -> Path:
    """Write the 6-column TrialRecord CSV aligned to the MATLAB reference layout.

    See ``docs/todo.md`` §II. Columns (in order):
    ``id, start_time, stop_time, stim_index, stim_name, fix_success``.

    Args:
        trials_df: NWB ``trials.to_dataframe()`` output. Must contain
            ``start_time``, ``stop_time``, ``stim_index``, ``stim_name``, and
            ``trial_valid`` (renamed to ``fix_success`` on export — semantic
            equivalence per ``docs/ground_truth/step5_matlab_vs_python.md:335``).
            Internal sync/diagnostic columns (``stim_onset_nidq_s_diag``,
            ``onset_time_ms``, ``stim_onset_imec_s``, ``photodiode_onset_s``,
            etc.) are dropped from CSV but retained in the NWB trials table.
        out_path: Destination CSV path.

    Returns:
        The ``out_path`` written.
    """
    out = pd.DataFrame(
        {
            "id": list(range(len(trials_df))),
            "start_time": trials_df["start_time"].to_numpy(),
            "stop_time": trials_df["stop_time"].to_numpy(),
            "stim_index": trials_df["stim_index"].to_numpy(),
            "stim_name": trials_df["stim_name"].to_numpy(),
            "fix_success": trials_df["trial_valid"].to_numpy(),
        }
    )
    out.to_csv(out_path, index=False)
    return out_path


# ────────────────────────────────────────────────────────────────────────
# resolve_post_onset_ms
# ────────────────────────────────────────────────────────────────────────


def resolve_post_onset_ms(bhv_parser: BHV2Parser) -> float:
    """Compute ``max(onset_time + offset_time)`` across trials' VariableChanges.

    Trials missing either key are skipped. If the parser raises or no trial
    supplies both fields, fall back to ``800.0`` ms.
    """
    try:
        trials = bhv_parser.parse()
    except Exception:
        return 800.0
    values: list[float] = []
    for t in trials:
        vc = getattr(t, "variable_changes", None) or {}
        if "onset_time" in vc and "offset_time" in vc:
            try:
                values.append(float(vc["onset_time"]) + float(vc["offset_time"]))
            except (TypeError, ValueError):
                continue
    if not values:
        return 800.0
    return float(max(values))
