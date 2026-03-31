根据 CLAUDE.md 的规范和 docs/legacy_analysis.md 的分析，完成以下两件事：

## 任务一：创建 docs/architecture.md

详细设计文档，包含：

1. Session 生命周期：从创建到各 stage 完成的状态流转图
2. 每个 Stage 的详细设计：
   - 输入：需要什么数据/前置 stage 的输出
   - 处理逻辑：关键步骤（用文字描述，不写代码）
   - 输出：产出什么文件/对象
   - checkpoint：保存什么信息来支持断点续跑
   - 内存管理：该 stage 的内存敏感点和应对策略
3. synchronize 的两级对齐流程图（IMEC↔NIDQ, BHV2↔NIDQ）
4. 配置文件设计：pipeline.yaml 和 sorting.yaml 的完整字段定义
5. NWB 输出结构：多 probe 数据在 NWB 中的组织方式
6. 错误处理策略：每个 stage 可能的失败场景和恢复方式

## 任务二：创建代码骨架

创建所有目录和模块文件，每个文件只包含：
- 类定义（含 __init__ 签名和参数类型）
- 公开方法签名（含参数类型和返回类型）
- Google style docstring（说明功能、参数、返回值）
- 方法体只写 raise NotImplementedError("TODO")

同时配好 pyproject.toml 的全部依赖声明和 ruff 配置。

注意：严格遵循 CLAUDE.md 中的目录结构和设计原则。