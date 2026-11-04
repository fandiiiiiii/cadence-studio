# 用户操作指南

## 1. 首次打开

双击仓库根目录的 **`启动 Cadence.cmd`**。首次启动会：

1. 创建 `.venv`；
2. 安装 `requirements.txt`；
3. 启动本地服务；
4. 自动打开浏览器（通常是 `http://127.0.0.1:8765/`）。

关闭终端窗口即停止工作台。数据保存在 `data/`：

```text
data/
  cadence.db          批次、项目、事件、用量
  config.json         非敏感设置
  secrets.bin         DPAPI 加密的 API Key
  audio/{batch_id}/   原始音频、转码副本
  exports/{batch_id}/ 导出文件
  logs/
  backups/
```

> 没有配置端点时，可以先点 **载入演示批次**。四首音频是本地生成的原创合成片段；标注结果带有 `DEMO` 标记，仅用于熟悉界面，不是模型真实输出。

## 2. 配置连接

### 2.1 Hugging Face 推理端点

进入 **设置 → 推理端点**。

| 字段 | 填写 |
| --- | --- |
| HF TOKEN | Fine-grained token；需要 Inference Endpoints 的读取/管理权限 |
| 显示名称 | 例如 `MOSS Music 8B` |
| 模型仓库 | `OpenMOSS-Team/MOSS-Music-8B-Instruct` 或 `nvidia/music-flamingo-2601-hf` |
| 适配器 | 自定义容器用 `Cadence custom /v1/annotate`；vLLM/OpenAI 兼容音频用 `OpenAI-compatible audio` |
| 最大并发 | A10G 保持 `1` |
| HF NAMESPACE | 你的 Hugging Face 用户名或组织 |
| HF ENDPOINT NAME | 控制台里的端点名称，例如 `moss-music-a10g` |
| INFERENCE URL | 可留空；保存后由 HF API 解析。若使用非 HF 服务，填完整 URL |
| 标注路径 | 默认 `/v1/annotate` |
| 健康检查 | 默认 `/health` |
| 超时 | 900 秒；冷启动较慢时保留足够时间 |

点 **验证令牌** 和 **测试**。顶部和左下角的端点状态会显示 `运行中 / 已暂停 / 未配置 / 失败`。

> 自动 Resume/Pause 需要 `HF NAMESPACE + HF ENDPOINT NAME + HF TOKEN`。只填 URL 的直连模式无法管理生命周期，系统不会假装调用云端暂停。

### 2.2 DeepSeek / 文字模型

进入 **设置 → 文字模型**。

| 字段 | 建议 |
| --- | --- |
| BASE URL | `https://api.deepseek.com/v1` |
| 模型名 | `deepseek-chat`（JSON 模式稳定；`deepseek-reasoner` 需确认最终 JSON 在 content 中返回） |
| API KEY | `sk-...`；保存后不再显示明文 |
| TEMPERATURE | `0.1` |
| MAX TOKENS | `4096` |

点 **测试**。系统会发一个最小 JSON 请求，不包含音频。

### 2.3 费用守卫

**设置 → 推理端点 → 费用守卫**：

- `自动恢复端点`：批次开始时，如果端点 paused/scaledToZero，自动 resume 并轮询健康检查。
- `空闲自动暂停`：最后一个任务结束、经过宽限期后 pause。默认 120 秒。
- 宽限期设 `0` 表示队列一空就请求暂停；冷启动频繁时建议保留 60–300 秒。

## 3. 新建批次

1. 点右上角 **新建标注批次**，或按 `N`。
2. 拖入音频（MP3 / WAV / FLAC / M4A / OGG 等），或点击选择。
3. 填批次名称与备注。系统默认用日期 + 文件数命名。
4. 勾选需要的模块。**只勾选真正需要的字段**：
   - 只要 Caption：只选 `描述 Caption`；
   - 曲库上架：Caption + Genre + Mood + BPM/Key + Instruments + Language + Vocal；
   - 剪辑/卡点：Caption + Structure + BPM/Key + Scene；
   - 合规：Safety + Lyrics + Language；
   - 自定义：勾选“自定义要求”，填写额外提示词与字段。
5. 选择输出语言、Caption 长度、标签策略。
6. 看底部估算条：目录标签数与规范化上下文 tokens。选择模块越多，规范化调用越慢/越贵。
7. 勾选/取消 **创建后立即开始**。

### 上传规则

- 单批最多 1000 个（可在设置中调整）。
- 单文件默认上限 512MB。
- 服务端读取音频时长；短于 2 秒或无法解码的文件会跳过，并在创建结果中返回 warning。
- 同一批中 SHA-256 相同的文件会跳过。
- 原文件保留；上传副本会转码为 44.1kHz / 双声道 / 96kbps MP3，以减少传输和冷启动时间。
- 音频模型上限默认 1200 秒（20 分钟）。

## 4. 批次页面

### 进度与状态

顶部进度卡显示：

- 完成 / 失败 / 排队 / 处理中数量；
- 横向进度条（完成、失败、运行中三段）；
- 当前绑定的音频模型与规范化模型；
- 批次状态。

每个项目有独立阶段：

```text
queued → preprocessing → inferencing → normalizing → saving → completed
                                                     ↘ failed
```

- `queued`：排队，等待并发槽位；
- `preprocessing`：读取/转码/校验；
- `inferencing`：端点启动、音频模型分析；
- `normalizing`：DeepSeek 规范化与标签校验；
- `saving`：写入结果；
- `failed`：保留错误、原始输出与重试入口。

### 搜索和筛选

- 按文件名、原始输出、错误信息搜索；
- 按状态筛选；
- 按导入顺序、时长、最新导入排序；
- SSE 实时更新，通常 1–2 秒内看到状态变化。

### 批次操作

| 操作 | 行为 |
| --- | --- |
| 暂停 | 正在处理的项目完成；其余暂停 |
| 继续 | 恢复排队 |
| 取消 | 未处理项目取消；已在处理的项目可能完成 |
| 重试失败项 | 重新排队；若已有音频模型原文，只重跑规范化 |
| 更多 → 重命名 | 修改批次名称 |
| 更多 → 删除 | 删除数据库记录、原始音频和结果，不可恢复 |
| 导出 | 打开格式选择器 |

## 5. 单曲审听抽屉

点击表格行打开右侧抽屉。

### 结构化

- Caption
- 主曲风 / 次曲风 / 映射依据
- 情绪标签、效价、能量
- BPM、调性、拍号、律动
- 乐器与声音设计
- 结构时间轴
- 人声、语言、歌词
- 场景、制作、质量、安全
- 人工复核状态

标签上的数字是置信度（0–100）。虚线边框表示发生过近似映射；悬停可看原始说法。

### 原始输出

- **音频模型原始观察**：MOSS / Music Flamingo 返回的完整文本；
- **规范化模型原始输出**：DeepSeek 返回的原始 JSON/文本。

即使规范化失败，原始观察仍会保留，便于人工判断或只重跑规范化。

### 规范化 JSON

最终服务端校验通过的 JSON。可直接复制。

### 标签映射

显示 `原始说法 → 规范 ID / 标准名 / 置信度`，以及 `unmapped` 列表。

### 元数据

Item ID、批次、文件、时长、采样率、声道、SHA-256、模型、尝试次数、耗时、错误码。

### 复核

- **已通过**：`review_status=approved`；
- **需修改**：`review_status=needs_changes`；
- 复核是人工状态，不改变模型结果；
- 可通过 API `PATCH /api/items/{id}` 提交手工修正后的 `normalized` JSON，服务端会重新做标签治理。

### 重试

- **重新规范化**：复用音频模型原文，只重跑 LLM，适合标签映射错误、JSON 不合法、换模型；
- **完整重跑**：重新送音频到端点。

## 6. 标签体系

在 **标签体系** 页面：

- 按大类筛选（曲风 273 / 乐器 136 / 场景 103 / 人声 45 / 情绪 33 / 语言 23 / 补充 28）；
- 搜索中文名、英文名、ID、定义；
- 点击标签查看定义、特征、情绪倾向、别名。

标签版本 `workbench-2026-11-03` 会写入每个结果的 `_meta.taxonomy_version`。修改标签定义时应生成新版本，而不是原地覆盖。

## 7. 导出

批次页 → **导出**：

| 格式 | 内容 |
| --- | --- |
| XLSX | 批次概览、标注总表、原始与规范化、结构时间轴、标签映射 |
| JSON | 完整数据包，含 raw/llm_raw/normalized/timings/error/models |
| Markdown | 可审阅报告，逐曲展开 |
| CSV | 一行一首，UTF-8 BOM |
| ZIP | 以上格式 + taxonomy.json + manifest |

单曲抽屉底部可单独导出 JSON / Markdown。

> 导出目录 `data/exports/{batch_id}/`。ZIP 不默认包含音频；需要交付音频时，单独归档 `data/audio/{batch_id}/`。

## 8. 数据管理

- **定位批次**：侧边栏最近批次、批次页搜索、命令面板（⌘/Ctrl+K）搜索批次名。
- **数据备份**：设置 → 数据与安全 → 备份数据库，写入 `data/backups/`。同时备份 `data/audio/` 与 `data/config.json`。
- **删除批次**：删除前确认没有运行中的项目；删除不可恢复。
- **更换电脑**：复制整个 `data/` 后，密钥因 DPAPI 绑定旧账号/机器而不可读，需要重新输入 API Key。
- **不要**把 `data/` 放进同步盘后让多台机器同时写入 SQLite；如需多人协作，应改为服务端部署与并发控制，而不是共享本地文件夹。

## 9. 快捷键

| 快捷键 | 动作 |
| --- | --- |
| `⌘/Ctrl + K` | 命令面板 |
| `N` | 新建批次 |
| `/` | 命令面板 |
| `Esc` | 关闭弹窗 / 抽屉 / 侧边栏 |
| `↑ / ↓` | 命令面板选择 |
| `Enter` | 打开选中项 |

## 10. 常见问题

| 现象 | 处理 |
| --- | --- |
| 启动后浏览器空白 | 等 2–3 秒；刷新；看终端是否有 Python 报错 |
| 端口被占用 | 启动器自动换端口；也可 `--port 8790` |
| `ffmpeg not found` | 安装 ffmpeg 并加入 PATH；否则音视频探测/转码会降级 |
| 端点显示“未配置” | 填 namespace + endpoint name + token，或完整 URL |
| 端点 503 / 冷启动 | 系统会等待；查看 HF Logs；不要连续点击 Resume |
| 端点 OOM | 降低音频长度/并发，改用更大显存；记录日志后再重试 |
| 标签全是 unmapped | 检查规范化模型输出是否被截断；降低模块数/目录；查看原始 JSON |
| 结果只有 Caption | 这是预期：只勾选了 Caption 模块 |
| API Key 无法解密 | 换回了旧的 Windows 用户/电脑；重新输入 Key |
| 批次卡在 queued | 检查端点配置、并发、是否有失败批次占用；看活动流 |
| 导出失败 | 检查 `data/exports` 权限；看终端 traceback |

更详细的部署与故障处理见 [Hugging Face 端点部署](../operations/huggingface-setup.md)、[故障排查](../operations/troubleshooting.md)。
