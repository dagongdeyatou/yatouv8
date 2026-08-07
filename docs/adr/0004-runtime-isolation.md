# ADR 0004：Runtime、Isolate 与 Realm 隔离

- 状态：Accepted
- 日期：2026-08-07
- 决策来源：Q12、Q25、Q40–Q46

## 背景

V8 handle 具有严格线程和生命周期要求；任意 Python 线程直接调用 V8 会造成难以验证的竞态和重入问题。

## 决策

一个 `Runtime` 拥有一个 Isolate 和 owner thread。MVP 每个 Runtime 一个 Context，未来允许多个 Context。Python 通过 command queue 调用 Runtime，等待时释放 GIL；同步重入同一 Runtime 被拒绝。

Native 对象使用稳定 `NativeId`，每个 Realm 维护 weak wrapper cache。Context 关闭后关联 `JSValue` 代理失效。

## 结果

所有 V8 操作具有明确所有者线程和关闭顺序。多个 Runtime 可并行，但不能共享 Local/Persistent handle。
