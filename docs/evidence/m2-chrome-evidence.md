# M2 Chrome evidence

## 结论

M2 已完成。Chrome 150 collector 现已具备隔离 profile、原始 CDP、descriptor snapshot、288-sample clock profile、规范化重复 diff、内容寻址、lineage、污染证明和清理验证。

## Headless 重复验证

Baseline：`win11-chrome150.0.7871.188-headless-m2-v2`

| Run | Surface | 稳定字段差异 | Clock samples |
| --- | ---: | ---: | ---: |
| `20260807T114720.890207Z-a91ab766` | 29/29 | 0 | 288 |
| `20260807T114724.561423Z-4394f9ac` | 29/29 | 0 | 288 |

规范化 diff 位于：

```text
.yatou/evidence/reports/m2/headless-v2-repeat-diff.json
```

两个样本均观察到：

- `Date.now()` 最小正增量：1 ms；
- `performance.now()` 最小正增量：约 0.1 ms；
- 两类时钟单调性违例：0；
- 256 个紧循环样本 + 32 个一毫秒 timer 间隔样本。

## Headful 规范基线

正式基线：`win11-chrome150.0.7871.188-headful-m2-v2`

- Run：`20260807T114946.259886Z-02b44a1e`
- Chrome：`Chrome/150.0.7871.188`
- V8/JavaScript：`15.0.245.21`
- OS：Windows 11 `10.0.26100`，AMD64
- UA：`Chrome/150.0.0.0`，不含 `HeadlessChrome`
- `navigator.webdriver=false`
- Screen：1920×1080，available 1920×1032
- Surface：29/29
- `globalThis` own keys：981
- Clock samples：288，单调性违例 0
- Collector pollution：无
- 临时 Chrome profile：已验证清理
- Snapshot SHA-256：`ce7c7cd6e1a3790f47412f48e7aeaf40fdb5dc07754bbd43a045f9891834b914`

可读运行目录：

```text
.yatou/evidence/baselines/win11-chrome150.0.7871.188-headful-m2-v2/runs/20260807T114946.259886Z-02b44a1e/
```

第一次 headful 候选 `headful-m2-v1` 因 `--remote-debugging-port=0` 导致 `navigator.webdriver=true`，已明确拒绝。v2 改用随机非零 loopback CDP 端口，消除了该采集器诱发字段。

## 验证方法

```powershell
C:\ProgramData\anaconda3\python.exe tools/chrome-collector/verify_capture.py RUN_DIRECTORY
cargo run -p yatou-schema --example validate_snapshot -- SNAPSHOT_PATH
C:\ProgramData\anaconda3\python.exe tools/chrome-collector/snapshot_diff.py LEFT RIGHT
```

Lineage：

```text
raw_cdp ──> chrome_snapshot ──> M3 trace fixture
chrome_stderr
```

## 已知边界

基线页面仍为 `about:blank` 非安全上下文，因此 Client Hints、secure-context API 和具体站点行为必须由后续行为 probe 或真实 trace 单独晋升，不能从本 snapshot 推断。
