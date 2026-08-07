# ADR 0005：Evidence → Manifest → Codegen

- 状态：Accepted
- 日期：2026-08-07
- 决策来源：Q8、Q19、Q23、Q28、Q39、Q56

## 背景

手写 constructor、prototype 和 descriptor 容易产生重复代码、属性顺序漂移和不可追踪差异。

## 决策

Chrome snapshot 经验证后转换为 Surface Manifest。Manifest 记录接口、继承、成员位置、descriptor、签名、brand check、HandlerId 和 evidence refs。生成器输出 V8 templates、安装顺序、共享 trampoline glue 和 golden tests。

生成器不猜测业务语义。DOM、CSSOM、Clock、Resource 等行为由手写 Rust handler 实现。

## 结果

生成文件提交到 Git，CI 重新生成后工作树必须无差异。参考源码不直接 vendored；版本和用途记录在 `docs/references.yaml`。
