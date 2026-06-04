"""Find the actual bottom toolbar buttons"""
import sys; sys.path.insert(0, '.')
from app.vision import screen_ocr
from app.screen import activate_chrome
import time, pyautogui

activate_chrome(); time.sleep(0.5)

# Scan bottom toolbar - it's at the very bottom of chat panel
# The chat panel starts at x≈430-width, so toolbar is at x≈430+
# and y is near the bottom of screen
sw, sh = pyautogui.size()
print(f"Screen: {sw}x{sh}")

# Scan near the input area
for name, region in [
    ("very_bottom", (400, sh-120, 500, 120)),
    ("toolbar_right", (600, sh-100, 400, 100)),
    ("chat_bottom", (400, sh-200, 800, 200)),
]:
    r = screen_ocr(region, min_confidence=8.0, scale=3, preprocess=True)
    print(f"\n=== {name} {region} ===")
    for b in sorted(r.get("boxes", []), key=lambda x: (x.center_x, x.center_y)):
        print(f"  '{b.text}' @ ({b.center_x}, {b.center_y}) conf={b.confidence}")
