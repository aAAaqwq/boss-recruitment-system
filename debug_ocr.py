#!/usr/bin/env python3
"""调试脚本 - 查看屏幕OCR结果"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.vision import screen_ocr
from PIL import Image

print("=" * 60)
print("屏幕OCR调试")
print("=" * 60)

# 1. 截取左侧导航栏区域
print("\n1. 扫描左侧导航栏...")
result = screen_ocr(
    region=(0, 80, 230, 460),
    lang="chi_sim+eng",
    min_confidence=20.0,
    scale=3,
    preprocess=True
)

print(f"\n识别到的文字:")
for i, box in enumerate(result["boxes"][:20]):  # 只显示前20个
    print(f"  {i+1}. {box.text} (置信度: {box.confidence:.1f}, 位置: {box.center_x}, {box.center_y})")

print(f"\n完整文本:\n{result['full_text']}")

# 2. 保存截图
if result.get("screenshot"):
    screenshot_path = "debug_left_sidebar.png"
    result["screenshot"].save(screenshot_path)
    print(f"\n✅ 截图已保存: {screenshot_path}")
    print("   请查看截图，确认是否包含'推荐牛人'按钮")

# 3. 查找"推荐牛人"
print("\n" + "=" * 60)
print("查找'推荐牛人'按钮")
print("=" * 60)

keywords = ["推荐", "牛人", "推荐牛人", "沟通", "职位"]
found = []

for box in result["boxes"]:
    for keyword in keywords:
        if keyword in box.text:
            found.append(box)
            print(f"✅ 找到: {box.text} (位置: {box.center_x}, {box.center_y})")

if not found:
    print("❌ 未找到相关按钮")
    print("\n可能的原因:")
    print("  1. BOSS直聘页面不在正确的位置")
    print("  2. 页面布局发生了变化")
    print("  3. OCR识别区域需要调整")
    print("\n建议:")
    print("  1. 确保BOSS直聘聊天页面在最前台")
    print("  2. 查看 debug_left_sidebar.png 确认截图内容")
    print("  3. 如果截图正确但识别不到，可能需要调整OCR参数")

print("\n" + "=" * 60)
