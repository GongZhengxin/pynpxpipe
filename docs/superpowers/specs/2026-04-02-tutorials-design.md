# Design: pynpxpipe Tutorial Notebook

**Date:** 2026-04-02
**Status:** Approved

---

## 1. Purpose

Create a single end-to-end Jupyter notebook (`tutorials/01_discover_pipeline.ipynb`) that guides new team members through the complete pynpxpipe workflow using real SpikeGLX data (path-parameterized). Covers all 9 currently-completed modules with working code, plus explicit placeholder cells for future functionality (bhv2, synchronize, postprocess visualizations).

---

## 2. Target Audience

New team members familiar with Python and basic neuroscience, but unfamiliar with pynpxpipe internals. The notebook explains design decisions (e.g., why phase_shift must precede bandpass) not just API calls.

---

## 3. File Location

```
tutorials/
  01_discover_pipeline.ipynb
```

(Future notebooks: `02_preprocess.ipynb`, `03_synchronize.ipynb`, etc., as more stages are completed.)

---

## 4. Notebook Structure

### Section 00 — Configuration (user-edited cell)

```python
# === 用户配置区（修改这里）===
from pathlib import Path

SESSION_DIR  = Path(r"C:\your\spikeglx\session")
OUTPUT_DIR   = Path(r"C:\your\output")
BHV_FILE     = Path(r"C:\your\session.bhv2")
SUBJECT_YAML = Path(r".\monkeys\YourMonkey.yaml")
```

- Followed by assertion cells that check path existence and print friendly error messages (not raw Python tracebacks) if paths are wrong.

### Section 01 — Session Setup

- Import and explain `SubjectConfig`, `ProbeInfo`, `Session` dataclasses.
- Load subject YAML via `ConfigLoader`.
- Construct a `Session` object manually (showing what `runner.py` will do automatically in production).
- Print `session.output_dir`, `session.subject.subject_id`, etc.
- Markdown: explain why Session is a pure dataclass with no UI dependency, and how it flows through every stage.

### Section 02 — SpikeGLX Data Discovery (IO layer)

- Instantiate `SpikeGLXDiscovery(session_dir)` and call `discover_probes()`.
- Print resulting `ProbeInfo` objects.
- Locate NIDQ files via `SpikeGLXDiscovery.discover_nidq()` (returns `(nidq_bin, nidq_meta)`).
- Load NIDQ recording lazily with `SpikeGLXLoader.load_nidq(nidq_bin, nidq_meta)`, print channel IDs and sample rate.
- **Visualization A — Raw NIDQ signal**: Extract first 5 seconds (`get_traces(start_frame=0, end_frame=5*fs)`), plot all analog channels as stacked time series using matplotlib. Label each channel by its channel ID. This is the earliest point where raw acquired signal is visible.
- Markdown: explain lazy loading — why `.bin` files are never fully loaded into RAM.

### Section 03 — DiscoverStage

- Instantiate `DiscoverStage(session)` and call `run()`.
- Show `session.probes` populated after the call.
- Read and pretty-print `session_info.json`.
- Markdown: explain checkpoint-first design — what happens if you call `run()` a second time (it returns immediately).

### Section 04 — Probe Visualizations

- **Visualization B — Probe channel position map**: For each probe, load AP recording lazily (`SpikeGLXLoader.load_ap(probe)`), then call `recording.get_probe()` to get the SpikeInterface `Probe` object and its `contact_positions` array. Scatter-plot positions (x vs. y in micrometers). Multi-probe sessions get subplot columns. Color-code by row (shank position). Note: `ProbeInfo.channel_positions` is `None` at this stage; positions come from the SpikeInterface recording's embedded probe geometry.
- **Visualization C — Probe metadata summary table**: Build a `pandas.DataFrame` from `session.probes` with columns: `probe_id`, `probe_type`, `serial_number`, `sample_rate`, `n_channels`. Display with `df.style`.

### Section 05 — Checkpoint & Resume

- Show the written checkpoint file: `output_dir / "checkpoints" / "discover.json"`.
- Pretty-print its contents (status, timestamp, payload).
- Call `DiscoverStage(session).run()` a second time — demonstrate it exits immediately with "already complete".
- **Visualization D — Checkpoint status board**: A small pandas DataFrame or formatted dict showing all checkpoint files found in `output_dir/checkpoints/`, their stage name, status (`completed` / `failed` / missing), and timestamp.

### Section 06 — Structured Logging

- Point to `session.log_path`.
- Read last 20 lines of the `.jsonl` log file, parse each line as JSON, display as a table (timestamp, stage, event, duration_ms).
- **Visualization E — Log output table**: `pandas.DataFrame` from parsed log lines.
- Markdown: explain why structured (JSON Lines) logging is preferred over plain text for programmatic analysis.

### Section 07 — Future Capabilities (Placeholder cells)

Each placeholder cell follows the same pattern:

```python
# TODO: Available in Tutorial 02 — Synchronize
# This cell will show: [description of visualization]
# Requires: [module names, e.g. io/bhv.py + stages/synchronize.py]
raise NotImplementedError("Not yet implemented — see docs/specs/synchronize.md")
```

Placeholder cells planned:
1. **Eye fixation point scatter**: X/Y scatter by trial (colored by condition), from `behavior_events.parquet`.
2. **Trial-averaged photodiode signal**: Mean ± SEM voltage trace per condition, from NIDQ photodiode channel aligned to trial onset via `sync_tables.json`.
3. **Image repetition count histogram**: Bar chart of how many times each image ID was shown, from `behavior_events.parquet`.
4. **Spike raster (preview)**: Placeholder for postprocess raster, depends on `stages/sort.py` + `stages/postprocess.py`.

---

## 5. Visual Summary

| # | Visualization | Data Source | Module Required | Status |
|---|---------------|-------------|-----------------|--------|
| A | Raw NIDQ stacked time series | `SpikeGLXLoader.load_nidq()` | `io/spikeglx.py` ✅ | Implemented |
| B | Probe channel position map | `SpikeGLXLoader.load_ap(probe).get_probe().contact_positions` | `io/spikeglx.py` ✅ | Implemented |
| C | Probe metadata table | `session.probes` | `stages/discover.py` ✅ | Implemented |
| D | Checkpoint status board | `output_dir/checkpoints/` | `core/checkpoint.py` ✅ | Implemented |
| E | Structured log table | `session.log_path` | `core/logging.py` ✅ | Implemented |
| F | Eye fixation scatter | `behavior_events.parquet` | `io/bhv.py` 🟡 | TODO stub |
| G | Trial-avg photodiode | NIDQ + `sync_tables.json` | `stages/synchronize.py` 🟡 | TODO stub |
| H | Image repetition histogram | `behavior_events.parquet` | `io/bhv.py` 🟡 | TODO stub |
| I | Spike raster | SortingAnalyzer | `stages/sort.py` 🟡 | TODO stub |

---

## 6. Dependencies

The notebook adds no new Python dependencies beyond what is already in `pyproject.toml`:
- `matplotlib` — already a transitive dependency via spikeinterface
- `pandas` — already a transitive dependency via spikeinterface

If `matplotlib` or `pandas` are not explicit dev dependencies, they should be added to `[tool.uv] dev-dependencies` in `pyproject.toml`.

---

## 7. Data Requirements

The user must have:
- A valid SpikeGLX session directory (with at least one `*_imec0` subdirectory)
- A valid `.bhv2` file (only the magic-byte check in discover will be run; full parse is a TODO stub)
- A `monkeys/*.yaml` subject config file

---

## 8. What is NOT in this notebook

- No mock/synthetic data — real data only (path-parameterized)
- No preprocessing, sorting, or synchronization (those are future notebooks)
- No unit test coverage (tutorials are exploratory, not part of the test suite)
- No CLI invocation (shows the Python API directly)
