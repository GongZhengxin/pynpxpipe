# SpikeInterface API 使用验证清单

> **✅ RESOLVED**: 2026-04-02
>
> All API calls verified via `scripts/verify_spikeinterface_api.py`.
> Documentation updated per ADR-002 and corresponding spec files.
>
> See:
> - `docs/adr/002-spikeinterface-api-verification.md`
> - `scripts/verify_spikeinterface_api.py`

---

> 日期：2026-04-01  
> 目的：验证 architecture.md 中的 SpikeInterface API 调用是否符合官方文档

---

## ⚠️ 无法访问官方文档

由于网络限制，无法直接访问 SpikeInterface 官方文档进行验证。以下是基于代码模式分析发现的**潜在问题点**，需要在实际编码前通过以下方式验证：

1. 本地安装 SpikeInterface 0.104+ 后查看 docstring
2. 访问 https://spikeinterface.readthedocs.io/en/latest/
3. 查看 SpikeInterface GitHub 仓库的示例代码

---

## 1. 预处理 API（Section 2.2）

### 1.1 函数调用模式

**architecture.md 中的写法**：
```python
si.phase_shift(recording)
si.bandpass_filter(recording, freq_min=300, freq_max=6000)
si.detect_bad_channels(recording, method="coherence+psd")
si.common_reference(recording, reference="global", operator="median")
si.correct_motion(recording, preset="nonrigid_accurate")
```

### ⚠️ 潜在问题 1：模块导入方式

**疑问**：这些函数是否直接在 `spikeinterface` 命名空间下？

**可能的正确方式**：
```python
# 方式 A：从 preprocessing 子模块导入
from spikeinterface.preprocessing import (
    phase_shift,
    bandpass_filter,
    detect_bad_channels,
    common_reference,
    correct_motion
)

recording = phase_shift(recording)
recording = bandpass_filter(recording, freq_min=300, freq_max=6000)

# 方式 B：使用完整路径
import spikeinterface.preprocessing as spre

recording = spre.phase_shift(recording)
recording = spre.bandpass_filter(recording, freq_min=300, freq_max=6000)
```

**需要验证**：
- [ ] `si.phase_shift()` 是否存在？还是应该用 `spre.phase_shift()`？
- [ ] 是否需要 `import spikeinterface.full` 才能使用简写 `si.*`？

---

### ⚠️ 潜在问题 2：`detect_bad_channels` 返回值

**architecture.md 中的写法**（第 109 行）：
```python
bad_ids, labels = si.detect_bad_channels(recording, method="coherence+psd")
```

**疑问**：返回值是 `(bad_ids, labels)` 元组，还是单个对象？

**需要验证**：
- [ ] 返回值结构是什么？
- [ ] 是否有 `channel_labels` 参数或返回字段？
- [ ] `method="coherence+psd"` 是否是有效值？（可能是 `"coherence_psd"` 或其他）

**可能的正确方式**：
```python
# 可能性 A：返回字典
bad_channel_info = detect_bad_channels(recording, method="coherence+psd")
bad_ids = bad_channel_info['channel_ids']
labels = bad_channel_info['channel_labels']

# 可能性 B：返回元组
bad_ids, labels = detect_bad_channels(recording, method="coherence+psd")

# 可能性 C：只返回 bad_ids
bad_ids = detect_bad_channels(recording, method="coherence+psd")
```

---

### ⚠️ 潜在问题 3：`correct_motion` preset 参数

**architecture.md 中的写法**（第 118 行）：
```python
si.correct_motion(recording, preset="nonrigid_accurate")
```

**疑问**：
- `preset="nonrigid_accurate"` 是否是有效的 preset 名称？
- 是否应该是 `"dredge"` 或其他名称？

**需要验证**：
- [ ] 可用的 preset 列表是什么？
- [ ] DREDge 算法对应的 preset 名称是什么？
- [ ] 是否需要额外参数（如 `method="dredge"`）？

---

## 2. Sorting API（Section 2.3）

### ⚠️ 潜在问题 4：`run_sorter` 参数

**architecture.md 中的写法**（第 235 行）：
```python
si.run_sorter(sorter_name, recording, output_folder="{output_dir}/sorting/{probe_id}")
```

**疑问**：参数顺序和命名是否正确？

**需要验证**：
- [ ] 参数顺序是 `(sorter_name, recording, output_folder)` 还是 `(recording, sorter_name, output_folder)`？
- [ ] 是 `output_folder` 还是 `output_dir`？
- [ ] 是否需要 `**sorter_params` 参数？

**可能的正确方式**：
```python
from spikeinterface.sorters import run_sorter

sorting = run_sorter(
    sorter_name="kilosort4",
    recording=recording,
    output_folder=output_folder,
    **sorter_params
)
```

---

## 3. Curation API（Section 2.5）

### ⚠️ 潜在问题 5：Bombcell 集成

**architecture.md 中的写法**（第 391-393 行）：
```python
import spikeinterface.curation as sc
thresholds = sc.bombcell_get_default_thresholds()
labels = sc.bombcell_label_units(analyzer, thresholds, label_non_somatic=True)
```

**疑问**：
- 这些函数是否真的存在于 SpikeInterface 0.104+？
- 函数名是否正确？

**需要验证**：
- [ ] `bombcell_get_default_thresholds()` 是否存在？
- [ ] `bombcell_label_units()` 是否存在？
- [ ] 参数 `label_non_somatic` 是否正确？（第 417 行还有 `split_non_somatic_good_mua`）
- [ ] 返回值是 DataFrame 还是其他格式？

**可能的情况**：
- **情况 A**：SpikeInterface 0.104+ 确实原生集成了 Bombcell
- **情况 B**：需要使用独立的 Bombcell 包（如旧版本）
- **情况 C**：函数名不同（如 `auto_label_units` 或 `quality_based_curation`）

---

### ⚠️ 潜在问题 6：SortingAnalyzer 创建

**architecture.md 中的写法**（第 386 行）：
```python
analyzer = si.create_sorting_analyzer(sorting, recording)
```

**疑问**：
- 是 `create_sorting_analyzer` 还是其他名称？
- 参数顺序是否正确？

**需要验证**：
- [ ] 函数名是否正确？（可能是 `SortingAnalyzer.create()` 或 `create_analyzer()`）
- [ ] 参数是 `(sorting, recording)` 还是 `(recording, sorting)`？
- [ ] 是否需要指定 `format="binary_folder"` 或其他参数？

**可能的正确方式**：
```python
# 方式 A
from spikeinterface import create_sorting_analyzer
analyzer = create_sorting_analyzer(sorting, recording, format="binary_folder")

# 方式 B
from spikeinterface.core import SortingAnalyzer
analyzer = SortingAnalyzer.create(sorting, recording)
```

---

## 4. Postprocess API（Section 2.6）

### ⚠️ 潜在问题 7：SLAY 集成

**architecture.md 中的写法**（第 521-528 行）：
```python
from spikeinterface.curation import compute_merge_unit_groups

merge_groups = compute_merge_unit_groups(
    sorting_analyzer=analyzer,
    preset="slay",
    resolve_graph=True
)
analyzer_merged = analyzer.merge_units(merge_unit_groups=merge_groups)
```

**疑问**：
- `compute_merge_unit_groups` 是否存在？
- `preset="slay"` 是否是有效值？
- `analyzer.merge_units()` 方法是否存在？

**需要验证**：
- [ ] 函数名和参数是否正确？
- [ ] 可用的 preset 列表（第 530 行提到：`similarity_correlograms`, `temporal_splits`, `x_contaminations`, `feature_neighbors`）
- [ ] 是否需要先计算某些扩展（如 `correlograms`）才能使用 SLAY？

---

### ⚠️ 潜在问题 8：Analyzer 扩展计算

**architecture.md 中的写法**（第 388, 408, 510-514 行）：
```python
analyzer.compute("quality_metrics")
analyzer.compute("waveforms", ms_before=1.5, ms_after=2.0)
analyzer.compute("templates")
analyzer.compute("unit_locations", method="monopolar_triangulation")
```

**疑问**：
- 扩展名是否正确？
- 参数传递方式是否正确？

**需要验证**：
- [ ] 扩展名列表是否正确？（`quality_metrics`, `waveforms`, `templates`, `unit_locations`, `template_similarity`, `correlograms`）
- [ ] 参数是直接传递还是需要字典？
- [ ] 是否有依赖顺序？（如 `templates` 依赖 `waveforms`）

**可能的正确方式**：
```python
# 方式 A：直接传参
analyzer.compute("waveforms", ms_before=1.5, ms_after=2.0)

# 方式 B：字典传参
analyzer.compute("waveforms", **{"ms_before": 1.5, "ms_after": 2.0})

# 方式 C：先注册再计算
analyzer.register_extension("waveforms", ms_before=1.5, ms_after=2.0)
analyzer.compute("waveforms")
```

---

## 5. 其他 API

### ⚠️ 潜在问题 9：`read_spikeglx` 和 `read_sorter_folder`

**architecture.md 中的写法**（第 128, 241 行）：
```python
si.read_spikeglx()
si.read_sorter_folder()
```

**需要验证**：
- [ ] 这些函数是否在 `spikeinterface` 顶层命名空间？
- [ ] 还是需要从 `spikeinterface.extractors` 导入？

**可能的正确方式**：
```python
from spikeinterface.extractors import read_spikeglx, read_sorter_folder
```

---

## 验证优先级

### 🔴 高优先级（必须验证，影响核心流程）

1. **预处理函数的导入方式**（问题 1）
   - 影响：preprocess stage 无法运行
   - 验证方法：`python -c "import spikeinterface as si; print(dir(si))"`

2. **`detect_bad_channels` 返回值**（问题 2）
   - 影响：坏道检测逻辑错误
   - 验证方法：查看函数 docstring 或运行小测试

3. **`create_sorting_analyzer` 函数名**（问题 6）
   - 影响：curate 和 postprocess stage 无法运行
   - 验证方法：查看 SpikeInterface 0.104+ API 文档

4. **Bombcell 集成是否存在**（问题 5）
   - 影响：curate stage 核心功能
   - 验证方法：`python -c "import spikeinterface.curation as sc; print(dir(sc))"`

### 🟡 中优先级（影响可选功能）

5. **`correct_motion` preset 名称**（问题 3）
   - 影响：运动校正功能
   - 可选功能，可暂时跳过

6. **SLAY 集成**（问题 7）
   - 影响：自动合并功能
   - 可选功能，可暂时跳过

### 🟢 低优先级（不影响核心功能）

7. **`run_sorter` 参数顺序**（问题 4）
   - 影响：sorting stage
   - 但 sorting 可以用 import 模式绕过

8. **Analyzer 扩展计算细节**（问题 8）
   - 影响：postprocess stage
   - 但可以通过试错快速修正

---

## 建议的验证流程

### Step 1: 安装并检查版本
```bash
uv add "spikeinterface>=0.104"
python -c "import spikeinterface; print(spikeinterface.__version__)"
```

### Step 2: 检查命名空间
```python
import spikeinterface as si
import spikeinterface.preprocessing as spre
import spikeinterface.curation as sc

print("Top-level:", [x for x in dir(si) if not x.startswith('_')])
print("Preprocessing:", [x for x in dir(spre) if not x.startswith('_')])
print("Curation:", [x for x in dir(sc) if not x.startswith('_')])
```

### Step 3: 验证关键函数
```python
# 验证预处理函数
from spikeinterface.preprocessing import phase_shift, bandpass_filter, detect_bad_channels
print(phase_shift.__doc__)
print(detect_bad_channels.__doc__)

# 验证 Bombcell
from spikeinterface.curation import bombcell_get_default_thresholds, bombcell_label_units
print(bombcell_get_default_thresholds.__doc__)

# 验证 SLAY
from spikeinterface.curation import compute_merge_unit_groups
print(compute_merge_unit_groups.__doc__)
```

### Step 4: 运行小测试
创建一个最小测试脚本，使用真实数据（或生成的测试数据）验证完整流程。

---

## 修正建议

在开始 Layer 1 实现之前，**必须先完成以上验证**。建议：

1. **创建验证脚本**：`scripts/verify_spikeinterface_api.py`
   - 检查所有 API 函数是否存在
   - 打印函数签名和 docstring
   - 运行小规模测试

2. **更新 architecture.md**：
   - 根据验证结果修正所有 API 调用
   - 添加正确的 import 语句
   - 标注 SpikeInterface 版本要求

3. **更新 specs**：
   - 确保 `docs/specs/*.md` 中的 API 调用与验证结果一致

4. **记录到 ADR**：
   - 如果发现 API 与预期不同，记录决策理由

---

## 总结

**当前状态**：architecture.md 中的 SpikeInterface API 调用**未经验证**，存在多处潜在错误。

**风险等级**：🔴 高风险 — 如果直接按 architecture.md 编码，可能导致大量返工。

**推荐行动**：
1. 立即创建 API 验证脚本
2. 验证所有高优先级问题（问题 1, 2, 5, 6）
3. 根据验证结果更新 architecture.md
4. 再开始 Layer 1 的 TDD 实现

**预计验证时间**：1-2 小时（安装 + 编写验证脚本 + 更新文档）

**收益**：避免后续 3-5 天的返工时间。
