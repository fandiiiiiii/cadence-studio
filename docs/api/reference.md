# HTTP API 参考

本地基址：`http://127.0.0.1:8765/api`。默认只允许本机访问；错误统一为：

```json
{
  "detail": {
    "message": "人类可读错误",
    "code": "machine_code"
  }
}
```

交互式文档：`/api/docs`。

## 系统

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康、版本、数据目录、ffmpeg 状态 |
| GET | `/api/info` | 产品名与版本（非 `/api` 下为 `/api/info`） |
| GET | `/api/system/overview` | 统计、缓存端点状态、最近批次/事件 |
| POST | `/api/system/backup` | 复制 SQLite 到 `data/backups/` |
| GET | `/api/modules` | 15 个模块与默认值 |
| GET | `/api/hardware-profiles` | T4–H200 的并发/音频上限/参考价预设 |
| GET | `/api/workspace` | 工作区名称、负责人、每日目标 |
| PATCH | `/api/workspace` | 快速修改 `daily_goal`（1–10000） |
| GET | `/api/taxonomy` | 完整 641 标签 payload；`seq` 为 1-based 展示序号，`id` 为稳定机器 ID |
| GET | `/api/taxonomy?category=Genre&q=jazz` | 过滤 |
| GET | `/api/taxonomy/meta` | 版本、类别、结构词表、规则数 |
| GET | `/api/activity?limit=100` | 最近事件 |
| GET | `/api/events?since_id=0` | 历史事件 |
| GET | `/api/events/stream` | SSE；可带 `since_id` |

## 设置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/settings` | 配置 + 密钥“已配置”状态（不含明文） |
| PUT | `/api/settings` | `{config, secrets}`；空 secret 表示删除 |
| GET | `/api/settings/prompt-metrics?modules=caption,genre` | 目录字符/token 估算；genre 自动含 Extra |
| POST | `/api/settings/test/hf` | `whoami` 验证 HF token |
| POST | `/api/settings/test/llm` | `{route_id}` 测试文字模型 |

## 推理端点

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/inference/status?route_id=moss` | 状态（HF 或直连 health） |
| POST | `/api/inference/{route_id}/resume` | HF resume |
| POST | `/api/inference/{route_id}/pause` | HF pause |
| POST | `/api/inference/{route_id}/scale-to-zero` | 需端点开启 scaleToZeroTimeout |
| POST | `/api/inference/{route_id}/test` | 健康检查 |
| GET | `/api/inference/hf/endpoints?namespace=...` | 列出 HF 端点 |

## 批次

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/batches?query=&status=&limit=50` | 批次列表（含计数/进度） |
| POST | `/api/batches` | multipart：`files`, `name`, `note`, `spec`, `auto_start` |
| GET | `/api/batches/{id}` | 批次详情 + 最近事件 + prompt metrics |
| PATCH | `/api/batches/{id}` | `{name?, note?}` |
| DELETE | `/api/batches/{id}` | 删除记录与音频；运行中拒绝 |
| GET | `/api/batches/{id}/items?query=&status=&limit=200&offset=0&sort=position` | 项目列表（不含大字段） |
| GET | `/api/batches/{id}/events` | 批次事件 |
| POST | `/api/batches/{id}/start` | 加入队列 |
| POST | `/api/batches/{id}/pause` | 暂停未开始项 |
| POST | `/api/batches/{id}/resume` | 继续 |
| POST | `/api/batches/{id}/cancel` | 取消排队项 |
| POST | `/api/batches/{id}/retry-failed` | 重试失败项 |
| GET | `/api/batches/{id}/export?format=xlsx` | 下载；`xlsx/json/md/csv/zip` |

### 创建批次示例

```bash
curl -X POST http://127.0.0.1:8765/api/batches \
  -F "files=@song1.mp3" \
  -F "files=@song2.mp3" \
  -F 'spec={"modules":["caption","genre","mood","bpm_key"],"language":"zh","caption_length":"medium","taxonomy_mode":"strict"}' \
  -F "name=第一批" \
  -F "auto_start=true"
```

> `genre` 自动包含 `Extra`。结果中每个曲风见 `items[].level`、`items[].path`、`items[].hierarchy`；一首歌可以有多个 `items`。

返回：

```json
{
  "batch": {"id": "bat_...", "status": "queued", "counts": {"total": 2}},
  "warnings": [],
  "imported": 2
}
```

无效文件会被跳过并返回 warnings；如果全部无效，返回 400。

## 项目

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/items/{id}` | 完整详情（raw/llm_raw/normalized/timings） |
| PATCH | `/api/items/{id}` | `review_status`, `review_note`, `normalized` |
| GET | `/api/items/{id}/audio` | 音频流；支持 Range |
| GET | `/api/items/{id}/export?format=json` | 单曲 JSON/MD |
| POST | `/api/items/{id}/retry` | `{normalize_only: false}` |

`PATCH normalized` 会重新走 `Normalizer` 校验；非法 ID/数值会被修正或丢弃。

## 演示

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/demo/seed` | 创建幂等的演示批次 |

## 状态码

| 状态 | 场景 |
| --- | --- |
| 200 | 成功 |
| 400 | 参数/配置/导出错误 |
| 404 | 批次/项目不存在 |
| 409 | 批次状态不允许（如已完成仍 start） |
| 413 | 音频超过端点/上传限制（模型容器） |
| 422 | 请求体校验失败 |
| 500 | 未预期错误 |
| 503 | 模型容器未 ready |

## SSE

```text
GET /api/events/stream?since_id=123
Content-Type: text/event-stream

id: 124
data: {"id":124,"kind":"item_completed","message":"...","batch_id":"bat_..."}
```

前端用 `EventSource` 自动重连；`id` 用于续传。事件表可能被清理，不要把它当永久审计日志。
