# Design: pynpxpipe Tutorial 02 — Preprocess & Sort

**Date:** 2026-04-02
**Status:** Approved

---

## 1. Purpose

Create a Jupyter notebook (`tutorials/02_preprocess_sort.ipynb`) covering Layer 2 of
pynpxpipe: **PreprocessStage** (AP signal preprocessing chain) and **SortStage** (Kilosort4
local run + external import). Builds on Tutorial 01's style and can be run standalone (includes
a brief session + discover setup section).

---

## 2. Target Audience

Same as Tutorial 01: new team members familiar with Python and basic neuroscience, unfamiliar
with pynpxpipe internals. This notebook explains *why* the processing chain order matters
(phase_shift MUST precede bandpass), the GPU constraint for sorting, and the two sort modes
(local run vs. import from Windows lab PC).

---

## 3. File Location

```
tutorials/
  02_preprocess_sort.ipynb
```

---

## 4. Notebook Structure

### Section 00 — Configuration (user-edited cell)

```python
# === 用户配置区（修改这里）=========================================
from pathlib import Path

DATA_DIR     = Path(r"C:\your\recording\root")
OUTPUT_DIR   = Path(r"C:\your\output")
SUBJECT_YAML = Path(r".\monkeys\YourMonkey.yaml")

# Optional — only needed for Section 04 (SortStage import mode)
# Maps probe_id → path of your existing Kilosort4 output folder
SORTED_PATHS = {
    "imec0": Path(r"C:\your\kilosort4\imec0"),
}
# ===================================================================
```

- Followed by validation + `OUTPUT_DIR.mkdir(parents=True, exist_ok=True)`.

### Section 01 — Setup (brief, standalone)

- Same session + discover as Tutorial 01, condensed into one code cell.
- Comment: "For full explanation of this section, see Tutorial 01."
- Calls `DiscoverStage(session).run()` — checkpoint-aware (skips if Tutorial 01 was run first).
- Prints probe list.

### Section 02 — PreprocessStage

Markdown explains the six-step chain and ordering constraints:
1. `phase_shift` — corrects Neuropixels ADC time-division multiplexing offsets. **Must be first.**
2. `bandpass_filter` — passes 300–6000 Hz (removes LFP and high-freq noise).
3. `detect_bad_channels` — coherence+PSD on filtered data (more accurate than on raw).
4. `remove_channels` — drops bad channels **before** CMR to avoid polluting the reference.
5. `common_reference (CMR)` — global median reference.
6. `correct_motion` (optional, default: DREDge) — note: mutually exclusive with KS4 `nblocks > 0`.

Two code cells:
1. **Default config run** — `PreprocessStage(session).run()` (DREDge enabled, 300–6000 Hz).
2. **Custom config example** — shows how to disable motion correction (`method=None`) for the
   KS4-internal-drift-correction workflow.

### Section 03 — Preprocessed Data Inspection

- **Visualization A — Raw vs. preprocessed AP traces**: Side-by-side subplots for 10 channels × 0.5 s.
  Left column: raw AP (lazy-loaded via `SpikeGLXLoader.load_ap`). Right column: preprocessed
  (lazy-loaded via `si.load(zarr_path)`). Same channels in both panels; channels chosen from
  preprocessed recording (bad channels already removed).
- **Visualization B — Bad channel summary table**: pandas DataFrame from checkpoint JSONs, showing
  `probe_id`, `n_channels_original`, `n_bad_channels`, `n_channels_after_bad_removal`,
  `freq_min`, `freq_max`, `motion_correction`.

### Section 04 — SortStage: Import Mode

Markdown: explains import mode rationale (KS4 typically run on Windows GPU lab PC; results
copied over and imported here).

Code cell:
- Build `SortingConfig(mode="import", import_cfg=ImportConfig(format="kilosort4", paths=SORTED_PATHS))`.
- Run `SortStage(session, sorting_cfg).run()`.
- Per-probe checkpoints confirm success.

### Section 05 — SortStage: Local Mode

Markdown: explains local mode (runs KS4 directly via SpikeInterface) and its GPU requirement.
Notes the DREDge ↔ KS4 nblocks mutual exclusion:
- DREDge enabled in preprocess → set `nblocks=0` for KS4.
- DREDge disabled → set `nblocks=15` for KS4 internal drift correction.

Code cell:
- Shows `SortingConfig` construction with explicit `SorterConfig(params=SorterParams(nblocks=0))`.
- `SortStage(session, sorting_cfg).run()` is commented out with a GPU-requirement note.

### Section 06 — Results & Checkpoint Board

- **Visualization C — Unit count summary table**: pandas DataFrame built from
  `sort_{probe_id}.json` checkpoint files: `probe_id`, `n_units`, `mode`, `sorter_name`.
- **Visualization D — Checkpoint status board**: same code as Tutorial 01 Section 05, now
  showing the full set of `preprocess_*` and `sort_*` files colored by status.

### Section 07 — Future Capabilities (Placeholder cells)

Each placeholder follows the same pattern as Tutorial 01:
```python
# TODO: Available in Tutorial 03 — Curate
# This cell will show: [description]
# Requires: [module names]
raise NotImplementedError("...")
```

Placeholder cells planned:
1. **Quality metrics violin plots** — ISI violation ratio, amplitude cutoff per unit (curate stage).
2. **Waveform gallery** — mean ± SD waveforms for top-10 units by firing rate (postprocess stage).
3. **Aligned spike raster** — raster aligned to trial onset via `behavior_events.parquet` (synchronize + postprocess).

---

## 5. Visual Summary

| # | Visualization | Data Source | Module Required | Status |
|---|---------------|-------------|-----------------|--------|
| A | Raw vs. preprocessed AP traces | `SpikeGLXLoader.load_ap` + `si.load(zarr_path)` | `stages/preprocess.py` ✅ | Implemented |
| B | Bad channel summary table | `checkpoints/preprocess_{probe_id}.json` | `stages/preprocess.py` ✅ | Implemented |
| C | Unit count summary table | `checkpoints/sort_{probe_id}.json` | `stages/sort.py` ✅ | Implemented |
| D | Checkpoint status board | `output_dir/checkpoints/*.json` | `core/checkpoint.py` ✅ | Implemented |
| E | Quality metrics violin | SortingAnalyzer quality_metrics | `stages/curate.py` 🟡 | TODO stub |
| F | Waveform gallery | SortingAnalyzer waveforms | `stages/postprocess.py` 🟡 | TODO stub |
| G | Aligned spike raster | SortingAnalyzer + `behavior_events.parquet` | `stages/synchronize.py` 🟡 | TODO stub |

---

## 6. Dependencies

No new Python dependencies beyond `pyproject.toml`:
- `matplotlib` — transitive via spikeinterface
- `pandas` — transitive via spikeinterface
- `numpy` — transitive via spikeinterface
- `spikeinterface.core` — for `si.load(zarr_path)`

---

## 7. Data Requirements

The user must have:
- A valid SpikeGLX session directory (with at least one `*_imec0` subdirectory).
- A `monkeys/*.yaml` subject config file.
- For Section 04 (import mode): a completed Kilosort4 output folder from SpikeInterface.

---

## 8. What is NOT in this notebook

- No synchronize, curate, or postprocess (those are future tutorials).
- No mock/synthetic data — real data only (path-parameterized).
- No unit test coverage (tutorials are exploratory, not part of the test suite).
- No CLI invocation — shows the Python API directly.
