# ADR 0006：分层 Trace 与因果 blocker

- 状态：Accepted
- 日期：2026-08-07
- 决策来源：Q7、Q26–Q27、Q33、Q43、Q50、Q62

## 背景

全量调试 Hook 会改变目标行为，简单统计缺失 API 又无法区分根因和级联错误。

## 决策

Trace 分为 L0 replay、L1 API ledger 和 L2 debug。L0 保存可重放 host-boundary 事件；L1 保存 browser-surface 的 get/set/call/construct；L2 仅在诊断时启用 Inspector 和完整栈。

Blocker 按严重度、因果顺序、复现频率和依赖扇出排序。级联错误归并到首个根因。Replay 中未匹配资源不得回退到真实网络。

## 结果

Trace spine 在大规模 API 开发前完成。原始敏感 trace 存放在 `.yatou/evidence`，提交仓库的 fixture 必须最小化并脱敏。
