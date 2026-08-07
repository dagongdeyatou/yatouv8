# trace-inspector

M3/M4 工具：查看 L0 replay trace、L1 API ledger、checkpoint diff 和 causal blocker lineage。

当前 M3 slice 已支持：

- 校验 header → 连续 event → footer 的物理 NDJSON 顺序；
- 汇总 eval、resource、timer、input、exception、checkpoint 等 L0 边界；
- 按顺序打印 get/set/call/construct L1 环境 API ledger；
- 保留单调用点，不启用高扰动完整栈。

```powershell
C:\ProgramData\anaconda3\python.exe tools/trace-inspector/trace_inspector.py `
  .yatou/evidence/traces/m3/trace-spine-v1.ndjson --ledger
```

通过 Rust 语义校验后，将 trace 与 headful Chrome snapshot 建立内容寻址 lineage：

```powershell
C:\ProgramData\anaconda3\python.exe tools/trace-inspector/admit_trace.py `
  .yatou/evidence/traces/m3/trace-spine-v1.ndjson `
  --snapshot HEADFUL_SNAPSHOT_PATH
```

完整 V8 Inspector 属于 post-MVP；本工具首先处理可重放、低扰动的结构化 NDJSON 证据。Rust `yatou-schema` 负责语义准入，Python inspector 提供独立物理检查和可读视图。
