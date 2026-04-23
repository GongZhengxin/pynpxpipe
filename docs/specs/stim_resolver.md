# Spec: io/stim_resolver.py

## 1. 目标

把 "行为文件里的 `UserVars.DatasetName`（一条 Windows 绝对路径）+ 用户可选的 image vault 搜索根" 翻译成一个 `{stim_index: stim_name}` 映射。**只做纯 I/O 解析**，不依赖 session / NWB / stage 层任何对象。供 `stages/export.py` 在写 NWB trials 表前调用，把 MATLAB 端的 stim_index（1-based，来自 `UserVars.Current_Image_Train`）翻译成可读文件名（如 `choice7873.png`）。

### 为什么独立成模块

`BHV2Parser` 只懂二进制行为文件，不读 tsv 也不做 glob；`NWBWriter.add_trials` 只懂 DataFrame → NWB 列，不碰 I/O；把 "找 tsv + 读 tsv" 单独成模块是为了 (a) 两端都能单独 mock；(b) 未来若要支持非 tsv 图集（mat / h5 / json）加 loader 不改上下游。

## 2. 输入

| 函数 | 参数 | 说明 |
|------|------|------|
| `resolve_dataset_tsv` | `dataset_name: str \| None` | 来自 `BHV2Parser.get_dataset_tsv_path()`，可能是 Windows 绝对路径（`'C:\\#Datasets\\TripleN10k\\stimuli\\nsd1w.tsv'`）、POSIX 路径、或 `None` |
| | `image_vault_paths: list[Path] \| None = None` | 用户在 `SubjectConfig` 里配置的图片库搜索根（可多个），None / 空 list 视同无 fallback |
| `load_stim_map` | `tsv_path: Path` | 已解析到的实际 tsv 路径 |

## 3. 输出

### `resolve_dataset_tsv(dataset_name, image_vault_paths) -> tuple[Path \| None, str]`

返回 `(resolved_path, source_tag)`：

| `source_tag` 取值 | 含义 | `resolved_path` |
|-------------------|------|-----------------|
| `"direct"` | `dataset_name` 本身可访问（直接 `Path.exists()`） | tsv 绝对路径 |
| `"vault:<path>"` | direct 失败，在某个 vault 下 `rglob(tsv_filename)` 单次命中 | tsv 绝对路径 |
| `"vault:<path>(multi)"` | 多 vault 同时命中：取首个 + WARN | tsv 绝对路径 |
| `"vault_miss"` | direct 失败 + vault 全部无命中 | `None` |
| `"no_dataset_name"` | `dataset_name is None or == ""` | `None` |

### `load_stim_map(tsv_path) -> dict[int, str]`

返回 `{1: filename_row1, 2: filename_row2, ...}`，key 是 1-based 行号（与 MATLAB 的 `Current_Image_Train` 对齐），value 是 tsv 中 `FileName` 列的字符串（保留原扩展名，如 `"choice7873.png"`）。

- tsv 必须含表头 `FileName` 列（精确匹配，大小写敏感）；缺列则 raise `ValueError(f"{tsv_path}: missing FileName column")`
- 额外列（如 `Category`）忽略，不写入 map
- 空文件（只有表头）返回空 dict（合法情况，上游决定如何处理）

## 4. 处理步骤

### `resolve_dataset_tsv`

1. 若 `dataset_name is None` 或 strip 后为空 → 返回 `(None, "no_dataset_name")`
2. `raw = Path(dataset_name)`。**注意**：BHV2 里的路径一般是 Windows 风格（含 `\`）。在 POSIX 系统 `Path("C:\\...")` 会被当单段字符串 —— 先统一走 `PureWindowsPath` → `Path(posix_like_str)` 规范化：
   ```python
   # dataset_name 可能是 'C:\\X\\Y\\nsd1w.tsv' 或 '/mnt/X/nsd1w.tsv'
   raw = Path(PureWindowsPath(dataset_name).as_posix()) if "\\" in dataset_name else Path(dataset_name)
   ```
3. 若 `raw.exists() and raw.is_file()` → 返回 `(raw.resolve(), "direct")`
4. 否则启动 vault 回退：
   - `tsv_name = raw.name`（如 `nsd1w.tsv`）—— 只用文件名，不保留目录结构
   - `image_vault_paths` 为 None / `[]` → 返回 `(None, "vault_miss")`
   - 对每个 `vault in image_vault_paths`：
     - 若 `not vault.exists()` → 跳过（DEBUG log，不 raise）
     - `hits = sorted(vault.rglob(tsv_name))`
     - 过滤非文件（排除同名目录）
     - 若非空 → 收集 `(vault, hits)`
   - 聚合所有命中：
     - 0 命中 → 返回 `(None, "vault_miss")`
     - 1 命中 → 返回 `(hit.resolve(), f"vault:{vault}")`
     - N 命中（across vaults or within one vault）→ WARN 一行列出所有 hit，返回 `(first_hit.resolve(), f"vault:{vault}(multi)")`
5. 所有返回路径都 `.resolve()`，避免下游再纠结相对/绝对

### `load_stim_map`

1. `df = pandas.read_csv(tsv_path, sep="\t", dtype=str, keep_default_na=False)` —— 强制全列 str，避免 `choice7873.png` 被当 NaN 或数值解析
2. `if "FileName" not in df.columns: raise ValueError(...)`
3. `return {i + 1: name for i, name in enumerate(df["FileName"].tolist())}`

## 5. 可配参数

- **`image_vault_paths`**：调用方（通常是 `export.py`）从 `session.subject.image_vault_paths` 读取；本模块不识别配置文件。
- 无其他可配项。glob 行为（`rglob` 递归、文件名精确匹配、sort asc）硬编码，足够明确。

## 6. 错误与容错

| 情况 | 行为 | 理由 |
|------|------|------|
| `dataset_name` 为 None / 空 | 返回 `(None, "no_dataset_name")` | 合法场景（legacy session 无 DatasetName），上游静默降级为空 stim_name |
| direct 路径失败 + 无 vault | 返回 `(None, "vault_miss")` | 同上，降级合法 |
| Vault 目录不存在 | DEBUG log 跳过 | 用户配了多个 vault 不保证都在当前机器存在 |
| 多 vault 命中 | WARN + 取首个 | 不 raise：多机器部署很容易同名图集，用户配置顺序即优先级 |
| tsv 缺 `FileName` 列 | raise `ValueError` | 格式错误必须让用户知道 |
| tsv 读取 IOError | 不捕获，冒泡 | 下游 try/except 决定是否降级 |

## 7. 与 MATLAB 参考实现的关系

- MATLAB `Load_Data_function.m:79-85` 只做了 `dataset_pool → img_set_name` 切名，**没实现路径回退**（因为 MATLAB 跑在采集机上，tsv 路径硬编码永远可达）。本模块增加 `image_vault_paths` 回退是**有意超集**，支持离线机器加载来自另一台机器的 BHV2。
- MATLAB 没检查 `max(Current_Image_Train) == N_rows`（隐式相信数据一致），spec 把这个 sanity check 放到 `NWBWriter.add_trials` —— 不是本模块职责，本模块只负责解析不负责校验。

## 8. 测试清单（`tests/test_io/test_stim_resolver.py`）

### `resolve_dataset_tsv`

1. `test_direct_hit_posix`：tmp_path 下建真 tsv，`dataset_name=str(tsv)` → `(tsv.resolve(), "direct")`
2. `test_direct_hit_windows_path`：`dataset_name="C:\\fake\\path\\x.tsv"` + vault 命中 → fallback 走 vault，`source_tag.startswith("vault:")`
3. `test_none_dataset_name`：`None` → `(None, "no_dataset_name")`
4. `test_empty_dataset_name`：`"   "` → `(None, "no_dataset_name")`
5. `test_vault_single_hit`：direct 不存在，vault 下 rglob 单次命中 → resolved + tag `"vault:<path>"`
6. `test_vault_multi_hit_warns`：两个 vault 都有同名 tsv → caplog WARN + 取首个 + tag 含 `"(multi)"`
7. `test_vault_miss`：direct 失败 + vault 无命中 → `(None, "vault_miss")`
8. `test_vault_nonexistent_dir_skipped`：某个 vault 路径不存在 → DEBUG log，不 raise，继续查其他 vault
9. `test_resolved_path_is_absolute`：direct 命中后返回路径 `.is_absolute()`

### `load_stim_map`

10. `test_roundtrip_small`：写入 3 行 tsv `FileName\tCategory\nA.png\tc1\nB.png\tc2\nC.png\tc1` → `{1:"A.png", 2:"B.png", 3:"C.png"}`
11. `test_missing_filename_column_raises`：tsv 只含 `Image\tCategory` → `ValueError`
12. `test_empty_tsv_returns_empty_dict`：只有 header 行 → `{}`
13. `test_filename_with_special_chars`：`"weird name (1).png"` 原样保留
14. `test_extra_columns_ignored`：3 列 tsv 只取 FileName

## 9. 不处理（out of scope）

- 不支持非 tsv 图集格式（csv/mat/json），未来可能加 `load_stim_map_from_csv` 等姊妹函数
- 不自动下载远程图集（不访问网络）
- 不缓存已解析过的 tsv（每次调用重新读；tsv 通常 < 10k 行，开销可忽略）
- 不校验 `stim_index` 覆盖完整性 —— 这是 `NWBWriter.add_trials` 的职责
