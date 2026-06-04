"""Debug: scan multiple regions to find where candidate info actually is"""
import sys
sys.path.insert(0, '.')
from app.vision import screen_ocr
from app.screen import activate_chrome

activate_chrome()
import time
time.sleep(1)

# Click on a candidate first
import pyautogui
pyautogui.moveTo(528, 451, duration=0.15)
pyautogui.click()
time.sleep(2)

# Scan multiple regions to find candidate info
regions = [
    ("right_top_wide", 420, 120, 400, 500),
    ("right_top_narrow", 430, 130, 350, 400),
    ("right_mid", 420, 200, 400, 300),
    ("right_bottom", 420, 400, 400, 300),
    ("far_right_top", 1200, 100, 500, 300),
    ("center_top", 400, 100, 600, 200),
]

for name, x, y, w, h in regions:
    r = screen_ocr(region=(x, y, w, h), min_confidence=15.0, scale=3, preprocess=True)
    boxes = r.get("boxes", [])
    text = " ".join(b.text for b in boxes)
    print(f"\n=== {name} ({x},{y},{w},{h}) — {len(boxes)} boxes ===")
    print(f"  Text: {text[:300]}")
