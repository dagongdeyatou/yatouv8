# surface-codegen

M5 工具：读取经过验证的 Surface Manifest，生成 constructor/prototype 安装代码、descriptor、HandlerId glue 和 golden tests。

生成器不推断返回值或浏览器语义；没有 `evidence_refs` 的成员不得进入生成输出。

```powershell
python tools/surface-codegen/generate.py `
  --snapshot .yatou/evidence/baselines/win11-chrome150.0.7871.188-headful-m2-v2/runs/20260807T114946.259886Z-02b44a1e/snapshot.json `
  --manifest manifests/chrome150.surface.json `
  --rust crates/yatou-surface/src/generated/chrome150.rs `
  --runtime manifests/chrome150.runtime-surface.json
```

输出完整保留 Chrome 的 interface 顺序、own-key 顺序、descriptor flags、native
callable 元数据和直接父证据 SHA-256。Rust 表和 stripped runtime manifest 由同一次
生成产生；`yatou-core` 启动时校验二者 baseline/member count，并由 runtime installer
安装 descriptor。手写语义通过 `yatou_core::dispatch_surface_with_l1` 写入 L1 ledger。
