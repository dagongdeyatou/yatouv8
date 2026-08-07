# M4 Trace diff 与因果 blocker ranking

## 结论

M4 已完成。`yatou-harness::compare_traces` 对 Chrome oracle 与 yatouv8 的类型化
L0/L1 stream 做顺序比较，并输出首个分叉、分类、受影响范围和可审计的因果评分。

## 规则

- L1 缺失或错位：`missing_surface`
- descriptor/checkpoint/结果差异：`behavioral` 或 `structural`
- timer 或 logical-time envelope：`timing`
- L0 顺序差异：`scheduling`
- 排名：`severity × causal_earliness × recurrence × dependency_fanout`

首个 divergence 被视为后续分叉的候选 causal root，但报告仍保留全部原始差异，
不会用评分替代证据。

## 验证

单元测试覆盖完全一致、首个 L1 缺失、checkpoint digest 差异和 timing allowance。
M6 的正向双侧 trace 得到：

```json
{"matching_prefix_events":7,"divergences":[],"blockers":[],"conformant":true}
```

负控移除 `atob` 后，首个 blocker 被分类为 `missing_surface`，因果分数
`28.571428571428573`；篡改结果 checkpoint 后被分类为 `behavioral`。
