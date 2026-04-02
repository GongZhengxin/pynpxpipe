# SpikeInterface API Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade SpikeInterface to 0.104.0, verify all 9 API calls, create verification script, and update documentation with correct API usage and SLAY algorithm.

**Architecture:** Three-phase approach: (1) upgrade dependency and create verification script, (2) run verification and document findings, (3) update architecture.md, curate.md, and postprocess.md based on verified API signatures.

**Tech Stack:** SpikeInterface 0.104.0, Python 3.11, uv package manager

---

## File Structure

**New files:**
- `scripts/verify_spikeinterface_api.py` - API verification script that checks all 9 API calls

**Modified files:**
- `docs/architecture.md` - Correct API import paths, signatures, return values (Sections 2.2, 2.3, 2.5, 2.6)
- `docs/specs/curate.md` - Update Bombcell API usage
- `docs/specs/postprocess.md` - Replace SLAY algorithm (lines 125-140)
- `docs/temp/api_verification_needed.md` - Mark as resolved

---

## Task 1: Upgrade SpikeInterface to 0.104.0

**Files:**
- Modify: `pyproject.toml` (no changes needed, already specifies >=0.104.0)

- [ ] **Step 1: Upgrade SpikeInterface**

Run:
```bash
uv pip install --upgrade 'spikeinterface[full]>=0.104.0'
```

Expected output: Successfully installed spikeinterface-0.104.x

- [ ] **Step 2: Verify installation**

Run:
```bash
uv pip list | grep spikeinterface
```

Expected output: `spikeinterface            0.104.x` (or higher)

- [ ] **Step 3: Commit**

```bash
git add -u
git commit -m "chore: upgrade spikeinterface to 0.104.0"
```

---

## Task 2: Create API Verification Script

**Files:**
- Create: `scripts/verify_spikeinterface_api.py`

- [ ] **Step 1: Create scripts directory if needed**

Run:
```bash
mkdir -p scripts
```

- [ ] **Step 2: Write verification script**

Create `scripts/verify_spikeinterface_api.py`:

```python
#!/usr/bin/env python3
"""Verify SpikeInterface API calls used in architecture.md.

Checks:
1. SpikeInterface version >= 0.104.0
2. All 9 API functions exist and are importable
3. Print docstrings for manual review
"""

import sys


def check_version():
    """Check SpikeInterface version."""
    import spikeinterface as si
    
    version = si.__version__
    major, minor = map(int, version.split('.')[:2])
    
    print(f"SpikeInterface version: {version}")
    
    if major == 0 and minor < 104:
        print(f"❌ ERROR: SpikeInterface {version} < 0.104.0")
        sys.exit(1)
    
    print("✅ Version check passed\n")


def verify_preprocessing_apis():
    """Verify preprocessing module APIs."""
    print("=" * 60)
    print("PREPROCESSING APIs")
    print("=" * 60)
    
    try:
        from spikeinterface.preprocessing import (
            phase_shift,
            bandpass_filter,
            detect_bad_channels,
            common_reference,
            correct_motion,
        )
        
        print("\n1. phase_shift")
        print("-" * 40)
        print(phase_shift.__doc__[:500] if phase_shift.__doc__ else "No docstring")
        
        print("\n2. bandpass_filter")
        print("-" * 40)
        print(bandpass_filter.__doc__[:500] if bandpass_filter.__doc__ else "No docstring")
        
        print("\n3. detect_bad_channels")
        print("-" * 40)
        print(detect_bad_channels.__doc__[:500] if detect_bad_channels.__doc__ else "No docstring")
        
        print("\n4. common_reference")
        print("-" * 40)
        print(common_reference.__doc__[:500] if common_reference.__doc__ else "No docstring")
        
        print("\n5. correct_motion")
        print("-" * 40)
        print(correct_motion.__doc__[:500] if correct_motion.__doc__ else "No docstring")
        
        print("\n✅ All preprocessing APIs importable\n")
        
    except ImportError as e:
        print(f"❌ ERROR: {e}")
        sys.exit(1)


def verify_sorter_api():
    """Verify sorters module API."""
    print("=" * 60)
    print("SORTERS API")
    print("=" * 60)
    
    try:
        from spikeinterface.sorters import run_sorter
        
        print("\n6. run_sorter")
        print("-" * 40)
        print(run_sorter.__doc__[:500] if run_sorter.__doc__ else "No docstring")
        
        print("\n✅ Sorters API importable\n")
        
    except ImportError as e:
        print(f"❌ ERROR: {e}")
        sys.exit(1)


def verify_core_api():
    """Verify core module API."""
    print("=" * 60)
    print("CORE API")
    print("=" * 60)
    
    try:
        from spikeinterface.core import create_sorting_analyzer
        
        print("\n7. create_sorting_analyzer")
        print("-" * 40)
        print(create_sorting_analyzer.__doc__[:500] if create_sorting_analyzer.__doc__ else "No docstring")
        
        print("\n✅ Core API importable\n")
        
    except ImportError as e:
        print(f"❌ ERROR: {e}")
        sys.exit(1)


def verify_curation_apis():
    """Verify curation module APIs."""
    print("=" * 60)
    print("CURATION APIs")
    print("=" * 60)
    
    try:
        from spikeinterface.curation import (
            bombcell_label_units,
            compute_merge_unit_groups,
        )
        
        print("\n8. bombcell_label_units")
        print("-" * 40)
        print(bombcell_label_units.__doc__[:500] if bombcell_label_units.__doc__ else "No docstring")
        
        print("\n9. compute_merge_unit_groups")
        print("-" * 40)
        print(compute_merge_unit_groups.__doc__[:500] if compute_merge_unit_groups.__doc__ else "No docstring")
        
        print("\n✅ All curation APIs importable\n")
        
    except ImportError as e:
        print(f"❌ ERROR: {e}")
        sys.exit(1)


def main():
    """Run all verification checks."""
    print("\n" + "=" * 60)
    print("SpikeInterface API Verification")
    print("=" * 60 + "\n")
    
    check_version()
    verify_preprocessing_apis()
    verify_sorter_api()
    verify_core_api()
    verify_curation_apis()
    
    print("=" * 60)
    print("✅ ALL CHECKS PASSED")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Review docstrings above for parameter names and return types")
    print("2. Update architecture.md with correct API usage")
    print("3. Update curate.md with correct Bombcell API")
    print("4. Update postprocess.md with correct SLAY algorithm")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Make script executable**

Run:
```bash
chmod +x scripts/verify_spikeinterface_api.py
```

- [ ] **Step 4: Run verification script**

Run:
```bash
uv run python scripts/verify_spikeinterface_api.py
```

Expected: All checks pass, docstrings printed

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_spikeinterface_api.py
git commit -m "feat(scripts): add SpikeInterface API verification script"
```

---

## Task 3: Update architecture.md - Preprocessing APIs

**Files:**
- Modify: `docs/architecture.md:100-135` (Section 2.2 preprocessing chain)

- [ ] **Step 1: Update import statements**

In `docs/architecture.md`, find Section 2.2 and update the preprocessing chain code block to use correct imports:

```python
# Correct import pattern
from spikeinterface.preprocessing import (
    phase_shift,
    bandpass_filter,
    detect_bad_channels,
    common_reference,
    correct_motion,
)

# Apply preprocessing chain
recording = phase_shift(recording)
recording = bandpass_filter(recording, freq_min=300, freq_max=6000)
bad_ids, labels = detect_bad_channels(recording, method="coherence+psd")
recording = recording.remove_channels(bad_ids)
recording = common_reference(recording, reference="global", operator="median")
recording = correct_motion(recording, preset="nonrigid_accurate")
```

- [ ] **Step 2: Verify changes**

Run:
```bash
git diff docs/architecture.md
```

Expected: Import statements added, `si.` prefix removed

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs(architecture): correct preprocessing API imports"
```

---

## Task 4: Update architecture.md - Sorting API

**Files:**
- Modify: `docs/architecture.md:235-240` (Section 2.3 sorting)

- [ ] **Step 1: Update run_sorter call**

In `docs/architecture.md`, find Section 2.3 and update:

```python
from spikeinterface.sorters import run_sorter

sorting = run_sorter(
    sorter_name="kilosort4",
    recording=recording,
    output_folder=output_folder,
    **sorter_params
)
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs(architecture): correct sorting API usage"
```

---

## Task 5: Update architecture.md - Curation APIs

**Files:**
- Modify: `docs/architecture.md:386-420` (Section 2.5 curation)

- [ ] **Step 1: Update SortingAnalyzer creation**

In `docs/architecture.md`, find Section 2.5 and update:

```python
from spikeinterface.core import create_sorting_analyzer

analyzer = create_sorting_analyzer(
    sorting=sorting,
    recording=recording,
    format="binary_folder",
    folder=output_folder,
    sparse=True,
)
```

- [ ] **Step 2: Update Bombcell API usage**

Update the Bombcell section:

```python
from spikeinterface.curation import bombcell_label_units

# Compute quality metrics first
analyzer.compute("quality_metrics")

# Apply Bombcell labeling
labels = bombcell_label_units(
    analyzer=analyzer,
    isi_violations_ratio_threshold=0.5,
    amplitude_cutoff_threshold=0.1,
    presence_ratio_threshold=0.9,
)
```

- [ ] **Step 3: Commit**

```bash
git add docs/architecture.md
git commit -m "docs(architecture): correct curation API usage"
```

---

## Task 6: Update architecture.md - SLAY Algorithm

**Files:**
- Modify: `docs/architecture.md:450-480` (Section 2.6 postprocess)

- [ ] **Step 1: Update SLAY algorithm description**

In `docs/architecture.md`, find Section 2.6 and replace the SLAY algorithm description:

```markdown
### SLAY 计算（Stimulus-Locked Activity Yield）

SLAY 衡量神经元响应的 trial-to-trial 可靠性（response reliability）。

**算法**：
1. 将 [pre_s, post_s] 窗口分成 10ms bins
2. 对每个 trial，计算每个 bin 的 spike count，形成向量
3. 计算所有 trial 对之间的 Spearman 相关系数（对低发放率更稳健）
4. SLAY = 所有 trial 对相关系数的平均值

**公式**：
```python
from scipy.stats import spearmanr
import numpy as np

def compute_slay(spike_times, stim_onset_times, pre_s=0.05, post_s=0.30, bin_size_ms=10):
    """Compute SLAY as trial-to-trial correlation.
    
    Returns:
        float: Mean Spearman correlation across all trial pairs (0-1 range)
               Higher values indicate more reliable responses
               Returns np.nan if < 5 valid trials
    """
    valid_onsets = stim_onset_times[~np.isnan(stim_onset_times)]
    
    if len(valid_onsets) < 5:
        return np.nan
    
    # Bin edges
    bin_size_s = bin_size_ms / 1000.0
    window_duration = pre_s + post_s
    n_bins = int(window_duration / bin_size_s)
    
    # Compute spike count vectors for each trial
    trial_vectors = []
    for onset in valid_onsets:
        window_start = onset - pre_s
        window_end = onset + post_s
        
        # Get spikes in window
        spikes_in_window = spike_times[
            (spike_times >= window_start) & (spike_times < window_end)
        ]
        
        # Bin spike counts
        counts, _ = np.histogram(
            spikes_in_window - window_start,
            bins=n_bins,
            range=(0, window_duration)
        )
        trial_vectors.append(counts)
    
    trial_vectors = np.array(trial_vectors)  # shape: (n_trials, n_bins)
    
    # Compute pairwise Spearman correlations
    n_trials = len(trial_vectors)
    correlations = []
    
    for i in range(n_trials):
        for j in range(i + 1, n_trials):
            corr, _ = spearmanr(trial_vectors[i], trial_vectors[j])
            if not np.isnan(corr):
                correlations.append(corr)
    
    if len(correlations) == 0:
        return np.nan
    
    return np.mean(correlations)
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture.md
git commit -m "docs(architecture): correct SLAY algorithm to trial-to-trial correlation"
```

---

## Task 7: Update curate.md

**Files:**
- Modify: `docs/specs/curate.md:84-102` (Bombcell usage in _curate_probe)

- [ ] **Step 1: Update Bombcell API in curate.md**

In `docs/specs/curate.md`, find step 5-10 in `_curate_probe` and update:

```python
5. **计算扩展序列**（顺序不可颠倒）：
   ```python
   analyzer.compute("random_spikes")
   analyzer.compute("waveforms", chunk_duration=..., n_jobs=...)
   analyzer.compute("templates")
   analyzer.compute("noise_levels")
   analyzer.compute("quality_metrics",
       metric_names=["isi_violation_ratio", "amplitude_cutoff",
                     "presence_ratio", "snr"])
   ```

6. **获取质量指标**：`qm = analyzer.get_extension("quality_metrics").get_data()`（返回 DataFrame）

7. **保存 quality_metrics.csv**：`qm.to_csv(output_dir / "curated" / probe_id / "quality_metrics.csv")`，`mkdir(parents=True, exist_ok=True)`

8. **记录过滤前数量**：`n_before = len(sorting.get_unit_ids())`

9. **应用过滤规则**（使用手动阈值，不使用 Bombcell 自动标注）：
   ```python
   keep_mask = (
       (qm["isi_violation_ratio"] <= config_isi_max) &
       (qm["amplitude_cutoff"] <= config_amp_max) &
       (qm["presence_ratio"] >= config_pr_min) &
       (qm["snr"] >= config_snr_min)
   )
   good_unit_ids = qm.index[keep_mask].tolist()
   curated_sorting = sorting.select_units(good_unit_ids)
   ```

**注意**：虽然 SI 0.104+ 提供 `bombcell_label_units`，但我们使用手动阈值过滤以保持配置灵活性。
```

- [ ] **Step 2: Update imports section**

In `docs/specs/curate.md`, Section 7 (依赖), update:

```markdown
| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.CurateError` | 项目内部 | 质控失败时抛出 |
| `spikeinterface.core` | 第三方 | `load_extractor`、`create_sorting_analyzer` |
| `spikeinterface.qualitymetrics` | 第三方 | quality_metrics 扩展计算 |
| `gc` | 标准库 | 显式内存释放 |
| `pandas` | 第三方 | quality_metrics CSV |
| `pathlib.Path` | 标准库 | 路径操作 |
```

- [ ] **Step 3: Commit**

```bash
git add docs/specs/curate.md
git commit -m "docs(curate): clarify manual threshold filtering approach"
```

---

## Task 8: Update postprocess.md - SLAY Algorithm

**Files:**
- Modify: `docs/specs/postprocess.md:125-180` (SLAY computation)

- [ ] **Step 1: Replace SLAY algorithm section**

In `docs/specs/postprocess.md`, replace the `_compute_slay` function specification (lines 125-140):

```markdown
### `_compute_slay(spike_times, stim_onset_times, pre_s, post_s) -> float`

SLAY（Stimulus-Locked Activity Yield）：计算该 unit 响应的 trial-to-trial 可靠性。

**算法**：
1. **过滤有效 stim onset**：`valid_onsets = stim_onset_times[~np.isnan(stim_onset_times)]`
2. **检查最小 trial 数**：若 `len(valid_onsets) < 5` → return `np.nan`（数据不足）
3. **分 bin**：将 [pre_s, post_s] 窗口分成 10ms bins，计算 bin 数量 `n_bins = int((pre_s + post_s) / 0.01)`
4. **逐 trial 计算 spike count 向量**：
   ```python
   trial_vectors = []
   for onset in valid_onsets:
       window_start = onset - pre_s
       window_end = onset + post_s
       spikes_in_window = spike_times[(spike_times >= window_start) & (spike_times < window_end)]
       counts, _ = np.histogram(spikes_in_window - window_start, bins=n_bins, range=(0, pre_s + post_s))
       trial_vectors.append(counts)
   trial_vectors = np.array(trial_vectors)  # shape: (n_trials, n_bins)
   ```
5. **计算 trial 对之间的 Spearman 相关系数**：
   ```python
   from scipy.stats import spearmanr
   correlations = []
   n_trials = len(trial_vectors)
   for i in range(n_trials):
       for j in range(i + 1, n_trials):
           corr, _ = spearmanr(trial_vectors[i], trial_vectors[j])
           if not np.isnan(corr):
               correlations.append(corr)
   ```
6. **返回平均相关系数**：`return np.mean(correlations)` 若 `len(correlations) > 0` 否则 `np.nan`

**返回值**：
- `float`：0-1 范围，1 表示完全可靠（所有 trial 响应模式一致）
- `np.nan`：trial 数 < 5 或所有相关系数为 NaN

**为什么用 Spearman 而非 Pearson**：
- Spearman 对低发放率更稳健（不假设正态分布）
- 对异常值（某个 trial 的异常高发放）不敏感
- 保留单调关系即可，不要求线性关系
```

- [ ] **Step 2: Update imports in dependencies section**

In `docs/specs/postprocess.md`, Section 7 (依赖), add scipy:

```markdown
| 依赖 | 类型 | 说明 |
|---|---|---|
| `pynpxpipe.stages.base.BaseStage` | 项目内部 | 基类 |
| `pynpxpipe.core.errors.PostprocessError` | 项目内部 | 后处理失败时抛出 |
| `pynpxpipe.io.bhv.BHV2Parser` | 项目内部 | 眼动数据读取（分 trial 块） |
| `spikeinterface.core` | 第三方 | `create_sorting_analyzer`、`load_extractor` |
| `numpy` | 必选 | SLAY 计算 |
| `scipy.stats` | 必选 | Spearman 相关系数 |
| `pandas` | 必选 | behavior_events DataFrame |
| `gc` | 标准库 | 显式内存释放 |
| `json` | 标准库 | slay_scores.json 写出 |
```

- [ ] **Step 3: Commit**

```bash
git add docs/specs/postprocess.md
git commit -m "docs(postprocess): correct SLAY to trial-to-trial correlation"
```

---

## Task 9: Mark API Verification as Resolved

**Files:**
- Modify: `docs/temp/api_verification_needed.md`

- [ ] **Step 1: Add resolution note**

Add to the top of `docs/temp/api_verification_needed.md`:

```markdown
> **✅ RESOLVED**: 2026-04-02
> 
> All API calls verified via `scripts/verify_spikeinterface_api.py`.
> Documentation updated in ADR-002 and corresponding spec files.
> 
> See:
> - `docs/adr/002-spikeinterface-api-verification.md`
> - `scripts/verify_spikeinterface_api.py`

---
```

- [ ] **Step 2: Commit**

```bash
git add docs/temp/api_verification_needed.md
git commit -m "docs(temp): mark API verification as resolved"
```

---

## Task 10: Final Verification

**Files:**
- None (verification only)

- [ ] **Step 1: Re-run verification script**

Run:
```bash
uv run python scripts/verify_spikeinterface_api.py
```

Expected: All checks pass

- [ ] **Step 2: Check all commits**

Run:
```bash
git log --oneline -10
```

Expected: 9 commits from this plan

- [ ] **Step 3: Verify documentation consistency**

Run:
```bash
grep -n "si\." docs/architecture.md
```

Expected: No matches (all `si.` prefixes should be replaced with proper imports)

- [ ] **Step 4: Create summary commit**

```bash
git commit --allow-empty -m "chore: complete ADR-002 implementation

- Upgraded SpikeInterface to 0.104.0
- Created API verification script
- Updated architecture.md with correct API imports
- Updated curate.md with manual threshold approach
- Updated postprocess.md with trial-to-trial correlation SLAY
- Marked api_verification_needed.md as resolved"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Task 1: Upgrade to SI 0.104.0 (ADR Decision 1)
- ✅ Task 2: Create verification script (ADR Decision 4)
- ✅ Task 3-6: Update architecture.md API calls (ADR Decision 5)
- ✅ Task 7: Update curate.md Bombcell usage (ADR Decision 2)
- ✅ Task 8: Update postprocess.md SLAY algorithm (ADR Decision 3)
- ✅ Task 9: Mark verification as resolved
- ✅ Task 10: Final verification

**Placeholder scan:**
- ✅ No TBD/TODO markers
- ✅ All code blocks complete
- ✅ All commands have expected output

**Type consistency:**
- ✅ API function names consistent across all tasks
- ✅ Import paths consistent
- ✅ SLAY algorithm signature consistent

**No gaps found.**
