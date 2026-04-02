# Tutorial 01 (Discover Pipeline) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `tutorials/01_discover_pipeline.ipynb` — an end-to-end tutorial notebook guiding new team members from Session setup through DiscoverStage, with 5 working visualizations and 4 future-stage placeholder cells.

**Architecture:** Single `.ipynb` file with 7 sections (cells). Users edit one config cell at the top (DATA_DIR, OUTPUT_DIR, SUBJECT_YAML). All code calls pynpxpipe's public Python API directly (no CLI). Future-stage cells use `raise NotImplementedError` with explanatory comments.

**Tech Stack:** pynpxpipe (core/io/stages), matplotlib, pandas, SpikeInterface BaseRecording

---

## File Map

| Action | Path |
|--------|------|
| Create | `tutorials/01_discover_pipeline.ipynb` |

---

### Task 1: Create `tutorials/` directory and notebook skeleton

**Files:**
- Create: `tutorials/01_discover_pipeline.ipynb`

- [ ] **Step 1: Create the tutorials directory and empty notebook file**

Run:
```bash
mkdir -p tutorials
```

Then create `tutorials/01_discover_pipeline.ipynb` with this minimal JSON skeleton:

```json
{
 "cells": [],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "name": "python",
   "version": "3.11.0"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
```

- [ ] **Step 2: Commit skeleton**

```bash
git add tutorials/01_discover_pipeline.ipynb
git commit -m "feat(tutorials): add notebook skeleton"
```

---

### Task 2: Section 00 — Title and Configuration

**Files:**
- Modify: `tutorials/01_discover_pipeline.ipynb`

- [ ] **Step 1: Add title markdown cell (cell 0)**

Content:
```markdown
# Tutorial 01: Discover Pipeline

This notebook walks through the first two layers of pynpxpipe:
**Core infrastructure** (Session, config, logging) and **IO + Discover stage**.

By the end you will have:
- A fully initialized `Session` object
- `session.probes` populated with your recording's probe metadata
- Five visualizations of your data
- An understanding of how checkpoints enable resume-on-failure

**Prerequisites:** A SpikeGLX recording folder and a `.bhv2` behavioral file on disk.

---
```

- [ ] **Step 2: Add configuration code cell (cell 1)**

Content:
```python
# === 用户配置区（修改这里）===========================================
# DATA_DIR: 根目录，需包含 SpikeGLX gate 文件夹（*_g0/ 等）和 .bhv2 文件
# OUTPUT_DIR: 处理结果输出目录（不存在会自动创建）
# SUBJECT_YAML: monkeys/*.yaml 中对应实验动物的配置文件

from pathlib import Path

DATA_DIR     = Path(r"C:\your\recording\root")   # <-- 修改这里
OUTPUT_DIR   = Path(r"C:\your\output")            # <-- 修改这里
SUBJECT_YAML = Path(r".\monkeys\YourMonkey.yaml") # <-- 修改这里
# =====================================================================

# Validate — friendly error messages instead of raw Python tracebacks
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

- [ ] **Step 3: Verify cell runs (open notebook in Jupyter, run cell 1)**

Expected output:
```
✅ 路径验证通过
   DATA_DIR     = C:\your\recording\root
   OUTPUT_DIR   = C:\your\output
   SUBJECT_YAML = .\monkeys\YourMonkey.yaml
```

- [ ] **Step 4: Commit**

```bash
git add tutorials/01_discover_pipeline.ipynb
git commit -m "feat(tutorials): add config section"
```

---

### Task 3: Section 01 — Session Setup

**Files:**
- Modify: `tutorials/01_discover_pipeline.ipynb`

- [ ] **Step 1: Add section header markdown cell**

Content:
```markdown
## Section 01: Session Setup

`Session` is pynpxpipe's central state object — a plain Python dataclass passed
through every stage. It holds paths, subject metadata, the probe list (populated
by DiscoverStage), and per-stage checkpoint status.

`SessionManager.from_data_dir()` auto-discovers the SpikeGLX gate folder
(`*_g0/` etc.) and the `.bhv2` file within `DATA_DIR`, then creates the output
directory structure and initializes logging.

**Design note:** `Session` has zero UI dependencies — no `click`, no `print`.
This means the same `Session` object works identically whether called from CLI,
this notebook, or a future GUI frontend.
```

- [ ] **Step 2: Add session creation code cell**

Content:
```python
from pynpxpipe.core.config import load_subject_config
from pynpxpipe.core.session import Session, SessionManager
from pynpxpipe.core.logging import setup_logging

# 1. Load subject metadata from YAML
subject = load_subject_config(SUBJECT_YAML)
print(f"Subject loaded: {subject.subject_id} ({subject.species}, {subject.sex}, {subject.age})")

# 2. Create session — auto-discovers gate dir and .bhv2 inside DATA_DIR
#    Also creates: OUTPUT_DIR/checkpoints/, OUTPUT_DIR/logs/
session = SessionManager.from_data_dir(
    data_dir=DATA_DIR,
    subject=subject,
    output_dir=OUTPUT_DIR,
)
print(f"\nSession created:")
print(f"  session_dir : {session.session_dir}")
print(f"  output_dir  : {session.output_dir}")
print(f"  bhv_file    : {session.bhv_file}")
print(f"  probes      : {len(session.probes)} (populated after DiscoverStage)")

# 3. Setup structured logging (writes to OUTPUT_DIR/logs/*.log)
#    After this call, all stage output goes to the log file as JSON Lines.
setup_logging(session.log_path)
print(f"\nLogging to: {session.log_path}")
```

- [ ] **Step 3: Verify cell runs**

Expected output:
```
Subject loaded: MaoDan (Macaca mulatta, M, P4Y)

Session created:
  session_dir : C:\your\recording\root\session_g0
  output_dir  : C:\your\output
  bhv_file    : C:\your\recording\root\session.bhv2
  probes      : 0 (populated after DiscoverStage)

Logging to: C:\your\output\logs\pynpxpipe_session_g0.log
```

- [ ] **Step 4: Commit**

```bash
git add tutorials/01_discover_pipeline.ipynb
git commit -m "feat(tutorials): add session setup section"
```

---

### Task 4: Section 02 — SpikeGLX IO and Raw NIDQ Visualization

**Files:**
- Modify: `tutorials/01_discover_pipeline.ipynb`

- [ ] **Step 1: Add section header markdown cell**

Content:
```markdown
## Section 02: SpikeGLX Data Discovery (IO Layer)

`SpikeGLXDiscovery` scans the session directory and returns metadata for each
probe — **without loading any `.bin` data**. The `.bin` files can be 400-500 GB;
lazy loading via SpikeInterface means only the metadata is read until you
explicitly request traces.

`SpikeGLXLoader.load_nidq()` returns a lazy `BaseRecording`. Only when you call
`get_traces()` does data actually move from disk to RAM — and only the requested
chunk.
```

- [ ] **Step 2: Add discovery and NIDQ raw plot code cell**

Content:
```python
import matplotlib.pyplot as plt
import numpy as np
from pynpxpipe.io.spikeglx import SpikeGLXDiscovery, SpikeGLXLoader

# --- 1. Discover all probes (reads .meta, not .bin) ---
discovery = SpikeGLXDiscovery(session.session_dir)
probes = discovery.discover_probes()
print(f"Found {len(probes)} probe(s):")
for p in probes:
    print(f"  {p.probe_id}: {p.probe_type}, SN={p.serial_number}, "
          f"{p.n_channels} ch @ {p.sample_rate/1000:.1f} kHz")

# --- 2. Discover NIDQ ---
nidq_bin, nidq_meta = discovery.discover_nidq()
print(f"\nNIDQ: {nidq_bin.name}")

# --- 3. Lazy-load NIDQ (no data read yet) ---
nidq_rec = SpikeGLXLoader.load_nidq(nidq_bin, nidq_meta)
fs        = nidq_rec.get_sampling_frequency()
ch_ids    = nidq_rec.get_channel_ids()
print(f"NIDQ: {len(ch_ids)} channels @ {fs:.0f} Hz")
print(f"Channels: {list(ch_ids)}")

# --- 4. Visualization A: Raw NIDQ — first 5 seconds ---
n_samples = int(5 * fs)
traces    = nidq_rec.get_traces(start_frame=0, end_frame=n_samples)  # shape: (n_samples, n_ch)
t         = np.arange(n_samples) / fs

fig, axes = plt.subplots(len(ch_ids), 1, figsize=(14, 2 * len(ch_ids)), sharex=True)
if len(ch_ids) == 1:
    axes = [axes]

for ax, ch_name, col in zip(axes, ch_ids, traces.T):
    ax.plot(t, col, lw=0.6)
    ax.set_ylabel(ch_name, fontsize=8, rotation=0, labelpad=40, va="center")
    ax.spines[["top", "right"]].set_visible(False)

axes[-1].set_xlabel("Time (s)")
fig.suptitle("Raw NIDQ Signal — First 5 seconds", y=1.01)
plt.tight_layout()
plt.show()
print("\n💡 注意：traces 仅从磁盘读取了前 5 秒的数据，.bin 文件其余内容未加载。")
```

- [ ] **Step 3: Verify cell runs**

Expected: printed probe/NIDQ summary + stacked time-series plot with one row per NIDQ channel.

- [ ] **Step 4: Commit**

```bash
git add tutorials/01_discover_pipeline.ipynb
git commit -m "feat(tutorials): add NIDQ raw signal visualization"
```

---

### Task 5: Section 03 — DiscoverStage

**Files:**
- Modify: `tutorials/01_discover_pipeline.ipynb`

- [ ] **Step 1: Add section header markdown cell**

Content:
```markdown
## Section 03: DiscoverStage

`DiscoverStage` wraps the IO-layer discovery in the pipeline's stage protocol:
it checks for a completed checkpoint first (skip if done), runs discovery,
validates probe + NIDQ + BHV2 integrity, populates `session.probes`, writes
`session_info.json`, and saves a checkpoint.

Every stage follows this same contract: **checkpoint-first, fail-fast, structured log.**
```

- [ ] **Step 2: Add DiscoverStage code cell**

Content:
```python
import json
from pynpxpipe.stages.discover import DiscoverStage

stage = DiscoverStage(session)
stage.run()

print(f"session.probes populated: {len(session.probes)} probe(s)")
for p in session.probes:
    print(f"  {p.probe_id}: {p.n_channels} channels, {p.sample_rate/1000:.1f} kHz")

# Read and display session_info.json
session_info_path = session.output_dir / "session_info.json"
session_info = json.loads(session_info_path.read_text(encoding="utf-8"))
print("\nsession_info.json:")
print(json.dumps(session_info, indent=2))
```

- [ ] **Step 3: Verify cell runs**

Expected: `session.probes` populated with real probe metadata + printed `session_info.json`.

- [ ] **Step 4: Commit**

```bash
git add tutorials/01_discover_pipeline.ipynb
git commit -m "feat(tutorials): add DiscoverStage section"
```

---

### Task 6: Section 04 — Probe Visualizations

**Files:**
- Modify: `tutorials/01_discover_pipeline.ipynb`

- [ ] **Step 1: Add section header markdown cell**

Content:
```markdown
## Section 04: Probe Visualizations

### Visualization B: Channel Position Map

Neuropixels probes have a fixed electrode layout. The positions (in micrometers)
are embedded in the SpikeInterface recording object — accessible via
`recording.get_probe().contact_positions`. Each row is `[x, y]` where y increases
from tip to base.

### Visualization C: Probe Metadata Table

A quick reference table of all probes: type, serial number, sample rate,
channel count.
```

- [ ] **Step 2: Add probe visualization code cell**

Content:
```python
import pandas as pd
import matplotlib.pyplot as plt
from pynpxpipe.io.spikeglx import SpikeGLXLoader

n_probes = len(session.probes)
fig, axes = plt.subplots(1, n_probes, figsize=(4 * n_probes, 8),
                         squeeze=False)

for col, probe in enumerate(session.probes):
    # Load AP recording lazily just to get probe geometry
    rec = SpikeGLXLoader.load_ap(probe)
    si_probe = rec.get_probe()
    positions = si_probe.contact_positions  # shape: (n_ch, 2)

    ax = axes[0][col]
    ax.scatter(positions[:, 0], positions[:, 1], s=15, c=positions[:, 1],
               cmap="viridis", edgecolors="none")
    ax.set_title(f"{probe.probe_id}\n{probe.probe_type}", fontsize=10)
    ax.set_xlabel("x (µm)")
    if col == 0:
        ax.set_ylabel("y (µm, 0 = tip)")
    ax.spines[["top", "right"]].set_visible(False)

fig.suptitle("Probe Channel Positions", fontsize=13)
plt.tight_layout()
plt.show()

# Visualization C: metadata table
rows = [
    {
        "probe_id":      p.probe_id,
        "probe_type":    p.probe_type,
        "serial_number": p.serial_number,
        "sample_rate":   f"{p.sample_rate/1000:.1f} kHz",
        "n_channels":    p.n_channels,
        "lf_present":    p.lf_bin is not None,
    }
    for p in session.probes
]
df = pd.DataFrame(rows).set_index("probe_id")
display(df)
```

- [ ] **Step 3: Verify cell runs**

Expected: scatter plot(s) of electrode positions + styled DataFrame table.

- [ ] **Step 4: Commit**

```bash
git add tutorials/01_discover_pipeline.ipynb
git commit -m "feat(tutorials): add probe visualizations"
```

---

### Task 7: Section 05 — Checkpoint & Resume

**Files:**
- Modify: `tutorials/01_discover_pipeline.ipynb`

- [ ] **Step 1: Add section header markdown cell**

Content:
```markdown
## Section 05: Checkpoint & Resume

Every stage writes a JSON checkpoint to `{output_dir}/checkpoints/` on completion.
When a stage is re-run, it reads the checkpoint first — if status is `"completed"`,
it returns immediately without reprocessing.

This means you can kill the pipeline mid-run (power failure, `Ctrl-C`) and
re-launch: completed stages are skipped, the interrupted stage restarts from
the beginning of that stage, and earlier stages do not re-run.
```

- [ ] **Step 2: Add checkpoint visualization code cell**

Content:
```python
import json
from pathlib import Path

checkpoints_dir = session.output_dir / "checkpoints"

# Visualization D: checkpoint status board
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
    display(df_cp.style.applymap(
        lambda v: "color: green" if v == "completed" else
                  ("color: red" if v == "failed" else ""),
        subset=["status"]
    ))
else:
    print("No checkpoint files found yet.")

print("\n--- Demonstrating resume: running DiscoverStage a second time ---")
stage2 = DiscoverStage(session)
stage2.run()
print("(returned immediately — checkpoint already complete)")
```

- [ ] **Step 3: Verify cell runs**

Expected: colored checkpoint table showing `discover.json: completed` + "returned immediately" print.

- [ ] **Step 4: Commit**

```bash
git add tutorials/01_discover_pipeline.ipynb
git commit -m "feat(tutorials): add checkpoint resume section"
```

---

### Task 8: Section 06 — Structured Logging

**Files:**
- Modify: `tutorials/01_discover_pipeline.ipynb`

- [ ] **Step 1: Add section header markdown cell**

Content:
```markdown
## Section 06: Structured Logging

All pipeline stages write **JSON Lines** (one JSON object per line) to
`session.log_path`. This makes logs both human-readable and machine-parseable —
you can `grep`, `jq`, or load them into pandas for analysis.

Each log entry always contains: `timestamp`, `level`, `logger`, `event`.
Stage entries also contain: `stage`, `probe_id`, `status`, `elapsed_s`.
```

- [ ] **Step 2: Add log display code cell**

Content:
```python
import json
import pandas as pd

log_path = session.log_path
if not log_path.exists():
    print(f"Log file not found: {log_path}")
else:
    lines = log_path.read_text(encoding="utf-8").splitlines()
    records = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # skip malformed lines

    if records:
        # Visualization E: log table
        df_log = pd.DataFrame(records)
        # Keep only the most informative columns if present
        cols = [c for c in ["timestamp", "level", "stage", "probe_id", "event", "elapsed_s", "status"]
                if c in df_log.columns]
        display(df_log[cols].tail(30))
        print(f"\nTotal log entries: {len(records)}")
    else:
        print("Log file is empty.")
```

- [ ] **Step 3: Verify cell runs**

Expected: table of the last 30 log entries with columns timestamp/level/stage/event/elapsed_s/status.

- [ ] **Step 4: Commit**

```bash
git add tutorials/01_discover_pipeline.ipynb
git commit -m "feat(tutorials): add structured logging section"
```

---

### Task 9: Section 07 — Future Capabilities (Placeholder Cells)

**Files:**
- Modify: `tutorials/01_discover_pipeline.ipynb`

- [ ] **Step 1: Add section header markdown cell**

Content:
```markdown
## Section 07: Future Capabilities

The cells below show what the tutorial will contain once the corresponding
pipeline stages are implemented. Each cell raises `NotImplementedError` with a
pointer to the relevant spec. They are here so new team members can see the full
picture of what the pipeline produces — not just the current state.
```

- [ ] **Step 2: Add eye fixation placeholder cell**

Content:
```python
# TODO: Available once io/bhv.py + stages/synchronize.py are implemented
#
# This cell will show:
#   Eye fixation scatter plot — X/Y gaze position for every trial,
#   colored by experimental condition.
#   Data source: behavior_events.parquet (written by synchronize stage)
#
# See: docs/specs/bhv.md, docs/specs/synchronize.md
raise NotImplementedError(
    "BHV2 parsing not yet implemented. "
    "Run Tutorial 03 (Synchronize) when available."
)
```

- [ ] **Step 3: Add trial-averaged photodiode placeholder cell**

Content:
```python
# TODO: Available once stages/synchronize.py is implemented
#
# This cell will show:
#   Trial-averaged photodiode voltage trace — mean ± SEM per condition,
#   aligned to trial onset using sync_tables.json.
#   Raw signal is already accessible (see Section 02), but trial alignment
#   requires the synchronize stage output.
#
# See: docs/specs/synchronize.md, docs/specs/photodiode_calibrate.md
raise NotImplementedError(
    "Trial alignment not yet implemented. "
    "Run Tutorial 03 (Synchronize) when available."
)
```

- [ ] **Step 4: Add image repetition histogram placeholder cell**

Content:
```python
# TODO: Available once io/bhv.py is implemented
#
# This cell will show:
#   Bar chart of how many times each image stimulus was shown,
#   to verify the experimental design (e.g., 10 repeats × 100 images).
#   Data source: behavior_events.parquet, column "stimulus_id"
#
# See: docs/specs/bhv.md
raise NotImplementedError(
    "BHV2 parsing not yet implemented. "
    "Run Tutorial 03 (Synchronize) when available."
)
```

- [ ] **Step 5: Add spike raster placeholder cell**

Content:
```python
# TODO: Available once stages/sort.py + stages/postprocess.py are implemented
#
# This cell will show:
#   Spike raster for the top-N units sorted by firing rate,
#   aligned to a behavioral event of your choice.
#   Data source: SortingAnalyzer (written by postprocess stage)
#
# See: docs/specs/sort.md, docs/specs/postprocess.md
raise NotImplementedError(
    "Spike sorting not yet implemented. "
    "Run Tutorial 04 (Sort + Postprocess) when available."
)
```

- [ ] **Step 6: Commit**

```bash
git add tutorials/01_discover_pipeline.ipynb
git commit -m "feat(tutorials): add future-stage placeholder cells"
```

---

## Self-Review

### Spec Coverage

| Spec Section | Covered By |
|---|---|
| Section 00 — Config cell with path validation | Task 2 |
| Section 01 — Session setup (SubjectConfig + SessionManager) | Task 3 |
| Section 02 — SpikeGLXDiscovery + load_nidq + Viz A (raw NIDQ) | Task 4 |
| Section 03 — DiscoverStage + session_info.json | Task 5 |
| Section 04 — Viz B (channel positions) + Viz C (probe table) | Task 6 |
| Section 05 — Viz D (checkpoint board) + resume demo | Task 7 |
| Section 06 — Viz E (log table) | Task 8 |
| Section 07 — 4 future placeholder cells | Task 9 |

All spec requirements are covered. ✅

### Type/API Consistency Check

- `load_subject_config(SUBJECT_YAML)` → `SubjectConfig` ✅
- `SessionManager.from_data_dir(data_dir, subject, output_dir)` → `Session` ✅
- `setup_logging(session.log_path)` — `session.log_path` auto-set by `__post_init__` ✅
- `SpikeGLXDiscovery(session.session_dir).discover_probes()` → `list[ProbeInfo]` ✅
- `discovery.discover_nidq()` → `(nidq_bin, nidq_meta)` ✅
- `SpikeGLXLoader.load_nidq(nidq_bin, nidq_meta)` → `BaseRecording` ✅
- `SpikeGLXLoader.load_ap(probe)` → `BaseRecording` ✅
- `rec.get_probe().contact_positions` — standard SpikeInterface Probe API ✅
- `nidq_rec.get_traces(start_frame=0, end_frame=n)` — standard BaseRecording API ✅
- `DiscoverStage(session).run()` ✅
- `session.output_dir / "checkpoints"` — created by `SessionManager.create()` ✅
- `session.log_path` = `output_dir / "logs" / "pynpxpipe_{session_dir.name}.log"` ✅

No placeholder patterns found. ✅
