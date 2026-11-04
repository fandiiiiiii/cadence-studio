# 故障排查

## 1. 启动

### 双击 `.cmd` 后窗口闪退

在 PowerShell 中运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup.ps1
```

看报错。常见原因：

- 未安装 Python / 未加入 PATH；
- 无网络，pip 安装失败；
- 文件夹路径被安全软件拦截；
- 端口全被占用（8765–8794）。

### 浏览器打开空白 / 一直加载

1. 确认终端里有 `Uvicorn running on http://127.0.0.1:xxxx`；
2. 用该 URL，不要用旧书签端口；
3. 打开 `http://127.0.0.1:xxxx/api/health`；
4. 浏览器强制刷新（Ctrl+F5）；
5. 若仍空白，打开开发者工具 Console，检查 JS 错误。

### 端口被占用

启动器会自动选下一个端口。也可：

```powershell
.\.venv\Scripts\python.exe -m cadence_studio --port 8791
```

## 2. API / 设置

### “凭据文件无法读取”

`data/secrets.bin` 由 DPAPI 绑定当前 Windows 用户与电脑。换用户、换机器、重装系统后无法解密。

处理：关闭工作台，将 `data/secrets.bin` 移到安全位置（或删除），重新打开，在设置中重新输入 API Key。

### “未配置”

- 推理：namespace + endpoint name + token 都必填，或填完整 URL；
- 文字：base_url + model 必填；部分本地服务不需要 key；
- 保存后是否点了底部 **保存设置**。

### 测试令牌 401

- token 失效；
- 不是 fine-grained token；
- 缺少 Inference Endpoints 权限；
- 组织端点需要组织访问权限。

### 测试模型 400 / response_format

系统会自动去掉 JSON 模式重试一次；如果仍失败，检查模型是否兼容 OpenAI chat completions。

## 3. 队列

### 批次一直 queued

1. 看设置里的端点状态；
2. 是否已配置 token/URL；
3. 是否有其他批次占满并发；
4. 看活动流中的 `scheduler_error` / `endpoint_warm_failed`；
5. 检查批次是否被暂停。

### 项目卡在 preprocessing

- ffmpeg 卡住或文件损坏；
- 大文件转码慢；
- 磁盘满；
- 重启工作台后会自动重新入队。

### 项目卡在 inferencing

- 端点冷启动；
- 请求超时（默认 900s）；
- 端点 OOM/500。
看 HF Logs 与 item 的 `error_code`/`error_message`。

### 项目卡在 normalizing

- LLM 超时/限流；
- 输出被截断；
- 目录过大。
优先点“重新规范化”（复用音频原文）；减少模块数。

### 失败后如何重试

- 单项抽屉：重新规范化 / 完整重跑；
- 批次页：重试失败项；
- 失败项目的 raw_text 如果存在，不要重复跑 GPU。

## 4. 端点

### 一直 initializing

- 镜像拉取慢；
- 模型加载慢（8B，5–15 分钟）；
- 容器崩溃。
看 HF Endpoint Logs。容器启动命令必须是：

```text
uvicorn server:app --host 0.0.0.0 --port 8000
```

健康路径 `/health`。

### 401 / 403

- token 与 namespace 不匹配；
- 端点不是 Private 或 token 无权限；
- endpoint name 填错。

### 404

- namespace/endpoint name 错；
- 端点已删除；
- 用的是模型仓库名而不是 endpoint 名。

### 503

- 冷启动；
- 模型未加载；
- 路由还没 ready。
系统会轮询；也可以查看 `/health`。

### 500 / OOM

- 24GB 不够；
- 输入超过 `MAX_AUDIO_SECONDS`；
- 模型代码/版本不匹配。
先看日志；不要反复自动重启烧钱。

### Pause / Resume 失败

- HF token 缺少 Manage Inference Endpoints；
- 端点已删除/正在更新；
- 400 already running（系统视为幂等）；
- scale-to-zero 未启用。

### 端点空闲没暂停

- 自动暂停关闭；
- 还在宽限期内；
- 端点不是 HF 托管模式（仅 URL）；
- pause 请求失败（看活动流）。

## 5. 数据

### 磁盘满

- `data/audio/` 原文件 + 转码副本；
- `data/exports/`；
- `data/backups/`。
清理前先备份数据库和需要的音频。

### 导出失败

- 检查 `data/exports/{batch_id}` 写权限；
- XLSX 单元格长度超限时系统会截断 raw（32000 字符）；
- 批次无项目时不能导出。

### 删除批次后空间没释放

- Windows 文件被占用；
- 检查 `data/audio/{batch_id}` 是否仍存在；
- 重启后手动删除。

### 想迁移到新电脑

1. 关闭工作台；
2. 复制整个 `data/`；
3. 新电脑重新输入 API Key（DPAPI 不可迁移）；
4. 不要两台电脑同时写同一个 SQLite。

## 6. 诊断包

提交问题前收集：

```powershell
# 版本与健康
.\.venv\Scripts\python.exe -c "import sys; sys.path.insert(0,'src'); import cadence_studio; print(cadence_studio.__version__)"

# 最近错误（不要包含密钥）
Get-Content data\logs\*.log -Tail 200

# 端点状态（脱敏）
# 设置页截图时遮住 token
```

不要发送：API Key、完整音频（除非有权且必要）、客户数据、未脱敏的歌词。

## 7. 快速恢复顺序

1. 暂停批次；
2. 看活动流最近 20 条；
3. 看端点状态；
4. 手动 Pause/Resume；
5. 单首重试；
6. 重启工作台（保留数据）；
7. 备份数据库后再做更大改动。
