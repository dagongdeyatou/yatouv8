# google-vm-collector

对固定 SHA-256 的 `InsideReCaptcha/model.js` 与 `enc` 执行两次 Chrome 150
采集：

1. **oracle**：不改写浏览器 API，用于 token shape 的规范结果；
2. **instrumented diagnostic**：只包裹四个已观察 host boundary，生成规范化 L1 trace。

只有 oracle 与 diagnostic 都满足 `string`、`!` 前缀、长度 `199`、无错误、
`navigator.webdriver === false`，且临时 profile 清理成功，run 才会被接纳。

该目标是公开归档的真实 Google reCAPTCHA BotGuard VM，不代表当前在线 Google VM。
