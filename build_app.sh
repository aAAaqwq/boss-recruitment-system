#!/bin/bash
# 打包脚本 - 将Python脚本打包成可执行文件

echo "========================================"
echo "🚀 BOSS直聘自动化系统 - 打包工具"
echo "========================================"

# 检查PyInstaller
if ! command -v pyinstaller &> /dev/null; then
    echo "📦 安装PyInstaller..."
    pip3 install pyinstaller
fi

# 打包参数
APP_NAME="BOSS直聘自动化系统"
APP_VERSION="1.0.0"

# 工作目录
WORK_DIR="$HOME/.openclaw/workspace/agents/workspace-xuanyuan/boss-recruitment-system"
cd "$WORK_DIR"

# 创建spec文件
cat > boss_recruitment.spec << 'EOF'
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['run_serial.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('app', 'app'),
        ('web', 'web'),
        ('data', 'data'),
    ],
    hiddenimports=[
        'pyautogui',
        'cv2',
        'numpy',
        'PIL',
        'fastapi',
        'uvicorn',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BOSS直聘自动化系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
EOF

echo ""
echo "📦 开始打包..."
pyinstaller boss_recruitment.spec --clean

echo ""
echo "========================================"
echo "✅ 打包完成"
echo "========================================"
echo ""
echo "📁 输出位置: dist/BOSS直聘自动化系统"
echo ""
echo "📦 分发方式:"
echo "   1. 将 dist/ 目录压缩为 zip"
echo "   2. 用户下载后解压"
echo "   3. 双击运行 'BOSS直聘自动化系统'"
echo ""
