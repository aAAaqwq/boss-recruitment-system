#!/bin/bash
# 打包脚本 - 将BOSS直聘自动化系统打包成可执行文件

echo "========================================"
echo "🚀 BOSS直聘自动化系统 - 打包工具"
echo "========================================"

# 检查PyInstaller
if ! command -v pyinstaller &> /dev/null; then
    echo "📦 安装PyInstaller..."
    pip3 install -q pyinstaller
fi

# 工作目录
WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$WORK_DIR"

echo ""
echo "📦 开始打包..."

# 打包参数
pyinstaller \
    --onefile \
    --windowed \
    --name "BOSS直聘自动化系统" \
    --add-data "skill.json:." \
    --hidden-import playwright \
    --hidden-import playwright.async_api \
    --hidden-import asyncio \
    --hidden-import json \
    --hidden-import os \
    --hidden-import datetime \
    --hidden-import random \
    --hidden-import argparse \
    boss_auto_v2.py

echo ""
echo "========================================"
echo "✅ 打包完成"
echo "========================================"
echo ""
echo "📁 输出位置:"
echo "   dist/BOSS直聘自动化系统"
echo ""
echo "📦 分发方式:"
echo "   1. 将 dist/ 目录压缩为 zip"
echo "   2. 用户下载后解压"
echo "   3. 双击运行 'BOSS直聘自动化系统'"
echo ""

# 创建README
cat > dist/README.md << 'EOF'
# BOSS直聘自动化系统

## 安装

1. 解压zip文件
2. 双击运行 `BOSS直聘自动化系统`

## 使用

首次运行会自动下载Chrome浏览器（约100MB）。

### 运行模式

- **完整流程**: 双击运行
- **自动打招呼**: `BOSS直聘自动化系统 --mode greet`
- **获取简历**: `BOSS直聘自动化系统 --mode resume`
- **AI对话**: `BOSS直聘自动化系统 --mode chat`

## 配置

编辑 `config.json` 文件：

```json
{
  "daily_greet_cap": 80,
  "school_whitelist": ["清华大学", "北京大学"],
  "delay_min": 1.5,
  "delay_max": 4.0
}
```

## 注意事项

1. 首次运行会自动下载Chrome浏览器
2. 需要在浏览器中手动登录BOSS直聘
3. 登录完成后按回车继续自动化

## 支持

如有问题，请联系技术支持。
EOF

echo "📄 README.md 已创建"
