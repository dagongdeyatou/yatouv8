# M5 Surface Manifest 与 descriptor generator

## 结论

M5 已完成：接受的 Chrome 150 headful snapshot 已转换成完整 Surface Manifest，
并生成紧凑 Rust descriptor 表和 runtime installer 输入。

## 生成结果

- baseline：`win11-chrome150.0.7871.188-headful-m2-v2`
- source snapshot SHA-256：`ce7c7cd6e1a3790f47412f48e7aeaf40fdb5dc07754bbd43a045f9891834b914`
- interfaces：29
- members/descriptors：1,785
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
