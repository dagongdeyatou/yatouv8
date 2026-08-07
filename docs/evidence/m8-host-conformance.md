# M8 Host conformance

M8 实现 MVP 范围内的 DOM tree、selector、attribute/class、CSSStyleDeclaration、
固定 `getComputedStyle`、EventTarget、timer/microtask drain、Storage、Cookie、
Response/Headers/fetch/XMLHttpRequest 和 deterministic crypto。布局、绘制、Canvas
像素和 WebGL 不在此阶段。

同一个 `tools/host-conformance/probe.js` 分别在 Chrome 150 与 yatouv8 执行，
覆盖 DOM mutation/query、inline CSSOM、one-shot event、iframe surface 和 navigator。
准入结果：

- canonical result SHA-256：`6e98db0e8ed777801ad03b02e8101cc9906c2a4cbfc475e9f7f3e3a40e8db0c7`
- Chrome/yatouv8：完全一致
- Chrome profile cleanup：已验证
- yatouv8 trace：完整
- network fallback：`false`

重现：`scripts/run-m8.ps1`。
