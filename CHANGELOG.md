# Changelog

## [Unreleased]

### Added

- Compare saved and proposed task windows against full neural recordings and aligned BHV
  trials on an interactive timeline. Tune gap and padding without rereading raw signals or
  changing outputs, including when reopening a completed preview.

### Fixed

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
