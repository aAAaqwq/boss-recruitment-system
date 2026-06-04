#!/bin/bash
# 安装脚本 - 安装BOSS直聘自动化系统

echo "========================================"
echo "🚀 BOSS直聘自动化系统 - 安装工具"
echo "========================================"

# 检查Python版本
python_version=$(python3 --version 2>&1 | grep -oP '\d+\.\d+')
echo "📦 Python版本: $python_version"

if [[ "$(printf '%s\n' "3.8" "$python_version" | sort -V | head -n1)" != "3.8" ]]; then
    echo "❌ Python版本过低，需要 >= 3.8"
    exit 1
fi

# 安装依赖
echo ""
echo "📦 安装依赖..."
pip3 install -q playwright pyinstaller

# 安装浏览器
echo ""
echo "🌐 安装Chrome浏览器..."
playwright install chromium

# 创建配置目录
echo ""
echo "📁 创建配置目录..."
mkdir -p ~/.boss-recruitment

# 复制配置文件
echo ""
echo "📝 复制配置文件..."
cp skill.json ~/.boss-recruitment/

# 创建快捷方式
echo ""
echo "🔗 创建快捷方式..."
if [[ "$OSTYPE" == "darwin" ]]; then
    # macOS
    mkdir -p ~/Desktop
    cat > ~/Desktop/BOSS直聘自动化.command << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
python3 boss_auto_v2.py --mode all
EOF
    chmod +x ~/Desktop/BOSS直聘自动化.command
    echo "✅ 桌面快捷方式已创建"
else
    # Windows/Linux
    echo "ℹ️ 请手动创建快捷方式"
fi

echo ""
echo "========================================"
echo "✅ 安装完成"
echo "========================================"
echo ""
echo "📦 使用方式:"
echo "   python boss_auto_v2.py --mode all"
echo ""
echo "📦 可用模式:"
echo "   --mode greet   # 自动打招呼"
echo "   --mode resume  # 自动获取简历"
echo "   --mode chat    # AI自动对话"
echo "   --mode all     # 完整流程"
echo ""
