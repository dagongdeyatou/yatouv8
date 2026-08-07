# ADR 0003：Conformance-first

- 状态：Accepted
- 日期：2026-08-07
- 决策来源：Q3、Q13–Q14、Q21–Q22、Q29–Q32、Q47

## 背景

没有可重复基线和差异分类时，手写 API 无法证明是否改善了目标执行路径。

## 决策

在功能扩张前先实现 Chrome Collector、Evidence Store、Diff Engine 和测试矩阵。Windows 11 上正式版 Chrome 150 的运行时结果是唯一规范 oracle；规范文本和参考项目用于解释，不覆盖实测。

Evidence 分为 surface、environment、distribution 和 behavior。未知差异默认失败，allowance 必须有类型、范围、理由、证据和有效期。

## 结果

每个生成成员都必须关联 Chrome evidence。结构要求精确匹配；环境值由 Profile 管理；时间类差异使用统计 envelope。
