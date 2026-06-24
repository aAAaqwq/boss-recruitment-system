"""浏览器自动化核心模块 — nodriver DOM定位 + xdotool 仿真鼠标"""
import asyncio
import json
import random
import subprocess
import os
import threading
from typing import Optional, Dict, Tuple, List, Any
from pathlib import Path
from datetime import datetime

from app.logging_config import logger

COOKIE_FILE = Path(os.environ.get("DATA_DIR", "/app/data")) / "cookies.json"

try:
    import nodriver as uc
except ImportError:
    uc = None  # 允许在非 Docker 环境导入


# ========== CDP 返回值反序列化 ==========

def _cdp_deserialize(obj: Any) -> Any:
    """递归地将 CDP RemoteObject 格式转为 Python 原生类型。

    CDP 序列化格式:
      - 对象: [[key1, {'type': t1, 'value': v1}], [key2, {'type': t2, 'value': v2}], ...]
      - 数组: [[{'type': t1, 'value': v1}], [{'type': t2, 'value': v2}], ...]
      - 标量: {'type': 'string'|'number'|'boolean', 'value': v}

    此函数将上述格式递归转为 Python dict/list/标量。
    """
    if obj is None:
        return None

    # 已经是 Python 原生类型，直接返回
    if isinstance(obj, (str, int, float, bool)):
        return obj

    if isinstance(obj, dict):
        # 单个值描述符: {'type': '...', 'value': ...}
        if 'type' in obj and 'value' in obj:
            return _cdp_deserialize(obj.get('value'))
        # 普通字典，递归处理
        return {k: _cdp_deserialize(v) for k, v in obj.items()}

    if isinstance(obj, list):
        if not obj:
            return []

        # 判断是对象 [[k, v_desc], [k, v_desc], ...] 还是数组 [v_desc, v_desc, ...]
        first = obj[0]
        if isinstance(first, list) and len(first) == 2:
            key_candidate = first[0]
            val_candidate = first[1]
            # 格式1: [string_name, {type, value}] — CDP 值描述符格式
            if isinstance(key_candidate, str) and isinstance(val_candidate, dict) and 'type' in val_candidate:
                result = {}
                for item in obj:
                    if isinstance(item, list) and len(item) == 2:
                        k, v = item
                        if isinstance(k, str):
                            result[k] = _cdp_deserialize(v)
                return result
            # 格式2: [string_name, already_deserialized_value] — nodriver 预反序列化后的格式
            if isinstance(key_candidate, str):
                result = {}
                for item in obj:
                    if isinstance(item, list) and len(item) == 2:
                        k, v = item
                        if isinstance(k, str):
                            result[k] = _cdp_deserialize(v)
                return result

        # 可能是数组: 每个元素可能是值描述符或普通元素
        result = []
        for item in obj:
            if isinstance(item, list) and len(item) == 1 and isinstance(item[0], dict):
                # CDP 数组元素包裹: [[{type, value}], [{type, value}], ...]
                result.append(_cdp_deserialize(item[0]))
            else:
                result.append(_cdp_deserialize(item))
        return result

    return obj


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
        self._lock = threading.Lock()  # 仅保护状态切换，不保护长操作
        self._display = os.environ.get("DISPLAY", ":1")

    # ===== 会话健康检查 =====

    async def _ensure_session(self, timeout: int = 5) -> bool:
        """确保CDP session有效，失效则自动重连。

        Returns:
            True 表示session可用，False 表示不可用且重连失败。
        """
        if not self._connected or not self.page:
            return False
        try:
            # 轻量探测：带超时的JS执行
            await asyncio.wait_for(self.page.evaluate("1"), timeout=timeout)
            return True
        except (asyncio.TimeoutError, Exception):
            logger.warning("CDP session已失效，正在重连...")
            # 清除旧状态（线程安全）
            with self._lock:
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
        在 Docker root 环境下，nodriver sandbox=False 可能无法正确传递
        --no-sandbox，因此先检测 CDP 端口是否已有 Chrome 在监听：
        - 有 → 直接连接 nodriver 到现有 Chrome
        - 没有 → 手动启动 Chrome（带 --no-sandbox）再连接
        """
        with self._lock:
            try:
                if self._connected and self.browser:
                    return {"status": "already_connected"}

                if uc is None:
                    return {"status": "error", "message": "nodriver 未安装"}

                user_data = "/app/data/chrome-profile"

                # 清理上一次异常退出残留的锁文件
                for lock_file in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
                    lock_path = os.path.join(user_data, lock_file)
                    if os.path.exists(lock_path):
                        try:
                            os.remove(lock_path)
                        except OSError:
                            pass

                # Step 1: 检测 CDP 端口是否已有 Chrome 在监听
                cdp_alive = await self._check_cdp_port(port)

                # Step 2: 没有 Chrome → 手动启动
                if not cdp_alive:
                    launched = await self._launch_chrome(port, user_data)
                    if not launched:
                        return {"status": "error", "message": "Chrome 启动失败，请检查 VNC 桌面"}

                # Step 3: nodriver 连接到 CDP（复用已启动的 Chrome）
                try:
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
                except Exception as start_err:
                    # nodriver start 失败（常见于 root 环境的 sandbox 问题），
                    # 尝试直接通过 CDP websocket 连接已运行的 Chrome
                    logger.warning(f"nodriver start 失败: {start_err}，尝试直接 CDP 连接...")
                    try:
                        self.browser = await uc.start(
                            user_data_dir=user_data,
                            browser_executable_path="google-chrome",
                            browser_args=[
                                f"--remote-debugging-port={port}",
                                "--no-sandbox",
                                "--disable-dev-shm-usage",
                            ],
                            sandbox=False,
                            host="127.0.0.1",
                            port=port,
                        )
                    except Exception as fallback_err:
                        logger.error(f"CDP 直接连接也失败: {fallback_err}")
                        return {"status": "error", "message": f"浏览器连接失败: {fallback_err}"}

                self.page = self.browser.main_tab
                self._connected = True
                logger.info(f"已连接到 Chrome CDP (profile: {user_data})")
                return {"status": "connected"}
            except Exception as e:
                logger.error(f"连接 Chrome 失败: {e}")
                return {"status": "error", "message": str(e)}

    @staticmethod
    async def _check_cdp_port(port: int = 9222) -> bool:
        """检测 CDP 端口是否有 Chrome 在监听"""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("127.0.0.1", port))
            sock.close()
            return result == 0
        except Exception:
            return False

    @staticmethod
    async def _launch_chrome(port: int = 9222, user_data: str = "/app/data/chrome-profile") -> bool:
        """手动启动 Chrome（带 --no-sandbox），返回是否成功"""
        import socket
        display = os.environ.get("DISPLAY", ":1")
        env = {**os.environ, "DISPLAY": display}

        # 清理Chrome僵尸锁文件（上次非正常退出残留）
        import glob as _glob
        for _f in _glob.glob(f"{user_data}/Singleton*"):
            try: os.remove(_f)
            except OSError: pass

        # 找 Chrome 二进制
        chrome_bin = "google-chrome"
        for candidate in ["google-chrome-stable", "google-chrome", "chromium-browser", "chromium"]:
            if subprocess.run(["which", candidate], capture_output=True).returncode == 0:
                chrome_bin = candidate
                break

        try:
            subprocess.Popen(
                [
                    chrome_bin,
                    f"--remote-debugging-port={port}",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    f"--user-data-dir={user_data}",
                    "about:blank",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        except Exception as e:
            logger.error(f"Chrome 启动失败: {e}")
            return False

        # 等待 CDP 端口就绪（最多 15 秒）
        for _ in range(15):
            await asyncio.sleep(1)
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = sock.connect_ex(("127.0.0.1", port))
                sock.close()
                if result == 0:
                    logger.info(f"Chrome CDP 端口 {port} 已就绪")
                    return True
            except Exception:
                pass

        logger.error("Chrome CDP 端口等待超时 (15s)")
        return False

    async def disconnect(self) -> Dict:
        """断开浏览器连接"""
        with self._lock:
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
        """执行 JavaScript，自动反序列化 CDP RemoteObject 格式"""
        if not await self._ensure_session():
            return None
        try:
            result = await self.page.evaluate(script)
            deserialized = _cdp_deserialize(result)
            if deserialized is not None and not isinstance(deserialized, (dict, list, str, int, float, bool)):
                logger.warning(f"[execute_js] 非预期返回类型: {type(deserialized).__name__} = {repr(deserialized)[:200]}")
            return deserialized
        except Exception as e:
            logger.error(f"JS 执行失败: {e}")
            return None

    # ===== Cookie 持久化 =====

    async def export_cookies(self) -> Dict:
        """通过 CDP 导出所有 cookie 到 /app/data/cookies.json

        只在检测到登录态 cookie (wt2/wbg/zp_at/bst) 时才覆盖备份文件，
        防止在登录页等未认证页面导出时污染已保存的有效 cookie。
        """
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

            # 验证：只在包含登录态 cookie 时才覆盖备份文件
            cookie_names = {c["name"] for c in cookies}
            auth_present = [n for n in self._LOGIN_COOKIE_NAMES if n in cookie_names]
            if auth_present:
                COOKIE_FILE.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(f"已导出 {len(cookies)} 条 cookie (含认证: {auth_present}) 到 {COOKIE_FILE}")
            else:
                logger.warning(
                    f"跳过导出: 当前页面无登录态 cookie ({len(cookies)} 条, "
                    f"缺: {[n for n in self._LOGIN_COOKIE_NAMES if n not in cookie_names]})"
                )

            return {
                "status": "ok",
                "count": len(cookies),
                "path": str(COOKIE_FILE),
                "saved": bool(auth_present),
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

                    # 转换 expires 为 CDP TimeSinceEpoch 类型
                    expires = None
                    exp_val = ck.get("expires")
                    if exp_val is not None:
                        try:
                            exp_float = float(exp_val)
                            import math
                            if math.isfinite(exp_float) and exp_float > 0:
                                # TimeSinceEpoch 是 nodriver CDP 类型（继承 float，有 to_json 方法）
                                expires = cdp_network.TimeSinceEpoch(exp_float)
                        except (ValueError, TypeError):
                            pass

                    # 跳过值为空或不可序列化的 cookie
                    ck_value = ck.get("value")
                    if ck_value is None:
                        continue
                    try:
                        ck_value = str(ck_value)
                    except (ValueError, TypeError):
                        skipped_reasons.append(f"跳过 cookie {ck_name}: 值无法转为字符串")
                        continue

                    set_args = {
                        "name": ck_name,
                        "value": ck_value,
                        "domain": ck.get("domain", ""),
                        "path": ck.get("path", "/"),
                        "secure": ck.get("secure") or None,
                        "http_only": ck.get("httpOnly") or None,
                        "same_site": same_site,
                    }
                    if expires is not None:
                        set_args["expires"] = expires

                    await self.page.send(cdp_network.set_cookie(**set_args))
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

    # 反向判断依赖的页面文案（不再用CSS选择器正向猜DOM）
    # 已登录: 页面含"推荐牛人"/"职位管理"等招聘者Dashboard专属文案
    # 未登录: URL含登录路径 或 页面有"登录/注册"按钮

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

    # 登录态 cookie 名称（来自真实 BOSS 会话分析）
    # HttpOnly cookie（CDP 可读，document.cookie 不可读）:
    #   wt2   - BOSS 会话 token
    #   wbg   - BOSS 认证 token
    #   zp_at - 直聘 access token
    # 普通 cookie:
    #   bst   - BOSS security token
    #   __c   - 会话标识
    #   __a   - 用户标识
    _LOGIN_COOKIE_NAMES = [
        "wt2",          # BOSS 会话 token (HttpOnly)
        "wbg",          # BOSS 认证 token (HttpOnly)
        "zp_at",        # 直聘 access token (HttpOnly)
        "bst",          # BOSS security token
    ]

    @staticmethod
    def _safe_str(val: Any) -> str:
        """安全地将 CDP 返回值转为字符串。
        nodriver evaluate 可能返回 ExceptionDetails 等非字符串对象。
        """
        if val is None:
            return ""
        if isinstance(val, str):
            return val
        # CDP RemoteObject 或 ExceptionDetails → 取 description/message 或 str()
        if isinstance(val, dict):
            return val.get("value", val.get("description", val.get("message", ""))) or ""
        return str(val) if val else ""

    async def _safe_evaluate(self, js: str, timeout: int = 8) -> str:
        """安全执行 JS 并返回字符串，超时或异常返回空串。"""
        try:
            result = await asyncio.wait_for(self.page.evaluate(js), timeout=timeout)
            return self._safe_str(result)
        except Exception:
            return ""

    async def check_login(self) -> Dict:
        """检测 BOSS直聘登录状态

        检测策略（按优先级）:
        1. Cookie 检测: wt2/wbg/zp_at/bst 存在且未过期 → 已登录
        2. URL 检测: 在登录页(passport/user) → 未登录
        3. iframe 内容检测: 等待 iframe 加载后检查招聘者文案
        4. 主页面文案检测: 检查侧边栏等非 iframe 内容

        关键: 不再盲目导航到登录页。只有 URL 确实在登录页时才报未登录。
        iframe 加载慢时用轮询等待(最多10秒)而非立即判定未登录。
        """
        if not await self._ensure_session(timeout=8):
            return {"logged_in": False, "message": "浏览器未连接或重连失败"}
        try:
            # --- Step 0: 导航到推荐页(如果不在 BOSS 域) ---
            current_url = await self._safe_evaluate("window.location.href")
            if "zhipin.com" not in current_url:
                try:
                    await asyncio.wait_for(
                        self.page.get("https://www.zhipin.com/web/chat/recommend"),
                        timeout=15,
                    )
                    await asyncio.sleep(3)
                except asyncio.TimeoutError:
                    pass
                current_url = await self._safe_evaluate("window.location.href")

            if not current_url:
                return {"logged_in": False, "message": "页面响应超时"}

            # --- Step 1: URL 判断 — 确实在登录页 → 未登录 ---
            on_login_page = (
                "/web/user/" in current_url
                or "passport" in current_url.lower()
            )
            # 注意: /web/chat/recommend URL 包含 "login" 不算登录页
            # 只有 /web/user/ 或 passport 才是真正的登录页

            if on_login_page:
                logger.info(f"URL 指向登录页: {current_url}")
                # 不主动导航到登录页，只报告状态
                qr_visible = await self._detect_qr_code()
                return {
                    "logged_in": False,
                    "message": "当前在登录页，请扫码登录",
                    "qr_visible": qr_visible,
                }

            # --- Step 2: Cookie 检测（最可靠） ---
            cookie_check = await self._safe_evaluate("""
            (function() {
                // 检查 document.cookie 中可访问的登录态 cookie
                var dc = document.cookie;
                var hasBst = dc.indexOf('bst=') >= 0;
                // wt2/wbg/zp_at 是 HttpOnly，document.cookie 读不到
                // 但如果 bst 存在且页面不在登录页，大概率已登录
                return hasBst ? 'has_bst' : 'no_bst';
            })()
            """)

            # --- Step 3: 等待 iframe 加载并检查内容 ---
            # 推荐页的"推荐牛人"文案在 iframe 内，需要等待 iframe 加载
            recruiter_found = False
            for wait_round in range(3):
                iframe_check = await self._safe_evaluate("""
                (function() {
                    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
                    if (!iframe) return 'no_iframe';
                    var doc = iframe.contentDocument;
                    if (!doc) return 'no_access';
                    var text = doc.body ? doc.body.innerText : '';
                    if (text.indexOf('推荐牛人') >= 0 || text.indexOf('打招呼') >= 0) return 'recruiter';
                    if (text.indexOf('加载中') >= 0 || text.length < 10) return 'loading';
                    return 'other:' + text.substring(0, 50);
                })()
                """)

                if "recruiter" in iframe_check:
                    recruiter_found = True
                    break
                elif "loading" in iframe_check or "no_iframe" in iframe_check:
                    await asyncio.sleep(3)
                else:
                    break  # iframe 有内容但不是招聘者页面

            # --- Step 4: 主页面侧边栏检测 ---
            page_text = await self._safe_evaluate("document.body.innerText.substring(0,500)")
            has_sidebar = (
                "职位管理" in page_text
                or "牛人管理" in page_text
                or "道具" in page_text
            )

            # --- Step 5: 综合判断 ---
            if recruiter_found:
                logger.info("iframe 内含招聘者内容，判定已登录")
                try:
                    await self.export_cookies()
                except Exception:
                    pass
                return {"logged_in": True, "message": "已登录（iframe内容检测）"}

            if has_sidebar and not on_login_page:
                logger.info("侧边栏含招聘者菜单，判定已登录")
                try:
                    await self.export_cookies()
                except Exception:
                    pass
                return {"logged_in": True, "message": "已登录（侧边栏检测）"}

            if cookie_check == "has_bst" and not on_login_page:
                logger.info("有 bst cookie 且不在登录页，判定已登录（页面可能仍在加载）")
                return {"logged_in": True, "message": "已登录（cookie检测，页面加载中）"}

            # --- Step 6: 未检测到登录态 → 尝试 cookie 恢复 ---
            if COOKIE_FILE.exists():
                logger.info("尝试导入备份cookie恢复登录态...")
                try:
                    import_result = await self.import_cookies()
                    logger.info(f"导入: {import_result.get('imported',0)}/{import_result.get('total',0)}")
                    if import_result.get("imported", 0) > 0:
                        try:
                            await self.page.get("https://www.zhipin.com/web/chat/recommend")
                        except Exception:
                            pass
                        await asyncio.sleep(8)
                        # 重做一次检测
                        retry_url = await self._safe_evaluate("window.location.href")
                        if retry_url and "/web/user/" not in retry_url and "passport" not in retry_url:
                            retry_text = await self._safe_evaluate("document.body.innerText.substring(0,500)")
                            if "职位管理" in retry_text or "牛人管理" in retry_text:
                                logger.info("Cookie恢复成功")
                                try:
                                    await self.export_cookies()
                                except Exception:
                                    pass
                                return {"logged_in": True, "message": "已登录（cookie恢复）"}
                except Exception as e:
                    logger.warning(f"Cookie恢复失败: {e}")

            # 未登录 — 不再主动导航到登录页（避免破坏已有会话）
            logger.info("未检测到登录态")
            return {
                "logged_in": False,
                "message": "未检测到登录态，请在 VNC 中确认登录状态",
            }
        except Exception as e:
            logger.error(f"检测登录状态失败: {e}")
            return {"logged_in": False, "message": str(e)}

    async def _navigate_to_login_page(self) -> bool:
        """导航到登录页并检测二维码是否可见

        Returns:
            True 表示二维码已可见于页面
        """
        if not self.page:
            logger.warning("_navigate_to_login_page: page 为 None，跳过")
            return False
        try:
            current_url = await self._safe_evaluate("window.location.href")
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

        # 沿路径移动（不使用 --sync，避免在 Docker VNC 环境中超时）
        for px, py in path:
            subprocess.run(
                ["xdotool", "mousemove", str(px), str(py)],
                env={**os.environ, "DISPLAY": self._display},
                timeout=3
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

    # ===== 屏幕/视口坐标偏移 =====

    async def get_chrome_offset(self) -> Tuple[int, int]:
        """计算浏览器视口坐标到屏幕坐标的偏移量。

        getBoundingClientRect() 返回视口坐标，
        xdotool 使用屏幕坐标。两者之间的差值 = 浏览器 chrome 高度 + 窗口位置偏移。

        Returns:
            (offset_x, offset_y) 屏幕坐标偏移
        """
        try:
            js_result = await self.execute_js(
                "JSON.stringify({sx: window.screenX, sy: window.screenY, "
                "innerH: window.innerHeight, outerH: window.outerHeight})"
            )
            if isinstance(js_result, str):
                js_result = json.loads(js_result)
            offset_x = int(js_result.get("sx", 0))
            # Y偏移 = 窗口Y位置 + (窗口高度 - 视口高度) = 窗口Y + chrome高度
            offset_y = int(js_result.get("sy", 0)) + (
                int(js_result.get("outerH", 720)) - int(js_result.get("innerH", 629))
            )
            logger.info(f"Chrome偏移: x={offset_x}, y={offset_y}")
            return (offset_x, offset_y)
        except Exception as e:
            logger.warning(f"获取chrome偏移失败，使用默认值(0,118): {e}")
            return (0, 118)  # Docker默认值

    # ===== CDP 原生点击（绕过JS事件系统，直接通过浏览器输入管道） =====

    async def cdp_click_viewport(self, x: float, y: float) -> bool:
        """通过 CDP Input.dispatchMouseEvent 在视口坐标处执行真实点击。

        与 JS 的 element.click() 或 dispatchEvent 不同，CDP 的
        dispatchMouseEvent 走浏览器原生输入管道，能正确触发 React
        等框架的事件处理器。坐标为视口坐标（getBoundingClientRect 返回的）。

        Args:
            x: 视口X坐标
            y: 视口Y坐标

        Returns:
            True 成功，False 失败
        """
        if not await self._ensure_session():
            return False
        try:
            from nodriver.cdp import input_ as cdp_input

            # mouseMoved — 先移动鼠标到目标位置
            await self.page.send(cdp_input.dispatch_mouse_event(
                type_="mouseMoved",
                x=x, y=y,
            ))
            await asyncio.sleep(0.02)

            # mousePressed
            await self.page.send(cdp_input.dispatch_mouse_event(
                type_="mousePressed",
                x=x, y=y,
                button=cdp_input.MouseButton.LEFT,
                click_count=1,
            ))
            await asyncio.sleep(0.05)
            # mouseReleased
            await self.page.send(cdp_input.dispatch_mouse_event(
                type_="mouseReleased",
                x=x, y=y,
                button=cdp_input.MouseButton.LEFT,
                click_count=1,
            ))
            return True
        except Exception as e:
            logger.warning(f"CDP点击失败: {e}")
            return False

    # ===== 线程安全重置 =====

    def reset_for_thread(self):
        """线程安全地重置浏览器状态，供后台线程重新连接。

        必须在创建新事件循环前调用，确保主循环不会引用已释放的对象。
        """
        with self._lock:
            self._connected = False
            self.browser = None
            self.page = None

    # ===== CDP 下载控制 =====

    async def enable_download_interception(self, download_dir: str) -> Dict:
        """启用 CDP 下载拦截，将浏览器下载保存到指定目录。

        通过 Page.setDownloadBehavior 让 Chrome 自动保存文件到 download_dir，
        无需处理保存对话框。

        Args:
            download_dir: 下载目标目录绝对路径

        Returns:
            {status, download_dir}
        """
        if not await self._ensure_session():
            return {"status": "error", "message": "浏览器未连接"}
        try:
            from nodriver.cdp import page as cdp_page

            # 确保目录存在
            Path(download_dir).mkdir(parents=True, exist_ok=True)

            # 设置下载行为：自动保存到指定目录，不弹对话框
            await self.page.send(
                cdp_page.set_download_behavior(
                    behavior="allow",
                    download_path=download_dir,
                )
            )
            logger.info(f"[CDP] 下载拦截已启用，目标目录: {download_dir}")
            return {"status": "ok", "download_dir": download_dir}
        except Exception as e:
            logger.warning(f"[CDP] 设置下载行为失败（降级模式）: {e}")
            # 降级：不拦截下载，依赖Chrome默认行为
            return {"status": "fallback", "message": str(e)}

    # ===== CDP 下载事件监听 =====

    async def wait_for_download(
        self, download_dir: str, timeout: float = 30.0, poll_interval: float = 0.5,
        before_files: set = None,
    ) -> Dict:
        """等待下载完成 — CDP事件 + 目录轮询双重保障。

        点击下载按钮后调用此方法。优先通过 CDP Browser.downloadProgress
        事件确认下载，失败时回退到目录轮询（检测新文件且大小稳定）。

        Args:
            download_dir: 下载目录绝对路径
            timeout: 最大等待秒数
            poll_interval: 目录轮询间隔秒数
            before_files: 预记录的文件快照（用于点击下载前就记录的情况）

        Returns:
            {status: "downloaded"|"timeout"|"error", path?: str, size?: int, method: str}
        """
        dl_dir = Path(download_dir)
        before = before_files if before_files is not None else (set(dl_dir.iterdir()) if dl_dir.exists() else set())

        # 方法1: 尝试 CDP 事件监听 (Browser.downloadProgress) — 短超时快速退回
        cdp_result = None
        try:
            cdp_result = await self._wait_download_cdp(min(timeout, 5.0))
        except Exception as e:
            logger.debug(f"[CDP] 下载事件监听失败，回退到目录轮询: {e}")

        if cdp_result and cdp_result.get("status") == "downloaded":
            return {**cdp_result, "method": "cdp_event"}

        # 方法2: 目录轮询 — 等待新文件出现且大小>0
        deadline = asyncio.get_event_loop().time() + timeout
        seen_sizes = {}  # path -> (size, count) — 用于检测文件写入完成

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(poll_interval)
            if not dl_dir.exists():
                continue
            after = set(dl_dir.iterdir())
            new_files = after - before

            for f in new_files:
                if not f.is_file():
                    continue
                # 跳过临时文件（.crdownload / .tmp / .part）
                if f.suffix.lower() in ('.crdownload', '.tmp', '.part'):
                    continue
                try:
                    current_size = f.stat().st_size
                except OSError:
                    continue
                if current_size == 0:
                    continue

                prev = seen_sizes.get(str(f))
                # 小文件(<100KB)一次检测即确认；大文件等大小稳定
                if current_size < 100 * 1024:
                    logger.info(f"[CDP] 目录轮询确认下载(小文件): {f.name} ({current_size} bytes)")
                    return {
                        "status": "downloaded",
                        "path": str(f),
                        "size": current_size,
                        "method": "poll_small",
                    }
                if prev is not None and prev[0] == current_size:
                    logger.info(f"[CDP] 目录轮询确认下载: {f.name} ({current_size} bytes)")
                    return {
                        "status": "downloaded",
                        "path": str(f),
                        "size": current_size,
                        "method": "poll",
                    }
                seen_sizes[str(f)] = (current_size, (prev[1] + 1) if prev else 1)

            # 也检查所有文件（包括 before_files 中已存在的），防止文件在 before 快照后被覆盖写入
            all_files = after
            for f in all_files:
                if not f.is_file():
                    continue
                if f.suffix.lower() in ('.crdownload', '.tmp', '.part'):
                    continue
                fpath = str(f)
                if fpath in {str(x) for x in before}:
                    continue  # 跳过之前就有的文件

        return {"status": "timeout", "message": f"下载未在 {timeout}s 内完成", "method": "timeout"}

    async def _wait_download_cdp(self, timeout: float = 30.0) -> Optional[Dict]:
        """通过 CDP Browser.downloadProgress 事件等待下载。

        nodriver 的 CDP 事件通过底层 websocket 分发。我们利用 page.send()
        后浏览器的响应流来捕获 downloadProgress 事件。
        """
        if not await self._ensure_session():
            return None
        try:
            # 注册一次性事件处理器
            # nodriver 内部使用 cdp.util.event_listener 或类似机制
            # 我们使用 page 的底层事件处理
            from nodriver.cdp import browser as cdp_browser

            download_event = asyncio.Event()
            download_state = {}

            # nodriver Tab 支持通过 add_handler 订阅 CDP 事件
            async def on_download_progress(event):
                try:
                    state = event.get("state", "")
                    if state == "completed":
                        download_state["status"] = "downloaded"
                        download_state["path"] = event.get("path", "")
                        download_event.set()
                    elif state in ("canceled", "interrupted"):
                        download_state["status"] = state
                        download_event.set()
                except Exception:
                    pass

            # 尝试通过 page 的 CDP 客户端注册事件处理器
            if hasattr(self.page, "_client") and hasattr(self.page._client, "on"):
                self.page._client.on("Browser.downloadProgress", on_download_progress)
            elif hasattr(self.page, "add_handler"):
                self.page.add_handler("Browser.downloadProgress", on_download_progress)
            else:
                return None  # 无法注册事件，回退到轮询

            # 等待下载事件或超时
            try:
                await asyncio.wait_for(download_event.wait(), timeout=timeout)
                if download_state.get("status") == "downloaded":
                    return {
                        "status": "downloaded",
                        "path": download_state.get("path", ""),
                        "method": "cdp_event",
                    }
                return {"status": download_state.get("status", "unknown")}
            except asyncio.TimeoutError:
                return {"status": "timeout"}
        except ImportError:
            return None
        except Exception as e:
            logger.debug(f"[CDP] _wait_download_cdp 异常: {e}")
            return None

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


# 全局取消信号 — 用于 F5/F6/F7/F8 任务中断
cancel_event = threading.Event()

# 全局单例
automation = BrowserAutomation()
