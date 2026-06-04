#!/usr/bin/env python3
"""调试筛选按钮位置"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from app.vision import screen_ocr
import pyautogui

print("=" * 60)
print("筛选按钮调试")
print("=" * 60)

screen_width, screen_height = pyautogui.size()
print(f"\n屏幕尺寸: {screen_width} x {screen_height}")

# 扫描整个屏幕上半部分（降低置信度）
print("\n扫描整个屏幕上半部分...")
result = screen_ocr(region=(0, 0, screen_width, screen_height // 2), min_confidence=40.0)

print(f"\n识别到 {len(result['boxes'])} 个文本框")
print("\n所有识别到的文字（按位置排序）:")

# 按Y坐标排序
sorted_boxes = sorted(result["boxes"], key=lambda b: (b.center_y, b.center_x))

for i, box in enumerate(sorted_boxes[:50], 1):
    print(f"{i:2d}. {box.text:20s} (置信度: {box.confidence:.1f}, 位置: {box.center_x:4d}, {box.center_y:4d})")

# 特别查找包含"筛"或"选"的文字
print("\n" + "=" * 60)
print("查找包含'筛'或'选'的文字:")
print("=" * 60)

found = False
for box in result["boxes"]:
    if "筛" in box.text or "选" in box.text:
        print(f"✅ 找到: {box.text} (置信度: {box.confidence:.1f}, 位置: {box.center_x}, {box.center_y})")
        found = True

if not found:
    print("❌ 未找到包含'筛'或'选'的文字")
    print("\n建议:")
    print("1. 确认BOSS直聘页面已打开")
    print("2. 确认在'推荐牛人'页面")
    print("3. 确认右上角有'筛选'按钮")
    print("4. 尝试放大浏览器窗口")

print("\n" + "=" * 60)
