# ADR 0001：Google VM 定向兼容层

- 状态：Accepted
- 日期：2026-08-07
- 决策来源：Q1、Q4–Q8、Q14、Q34、Q58–Q59

## 背景

完整复刻 Chromium 会把项目拖入布局、绘制、网络和海量 Web API，无法证明哪些能力对目标执行路径有价值。

## 决策

`yatouv8` 首先面向 Windows 11 + Chrome 150 的 Google VM 定向兼容。MVP 不实现布局和绘制；接口优先级由真实 trace 和因果 blocker 决定。固定的 `bootstrap_p0` 只提供启动、DOM、事件、时间、资源和基础身份所需能力。

## 结果

- 第一条真实 trace 通过前，不横向扩展大接口面。
- Chrome 版本通过独立 baseline/profile 管理。
- “存在很多 API”不是完成标准，端到端回放和证据覆盖才是。
