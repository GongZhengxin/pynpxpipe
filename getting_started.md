# Getting Started: Run the UI & Preprocess Your Data

This tutorial walks you through installing pynpxpipe, launching the Web UI, and running the preprocessing pipeline on SpikeGLX recordings.

## Prerequisites

- **Python 3.11 or 3.12** (3.13 is not supported)
- **uv** package manager ([install guide](https://docs.astral.sh/uv/getting-started/installation/))
- **SpikeGLX recording data** (a session directory containing `imec0/`, `imec1/`, ... subdirectories with `.ap.bin`/`.ap.meta` files, plus a NIDQ `.bin`/`.meta` pair)
- **MonkeyLogic BHV2 file** (the `.bhv2` behavioral data file for the same session)
- (Optional) **NVIDIA GPU** with CUDA for Kilosort4 spike sorting

## 1. Install pynpxpipe

You have two installation modes depending on your use case.

### Mode A — Consume as a dependency (most users)

Step 1 — add pynpxpipe to your own uv project:

```bash
# Recommended: full pipeline (Web UI + GPU detection + plots)
uv add "pynpxpipe[ui,gpu,plots] @ git+https://github.com/GongZhengxin/pynpxpipe.git"

# Add the LLM help assistant on top
uv add "pynpxpipe[ui,gpu,plots,chat] @ git+https://github.com/GongZhengxin/pynpxpipe.git"

# Core only (no UI, no plots)
uv add git+https://github.com/GongZhengxin/pynpxpipe.git
```

Step 2 — install the sort stack (**once**, not repeated on every update):

```bash
# Grab install_sort_stack.py from the repo (skip if you cloned in Mode B)
curl -O https://raw.githubusercontent.com/GongZhengxin/pynpxpipe/main/tools/install_sort_stack.py
curl -O https://raw.githubusercontent.com/GongZhengxin/pynpxpipe/main/tools/cuda_matrix.yaml
mkdir -p tools && mv install_sort_stack.py cuda_matrix.yaml tools/

# Interactive install — auto-detects your GPU + driver, recommends a CUDA wheel
uv run python tools/install_sort_stack.py
```

> **Why a separate step?** `torch` and `kilosort` are intentionally NOT listed
> in `pyproject.toml`. If they were, every `uv sync` would revert a CUDA build
> of torch back to the pypi CPU wheel, and you'd silently run on CPU again.
> Keeping them out of pyproject means the wheel you pick sticks across
> updates, and each user installs the wheel matching their own CUDA version.
>
> The installer reads `tools/cuda_matrix.yaml` to pick the right wheel for
> your driver. It always shows the recommendation first, then lets you
> confirm or override. Re-running it is idempotent (a lock file at
> `.venv/.gpu_stack_lock.json` records what was installed).

### Mode B — Clone for development / contribution

```bash
git clone https://github.com/GongZhengxin/pynpxpipe.git
cd pynpxpipe
uv sync --all-groups

# One-time sort stack install (see Mode A step 2 for why)
uv run python tools/install_sort_stack.py
```

To confirm the install at any later time:

```bash
uv run python tools/verify_gpu.py
```

### Keeping torch installed across future syncs

After the installer runs, **always pass `--inexact` when re-syncing**:

```bash
uv sync --inexact --extra ui --extra gpu --extra plots         # preserves torch/kilosort
uv sync --extra ui --extra gpu --extra plots                   # ✗ DON'T — removes torch
```

Why: `uv sync` defaults to strict mode and uninstalls anything not in `uv.lock`.
Since `torch` / `kilosort` live outside the lock (that's how CUDA builds stay
put per-user), strict sync nukes them. `--inexact` tells uv to leave
out-of-lock packages alone. As of uv 0.8 there is no environment-variable
equivalent, so you must pass the flag explicitly (or bake it into a shell
alias / Makefile).

If you see `ModuleNotFoundError: No module named 'torch'` after a `uv sync`,
you forgot `--inexact` — just re-run the installer (`--force` to skip prompts):

```bash
uv run python tools/install_sort_stack.py --yes --force
```

### Verify the installation

```bash
uv run pynpxpipe --version
uv run pynpxpipe --help
```

## 2. Prepare Your Data

### 2.1 SpikeGLX Session Directory

Your SpikeGLX recording folder should have this structure:

```
my_session_g0/
  my_session_g0_imec0/
    my_session_g0_t0.imec0.ap.bin
    my_session_g0_t0.imec0.ap.meta
    my_session_g0_t0.imec0.lf.bin      # optional
    my_session_g0_t0.imec0.lf.meta     # optional
  my_session_g0_imec1/                  # if multi-probe
    ...
  my_session_g0_t0.nidq.bin
  my_session_g0_t0.nidq.meta
```

### 2.2 BHV2 Behavioral File

The `.bhv2` file from MonkeyLogic for the same session. pynpxpipe reads it with a pure-Python parser (no MATLAB required).

### 2.3 Subject Configuration (YAML)

Create a YAML file for your subject (or use an existing one in `monkeys/`). Example — `monkeys/MaoDan.yaml`:

```yaml
Subject:
  subject_id: "MaoDan"            # required by DANDI
  description: "good monkey"      # free text
  species: "Macaca mulatta"       # required by DANDI
  sex: "M"                        # required by DANDI
  age: "P4Y"                      # ISO 8601 duration
  weight: "12.8kg"                # body weight with unit
```

### 2.4 Output Directory

Choose a directory for processed output. pynpxpipe will create subdirectories for checkpoints, preprocessed data, sorting results, sync tables, and the final NWB file.

## 3. Launch the Web UI

The Web UI is the easiest way to configure and run the pipeline.

```bash
uv run pynpxpipe-ui
```

This starts a local Panel server and opens the UI in your default browser (typically at `http://localhost:5006`).

Alternatively, you can serve it manually:

```bash
uv run panel serve src/pynpxpipe/ui/app.py --show
```

### UI Overview

The UI has three sections, accessible from the sidebar:

| Section | Purpose |
|---------|---------|
| **Configure** | Set input paths, subject metadata, pipeline parameters, sorting options, and select stages. Subject forms can now be saved as reusable YAML files. |
| **Execute** | Start/stop the pipeline, monitor stage-level and probe-level progress, view real-time logs |
| **Review** | Load previous sessions, inspect checkpoint status, reset stages for re-run, browse generated figures via the **Figures Viewer**, and ask questions via the **Chat Help** panel (requires `chat` extra + API key) |

## 4. Configure a Pipeline Run (via UI)

### Step 1: Session Form

In the **Configure** section, fill in:

- **Session Directory** — path to your SpikeGLX recording folder (e.g., `D:/data/my_session_g0/`)
- **BHV File** — path to the `.bhv2` file (e.g., `D:/data/my_session.bhv2`)
- **Output Directory** — where to write results (e.g., `D:/output/my_session/`)

### Step 2: Subject Metadata

Fill in the subject fields (or load from a YAML file):

- **Subject ID** — unique identifier (e.g., `MaoDan`)
- **Species** — binomial name (e.g., `Macaca mulatta`)
- **Sex** — `M`, `F`, `U`, or `O`
- **Age** — ISO 8601 duration (e.g., `P4Y` for 4 years)
- **Weight** — with unit (e.g., `12.8kg`)

### Step 3: Pipeline Parameters

Adjust processing parameters (defaults are usually fine):

| Parameter | Default | Description |
|-----------|---------|-------------|
| **n_jobs** | auto | Number of parallel threads |
| **chunk_duration** | auto | Processing chunk window (e.g., `1s`) |
| **max_memory** | auto | Memory ceiling for logging |
| **Bandpass freq_min** | 300 Hz | High-pass cutoff |
| **Bandpass freq_max** | 6000 Hz | Low-pass cutoff |
| **Motion correction** | dredge | `dredge`, `kilosort`, or disabled |

### Step 4: Sorting Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| **Mode** | local | `local` (run Kilosort4) or `import` (load external results) |
| **nblocks** | 15 | Drift correction blocks (0 = disabled) |
| **do_CAR** | false | Always false (preprocessing already does CMR) |
| **batch_size** | auto | Auto-detected based on GPU VRAM |

### Step 5: Select Stages

Choose which stages to run. The full pipeline order is:

1. **discover** — scan SpikeGLX folder, detect probes
2. **preprocess** — filter, bad channel removal, CMR, motion correction, save Zarr
3. **sort** — Kilosort4 spike sorting (or import external results)
4. **synchronize** — time alignment across IMEC, NIDQ, and BHV2
5. **curate** — quality metrics and unit classification
6. **postprocess** — waveform analysis, auto-merge
7. **export** — assemble final NWB file

For preprocessing only, select **discover** + **preprocess**.

## 5. Run the Pipeline

1. Click the sidebar **Execute** button to switch to the Execute section.
2. Click **Run**. The pipeline launches in a background thread (the UI stays responsive).
3. Monitor progress:
   - **Progress bar** — shows which stage is active and per-probe sub-progress
   - **Log viewer** — real-time structured logs with level filtering (INFO, WARNING, ERROR)
   - **Status** — idle / running / completed / failed
4. To stop early, click **Stop** (sets an interrupt flag; the current probe finishes before stopping).

## 6. Run via Command Line (Alternative)

If you prefer the CLI:

```bash
uv run pynpxpipe run \
  D:/data/my_session_g0 \
  D:/data/my_session.bhv2 \
  --subject monkeys/MaoDan.yaml \
  --output-dir D:/output/my_session \
  --pipeline-config config/pipeline.yaml \
  --sorting-config config/sorting.yaml
```

Run only specific stages:

```bash
# Only discover + preprocess
uv run pynpxpipe run \
  D:/data/my_session_g0 \
  D:/data/my_session.bhv2 \
  --subject monkeys/MaoDan.yaml \
  --output-dir D:/output/my_session \
  --stages discover --stages preprocess
```

Check pipeline status:

```bash
uv run pynpxpipe status D:/output/my_session
```

Reset a stage to re-run it:

```bash
uv run pynpxpipe reset-stage D:/output/my_session preprocess
```

## 7. Understanding Preprocessing Output

After running the **discover** and **preprocess** stages, your output directory will contain:

```
D:/output/my_session/
  session_info.json              # Session metadata (probe list, paths)
  logs/
    pipeline.jsonl               # Structured JSON Lines log
  checkpoints/
    discover.json                # Stage checkpoint
    preprocess_imec0.json        # Per-probe checkpoint
    preprocess_imec1.json        # (if multi-probe)
  preprocessed/
    imec0/                       # Zarr recording (chunked, memory-efficient)
    imec1/                       # (if multi-probe)
```

### Preprocessing Steps (per probe)

The preprocess stage applies these steps in strict order:

| Step | Operation | Why |
|------|-----------|-----|
| 1 | **Phase shift** | Fix ADC multiplexing timing — MUST be first |
| 2 | **Bandpass filter** | 300-6000 Hz (configurable) |
| 3 | **Bad channel detection** | Coherence + PSD method |
| 4 | **Bad channel removal** | Remove detected bad channels |
| 5 | **Common median reference** | Global median subtraction |
| 6 | **Motion correction** | DREDge drift correction (optional) |
| 7 | **Save to Zarr** | Chunked format for downstream stages |

Each probe is processed serially. Memory is released between probes (`del` + `gc.collect()`), so even 400+ GB AP files can be processed on modest hardware.

## 8. Resume from Interruption

pynpxpipe has checkpoint-based resume. If the pipeline is interrupted:

**Via UI:**
1. Open the **Review** section
2. Use the **Session Loader** to browse your output directory
3. Click **Load** — it auto-fills all forms from the saved session
4. Switch to **Execute** and click **Run** — completed stages are automatically skipped

**Via CLI:**
```bash
# Just re-run the same command — completed stages are skipped automatically
uv run pynpxpipe run D:/data/my_session_g0 D:/data/my_session.bhv2 \
  --subject monkeys/MaoDan.yaml --output-dir D:/output/my_session
```

To force re-run a stage, reset its checkpoint first:

**Via UI:** In the **Review** section, use the **Status View** to reset a stage.

**Via CLI:**
```bash
uv run pynpxpipe reset-stage D:/output/my_session preprocess
```

## 9. Configuration Reference

### Pipeline Config (`config/pipeline.yaml`)

```yaml
resources:
  n_jobs: auto                   # "auto" or integer
  chunk_duration: auto           # "auto" or "1s", "2s", "0.5s"
  max_memory: auto               # "auto" or "32G"

preprocess:
  bandpass:
    freq_min: 300
    freq_max: 6000
  bad_channel_detection:
    method: "coherence+psd"
    dead_channel_threshold: 0.5
  common_reference:
    reference: "global"
    operator: "median"
  motion_correction:
    method: "dredge"             # "dredge" | "kilosort" | null
    preset: "nonrigid_accurate"
```

### Sorting Config (`config/sorting.yaml`)

```yaml
mode: "local"                    # "local" | "import"

sorter:
  name: "kilosort4"
  params:
    nblocks: 15
    Th_learned: 7.0
    do_CAR: false                # Always false (preprocess handles CMR)
    batch_size: auto
```

### Subject Config (`monkeys/*.yaml`)

```yaml
Subject:
  subject_id: "MaoDan"
  description: "good monkey"
  species: "Macaca mulatta"
  sex: "M"
  age: "P4Y"
  weight: "12.8kg"
```

## 10. Troubleshooting

| Problem | Solution |
|---------|----------|
| `ModuleNotFoundError: No module named 'panel'` | Install UI extra: `uv sync --extra ui` |
| `ModuleNotFoundError: No module named 'torch'` | Run `uv run python tools/install_sort_stack.py` (torch lives outside pyproject; see install guide) |
| `The dredge method require torch: pip install torch` | Same — run the sort stack installer; DREDge needs `torch` |
| `ModuleNotFoundError: No module named 'kilosort'` | Same — run the sort stack installer |
| `TorchEnvError: torch_device='cuda' was requested ... CPU-only build` | Your torch is the CPU wheel. Run `uv run python tools/install_sort_stack.py --force` and pick a CUDA wheel matching your driver |
| `TorchEnvError: torch_device='cuda' was requested but no NVIDIA GPU` | Set `torch_device: cpu` (or `auto`) in `config/sorting.yaml` |
| `pynpxpipe-ui` command not found | Run via `uv run pynpxpipe-ui` or install with `uv sync` |
| UI doesn't open in browser | Navigate manually to `http://localhost:5006` |
| Out of memory during preprocess | Reduce `chunk_duration` (e.g., `"0.5s"`) or lower `n_jobs` in `pipeline.yaml` |
| Motion correction + KS4 nblocks conflict | These are mutually exclusive. Set motion correction to `null` if using KS4 nblocks > 0, or set nblocks to 0 if using DREDge |
| GPU not detected for sorting | Install GPU extra: `uv sync --extra gpu`. Ensure CUDA drivers are installed |
| Pipeline stuck on a stage | Check `logs/pipeline.jsonl` for errors. Use `reset-stage` to clear the checkpoint and retry |
| BHV2 parsing errors | pynpxpipe uses a pure-Python parser by default. Set `BHV2_BACKEND=matlab` to use MATLAB Engine as fallback (requires MATLAB) |
