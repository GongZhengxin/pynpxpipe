# Spec Revision Plan

## 目标

系统化改善全部 22 个 spec 文件，主要工作：

1. **MATLAB 对照**：涉及 MATLAB 实现的 spec 增加 `## N. MATLAB 对照` 小节（摘要 + ground_truth 指针）
2. **接口契约**：确保相邻 spec 的 output type ↔ input type 严格匹配（dataclass 名/字段一致）
3. **ground truth 纠错**：将 architecture.md S7 的 5 个 ❌ 差异落实到具体 spec 的实现约束中
4. **轻量打磨**：修复过期引用、补全遗漏的测试场景、统一节号格式

---

## 分类与优先级

### P0 — 含 ❌ 关键 bug，影响实现正确性（4 个）

| Spec | 行数 | 对应 MATLAB 步骤 | ❌ 差异编号 |
|------|------|-----------------|-----------|
| imec_nidq_align.md | 172 | #6 | ❌1 缺 sync pulse repair |
| photodiode_calibrate.md | 318 | #10, #11 | ❌2 缺极性校正 |
| postprocess.md | 325 | #9, #15, #18, #19 | ❌4 缺方向性过滤, ❌5 trial_valid_idx 语义 |
| preprocess.md | 238 | #13 | ❌3 phase_shift 顺序（ADR-002 已修正，需确认 spec 一致） |

### P1 — 🟡 待实现模块，spec 质量直接决定实现质量（7 个）

| Spec | 行数 | 对应 MATLAB 步骤 |
|------|------|-----------------|
| bhv_nidq_align.md | 333 | #7, #8 |
| synchronize.md | 396 | 编排 #6-#12 |
| curate.md | 256 | #14 |
| sort.md | 260 | #13 |
| export.md | 275 | #20 |
| nwb_writer.md | 170 | #20 |
| sync_plots.md | 388 | #12 |

### P2 — ✅ 已实现模块，补 MATLAB 对照 + 接口校验（3 个）

| Spec | 行数 | 对应 MATLAB 步骤 |
|------|------|-----------------|
| discover.md | 198 | #0, #2, #5 |
| spikeglx.md | 219 | #0, #1, #5 |
| bhv.md | 260 | #2, #3 |

### P3 — 基础设施，无 MATLAB 对照，仅做接口校验 + 轻量打磨（8 个）

| Spec | 行数 |
|------|------|
| config.md | 441 |
| checkpoint.md | 468 |
| resources.md | 536 |
| logging.md | 356 |
| session.md | 307 |
| base.md | 143 |
| runner.md | 262 |
| cli_main.md | 260 |

---

## 执行策略：6 个 Batch，每 Batch 一个独立 session

### 上下文预算

每个 batch 的上下文消耗估算：

| 素材 | tokens 估算 |
|------|------------|
| CLAUDE.md（自动加载） | ~3.5k |
| 本计划文件 | ~2k |
| architecture.md 相关 section | ~1-2k |
| ground_truth 相关步骤（按需读取） | ~2-4k |
| 待修订 spec（2-4 个） | ~2-4k |
| 源代码（校验接口时按需读取） | ~1-2k |
| 工作输出 | ~4-6k |
| **合计** | **~16-24k**（安全范围） |

### Batch 定义

#### Batch 1: Sync 核心（P0 × 2 + P1 × 1）
- **Specs**: imec_nidq_align.md, photodiode_calibrate.md, bhv_nidq_align.md
- **总行数**: 823
- **读取 ground truth**: step4 #6-#11, step5 #6-#11 对应段落
- **核心任务**:
  - imec_nidq_align: 增加 sync pulse repair 算法描述（检测 >1200ms gap → 插值修复）
  - photodiode_calibrate: 增加极性校正步骤（逐 trial 检测信号方向，下降沿翻转）
  - bhv_nidq_align: 校验与上游两个模块的接口匹配
  - 三个 spec 各加 MATLAB 对照小节
- **接口链校验**: spikeglx → imec_nidq_align → synchronize, bhv → bhv_nidq_align → synchronize

#### Batch 2: Sync 编排 + 诊断（P1 × 2）
- **Specs**: synchronize.md, sync_plots.md
- **总行数**: 784
- **前置**: Batch 1 完成（synchronize 消费 Batch 1 三个模块的输出）
- **核心任务**:
  - synchronize: 校验与 Batch 1 三模块的 I/O 类型对齐；加 MATLAB 对照
  - sync_plots: 校验 6 张图的输入数据来源与 synchronize 输出匹配
- **接口链校验**: imec_nidq_align + bhv_nidq_align + photodiode_calibrate → synchronize → sync_plots

#### Batch 3: Postprocess（P0 × 1，此 spec 涵盖 4 个 MATLAB 步骤，单独一个 batch）
- **Specs**: postprocess.md
- **总行数**: 325
- **读取 ground truth**: step4 #9, #15, #18, #19
- **核心任务**:
  - 增加方向性过滤条件描述（mean(response) > mean(baseline)）
  - 明确 trial_valid_idx 语义及与 MATLAB 的差异处理策略
  - 加 MATLAB 对照小节（覆盖 4 个步骤）
- **接口链校验**: curate → postprocess → export

#### Batch 4: Preprocess + Sort + Curate（P0 × 1 + P1 × 2）
- **Specs**: preprocess.md, sort.md, curate.md
- **总行数**: 754
- **读取 ground truth**: step4 #13, #14
- **核心任务**:
  - preprocess: 确认 ADR-002 已正确体现，加 MATLAB 对照
  - sort: 校验与 preprocess 的 Zarr 输出接口匹配，加 MATLAB 对照
  - curate: 校验 Bombcell 阈值参数与 MATLAB step #14 一致性，加 MATLAB 对照
- **接口链校验**: preprocess → sort → curate → postprocess（后者 Batch 3 已做）

#### Batch 5: IO + Discover（P2 × 3 + P1 × 1）
- **Specs**: spikeglx.md, bhv.md, discover.md, nwb_writer.md
- **总行数**: 847
- **读取 ground truth**: step4 #0-#5, step5 #0-#5
- **核心任务**:
  - 三个已实现模块补 MATLAB 对照小节
  - nwb_writer: 校验与 export stage 的接口匹配
  - 校验 discover 输出的 Session 对象字段是否满足下游所有 stage 的需求
- **接口链校验**: spikeglx + bhv → discover → session 对象 → 所有下游 stage

#### Batch 6: 基础设施（P3 × 8，轻量扫描）
- **Specs**: config, checkpoint, resources, logging, session, base, runner, cli_main
- **总行数**: 2773
- **核心任务**:
  - 校验 config spec 中的参数键名与各 stage spec 中引用的键名一致
  - 校验 session dataclass 字段是否覆盖所有 stage 的需求
  - 校验 runner 的 STAGE_ORDER 与 architecture.md 一致
  - 轻量格式统一（节号、措辞）
  - **不加 MATLAB 对照**（无对应步骤）
- **注意**: 8 个 spec 共 2773 行，但修改量小，以读 + 校验为主；如上下文紧张可拆为 6a（config/checkpoint/resources/logging）+ 6b（session/base/runner/cli_main）

---

## 每个 Spec 的修订检查清单

对每个 spec，按以下顺序检查并修改：

```
□ 1. 读 architecture.md 对应 stage 摘要，确认 spec 与摘要无矛盾
□ 2. 读 ground_truth 对应 MATLAB 步骤（如适用）
□ 3. 检查/增加 "MATLAB 对照" 小节（P0-P2）：
     - 对应 MATLAB 步骤编号
     - 有意偏离及理由（一句话）
     - 指向 ground_truth 文件的具体行范围
□ 4. 接口契约校验：
     - 输入类型/字段是否与上游 spec 的输出定义一致
     - 输出类型/字段是否被下游 spec 正确引用
     - dataclass 名称拼写一致
□ 5. ❌ 差异落实（仅 P0）：
     - 将缺失的算法步骤写入 spec 的"处理步骤"小节
     - 在测试范围中增加对应测试场景
□ 6. 轻量打磨：
     - 节号连续（不跳号）
     - 无过期文件路径引用
     - 参数名与 config spec 中的键名一致
□ 7. 更新 REVISION_PLAN.md 中的进度状态
```

---

## 跨 Session 进度追踪

每个 batch 完成后更新下表。新 session 开头读此文件即可接续。

| Batch | Specs | 状态 | 完成日期 | 备注 |
|-------|-------|------|---------|------|
| 1 | imec_nidq_align, photodiode_calibrate, bhv_nidq_align | ✅ 完成 | 2026-04-05 | +repair算法, +极性校正, +MATLAB对照×3 |
| 2 | synchronize, sync_plots | ✅ 完成 | 2026-04-05 | +gap_threshold_ms传递, +极性校正流程图, +MATLAB对照×2 |
| 3 | postprocess | ✅ 完成 | 2026-04-05 | +方向性过滤, +trial_valid语义说明, +eye_threshold配置, +MATLAB对照 |
| 4 | preprocess, sort, curate | ✅ 完成 | 2026-04-05 | ADR-002确认, +MATLAB对照×3 |
| 5 | spikeglx, bhv, discover, nwb_writer | ✅ 完成 | 2026-04-05 | +MATLAB对照×4 |
| 6 | config, checkpoint, resources, logging, session, base, runner, cli_main | ✅ 完成 | 2026-04-05 | +PostprocessConfig+EyeValidationConfig, +SyncConfig补全, +Session.config字段, cli_main.delete→clear修正 |

---

## Session 启动模板

每个新 session 开头发送：

```
继续 spec revision 工作。请先读 docs/specs/REVISION_PLAN.md 确认当前进度，
然后执行下一个未完成的 Batch。每完成一个 spec 立即更新计划中的进度表。
```

---

## 质量保障

1. **单 spec 完成即更新进度**：不要等 batch 全做完才标记，防止中断丢进度
2. **ground truth 按需读取**：只读当前 batch 涉及的 MATLAB 步骤，不要一次性加载整个 step4/step5
3. **接口校验双向做**：修改一个 spec 的输出类型时，grep 所有引用该类型的其他 spec 确认无破坏
4. **每 batch 结束验证**：检查修改后的 spec 行数未膨胀超过 +30%（避免冗余）
5. **Batch 依赖**：Batch 2 必须在 Batch 1 之后（synchronize 消费 sync 子模块输出）；其余 batch 可按任意顺序
