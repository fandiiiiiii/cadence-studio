# Windows 快速开始

本指南假设你使用的是 Windows 10/11，目标是**双击打开、填一次 API、开始标注**。

## 0. 先检查

| 依赖 | 要求 | 检查 |
| --- | --- | --- |
| Python | 3.11+；推荐 3.12 | `python --version` |
| ffmpeg / ffprobe | 建议安装并加入 PATH | `ffmpeg -version` |
| 浏览器 | Edge / Chrome / Firefox 最新版 | — |
| 磁盘 | 至少 2GB 可用（不含音频与模型） | — |

> 没有 ffmpeg 也能启动，但无法可靠读取部分 MP3/M4A 时长，也无法生成紧凑上传副本。建议安装。Windows 可用 `winget install Gyan.FFmpeg`，或使用现有 FFmpeg 的 `bin` 目录加入 PATH。

## 1. 首次启动

### 已构建的 EXE

双击 `dist\CadenceStudio.exe`。会出现一个小型控制窗；点 **打开工作台** 或等浏览器自动打开。关闭控制窗即停止服务。数据位于 `%LOCALAPPDATA%\CadenceStudio`。

重新构建：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_windows.ps1
```

### 源码脚本

双击：

```text
启动 Cadence.cmd
```

首次启动会显示安装过程（1–3 分钟）：

```text
Cadence Studio · 0.2.0
http://127.0.0.1:8765/
data: ...\AI Music Caption\data
关闭此窗口即可停止工作台。
```

浏览器会自动打开。如果端口被占用，会使用 `8766–8794`，以终端打印的 URL 为准。

### 如果双击没反应

在仓库目录打开 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.\启动 Cadence.cmd
```

如果提示 Python 不存在，请先安装 Python 3.12，并勾选 **Add python.exe to PATH**。

## 2. 先看演示批次

没有配置 API 时，首页会显示空状态。点击 **载入演示批次**：

- 四首本地生成的原创合成片段；
- 结果带有 `DEMO` 标记；
- 可体验表格、抽屉、原始输出、JSON、标签映射、五种导出。

演示数据不是模型真实输出，不要用于生产。

## 3. 配置 DeepSeek

1. 打开 **设置 → 文字模型**。
2. 填写：
   - BASE URL：`https://api.deepseek.com`
   - 模型名：`deepseek-flash`（当前官方名；`deepseek-chat` 是旧名）
   - API KEY：你的 `sk-...`
   - 思考模式：关闭（推荐）
   - TEMPERATURE：`0.1`
   - MAX TOKENS：`4096`
3. 点 **测试**。
4. 点页面底部 **保存设置**。

## 4. 配置 Hugging Face

完整步骤见 **[Hugging Face 端点部署教程](huggingface-setup.md)**。最短路径：

1. 在 Hugging Face 创建自定义容器 Endpoint（MOSS 或 Flamingo）。
2. 等状态变成 `Running`，复制端点名称。
3. 在 **设置 → 推理端点** 填：
   - HF TOKEN
   - HF NAMESPACE
   - HF ENDPOINT NAME
   - 模型仓库（与端点一致）
   - 最大并发 `1`
4. 点 **验证令牌**、**测试**。
5. 点页面底部 **保存设置**。

系统会自动解析 Inference URL，不需要手动复制随机域名。

## 5. 第一首真实音频

不要一上来跑 500 首（或你当前的每日目标）。

1. 新建批次；
2. 选一首 30–60 秒、有权使用的音频；
3. 只勾选 **Caption + Genre + Mood + BPM/Key**；
4. 取消“创建后立即开始”；
5. 创建后，在批次页点 **开始处理**；
6. 盯住进度：
   - 端点启动可能 5–15 分钟；
   - 音频模型推理；
   - DeepSeek 规范化；
   - 写入结果；
7. 打开抽屉，对照试听检查：
   - 原始观察是否完整；
   - 标签是否在目录内；
   - Caption 是否准确；
   - BPM/Key 是否合理；
8. 记录：音频时长、GPU、模型 revision、端点启动时间、端到端耗时、错误、账单。

## 6. 第二批：20 首

第一首通过后，再跑 20 首 3–4 分钟音频，验证：

- 显存是否稳定；
- 冷启动后连续处理是否正常；
- 失败重试是否有效；
- 导出是否完整；
- 自动暂停是否在队列空后触发；
- 实际每小时吞吐。

用 `docs/quality/benchmark.md` 的表格记录，不要凭感觉估算。

## 7. 每日目标

Cadence 的每日目标可以在 **总览 → Daily runway → 目标** 或 **设置 → 工作区** 中随时修改，不一定是 500。目标只影响进度展示，不决定实际产能。

确认单首耗时后再决定：

- 单卡 90 秒/首 → 约 12.5 GPU 小时；可行但接近日容量；
- 单卡 150 秒/首 → 约 20.8 小时；需要过夜；
- 单卡 240 秒/首 → 33 小时；单卡不可行；
- 需要白天交付：两条端点或更大显存。

系统支持持久队列与断点恢复；可以前一天晚上开始，第二天早上导出。

## 8. 关机与数据

- 关闭终端窗口即停止本地服务；
- 已提交的数据在 `data/`，下次打开继续；
- 处理中的项目在重启后会重新入队；
- 端点如果仍在运行，会继续计费。离开前可在设置里点 **Pause**，或等待自动暂停；
- 定期备份 `data/`（至少数据库 + 配置 + 音频 + 导出）。

## 9. 升级

```powershell
git pull
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

升级前备份 `data/`。标签体系或 schema 变更会写入 `CHANGELOG.md`；历史批次保留自己的快照。

## 10. 卸载

- 关闭工作台；
- 删除仓库目录；
- 删除 `%LOCALAPPDATA%\CadenceStudio`（仅打包版使用）；
- 到 Hugging Face 控制台 Pause/Delete 端点，避免继续计费；
- 撤销不再使用的 HF / DeepSeek API Key。
