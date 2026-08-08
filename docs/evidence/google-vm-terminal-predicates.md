# Google VM 终态谓词

`undefined` 不是统一的失败信号。JavaScript setter 和多数事件/存储/导航方法本来就
返回 `undefined`；页面初始化前读取一个稍后创建的 global 也不能证明初始化失败。

对 `debug_step1.html` 这类 Google 搜索 SG_SS challenge，终态门槛是：

1. 页面脚本没有未处理异常；
2. `window.knitsail` 最终为 object；
3. `window.td.ns/rs` 为有效且有序的 timing；
4. `document.cookie` 中生成 `SG_SS=*...`；
5. trace 观察到 `Document.prototype.cookie` SET；
6. trace 观察到 `Location.prototype.replace` CALL。

`window.sgs` 不是固定门槛。目标页面源码的选择条件是：

```js
window.sgs && ussv && sp ? window.sgs(sp) : Promise.resolve(false)
```

当页面提供 `ussv=''`、`sp=''` 时，该分支按输入必然关闭，随后执行
`Z.then(function(a){a||la()})`。`la()` 经 `g='knitsail'`、`C[g]` 使用 VM
创建的 knitsail generator，最终设置 Cookie 并导航。

验收命令：

```powershell
py -3.13 tools\google-vm-acceptance\runner.py `
  --html C:\path\to\debug_step1.html `
  --url "https://www.google.com.hk/search?q=kiss+site:imdb.com" `
  --output .yatou\evidence\google-vm-execution\acceptance.json
```

输出保留源码 SHA-256、逐 eval precise coverage、终态谓词与 trace 索引，但不保存
完整 SG_SS Cookie，只保存长度、前缀和 SHA-256。
