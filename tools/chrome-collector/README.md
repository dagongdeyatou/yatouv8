# chrome-collector

M2 工具：启动固定的 Chrome 150 二进制，通过原始 CDP 采集环境和 surface descriptor evidence。

## 当前能力

- 每次运行使用独立临时 `--user-data-dir`。
- Probe 只读取 descriptor，不调用 accessor，也不向 `globalThis` 写值。
- 从全局 data descriptor 动态发现全部构造器、prototype 与内建 namespace；固定
  29 接口列表只作为必须存在的核心种子，不再是覆盖上限。
- 采集前后比较完整全局 key 序列并保存污染证明。
- 使用独立 CDP object group，结束后显式释放。
- 保存原始 CDP NDJSON、规范化 snapshot、Chrome stderr 和 lineage manifest。
- 所有证据进入 SHA-256 content-addressed store。

## 运行

```powershell
.\tools\chrome-collector\run.ps1
```

默认写入 `.yatou/evidence`，默认采用 `headless` 模式。该模式用于验证 collector；正式规范基线必须单独采集并标记 `headful`。

验证 Rust schema：

```powershell
cargo run -p yatou-schema --example validate_snapshot -- SNAPSHOT_PATH
```

独立验证一次运行的 content address、lineage、可读副本和污染证明：

```powershell
C:\ProgramData\anaconda3\python.exe tools/chrome-collector/verify_capture.py RUN_DIRECTORY
```

运行 collector 单元测试：

```powershell
C:\ProgramData\anaconda3\python.exe -m unittest discover tools/chrome-collector/tests
```
