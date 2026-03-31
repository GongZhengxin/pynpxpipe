# pynpxpipe 开发进度

## 构建块状态

状态标记：⬜ 未开始 | 🟡 spec 已写 | 🔵 实现中 | ✅ 完成（测试通过+committed）| 🔴 阻塞

### Layer 0: 基础设施（无业务依赖）
| 模块 | 文件 | 状态 | 依赖 | 备注 |
|------|------|------|------|------|
| 配置加载 | core/config.py | ⬜ | 无 | |
| 结构化日志 | core/logging.py | ⬜ | 无 | |
| Checkpoint | core/checkpoint.py | ⬜ | 无 | |
| 资源探测 | core/resources.py | ⬜ | 无 | |
| Session 对象 | core/session.py | ⬜ | config, checkpoint | |
| Stage 基类 | stages/base.py | ⬜ | session, logging, checkpoint | |

### Layer 1: IO 层（数据读写）
| 模块 | 文件 | 状态 | 依赖 | 备注 |
|------|------|------|------|------|
| SpikeGLX 读取 | io/spikeglx.py | ⬜ | 无 | |
| BHV2 解析 | io/bhv.py | ⬜ | MATLAB Engine | |
| NWB 写入 | io/nwb_writer.py | ⬜ | 无 | |
| IMEC↔NIDQ 对齐 | io/sync/imec_nidq_align.py | ⬜ | io/spikeglx | |
| BHV2↔NIDQ 对齐 | io/sync/bhv_nidq_align.py | ⬜ | io/bhv | |
| Photodiode 校准 | io/sync/photodiode_calibrate.py | ⬜ | 无 | |
| 同步诊断图 | io/sync_plots.py | ⬜ | matplotlib | |

### Layer 2: Stages（处理阶段）
| 模块 | 文件 | 状态 | 依赖 | 备注 |
|------|------|------|------|------|
| discover | stages/discover.py | ⬜ | base, io/spikeglx | |
| preprocess | stages/preprocess.py | ⬜ | base, io/spikeglx | |
| sort | stages/sort.py | ⬜ | base | |
| synchronize | stages/synchronize.py | ⬜ | base, io/sync/* | |
| curate | stages/curate.py | ⬜ | base | |
| postprocess | stages/postprocess.py | ⬜ | base | |
| export | stages/export.py | ⬜ | base, io/nwb_writer | |

### Layer 3: 编排与入口
| 模块 | 文件 | 状态 | 依赖 | 备注 |
|------|------|------|------|------|
| Pipeline Runner | pipelines/runner.py | ⬜ | all stages, resources | |
| CLI 入口 | cli/main.py | ⬜ | pipelines/runner | |
