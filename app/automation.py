"""浏览器自动化核心模块 — nodriver DOM定位 + xdotool 仿真鼠标"""
import asyncio
import random
import subprocess
import os
from typing import Optional, Dict, Tuple, List
from pathlib import Path

from app.logging_config import logger

try:
    import nodriver as uc
except ImportError:
    uc = None  # 允许在非 Docker 环境导入


class BrowserAutomation:
    """浏览器自动化控制器

    设计原则：
    - nodriver 负责 DOM 定位（精确到像素）
    - xdotool 负责系统级鼠标/键盘操作（VNC 可见）
    - 贝塞尔曲线模拟人类鼠标轨迹
    """

    def __init__(self):
        self.browser = None
        self.page = None
        self._connected = False
        self._lock = asyncio.Lock()
        self._display = os.environ.get("DISPLAY", ":1")

    # ===== nodriver 层 =====

    async def connect(self, port: int = 9222) -> Dict:
        """连接到已运行的 Chrome（通过 CDP 端口 9222）"""
        async with self._lock:
            try:
                if self._connected and self.browser:
                    return {"status": "already_connected"}

                if uc is None:
                    return {"status": "error", "message": "nodriver 未安装"}

                self.browser = await uc.start(
                    browser_args=[
                        f'--remote-debugging-port={port}',
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                    ]
                )
                self.page = self.browser.main_tab
                self._connected = True
                logger.info("已连接到 Chrome CDP")
                return {"status": "connected"}
            except Exception as e:
                logger.error(f"连接 Chrome 失败: {e}")
                return {"status": "error", "message": str(e)}

    async def disconnect(self) -> Dict:
        """断开浏览器连接"""
        async with self._lock:
            if not self._connected:
                return {"status": "already_disconnected"}
            try:
                # nodriver 的 browser 关闭
                if self.browser:
                    self.browser.stop()
                self.browser = None
                self.page = None
                self._connected = False
                logger.info("已断开浏览器连接")
                return {"status": "disconnected"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    async def navigate(self, url: str) -> Dict:
        """导航到指定 URL"""
        if not self._connected or not self.page:
            return {"status": "error", "message": "浏览器未连接"}
        try:
            await self.page.get(url)
            title = await self.page.evaluate("document.title")
            current_url = await self.page.evaluate("window.location.href")
            return {"status": "ok", "title": title, "url": current_url}
        except Exception as e:
            logger.error(f"导航失败: {e}")
            return {"status": "error", "message": str(e)}

    async def find_element(self, selector: str, timeout: int = 10) -> Optional[object]:
        """查找单个元素（CSS 选择器）"""
        if not self._connected or not self.page:
            return None
        try:
            return await self.page.select(selector, timeout=timeout)
        except Exception:
            return None

    async def find_all(self, selector: str) -> List[object]:
        """查找所有匹配元素"""
        if not self._connected or not self.page:
            return []
        try:
            return await self.page.select_all(selector)
        except Exception:
            return []

    async def get_bounding_box(self, selector: str, timeout: int = 10) -> Optional[Dict]:
        """获取元素的边界框（viewport 坐标）"""
        element = await self.find_element(selector, timeout=timeout)
        if not element:
            return None
        try:
            box = await element.bounding_box()
            if box:
                return {
                    "x": box.x,
                    "y": box.y,
                    "width": box.width,
                    "height": box.height,
                    "center_x": box.x + box.width / 2,
                    "center_y": box.y + box.height / 2,
                }
            return None
        except Exception:
            return None

    async def screenshot(self, path: str = None) -> Dict:
        """截图"""
        if not self._connected or not self.page:
            return {"status": "error", "message": "浏览器未连接"}
        try:
            save_path = path or f"/tmp/screenshot_{int(asyncio.get_event_loop().time())}.png"
            await self.page.screenshot(path=save_path)
            return {"status": "ok", "path": save_path}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def execute_js(self, script: str):
        """执行 JavaScript"""
        if not self._connected or not self.page:
            return None
        try:
            return await self.page.evaluate(script)
        except Exception as e:
            logger.error(f"JS 执行失败: {e}")
            return None

    async def check_login(self) -> Dict:
        """检测 BOSS直聘登录状态"""
        if not self._connected or not self.page:
            return {"logged_in": False, "message": "浏览器未连接"}
        try:
            # 尝试多种选择器判断登录状态
            user_el = await self.page.select(
                '.user-info, .nav-figure, .user-nav, [class*="avatar"], .mini-user',
                timeout=3
            )
            if user_el:
                return {"logged_in": True, "message": "已登录"}
            login_btn = await self.page.select(
                '.btn-signin, .login-btn, [class*="sign-in"], .tosign-login',
                timeout=3
            )
            if login_btn:
                return {"logged_in": False, "message": "请在 VNC 中扫码登录"}
            return {"logged_in": False, "message": "无法确定登录状态"}
        except Exception as e:
            return {"logged_in": False, "message": str(e)}

    def get_status(self) -> Dict:
        """获取当前状态"""
        if not self._connected:
            return {"status": "disconnected", "connected": False}
        try:
            return {
                "status": "connected",
                "connected": True,
            }
        except Exception:
            return {"status": "error", "connected": False}

    # ===== 贝塞尔曲线 + xdotool 层 =====

    @staticmethod
    def _de_casteljau(points: List[Tuple[float, float]], t: float) -> Tuple[float, float]:
        """De Casteljau 算法 — 递归求贝塞尔曲线上的点"""
        if len(points) == 1:
            return points[0]
        new_points = []
        for i in range(len(points) - 1):
            x = points[i][0] * (1 - t) + points[i + 1][0] * t
            y = points[i][1] * (1 - t) + points[i + 1][1] * t
            new_points.append((x, y))
        return BrowserAutomation._de_casteljau(new_points, t)

    @staticmethod
    def _generate_bezier_path(
        start: Tuple[int, int],
        end: Tuple[int, int],
        num_points: int = 30,
    ) -> List[Tuple[int, int]]:
        """生成贝塞尔曲线路径

        Args:
            start: 起始坐标 (x, y)
            end: 目标坐标 (x, y)
            num_points: 采样点数 (20-40)

        Returns:
            路径点列表 [(x, y), ...]
        """
        # 生成 3-5 个随机控制点
        num_controls = random.randint(3, 5)
        controls = [start]
        for i in range(1, num_controls + 1):
            t = i / (num_controls + 1)
            # 线性插值 + 随机垂直偏移
            x = start[0] + (end[0] - start[0]) * t + random.uniform(-30, 30)
            y = start[1] + (end[1] - start[1]) * t + random.uniform(-20, 20)
            controls.append((x, y))
        controls.append(end)

        # 沿曲线采样
        path = []
        steps = random.randint(max(20, num_points - 10), min(40, num_points + 10))
        for i in range(steps + 1):
            t = i / steps
            # Smoothstep 缓动: 慢→快→慢
            t_eased = t * t * (3 - 2 * t)
            x, y = BrowserAutomation._de_casteljau(controls, t_eased)
            path.append((int(x), int(y)))

        return path

    async def move_mouse(self, x: int, y: int) -> None:
        """仿真人类鼠标移动（贝塞尔曲线 + xdotool）"""
        # 获取当前鼠标位置
        result = subprocess.run(
            ["xdotool", "getmouselocation"],
            capture_output=True, text=True, timeout=5,
            env={**os.environ, "DISPLAY": self._display}
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            current_x = int(parts[0].split(":")[1])
            current_y = int(parts[1].split(":")[1])
        else:
            current_x, current_y = 0, 0

        # 生成贝塞尔路径
        path = self._generate_bezier_path((current_x, current_y), (x, y))

        # 沿路径移动
        for px, py in path:
            subprocess.run(
                ["xdotool", "mousemove", "--sync", str(px), str(py)],
                env={**os.environ, "DISPLAY": self._display},
                timeout=5
            )
            # 随机延迟 10-30ms
            await asyncio.sleep(random.uniform(0.01, 0.03))

    async def click(self, x: int = None, y: int = None) -> None:
        """仿真人类点击"""
        if x is not None and y is not None:
            # 添加随机偏移（避免每次点同一像素）
            target_x = x + int(random.uniform(-5, 5))
            target_y = y + int(random.uniform(-5, 5))
            await self.move_mouse(target_x, target_y)
        subprocess.run(
            ["xdotool", "click", "1"],
            env={**os.environ, "DISPLAY": self._display},
            timeout=5
        )
        # 随机等待（模拟人类反应时间）
        await asyncio.sleep(random.uniform(0.2, 0.6))

    async def type_text(self, text: str, delay: int = 80) -> None:
        """仿真人类输入文本"""
        actual_delay = delay + random.randint(-20, 20)
        subprocess.run(
            ["xdotool", "type", "--delay", str(max(30, actual_delay)), text],
            env={**os.environ, "DISPLAY": self._display},
            timeout=30
        )
        await asyncio.sleep(random.uniform(0.1, 0.3))

    async def press_key(self, key: str) -> None:
        """按键"""
        subprocess.run(
            ["xdotool", "key", key],
            env={**os.environ, "DISPLAY": self._display},
            timeout=5
        )
        await asyncio.sleep(random.uniform(0.1, 0.3))

    async def scroll(self, direction: str = "down", amount: int = 3) -> None:
        """滚动"""
        button = "5" if direction == "down" else "4"
        subprocess.run(
            ["xdotool", "click", "--repeat", str(amount), "--delay", "50", button],
            env={**os.environ, "DISPLAY": self._display},
            timeout=10
        )
        await asyncio.sleep(random.uniform(0.3, 0.8))

    # ===== 复合操作 =====

    async def click_element(self, selector: str, timeout: int = 10) -> bool:
        """点击指定元素（nodriver 定位 + xdotool 点击）"""
        box = await self.get_bounding_box(selector, timeout=timeout)
        if not box:
            logger.warning(f"元素未找到: {selector}")
            return False
        await self.click(int(box["center_x"]), int(box["center_y"]))
        return True

    async def type_into_element(self, selector: str, text: str) -> bool:
        """点击元素并输入文本"""
        if not await self.click_element(selector):
            return False
        await asyncio.sleep(random.uniform(0.3, 0.6))
        await self.type_text(text)
        return True


# 全局单例
automation = BrowserAutomation()
