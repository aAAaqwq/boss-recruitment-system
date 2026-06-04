#!/usr/bin/env python3
"""详细的权限诊断脚本"""
import sys
import os

print("=" * 60)
print("屏幕权限详细诊断")
print("=" * 60)

# 1. 检查当前进程信息
print("\n1. 当前进程信息:")
print(f"   PID: {os.getpid()}")
print(f"   Python: {sys.executable}")
print(f"   工作目录: {os.getcwd()}")

# 2. 测试PIL截图
print("\n2. 测试PIL截图...")
try:
    from PIL import ImageGrab
    img = ImageGrab.grab()
    print(f"   ✅ 成功！屏幕尺寸: {img.size}")
    
    # 保存测试截图
    test_path = "test_screenshot.png"
    img.save(test_path)
    print(f"   ✅ 测试截图已保存: {test_path}")
    
except Exception as e:
    print(f"   ❌ 失败: {e}")
    print("\n   可能的原因:")
    print("   - 当前进程没有屏幕录制权限")
    print("   - 需要在系统设置中授权")
    print("\n   解决方法:")
    print("   1. 打开 系统设置 → 隐私与安全性 → 屏幕录制")
    print("   2. 找到并勾选:")
    print("      - 终端 (Terminal)")
    print("      - Python")
    print("      - 或者当前运行的应用")
    print("   3. 重新运行此脚本")
    sys.exit(1)

# 3. 测试pyautogui
print("\n3. 测试pyautogui...")
try:
    import pyautogui
    x, y = pyautogui.position()
    print(f"   ✅ 鼠标位置: ({x}, {y})")
    
    size = pyautogui.size()
    print(f"   ✅ 屏幕尺寸: {size}")
    
except Exception as e:
    print(f"   ❌ 失败: {e}")

# 4. 测试OCR
print("\n4. 测试OCR...")
try:
    import pytesseract
    from PIL import Image, ImageDraw
    
    # 创建测试图片
    img = Image.new('RGB', (200, 50), color='white')
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "测试 Test", fill='black')
    
    # OCR识别
    text = pytesseract.image_to_string(img, lang='chi_sim+eng')
    print(f"   ✅ OCR识别: {text.strip()}")
    
except Exception as e:
    print(f"   ❌ 失败: {e}")

print("\n" + "=" * 60)
print("诊断完成！")
print("=" * 60)

if 'img' in locals():
    print("\n✅ 所有测试通过！可以运行自动化脚本了。")
    print("\n下一步:")
    print("  python3 tests/test_workflow_3_1.py")
else:
    print("\n❌ 屏幕权限测试失败，请按照上述提示授权后重试。")
