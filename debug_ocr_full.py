#!/usr/bin/env python3
"""
调试工具：显示筛选面板OCR识别的所有文字
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.vision import screen_ocr
import pyautogui
import time

def main():
    screen_width, screen_height = pyautogui.size()
    
    # 扫描筛选面板 - 屏幕右侧
    filter_region = (screen_width//2, 100, screen_width//2, 800)
    
    print(f"🔍 扫描区域: x={filter_region[0]}, y={filter_region[1]}, w={filter_region[2]}, h={filter_region[3]}")
    print("⏳ 开始OCR识别（超高清模式）...\n")
    
    result = screen_ocr(
        region=filter_region,
        min_confidence=5.0,
        scale=5,
        preprocess=True
    )
    
    print(f"✅ 识别到 {len(result['boxes'])} 个文本框\n")
    print("=" * 80)
    
    # 按Y坐标排序
    boxes = sorted(result["boxes"], key=lambda b: b.center_y)
    
    for i, box in enumerate(boxes, 1):
        print(f"{i:3d}. [{box.center_x:4d}, {box.center_y:4d}] 置信度:{box.confidence:5.1f}% | {box.text}")
    
    print("\n" + "=" * 80)
    print(f"\n完整文本:\n{result['full_text']}")

if __name__ == "__main__":
    main()
