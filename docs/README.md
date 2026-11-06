# 文档地图

| 文档 | 读者 | 内容 |
| --- | --- | --- |
| [产品字段契约](product/annotation-schema.md) | 产品、数据、工程 | 15 模块、结果 JSON、标签治理、状态、导出 |
| [行业标注任务全景](product/industry-taxonomy.md) | 产品、运营、客户 | 25 类任务族、平台/标准证据、覆盖边界 |
| [用户操作指南](product/user-guide.md) | 标注员、运营 | 首次使用、批次、审听、导出、快捷键 |
| [Windows 快速开始](operations/quickstart.md) | 所有人 | 双击启动、配置、第一首、500 首 |
| [Hugging Face 部署](operations/huggingface-setup.md) | 运维、工程 | 自定义容器、A10G、Token、生命周期 |
| [硬件预设与并发](operations/hardware-presets.md) | 运维 | T4–H200 的并发、音频上限、参考价 |
| [DeepSeek 配置](operations/deepseek-setup.md) | 工程 | API Key、模型、错误处理 |
| [故障排查](operations/troubleshooting.md) | 运维 | 启动、端点、队列、数据 |
| [系统架构](architecture/system.md) | 工程 | 组件、流程、并发、安全、扩展 |
| [数据模型](architecture/data-model.md) | 工程 | SQLite 表、状态、文件布局、迁移 |
| [架构决策](architecture/adr/) | 工程 | 本地优先、自定义容器、标签治理、生命周期 |
| [API 参考](api/reference.md) | 集成方 | 端点、错误码、SSE、示例 |
| [基准与容量](quality/benchmark.md) | 产品、运维 | 验收、500 首算术、真实测试记录 |
| [标签原文](product/taxonomy-reference.md) | 标注、产品 | 737 标签定义与规则来源 |

## 阅读顺序

**第一次使用**：README → 快速开始 → 用户指南 → HF 部署。

**接手维护**：README → 字段契约 → 系统架构 → 数据模型 → AGENTS/CONTRIBUTING。

**评估可行性**：行业全景 → 字段契约 → 基准计划 → HF 部署的限制章节。

## 文档原则

- 区分“已实现”“已模拟验证”“已在真实模型/GPU 验证”。
- 不把公开模型卡或供应商宣传当成项目实测。
- 每个限制都写清触发条件与替代方案。
- 变更 schema、状态或导出契约时，同步更新文档与测试。
