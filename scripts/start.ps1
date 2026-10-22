#!/usr/bin/env pwsh
# ─────────────────────────────────────────────────────────────
# reese-ag 快速启动脚本（PowerShell — Windows / macOS / Linux）
# 用法：
#   ./start.ps1          首次运行自动完成环境搭建
#   ./start.ps1 -CLI     以 CLI 模式启动（非 Web）
# ─────────────────────────────────────────────────────────────

param(
    [switch]$CLI,
    [int]$Port = 8000,
    [string]$Host = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$VenvDir = ".venv"

function Info($msg)  { Write-Host "[v] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Fail($msg)  { Write-Host "[x] $msg" -ForegroundColor Red; exit 1 }

# ── 1. 检查 Python ──
$python = $null
foreach ($cmd in @("python3", "python", "py")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        $major = & $cmd -c "import sys; print(sys.version_info.major)" 2>$null
        $minor = & $cmd -c "import sys; print(sys.version_info.minor)" 2>$null
        if ([int]$major -ge 3 -and [int]$minor -ge 11) {
            $python = $cmd
            break
        }
    } catch { }
}

if (-not $python) {
    Fail "需要 Python 3.11+，请先安装：https://www.python.org/downloads/"
}
Info "Python $ver ($python)"

# ── 2. 创建虚拟环境 ──
$activateScript = if ($IsWindows -or $env:OS -match "Windows") {
    "$VenvDir/Scripts/Activate.ps1"
} else {
    "$VenvDir/bin/Activate.ps1"
}

if (-not (Test-Path $activateScript)) {
    Warn "首次运行，正在创建虚拟环境..."
    & $python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Fail "虚拟环境创建失败" }
    Info "虚拟环境已创建"
}

# 激活虚拟环境
. $activateScript
Info "虚拟环境已激活"

# ── 3. 安装依赖 ──
$marker = "$VenvDir/.deps_installed"
$needInstall = $false

if (-not (Test-Path $marker)) {
    $needInstall = $true
} elseif ((Get-Item "requirements.txt").LastWriteTime -gt (Get-Item $marker).LastWriteTime) {
    $needInstall = $true
}

if ($needInstall) {
    Warn "正在安装依赖..."
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Fail "依赖安装失败" }
    New-Item -Path $marker -ItemType File -Force | Out-Null
    Info "依赖安装完成"
} else {
    Info "依赖已是最新"
}

# ── 4. 配置 .env ──
if (-not (Test-Path ".env")) {
    if (Test-Path "resources/.env.example") {
        Copy-Item "resources/.env.example" ".env"
        Warn "已从 .env.example 创建 .env，请编辑填入 API Key"
        Write-Host ""
        Warn "至少需要设置以下一项："
        Warn "  ANTHROPIC_API_KEY=sk-ant-xxx    (Anthropic Claude)"
        Warn "  LLM_API_KEY=sk-xxx              (DeepSeek/通义千问等)"
        Write-Host ""
        $answer = Read-Host "是否现在编辑 .env？[Y/n]"
        if ($answer -ne "n" -and $answer -ne "N") {
            if ($IsWindows -or $env:OS -match "Windows") {
                notepad .env
            } else {
                & ($env:EDITOR ?? "nano") .env
            }
        } else {
            Warn "跳过，稍后请手动编辑 .env"
        }
    } else {
        Fail "缺少 .env.example 文件"
    }
}

# ── 5. 创建必要目录 ──
@("data", "output", "checkpoints") | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ | Out-Null }
}

# ── 6. 启动 ──
Write-Host ""
if ($CLI) {
    Info "以 CLI 模式启动"
    Write-Host "─────────────────────────────────────────"
    Write-Host 'python generate.py new --genre 玄幻 --core-pleasure 逆袭打脸 `'
    Write-Host '  --protagonist-name 林逸 --protagonist-background 废材少年 `'
    Write-Host '  --golden-finger 万界交易系统'
    Write-Host "─────────────────────────────────────────"
} else {
    Info "启动 Web 服务：http://localhost:${Port}"
    Write-Host "─────────────────────────────────────────"
    Write-Host "  浏览器打开：http://localhost:${Port}"
    Write-Host "  按 Ctrl+C 停止"
    Write-Host "─────────────────────────────────────────"
    uvicorn main:app --host $Host --port $Port
}
