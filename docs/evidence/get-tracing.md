# GET tracing 诊断合同

## 目标

GET/reflection tracing 用于回答“Google VM 在首个分叉前读取和扫描了哪些环境属性”。
它把 Browser host 边界操作写成 L1，与既有 `call/set/construct` 及 L0
事件组成同一条因果 trace。

该能力是可选诊断面，不是 Chrome oracle 的默认执行模式。关闭时不安装 global
property interceptor，也不代理 Browser host 对象。

## 使用

```python
import yatouv8

config = yatouv8.RuntimeConfig(
    get_trace=yatouv8.GetTraceConfig(
        enabled=True,
        max_events=50_000,
    ),
)

with yatouv8.Runtime(config) as runtime:
    runtime.eval("navigator.userAgent; performance.now(); screen.width")
    for event in runtime.trace["events"]:
        if event["level"] == "l1":
            entry = event["entry"]
            print(entry["operation"], entry["target"], entry["member"])
```

输出顺序为：

```text
get  globalThis             navigator
get  Navigator.prototype   userAgent
get  globalThis             performance
get  Performance.prototype now
call Performance.prototype now
get  globalThis             screen
get  Screen.prototype      width
```

## 覆盖范围

| 场景 | 结果 |
| --- | --- |
| 已存在与缺失的全局属性 | 由 V8 global named-property interceptor 记录 |
| Navigator、Screen、Document、Element、Location、Performance 等嵌套读取 | 由稳定身份的透明代理记录 |
| Trusted Types native factory、policy 与 typed value | 原生 prototype 注册后记录 GET，并与 native CALL 合并 |
| Promise microtask | Runtime 使用 explicit microtask policy，在激活窗口内 checkpoint |
| `setTimeout`、`queueMicrotask` 与 `drain()` | 回调执行期间激活 GET tracing |
| `Object.getOwnPropertyNames` / `Reflect.ownKeys` | 每个扫描 key 记录为 `own_keys` |
| descriptor 扫描 | 记录为 `get_own_property_descriptor` |
| prototype / presence 扫描 | 记录为 `get_prototype_of` / `has` |
| 纯 JavaScript 对象、Array/Map/TypedArray 内部读取 | 不记录；它们不是 Browser host 边界 |

代理缓存保证同一 host 对象重复读取仍保持稳定身份。不可写且不可配置的数据属性遵守
Proxy invariant；内部槽对象不做代理。`window === globalThis`、构造器 `instanceof`、
全局 data/accessor descriptor 和 tracing 关闭时的返回结果都有正向/负向回归。

内建 namespace 保留直接语义 owner：`Math.random` 的 target 是 `Math`，
`JSON.stringify` 的 target 是 `JSON`，不再沿继承链误报为 `Object.prototype`。

## 时序与预算

Rust native callback 与 JS host logger 从同一 `u32` 序号器取号。每次 `eval` 或
`drain` 收集后，两类 observation 按该序号稳定合并，再分配 trace logical time。
这避免了旧实现中“所有 native CALL 在前、所有 host 事件在后”的伪顺序。

`max_events` 限制 GET 与 reflection 诊断事件，允许范围为 `1..=1_000_000`。达到上限后不再保留诊断事件，
但 Runtime 继续执行；Python 的 `runtime.get_trace_stats` 返回 `events` 与 `dropped`
计数。

## 验证

```powershell
python -m unittest python.tests.test_runtime -v
cargo clippy --locked -p yatou-core --features v8-runtime --all-targets -- -D warnings
```

当前回归覆盖：默认关闭、语义一致、缺失属性、descriptor/prototype/own-key/has、硬预算、
native/host 因果顺序、Trusted Types、Promise microtask、drained timer、异常恢复、资源与并发调用。
