# M6 归档真实 Google BotGuard 路径

## 结论

M6 已对一条公开归档的真实 Google reCAPTCHA BotGuard VM 路径完成端到端闭环。
这证明的是固定 `model.js + enc` artifact，不宣称当前在线 Google VM 已通过。

## 目标与 lineage

- 来源：`neuroradiology/InsideReCaptcha`
- commit：`5176f31a7dc87654bcf3e9fa98d62bd537bea32b`
- `model.js`：`eb283e820750810020f120000c99008dcf8930d9ce9d8b881a01ff88157bb9ff`
- `enc`：`f2f5fee92d9717e207fc88d4c9893370df86d23e78c47252fbf0f30422f086f0`
- M6 run：`20260807T125641.658258Z-f375a686`

## 双侧结果

Chrome 150.0.7871.188 的未插桩 oracle 与 yatouv8 都返回：

- JavaScript type：`string`
- 前缀：`!`
- 长度：199
- error：null

token 含随机字节，因此不比较 token 本身。比较的是结果 shape checkpoint 与四个
真实 host boundary 的顺序和摘要：

```text
addEventListener → atob(9720→7290) → performance.now → btoa(148→200)
```

完整 trace 含 3 个 L0 与 4 个 L1 事件；Chrome/yatouv8 7/7 一致。ReplayTape
全消费所有 L0，且没有网络 fallback。

## 因果收敛

首轮 yatouv8 token 长度为 2,777。诊断性 VM error ledger 定位首个根因为 iframe
element 缺少 `contentWindow`，导致读取 `contentWindow.String` 时抛错并把错误栈
编码进 token。补齐 iframe realm 引用后，token shape 收敛到 Chrome 的 199，未横向
扩张 Canvas、WebGL、Worker 或 TrustedTypes。

## Oracle 与插桩隔离

Chrome 每次 run 执行两个独立 target：

1. 未修改 API 的 oracle 决定规范结果；
2. 仅包裹四个已观察 boundary 的 diagnostic 生成 L1。

只有两者均保持 199 长度、`!` 前缀、无错误、`webdriver=false` 才准入。原始 CDP、
Chrome stderr、双方 trace、diff、replay、负控和最终报告均进入 content-addressed
evidence store；临时 Chrome profile 清理已验证。

## Negative controls

- 删除 yatouv8 `atob` 事件：拒绝，首个 blocker=`missing_surface`
- 篡改 `botguard.result.shape`：拒绝，首个 blocker=`behavioral`
- 资源 miss：既有 ReplayTape 测试返回 mismatch，不访问网络

终态报告 SHA-256：`be8116094da6782b411e17a1f5ee8566abdfb2c489ad2060e9a6e9c836548876`。
