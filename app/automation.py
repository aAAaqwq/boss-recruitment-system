"""浏览器自动化核心模块 — nodriver DOM定位 + xdotool 仿真鼠标"""
import asyncio
import json
import random
import subprocess
import os
from typing import Optional, Dict, Tuple, List
from pathlib import Path
from datetime import datetime

from app.logging_config import logger

COOKIE_FILE = Path(os.environ.get("DATA_DIR", "/app/data")) / "cookies.json"

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

    # ===== 会话健康检查 =====

    async def _ensure_session(self) -> bool:
        """确保CDP session有效，失效则自动重连。

        Returns:
            True 表示session可用，False 表示不可用且重连失败。
        """
        if not self._connected or not self.page:
            return False
        try:
            # 轻量探测：执行一个无副作用的JS表达式
            await self.page.evaluate("1")
            return True
        except Exception:
            logger.warning("CDP session已失效，正在重连...")
            # 清除旧状态
            self._connected = False
            self.browser = None
            self.page = None
            try:
                result = await self.connect()
                reconnected = result.get("status") == "connected"
                if reconnected:
                    logger.info("CDP session重连成功")
                else:
                    logger.error(f"CDP session重连失败: {result}")
                return reconnected
            except Exception as e:
                logger.error(f"CDP session重连异常: {e}")
                return False

    # ===== nodriver 层 =====

    async def connect(self, port: int = 9222) -> Dict:
        """连接到 Chrome CDP（复用现有 Chrome 或启动新实例）

        使用 user_data_dir 确保重用 Chrome profile 中的登录 cookie。
        """
        async with self._lock:
            try:
                if self._connected and self.browser:
                    return {"status": "already_connected"}

                if uc is None:
                    return {"status": "error", "message": "nodriver 未安装"}

                # 使用 user_data_dir 重用 Chrome profile（含登录 cookie）
                user_data = "/app/data/chrome-profile"
                self.browser = await uc.start(
                    user_data_dir=user_data,
                    browser_args=[
                        f"--remote-debugging-port={port}",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                    sandbox=False,
                    host="127.0.0.1",
                    port=port,
                )
                self.page = self.browser.main_tab
                self._connected = True
                logger.info(f"已连接到 Chrome CDP (profile: {user_data})")
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
        if not await self._ensure_session():
            return {"status": "error", "message": "浏览器未连接或重连失败"}
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
        if not await self._ensure_session():
            return None
        try:
            return await self.page.select(selector, timeout=timeout)
        except Exception:
            return None

    async def find_all(self, selector: str) -> List[object]:
        """查找所有匹配元素"""
        if not await self._ensure_session():
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
        """截图 — 返回base64编码的PNG"""
        if not await self._ensure_session():
            return {"status": "error", "message": "浏览器未连接或重连失败"}
        try:
            import base64
            save_path = path or f"/tmp/screenshot_{int(asyncio.get_event_loop().time())}.png"
            await self.page.save_screenshot(save_path)

            # 读取文件并转为base64
            with open(save_path, "rb") as f:
                img_data = base64.b64encode(f.read()).decode("utf-8")

            # 尝试获取页面标题
            title = ""
            try:
                title = await self.page.evaluate("document.title") or ""
            except Exception:
                pass

            return {
                "status": "success",
                "screenshot": img_data,
                "title": title,
                "path": save_path,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def execute_js(self, script: str):
        """执行 JavaScript"""
        if not await self._ensure_session():
            return None
        try:
            return await self.page.evaluate(script)
        except Exception as e:
            logger.error(f"JS 执行失败: {e}")
            return None

    # ===== Cookie 持久化 =====

    async def export_cookies(self) -> Dict:
        """通过 CDP 导出所有 cookie 到 /app/data/cookies.json"""
        if not await self._ensure_session():
            return {"status": "error", "message": "浏览器未连接或重连失败"}
        try:
            from nodriver.cdp import network as cdp_network

            # 使用 nodriver CDP 模块获取所有 cookie
            cookie_objects = await self.page.send(cdp_network.get_all_cookies())

            # 将 CDP Cookie 对象转为可序列化的 dict
            cookies = []
            for ck in cookie_objects:
                ck_dict = {
                    "name": str(ck.name) if ck.name else "",
                    "value": str(ck.value) if ck.value is not None else "",
                    "domain": str(ck.domain) if ck.domain else "",
                    "path": str(ck.path) if ck.path else "/",
                }
                # expires: 只保留有效的正数（排除 NaN, Inf, None, 0, 负数）
                if ck.expires is not None:
                    try:
                        exp_val = float(ck.expires)
                        import math
                        if math.isfinite(exp_val) and exp_val > 0:
                            ck_dict["expires"] = exp_val
                    except (ValueError, TypeError):
                        pass
                if ck.http_only:
                    ck_dict["httpOnly"] = True
                if ck.secure:
                    ck_dict["secure"] = True
                if ck.same_site:
                    try:
                        val = ck.same_site.name if hasattr(ck.same_site, "name") else str(ck.same_site)
                        ck_dict["sameSite"] = str(val)
                    except (AttributeError, TypeError, ValueError):
                        pass
                cookies.append(ck_dict)

            # 确保目标目录存在
            COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)

            payload = {
                "cookies": cookies,
                "exported_at": datetime.now().isoformat(),
                "count": len(cookies),
            }
            COOKIE_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(f"已导出 {len(cookies)} 条 cookie 到 {COOKIE_FILE}")
            return {
                "status": "ok",
                "count": len(cookies),
                "path": str(COOKIE_FILE),
            }
        except Exception as e:
            logger.error(f"导出 cookie 失败: {e}")
            return {"status": "error", "message": str(e)}

    async def import_cookies(self) -> Dict:
        """从 /app/data/cookies.json 导入 cookie 到浏览器"""
        if not await self._ensure_session():
            return {"status": "error", "message": "浏览器未连接或重连失败"}
        if not COOKIE_FILE.exists():
            return {"status": "error", "message": f"cookie 文件不存在: {COOKIE_FILE}"}
        try:
            from nodriver.cdp import network as cdp_network
            from nodriver.cdp.network import CookieSameSite

            payload = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
            cookies = payload.get("cookies", [])
            if not cookies:
                return {"status": "ok", "imported": 0, "message": "cookie 文件为空"}

            imported = 0
            skipped_reasons = []
            for ck in cookies:
                try:
                    ck_name = ck.get("name", "")
                    # 跳过无效 cookie（name 或 value 为空、未序列化值等）
                    if not ck_name or not isinstance(ck.get("value"), (str, type(None))):
                        continue

                    # 转换 same_site 为枚举，宽容处理非标准值
                    same_site = None
                    ss_val = ck.get("sameSite")
                    if ss_val:
                        ss_upper = str(ss_val).upper().replace("-", "_")
                        if ss_upper in ("STRICT", "LAX", "NONE", "UNSPECIFIED"):
                            try:
                                same_site = CookieSameSite(ss_upper)
                            except (ValueError, TypeError):
                                pass  # 无法匹配则留为 None

                    # 转换 expires 为 float，跳过非法值
                    expires = None
                    exp_val = ck.get("expires")
                    if exp_val is not None:
                        try:
                            expires = float(exp_val)
                            if expires <= 0:
                                expires = None
                        except (ValueError, TypeError):
                            expires = None

                    # 跳过值为空或不可序列化的 cookie
                    ck_value = ck.get("value")
                    if ck_value is None:
                        continue
                    try:
                        ck_value = str(ck_value)
                    except (ValueError, TypeError):
                        skipped_reasons.append(f"跳过 cookie {ck_name}: 值无法转为字符串")
                        continue

                    await self.page.send(cdp_network.set_cookie(
                        name=ck_name,
                        value=ck_value,
                        domain=ck.get("domain", ""),
                        path=ck.get("path", "/"),
                        secure=ck.get("secure") or None,
                        http_only=ck.get("httpOnly") or None,
                        same_site=same_site,
                        expires=expires,
                    ))
                    imported += 1
                except Exception as inner_e:
                    logger.warning(f"跳过 cookie {ck.get('name')}: {inner_e}")
                    continue

            logger.info(f"已导入 {imported}/{len(cookies)} 条 cookie")
            return {
                "status": "ok",
                "imported": imported,
                "total": len(cookies),
                "source": str(COOKIE_FILE),
            }
        except Exception as e:
            logger.error(f"导入 cookie 失败: {e}")
            return {"status": "error", "message": str(e)}

    # ===== 登录检测 =====

    # BOSS直聘登录页 URL（扫码登录）
    LOGIN_URL = "https://www.zhipin.com/web/user/?ka=header-login"

    # 已登录选择器（2024-2025 版 BOSS直聘首页布局）
    _LOGGED_IN_SELECTORS = [
        # 顶部导航栏用户头像/昵称
        '.user-nav', '.nav-figure', '.user-info',
        '[class*="user-nav"]', '[class*="nav-figure"]',
        '[class*="avatar"]', '.mini-user', '.user-box',
        # 侧边栏用户信息
        '.user-card', '[class*="user-card"]',
        # 右上角用户区域
        '.header-user', '[class*="header-user"]',
        '.user-wrap', '[class*="user-wrap"]',
    ]

    # 用户昵称选择器
    _USERNAME_SELECTORS = [
        '.user-info .name', '.nav-figure .name', '.user-name',
        '[class*="user"] .name', '.mini-user .name',
        '.user-nav .name', '.user-box .name',
        '.header-user .name', '.user-wrap .name',
        '[class*="user"] [class*="name"]',
    ]

    # 登录按钮选择器
    _LOGIN_BTN_SELECTORS = [
        '.btn-signin', '.login-btn', '[class*="sign-in"]',
        '.tosign-login', '[class*="login-btn"]',
        'a[href*="login"]', 'a[href*="user"]',
        '[class*="register-btn"]',
    ]

    # 二维码容器选择器
    _QR_SELECTORS = [
        '[class*="qr"]', '[class*="QR"]', '[class*="scan"]',
        '[class*="qrcode"]', '[class*="ewm"]',
        '.login-qr', '.scan-code', '.qr-code',
        'canvas[class*="qr"]', 'img[class*="qr"]',
        'img[alt*="二维码"]', 'img[alt*="QR"]',
    ]

    # 登录态 cookie 名称
    _LOGIN_COOKIE_NAMES = [
        "__zp_stoken__", "geek_zp_token", "token", "sid",
        "bstoken", "Hm_lvt_*",
    ]

    async def check_login(self) -> Dict:
        """检测 BOSS直聘登录状态（F4 增强）

        增强逻辑：
        1. 确保在 zhipin.com 域名下
        2. 通过 DOM 元素 + document.cookie 判断登录状态
        3. 若未登录，导航到登录页使 VNC 中可见扫码二维码
        4. 检测二维码是否可见，返回 qr_visible 字段

        Returns:
            {logged_in, message, username?, qr_visible?}
        """
        if not await self._ensure_session():
            return {"logged_in": False, "message": "浏览器未连接或重连失败"}
        try:
            # --- Step 1: 确保在 zhipin.com 域名下 ---
            current_url = await self.page.evaluate("window.location.href") or ""
            if "zhipin.com" not in current_url:
                logger.info(f"当前不在 zhipin.com ({current_url})，正在导航...")
                await self.page.get("https://www.zhipin.com/")
                await asyncio.sleep(2)
                current_url = await self.page.evaluate("window.location.href") or ""

            # --- Step 2: 通过 DOM 选择器判断已登录 ---
            user_el = None
            for sel in self._LOGGED_IN_SELECTORS:
                try:
                    el = await self.page.select(sel, timeout=2)
                    if el:
                        user_el = el
                        break
                except Exception:
                    continue

            if user_el:
                username = await self._extract_username()
                result = {"logged_in": True, "message": "已登录（DOM检测）"}
                if username:
                    result["username"] = username
                # 登录成功后自动备份 cookie（不影响主逻辑）
                try:
                    await self.export_cookies()
                except Exception as cookie_err:
                    logger.warning(f"自动备份 cookie 失败: {cookie_err}")
                return result

            # --- Step 3: 通过 document.cookie 辅助判断 ---
            cookie_str = await self.page.evaluate("document.cookie") or ""
            has_login_cookie = any(
                f"{name.split('*')[0]}=" in cookie_str
                for name in self._LOGIN_COOKIE_NAMES
                if "*" not in name  # 跳过通配符
            )
            if has_login_cookie:
                try:
                    await self.export_cookies()
                except Exception:
                    pass
                return {"logged_in": True, "message": "已登录（cookie 检测）"}

            # --- Step 4: 未登录 — 导航到登录页显示二维码 ---
            logger.info("未检测到登录态，导航到登录页...")
            qr_visible = await self._navigate_to_login_page()
            return {
                "logged_in": False,
                "message": "请在 VNC 中用手机扫码登录",
                "qr_visible": qr_visible,
            }
        except Exception as e:
            logger.error(f"检测登录状态失败: {e}")
            return {"logged_in": False, "message": str(e)}

    async def _extract_username(self) -> str:
        """从页面中提取已登录用户昵称"""
        for sel in self._USERNAME_SELECTORS:
            try:
                name_el = await self.page.select(sel, timeout=2)
                if name_el:
                    text = ""
                    try:
                        text = name_el.text_all
                    except Exception:
                        try:
                            text = await name_el.get_text()
                        except Exception:
                            try:
                                text = await self.page.evaluate(
                                    "document.querySelector(arguments[0])?.textContent?.trim()",
                                    sel,
                                )
                            except Exception:
                                pass
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return ""

    async def _navigate_to_login_page(self) -> bool:
        """导航到登录页并检测二维码是否可见

        Returns:
            True 表示二维码已可见于页面
        """
        try:
            current_url = await self.page.evaluate("window.location.href") or ""
            # 如果已在登录页，不重复导航
            if "login" not in current_url and "user" not in current_url:
                await self.page.get(self.LOGIN_URL)
                await asyncio.sleep(3)

            # 检测二维码是否可见
            qr_visible = await self._detect_qr_code()
            if qr_visible:
                logger.info("登录页二维码已可见")
            else:
                logger.warning("未检测到登录二维码，可能页面加载中或布局变化")
                # 尝试点击"扫码登录"标签（如果存在多种登录方式）
                for tab_sel in [
                    '[class*="scan"]', '[class*="qr-tab"]', '[class*="scan-login"]',
                    'li[data-type="scan"]', '.tab-scan', '[class*="qrcode-tab"]',
                ]:
                    try:
                        tab_el = await self.page.select(tab_sel, timeout=2)
                        if tab_el:
                            await tab_el.click()
                            await asyncio.sleep(2)
                            qr_visible = await self._detect_qr_code()
                            if qr_visible:
                                logger.info("点击扫码标签后二维码可见")
                                break
                    except Exception:
                        continue
            return qr_visible
        except Exception as e:
            logger.error(f"导航到登录页失败: {e}")
            return False

    async def _detect_qr_code(self) -> bool:
        """检测页面上是否有可见的二维码

        Returns:
            True 表示二维码元素存在且可见
        """
        for sel in self._QR_SELECTORS:
            try:
                el = await self.page.select(sel, timeout=2)
                if el:
                    # 验证元素可见（非 display:none / visibility:hidden）
                    visible = await self.page.evaluate(
                        """(function() {
                            var el = document.querySelector(arguments[0]);
                            if (!el) return false;
                            var rect = el.getBoundingClientRect();
                            return rect.width > 10 && rect.height > 10;
                        })()""",
                        sel,
                    )
                    if visible:
                        return True
            except Exception:
                continue
        return False

    async def get_status(self) -> Dict:
        """获取当前状态（包含真实session探测）"""
        if not self._connected:
            return {"status": "disconnected", "connected": False}
        # 即使 _connected=True，也探测session是否真正可用
        try:
            await self.page.evaluate("1")
            return {"status": "connected", "connected": True}
        except Exception:
            self._connected = False
            return {"status": "disconnected", "connected": False}

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
