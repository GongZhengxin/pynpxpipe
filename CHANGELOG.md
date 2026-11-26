# Changelog

## [Unreleased]

### Added

- Web UI (ui_redesign P0-1): after choosing a data folder, a discovery card lists the gate
  folder, NIDQ file, probes (model, serial, channels, AP size) and recording date, which is
  filled in automatically. When several gate folders or BHV2 files are found, pick one from a list.
- Web UI (ui_redesign P0-2): parameter presets from `config/` paired by suffix, YAML import
  and export, and a list of fields changed from the selected preset with per-field restore.
- Compare saved and proposed task windows against full neural recordings and aligned BHV
  trials on an interactive timeline. Tune gap and padding without rereading raw signals or
  changing outputs, including when reopening a completed preview.

### Fixed

- Rerunning only select_segments (e.g. after applying new task windows) no longer reads its
  own rewritten `04_sync/behavior_events.parquet` in single-recording sessions; it keeps
  synchronize's table as `behavior_events_source.parquet`, which synchronize refreshes.
- Execute always shows the task timeline entry and can reopen a saved preview without
  rerunning alignment. Reviewing status no longer prepares a run or archives existing outputs.
- Task cropping and the timeline retain whole trials with a recorded image presentation,
  including failed trials, and exclude empty trials even during padding. Refresh a proposed
  selection in memory and compare it with the saved one, including previews from older versions.
- The web UI now writes diagnostic PNGs with Agg and sends progress, errors and
  button updates to the browser session that started the run.
- Task selection checks each recording's acquisition timestamp before reading
  sync signals and identifies where to enter the acquisition timezone.
- Match full-trial BHV markers to the corresponding NIDQ event instead of an
  independent trial TTL, retaining failed and stimulus-free trials. Infer the
  common first BHV event or honor an explicit marker, validate the mapping,
  and record both anchor codes and timestamps.
- Invalidate derived results from the previous trial-anchor algorithm so cached
  alignment results cannot silently retain incorrect timing.

### Changed

- Document preview running/failed states and update the processing-computer
  instructions to pull the integrated changes from `main`.
