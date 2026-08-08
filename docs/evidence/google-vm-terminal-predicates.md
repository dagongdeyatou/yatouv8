# Google VM 终态谓词

`undefined` 不是统一的失败信号。JavaScript setter 和多数事件/存储/导航方法本来就
返回 `undefined`；页面初始化前读取一个稍后创建的 global 也不能证明初始化失败。

对 `debug_step1.html` 这类 Google 搜索 SG_SS challenge，终态门槛是：

1. 页面脚本没有未处理异常；
2. `window.knitsail` 最终为 object；
3. `window.td.ns/rs` 为有效且有序的 timing；
4. `document.cookie` 中生成 `SG_SS=*...`；
5. trace 观察到 `Document.prototype.cookie` SET；
6. trace 观察到 `Location.prototype.replace` CALL；
7. Runtime 导出一个带 domain/path 属性的结构化 `SG_SS` Cookie，可交给 HTTP session；
8. Runtime 暴露 `kind=replace`、同入口 URL 且包含 `sei` 的 pending navigation。

`window.sgs` 不是固定门槛。目标页面源码的选择条件是：

```js
window.sgs && ussv && sp ? window.sgs(sp) : Promise.resolve(false)
```

当页面提供 `ussv=''`、`sp=''` 时，该分支按输入必然关闭，随后执行
`Z.then(function(a){a||la()})`。`la()` 经 `g='knitsail'`、`C[g]` 使用 VM
创建的 knitsail generator，最终设置 Cookie 并导航。

## 当前快照的已接纳基线

对 SHA-256 为
`d080ae7f8cd96f3835694af5856e96568388ac11aeaa4403f645276bc7950d3a`
的 `debug_step1.html`，`545` 个 L1 events 是完整成功路径，不是提前退出：

| 证据 | 结果 |
| --- | --- |
| `window.sgs` | `undefined`，与空 `sp/ussv` gate 一致 |
| `window.knitsail` | `object` |
| `window.td` | `ns/rs` 有效且有序 |
| Cookie SET | event `534` |
| `location.replace` | event `536` |
| HTTP handoff | 结构化 `SG_SS` + 带 `sei` 的 pending navigation |

因此不应通过伪造 `window.sgs` 或增加无意义事件数来制造“进展”。缺失第 4 个 bootstrap
脚本的负对照只有 `92` 个 L1 events，并且不会生成 timing、Cookie 或 navigation。

验收命令：

```powershell
py -3.13 tools\google-vm-acceptance\runner.py `
  --html C:\path\to\debug_step1.html `
  --url "https://www.google.com.hk/search?q=kiss+site:imdb.com" `
  --output .yatou\evidence\google-vm-execution\acceptance.json
```

输出保留源码 SHA-256、逐 eval precise coverage、终态谓词、trace 索引、脱敏 Cookie
handoff 记录与 pending navigation。不会保存完整 SG_SS Cookie，只保存长度、首字符和
SHA-256。
