# M5 Surface Manifest 与 descriptor generator

## 结论

M5 已完成：接受的 Chrome 150 headful snapshot 已转换成完整 Surface Manifest，
并生成紧凑 Rust descriptor 表和 runtime installer 输入。

## 生成结果

- baseline：`win11-chrome150.0.7871.188-headful-m2-v3-full`
- source snapshot SHA-256：`4d6287f79a5a4f9b0d918e10348fb8ff40fe6c35a8a03854833df438ac7c5417`
- surfaces：1,469（其中 prototype 731）
- members/descriptors：12,841
- callable/getter/setter metadata：9,565
- `globalThis` own keys：981
- manifest：`manifests/chrome150.surface.json`
- Rust 输出：`crates/yatou-surface/src/generated/chrome150.rs`
- runtime 输出：`manifests/chrome150.runtime-surface.json`

Manifest 逐成员保存 key kind、own-key 顺序、owner、data/accessor kind、
configurable/enumerable/writable、callable/getter/setter、HandlerId 和父证据。
validator 拒绝无证据成员、重复接口、顺序漂移和空 HandlerId。

`yatou_core::dispatch_surface_with_l1` 是生成 binding 的共享语义入口：调用手写 handler 后把相同
operation、receiver、member、参数摘要和 outcome 写入 L1 ledger。生成器不猜测 DOM、
CSSOM、Clock 或资源语义。

旧版 v2 仅采集固定 29 个核心接口，不能代表 VM 所需浏览器面完整。v3-full
通过 `globalThis` 的 data descriptor 动态发现构造器及其 prototype，全程不调用
accessor；Chrome 临时 profile 清理、零全局污染和内容寻址证据均已验证。
