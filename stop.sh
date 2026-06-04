#!/bin/bash
# BOSS直聘三位一体系统 - 停止脚本

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

WORK_DIR="$HOME/.openclaw/workspace/agents/workspace-xuanyuan/boss-recruitment-system"
cd "$WORK_DIR"

# 读取PID
if [ -f .trinity.pid ]; then
    PID=$(cat .trinity.pid)
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo "${GREEN}✅ 系统已停止 (PID: $PID)${NC}"
    else
        echo "${RED}⚠️ 进程不存在 (PID: $PID)${NC}"
    fi
    rm -f .trinity.pid
else
    echo "${RED}⚠️ 未找到PID文件${NC}"
fi

# 额外清理可能的Python进程
pkill -f "run_trinity.py" 2>/dev/null || true
pkill -f "uvicorn app.api" 2>/dev/null || true

echo "清理完成"
