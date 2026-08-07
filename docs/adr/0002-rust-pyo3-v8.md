# ADR 0002：Rust + PyO3 + V8 150

- 状态：Accepted
- 日期：2026-08-07
- 决策来源：Q9–Q10、Q15、Q20、Q48、Q55–Q57

## 背景

STPyV8 提供了清晰的 V8 embedding 参考，但 Boost.Python 和其 V8 版本不适合作为新项目底座。`ming_iv8_rs` 证明了 Rust、PyO3 和现代 V8 的可行性。

## 决策

- Runtime 使用 Rust 2024 edition。
- Python 扩展使用 PyO3。
- 锁定 `v8 = 150.4.0`。
- 设置 `V8_FROM_SOURCE=1`，不使用预编译 V8 archive。
- 锁定 Rust 1.97.1、PyO3 0.29.2 和 Python 3.13+。
- 项目使用 Apache-2.0。

## 结果

CI 缓存必须来源于源码构建；nightly 和 release 执行 cold build。所有原生依赖、构建脚本和许可证进入供应链审计。
