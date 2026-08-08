# 动态 eval execution trace

## 目的

GET tracing 回答“宿主对象被读了什么”，但不能说明 60KB 动态脚本内部哪些函数和
分支执行。`ExecutionTraceConfig` 通过 V8 Inspector Protocol 捕获：

- `Debugger.scriptParsed`：本轮 eval 新解析的脚本及顺序；
- `Debugger.getScriptSource`：未经改写的 entry/nested eval 源码；
- `Profiler.startPreciseCoverage/takePreciseCoverage`：函数和 block range 次数；
- 源码 UTF-8 长度、SHA-256，以及 zero-count range 周边上下文。

该实现没有 JavaScript 级 `eval` wrapper 替换，不改变 direct/indirect eval、receiver
或函数 `toString()`。yatouv8 自己用于结果封装的脚本会标为
`yatouv8_eval_wrapper`；调用者源码标为 `entry_eval`，其中再次生成的脚本标为
`nested_dynamic_script`。

## Python 用法

```python
import json
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
    runtime.eval(challenge_source)
    capture = runtime.execution_trace

analysis = yatouv8.analyze_execution_trace(
    capture,
    symbols=("knitsail", "td", "sgs"),
)
with open("execution-trace.json", "w", encoding="utf-8") as output:
    json.dump(
        {"capture": capture, "analysis": analysis},
        output,
        ensure_ascii=False,
        indent=2,
    )
```

`analysis.ranked_blockers` 的排序规则：

1. watched symbol 落在 zero-count range 内；
2. nested dynamic script 的其他 zero-count range；
3. entry eval 的其他 zero-count range。

Inspector 使用 UTF-16 code-unit offset；分析器在包含非 BMP 字符时也保持这一坐标，
可直接对应 `startOffset/endOffset`。

## Rust CLI

使用已安装 wheel 对 challenge entry 运行完整分析：

```powershell
py -3.13 tools\execution-trace\runner.py `
  --source C:\path\to\challenge.js `
  --output C:\path\to\execution-trace.json `
  --symbol knitsail --symbol td --symbol sgs
```

如果还要把宿主 GET 事件合并到同一证据文件，增加 `--get-trace`。

也可以直接使用 Rust CLI：

对已有 JavaScript 文件生成独立证据：

```powershell
C:\Users\wuye\.cargo\bin\cargo.exe run -p yatou-core `
  --example execution_trace --features v8-runtime -- `
  C:\path\to\challenge.js `
  C:\path\to\execution-trace.json
```

## 边界

- 默认关闭；最终 Chrome semantic/oracle 门禁必须在关闭 Inspector 后复跑。
- `max_scripts` 和 `max_source_bytes` 是硬边界；截断时仍记录完整源码 SHA-256。
- precise coverage 证明某个源码 range 是否执行，不单独证明某个环境值为何不同；应把
  首个 zero-count 初始化块与 Chrome 命中基线或单变量反事实运行进行比较。
