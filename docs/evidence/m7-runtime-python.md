# M7 Runtime 与 Python SDK

## 完成条件

- 一个 `BrowserRuntime` 对应一个 owner thread、V8 Isolate 和 persistent Context。
- V8 handle 不跨线程；并发调用通过 command channel 串行化。
- `eval`、`add_resource`、`drain`、`trace`、`environment`、`close` 已成为稳定 Rust API。
- Python `Runtime`/`Context` 等待 native command 时释放 GIL。
- JavaScript exception 返回结构化结果，不销毁 Context。
- `fetch` 仅使用 caller-owned `Resource`；无网络 adapter。

## 发布验证

`scripts/build-wheel.ps1` 构建 `yatouv8-0.1.0-cp313-cp313-win_amd64.whl`，
使用 `--auditwheel repair` 把 `zlib.dll` 收入 `yatouv8.libs`，然后在临时 venv
安装 wheel 并执行三组测试：persistent state/resource/timer/trace、异常恢复、
32 个 Python 并发调用。临时 venv 在测试后删除。
