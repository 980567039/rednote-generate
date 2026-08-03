#!/bin/bash

# AI 图文创作工具 - macOS 启动脚本
# 双击此文件即可启动；关闭窗口或按 Ctrl+C 会停止本次启动的全部服务。

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FRONTEND_DIR="$PROJECT_DIR/frontend"
BACKEND_PORT=12398
FRONTEND_PORT=5173

BACKEND_PID=""
FRONTEND_PID=""
BACKEND_LOG=""
FRONTEND_LOG=""
STARTED=false
CLEANED_UP=false
USE_UV=false
PKG_MANAGER=""

cd "$PROJECT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

print_banner() {
    # 非交互环境可能没有可用的终端类型；不要因此中断启动。
    clear 2>/dev/null || true
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════╗"
    echo "║     🍎 AI 图文创作工具 - macOS 版             ║"
    echo "╚═══════════════════════════════════════════════╝"
    echo -e "${NC}"
}

check_homebrew() {
    if ! command -v brew &> /dev/null; then
        echo -e "${YELLOW}⚠️  未检测到 Homebrew，建议安装以获得更好体验${NC}"
        echo -e "   安装命令: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo ""
    fi
}

check_requirements() {
    echo -e "${BLUE}📋 检查环境依赖...${NC}"
    echo ""

    if command -v python3 &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} $(python3 --version 2>&1)"
    else
        echo -e "  ${RED}✗${NC} Python3 未安装"
        echo -e "    ${YELLOW}请运行: brew install python3${NC}"
        exit 1
    fi

    if command -v uv &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} uv $(uv --version 2>&1 | head -1)"
        USE_UV=true
    else
        echo -e "  ${YELLOW}!${NC} uv 未安装，将使用 pip3"
    fi

    if command -v pnpm &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} pnpm $(pnpm --version)"
        PKG_MANAGER="pnpm"
    elif command -v npm &> /dev/null; then
        echo -e "  ${YELLOW}!${NC} npm $(npm --version)（建议安装 pnpm）"
        PKG_MANAGER="npm"
    else
        echo -e "  ${RED}✗${NC} Node.js 未安装"
        echo -e "    ${YELLOW}请运行: brew install node${NC}"
        exit 1
    fi

    if ! command -v curl &> /dev/null || ! command -v lsof &> /dev/null; then
        echo -e "${RED}✗${NC} 缺少 curl 或 lsof，无法进行服务健康检查"
        exit 1
    fi

    echo ""
}

check_port_available() {
    local port="$1"
    local service_name="$2"
    local pids
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"

    if [[ -n "$pids" ]]; then
        echo -e "${RED}✗${NC} $service_name 端口 $port 已被占用（PID: ${pids//$'\n'/, }）"
        echo -e "  请先停止已有服务后再启动。可执行：${YELLOW}lsof -tiTCP:$port -sTCP:LISTEN | xargs kill${NC}"
        return 1
    fi

    return 0
}

check_ports() {
    echo -e "${BLUE}🔌 检查端口...${NC}"
    check_port_available "$BACKEND_PORT" "后端" || exit 1
    check_port_available "$FRONTEND_PORT" "前端" || exit 1
    echo -e "  ${GREEN}✓${NC} 端口 ${BACKEND_PORT}、${FRONTEND_PORT} 可用"
    echo ""
}

ensure_publisher_component() {
    local publisher_dir="$PROJECT_DIR/third_party/XiaohongshuSkills"
    if [[ -f "$publisher_dir/scripts/publish_pipeline.py" ]]; then
        echo -e "  ${GREEN}✓${NC} 小红书发布组件已就绪"
        return 0
    fi

    if ! command -v git &> /dev/null || [[ ! -f "$PROJECT_DIR/.gitmodules" ]]; then
        echo -e "  ${YELLOW}!${NC} 未找到小红书发布组件；生成和下载功能仍可使用"
        return 0
    fi

    echo -e "  ${CYAN}→${NC} 初始化小红书发布组件（首次运行需要网络）"
    if git -C "$PROJECT_DIR" submodule update --init third_party/XiaohongshuSkills; then
        echo -e "  ${GREEN}✓${NC} 小红书发布组件已就绪"
    else
        echo -e "  ${YELLOW}!${NC} 发布组件初始化失败；可稍后执行：git submodule update --init"
    fi
}

install_deps() {
    echo -e "${BLUE}📦 检查项目依赖...${NC}"

    if [[ "$USE_UV" == true ]]; then
        echo -e "  ${CYAN}→${NC} 后端依赖 (uv)"
        uv sync --quiet 2>/dev/null || uv sync
    else
        echo -e "  ${CYAN}→${NC} 后端依赖 (pip)"
        pip3 install -e . --quiet 2>/dev/null || pip3 install -e .
    fi
    echo -e "  ${GREEN}✓${NC} 后端依赖完成"

    echo -e "  ${CYAN}→${NC} 前端依赖"
    if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
        (
            cd "$FRONTEND_DIR"
            "$PKG_MANAGER" install
        )
    fi
    echo -e "  ${GREEN}✓${NC} 前端依赖完成"
    echo ""
}

# 递归停止一个进程及其子进程，避免 pnpm/uv 的子进程遗留在后台。
stop_process_tree() {
    local pid="${1:-}"
    local child

    [[ -n "$pid" ]] || return 0
    kill -0 "$pid" 2>/dev/null || return 0

    while IFS= read -r child; do
        [[ -n "$child" ]] && stop_process_tree "$child"
    done < <(pgrep -P "$pid" 2>/dev/null || true)

    kill -TERM "$pid" 2>/dev/null || true
    for _ in {1..10}; do
        kill -0 "$pid" 2>/dev/null || return 0
        sleep 0.2
    done
    kill -KILL "$pid" 2>/dev/null || true
}

show_log_tail() {
    local log_file="$1"
    local label="$2"
    echo -e "${YELLOW}最近的${label}日志：${NC}"
    tail -n 40 "$log_file" 2>/dev/null | sed "s/^/  [$label] /" || true
}

wait_for_service() {
    local name="$1"
    local url="$2"
    local pid="$3"
    local attempt

    for ((attempt = 1; attempt <= 40; attempt++)); do
        if curl -fsS --max-time 2 "$url" > /dev/null 2>&1; then
            echo -e "  ${GREEN}✓${NC} $name 已就绪"
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            echo -e "  ${RED}✗${NC} $name 启动后意外退出，请查看上方日志"
            return 1
        fi
        sleep 0.5
    done

    echo -e "  ${RED}✗${NC} 等待 $name 就绪超时，请查看上方日志"
    return 1
}

cleanup() {
    [[ "$CLEANED_UP" == true ]] && return 0
    CLEANED_UP=true
    [[ "$STARTED" == true ]] || return 0

    echo ""
    echo -e "${YELLOW}⏹  正在停止服务...${NC}"
    stop_process_tree "$FRONTEND_PID"
    stop_process_tree "$BACKEND_PID"
    [[ -n "$BACKEND_LOG" ]] && rm -f "$BACKEND_LOG"
    [[ -n "$FRONTEND_LOG" ]] && rm -f "$FRONTEND_LOG"
    echo -e "${GREEN}✓${NC} 服务已停止"
}

start_services() {
    echo -e "${GREEN}🚀 启动服务...${NC}"
    echo ""

    BACKEND_LOG="$(mktemp -t ai-content-backend.XXXXXX.log)"
    FRONTEND_LOG="$(mktemp -t ai-content-frontend.XXXXXX.log)"
    STARTED=true

    if [[ "$USE_UV" == true ]]; then
        uv run --no-sync flask --app backend.app:create_app run \
            --host 127.0.0.1 --port "$BACKEND_PORT" --no-reload > "$BACKEND_LOG" 2>&1 &
    else
        python3 -m flask --app backend.app:create_app run \
            --host 127.0.0.1 --port "$BACKEND_PORT" --no-reload > "$BACKEND_LOG" 2>&1 &
    fi
    BACKEND_PID=$!

    if ! wait_for_service "后端" "http://127.0.0.1:$BACKEND_PORT/api/health" "$BACKEND_PID"; then
        show_log_tail "$BACKEND_LOG" "后端"
        cleanup
        exit 1
    fi

    (
        cd "$FRONTEND_DIR"
        ./node_modules/.bin/vite --host 127.0.0.1
    ) > "$FRONTEND_LOG" 2>&1 &
    FRONTEND_PID=$!

    if ! wait_for_service "前端" "http://127.0.0.1:$FRONTEND_PORT" "$FRONTEND_PID"; then
        show_log_tail "$FRONTEND_LOG" "前端"
        cleanup
        exit 1
    fi

    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║         🎉 服务启动成功！                     ║${NC}"
    echo -e "${GREEN}╠═══════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║${NC}  🌐 前端: ${BLUE}http://localhost:$FRONTEND_PORT${NC}              ${GREEN}║${NC}"
    echo -e "${GREEN}║${NC}  🔧 后端: ${BLUE}http://localhost:$BACKEND_PORT${NC}             ${GREEN}║${NC}"
    echo -e "${GREEN}╠═══════════════════════════════════════════════╣${NC}"
    echo -e "${GREEN}║${NC}  按 ${YELLOW}Ctrl+C${NC} 或关闭此窗口即可停止服务            ${GREEN}║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════╝${NC}"
    echo ""

    open "http://localhost:$FRONTEND_PORT" 2>/dev/null || true
}

monitor_services() {
    local status
    while true; do
        if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
            status=0
            wait "$BACKEND_PID" || status=$?
            echo -e "${RED}后端服务已退出（状态码：$status）${NC}"
            return "$status"
        fi
        if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
            status=0
            wait "$FRONTEND_PID" || status=$?
            echo -e "${RED}前端服务已退出（状态码：$status）${NC}"
            return "$status"
        fi
        sleep 1
    done
}

on_exit() {
    local exit_status=$?
    cleanup || true
    trap - EXIT
    exit "$exit_status"
}

trap on_exit EXIT
trap 'exit 0' INT TERM HUP

print_banner
check_homebrew
check_requirements
check_ports
ensure_publisher_component
install_deps
start_services
monitor_services
