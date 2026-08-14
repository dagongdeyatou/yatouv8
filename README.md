# yatouv8

`yatouv8` 是一个面向 Python 的高性能嵌入式 V8 运行时，提供常用的 BOM、DOM、
CSSOM、事件、时间、存储和网络接口，使 Python 可以直接执行依赖 Web 环境的
JavaScript，无需启动 Chrome、WebDriver 或其他完整浏览器进程。

## 安装

`yatouv8` 已发布到 [PyPI](https://pypi.org/project/yatouv8/)，支持 CPython
3.10–3.14：

```bash
pip install yatouv8
```

## 快速使用

### 执行 JavaScript

```python
import yatouv8

with yatouv8.Runtime() as runtime:
    print(runtime.eval("6 * 7"))
    print(runtime.eval("navigator.userAgent"))
    print(runtime.eval("document.createElement('div').tagName"))
    runtime.eval("globalThis.counter = 1")
    runtime.eval("counter += 41")
    assert runtime.eval("counter") == 42
```

### 注入资源

可以从 Python 注册脚本需要访问的资源：

```python
import yatouv8

with yatouv8.Runtime() as runtime:
    runtime.add_resource(
        "https://example.test/data.json",
        '{"answer": 42}',
        headers={"content-type": "application/json"},
    )
    runtime.eval(
        "fetch('https://example.test/data.json')"
        ".then(response => response.json())"
        ".then(data => globalThis.answer = data.answer)"
    )
    runtime.drain()
    assert runtime.eval("answer") == 42
```

## 支持范围

- Python 3.10、3.11、3.12、3.13、3.14；
- Windows x86_64 / ARM64；
- macOS x86_64 / Apple Silicon；
- Linux glibc / musl，x86_64 / ARM64。

## License

[Apache License 2.0](LICENSE)
