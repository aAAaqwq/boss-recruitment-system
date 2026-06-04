#!/usr/bin/env python3
"""诊断脚本 v2 - 先激活Chrome再截图分析"""
import sys, os, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import ImageGrab, Image
import cv2
import numpy as np
import pyautogui

# 1. 激活Chrome到前台
print("激活Chrome浏览器...")
subprocess.run(["osascript", "-e", 'tell application "Google Chrome" to activate'])
time.sleep(1.5)

screen_width, screen_height = pyautogui.size()
print(f"屏幕: {screen_width}x{screen_height}")

# 2. 截取右半屏（筛选面板区域）
filter_region = (screen_width//2, 100, screen_width//2, 800)
x, y, width, height = filter_region

screenshot = ImageGrab.grab(bbox=(x, y, x + width, y + height))
screenshot.save("/tmp/boss_filter_panel.png")
print(f"✅ 截图保存: /tmp/boss_filter_panel.png ({width}x{height})")

img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

# 3. 检测绿色
print("\n=== 颜色分析 ===")

ranges = [
    ("宽绿 H:30-90 S:30+ V:60+", (30, 30, 60), (90, 255, 255)),
    ("亮绿 H:35-85 S:50+ V:100+", (35, 50, 100), (85, 255, 255)),
    ("全绿 H:25-95 S:20+ V:40+", (25, 20, 40), (95, 255, 255)),
    ("浅绿 H:35-80 S:10+ V:150+", (35, 10, 150), (80, 255, 255)),
    ("深绿 H:35-85 S:40+ V:40+", (35, 40, 40), (85, 255, 200)),
]

for name, lower, upper in ranges:
    mask = cv2.inRange(hsv, np.array(lower), np.array(upper))
    pixels = cv2.countNonZero(mask)
    
    if pixels > 100:
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        valid = [c for c in contours if cv2.contourArea(c) > 300]
        
        print(f"\n  {name}: {pixels}px → {len(valid)}个区域")
        valid.sort(key=cv2.contourArea, reverse=True)
        for i, cnt in enumerate(valid[:5]):
            bx, by, bw, bh = cv2.boundingRect(cnt)
            area = cv2.contourArea(cnt)
            aspect = bw / max(bh, 1)
            print(f"    #{i+1}: pos=({bx},{by}) size={bw}x{bh} area={area:.0f} ratio={aspect:.1f}")
            
            roi = img[by:by+bh, bx:bx+bw]
            cv2.imwrite(f"/tmp/boss_green_{name[:4]}_{i+1}.png", roi)
            
            roi_pil = Image.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
            roi_scaled = roi_pil.resize((roi_pil.width * 4, roi_pil.height * 4), Image.LANCZOS)
            
            import pytesseract
            text = pytesseract.image_to_string(roi_scaled, lang="chi_sim+eng").strip()
            print(f"    OCR: '{text}'")
    else:
        print(f"  {name}: {pixels}px → 无")

# 4. 全图OCR
print("\n=== 直接OCR ===")
import pytesseract
scaled = screenshot.resize((screenshot.width * 3, screenshot.height * 3), Image.LANCZOS)
data = pytesseract.image_to_data(scaled, lang="chi_sim+eng", output_type=pytesseract.Output.DICT)
for i in range(len(data['text'])):
    t = data['text'][i].strip()
    c = float(data['conf'][i])
    if t and c > 30:
        sx = data['left'][i] // 3 + x
        sy = data['top'][i] // 3 + y
        print(f"  [{c:5.1f}%] ({sx:4d}, {sy:4d}) {t}")

print("\n✅ 诊断完成")
