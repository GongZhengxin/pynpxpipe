背景：当前 F:\tools\pynpxpipe\docs\architecture.md 中 pipeline.yaml 中的资源参数（n_jobs, chunk_duration, max_memory）是固定值，
用户换机器后需要手动修改。我们需要一个 ResourceDetector 模块，
在 pipeline 启动时自动探测硬件能力，智能设置默认参数。

请完成以下设计：

1. 探测项目清单：
   - 需要探测哪些硬件指标？（CPU、内存、GPU、磁盘）
   - 每个指标用什么 Python API 获取？（列出具体函数调用）
   - 哪些指标在 Windows 上有兼容性问题？

2. 参数推算规则：
   - 基于我们的数据特点（小型数据：单个 AP bin 20-60G, 中型数据： 单个 AP bin 120-200G， 大型数据：单个 AP bin 400-500GB，384通道，30kHz采样率），
     推算 chunk_duration 的公式是什么？
   - n_jobs 应该怎么根据 CPU 核数和内存设置？
   - 多 probe 并行的 max_workers 怎么根据内存决定？
   - sorting 的 batch_size 怎么根据 GPU 显存调整？

3. 配置优先级设计：
   - 用户显式配置 > 自动探测 > 硬编码兜底值
   - pipeline.yaml 中怎么表示"使用自动值"？（建议用 "auto" 关键字）

4. 输出格式：
   - ResourceDetector 探测结果应该以什么格式记录到日志？
   - 是否需要在 pipeline 启动时向用户显示资源摘要？

请将设计输出为 docs/resource_design.md，
同时给出 core/resources.py 的类签名和公开方法签名（不写实现）。