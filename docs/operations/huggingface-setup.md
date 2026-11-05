# Hugging Face 专用端点部署（新手版）

更新时间：2026-11-05。本文给出可执行的路径，但**不是“已在 A10G 上验证”的承诺**。首次必须只跑 1 首并记录结果。

## 0. 为什么必须用自定义容器

两个模型都**不在** Hugging Face 专用端点的托管引擎（vLLM / SGLang / TGI）里开箱即用：

- **MOSS-Music 8B**：官方推荐 fork 的 SGLang（`OpenMOSS/sglang` 的 `moss-audio` 分支），上游 SGLang 没有对应实现；HF 托管 SGLang 镜像无法加载。
- **Music Flamingo 2601**：vLLM 对该架构的支持在 2026 年被移除；当前 vLLM 回退 Transformers 后端会失败。主线 Transformers 可以本地推理。
- 因此本仓库提供**自定义容器**：容器里运行一个 FastAPI 服务，暴露 `/health` 与 `/v1/annotate`；HF 负责 GPU、扩缩容和路由。

参考资料：

- [MOSS-Music 官方仓库](https://github.com/OpenMOSS/MOSS-Music)
- [MOSS SGLang 使用说明](https://github.com/OpenMOSS/MOSS-Music/blob/main/moss_music_usage_guide.md)
- [Music Flamingo 模型卡](https://huggingface.co/nvidia/music-flamingo-2601-hf)
- [Music Flamingo Transformers 文档](https://huggingface.co/docs/transformers/main/model_doc/musicflamingo)
- [HF 自定义容器文档](https://huggingface.co/docs/inference-endpoints/engines/custom_container)
- [HF 端点生命周期 API](https://huggingface.co/docs/inference-endpoints/api_reference)

## 1. 前置条件

- Hugging Face 账号，已绑定有效付款方式（专用端点要求）。
- 可以构建并推送 Docker 镜像的仓库（Docker Hub、GHCR 等）。
- Docker Desktop（Windows）或 Linux 构建机。
- 目标显卡：AWS A10G 24GB（首个候选）。更大的 L40S/A100 更稳。工作台里的硬件预设见 [硬件预设与并发推荐](hardware-presets.md)。
- 能访问 Hugging Face、Docker Hub、PyPI。

> 模型权重不需要下载到你的电脑。Endpoint 会把所选模型仓库挂载到容器内的 `/repository`；容器只包含代码和依赖。

## 2. 构建镜像

### 2.1 MOSS-Music

在仓库根目录：

```powershell
docker buildx build --platform linux/amd64 `
  -f deploy/inference-endpoint/Dockerfile `
  --build-arg MODEL_FAMILY=moss `
  -t <your-docker-user>/cadence-moss:0.1 `
  deploy/inference-endpoint

docker push <your-docker-user>/cadence-moss:0.1
```

### 2.2 Music Flamingo

```powershell
docker buildx build --platform linux/amd64 `
  -f deploy/inference-endpoint/Dockerfile `
  --build-arg MODEL_FAMILY=flamingo `
  -t <your-docker-user>/cadence-flamingo:0.1 `
  deploy/inference-endpoint

docker push <your-docker-user>/cadence-flamingo:0.1
```

> 构建可能需要 10–20 分钟。镜像较大（PyTorch + CUDA）。Dockerfile 使用 PyTorch 2.9.1 / CUDA 12.8 基础镜像；MOSS 固定 `transformers==4.57.1`，Flamingo 使用 `transformers>=5.6`。两者不能装在同一镜像里，所以是两张镜像。

### 2.3 先用 DRY_RUN 验证容器契约（不需要 GPU）

```powershell
docker run --rm -p 8000:8000 `
  -e DRY_RUN=1 `
  -e MODEL_FAMILY=moss `
  <your-docker-user>/cadence-moss:0.1
```

另开终端：

```powershell
curl http://127.0.0.1:8000/health
# {"status":"ok",...}

curl -X POST http://127.0.0.1:8000/v1/annotate `
  -F "audio=@data/audio/demo-seed/<file>.mp3" `
  -F "prompt=Describe genre, mood, BPM, instrumentation and structure." `
  -F "max_new_tokens=900"
```

返回 `text`、`model`、`usage`、`timings` 即契约正确。DRY_RUN 返回的是合成文本，不代表模型能力。

## 3. 创建 Hugging Face Endpoint

1. 打开 [Inference Endpoints 控制台](https://endpoints.huggingface.co/endpoints)，创建 Endpoint。
2. 选择模型仓库：
   - MOSS：`OpenMOSS-Team/MOSS-Music-8B-Instruct`
   - Flamingo：`nvidia/music-flamingo-2601-hf`
3. 任务选 **Custom**，引擎选 **Custom container / 自定义容器**。
4. 填镜像地址、端口 `8000`、健康检查 `/health`。
5. 选择 AWS + A10G 24GB（或更大卡）。
6. 访问类型选 **Private**。
7. Autoscaling：
   - Min replicas `0`
   - Max replicas `1`
   - Automatic scale-to-zero `15 minutes`
8. 环境变量：

| 变量 | 值 | 说明 |
| --- | --- | --- |
| `MODEL_FAMILY` | `moss` / `flamingo` | 必须与镜像一致 |
| `MODEL_PATH` | `/repository` | HF 挂载路径 |
| `MAX_AUDIO_SECONDS` | `1200` | 20 分钟硬上限 |
| `MAX_NEW_TOKENS` | `1024` | 输出上限 |
| `TORCH_DTYPE` | `bfloat16` | A10G 支持 |
| `MODEL_REVISION` | 可选 | 固定 revision，便于追溯 |
| `LOAD_IN_4BIT` | `0` 或实验性 `1` | 非官方量化；质量与稳定性未验证 |

9. 创建。等状态从 `initializing` 变成 `running`。首次加载模型可能 5–15 分钟；期间健康检查未通过是正常的。
10. 如果容器日志显示 OOM：不要反复重启。先用更短的音频测试，或换 48GB+ 显卡。A10G 装 8B 模型 + 4 分钟音频没有官方保证。

## 4. 创建访问令牌

打开 [Access Tokens](https://huggingface.co/settings/tokens)，创建 **Fine-grained** token：

- User permissions → Inference：
  - **Make calls to Inference Endpoints**
  - **Manage Inference Endpoints**（自动 Resume/Pause 需要）
- 如果模型是私有仓库，另加仓库读取权限。

把 token 填进 Cadence 的 **设置 → 推理端点 → HF TOKEN**。不要放进 Dockerfile、Git、截图或聊天记录。

## 5. 在工作台连接

1. 打开 **设置 → 推理端点**。
2. 选择要用的路由（MOSS 或 Flamingo）。
3. 填写：

| 字段 | 示例 |
| --- | --- |
| HF NAMESPACE | `your-hf-username` |
| HF ENDPOINT NAME | `moss-music-a10g` |
| 模型仓库 | `OpenMOSS-Team/MOSS-Music-8B-Instruct` |
| 最大并发 | `1` |
| 适配器 | `Cadence custom /v1/annotate` |

4. **INFERENCE URL 留空**。系统会通过 HF API 读取 `status.url`，避免手抄随机域名。
5. 点 **验证令牌**，再点 **测试**。
6. 保存设置。
7. 左下角/顶栏应显示端点 State；未运行时显示“已暂停/未配置”。

### 自动生命周期

- 新建批次或点击开始：如果端点 `paused` / `scaledToZero` / `stopped`，系统调用 `POST /resume`，轮询到 `running` 且 `/health` 通过后才发音频。
- 队列一空（超过 `pause_grace_seconds`，默认 0 秒）：调用 `POST /scale-to-zero`，状态变为 `scaledToZero`。
- 队列重新有任务：再次自动 resume。
- `scale-to-zero` 是默认空闲动作，需要端点在 spec 中开启 `scaleToZeroTimeout`。系统不会把“请求已发送”当成“云端已完成”，UI 会继续显示真实 State。

## 6. 第一首真实验证

只选一首 30–60 秒、你有权使用的音频：

1. 新建批次，取消立即开始；
2. 模块只选 Caption + Genre + Mood + BPM/Key；
3. 开始处理；
4. 记录：
   - 端点从 paused 到 running 的耗时；
   - `/health` 里的模型加载秒数；
   - 音频模型耗时；
   - DeepSeek 耗时；
   - 是否 OOM、是否 413、是否超时；
   - 输出原始文本是否完整；
   - 标签是否都在 641 目录内；
5. 再跑一条 3–4 分钟音频，观察显存；
6. 在 HF 控制台确认暂停/恢复状态与账单。

### 如果 OOM

按顺序处理：

1. 降低 `MAX_AUDIO_SECONDS`，但**必须明确告知使用者音频被拒收/截断**，不能静默截断；
2. 降低并发到 1（默认已 1）；
3. 使用 L40S 48GB / A100 80GB；
4. 仅在试验环境尝试 `LOAD_IN_4BIT=1`，并重新评估标签质量；
5. 不要把“OOM 通过重启”当作稳定方案。

## 7. 容量与成本

A10G 按小时计费，初始化和运行都算。以 $1/小时、全天 24 小时常开计算约 $24/日，未含存储/网络/其他费用。自动暂停可以显著减少空闲成本，但**不能保证**云端立即暂停；最终账单以 HF 为准。

500 首/日的容量算术见 [基准测试计划](../quality/benchmark.md)。单卡 A10G 的结论取决于实测单首耗时：

- 60–90 秒/首：有希望；
- 150 秒/首：约 21 小时，需过夜；
- 240 秒/首：单卡不可行。

系统优化的是“每首的提示词”和“队列等待”，不是 GPU 本身。不要在单卡上把两个 8B 模型同时常驻。

## 8. 常见错误

| 错误 | 可能原因 | 处理 |
| --- | --- | --- |
| Endpoint 一直 initializing | 模型下载/加载慢，或容器启动失败 | 看 HF Logs；确认镜像可拉取、端口 8000、health 路径 |
| 401 | Token 无效/权限不足 | 重新创建 fine-grained token，勾选 Inference 权限 |
| 403 | 端点 Private / 组织权限 | 确认 token 属于可访问该 namespace 的账号 |
| 404 | namespace / endpoint name 填错 | 用控制台名称，不是模型仓库名 |
| 503 | 冷启动 / 未 ready | 等待；系统会轮询；检查 `/health` |
| 413 | 音频超过端点或请求体限制 | 缩短音频；检查 `MAX_AUDIO_SECONDS` |
| 500 | 模型代码/显存/输入格式问题 | 看容器日志；用 DRY_RUN 验证契约 |
| OOM | 24GB 不足 | 换卡/缩短音频/实验性 4-bit |
| Resume 400 already running | 并发操作 | 系统视为幂等；刷新状态 |
| Scale-to-zero 400 | 端点未开启 scaleToZeroTimeout | 用 Pause，或在 HF 配置中开启 |

## 9. 许可

- **MOSS-Music**：模型卡标注 Apache-2.0；仍需核对代码、数据与使用条款。
- **Music Flamingo**：模型卡标注 NVIDIA OneWay Noncommercial License，仅非商业研究；商业使用前必须取得适当授权。
- Hugging Face、DeepSeek、你上传的音乐各有自己的条款。Cadence 不替代这些判断。
