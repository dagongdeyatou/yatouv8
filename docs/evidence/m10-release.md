# M10 发布与终态门禁

M10 的终态准入由 `scripts/run-m10.ps1` 执行：

1. rustfmt、workspace check/test/clippy 和 Python collector tests；
2. V8 150 source smoke、feature tests 与 `-D warnings` clippy；
3. M6 archived BotGuard、M8 Chrome host probe、M9 current public loaders；
4. startup/eval latency、64 caller concurrency、100 exception recovery cycles；
5. repaired CPython 3.13 Windows wheel 安装测试；
6. CycloneDX SBOM、LICENSE/NOTICE、bundled zlib 和 Cargo.lock audit；
7. 所有父报告与产物进入 SHA-256 content-addressed store；
8. 只有全部 predicate 为真才生成 `m10.report.json`。

M10 是 yatouv8 `0.1.0` 的工程完成点，但不改变 MVP 边界：不提供布局/绘制引擎，
也不宣称通过当前在线 Google challenge。
