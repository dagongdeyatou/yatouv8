# yatouv8 总体架构

`yatouv8` 分成构建时一致性、运行时执行和可选调试三个平面。完整图：

- [HTML + SVG 交互图](yatouv8-overview.html)
- [PNG 预览](yatouv8-overview.png)

## 构建时一致性平面

```text
Chrome 150 Oracle
  → Chrome Collector
  → Evidence Store
  → Diff + Causal Blocker Ranking
  → Surface Manifest
  → Descriptor Generator
```

Chrome 150 的实测行为是唯一规范事实源。Collector 采集 surface、behavior、trace 和 timing distribution；Evidence Store 保存原始证据及 lineage；Diff Engine 找到首个造成执行链分叉的根因；只有经过验证的结构进入 Manifest 和生成器。

## 运行时执行平面

```text
Python API
  → PyO3 command queue
  → Runtime / V8 Isolate owner thread
  → Context / Realm
  → Generated Browser Surface
  → handwritten Rust handlers
```

一个 `Runtime` 拥有一个 V8 Isolate 和 owner thread。所有 V8 调用在 owner thread 上执行，Python 等待时释放 GIL。生成代码负责 constructor、prototype、descriptor 和 trampoline；DOM、CSSOM、Clock、Profile、Resource 等状态语义由 Rust handler 实现。

## Trace 闭环

Trace 分三层：

| 层 | 内容 | 默认用途 |
| --- | --- | --- |
| L0 replay | eval、资源、timer、input、exception、checkpoint | 可重复回放 |
| L1 API ledger | get/set/call/construct、参数、结果、调用点 | blocker ranking；GET 诊断显式开启 |
| L2 debug | 完整栈、Inspector、wrapper 生命周期 | 高开销诊断 |

Runtime 输出的 checkpoint 回流到 Diff Engine，从而形成：

```text
Chrome evidence → Manifest/codegen → yatouv8 runtime → trace replay → diff
```

M6 已把这条闭环落实到公开归档的真实 Google BotGuard 模型：生成环境提供
`addEventListener`、Latin-1 `atob`/`btoa`、可配置 `performance.now()` 和最小
document/iframe realm；Chrome 与 yatouv8 的规范化 trace 为 7/7 一致。

M7–M10 把这条闭环提升为可发布 Runtime：`BrowserRuntime` 在独立 owner thread
持有 persistent Isolate/Context，Python 调用通过 command queue 串行化并释放 GIL；
M8 的 DOM/CSSOM/Event/Timer/Storage/Resource 最小语义用同一 probe 在 Chrome 与
yatouv8 中取得相同哈希；M9 对当前公开双镜像 loader 建立版本化 corpus；M10
增加 wheel、CI、SBOM、性能、并发、异常恢复和 content-addressed 终态准入。

可选 GET tracing 在 V8 global named-property interceptor 与 Browser host 透明代理之间
共享同一个有界事件预算。JS host 事件和 Rust native callback 从同一序号器取号，再按
序号写入 L1，因此 `performance.now`、Trusted Types 等链路的 GET/CALL 不会被分批重排。
该诊断只在用户 source、microtask 和显式 `drain()` 回调期间激活，不污染 bootstrap、
结果序列化或 oracle 默认路径。

## MVP 边界

- 实现最小真实 DOM tree，不做布局和绘制。
- CSSOM 保存样式与 descriptor；`getComputedStyle` 使用固定策略。
- Replay 优先匹配 trace 和 ResourceStore，不回退到真实网络。
- Trusted Types 已由真实阻塞证据晋升；WebGL、Canvas、Worker、Audio 仍需真实 trace 才晋升。
- 第一条端到端路径通过前，不扩张大面积浏览器 API。
