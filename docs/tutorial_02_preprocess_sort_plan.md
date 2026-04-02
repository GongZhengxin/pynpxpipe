# Tutorial 02 (Preprocess & Sort) Implementation Plan

**Goal:** Create `tutorials/02_preprocess_sort.ipynb` — a standalone tutorial covering
PreprocessStage (AP preprocessing chain) and SortStage (import + local modes), with 4
working visualizations and 3 future-stage placeholder cells. Follows the same style as
Tutorial 01.

**Architecture:** Single `.ipynb` file with 8 sections. Users edit one config cell at the
top (DATA_DIR, OUTPUT_DIR, SUBJECT_YAML, SORTED_PATHS). All code calls pynpxpipe's public
Python API directly. Future-stage cells use `raise NotImplementedError`.

**Tech Stack:** pynpxpipe (core/io/stages), matplotlib, pandas, numpy, SpikeInterface

---

## File Map

| Action | Path |
|--------|------|
| Create | `tutorials/02_preprocess_sort.ipynb` |
| Create | `docs/tutorial_02_preprocess_sort_design.md` |

---

### Task 1: Create notebook skeleton

- [ ] **Step 1: Create `tutorials/02_preprocess_sort.ipynb` with minimal JSON skeleton**

```json
{
 "cells": [],
 "metadata": {
  "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
  "language_info": {"name": "python", "version": "3.11.0"}
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
```

- [ ] **Step 2: Commit skeleton**

```bash
git add tutorials/02_preprocess_sort.ipynb docs/tutorial_02_preprocess_sort_design.md
git commit -m "feat(tutorials): add Tutorial 02 skeleton and design doc"
```

---

### Task 2: Section 00 — Title and Configuration

- [ ] **Step 1: Add title markdown cell (cell 0)**

```markdown
# Tutorial 02: Preprocess & Sort

This notebook covers Layer 2 of pynpxpipe:
**PreprocessStage** (AP signal preprocessing chain) and **SortStage** (Kilosort4).

By the end you will have:
- Preprocessed AP recordings saved as Zarr (phase_shift → bandpass → bad channels → CMR → motion correction)
- Spike sorting results saved as SpikeInterface Sorting objects
- Four visualizations: raw vs. preprocessed traces, bad channel summary, unit count table, checkpoint board

**Prerequisites:** A SpikeGLX recording folder on disk. For Section 04 (import mode) you also need a completed Kilosort4 output folder.

> **Note:** Section 05 (local sort) requires a CUDA-compatible GPU. Section 07 contains placeholder cells that intentionally raise `NotImplementedError`.

---
```

- [ ] **Step 2: Add configuration code cell (cell 1)**

```python
# === 用户配置区（修改这里）=========================================
# DATA_DIR:     SpikeGLX 录制根目录（含 *_g0/ 文件夹和 .bhv2 文件）
# OUTPUT_DIR:   处理结果输出目录（不存在会自动创建）
# SUBJECT_YAML: monkeys/*.yaml 对应实验动物配置文件
# SORTED_PATHS: （可选）Kilosort4 输出目录，仅 Section 04 import 模式使用

from pathlib import Path

DATA_DIR     = Path(r"C:\your\recording\root")     # <-- 修改这里
OUTPUT_DIR   = Path(r"C:\your\output")              # <-- 修改这里
SUBJECT_YAML = Path(r".\monkeys\YourMonkey.yaml")   # <-- 修改这里

# Optional: existing Kilosort4 output folders (for Section 04 import mode)
# Format: {"probe_id": Path("path/to/ks4/output/for/that/probe")}
SORTED_PATHS = {
    "imec0": Path(r"C:\your\kilosort4\imec0"),      # <-- 修改这里（或留空跳过 Section 04）
}
# ===================================================================

# Validate paths
issues = []
if not DATA_DIR.exists():
    issues.append(f"❌ DATA_DIR not found: {DATA_DIR}")
if not SUBJECT_YAML.exists():
    issues.append(f"❌ SUBJECT_YAML not found: {SUBJECT_YAML}")

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

if issues:
    for msg in issues:
        print(msg)
    raise SystemExit("请修改上方配置区中的路径，再重新运行此 cell。")

print("✅ 路径验证通过")
print(f"   DATA_DIR     = {DATA_DIR}")
print(f"   OUTPUT_DIR   = {OUTPUT_DIR}")
print(f"   SUBJECT_YAML = {SUBJECT_YAML}")
```

- [ ] **Step 3: Commit**

```bash
git add tutorials/02_preprocess_sort.ipynb
git commit -m "feat(tutorials): add Tutorial 02 config section"
```

---

### Task 3: Section 01 — Setup

- [ ] **Step 1: Add section header markdown cell**

```markdown
## Section 01: Setup

Quick setup — Session creation + DiscoverStage. For a full walkthrough of this section,
see **Tutorial 01**.

`DiscoverStage.run()` is checkpoint-aware: if you already ran Tutorial 01 with the same
`OUTPUT_DIR`, it returns immediately without re-discovering.
```

- [ ] **Step 2: Add setup code cell**

```python
from pynpxpipe.core.config import load_subject_config
from pynpxpipe.core.session import SessionManager
from pynpxpipe.core.logging import setup_logging
from pynpxpipe.stages.discover import DiscoverStage

subject = load_subject_config(SUBJECT_YAML)
session = SessionManager.from_data_dir(DATA_DIR, subject, OUTPUT_DIR)
setup_logging(session.log_path)

DiscoverStage(session).run()

print(f"Session : {session.session_dir.name}")
print(f"Output  : {session.output_dir}")
print(f"Probes  : {[p.probe_id for p in session.probes]}")
```

- [ ] **Step 3: Commit**

```bash
git add tutorials/02_preprocess_sort.ipynb
git commit -m "feat(tutorials): add Tutorial 02 setup section"
```

---

### Task 4: Section 02 — PreprocessStage

- [ ] **Step 1: Add section header markdown cell**

```markdown
## Section 02: PreprocessStage

The preprocessing chain applies **six steps per probe in strict order**:

| Step | SpikeInterface call | Why this order |
|------|---------------------|----------------|
| 1 | `phase_shift` | Corrects Neuropixels ADC time-division multiplexed offsets. **Must be first** — placing it after filtering degrades CMR effectiveness |
| 2 | `bandpass_filter` | Passes 300–6000 Hz. Removes slow drift (LFP) and high-frequency noise |
| 3 | `detect_bad_channels` | Uses coherence+PSD on *filtered* data — more accurate than on raw |
| 4 | `remove_channels` | Drops bad channels **before** CMR so they don't contaminate the reference |
| 5 | `common_reference (CMR)` | Global median reference: removes common-mode noise across all good channels |
| 6 | `correct_motion` (optional) | DREDge drift correction (default: enabled). **Mutually exclusive** with KS4 `nblocks > 0` |

Each probe is processed serially. After each probe: `del recording; gc.collect()` — AP `.bin`
files can be 400–500 GB; lazy SpikeInterface recordings must be explicitly released.

**DREDge ↔ KS4 nblocks constraint:**
Choose one drift correction strategy:
- **DREDge (default):** Enable in preprocess, set `nblocks=0` in KS4.
- **KS4 internal:** Disable DREDge (`method=None`), set `nblocks=15` in KS4.
```

- [ ] **Step 2: Add default run code cell**

```python
from pynpxpipe.stages.preprocess import PreprocessStage

# Default config: 300–6000 Hz bandpass, DREDge motion correction enabled, nblocks=0 for KS4
stage = PreprocessStage(session)
stage.run()

# Verify Zarr output exists for each probe
for probe in session.probes:
    zarr_path = session.output_dir / "preprocessed" / probe.probe_id
    status = "✅" if zarr_path.exists() else "❌ missing"
    print(f"  {probe.probe_id}: {status}  →  {zarr_path}")
```

- [ ] **Step 3: Add custom config example code cell**

```python
# Alternative: disable DREDge (use KS4 internal drift correction instead)
# In this case, set nblocks=15 in SortStage (see Section 05)
from pynpxpipe.core.config import PipelineConfig, PreprocessConfig, MotionCorrectionConfig

cfg_no_dredge = PipelineConfig(
    preprocess=PreprocessConfig(
        motion_correction=MotionCorrectionConfig(method=None)  # disable DREDge
    )
)

# Uncomment to run with this config instead:
# PreprocessStage(session, cfg_no_dredge).run()

print("ℹ️  Custom config (DREDge disabled) shown above — commented out.")
print("    Use this if you want KS4 to handle drift internally (nblocks=15).")
```

- [ ] **Step 4: Commit**

```bash
git add tutorials/02_preprocess_sort.ipynb
git commit -m "feat(tutorials): add PreprocessStage section"
```

---

### Task 5: Section 03 — Preprocessed Data Inspection

- [ ] **Step 1: Add section header markdown cell**

```markdown
## Section 03: Preprocessed Data Inspection

### Visualization A: Raw vs. Preprocessed AP Traces

Both recordings are loaded lazily — no full file is read into RAM.
Only the requested chunk (10 channels × 0.5 s) is actually fetched from disk.

- **Left column (Raw):** Phase-locked LFP visible, large common-mode noise.
- **Right column (Preprocessed):** Bandpass filtered, CMR applied, motion corrected.
  Spikes appear as sharp transients.

### Visualization B: Bad Channel Summary

Built from the per-probe checkpoint written by `PreprocessStage`. Shows how many
channels were flagged as noisy/dead (coherence + PSD analysis on filtered data).
```

- [ ] **Step 2: Add visualization A code cell**

```python
import matplotlib.pyplot as plt
import numpy as np
import spikeinterface.core as si

from pynpxpipe.io.spikeglx import SpikeGLXLoader

probe = session.probes[0]  # first probe
N_CHANNELS_SHOW = 10
T_DURATION_S    = 0.5      # seconds to display

# --- Load recordings lazily (no data read yet) ---
raw_rec  = SpikeGLXLoader.load_ap(probe)
zarr_path = session.output_dir / "preprocessed" / probe.probe_id
prep_rec = si.load(zarr_path)

fs       = raw_rec.get_sampling_frequency()
n_frames = int(T_DURATION_S * fs)

# Pick N_CHANNELS_SHOW channels from the middle of the preprocessed recording
prep_ch = prep_rec.get_channel_ids()
mid     = len(prep_ch) // 2
ch_show = prep_ch[mid : mid + min(N_CHANNELS_SHOW, len(prep_ch) - mid)]

# Fetch traces (only the selected channels and time window)
raw_tr  = raw_rec.get_traces(start_frame=0, end_frame=n_frames, channel_ids=ch_show)
prep_tr = prep_rec.get_traces(start_frame=0, end_frame=n_frames, channel_ids=ch_show)
t = np.arange(n_frames) / fs

n_show = len(ch_show)
fig, axes = plt.subplots(n_show, 2, figsize=(14, n_show * 1.1), sharex=True)
if n_show == 1:
    axes = axes[np.newaxis, :]

for row in range(n_show):
    ch_id = ch_show[row]

    axes[row, 0].plot(t, raw_tr[:, row], lw=0.5, color="steelblue")
    axes[row, 0].set_ylabel(ch_id, fontsize=7, rotation=0, labelpad=38, va="center")
    axes[row, 0].spines[["top", "right"]].set_visible(False)

    axes[row, 1].plot(t, prep_tr[:, row], lw=0.5, color="darkorange")
    axes[row, 1].spines[["top", "right"]].set_visible(False)

axes[0, 0].set_title("Raw AP", fontsize=11)
axes[0, 1].set_title("Preprocessed (filtered + CMR)", fontsize=11)
axes[-1, 0].set_xlabel("Time (s)")
axes[-1, 1].set_xlabel("Time (s)")
fig.suptitle(
    f"Probe {probe.probe_id} — {n_show} channels × {T_DURATION_S:.1f} s "
    f"(lazy-loaded: only this chunk read from disk)",
    fontsize=11, y=1.01
)
plt.tight_layout()
plt.show()
```

- [ ] **Step 3: Add visualization B code cell**

```python
import json
import pandas as pd
from IPython.display import display

rows = []
for probe in session.probes:
    cp_path = session.output_dir / "checkpoints" / f"preprocess_{probe.probe_id}.json"
    if cp_path.exists():
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        rows.append({
            "probe_id":       probe.probe_id,
            "n_ch_original":  data.get("n_channels_original", "—"),
            "n_bad":          data.get("n_bad_channels", "—"),
            "n_ch_after":     data.get("n_channels_after_bad_removal", "—"),
            "freq_min_Hz":    data.get("freq_min", "—"),
            "freq_max_Hz":    data.get("freq_max", "—"),
            "motion_method":  data.get("motion_correction_method") or "disabled",
        })
    else:
        rows.append({"probe_id": probe.probe_id, "n_ch_original": "checkpoint missing"})

df_preprocess = pd.DataFrame(rows).set_index("probe_id")
display(df_preprocess)
```

- [ ] **Step 4: Commit**

```bash
git add tutorials/02_preprocess_sort.ipynb
git commit -m "feat(tutorials): add preprocessed data inspection section"
```

---

### Task 6: Section 04 — SortStage: Import Mode

- [ ] **Step 1: Add section header markdown cell**

```markdown
## Section 04: SortStage — Import Mode

**Import mode** loads an externally computed Kilosort4 (or Phy) sorting result from disk.
This is the typical workflow when:
- Kilosort4 was run on a Windows lab PC with a dedicated GPU.
- You copied the KS4 output folder to this machine.
- You want to use pynpxpipe's curate/postprocess/export pipeline downstream.

`SortStage` validates the path, loads the result via SpikeInterface
(`ss.read_sorter_folder` for KS4 format, `se.read_phy` for Phy format),
saves it as a `binary_folder` Sorting object, and writes a checkpoint.

> **Before running this section:** Update `SORTED_PATHS` in Section 00 to point
> to your actual Kilosort4 output folders.
```

- [ ] **Step 2: Add import mode code cell**

```python
from pynpxpipe.core.config import SortingConfig, ImportConfig
from pynpxpipe.stages.sort import SortStage

sorting_cfg = SortingConfig(
    mode="import",
    import_cfg=ImportConfig(
        format="kilosort4",
        paths=SORTED_PATHS,   # from Section 00 config cell
    ),
)

SortStage(session, sorting_cfg).run()

# Verify sorted output exists for each probe
for probe in session.probes:
    sorted_path = session.output_dir / "sorted" / probe.probe_id
    status = "✅" if sorted_path.exists() else "❌ missing"
    print(f"  {probe.probe_id}: {status}  →  {sorted_path}")
```

- [ ] **Step 3: Commit**

```bash
git add tutorials/02_preprocess_sort.ipynb
git commit -m "feat(tutorials): add SortStage import mode section"
```

---

### Task 7: Section 05 — SortStage: Local Mode

- [ ] **Step 1: Add section header markdown cell**

```markdown
## Section 05: SortStage — Local Mode

**Local mode** runs Kilosort4 directly on this machine via SpikeInterface. This requires:
- A CUDA-compatible GPU (≥ 8 GB VRAM recommended for NP1.0 probes at 30 kHz).
- `kilosort` Python package installed (`uv add kilosort`).
- Preprocessed Zarr recordings from Section 02.

**nblocks constraint:** Set `nblocks=0` if PreprocessStage ran DREDge motion correction
(the default). Set `nblocks=15` if PreprocessStage had `motion_correction.method=None`.
Running both simultaneously applies double drift correction and degrades results.

The `SortStage` always processes probes serially regardless of `parallel.enabled` in
`PipelineConfig` — spike sorting requires exclusive GPU access.

The code cell below is **commented out**. Run it manually if you have a compatible GPU.
Expected runtime: 20–60 minutes per probe depending on recording length and GPU model.
```

- [ ] **Step 2: Add local mode code cell**

```python
from pynpxpipe.core.config import SortingConfig, SorterConfig, SorterParams
from pynpxpipe.stages.sort import SortStage

# Config for DREDge-preprocessed data (nblocks=0 disables KS4 internal drift correction)
sorting_cfg_local = SortingConfig(
    mode="local",
    sorter=SorterConfig(
        name="kilosort4",
        params=SorterParams(
            nblocks=0,    # DREDge already handled drift in Section 02
            do_CAR=False, # CMR already applied in Section 02
            batch_size=65536,  # increase if GPU has more VRAM
        ),
    ),
)

# Uncomment to run (requires CUDA GPU, ~20-60 min per probe):
# SortStage(session, sorting_cfg_local).run()

print("⚠️  Local sort is commented out.")
print("    Uncomment and run manually if you have a CUDA-compatible GPU.")
print("    Or use import mode (Section 04) if you already have KS4 output.")
```

- [ ] **Step 3: Commit**

```bash
git add tutorials/02_preprocess_sort.ipynb
git commit -m "feat(tutorials): add SortStage local mode section"
```

---

### Task 8: Section 06 — Results & Checkpoint Board

- [ ] **Step 1: Add section header markdown cell**

```markdown
## Section 06: Results & Checkpoint Board

### Visualization C: Sorting Results

Unit counts and sorting metadata from per-probe sort checkpoints.

### Visualization D: Checkpoint Status Board

Full checkpoint board showing all stages completed so far.
Green = completed, red = failed, missing = not yet run.
```

- [ ] **Step 2: Add visualization C code cell**

```python
import json
import pandas as pd
from IPython.display import display

rows = []
for probe in session.probes:
    cp_path = session.output_dir / "checkpoints" / f"sort_{probe.probe_id}.json"
    if cp_path.exists():
        data = json.loads(cp_path.read_text(encoding="utf-8"))
        rows.append({
            "probe_id":    probe.probe_id,
            "n_units":     data.get("n_units", "—"),
            "mode":        data.get("mode", "—"),
            "sorter_name": data.get("sorter_name", "—"),
            "output_path": data.get("output_path", "—"),
        })
    else:
        rows.append({"probe_id": probe.probe_id, "n_units": "checkpoint missing"})

df_sort = pd.DataFrame(rows).set_index("probe_id")
display(df_sort)
```

- [ ] **Step 3: Add visualization D code cell**

```python
import json
import pandas as pd
from IPython.display import display
from pathlib import Path

checkpoints_dir = session.output_dir / "checkpoints"

rows = []
for cp_file in sorted(checkpoints_dir.glob("*.json")):
    data = json.loads(cp_file.read_text(encoding="utf-8"))
    rows.append({
        "file":         cp_file.name,
        "stage":        data.get("stage", "—"),
        "status":       data.get("status", "—"),
        "completed_at": data.get("completed_at", "—"),
    })

if rows:
    df_cp = pd.DataFrame(rows).set_index("file")
    display(df_cp.style.map(
        lambda v: "color: green" if v == "completed" else
                  ("color: red" if v == "failed" else ""),
        subset=["status"]
    ))
else:
    print("No checkpoint files found yet.")
```

- [ ] **Step 4: Commit**

```bash
git add tutorials/02_preprocess_sort.ipynb
git commit -m "feat(tutorials): add results and checkpoint board section"
```

---

### Task 9: Section 07 — Future Capabilities (Placeholder Cells)

- [ ] **Step 1: Add section header markdown cell**

```markdown
## Section 07: Future Capabilities

Placeholder cells for pipeline stages not yet implemented. Each raises
`NotImplementedError` with a pointer to the relevant spec.
```

- [ ] **Step 2: Add quality metrics placeholder**

```python
# TODO: Available once stages/curate.py is implemented
#
# This cell will show:
#   Violin plots of quality metrics per unit — ISI violation ratio,
#   amplitude cutoff, presence ratio, SNR — for each probe.
#   Units classified by Bombcell: "good" / "mua" / "noise" / "non_soma_mua".
#   Data source: SortingAnalyzer quality_metrics (written by curate stage)
#
# See: docs/specs/curate.md
raise NotImplementedError(
    "Curate stage not yet implemented. "
    "Run Tutorial 03 (Curate + Postprocess) when available."
)
```

- [ ] **Step 3: Add waveform gallery placeholder**

```python
# TODO: Available once stages/postprocess.py is implemented
#
# This cell will show:
#   Mean ± SD waveforms for the top-10 units by firing rate (one panel per unit).
#   Shows the template waveform across all channels, with the peak channel highlighted.
#   Data source: SortingAnalyzer waveforms (written by postprocess stage)
#
# See: docs/specs/postprocess.md
raise NotImplementedError(
    "Postprocess stage not yet implemented. "
    "Run Tutorial 03 (Curate + Postprocess) when available."
)
```

- [ ] **Step 4: Add aligned raster placeholder**

```python
# TODO: Available once stages/synchronize.py + stages/postprocess.py are implemented
#
# This cell will show:
#   Spike raster for the top-N units aligned to trial stimulus onset.
#   X axis: time relative to stimulus onset (ms). Y axis: unit index.
#   Colored by experimental condition.
#   Data sources: SortingAnalyzer spike trains + behavior_events.parquet (synchronize stage)
#
# See: docs/specs/synchronize.md, docs/specs/postprocess.md
raise NotImplementedError(
    "Synchronize + postprocess stages not yet implemented. "
    "Run Tutorial 03 (Synchronize) and Tutorial 04 (Postprocess) when available."
)
```

- [ ] **Step 5: Commit**

```bash
git add tutorials/02_preprocess_sort.ipynb
git commit -m "feat(tutorials): add Tutorial 02 future-stage placeholder cells"
```

---

## Self-Review

### Spec Coverage

| Spec Section | Covered By |
|---|---|
| Section 00 — Config cell (DATA_DIR, OUTPUT_DIR, SUBJECT_YAML, SORTED_PATHS) | Task 2 |
| Section 01 — Brief session + discover | Task 3 |
| Section 02 — PreprocessStage (default + custom config) | Task 4 |
| Section 03 — Viz A (raw vs preprocessed) + Viz B (bad channels) | Task 5 |
| Section 04 — SortStage import mode | Task 6 |
| Section 05 — SortStage local mode (instructional, commented out) | Task 7 |
| Section 06 — Viz C (unit counts) + Viz D (checkpoint board) | Task 8 |
| Section 07 — 3 future placeholder cells | Task 9 |

All spec requirements covered. ✅

### Type/API Consistency Check

- `PreprocessStage(session)` → uses `PipelineConfig()` defaults ✅
- `PreprocessStage(session, pipeline_config)` → custom bandpass/motion_correction ✅
- `si.load(zarr_path)` → lazy `BaseRecording` from Zarr ✅
- `SortingConfig(mode="import", import_cfg=ImportConfig(...))` ✅
- `SortStage(session, sorting_cfg).run()` ✅
- `SortingConfig(mode="local", sorter=SorterConfig(params=SorterParams(nblocks=0)))` ✅
- `raw_rec.get_traces(start_frame=0, end_frame=n, channel_ids=ch_list)` ✅
- Checkpoint paths: `checkpoints/preprocess_{probe_id}.json`, `checkpoints/sort_{probe_id}.json` ✅
