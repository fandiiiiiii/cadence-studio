$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$Requirements = Join-Path $Root "requirements.txt"
$Marker = Join-Path $Root ".venv\.cadence-deps"

function Write-Step([string]$Text) {
  Write-Host ""
  Write-Host "  [Cadence] $Text" -ForegroundColor DarkGray
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
  Write-Step "首次启动：创建 Python 虚拟环境"
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    & py -3 -m venv .venv
  } else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
      Write-Host "  找不到 Python。请安装 Python 3.11+ 并加入 PATH。" -ForegroundColor Red
      exit 1
    }
    & python -m venv .venv
  }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
  Write-Host "  虚拟环境创建失败。" -ForegroundColor Red
  exit 1
}

$NeedInstall = -not (Test-Path -LiteralPath $Marker)
if (-not $NeedInstall) {
  $NeedInstall = (Get-Item -LiteralPath $Requirements).LastWriteTime -gt (Get-Item -LiteralPath $Marker).LastWriteTime
}

if ($NeedInstall) {
  Write-Step "安装运行依赖（首次约 1–3 分钟）"
  & $VenvPython -m pip install --disable-pip-version-check -r $Requirements
  if ($LASTEXITCODE -ne 0) {
    Write-Host "  依赖安装失败。请检查网络或代理。" -ForegroundColor Red
    exit 1
  }
  Set-Content -LiteralPath $Marker -Value (Get-Date).ToString("o") -Encoding UTF8
}

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$ffprobe = Get-Command ffprobe -ErrorAction SilentlyContinue
if (-not $ffmpeg -or -not $ffprobe) {
  Write-Host "  [提示] 未找到 ffmpeg/ffprobe，音视频转码与部分格式时长读取会降级。" -ForegroundColor Yellow
}

exit 0
