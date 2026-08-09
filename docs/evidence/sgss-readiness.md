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
| clock | fixture 回放 Chrome 分布；在线模式从 curl total time 启动 0.1 ms 量化单调时钟 |
| navigation timing | curl DNS/TCP/TLS/TTFB/total 同时驱动 legacy timing 与 PerformanceNavigationTiming entry |
| Cookie | `SG_SS` 属性化存储、导入/导出与 Python session handoff 已验证 |
| navigation | `location.replace()` 解析、记录、peek/take 已验证 |
| Trusted Types | `createPolicy`、`createScript` 与 native-like contract 已验证 |
| replay boundary | 资源缺失不回退网络 |

`yatou-core` 现在直接依赖 `yatou-surface`；启动时同时校验生成 Rust 表和
`manifests/chrome150.runtime-surface.json` 的 baseline/member count，二者不一致即拒绝启动。
运行时 host bridge 保存在 V8 private state，不再依赖 JS 可见的 `__yatou*` 属性。

## 2026-08-09 最终兼容迭代

本轮用 Chrome for Testing `150.0.7871.129` 对同一份四段 inline challenge 做了
precise-coverage 与分类器输入对照，并完成以下修复：

- TrustedScript 使用 V8 code-like 模板，原生 `eval(TrustedScript)` 不再依赖包装 `eval`；
- `Event.isTrusted` 的 own accessor、legacy event state、`createEvent("MouseEvents")`、
  `MouseEvent` 字段及 `addEventListener` options 读取顺序与 Chrome 对齐；
- `document.createElement()` 绑定正确 WebIDL prototype，`img/div` 的 brand、constructor
  和字符串默认值不再退化成通用 `HTMLElement`；
- `window.name/status`、`inner=1280x633`、`outer=1280x720`、
  `screen=1920x1080` 使用同一 Win11 headful profile；
- 生成 accessor 的 GET trace 进入统一的 depth/budget 路径，既覆盖原始对象读取，也不再
  与诊断 Proxy 重复计数或越过 `maxEvents`；
- oracle 模式关闭隐藏的 native `performance.now()` observation 分配，避免诊断本身改变
  被测时钟分布。

最终本地实页门禁记录为
`.yatou/evidence/google-vm-live/google-com-ya-fei-offline-final.json`：9 个谓词全部为
`true`，四段脚本零异常，`knitsail=object`、`td.ns/rs` 有序、生成 950 字节 Cookie，
并产生同入口的 `sei` 导航。`window.sgs=undefined` 是当前页面 `sp/ussv` 均为空时的
预期 gate，不是未初始化信号。

同源 decoded VM 的 62,175 字节主体与 Chrome 完全一致（SHA-256
`6b4cfef5f0fdcc1a22727e3533d4f8d0f1bf850eeeb8337d9c031362b522b6e6`）。分类器前
35 次语义输入全部一致；yatouv8 多出的 4 次后续数组探针集中在一个随机采样辅助函数，
不改变 Cookie、timing、knitsail 或 navigation 终态。对照记录位于
`.yatou/evidence/google-vm-live/main-coverage-diff-final.json`。

项目发布流水线 `scripts/run-m10.ps1` 已返回 `terminal_complete`。最终 wheel 为
`dist/yatouv8-0.1.0-cp313-cp313-win_amd64.whl`，SHA-256
`7500de5968bb1abe0e3e9800414c8aff9dbe343a3456962f43e4026650dd4216`；M10 报告位于
`.yatou/evidence/reports/m10/runs/20260809T071107.197469Z-2df7b55e/m10.report.json`。

这里的 12,841/12,841 证明的是 presence、own-key 顺序、descriptor 和 callable
metadata，不等价于 12,841 个成员都具有完整 Chromium 行为。当前在线 VM 是否激活仍以
同一脚本的 first-divergence trace 为准；调用量下降只能说明更早分支退出，不能用门禁
总数替代行为证据。

本轮同时关闭了三个旧的误报方向：Chrome 150 基线的 981 个 global own keys 中本来就
没有 `global`，因此 `globalThis.global === undefined` 不应补成 Node 风格对象；当前页面
的 `sp/ussv` 均为空，`window.sgs` 分支按页面输入关闭；VM 已初始化 `knitsail`、生成
SG_SS 并触发消费，所以不能再用 trace event 数量或 navigator 子属性读取数量判断它
“提前退出”。

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
2026-08-09 已通过 `127.0.0.1:7890` 完成三次 trace-free 同会话在线二跳：每次首次
响应均为 HTTP 200，四段脚本零异常，`knitsail` 初始化，生成 SG_SS 和 `sei` 导航；
第二跳响应链也都写入 `SG_SS=0`，说明一次性 token 已被消费。但最终响应仍为 HTTP 429
`/sorry/`，所以 SearchResultsPage 硬门禁保持失败。记录位于
`.yatou/evidence/google-vm-live/google-com-ya-fei-live-acceptance.json`。

同一代理下，隔离的新 Chrome 151 profile + Chrome 自己生成的 SG_SS 也落入 429；本机
长期用户 Chrome profile 则能直接打开同一搜索。因此当前证据把剩余差异定位到 fresh
session / Google 风险状态，不能再把它单独归因于 yatouv8 API 缺口，也不能据此宣称
在线搜索已通过。正式在线入口为 `tools/google-vm-acceptance/live_runner.py`。

2026-08-09 代理复测还发现并修复了一个真实 handoff 缺陷：当前 mihomo 节点会把
`www.google.com` 地理重定向到 `www.google.com.hk`，Cookie jar 因而可能同时持有
`.google.com` 与 `.google.com.hk` 的同名 `__Secure-STRP`。curl_cffi 的 Cookies 同时
实现 Mapping，旧代码走 `items()` 会抛出 `CookieConflict`；现在优先迭代底层 CookieJar，
保留 domain/path 身份，并以实际重定向后的 `.google.com.hk/search` 作为 Runtime URL
和 `location.replace` 同入口校验基准。

最终一次 `127.0.0.1:7890` 在线记录位于
`.yatou/evidence/google-vm-live/google-com-ya-fei-live-final.json`：首次响应 200、四段
脚本零异常、SG_SS 生成且被服务端消费为 `0`，但第二跳仍被 fresh-session 风险控制转入
HTTP 429 `/sorry/`。同一时刻 Chrome 151 headless 自己执行完整页面也得到相同 429，记录
为 `.yatou/evidence/google-vm-live/google-com-ya-fei-headless-chrome-control-final.json`。
因此 M10、本地 Google VM 和 handoff 验收已完成；公网 SearchResultsPage 仍作为外部
风险状态门禁单独保留，不能伪报为通过。
