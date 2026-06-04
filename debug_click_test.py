#!/usr/bin/env python3
"""诊断v2: 点击联系人前先截图确认位置"""
import subprocess, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.vision import screen_ocr
import pyautogui
from PIL import ImageGrab

subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'])
time.sleep(1.5)

screen_width, screen_height = pyautogui.size()
print(f"屏幕: {screen_width}x{screen_height}")

# 截全屏保存
full = ImageGrab.grab()
full.save("/tmp/boss_communicate_debug.png")
print("全屏截图已保存")

# OCR消息列表找联系人
msg_region = (500, 280, 350, 700)
result = screen_ocr(msg_region, min_confidence=30)

print("\n=== 消息列表中的联系人 ===")
contacts = []
for box in sorted(result["boxes"], key=lambda b: b.center_y):
    if "实习生" in box.text or "运营" in box.text:
        name = box.text.split("ai")[0].split("AI")[0].split("运")[0].strip()
        if name and len(name) >= 2 and not any(abs(box.center_y - c[1]) < 30 for c in contacts):
            contacts.append((name, box.center_y, box.center_x))
            print(f"  {name}: 点击坐标=({box.center_x}, {box.center_y})")

if not contacts:
    print("  未找到联系人")
    sys.exit(0)

# 点击第一个联系人
name, cy, cx = contacts[0]
print(f"\n点击第一个联系人: {name} at ({cx}, {cy})")

# 先移动鼠标到位置，等1秒让你确认
pyautogui.moveTo(cx, cy, duration=0.3)
print("鼠标已移到目标位置，确认是否正确...")
time.sleep(2)

# 截图确认鼠标位置
img = ImageGrab.grab()
img.save("/tmp/boss_before_click.png")
print("点击前截图已保存到 /tmp/boss_before_click.png")

# 点击
pyautogui.click()
time.sleep(2)

# 截图看点击后效果
img2 = ImageGrab.grab()
img2.save("/tmp/boss_after_click.png")
print("点击后截图已保存到 /tmp/boss_after_click.png")

# OCR右侧面板
print("\n=== 点击后右侧面板OCR ===")
right_region = (850, 200, screen_width - 870, screen_height - 200)
result2 = screen_ocr(right_region, min_confidence=20)
for box in sorted(result2["boxes"], key=lambda b: b.center_y):
    if box.confidence >= 20:
        print(f"  [{box.confidence:.0f}%] ({box.center_x},{box.center_y}) {box.text}")
