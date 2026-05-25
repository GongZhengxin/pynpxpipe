# Technical Debt Audit

Date: 2026-05-25

Scope: first pass for Codex task 1, focused on low-risk lint cleanup and static audit. No new features were added.

## Execution Baseline

Environment checks:

- `git status -s`: clean before edits.
- `git log --oneline -5`: HEAD matched the handoff commit `196c173`.
- System `uv` / `python` / `py` were not available in PATH.
- Local toolchain created for this audit:
  - `.codex-tools/uv.exe`: uv 0.11.16
  - `.venv`: CPython 3.12.13, created by `uv sync --inexact --all-groups --extra ui --extra plots --extra chat --extra gpu`
  - `.codex-tools/`, `.codex-python/`, `.uv-cache/`, and `.localappdata/` are local-only and excluded via `.git/info/exclude`.
  - On Windows, PyNWB/HDMF cache creation needs `WIN_PD_OVERRIDE_LOCAL_APPDATA=.localappdata` in this sandbox; setting `LOCALAPPDATA` alone is not enough because `platformdirs` prefers Windows known-folder APIs.

Verification:

- `uv run ruff check src/ tests/`: passed.
- `uv run ruff format --check src/ tests/`: passed.
- `uv run pytest --collect-only`: passed, 1569 tests collected.
- Targeted tests for touched modules: passed, 267 passed / 23 skipped.
- Curate/Merge error-handling regression tests: passed, 7 passed.
- Config/UI/Curate/Merge targeted regression subset: passed, 138 passed / 2 skipped.
- `uv run pytest --tb=short --ignore=tests/test_install_smoke.py`: passed, 1526 passed / 48 skipped.
- `uv run pytest --tb=short`: 1518 passed / 48 skipped / 2 failed from missing out-of-band sort stack (`torch`, `kilosort`) before fixing `MonkeyTemplate.yaml`; after the template fix, the only known full-suite blockers are the sort stack smoke tests.
- `uv run pytest --cov=pynpxpipe --cov-report=term-missing --ignore=tests/test_install_smoke.py --tb=short`: passed, 1526 passed / 48 skipped, total coverage 85%.
- Focused failed-checkpoint regression tests for `preprocess`, `sort`, `postprocess`, `synchronize`, and `export`: passed, 145 passed.
- Config default audit subset: `uv run pytest tests/test_core/test_config_integration.py tests/test_ui/test_components.py -k "default_roundtrip or real_pipeline_yaml_resources_fields or real_pipeline_yaml_preprocess_fields or real_sorting_yaml_sorter_fields or real_sorting_yaml_import_cfg_populated" --tb=short`: passed, 6 passed.
- `git diff --check`: passed; Windows reported expected LF-to-CRLF warnings only.

## Fixed In This Pass

### Lint cleanup

Status: fixed and verified by ruff.

Files touched:

- `src/pynpxpipe/io/nwb_writer.py`
- `src/pynpxpipe/io/spikeglx.py`
- `src/pynpxpipe/plots/style.py`
- `src/pynpxpipe/stages/curate.py`
- `src/pynpxpipe/stages/discover.py`
- `src/pynpxpipe/ui/state.py`
- `tests/integration/harness.py`
- `tests/test_io/test_nwb_writer.py`
- `tests/test_harness/test_sync_tables_contract.py`
- `tests/test_io/test_bhv.py`

Changes:

- Replaced small `try/except/pass` blocks with `contextlib.suppress`.
- Removed unused imports in `nwb_writer.py` and `discover.py`.
- Simplified one branch assignment in `spikeglx.py`.
- Simplified a no-op fallback assignment in `ui/state.py`.
- Replaced f-strings without placeholders in `tests/integration/harness.py`.
- Collapsed nested `with` statements in `tests/test_io/test_nwb_writer.py`.
- Rewrote the `amplitude_cutoff` NaN check in `curate.py` to avoid the double-negative comparison.
- Applied ruff format to the three pre-existing format drift files reported in the handoff.

### Subject template validation

Status: fixed and verified.

`monkeys/MonkeyTemplate.yaml` used `age: "P[x]Y"`, but `load_subject_config()` now validates ISO 8601 duration strings. This caused `tests/test_core/test_config_integration.py::test_load_real_subject_config[MonkeyTemplate]` to fail. The template now uses the valid example value `P4Y`.

### Config defaults audit

Status: fixed for spec drift found in this pass.

Reviewed sources:

- Code defaults in `src/pynpxpipe/core/config.py`.
- Active sample configs: `config/pipeline.yaml` and `config/sorting.yaml`.
- Ablation configs: `config/pipeline_E2.yaml` and `config/sorting_E*.yaml`.
- UI drift tests: `test_pipeline_form_default_roundtrip`, `test_sorting_form_default_roundtrip`, and field coverage tests in `tests/test_ui/test_components.py`.
- Real config integration tests in `tests/test_core/test_config_integration.py`.

Findings:

- Active YAML defaults match the dataclass defaults for the audited fields: resources use `"auto"`, preprocess motion correction defaults to DREDge, sorting import format defaults to `"kilosort4"`, sorter internal `n_jobs` defaults to `1`, and derivatives default to 1 ms bins.
- `config/pipeline_E2.yaml` intentionally disables motion correction for an ablation; this is not default drift.
- Resource fallback values such as `n_jobs=4` and `chunk_duration="1s"` are runtime fallbacks used when an unresolved `"auto"` reaches `BaseStage._setup_spikeinterface_jobs()`, not YAML/dataclass defaults.
- Fixed stale spec wording in `docs/specs/preprocess.md`, `docs/specs/sort.md`, and `docs/specs/postprocess.md` so the documented defaults distinguish dataclass/YAML defaults from runtime fallbacks.

Remaining note: `docs/specs/ui_improvements_plan.md` still contains historical planning language from before the UI default-roundtrip work. It is not treated as canonical user documentation.

### Legacy MATLAB PSTH timing note

Status: fixed in docs.

The handoff records a known legacy MATLAB bug where `PostProcess_function_raw.m` hard-coded `imec0` for meta/sync lookup, causing non-`imec0` probe PSTHs to appear about 20 ms later than pynpxpipe on long multi-probe sessions. This is now documented in:

- `README.md`
- `docs/specs/postprocess.md`

The documentation explicitly says not to compensate pynpxpipe timestamps for this legacy offset, and to use per-probe NWB units / `07_derivatives` rasters as canonical numeric outputs.

### Documentation drift on output directories

Status: fixed in user-facing and spec docs.

Updated docs and code comments to match the current numbered output layout:

- Preprocess outputs: `01_preprocessed/{probe_id}.zarr` plus `01_preprocessed/{probe_id}/figures`.
- Sort outputs: `02_sorted/{probe_id}`.
- Synchronization outputs: `04_sync/...`.
- Curated outputs: `05_curated/{probe_id}`.
- Postprocess outputs: `06_postprocessed/{probe_id}`.
- Derivative exports: `07_derivatives/...`.

Files updated include `getting_started.md`, `getting_started_cn.md`, `docs/architecture.md`, and the stage specs for preprocess, sort/merge/curate, synchronize, plots, postprocess, export, and checkpoints.

Remaining `07_export` references are intentional historical/negative-test text rather than active output path guidance.

### Failed checkpoint and error subclass consistency

Status: fixed for locally actionable stage-loop paths.

Baseline behavior is good in the checkpoint layer:

- `CheckpointManager.mark_failed()` writes `status: failed`, `failed_at`, and `error`.
- If writing the failed checkpoint itself fails, it logs and returns instead of masking the original stage exception.

Fixed during this audit:

- `PreprocessStage` now writes `checkpoints/preprocess.json` with `status: failed` when the no-probes preflight check fails.
- `SortStage` now writes `checkpoints/sort.json` for invalid mode and no-probes preflight failures.
- `ExportStage` now writes `checkpoints/export.json` when the target-area preflight check fails before NWBWriter is constructed.
- `PostprocessStage` now writes `checkpoints/postprocess.json` when `behavior_events.parquet` cannot be loaded, and per-probe failed checkpoints for postprocess failures such as unrecovered waveform OOM.
- `SynchronizeStage` now converts unexpected IO/schema/runtime failures into `SyncError`, writes `checkpoints/synchronize.json` with `status: failed`, and re-raises the stage-specific exception.
- `CurateStage` now preserves declared `CurateError` failures, wraps unexpected probe-loop failures into `CurateError`, and writes failed per-probe checkpoints.
- `MergeStage` now preserves declared `MergeError` failures, wraps unexpected probe-loop failures into `MergeError`, and writes failed per-probe checkpoints.

Focused regression tests were added for these paths and pass.

### Coverage baseline

Status: baseline captured and one high-risk low-coverage stage improved.

Command:

```bash
uv run pytest --cov=pynpxpipe --cov-report=term-missing --ignore=tests/test_install_smoke.py --tb=short
```

Result: 1526 passed / 48 skipped, total line coverage 85%.

Notable improvement:

- `src/pynpxpipe/stages/merge.py`: improved from 20% to 88% after adding merge-stage behavior tests.

Modules still below 70%:

- `src/pynpxpipe/io/_bhv_matlab.py`: 0%. Legacy MATLAB BHV reader shim is entirely unexercised by current tests.
- `src/pynpxpipe/io/bhv2_reader.py`: 39%. BHV2 parsing has substantial untested branches.
- `src/pynpxpipe/harness/validators/sync_validator.py`: 28%.
- `src/pynpxpipe/harness/validators/preprocess_validator.py`: 36%.
- `src/pynpxpipe/harness/validators/postprocess_validator.py`: 42%.
- `src/pynpxpipe/ui/app.py`: 59%. Main UI assembly still has lower coverage than individual UI components.
- Low-signal package init files: `src/pynpxpipe/__init__.py` 50%, `src/pynpxpipe/pipelines/__init__.py` 60%.

Suggested next action for a later task: prioritize behavior tests for `bhv2_reader.py` and the harness validators before spending time on package init coverage.

## Open Findings

### Missing graph report

Status: blocked by local inputs/tooling.

`CLAUDE.md` and the handoff require reading `graphify-out/GRAPH_REPORT.md` before architecture work, but the file is absent in the current clone. The `graphify` command is also not available in this local environment, so the graph-guided architecture review cannot be regenerated here.

Suggested next action: restore `graphify-out/GRAPH_REPORT.md` or install/provide `graphify`, then re-run the architecture-oriented portion of the audit.

### NWB validation with real outputs

Status: blocked by local inputs.

No `.nwb` files are present in the repository checkout, so a real generated-output NWB validation pass cannot be completed locally. Unit and integration tests around NWB writer behavior pass, but validating a produced NWB artifact requires a user-provided pipeline output or a generated fixture from a real run.

### Unsafe `uv sync` examples in docs

Status: fixed for positive examples.

Static search found bare `uv sync` examples in:

- `README.md`
- `getting_started.md`
- `getting_started_cn.md`
- `docs/release_prep_plan.md`
- `tools/install_sort_stack.py` messaging
- `src/pynpxpipe/plots/sync.py` user-facing warning text

Positive developer/user instructions now use `uv sync --inexact ...`, including README, getting-started guides, release-prep examples, installer messaging, and plots-extra warnings.

Remaining bare `uv sync` occurrences are intentional warnings or historical explanations, such as the explicit "DON'T" strict-sync example and comments explaining that plain strict sync can remove out-of-lock torch/kilosort.

### TODO scan

Status: open.

Source scan found one active code TODO:

- `src/pynpxpipe/stages/postprocess.py`: rename `slay_score` to `response_consistency_score` in a future compatibility-breaking change.

Docs contain tutorial TODO placeholders that appear instructional rather than code debt.

Suggested next action: leave the code TODO for a planned API rename milestone; do not change it during lint cleanup.

### Multi-probe `imec0` audit

Status: partially reviewed.

Source occurrences of `imec0` are mostly examples, UI seed defaults, tests, or the intentionally hardcoded NWB trial reference clock:

- `src/pynpxpipe/io/nwb_writer.py:_REFERENCE_PROBE = "imec0"` is explicitly locked by Phase NWB E1.1.
- `src/pynpxpipe/ui/state.py` and `probe_region_editor.py` use `{"imec0": ""}` as an editable default row.
- `src/pynpxpipe/stages/synchronize.py` comments describe deriving `imec_i` to `imec0` alignment through NIDQ.

No obvious source-level "should be probe_id but hardcoded imec0" bug was found in this first static scan. This still needs verification with ruff/tests and, ideally, the missing graph report.

## Remaining Verification

The only remaining full-suite check needs the out-of-band GPU/sorter stack:

```bash
uv run pytest --tb=short
```

It is expected to fail in this local environment because `torch` and `kilosort` are intentionally not installed from the lockfile. If dependencies must be synchronized first, use:

```bash
uv sync --inexact --all-groups
```
