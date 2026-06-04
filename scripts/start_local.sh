#!/bin/bash
# 临时启动脚本 - 在Mac本地运行Web界面和VNC

echo "========================================"
echo "🚀 BOSS直聘三位一体系统 - 本地启动"
echo "========================================"

# 工作目录
WORK_DIR="$HOME/.openclaw/workspace/agents/workspace-xuanyuan/boss-recruitment-system"
cd "$WORK_DIR"

# 检查依赖
echo "📦 检查依赖..."
python3 -c "import fastapi, uvicorn, pyautogui" 2>/dev/null || {
    echo "安装依赖..."
    pip3 install fastapi uvicorn pyautogui -q
}

# 启动Web API
echo "🔌 启动Web API..."
python3 -m uvicorn app.api:app --host 0.0.0.0 --port 8101 &
API_PID=$!

# 启动Web管理界面
echo "📊 启动Web管理界面..."
cd "$WORK_DIR/web"
python3 -m http.server 3101 &
WEB_PID=$!

echo ""
echo "========================================"
echo "✅ 系统已启动"
echo "========================================"
echo ""
echo "📊 Web管理: http://localhost:3101"
echo "🔌 API文档: http://localhost:8101/docs"
echo ""
echo "🛑 停止命令: kill $API_PID $WEB_PID"
echo "========================================"

# 保存PID
echo "$API_PID $WEB_PID" > .local.pid

# 等待
wait
