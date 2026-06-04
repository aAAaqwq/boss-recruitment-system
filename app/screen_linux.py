"""屏幕操作模块 - Linux Docker版
使用 nodriver 控制 Chrome，浏览器可见（非headless）
"""
import asyncio
import os
import time
import subprocess
from typing import Optional

# nodriver
import nodriver as uc

# 全局浏览器实例
_BROWSER = None
_TAB = None


def get_chrome_path() -> str:
    """获取 Chrome 路径"""
    for path in ["/usr/bin/chromium-browser",
                  "/usr/bin/chromium",
                  "/usr/bin/chrome",
                  "/usr/bin/google-chrome"]:
        if os.path.exists(path):
            return path
    return "/usr/bin/chromium-browser"


def activate_chrome():
    """激活 Chrome（nodriver 模式）"""
    global _BROWSER, _TAB

    if _BROWSER is not None:
        return _BROWSER, _TAB

    # 使用 nodriver 启动 Chrome
    chrome_path = get_chrome_path()

    # 启动浏览器（nodriver 新版是异步接口）
    _BROWSER = asyncio.run(uc.start(
        browser_args=["--no-sandbox", "--disable-dev-shm-usage"],
        headless=False
    ))

    # 获取标签页
    _TAB = _BROWSER.main_tab

    return _BROWSER, _TAB


def move_and_click(x: int, y: int, duration: float = 0.5):
    """移动鼠标并点击"""
    import pyautogui
    pyautogui.moveTo(x, y, duration=duration)
    time.sleep(0.1)
    pyautogui.click()
    time.sleep(0.2)


def scroll_down(amount: int = 3):
    """向下滚动"""
    import pyautogui
    pyautogui.scroll(-amount * 100)
    time.sleep(0.3)


def scroll_up(amount: int = 3):
    """向上滚动"""
    import pyautogui
    pyautogui.scroll(amount * 100)
    time.sleep(0.3)


if __name__ == "__main__":
    print("Screen module for Linux Docker")
