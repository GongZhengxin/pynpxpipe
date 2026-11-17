# Task-window selection and joint recordings

User-approved implementation specification (2026-11-17).

## Goal

Synchronize before sorting, retain all task activity (including failed and
stimulus-free trials), and sort ordered neural/BHV2 pairs from the same animal,
experiment/day and unchanged probe placement together. Original files are read-only.

## Inputs and configuration

`Session.recordings` contains ordered `RecordingSource` entries (`source_id`,
`session_dir`, `bhv_file`, optional `start_offset_s`). Legacy sessions normalize
to one source. `SessionManager.create_from_recordings` and YAML/GUI expose pairing.
`task_windows`: `enabled=false` for legacy configurations; GUI new runs enable it;
`max_idle_s=180`, `padding_before_s=30`, `padding_after_s=30`,
`join_guard_s=0.1`, `filter_margin_s=0.1`, `recording_timezone=null`.
Naive acquisition timestamps require an explicit IANA timezone. Explicit offsets
override acquisition timestamps for restart corrections; ordering/overlap are validated.

## Outputs

An immutable JSON segment manifest records source identity, original half-open
sample intervals, concatenation offsets, affine clock mappings, observation
intervals, and a content signature. Complete aligned trial intervals are separate
from the per-stimulus event table. A single NWB contains all probes, selected raw
AP/LF/NIDQ blocks, full trial/task intervals and source provenance. Gaps remain real
gaps; units carry `obs_intervals`. Trial/stimulus identity is namespaced by source.

## Processing

1. Discover and validate every pair and probe configuration.
2. Independently synchronize each source using bounded channel reads. Preserve
   the existing linear IMEC/NIDQ fit and photodiode threshold semantics.
3. Anchor BHV trial zero to matched behavioral markers (including their BHV
   offsets). Trial end is the maximum recorded event/analog extent, never the
   next trial's start. Ambiguous or missing boundaries fail selection.
4. Merge consecutive trials when next start minus previous end is <=180 s.
   Pad blocks, clamp to stream extent and merge overlaps; do not discard sparse activity.
5. Filter within source/block context. Union bad channels per probe, reference,
   concatenate for optional DREDge and one sorter invocation per probe.
6. Split sorting back to analysis segments with shared unit IDs. Exclude the
   configured guard around joins from spikes AND analysis duration; raw export
   retains those samples. All downstream consumers must handle segments.
7. Map spikes via source frames into the experiment reference clock (imec0).
   Export raw blocks independently with transformed starting_time/rate and eye
   samples with aligned timestamps. No synthetic zero padding.
8. Input/config/manifest signatures invalidate stale checkpoints and caches;
   external sorting imports must declare the same mapping signature.

## Open-source references and relationship to MATLAB

- [neuropixel-utils](https://djoshea.github.io/neuropixel-utils/imec_dataset/):
  `TrialSegmentationInfo.computeActiveRegions` and `TimeShiftSpec` inform block
  selection and reversible time mapping; no MATLAB dependency is introduced.
- [SpikeInterface 0.104.0](https://github.com/SpikeInterface/spikeinterface/blob/0.104.0/src/spikeinterface/core/segmentutils.py):
  reuse lazy frame slicing, concatenation, appending and sorting splitting.
  Concatenation alone does not preserve acquisition time or avoid sorter disk I/O.
- [CatGT](https://billkarsh.github.io/CatGT/) and
  [TPrime](https://billkarsh.github.io/TPrime/): reference cropping/concatenation
  and clock alignment. Our linear fit is not TPrime's local-edge transformation.
- [AIND ephys pipeline](https://github.com/AllenNeuralDynamics/aind-ephys-pipeline):
  reference concatenation before motion correction; output organization differs.
- [PyNWB 3.1.3](https://github.com/NeurodataWithoutBorders/pynwb/blob/3.1.3/src/pynwb/misc.py):
  standard Units `obs_intervals` and TimeIntervals represent observation gaps.

Existing MATLAB photodiode calibration (ground_truth step #10) and direct
stimulus TTL matching remain intact. Full trial coverage, per-source clocks and
segmented NWB extend that workflow. The 100 ms join guard is an engineering
default requiring validation, not a published community standard.

## Validation

Synthetic tests cover 179/180/181 s gaps, sparse/failed/no-stimulus trials,
overlapping padding and clipping, frame round trips and unit identity, streamed
edge boundaries, photodiode equivalence, configuration mismatch rejection,
NWB real gaps/observation intervals/raw bit equivalence, reader/rerun handling,
GUI pairing and cache invalidation. Real recording/GPU acceptance is reported
separately when fixtures and the sorting stack are available.

Implemented and verified on 2026-11-17 with SpikeInterface 0.104.0 and PyNWB
3.1.3: 27 focused cases, including real filtering, merge proposals, Bombcell,
analyzers, interrupted-export recovery, multi-probe electrode metadata and NWB
raw reruns. The locked dependency CPU regression passed 1671 tests, skipped 48
unavailable data/MATLAB cases and explicitly deselected two missing torch/Kilosort
installation checks. The final GUI restore change passed 20 focused tests.
The pre-upload CPU coverage rerun passed the same 1671 tests with 85.00% coverage
(80% required). Formatting checks pass for all changed Python files; five
unchanged files have pre-existing formatting failures in the full-repository check.
The sorter is deterministic test input; real Kilosort/DREDge acceptance is pending.
