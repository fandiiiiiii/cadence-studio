# 数据模型

SQLite 文件：`data/cadence.db`，WAL 模式。所有时间戳为 UTC ISO-8601 字符串。

## 1. 关系

```text
batches 1 ─── n items
batches 1 ─── n events
batches 1 ─── n usage
items   1 ─── n events
items   1 ─── n usage
```

`events` / `usage` 通过可空外键关联，用于跨批次活动流。

## 2. batches

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | `bat_...` |
| `name` | TEXT | 用户可改 |
| `note` | TEXT | 备注 |
| `status` | TEXT | draft/queued/running/paused/completed/completed_with_errors/canceled |
| `mode` | TEXT | live / demo |
| `spec_json` | TEXT | 冻结的 BatchSpec |
| `route_snapshot_json` | TEXT | 冻结的模型路由 |
| `created_at` / `updated_at` | TEXT | UTC |
| `started_at` / `finished_at` | TEXT? | UTC |
| `archived` | INTEGER | 保留字段；当前 UI 不做归档 |

计数不单独存储，读取时从 items 聚合；避免计数器漂移。

## 3. items

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | TEXT PK | `itm_...` |
| `batch_id` | TEXT FK | 级联删除 |
| `position` | INTEGER | 批次内顺序 |
| `file_name` | TEXT | 原始显示名 |
| `stored_path` | TEXT | 原始音频绝对路径 |
| `inference_path` | TEXT | 转码后的上传副本 |
| `mime` / `size_bytes` | TEXT/INTEGER | 原文件信息 |
| `sha256` | TEXT | 去重 |
| `duration_sec` / `sample_rate` / `channels` / `bitrate` | 数值 | ffprobe |
| `status` | TEXT | queued/preprocessing/inferencing/normalizing/saving/completed/failed/canceled |
| `stage` | TEXT | 更细的阶段，用于 UI |
| `progress` | INTEGER | 0–100 |
| `raw_text` | TEXT | 音频模型原始输出 |
| `llm_raw_text` | TEXT | 规范化模型原始输出（含失败时的内容） |
| `normalized_json` | TEXT? | 校验后的结果 |
| `summary_json` | TEXT? | 列表展示用摘要 |
| `error_code` / `error_message` | TEXT | 分类错误 |
| `attempts` | INTEGER | 已尝试次数 |
| `next_retry_at` | TEXT? | 指数退避 |
| `inference_route_id` / `inference_model` | TEXT | 实际模型 |
| `llm_route_id` / `llm_model` | TEXT | 实际规范化模型 |
| `timings_json` | TEXT | 预处理/推理/规范化/总耗时、usage |
| `review_status` | TEXT | unreviewed/approved/needs_changes |
| `review_note` | TEXT | 人工备注 |
| `created_at` / `updated_at` | TEXT | UTC |
| `started_at` / `finished_at` | TEXT? | UTC |

索引：`(batch_id, position)`, `(status)`, `(batch_id, status)`。

## 4. events

| 字段 | 说明 |
| --- | --- |
| `id` | 自增，SSE 游标 |
| `batch_id` / `item_id` | 可空 |
| `kind` | `batch_created`, `item_completed`, `endpoint_auto_paused` 等 |
| `level` | info/warn/error |
| `message` | 人类可读 |
| `data_json` | 结构化补充 |
| `created_at` | UTC |

事件是运行日志，不是审计签名；可被清理，不应作为法律凭证。

## 5. usage

| 字段 | 说明 |
| --- | --- |
| `stage` | inference / normalization |
| `provider` / `model` | 供应商标识 |
| `latency_ms` | 墙钟 |
| `input_units` / `output_units` | token 数（若供应商返回） |
| `meta_json` | 原始 usage、attempt 等 |
| `batch_id` / `item_id` | 可空 |

当前不做费用计算；不同供应商的计价单位不同，不能用一个硬编码价格。

## 6. schema_meta

| key | value |
| --- | --- |
| `schema_version` | `1` |
| `created_at` | 首次初始化时间 |

## 7. 文件布局

```text
data/
  cadence.db
  config.json
  secrets.bin
  audio/
    {batch_id}/
      {item_id}.mp3          # 原文件
      inference/{item_id}.mp3 # 转码副本
    demo-seed/               # 演示音频
  exports/{batch_id}/
  logs/
  backups/
```

## 8. 数据生命周期

- 删除批次：删除 batch、items、events，再删 `data/audio/{batch_id}`。
- 运行中的项目不能删批次；先暂停/等待。
- 没有自动 TTL；音频和导出会一直保留，需自行制定保留策略。
- 备份只复制数据库；音频/配置需单独备份。

## 9. 迁移策略

`db.init()` 使用 `CREATE TABLE IF NOT EXISTS`，当前没有迁移工具。新增字段时：

1. 在 `SCHEMA` 加入字段；
2. 为已有数据库增加 `ALTER TABLE` 的幂等迁移；
3. 更新 `schema_version`；
4. 更新本文档与测试；
5. 不删除历史字段，除非有明确的迁移与回滚方案。
