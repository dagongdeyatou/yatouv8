# SG_SS 定向兼容与最终本地验收

本轮针对“Google 搜索 SG_SS”流程补齐结构扫描、时钟、Cookie 与导航交接。验收入口：

```powershell
.\scripts\run-sgss-acceptance.ps1
```

## 已满足的本地门禁

| Predicate | 结果 |
| --- | --- |
| Chrome 150 runtime surface | 1,469 surfaces / 12,841 members 全部存在 |
| descriptor 基本形状 | 12,841 / 12,841 精确匹配 |
| callable/getter/setter metadata | 9,565 / 9,565 精确匹配 |
| `globalThis` own keys | 981，集合及 observable 顺序与已接纳基线一致 |
| 内部全局泄漏 | `__yatou*`、`_listeners` 为 0 |
| brands | Navigator、Screen、Location、Performance、Document 匹配 |
| reflection trace | `own_keys`、`get_own_property_descriptor`、`get_prototype_of`、`has` 已验证 |
| clock | 回放 Chrome 录制分布；800 次调用存在重复值，非逐次固定递增 |
| Cookie | `SG_SS` 属性化存储、导入/导出与 Python session handoff 已验证 |
| navigation | `location.replace()` 解析、记录、peek/take 已验证 |
| Trusted Types | `createPolicy`、`createScript` 与 native-like contract 已验证 |
| replay boundary | 资源缺失不回退网络 |

`yatou-core` 现在直接依赖 `yatou-surface`；启动时同时校验生成 Rust 表和
`manifests/chrome150.runtime-surface.json` 的 baseline/member count，二者不一致即拒绝启动。
运行时 host bridge 保存在 V8 private state，不再依赖 JS 可见的 `__yatou*` 属性。

这里的 12,841/12,841 证明的是 presence、own-key 顺序、descriptor 和 callable
metadata，不等价于 12,841 个成员都具有完整 Chromium 行为。当前在线 VM 是否激活仍以
同一脚本的 first-divergence trace 为准；调用量下降只能说明更早分支退出，不能用门禁
总数替代行为证据。

## SG_SS 本地流程

`sgss_acceptance` 使用 Google Search 形状的 fixture URL 执行：

1. descriptor/reflection 扫描；
2. Trusted Types policy 与 script；
3. `atob` 与 800 次 `performance.now()`；
4. `document.cookie = SG_SS=...`；
5. `location.replace(...&sei=...)`；
6. Rust/Python 导出 Cookie 并消费 pending navigation；
7. 验证 L1 因果 trace 和零 dropped event。

## 外部在线验收边界

本地门禁不硬编码 `window.td`、`window.sgs` 或真实 `SG_SS`。最终在线第二跳仍必须使用
同一时刻取得的首次 `/search` 响应、脚本资源、Cookie 和 `location.replace` URL。
2026-08-08 本机对 `https://www.google.com/search?q=yatouv8` 的单次
`curl_cffi` 探测在 20 秒后连接超时，因此没有伪造“在线 SearchResultsPage 已通过”的结论。
拿到可访问的挑战响应后，可直接使用 `Runtime.eval_challenge()`、`import_cookies()`、
`export_cookies(session)` 和 `take_navigation()` 完成同会话第二跳验收。
