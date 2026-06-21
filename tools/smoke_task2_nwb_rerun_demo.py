"""Build and run a bounded Task 2 NWB rerun smoke test on demo_NPXdata.

This script is intentionally small and local-data oriented. It creates a compact
NWB file from a short real SpikeGLX AP slice, then exercises the three Task 2
rerun modes: rewrite-units, postprocess, and raw.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import spikeinterface.extractors as se
from hdmf.backends.hdf5.h5_utils import H5DataIO
from pynwb import NWBHDF5IO, NWBFile
from pynwb.ecephys import ElectricalSeries
from pynwb.file import Subject

from pynpxpipe.core.config import PipelineConfig, SorterConfig, SortingConfig
from pynpxpipe.io.nwb_reader import NWBLoader
from pynpxpipe.pipelines.nwb_rerun import rerun_from_nwb


def main() -> None:
    args = _parse_args()
    demo_dir = args.demo_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    input_nwb = output_dir / "task2_demo_real_slice_input.nwb"
    if args.rebuild or not input_nwb.exists():
        _build_real_slice_nwb(
            demo_dir=demo_dir,
            output_nwb=input_nwb,
            duration_sec=args.duration_sec,
            n_channels=args.n_channels,
        )

    updates_csv = output_dir / "unit_updates.csv"
    updates_csv.write_text(
        "unit_id,unittype_string,is_visual,keep\n1,MUA,false,true\n2,MUA,false,true\n",
        encoding="utf-8",
    )

    pipeline_cfg = PipelineConfig()
    pipeline_cfg.preprocess.bad_channel_detection.method = "std"
    pipeline_cfg.preprocess.motion_correction.method = None
    sorting_cfg = SortingConfig(sorter=SorterConfig(name=args.sorter))

    results = {
        "input": _inspect_nwb(input_nwb),
        "rewrite_units": _inspect_result(
            rerun_from_nwb(
                input_nwb,
                output_dir / "rewrite_units",
                mode="rewrite-units",
                unit_updates=updates_csv,
            )
        ),
        "postprocess": _inspect_result(
            rerun_from_nwb(
                input_nwb,
                output_dir / "postprocess",
                mode="postprocess",
            )
        ),
        "raw": _inspect_result(
            rerun_from_nwb(
                input_nwb,
                output_dir / "raw",
                mode="raw",
                pipeline_config=pipeline_cfg,
                sorting_config=sorting_cfg,
                raw_time_range=(0.0, args.duration_sec),
            )
        ),
    }

    summary_path = output_dir / "task2_smoke_summary.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    print(f"summary={summary_path}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--demo-dir",
        type=Path,
        default=Path(r"D:\neurotool_dev\test_data\demo_NPXdata"),
        help="Path to downloaded demo_NPXdata.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("logs/task2_smoke"),
        help="Output directory for generated NWB and rerun outputs.",
    )
    parser.add_argument("--duration-sec", type=float, default=2.0)
    parser.add_argument("--n-channels", type=int, default=16)
    parser.add_argument("--sorter", default="tridesclous2")
    parser.add_argument("--rebuild", action="store_true")
    return parser.parse_args()


def _build_real_slice_nwb(
    *,
    demo_dir: Path,
    output_nwb: Path,
    duration_sec: float,
    n_channels: int,
) -> None:
    session_dir = demo_dir / "NPX_MD241029_exp_g0"
    bhv_file = demo_dir / "241026_MaoDan_YJ_WordLOC.bhv2"
    if not session_dir.exists():
        raise FileNotFoundError(f"SpikeGLX session not found: {session_dir}")
    if not bhv_file.exists():
        raise FileNotFoundError(f"BHV2 file not found: {bhv_file}")

    recording = se.read_spikeglx(session_dir, stream_name="imec0.ap")
    fs = float(recording.get_sampling_frequency())
    n_frames = int(round(duration_sec * fs))
    channel_ids = recording.get_channel_ids()[:n_channels]
    recording_slice = recording.select_channels(channel_ids).frame_slice(
        start_frame=0,
        end_frame=n_frames,
    )
    traces = recording_slice.get_traces(start_frame=0, end_frame=n_frames)
    locations = np.asarray(recording.get_channel_locations()[:n_channels], dtype=float)

    nwbfile = NWBFile(
        session_description="Task 2 real-data NWB rerun smoke from demo_NPXdata",
        identifier="task2-demo-real-slice",
        session_start_time=datetime(2024, 10, 29, tzinfo=UTC),
        session_id="241029_MaoDan_WordLOC_V4_smoke",
        subject=Subject(
            subject_id="MaoDan",
            species="Macaca mulatta",
            sex="M",
            age="P4Y",
            description="Demo subject for local Task 2 smoke validation",
        ),
    )

    _add_units_and_trials(nwbfile, duration_sec)
    _add_ap_electrical_series(nwbfile, traces, locations, channel_ids, fs)
    nwbfile.add_scratch(
        json.dumps(
            {
                "demo_dir": str(demo_dir),
                "session_dir": str(session_dir),
                "bhv_file": str(bhv_file),
                "duration_sec": duration_sec,
                "n_channels": n_channels,
                "stream_name": "imec0.ap",
            },
            indent=2,
        ),
        name="task2_smoke_source",
        description="Source paths and slice parameters for this smoke NWB.",
    )

    output_nwb.parent.mkdir(parents=True, exist_ok=True)
    with NWBHDF5IO(str(output_nwb), "w") as io:
        io.write(nwbfile)


def _add_units_and_trials(nwbfile: NWBFile, duration_sec: float) -> None:
    onsets = np.linspace(0.2, max(0.21, duration_sec - 0.4), num=8)
    responsive_spikes = np.sort(np.concatenate([onsets + 0.023, onsets + 0.067]))

    nwbfile.add_unit_column("probe_id", "Probe identifier")
    nwbfile.add_unit_column("ks_id", "Original sorter unit id")
    nwbfile.add_unit_column("unittype_string", "Unit type")
    nwbfile.add_unit_column("is_visual", "Visual response flag")
    nwbfile.add_unit_column("slay_score", "SLAY score")
    nwbfile.add_unit(
        id=1,
        spike_times=responsive_spikes,
        probe_id="imec0",
        ks_id=1,
        unittype_string="SUA",
        is_visual=False,
        slay_score=0.0,
    )
    nwbfile.add_unit(
        id=2,
        spike_times=np.array([], dtype=float),
        probe_id="imec0",
        ks_id=2,
        unittype_string="MUA",
        is_visual=True,
        slay_score=0.5,
    )

    nwbfile.add_trial_column("stim_onset_time", "Reference-probe onset time")
    nwbfile.add_trial_column("trial_id", "BHV2 trial identifier")
    nwbfile.add_trial_column("trial_valid", "Whether the trial is valid")
    nwbfile.add_trial_column("stim_onset_imec_imec0", "Stimulus onset time for imec0")
    for idx, onset in enumerate(onsets, start=1):
        nwbfile.add_trial(
            start_time=float(onset),
            stop_time=float(min(duration_sec, onset + 0.35)),
            trial_id=idx,
            stim_onset_time=float(onset),
            trial_valid=True,
            stim_onset_imec_imec0=float(onset),
        )


def _add_ap_electrical_series(
    nwbfile: NWBFile,
    traces: np.ndarray,
    locations: np.ndarray,
    channel_ids: np.ndarray,
    sampling_frequency: float,
) -> None:
    nwbfile.add_electrode_column("probe_id", "Probe identifier")
    nwbfile.add_electrode_column("channel_id", "Channel id within the source stream")
    device = nwbfile.create_device("imec0_device")
    group = nwbfile.create_electrode_group(
        "imec0_group",
        description="imec0 AP electrodes",
        location="V4",
        device=device,
    )
    for idx, channel_id in enumerate(channel_ids):
        x, y = locations[idx]
        nwbfile.add_electrode(
            id=idx,
            x=float(x),
            y=float(y),
            z=0.0,
            imp=np.nan,
            location="V4",
            filtering="none",
            group=group,
            probe_id="imec0",
            channel_id=str(channel_id),
        )
    region = nwbfile.create_electrode_table_region(
        list(range(len(channel_ids))),
        "AP electrodes for imec0",
    )
    nwbfile.add_acquisition(
        ElectricalSeries(
            name="ElectricalSeriesAP_imec0",
            data=H5DataIO(traces, compression="gzip"),
            electrodes=region,
            starting_time=0.0,
            rate=sampling_frequency,
            conversion=1e-6,
            description="Real SpikeGLX AP slice from demo_NPXdata.",
        )
    )


def _inspect_result(result) -> dict[str, object]:  # noqa: ANN001
    data = _inspect_nwb(result.output_nwb)
    data.update(
        {
            "mode": result.mode,
            "output_nwb": str(result.output_nwb),
            "report_path": str(result.report_path),
            "checkpoint_path": str(result.checkpoint_path),
            "n_units_before": result.n_units_before,
            "n_units_after": result.n_units_after,
        }
    )
    return data


def _inspect_nwb(nwb_path: Path) -> dict[str, object]:
    summary = NWBLoader(nwb_path).inspect()
    return {
        "nwb_path": str(nwb_path),
        "session_id": summary.session_id,
        "subject_id": summary.subject_id,
        "probe_ids": list(summary.probe_ids),
        "n_units": summary.n_units,
        "n_trials": summary.n_trials,
        "raw_ap_streams": summary.raw_ap_streams,
        "raw_lf_streams": summary.raw_lf_streams,
        "has_sync_tables": summary.has_sync_tables,
        "has_pipeline_config": summary.has_pipeline_config,
    }


if __name__ == "__main__":
    main()
