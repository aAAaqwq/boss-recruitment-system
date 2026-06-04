"""xdotool X11 自动化辅助模块 — Docker 容器内使用"""
import asyncio
import os
import subprocess
from typing import Tuple

# X11 显示环境
_DISPLAY = os.environ.get("DISPLAY", ":1")


async def mousemove(x: int, y: int, sync: bool = True) -> None:
    """移动鼠标到绝对坐标"""
    cmd = ["xdotool", "mousemove"]
    if sync:
        cmd.append("--sync")
    cmd.extend([str(x), str(y)])
    await _run(cmd)


async def click(button: int = 1) -> None:
    """点击鼠标按钮 (1=左, 2=中, 3=右, 4=上滚, 5=下滚)"""
    await _run(["xdotool", "click", str(button)])


async def type_text(text: str, delay: int = 80) -> None:
    """输入文本（支持 UTF-8/中文）"""
    await _run(["xdotool", "type", "--delay", str(delay), text])


async def press_key(key: str) -> None:
    """按键 (如 Return, Escape, Tab, ctrl+a, ctrl+c)"""
    await _run(["xdotool", "key", key])


async def get_mouse_location() -> Tuple[int, int]:
    """获取当前鼠标位置"""
    result = await _run(["xdotool", "getmouselocation"])
    # 输出格式: x:450 y:320 screen:0 window:12345
    parts = result.strip().split()
    x = int(parts[0].split(":")[1])
    y = int(parts[1].split(":")[1])
    return (x, y)


async def scroll_up(clicks: int = 3) -> None:
    """向上滚动"""
    await _run(["xdotool", "click", "--repeat", str(clicks), "--delay", "50", "4"])


async def scroll_down(clicks: int = 3) -> None:
    """向下滚动"""
    await _run(["xdotool", "click", "--repeat", str(clicks), "--delay", "50", "5"])


async def _run(cmd: list) -> str:
    """执行命令，返回 stdout"""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            env={**os.environ, "DISPLAY": _DISPLAY}
        )
    )
    if result.returncode != 0:
        raise RuntimeError(f"xdotool error: {result.stderr.strip()}")
    return result.stdout
