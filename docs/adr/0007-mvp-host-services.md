# ADR 0007：MVP Host Services

- 状态：Accepted
- 日期：2026-08-07
- 决策来源：Q5–Q6、Q17、Q35–Q38、Q43–Q45、Q52–Q53

## 背景

目标脚本需要跨 API 状态一致性，但 MVP 不应实现完整浏览器引擎。

## 决策

- DOM：真实最小 tree、HTML parser、属性、选择器和事件，不做布局。
- CSSOM：保存 style、priority、顺序和 cssText；`getComputedStyle` 使用固定表、inline style 和少量继承。
- Profile：统一驱动 UA、语言、屏幕、GPU、Origin、Storage 等身份字段，Realm 创建后不可变。
- Clock：提供 deterministic、replay、chrome_profile 和 system 模式。
- Entropy：提供 secure、deterministic 和 replay 模式。
- Resource：匹配顺序为 trace、ResourceStore、Host FetchAdapter、确定性失败。
- Runtime limits：限制 heap、deadline、pending tasks、body、trace 和 native objects。

## 结果

Profile 加载时执行跨字段一致性检查。几何 API 使用 Profile DOMRect，不引入布局引擎。真实网络和高级接口必须由 trace 证据晋升。
