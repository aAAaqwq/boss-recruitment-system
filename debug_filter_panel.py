#!/usr/bin/env python3
"""
调试OCR识别结果 - 查看筛选面板的完整识别内容
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.screen import activate_chrome
from app.vision import screen_ocr
import pyautogui
import time


def main():
    print("="*60)
    print("OCR调试工具 - 筛选面板识别")
    print("="*60)
    
    # 激活Chrome
    print("\n🚀 激活Chrome浏览器...")
    activate_chrome()
    time.sleep(1)
    
    # 获取屏幕尺寸
    screen_width, screen_height = pyautogui.size()
    print(f"📐 屏幕尺寸: {screen_width}x{screen_height}")
    
    # 请用户打开筛选面板
    print("\n💡 请手动打开BOSS直聘的筛选面板，然后按回车...")
    input("按回车继续...")
    
    # 扫描右侧区域（筛选面板）
    print("\n🔍 扫描屏幕右侧区域...")
    filter_region = (screen_width*2//3, 150, screen_width//3, 700)
    print(f"   区域: x={filter_region[0]}, y={filter_region[1]}, w={filter_region[2]}, h={filter_region[3]}")
    
    result = screen_ocr(
        region=filter_region,
        min_confidence=10.0,  # 超低置信度，看所有识别结果
        scale=3,
        preprocess=True
    )
    
    print(f"\n✅ 识别到 {len(result['boxes'])} 个文本框")
    print("\n" + "="*60)
    print("所有识别结果（按Y坐标排序）:")
    print("="*60)
    
    # 按Y坐标排序
    boxes = sorted(result["boxes"], key=lambda b: b.center_y)
    
    for i, box in enumerate(boxes):
        print(f"\n[{i+1}] 文字: '{box.text}'")
        print(f"    置信度: {box.confidence:.1f}%")
        print(f"    位置: ({box.center_x}, {box.center_y})")
        print(f"    大小: {box.width}x{box.height}")
    
    print("\n" + "="*60)
    print("完整文本:")
    print("="*60)
    print(result['full_text'])
    
    print("\n" + "="*60)
    print("查找关键词:")
    print("="*60)
    
    keywords = ["985", "211", "本科", "硕士", "博士", "3年", "5年", "名校", "学历", "工作年限"]
    for keyword in keywords:
        found = [box for box in boxes if keyword in box.text]
        if found:
            print(f"✅ 找到 '{keyword}': {len(found)} 个")
            for box in found:
                print(f"   - '{box.text}' at ({box.center_x}, {box.center_y})")
        else:
            print(f"❌ 未找到 '{keyword}'")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
    except Exception as e:
        print(f"\n\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
