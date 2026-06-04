#!/bin/bash
# 打包PyAutoGUI版本

echo "========================================"
echo "🚀 BOSS直聘自动化系统 - PyAutoGUI版本"
echo "========================================"

# 安装PyInstaller
pip3 install -q pyinstaller

cd ~/.openclaw/workspace/agents/workspace-xuanyuan/boss-recruitment-system

# 打包
echo "📦 正在打包..."
python3 -m PyInstaller \
    --onefile \
    --name "BOSS直聘自动化系统" \
    --add-data "app:app" \
    --hidden-import pyautogui \
    --hidden-import PIL \
    --hidden-import pytesseract \
    run_automation_final.py

echo ""
echo "========================================"
echo "✅ 打包完成"
echo "========================================"
echo ""
echo "📁 输出: dist/BOSS直聘自动化系统"
echo ""
echo "📦 使用方式:"
echo "   1. 先手动打开Chrome并登录BOSS直聘"
echo "   2. 运行: ./dist/BOSS直聘自动化系统"
echo ""
