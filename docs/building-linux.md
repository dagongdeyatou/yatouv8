# Linux x86_64 wheel 构建

## 目标

Linux 第一阶段只承诺：

- `x86_64-unknown-linux-gnu`；
- `manylinux_2_28_x86_64`；
- CPython 3.10、3.11、3.12、3.13、3.14；
- `v8 = 150.4.0` 且 `V8_FROM_SOURCE=1`；
- wheel 安装后运行全部 `python/tests` 和 native V8 smoke。

这不是纯 Python wheel。每个 Python ABI、操作系统和 CPU 架构都必须有独立的
原生 wheel；`pip install yatouv8` 只有在 PyPI 上存在与当前环境匹配的产物时才会
直接安装。

## 固定输入

CI 使用：

- Rust `1.97.1`；
- maturin `1.14.1`；
- `manylinux_2_28_x86_64` 镜像摘要
  `sha256:443eabd378e140996780a772e12c1a1ef10551da933fe76d74a1bab61f68a7b7`；
- PyO3/maturin-action commit
  `86b9d133d34bc1b40018696f782949dac11bd380`；
- ICU 数据 SHA-256
  `1cf67874b5a87a8363a86fb3f81e3cbbed54d389062dab8fb52308d5cf8c8612`；
- Chromium Rust vendor archive SHA-256
  `23326dc97cc82b2e0b551f823c8afb0a91524abcfe078c50d38dbdf37fe0eb92`。

`tools/build/prepare_v8_source.py` 是 Windows/Linux/macOS 共用的依赖水合入口。
它先执行 `cargo fetch --locked`，再定位精确的 `v8-150.4.0` crate，并拒绝校验失败
或包含路径穿越/链接条目的 archive。

## 构建入口

GitHub Actions 的 `linux-v8-wheels` job 在固定 manylinux 容器中执行：

1. source `scripts/prepare-manylinux.sh`；
2. 安装 glib2 和 clang 19+ 开发文件；
3. 水合固定 V8 source inputs；
4. 一次 maturin 调用构建五个 CPython ABI wheel；
5. 校验 wheel tag、native module、LICENSE、NOTICE 和 SHA-256；
6. `linux-wheel-install` 在五个独立 CPython runner 上无编译器安装并运行测试。

已有 Rust 1.97.1、maturin 1.14.1 和 `/opt/python/cp3*-cp3*` 的
`manylinux_2_28_x86_64` 容器，也可以直接运行：

```bash
bash scripts/build-wheel-linux.sh dist
```

`scripts/prepare-manylinux.sh` 必须由调用者 `source`，因为它导出的
`V8_FROM_SOURCE` 和 `LIBCLANG_PATH` 必须传递给 maturin。V8 编译器不复用系统
clang，而由 `v8-150.4.0` 内固定 revision 的 Chromium 下载脚本准备；系统
clang 19+ 只向 bindgen 提供 `libclang`。

## 准入与当前边界

Linux 支持只有在 CI 实际生成五个 wheel，并且五个安装测试 job 全部通过后才可
标记为已验收。本机 Windows 上的交叉 `cargo check` 只能证明 Linux `cfg` Rust
代码可编译，不能替代 manylinux 链接、auditwheel 和运行时测试。

后续阶段依次为 Linux aarch64、macOS arm64/x86_64、musllinux；每一阶段都沿用
相同的“构建产物 → 独立安装 → native smoke → Python tests → hash”门禁。
