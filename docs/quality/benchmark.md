# 基准、容量与验收

> 当前状态（2026-11-05）：本地工作台、队列、标签校验、导出、自定义推理容器契约已通过**模拟/DRY_RUN**测试；**没有在真实 A10G、真实 MOSS / Music Flamingo、真实 500 首上运行**。因此不能声称已经达到 500 首/日、不能声称 A10G 一定不 OOM、不能声称标签质量达标。

## 1. 验收门槛

在真实环境跑完以下三轮，记录在本文末尾，才算“可用”。

### 第 1 轮：单首烟雾测试

| 检查 | 通过标准 |
| --- | --- |
| 容器启动 | `/health` 200，模型 revision 与预期一致 |
| 短音频 | 30–60 秒，完整返回，不截断 |
| 长音频 | 3–4 分钟，完整返回，不 OOM |
| 原始输出 | 非空，包含任务要求的字段信息 |
| 规范化 | JSON 合法，所有标签 ID 在目录内 |
| 只请求字段 | Caption-only 请求只返回 `caption` |
| 导出 | XLSX/JSON/MD 可打开，含 raw + normalized |
| 端点状态 | UI 显示 running → 手动 pause → resume 后可用 |

### 第 2 轮：20 首校准

| 指标 | 建议门槛 |
| --- | --- |
| 成功率 | ≥ 90%（不含人为取消） |
| 规范化失败 | ≤ 5% |
| 平均端到端 | 记录实测，不设虚假门槛 |
| 失败可恢复 | 网络/超时失败可重试成功 |
| 端点自动暂停 | 队列空后按宽限期触发 |
| 导出完整 | 20 首全部有 raw + normalized |
| 人工抽检 | ≥ 10 首对照试听 |

### 第 3 轮：高日目标（以 500 首为例）

| 指标 | 建议门槛 |
| --- | --- |
| 24 小时完成 | ≥ 500（含重试） |
| 失败率 | ≤ 2% |
| 单首 P50/P95 | 记录；P95 不超过端点超时 |
| GPU 利用率 | 记录；不要靠猜测 |
| 单首成本 | 记录实际账单 |
| 队列恢复 | 中途重启工作台，任务继续 |

## 2. 容量算术

500 首/日 = 20.8 首/小时 = 每 172.8 秒完成 1 首（全天 24 小时）。如果只在 8 小时工作时间内完成，则需要每 57.6 秒完成 1 首。

| 单首端到端 | 500 首 GPU·小时 | 24h 单卡 | 8h 单卡 |
| ---: | ---: | --- | --- |
| 60 s | 8.3 | 有余量 | 不够（需 2 卡） |
| 90 s | 12.5 | 接近上限 | 不够 |
| 120 s | 16.7 | 可行 | 不够 |
| 150 s | 20.8 | 勉强 | 不够 |
| 180 s | 25.0 | 不够 | 不够 |
| 240 s | 33.3 | 不够 | 不够 |

“单首端到端”应包含：转码、端点已就绪后的推理、LLM、写入。冷启动单独记录。

## 3. 测试方法

### 3.1 端点 DRY_RUN

```powershell
$env:DRY_RUN="1"; $env:MODEL_FAMILY="moss"
.\.venv\Scripts\python.exe -m uvicorn server:app --app-dir deploy\inference-endpoint --port 8780
```

用 `scripts/test_endpoint_dry.py` 验证 multipart 契约。该测试**不验证**模型质量。

### 3.2 本地端到端（mock LLM + DRY_RUN endpoint）

已有 `scripts/test_pipeline.py`，验证队列、SSE、normalizer、导出。运行前启动 mock LLM：

```powershell
.\.venv\Scripts\python.exe -m uvicorn mock_llm:app --app-dir scripts --port 8790
```

这是逻辑测试，不代表真实模型能力。

### 3.3 真实端点测试

快速测端点延迟：

```powershell
python scripts\benchmark_endpoint.py `
  --url https://xxxx.endpoints.huggingface.cloud `
  --audio "data\audio\demo-seed\<file>.mp3" `
  --token $env:HF_TOKEN --runs 3 --out runtime\endpoint-benchmark.json
```

注意：这个脚本测的是端点本身，不含队列、转码、DeepSeek。

1. 在 Cadence 设置连接真实端点与 DeepSeek；
2. 新建单首批次，记录：
   - 端点状态变化时间；
   - `/health` 的 `load_seconds`；
   - 项目 `timings.inference_ms`、`timings.normalization_ms`；
   - `raw_text` / `llm_raw_text` 长度；
   - 失败码。
3. 在 HF 控制台记录实例类型、GPU、模型 revision、每小时价格。
4. 用 `nvidia-smi` 或 HF Metrics 记录峰值显存（若可见）。
5. 重复 20 首，计算 P50/P95。

### 3.4 质量抽检

至少 30–50 首，覆盖不同曲风/语言/人声/纯音乐。两个人独立听，按字段评估：

- 曲风：每个独立曲风是否被保留；一级/二级路径是否正确；是否过度标注；补充曲风是否合理；
- 情绪：dominant 是否正确；互斥是否遵守；
- BPM/Key：与参考工具/人工对照，允许的误差范围；
- 结构：边界误差（秒），段落命名是否合理；
- Caption：事实性、具体性、是否有幻觉；
- 歌词：WER/CER，时间戳误差；
- 安全/质量：漏报/误报；
- 映射：`mapped=true` 的标签是否语义合理。

报告 `precision`、`recall`、`F1`（如适用）、人工一致率、拒绝率。不要只报“看起来不错”。

## 4. 成本记录

不同卡型的推荐并发、音频上限与参考价见 [硬件预设与并发推荐](../operations/hardware-presets.md)。

| 项目 | 记录 |
| --- | --- |
| GPU 实例 | 型号、数量、地区、每小时价格 |
| 运行时长 | 初始化 + 推理 + 空闲 |
| HF 存储/网络 | 若账单列出 |
| DeepSeek tokens | 输入/输出，按实际账单 |
| 重试 | 次数与重复费用 |
| 总成本 | 当日账单 |
| 单首成本 | 总成本 / 成功首数 |

## 5. 当前实测记录（待填）

| 日期 | 硬件 | 模型/revision | 音频 | 端到端 | 结果 | 备注 |
| --- | --- | --- | --- | ---: | --- | --- |
| — | 未测 | — | — | — | — | 等待真实端点 |

> 只有填入真实数据后，才能把 README 的“目标”改成“已验证”。

## 6. 失败模式清单

- OOM（24GB 不足）
- 音频解码失败 / 不支持的容器
- 端点冷启动超时
- 413 请求体过大
- 500 模型代码错误
- 规范化 JSON 截断
- 标签目录超上下文
- LLM 限流 / 余额不足
- 磁盘满
- 工作台进程被杀
- 云端暂停失败（账单继续）

每次失败都记录 `error_code`、端点日志片段、音频时长、模型 revision。不要只写“失败了”。
