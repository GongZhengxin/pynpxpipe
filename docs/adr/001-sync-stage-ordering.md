# ADR-001: synchronize 放在 sort 之后、curate 之前

## 状态
接受

## 上下文
synchronize 阶段（时间同步 + 行为事件解析）在 pipeline 中的位置有争议。
旧代码放在最后（所有处理完再同步），但 SLAY 计算和眼动验证都需要同步后的时间信息。

## 决策
synchronize 放在 sort 之后、curate 之前。
顺序：discover → preprocess → sort → synchronize → curate → postprocess → export

## 理由
- curate 阶段未来可能需要行为事件信息（如按条件筛选 unit）
- postprocess 的 SLAY 计算必须依赖同步后的 stimulus onset 时间
- postprocess 的眼动验证必须依赖同步后的 trial 时间轴
- synchronize 不依赖 sorting 的质控结果，可以在 sort 后独立运行

## 考虑过但拒绝的方案
- 放在 export 之前（旧代码方式）：SLAY 和眼动验证无法使用同步时间
- 放在 preprocess 之前：synchronize 需要先发现 probe（依赖 discover）

## 影响
- synchronize 必须能在没有 curate 结果的情况下独立运行
- BHV2 解析（需要 MATLAB 引擎）的耗时会阻塞 curate 之后的所有 stage
