#!/usr/bin/env python3
"""屏幕权限检查和引导脚本"""
import subprocess
import sys

print("=" * 60)
print("BOSS招聘自动化系统 - 屏幕权限检查")
print("=" * 60)

print("\n正在检查屏幕录制权限...")

try:
    from PIL import ImageGrab
    img = ImageGrab.grab()
    print("✅ 屏幕录制权限已授权！")
    print(f"   屏幕尺寸: {img.size}")
    sys.exit(0)
except Exception as e:
    print("❌ 屏幕录制权限未授权")
    print(f"   错误: {e}")

print("\n" + "=" * 60)
print("如何授权屏幕录制权限")
print("=" * 60)

print("\n方法1: 通过系统设置授权（推荐）")
print("------")
print("1. 打开 系统设置")
print("2. 点击 隐私与安全性")
print("3. 点击 屏幕录制")
print("4. 点击左下角的锁图标解锁")
print("5. 找到并勾选:")
print("   - 终端 (Terminal)")
print("   - Python")
print("   - 或者运行此脚本的应用")
print("6. 重启终端")

print("\n方法2: 通过命令行打开系统设置")
print("------")
print("运行以下命令打开屏幕录制设置:")
print("  open 'x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture'")

print("\n" + "=" * 60)
print("授权后请重新运行此脚本验证")
print("=" * 60)

# 尝试打开系统设置
print("\n是否现在打开系统设置？(y/n): ", end="")
try:
    choice = input().strip().lower()
    if choice == 'y':
        subprocess.run([
            "open",
            "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
        ])
        print("\n✅ 已打开系统设置，请按照上述步骤授权")
        print("   授权后请重启终端，然后重新运行此脚本")
except:
    pass
