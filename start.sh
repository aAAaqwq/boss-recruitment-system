#!/bin/bash
# BOSS直聘三位一体系统 - 一键启动脚本

set -e

echo "=================================="
echo "🚀 BOSS直聘三位一体系统 v1.0"
echo "=================================="
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 工作目录
WORK_DIR="$HOME/.openclaw/workspace/agents/workspace-xuanyuan/boss-recruitment-system"
cd "$WORK_DIR"

# 创建必要目录
mkdir -p logs data

# 检查依赖
echo "📦 检查依赖..."
python3 -c "import fastapi, uvicorn" 2>/dev/null || {
    echo "${RED}❌ 缺少依赖，正在安装...${NC}"
    pip3 install fastapi uvicorn pydantic -q
}

echo "${GREEN}✅ 依赖检查完成${NC}"

# 启动模式
MODE="${1:-all}"

case "$MODE" in
    all)
        echo "🟢 启动模式: 所有Agent"
        python3 run_trinity.py --mode all &
        ;;
    greet)
        echo "🟢 启动模式: 打招呼Agent"
        python3 run_trinity.py --mode greet &
        ;;
    resume)
        echo "🟢 启动模式: 简历Agent"
        python3 run_trinity.py --mode resume &
        ;;
    chat)
        echo "🟢 启动模式: 对话Agent"
        python3 run_trinity.py --mode chat &
        ;;
    api)
        echo "🟢 启动模式: Web API"
        python3 -m uvicorn app.api:app --host 0.0.0.0 --port 8001 --reload &
        ;;
    *)
        echo "${RED}❌ 未知模式: $MODE${NC}"
        echo "用法: ./start.sh [all|greet|resume|chat|api]"
        exit 1
        ;;
esac

# 保存PID
echo $! > .trinity.pid
echo ""
echo "${GREEN}✅ 系统已启动${NC}"
echo ""
echo "📊 访问地址:"
echo "   Web界面: http://localhost:3001"
echo "   API文档: http://localhost:8001/docs"
echo ""
echo "🛑 停止命令: ./stop.sh"
echo "=================================="
