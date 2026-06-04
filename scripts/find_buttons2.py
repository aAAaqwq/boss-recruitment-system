"""Find bottom bar buttons after clicking a candidate"""
import sys
sys.path.insert(0, '.')
from app.vision import screen_ocr
from app.screen import activate_chrome, move_and_click
import time, pyautogui

activate_chrome()
time.sleep(1)

# Click a candidate (slot 1)
move_and_click(528, 372)
time.sleep(2)

# Now scan the bottom bar
for name, region in [
    ("bottom_wide", (400, 780, 500, 100)),
    ("bottom_narrow", (500, 800, 350, 50)),
    ("send_area", (700, 780, 200, 100)),
    ("full_bottom", (400, 750, 600, 150)),
]:
    r = screen_ocr(region, min_confidence=10.0, scale=3, preprocess=True)
    print(f"\n=== {name} {region} ===")
    for b in sorted(r.get("boxes", []), key=lambda x: (x.center_x, x.center_y)):
        print(f"  '{b.text}' @ ({b.center_x}, {b.center_y}) conf={b.confidence}")
