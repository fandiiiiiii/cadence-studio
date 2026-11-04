# DeepSeek / 文字模型配置

规范化阶段只接收**文字观察**与曲目元数据，不接收音频文件。默认使用 DeepSeek 的 OpenAI-compatible Chat Completions。

## 1. 获取 API Key

1. 登录 [DeepSeek 开放平台](https://platform.deepseek.com/)。
2. 创建 API Key，保存在安全位置。
3. 确认账户有可用余额。

> 不要把 Key 写进代码、`.env` 提交、截图或聊天。Cadence 会把 Key 用 Windows DPAPI 加密保存在本机 `data/secrets.bin`，HTTP API 不返回明文。

## 2. 在 Cadence 中填写

**设置 → 文字模型**：

| 字段 | 值 |
| --- | --- |
| 显示名称 | `DeepSeek Chat` |
| 模型名 | `deepseek-chat` |
| BASE URL | `https://api.deepseek.com/v1` |
| API KEY | `sk-...` |
| TEMPERATURE | `0.1` |
| MAX TOKENS | `4096` |
| JSON MODE | 开启（默认） |

点 **测试**。测试只发送 `ping`，不包含标签目录或音频。

## 3. 模型选择

### `deepseek-chat`

推荐默认。支持 JSON output；延迟低，适合逐首规范化。

### `deepseek-reasoner`

会先返回推理内容。Cadence 只接受 `message.content` 中的最终 JSON；如果模型只给 `reasoning_content`，请求会失败并提示。除非你确认当前 API 行为，否则不要作为默认模型。

### 其他 OpenAI-compatible

可以接：

- 本地 Ollama：`http://127.0.0.1:11434/v1`，模型如 `qwen2.5:14b`；
- 其他云厂商的 `/v1/chat/completions`。

要求：

1. `POST {base_url}/chat/completions`；
2. 返回 `choices[0].message.content`；
3. 支持 JSON 模式；如果不支持，Cadence 会自动重试一次不带 `response_format` 的请求；
4. 模型上下文至少能容纳目录 + 原始观察 + 输出（通常 20k–40k tokens）。

## 4. 目录与成本

规范化提示只包含**选中模块**的标签。全选 641 个标签时，目录约 20k 字符，加上规则与原始观察，通常 9k–13k tokens；只选 Caption 时不注入目录。

降低成本：

- 只勾选需要的模块；
- Caption 优先，不要默认全选；
- 同一批次内标签体系不变，DeepSeek 可能命中上下文缓存（是否计费折扣以平台为准）；
- 失败时优先“重新规范化”，复用音频模型原文，避免再次跑 GPU。

## 5. 错误处理

| 错误 | 处理 |
| --- | --- |
| 401 / 403 | Key 无效或无权限 |
| 400 `response_format` | 系统会自动去掉 JSON 模式重试；检查模型是否支持 JSON |
| 429 | 限流；系统退避重试，仍失败则稍后再试 |
| 500 | 服务端错误；已重试，查看活动流 |
| JSON 不完整 | 系统会带错误原因修复一次；仍失败则保留原始观察并标记失败 |
| 输出缺少模块 | 会修复一次；仍缺失则完成但带 warnings，需人工查看 |
| 只返回 reasoning | 换 `deepseek-chat`，或调整模型 |

## 6. 安全

- 工作台只把文字发送到你配置的地址；不会把音频发给文字模型。
- 如果使用第三方中转，请自行确认其日志、保留和训练政策。
- 生产环境建议给文字模型单独设预算/限额；Cadence 不包含自动账单上限。
