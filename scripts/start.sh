#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# reese-ag 快速启动脚本（macOS / Linux）
# 用法：
#   chmod +x start.sh
#   ./start.sh          # 首次运行自动完成环境搭建
#   ./start.sh --cli    # 以 CLI 模式启动（非 Web）
# ─────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

VENV_DIR=".venv"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

# ── 颜色 ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
fail()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

# ── 1. 检查 Python ──
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null)
        minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    fail "需要 Python 3.11+，请先安装：https://www.python.org/downloads/"
fi
info "Python $version ($PYTHON)"

# ── 2. 创建虚拟环境 ──
if [ ! -d "$VENV_DIR" ]; then
    warn "首次运行，正在创建虚拟环境..."
    "$PYTHON" -m venv "$VENV_DIR"
    info "虚拟环境已创建"
fi

# 激活虚拟环境
source "$VENV_DIR/bin/activate"
info "虚拟环境已激活"

# ── 3. 安装依赖 ──
# 用 requirements.txt 的修改时间判断是否需要重新安装
MARKER="$VENV_DIR/.deps_installed"
if [ ! -f "$MARKER" ] || [ "requirements.txt" -nt "$MARKER" ]; then
    warn "正在安装依赖..."
    pip install -q --upgrade pip
    pip install -q -r requirements.txt
    touch "$MARKER"
    info "依赖安装完成"
else
    info "依赖已是最新"
fi

# ── 4. 配置 .env ──
if [ ! -f ".env" ]; then
    if [ -f "resources/.env.example" ]; then
        cp resources/.env.example .env
        warn "已从 .env.example 创建 .env，请编辑填入 API Key："
        warn "  vi .env"
        echo ""
        warn "至少需要设置以下一项："
        warn "  ANTHROPIC_API_KEY=sk-ant-xxx    (Anthropic Claude)"
        warn "  LLM_API_KEY=sk-xxx              (DeepSeek/通义千问等)"
        echo ""
        read -p "是否现在编辑 .env？[Y/n] " answer
        case "$answer" in
            [nN]*) warn "跳过，稍后请手动编辑 .env" ;;
            *)     ${EDITOR:-vi} .env ;;
        esac
    else
        fail "缺少 .env.example 文件"
    fi
fi

# ── 5. 创建必要目录 ──
mkdir -p data output checkpoints

# ── 6. 启动 ──
echo ""
if [ "$1" = "--cli" ]; then
    info "以 CLI 模式启动"
    echo "─────────────────────────────────────────"
    echo "用法：python generate.py new --genre 玄幻 --core-pleasure 逆袭打脸 \\"
    echo "        --protagonist-name 林逸 --protagonist-background 废材少年 \\"
    echo "        --golden-finger 万界交易系统"
    echo "─────────────────────────────────────────"
    exec "$SHELL"
else
    info "启动 Web 服务：http://localhost:${PORT}"
    echo "─────────────────────────────────────────"
    echo "  浏览器打开：http://localhost:${PORT}"
    echo "  按 Ctrl+C 停止"
    echo "─────────────────────────────────────────"
    exec uvicorn main:app --host "$HOST" --port "$PORT"
fi
