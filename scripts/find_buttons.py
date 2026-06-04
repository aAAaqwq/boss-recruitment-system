"""Find the exact positions of bottom bar buttons"""
import sys
sys.path.insert(0, '.')
from app.vision import screen_ocr
from app.screen import activate_chrome

activate_chrome()
import time, pyautogui
time.sleep(1)

# Scan the bottom bar area
r = screen_ocr((400, 780, 450, 50), min_confidence=10.0, scale=3, preprocess=True)
print("=== Bottom bar (400,780,450,50) ===")
for b in r.get("boxes", []):
    print(f"  '{b.text}' @ ({b.center_x}, {b.center_y}) conf={b.confidence}")

# Scan the whole right area to find all buttons
r2 = screen_ocr((400, 750, 500, 120), min_confidence=10.0, scale=3, preprocess=True)
print("\n=== Full bottom area (400,750,500,120) ===")
for b in sorted(r2.get("boxes", []), key=lambda x: (x.center_y, x.center_x)):
    print(f"  '{b.text}' @ ({b.center_x}, {b.center_y}) conf={b.confidence}")
