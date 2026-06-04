"""屏幕控制模块"""
import pyautogui
import subprocess
import time
import random
from typing import Tuple


# 设置PyAutoGUI安全参数
pyautogui.PAUSE = 0.1
pyautogui.FAILSAFE = True  # 鼠标移到左上角可紧急停止


def activate_chrome():
    """激活Chrome浏览器"""
    try:
        subprocess.run([
            "osascript", "-e",
            'tell application "Google Chrome" to activate'
        ], check=False)
        time.sleep(0.6)
        return True
    except Exception:
        return False


def move_and_click(x: int, y: int, duration: float = 0.15):
    """移动鼠标并点击"""
    pyautogui.moveTo(x, y, duration=duration)
    pyautogui.click(x, y)
    time.sleep(random.uniform(0.3, 0.5))


def type_text(text: str, interval: float = 0.015):
    """输入文字"""
    pyautogui.write(text, interval=interval)


def press_hotkey(*keys):
    """按热键"""
    pyautogui.hotkey(*keys)


def screenshot(region: Tuple[int, int, int, int] = None, save_path: str = None):
    """截图"""
    if region:
        x, y, width, height = region
        img = pyautogui.screenshot(region=(x, y, width, height))
    else:
        img = pyautogui.screenshot()
    
    if save_path:
        img.save(save_path)
    
    return img


def get_mouse_position() -> Tuple[int, int]:
    """获取鼠标位置"""
    return pyautogui.position()


def scroll(clicks: int, x: int = None, y: int = None):
    """滚动"""
    if x and y:
        pyautogui.moveTo(x, y)
    pyautogui.scroll(clicks)
