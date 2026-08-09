# Linux wheel 构建

Linux 发布面现包括：

- `manylinux_2_28_x86_64`；
- `manylinux_2_28_aarch64`；
- `musllinux_1_2_x86_64`；
- `musllinux_1_2_aarch64`；
- 每个平台的 CPython 3.10–3.14 五个 ABI wheel。

完整矩阵、容器摘要、构建入口、宿主/目标边界和验收门槛统一记录在
[CPython 3.10–3.14 跨平台 wheel](building-cross-platform.md)。

Linux 构建环境由 `scripts/prepare-linux.sh` 准备。原来的
`scripts/prepare-manylinux.sh` 保留为 `manylinux-x86_64` 兼容入口。四个构建目标
统一由以下命令选择：

```bash
bash scripts/build-wheel-linux.sh TARGET_ID dist
```

交叉目标的产物不可在 x64 glibc 构建容器中冒充运行成功；必须在矩阵规定的原生
policy 容器中执行：

```bash
bash scripts/test-wheel-linux.sh TARGET_ID PYTHON_VERSION dist
```
