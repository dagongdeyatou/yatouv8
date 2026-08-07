# M9 当前公开 loader corpus

M9 于 2026-08-07 从两个官方公开入口采集：

- `https://www.google.com/recaptcha/api.js?render=explicit`
- `https://www.recaptcha.net/recaptcha/api.js?render=explicit`

两者解析到同一 release `w_Yb7dGGXaKesJ7BMiqFJqBG`；对应 gstatic 第二阶段
SHA-256 为 `6dba4114e36a52e724a9c2be4732b94d1973ef2ef91f0f71774b9e28f83f364f`。

Chrome 侧阻断第二阶段网络，只观察 loader 的确定性状态；yatouv8 执行同源 probe。
两个镜像的 canonical 结果分别完全一致。首轮 blocker 是当前 loader 新使用的
`document.head.prepend`，补齐 ParentNode 语义后收敛。篡改插入脚本 URL 的负对照
被拒绝。

完成声明严格限定为**当前公开 loader**。第二阶段已采集并内容寻址，但当前在线
challenge 和私有 BotGuard bytecode 未声明通过。

重现：`scripts/run-m9.ps1`。
