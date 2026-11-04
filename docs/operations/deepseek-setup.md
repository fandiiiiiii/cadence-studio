# DeepSeek / 文字模型配置

规范化阶段只接收**文字观察**与曲目元数据，不接收音频文件。默认使用 DeepSeek 的 OpenAI-compatible Chat Completions。

> 模型名由请求里的 `model` 字段决定，**不是由 API Key 决定**。同一个 Key 可以调用当前开放的不同模型。

## 1. 当前 DeepSeek 模型名（2026-11-05）

官方文档当前列出：

| 模型名 | 说明 |
| --- | --- |
| `deepseek-flash` | 默认推荐；由 DeepSeek-V4.1-Flash-1017 提供服务；支持 JSON output |
| `deepseek-v4-pro` | 更高能力/更高价格；支持 JSON output |

`deepseek-chat`、`deepseek-reasoner` 是**旧文档里的名字**，不在当前官方模型表中。不要把它们作为默认值；旧配置在 Cadence 启动时会自动迁移到 `deepseek-flash`。

来源：[Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing)、[Your First API Call](https://api-docs.deepseek.com/)、[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode)。

## 2. 在 Cadence 中填写

**设置 → 文字模型**：

| 字段 | 值 |
| --- | --- |
| 显示名称 | `DeepSeek Flash` |
| 模型名 | `deepseek-flash` |
| BASE URL | `https://api.deepseek.com` |
| API KEY | 你的 `sk-...` |
| 思考模式 | **关闭（推荐）** |
| TEMPERATURE | `0.1` |
| MAX TOKENS | `4096` |
| JSON MODE | 开启（默认） |

点 **测试**。测试只发送 `ping`，不包含标签目录或音频。

## 3. 思考模式

DeepSeek V4 默认开启 thinking。对于逐首规范化，这会增加延迟和输出 token；Cadence 默认发送：

```json
{"thinking": {"type": "disabled"}}
```

只有 Base URL 包含 `deepseek.com` 时才发送该字段，避免其他 OpenAI-compatible 服务因未知参数报错。若你确实需要更强推理，可在设置里改为“开启”，但要接受延迟与成本。

## 4. 模型选择

### `deepseek-flash`

推荐默认。支持 1M 上下文、JSON output，速度快，适合逐首标签映射。

### `deepseek-v4-pro`

更强、更贵。适合疑难标签映射或高价值批次；先用同一批 20 首做 A/B，再决定是否值得。

### 其他 OpenAI-compatible

可以接：

- 本地 Ollama：`http://127.0.0.1:11434/v1`，模型如 `qwen2.5:14b`；
- 其他云厂商的 `/v1/chat/completions`。

要求：

1. `POST {base_url}/chat/completions`；
2. 返回 `choices[0].message.content`；
3. 支持 JSON 模式；如果不支持，Cadence 会自动重试一次不带 `response_format` 的请求；
4. 模型上下文至少能容纳目录 + 原始观察 + 输出（通常 20k–40k tokens）。

## 5. 目录与成本

规范化提示只包含**选中模块**的标签。全选 641 个标签时，目录约 20k 字符，加上规则与原始观察，通常 9k–13k tokens；只选 Caption 时不注入目录。

降低成本：

- 只勾选需要的模块；
- Caption 优先，不要默认全选；
- 同一批次内标签体系不变，DeepSeek 可能命中上下文缓存（是否计费折扣以平台为准）；
- 失败时优先“重新规范化”，复用音频模型原文，避免再次跑 GPU；
- 保持思考模式关闭。

## 6. 错误处理

| 错误 | 处理 |
| --- | --- |
| 401 / 403 | Key 无效或无权限 |
| 400 `model` | 当前模型名不是 `deepseek-flash` / `deepseek-v4-pro`；检查设置 |
| 400 `response_format` | 系统会自动去掉 JSON 模式重试；检查模型是否支持 JSON |
| 429 | 限流；系统退避重试，仍失败则稍后再试 |
| 500 | 服务端错误；已重试，查看活动流 |
| JSON 不完整 | 系统会带错误原因修复一次；仍失败则保留原始观察并标记失败 |
| 输出缺少模块 | 会修复一次；仍缺失则完成但带 warnings，需人工查看 |
| 只返回 reasoning | 关闭思考模式，或换回 `deepseek-flash` |

## 7. 安全

- 工作台只把文字发送到你配置的地址；不会把音频发给文字模型。
- 如果使用第三方中转，请自行确认其日志、保留和训练政策。
- 生产环境建议给文字模型单独设预算/限额；Cadence 不包含自动账单上限。
