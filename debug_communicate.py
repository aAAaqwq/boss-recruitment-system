#!/usr/bin/env python3
"""诊断：看BOSS沟通页面的Vision OCR结果"""
import subprocess, time
subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'])
time.sleep(1.5)

from PIL import ImageGrab
import pyautogui

screen_width, screen_height = pyautogui.size()

# 截全屏
full = ImageGrab.grab()
full.save("/tmp/boss_full.png")
print(f"全屏截图: {full.size}")

# 截左侧消息列表
left = full.crop((0, 80, 500, screen_height))
left.save("/tmp/boss_left.png")
print(f"左侧区域: {left.size}")

# 用Vision OCR识别
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.vision import _vision_ocr

print("\n=== 左侧消息列表 Vision OCR ===")
boxes = _vision_ocr(left, region_offset=(0, 80))
for b in sorted(boxes, key=lambda x: x.center_y):
    if b.confidence >= 30:
        print(f"  [{b.confidence:5.1f}%] ({b.center_x:4d}, {b.center_y:4d}) {b.text}")

# 截中间聊天区域
mid = full.crop((500, 80, screen_width-100, screen_height))
mid.save("/tmp/boss_mid.png")
print(f"\n中间聊天区域: {mid.size}")

print("\n=== 中间聊天区域 Vision OCR ===")
boxes2 = _vision_ocr(mid, region_offset=(500, 80))
for b in sorted(boxes2, key=lambda x: x.center_y):
    if b.confidence >= 30:
        print(f"  [{b.confidence:5.1f}%] ({b.center_x:4d}, {b.center_y:4d}) {b.text}")

print("\n✅ 诊断完成")
