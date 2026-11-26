# Task-window selection and joint recordings

User-approved implementation specification (2026-11-17).

## Goal

Synchronize before sorting, retain each whole trial with at least one image onset
(even if it later failed), and sort ordered neural/BHV2 pairs from the same animal,
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

1. Discover and validate every pair and probe configuration. When the run includes
   synchronization and segment selection, check every source's imec0 AP
   `fileCreateTime` before synchronizing the first source. Embedded UTC offsets
   are sufficient. A missing timezone identifies the source and the setting to fill.
2. Independently synchronize each source using bounded channel reads. Preserve
   the existing linear IMEC/NIDQ fit and photodiode threshold semantics.
3. Anchor BHV trial zero to matched behavioral markers (including their BHV
   offsets). Trial end is the maximum recorded event/analog extent, never the
   next trial's start. Ambiguous or missing boundaries fail selection.
4. Use a finite recorded BHV stimulus onset (or a finite NIDQ onset in older tables without the BHV column).
   Image IDs, planned images, fixation success and placeholder rows do not establish presentation.
   Merge presented trials when next start minus previous end is <=180 s. Empty trials are hard
   boundaries for gap merging, padding and frame selection. Per-source alignment still includes
   all trial anchors; selected behavior tables and the timeline only include trials with a presentation.
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

### 2026-11-20 full-trial marker correction

The independent NIDQ trial TTL is not necessarily a BHV behavioral event code.
In the reported recordings, the TTL adapter emits physical value 2, while BHV
trials begin with behavioral code 9. Reversing the detected TTL bit into BHV code
2 therefore fails; pairing BHV code 9 to that later TTL silently shifts trial zero.

Full-trial alignment must infer the common first BHV event (unique in every
trial), or use `task_windows.trial_start_code` when explicitly configured. It
projects that actual BHV code through `sync.event_bits`, using the same packing
as NIDQ decoding, and matches the corresponding NIDQ transitions independently
of the trial TTL used for stimulus window matching. It never hardcodes code 9.
Reject missing/repeated BHV anchors, projected-code collisions, unrecorded codes,
non-finite/invalid extents, unequal counts, non-monotonic times, overlapping
intervals, or a trial TTL outside its reconstructed trial. Align even failed and
stimulus-free trials before selecting task windows. Save both anchor codes and timestamps in trial intervals
and log the selected mapping. With no decoder mapping, existing callers with an
explicit BHV code retain their explicitly supplied decoded bit mapping.
Increment the segmented run-signature version so completed results from the old
anchor algorithm are archived and recomputed, including earlier explicit-code runs.

This extends complete-trial coverage; MATLAB-style stimulus matching and
photodiode calibration are unchanged. Tests must include a failed first trial,
different per-trial TTL delays, a custom event-bit order, explicit overrides,
and ambiguous/missing markers. Production checks may read BHV/NIDQ for marker
diagnosis; no AP processing or sorting runs on the development computer.

### 2026-11-20 production correction

SpikeGLX discovery reads `imDatPrb_sn` / `imDatPrb_type`, falling back to
`imProbeSN` / `imProbeOpt` / `imProbeType` for older headers. Cached probe
identities are refreshed from the original metadata on resume. This follows
[ProbeInterface's SpikeGLX reader](https://github.com/SpikeInterface/probeinterface/blob/main/src/probeinterface/neuropixels_tools.py).
The raw files are never edited.

Discovery and alignment operate on each pair independently. Selection writes
joint compatibility status and any rejection reason into the preview summary;
missing/different probe serials do not prevent viewing aligned task intervals.
Preprocessing and sorting still enforce the complete compatibility check before
reading or sorting selected traces, including when resuming checkpoints.

The UI explicitly selects `single` or `joint` input mode. Single paths and joint
pair drafts are separate; only the selected mode supplies pipeline inputs.
Joint mode requires at least two saved pairs, supports editing and reordering,
and displays the required directory level and preview/run steps inline.
Restoring a saved joint session restores joint mode. Hidden draft edits never
change the saved pairs. No local production sorting is part of this correction;
deploy the tested branch through GitHub to the acquisition/processing computer.

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

### 2026-11-26 rerun-safe behavioral input

**Goal.** Re-running only `select_segments` (UI "apply proposed task windows",
`docs/specs/ui_redesign.md` §8.1) must give the same result as the first run.

**Problem.** In single-source mode the per-source sync directory is the output's
`04_sync/`, so the stage read `behavior_events.parquet` and then overwrote it with
the namespaced table (`stim_onset_imec_s` turned into per-probe JSON,
`source_stim_onset_imec_s` added, `attempt_id` prefixed). A second run read its own
output and corrupted the table. Joint mode reads `sources/<id>/04_sync/` and was
not affected.

**Processing.**
1. When a source's sync directory is the output's `04_sync/` (single-source mode), the
   stage reads `04_sync/behavior_events_source.parquet`. If it does not exist, it is
   created as a byte copy of `behavior_events.parquet` (synchronize's table). The
   output path `04_sync/behavior_events.parquet` and downstream consumers are unchanged.
   Joint sources keep reading `sources/<id>/04_sync/behavior_events.parquet` directly,
   since this stage never writes there.

2. A table that already carries `source_stim_onset_imec_s` is a previous
   select_segments output, not synchronize's table (outputs from versions before this
   fix). The stage fails with a message asking to rerun from synchronize.
3. `synchronize` deletes a stale `behavior_events_source.parquet` whenever it
   writes a new `behavior_events.parquet`, so the copy always matches the current
   alignment.

**Relationship to MATLAB.** No MATLAB counterpart; file-handling only.
