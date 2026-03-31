ultrathink：请仔细阅读 legacy_reference/ 中的 core/synchronizer.py，
重点是 process_full_synchronization 函数（或类似的主函数）。

请完成以下分析：

1. 列出该函数的所有步骤（按执行顺序编号），每个步骤说明：
   - 做了什么（一句话）
   - 输入数据来源（哪个文件/通道/变量）
   - 输出是什么
   - 是否有验证/可视化（生成了什么图）

2. 特别关注：
   - photodiode 信号是从哪个通道读取的？模拟通道还是数字通道？
   - photodiode 信号如何检测 stimulus onset？（阈值检测？峰值检测？）
   - photodiode 校准的精度提升了多少？（相比纯数字事件码）
   - 有哪些边界情况处理？（如 photodiode 信号丢失、噪声等）

3. 找出旧代码中的硬编码值：
   - 通道名、采样率、阈值、事件码等所有 magic number
   - 这些值在新架构中应该放在哪里（config 还是从数据自动读取）

4. 旧代码中是否有中间结果的可视化/验证步骤？
   如果有，列出每个图的内容和用途。
   如果没有，建议在哪些关键节点加入诊断图。

请将分析结果输出为 docs/sync_analysis.md