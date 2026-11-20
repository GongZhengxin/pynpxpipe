# Changelog

## [Unreleased]

### Fixed

- Match full-trial BHV markers to the corresponding NIDQ event instead of an
  independent trial TTL, retaining failed and stimulus-free trials. Infer the
  common first BHV event or honor an explicit marker, validate the mapping,
  and record both anchor codes and timestamps.
- Invalidate derived results from the previous trial-anchor algorithm so cached
  alignment results cannot silently retain incorrect timing.

### Changed

- Document preview running/failed states and update the processing-computer
  instructions to pull the integrated changes from `main`.
