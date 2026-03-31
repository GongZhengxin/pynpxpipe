请阅读 legacy_reference/pyneuralpipe/ 目录下的代码，重点关注以下文件：

1. NPX_session_process.ipynb —— 主处理流程
2. core/ 目录下所有 .py 文件（跳过 _bk 后缀的备份文件）
3. config/ 目录下所有 .yaml 文件
4. utils/ 目录下所有 .py 文件
5. Util/ 目录下的个别 .m 文件：mlread.m, mlbhv2.m, bhv_read.m
6. monkeys/ 目录下的 yaml 文件
7. process_session.py
8. PyNeuralPipeline_developplan.md 和 README.md

不需要读的：
- Util/BC/ 目录（MATLAB bombcell，已过时）
- config_editor_gui.py 和 GUI 相关文件（废弃）
- _bk 后缀的备份文件
- tests/ 目录暂时跳过

阅读完成后，请输出一份结构化的分析报告，保存为 docs/legacy_analysis.md，包含：

1.【Pipeline 总览】当前完整的处理流程是什么？每一步做了什么，输入输出是什么？
2.【模块职责】core/ 下每个模块的核心功能、关键函数、对外部库的依赖
3.【配置体系】yaml 配置文件的结构和作用，monkeys/ 的 subject 配置包含什么
4.【已知问题清单】从代码中能看出的问题：
   - 哪里有硬编码路径？
   - 哪里的内存管理有隐患？（特别是 sorting 相关）
   - 哪里只支持单电极，需要改造为多电极？
   - 哪些外部库的用法已过时（对比 spikeinterface 最新版）？
5.【可复用资产】哪些代码逻辑可以直接迁移到新项目？哪些需要重写？
6.【依赖清单】requirements.txt 中的依赖 + 代码中实际 import 的库，列出完整清单