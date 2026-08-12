# CPython 3.10–3.14 跨平台 wheel

## 发布矩阵

`tools/build/wheel_matrix.json` 是原生发布面的唯一清单。它固定 8 个目标、5 个
CPython ABI，共 40 个 wheel：

| 目标 ID | Rust target | wheel platform | 构建方式 |
| --- | --- | --- | --- |
| `windows-x86_64` | `x86_64-pc-windows-msvc` | `win_amd64` | Windows x64 原生 |
| `windows-arm64` | `aarch64-pc-windows-msvc` | `win_arm64` | Windows x64 → ARM64 交叉 |
| `macos-x86_64` | `x86_64-apple-darwin` | `macosx_11_0_x86_64` | Intel macOS 原生 |
| `macos-arm64` | `aarch64-apple-darwin` | `macosx_11_0_arm64` | Apple Silicon 原生 |
| `manylinux-x86_64` | `x86_64-unknown-linux-gnu` | `manylinux_2_28_x86_64` | manylinux 容器原生 |
| `manylinux-aarch64` | `aarch64-unknown-linux-gnu` | `manylinux_2_28_aarch64` | glibc x64 → ARM64 交叉 |
| `musllinux-x86_64` | `x86_64-unknown-linux-musl` | `musllinux_1_2_x86_64` | glibc x64 → musl x64 交叉 |
| `musllinux-aarch64` | `aarch64-unknown-linux-musl` | `musllinux_1_2_aarch64` | glibc x64 → musl ARM64 交叉 |

每个目标都构建 `cp310-cp310`、`cp311-cp311`、`cp312-cp312`、
`cp313-cp313`、`cp314-cp314`。项目目前不使用 `abi3`，因此 40 个 ABI/平台产物
不能合并成一个“万能 wheel”。PyPI 会按操作系统、CPU、libc 和 Python ABI 自动
选择匹配文件，用户侧仍然只需：

```console
python -m pip install yatouv8
```

## 浏览器基线与原生平台是两件事

这次扩展的是 V8 host 原生二进制的可安装平台，不是伪造八套浏览器指纹。
`yatouv8` 的行为 oracle 仍是 **Windows 11 + Chrome 150**。macOS/Linux wheel
默认继续装载该经过 conformance 验证的 profile。只有采集到对应 Chrome snapshot、
完成 snapshot diff 并通过语义门禁后，才新增 macOS/Linux 浏览器 profile；构建成功
本身不能证明新 profile 正确。

## 为什么交叉构建仍需 x64 glibc 宿主

V8 源码构建包含 GN、Torque、`mksnapshot` 和代码生成器。这些工具必须能在构建机
执行，最终静态库才按目标 ABI 编译。因此：

- Windows ARM64 在 `windows-2022` x64 上用 VS 2022 MSVC ARM64 工具链构建，再到
  `windows-11-arm` 原生运行；
- Linux ARM64 和两个 musl 目标在 glibc x64 容器中构建宿主工具；
- `RUSTY_V8_MUSL_SYSROOT` 只约束最终 musl 对象，不把宿主生成器变成 musl；
- macOS 使用对应架构 runner，避免 Rosetta/SDK 混用污染部署目标。

V8 一律固定 `v8 = 150.4.0`。Linux/macOS 使用 `V8_FROM_SOURCE=1`，
`prepare_v8_source.py` 校验并水合固定 ICU 与 Chromium Rust vendor 输入；其
`libclang` 只供 bindgen，V8 C++ 编译继续使用 rusty_v8 固定 revision 的 Chromium
clang。Windows 使用 rusty_v8 同版本官方 release 静态库与绑定文件，并通过
`tools/build/rusty_v8_windows_assets.json` 固定 URL 和 SHA-256；这避免 GitHub
Windows runner 单次源码编译超过 4 小时，同时不改变 V8 版本或 Rust API。

## 本地入口

### Windows

```powershell
# x64，默认安装后运行测试
.\scripts\build-wheel.ps1 `
  -TargetId windows-x86_64 `
  -PythonExecutable "D:\language\python-3.10.1\python.exe"

# ARM64 交叉构建；运行测试由 ARM64 机器执行
.\scripts\build-wheel.ps1 `
  -TargetId windows-arm64 `
  -PythonExecutable "D:\language\python-3.10.1\python.exe"
```

Windows 脚本会通过 `VsDevCmd.bat` 分别加载 `amd64` 或 `arm64` MSVC 环境，并
使用固定 GN、Ninja 和 Chromium libclang。Chromium GN 的 Rust sysroot 输入路径很
长，脚本默认把 Cargo/V8 输出放在短路径 `C:\y8t`，避免尚未归一化的 `..` 路径触发
Win32 260 字符限制；如需改盘符，可预先设置另一个足够短的 `CARGO_TARGET_DIR`。

CI 和批量发布使用 `scripts/build-wheels-windows.ps1`，为一个目标架构接收五个 x64
构建解释器。脚本先校验并准备一次目标 V8 静态资产，再复用相同 Cargo target tree
依次链接 `cp310`–`cp314`，防止把与 Python ABI 无关的工作重复执行五次。

### macOS

在对应架构 Mac 上安装 Xcode Command Line Tools、Homebrew `llvm@19`、Rust 1.97.1、
Maturin 1.14.1 和五个 CPython 后执行：

```bash
bash scripts/build-wheel-macos.sh macos-arm64 dist
# Intel Mac 使用 macos-x86_64
```

最低部署版本固定为 macOS 11.0。

### Linux

脚本应在矩阵指定的构建容器中运行：

```bash
bash scripts/build-wheel-linux.sh manylinux-x86_64 dist
bash scripts/build-wheel-linux.sh manylinux-aarch64 dist
bash scripts/build-wheel-linux.sh musllinux-x86_64 dist
bash scripts/build-wheel-linux.sh musllinux-aarch64 dist
```

交叉构建不执行目标 Python。Maturin 1.14 使用 `python3.10`–`python3.14` 这些
符号名从内置 target sysconfig 生成五个 ABI wheel。产物随后必须进入矩阵固定的
原生 manylinux/musllinux 容器运行 `scripts/test-wheel-linux.sh`。

## CI 拓扑

`.github/workflows/ci.yml` 先由 `wheel-matrix` job 生成动态矩阵，再执行：

1. `contracts`：Rust/Python 静态合同与单元测试；
2. `windows-v8-wheel`：两个架构任务各校验一次 V8 资产，并分别生成五个 CPython ABI wheel；
3. `windows-wheel-install`：在 x64/ARM64 原生 runner 安装和运行；
4. `macos-v8-wheels`：两个架构各一次构建五个 ABI，并原生测试；
5. `linux-v8-wheels`：四个 libc/架构构建；
6. `linux-wheel-install`：20 个 libc/架构/ABI 原生容器测试。

Linux 构建与测试镜像均以 SHA-256 digest 固定。Maturin Action 同时固定 commit 与
Maturin 版本，防止 `latest` 静默改变产物。

## 验收边界

“开发完成”表示矩阵、工具链准备、构建、产物审计和原生测试流水线均已实现；
“平台验收通过”必须有对应 runner 的真实产物与运行证据。每个 wheel 的硬门槛是：

1. tag 与矩阵精确匹配；
2. 包含 `_native`、`LICENSE`、`NOTICE`；
3. 在无编译器环境安装；
4. 运行全部 `python/tests`；
5. `v8_smoke_value() == "42"`；
6. `Runtime().eval("21 * 2") == 42`；
7. 记录 SHA-256；
8. 解析 PE/ELF/Mach-O 头，确保 `_native` 与所有 bundled native library 都与
   wheel 目标架构一致；Windows 的 zlib 仅在构建解释器产生真实依赖时由 repair
   步骤打包，不把“必须存在 zlib.dll”误当成平台门槛。

在上述原生流水线实际产生绿色证据前，不能把 Windows 本机的静态检查写成 macOS、
ARM64 或 musl 的验收结论。
