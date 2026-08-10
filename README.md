# yatouv8

> **yatouv8** 是一个基于 V8 引擎的高性能 Python 原生扩展。它在原生宿主层实现
> 可配置的 BOM、DOM、CSSOM、事件循环、时间、存储、Cookie、Fetch 等浏览器 API，
> 并提供 API 调用链追踪与 V8 Inspector 级执行诊断，使 Python 可以直接运行依赖
> Web 环境的 JavaScript，**无需启动 Chrome、WebDriver 或其他完整浏览器进程**。

`yatouv8` 面向需要“V8 执行能力 + 浏览器宿主环境”的场景。它不是把 JavaScript
交给外部浏览器执行，而是把 V8 Isolate、持久化 Context 和浏览器兼容层直接嵌入
Python 进程，在可控环境中执行普通脚本、动态 `eval`、网页 Bundle 和依赖 Web API
的 JavaScript。

![yatouv8 总体架构](docs/architecture/yatouv8-overview.png)

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 原生 V8 执行 | 嵌入 V8 150.4.0，通过 Rust/PyO3 暴露 Python 原生扩展，不启动浏览器 |
| 持久化运行时 | 每个 `Runtime` 持有独立 Isolate/Context，全局变量、Cookie、Storage 和任务状态可持续存在 |
| 浏览器环境 | 提供 Window、Document、Navigator、Screen、Location、DOM、CSSOM、EventTarget 等宿主对象 |
| Web 运行语义 | 支持 Timer、Microtask、Performance、Storage、Cookie、Fetch、Trusted Types 和页面导航状态 |
| 可控资源模型 | Python 显式注入脚本、JSON、HTML 等资源；离线执行时不会意外回退真实网络 |
| Chrome 行为基线 | API 类型、原型链、descriptor、枚举顺序和关键返回语义以 Windows 11 + Chrome 150 为基线 |
| 调用链监控 | 可记录 API `get`、`set`、`call`、反射操作、Cookie、导航和资源访问 |
| 执行诊断 | 集成 V8 Inspector precise coverage，可定位动态 `eval`、未执行分支和首个环境分叉 |
| Python SDK | 提供值转换、异常映射、资源注入、任务排空、Cookie 导入导出和 challenge 便捷封装 |

适合用于：

- 在 Python 中执行依赖 `window`、`document`、`navigator` 等对象的 JavaScript；
- 运行或测试从网页中提取的脚本和 Bundle；
- 构建可重复的浏览器环境模拟、差分测试和 JavaScript 分析流程；
- 在不启动完整浏览器的情况下追踪脚本读取了哪些环境属性；
- 将 HTTP 客户端取得的页面资源交给 V8 执行，再把 Cookie 与导航结果返回 Python。

## 快速开始

### 直接执行 JavaScript

```python
import yatouv8

with yatouv8.Runtime() as runtime:
    print(runtime.eval("6 * 7"))
    print(runtime.eval("navigator.userAgent"))
    print(runtime.eval("document.createElement('div').tagName"))
```

`Runtime` 是持久化环境，同一个实例中的 JavaScript 状态不会在每次 `eval()` 后丢失：

```python
import yatouv8

with yatouv8.Runtime() as runtime:
    runtime.eval("globalThis.counter = 1")
    runtime.eval("counter += 41")
    assert runtime.eval("counter") == 42
```

JavaScript 异常会映射为 Python `JSException`，异常不会销毁当前 Context：

```python
import yatouv8

with yatouv8.Runtime() as runtime:
    try:
        runtime.eval("throw new TypeError('invalid value')")
    except yatouv8.JSException as error:
        print(error.name, error.message)
```

### 注入资源并运行异步代码

`fetch()` 默认只访问 Python 显式注册的资源，使脚本执行可重复、可审计：

```python
import yatouv8

with yatouv8.Runtime() as runtime:
    runtime.add_resource(
        "https://fixture.invalid/data.json",
        '{"answer": 42}',
        headers={"content-type": "application/json"},
    )
    runtime.eval(
        "fetch('https://fixture.invalid/data.json')"
        ".then(r => r.json())"
        ".then(v => globalThis.answer = v.answer)"
    )
    runtime.drain()
    assert runtime.eval("answer") == 42
```

## 浏览器环境

当前宿主环境覆盖以下主要类别：

- **BOM**：`globalThis`、`window`、`navigator`、`screen`、`location`、`history`、
  `performance`、`crypto`；
- **DOM**：`document`、Element/Node 接口、属性、事件监听、iframe/window 索引；
- **CSSOM**：样式声明存储、descriptor、`getComputedStyle()` 固定返回策略；
- **事件与任务**：EventTarget、Mouse/Pointer/Input 事件、Timer、Microtask、任务排空；
- **状态**：Cookie、local/session storage、页面导航和资源生命周期；
- **安全与反射**：Trusted Types、`Object`/`Reflect`/`Function` 关键语义、原生函数外观；
- **网络边界**：受控 Fetch/Response 和 Python 注入的内容寻址资源。

浏览器 API 的结构面由 Chrome snapshot 和 Surface Manifest 生成，行为面由原生
handler 实现。新增接口必须经过 Chrome 基线采集、snapshot diff 和 conformance
测试，而不是简单堆叠手写 JavaScript shim。

## API 调用追踪

需要知道目标脚本读取、写入或调用了哪些浏览器 API 时，可以显式开启有界 GET
tracing：

```python
import yatouv8

config = yatouv8.RuntimeConfig(
    get_trace=yatouv8.GetTraceConfig(
        enabled=True,
        max_events=50_000,
    )
)

with yatouv8.Runtime(config) as runtime:
    runtime.eval("navigator.userAgent; performance.now(); screen.width")
    for event in runtime.trace["events"]:
        if event["level"] == "l1":
            print(event["entry"])
```

Trace 使用共享递增序号记录 `get`、`set`、`call`、反射、资源、Cookie 和导航操作，
可保留跨原生回调、Microtask 与 Timer 的因果顺序。诊断默认关闭，避免影响普通执行
路径。

## 动态代码与 V8 Inspector 诊断

对于包含多层 `eval`、Function Constructor 或动态加载脚本的代码，可以开启
Inspector precise coverage：

```python
import yatouv8

config = yatouv8.RuntimeConfig(
    execution_trace=yatouv8.ExecutionTraceConfig(
        enabled=True,
        capture_source=True,
        max_scripts=256,
        max_source_bytes=1_048_576,
    )
)

with yatouv8.Runtime(config) as runtime:
    runtime.eval(source)
    capture = runtime.execution_trace
    blockers = yatouv8.analyze_execution_trace(
        capture,
        symbols=("bootstrap", "initialize", "result"),
    )
```

该模式会记录 entry script 与动态脚本的 SHA-256、源码、函数范围、block range 和
执行计数，可用于定位未进入的初始化分支。它不替换 `eval`，也不改写目标源码。

## 与 HTTP 客户端配合

`yatouv8` 本身负责 JavaScript 和浏览器宿主语义；真实 HTTP 请求可以继续由
`curl_cffi`、`httpx` 或其他 Python 客户端负责。典型流程是：

1. Python 请求页面并保存响应、Cookie 与网络计时；
2. 将页面脚本、资源、Cookie 和时钟信息导入 `yatouv8.Runtime`；
3. 在嵌入式 V8 中执行 JavaScript；
4. 将生成的 Cookie、导航 URL 和结果导回 Python；
5. HTTP 客户端继续下一跳请求。

针对单段页面 challenge，项目提供高层封装：

```python
import yatouv8

bundle = yatouv8.solve_with_yatouv8(
    first_response,
    cookie_jar,
    navigation_start_ms=request_start_ms,
)
bundle.apply_cookies(cookie_jar)

next_response = requests.get(
    cookies=cookie_jar,
    **bundle.request_kwargs(),
)
```

`ChallengeBundle` 包含完整 Cookie、下一跳 URL、请求头和执行统计；调用者不必持续
持有原来的 Session 对象。

## 安装与构建

项目包名为 `yatouv8`，支持 CPython 3.10–3.14。正式发布到 PyPI 后可直接安装：

```console
python -m pip install yatouv8
```

在当前源码仓库中，可以安装已经构建好的匹配 wheel：

```console
python -m pip install dist/yatouv8-0.1.0-cp313-cp313-win_amd64.whl
```

Windows 本地构建：

```powershell
# 当前 Python
.\scripts\build-wheel.ps1

# 指定 Python 3.10
.\scripts\build-wheel.ps1 `
  -PythonExecutable "D:\language\python-3.10.1\python.exe"

# Windows ARM64 交叉构建
.\scripts\build-wheel.ps1 `
  -TargetId windows-arm64 `
  -PythonExecutable "D:\language\python-3.10.1\python.exe"
```

完整发布矩阵覆盖：

- Windows x86_64 / ARM64；
- macOS x86_64 / Apple Silicon；
- manylinux glibc x86_64 / ARM64；
- musllinux x86_64 / ARM64；
- 每个平台的 CPython 3.10、3.11、3.12、3.13、3.14。

矩阵共定义 40 个 wheel。构建入口、固定容器和原生验收流程见
[跨平台 wheel 构建说明](docs/building-cross-platform.md)。

## 架构

```text
Python SDK
    │  Runtime / Context / eval / resources / cookies / trace
    ▼
PyO3 Native Bridge
    │  类型转换 / 生命周期 / GIL 释放 / owner-thread 调度
    ▼
yatou-core
    │  Isolate / Context / DOM runtime / event loop / clock / storage
    ▼
V8 150.4.0

Chrome snapshot ──► diff/ranking ──► Surface Manifest ──► descriptor generator
                                         │
                                         └──────────────► 浏览器兼容层
```

Workspace 主要模块：

```text
crates/
├── yatou-core       # V8 Runtime、Isolate、Context 和浏览器行为 handler
├── yatou-py         # Python/PyO3 原生扩展
├── yatou-surface    # 生成的浏览器接口与 descriptor
├── yatou-schema     # Snapshot、Manifest、Profile、Trace 数据合同
└── yatou-harness    # Diff、allowance 与因果 blocker ranking

tools/
├── chrome-collector       # Chrome 基线采集
├── surface-codegen        # Surface Manifest 代码生成
├── semantic-conformance   # Chrome/yatouv8 语义差分
├── trace-inspector        # Trace 与 API ledger 检查
└── release                # wheel、架构、SBOM 和发布审计
```

## 当前边界

- `yatouv8` 是 JavaScript 运行时和浏览器宿主模拟，不是完整浏览器；
- MVP 不包含排版、绘制、字体栅格化和真实页面渲染；
- `getComputedStyle()` 使用可配置的固定返回策略，不实现布局计算；
- 离线 Runtime 的 `fetch()` 只读取显式注入资源，不自动访问真实网络；
- 默认浏览器行为 profile 为 Windows 11 + Chrome 150；
- 跨平台原生发布矩阵已经实现，最终可发布性以各目标 runner 生成并安装 wheel 的
  原生 CI 证据为准。

## 验证

运行不依赖在线服务的完整本地检查：

```powershell
.\scripts\check.ps1
```

从源码构建 V8 并执行 smoke test：

```powershell
.\scripts\build-v8-source.ps1 -Profile release
```

成功输出应包含：

```text
yatouv8 V8 smoke: {"engine":"v8","answer":42,"traceSpine":false}
```

## 文档

- [总体架构说明](docs/architecture/README.md)
- [交互式 HTML 架构图](docs/architecture/yatouv8-overview.html)
- [架构决策记录](docs/adr/README.md)
- [跨平台 wheel 构建](docs/building-cross-platform.md)
- [GET tracing](docs/evidence/get-tracing.md)
- [动态 eval execution trace](docs/evidence/execution-tracing.md)
- [Runtime 与 Python SDK](docs/evidence/m7-runtime-python.md)
- [Host conformance](docs/evidence/m8-host-conformance.md)
- [发布与终态门禁](docs/evidence/m10-release.md)
- [参考项目与固定版本](docs/references.yaml)

## 设计原则

1. Chrome 实测行为是浏览器兼容层的规范来源；
2. `iv8`、`ming_iv8_rs` 和 STPyV8 仅作为行为或实现参考，不作为核心依赖；
3. 新接口需要 Chrome evidence、差分测试和 Manifest 记录；
4. 生成器负责大规模结构面，原生 handler 负责 DOM、CSSOM、Clock 等行为语义；
5. Trace 输出是诊断数据，不能替代可复现测试与最终运行结果。

## License

Apache License 2.0。参考项目的源码与发布物保留各自许可证，详见
[NOTICE](NOTICE) 和 [references.yaml](docs/references.yaml)。
