# Task 2 Real-Data NWB Rerun Smoke

Date: 2026-05-27

## Data

- Source: Quark `demo_NPXdata`
- Local path: `D:\neurotool_dev\test_data\demo_NPXdata`
- SpikeGLX session: `NPX_MD241029_exp_g0`
- BHV2 file: `241026_MaoDan_YJ_WordLOC.bhv2`
- AP stream: `imec0.ap`, 384 channels, 30000.201673640167 Hz, 373.32 s

## Environment Note

`torch`/`kilosort4` is not installed in this local environment, so the real-data smoke used the installed CPU sorter `tridesclous2`. This validates the NWB rerun plumbing on real AP samples. A full Kilosort4/GPU equivalence benchmark remains hardware-gated.

## Command

```powershell
uv run python tools\smoke_task2_nwb_rerun_demo.py `
  --demo-dir D:\neurotool_dev\test_data\demo_NPXdata `
  --output-dir logs\task2_smoke_real2 `
  --duration-sec 2 `
  --n-channels 16 `
  --sorter tridesclous2 `
  --rebuild
```

The output directory is under `logs/`, which is git-ignored.

## Result

| Step | Outcome |
| --- | --- |
| Build smoke NWB | `task2_demo_real_slice_input.nwb`, 2 units, 8 trials, `ElectricalSeriesAP_imec0` |
| `rewrite-units` | completed, 2 -> 2 units, report/checkpoint written |
| `postprocess` | completed, 2 -> 2 units, report/checkpoint written |
| `raw` | completed, 2 -> 8 units, report/checkpoint written |

Raw rerun details:

- `raw_time_range_sec`: `[0.0, 2.0]`
- Frames sorted: `60000`
- Sorter: `tridesclous2`
- Output: `logs\task2_smoke_real2\raw\nwb_rerun\task2_demo_real_slice_input_rerun_v001.nwb`
- Output NWB opens with PyNWB and contains `scratch["nwb_rerun_report"]`

## Issues Found And Fixed

- NWB-loaded recordings do not always carry SpikeGLX `inter_sample_shift`; raw rerun now skips `phase_shift()` unless that property exists.
- SpikeInterface's NWB reader did not restore channel locations from `ElectricalSeries.electrodes`; `NWBLoader.load_recordings()` now reattaches electrode x/y coordinates so geometry-aware sorters can run.
- Raw rerun now supports bounded `raw_time_range` and CLI config paths, making real-data smoke feasible without full-session GPU sorting.
