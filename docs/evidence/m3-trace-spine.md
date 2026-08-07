# M3 Trace spine

## 结论

M3 已完成：`yatouv8` 已有可验证的 L0 replay 数据合同、append-only recorder、严格离线 replay cursor、L1 API ledger 和独立 trace inspector。

## L0 replay

当前类型化边界包括：

- `eval_start` / `eval_end`
- `resource_request` / `resource_response`
- `timer_schedule` / `timer_fire`
- `input`
- `exception`
- `checkpoint`

Rust Schema 强制检查：连续 sequence、非递减 logical time、因果 parent、SHA-256、eval/resource/timer 生命周期和 footer 计数。`ReplayTape` 只消费 trace 中的 L0 记录，没有 Host FetchAdapter；资源 miss 的单元测试确认其返回 `ReplayMismatch`，不会回退真实网络。

## L1 API ledger

L1 合同支持 `get`、`set`、`call`、`construct`，记录 receiver/member、参数摘要、return/throw 和一个低开销调用点。`TraceRecorder::record_l1` 是后续 generated browser-surface trampoline 的统一接入点。

当前 fixture 可打印：

```text
L1 seq=1 GET Navigator.prototype.userAgent
L1 seq=6 CALL Performance.prototype.now
```

## 端到端验证

Fixture：`.yatou/evidence/traces/m3/trace-spine-v1.ndjson`

- Trace ID：`m3-trace-spine-v1`
- Baseline：`win11-chrome150.0.7871.188-headful-m2-v2`
- 总事件：9
- L0：7
- L1：2
- Resource replay status：200
- Replay consumed：全部
- Network fallback：false
- Trace SHA-256：`77734bd7fa7da3771ad642f71bb7bfe8c9700996c0ddda19d149837eff60b846`
- Evidence manifest SHA-256：`f1df5b68beabbc25f5e0dbae1e0565ed76aaa6148acdc4aff3e97542106583a0`

证据链：

```text
Chrome headful snapshot
  └── M3 L0/L1 NDJSON trace
        └── independent inspector summary
```

完整重现：

```powershell
.\scripts\run-m3-spine.ps1
```

## 完成边界

这证明的是 trace 基础设施，而不是“真实 Google VM 已通过”。Fixture 的 `source=fixture` 已写入 header 和 manifest。当前还没有生成后的完整 browser surface，因此尚不能声称已经打印 Chrome 所有 API；从 M5 起，每个 generated trampoline 会调用 L1 入口，届时 ledger 才覆盖已实现环境的全部跨边界调用。

M4 的输入是这套稳定 Trace Schema、checkpoint 和 L1 顺序，用于 differential diff 与首个因果 blocker ranking。
