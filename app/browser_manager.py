"""
浏览器连接管理器 - 使用Playwright连接已打开的Chrome浏览器
支持通过CDP(Chrome DevTools Protocol)连接或启动新的浏览器实例
"""
import asyncio
from typing import Dict, Optional


class BrowserManager:
    """管理浏览器连接 - 使用Playwright连接已打开的Chrome"""

    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self, headless: bool = False):
        """连接到已打开的Chrome浏览器或启动新的

        Chrome需要以调试模式启动：
        macOS: /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
        Linux: google-chrome --remote-debugging-port=9222
        """
        async with self._lock:
            if self._connected and self.browser and self.browser.is_connected():
                return {
                    "status": "already_connected",
                    "message": "浏览器已连接"
                }

            try:
                from playwright.async_api import async_playwright

                self.playwright = await async_playwright().start()

                # 尝试连接到已打开的Chrome调试端口
                try:
                    from app.logging_config import api_logger
                    api_logger.info("尝试连接到已打开的Chrome (port 9222)...")
                    self.browser = await self.playwright.chromium.connect_over_cdp(
                        "http://localhost:9222"
                    )
                    api_logger.info("成功连接到已打开的Chrome")

                    # 获取或创建context和page
                    contexts = self.browser.contexts
                    if contexts:
                        self.context = contexts[0]
                        pages = self.context.pages
                        if pages:
                            self.page = pages[0]
                        else:
                            self.page = await self.context.new_page()
                    else:
                        self.context = await self.browser.new_context()
                        self.page = await self.context.new_page()

                    self._connected = True
                    return {
                        "status": "connected",
                        "message": "成功连接到已打开的Chrome浏览器",
                        "method": "connect_over_cdp",
                        "url": self.page.url if self.page else None
                    }

                except Exception as e:
                    from app.logging_config import api_logger
                    api_logger.warning(f"连接已打开的Chrome失败: {e}")
                    # 启动新的浏览器实例
                    api_logger.info("启动新的Chrome实例...")
                    self.browser = await self.playwright.chromium.launch(
                        headless=headless,
                        args=[
                            '--disable-blink-features=AutomationControlled',
                            '--no-sandbox'
                        ]
                    )
                    self.context = await self.browser.new_context(
                        viewport={'width': 1280, 'height': 720},
                        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
                    )
                    self.page = await self.context.new_page()
                    self._connected = True

                    return {
                        "status": "connected",
                        "message": "已启动新的Chrome浏览器",
                        "method": "launch_new",
                        "url": self.page.url
                    }

            except Exception as e:
                from app.logging_config import api_logger
                api_logger.error(f"浏览器连接失败: {e}")
                await self._cleanup()
                return {
                    "status": "error",
                    "message": f"浏览器连接失败: {str(e)}"
                }

    async def disconnect(self):
        """断开浏览器连接"""
        async with self._lock:
            await self._cleanup()
            return {"status": "disconnected", "message": "已断开浏览器连接"}

    async def _cleanup(self):
        """清理资源"""
        self._connected = False
        if self.page:
            try:
                await self.page.close()
            except:
                pass
            self.page = None
        if self.context:
            try:
                await self.context.close()
            except:
                pass
            self.context = None
        # 注意：connect_over_cdp连接的browser不应关闭（它是用户打开的浏览器）
        # 只有我们启动的browser才需要关闭
        if self.browser and not hasattr(self.browser, '_is_connected_over_cdp'):
            try:
                await self.browser.close()
            except:
                pass
        self.browser = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except:
                pass
            self.playwright = None

    def get_status(self):
        """获取连接状态"""
        if not self._connected or not self.browser:
            return {
                "connected": False,
                "message": "未连接"
            }

        try:
            page_info = None
            if self.page:
                # Don't call async methods in sync context
                # Just return basic URL info
                page_info = {
                    "url": self.page.url,
                    "title": None  # Can't get title sync
                }
            return {
                "connected": True,
                "message": "已连接",
                "browser": "chromium",
                "page": page_info
            }
        except Exception as e:
            return {
                "connected": False,
                "message": f"状态获取失败: {str(e)}"
            }

    async def screenshot(self, full_page: bool = False) -> Dict:
        """获取当前页面截图

        Returns:
            包含base64截图的字典
        """
        if not self._connected or not self.page:
            return {
                "status": "error",
                "message": "浏览器未连接"
            }

        try:
            import base64

            screenshot_bytes = await self.page.screenshot(
                full_page=full_page,
                type='png'
            )

            base64_str = base64.b64encode(screenshot_bytes).decode('utf-8')

            return {
                "status": "success",
                "screenshot": base64_str,
                "format": "png",
                "encoding": "base64",
                "url": self.page.url,
                "title": await self.page.title()
            }

        except Exception as e:
            from app.logging_config import api_logger
            api_logger.error(f"截图失败: {e}")
            return {
                "status": "error",
                "message": f"截图失败: {str(e)}"
            }

    async def navigate(self, url: str) -> Dict:
        """导航到指定URL"""
        if not self._connected or not self.page:
            return {
                "status": "error",
                "message": "浏览器未连接"
            }

        try:
            await self.page.goto(url, wait_until='domcontentloaded')
            return {
                "status": "success",
                "url": self.page.url,
                "title": await self.page.title()
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"导航失败: {str(e)}"
            }

    async def execute_script(self, script: str) -> Dict:
        """在页面中执行JavaScript"""
        if not self._connected or not self.page:
            return {
                "status": "error",
                "message": "浏览器未连接"
            }

        try:
            result = await self.page.evaluate(script)
            return {
                "status": "success",
                "result": result
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"脚本执行失败: {str(e)}"
            }

    async def check_login(self) -> Dict:
        """检查BOSS直聘登录状态

        Returns:
            包含登录状态的字典
        """
        if not self._connected or not self.page:
            return {
                "logged_in": False,
                "message": "浏览器未连接"
            }

        try:
            from app.logging_config import api_logger
            # 导航到BOSS直聘主页
            await self.page.goto('https://www.zhipin.com/', wait_until='domcontentloaded')

            # 检查是否存在登录后的元素（如用户头像、用户名等）
            # 同时检查是否有登录按钮或二维码
            has_login_btn = await self.page.query_selector('.web-slogan')
            has_qrcode = await self.page.query_selector('.qrcode-img')
            has_user_info = await self.page.query_selector('.user-nav-name')

            if has_user_info:
                # 获取用户名
                username = await self.page.inner_text('.user-nav-name')
                return {
                    "logged_in": True,
                    "username": username.strip(),
                    "message": "已登录"
                }
            elif has_login_btn or has_qrcode:
                return {
                    "logged_in": False,
                    "message": "未登录，请扫码登录"
                }
            else:
                return {
                    "logged_in": False,
                    "message": "登录状态未知"
                }

        except Exception as e:
            from app.logging_config import api_logger
            api_logger.error(f"检查登录状态失败: {e}")
            return {
                "logged_in": False,
                "error": str(e)
            }


# 全局单例
browser_manager = BrowserManager()
