#!/usr/bin/env python3
"""
BOSS直聘 · 简历获取轮转系统 v2.0
===================================
基于Playwright的纯DOM操作 + OCR保底方案
无需屏幕录制权限，跨macOS版本兼容

核心流程（每条候选人）:
  1. 从左侧沟通列表选中候选人
  2. 获取简历:
     ├─ 深蓝"附件简历" → 预览PDF → 点下载 → 关预览
     └─ 浅蓝"在线简历"/无简历 → 点"求简历" → 确认弹窗
  3. 换微信 → 确认弹窗
  4. 轮转到下一个候选人
"""
import sys, os, time, json, random
from datetime import datetime
from typing import Optional, List, Dict, Tuple

# 项目根目录
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# ============================================================
# 日志系统
# ============================================================
def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌","ACT":"🖱️","SKIP":"⏭️","DB":"💾"}.get(level, "•")
    print(f"[{ts}] {icon} {msg}")


def json_log(data: dict, level: str = "DB"):
    """JSON格式的结构化日志"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] 💾 {json.dumps(data, ensure_ascii=False)}")


# ============================================================
# BOSS直聘Playwright控制器 v2.0
# ============================================================

class BossResumeCollector:
    """
    BOSS直聘简历收集器
    
    使用Playwright接管浏览器，完成简历下载+换微信的全流程
    """
    
    # ---- 选择器常量 ----
    
    # 左侧导航
    NAV_CHAT_SELECTOR = "a.nav-item:has-text('沟通'), a[href*='chat'], a:has-text('沟通')"
    
    # 沟通列表 - 候选人项
    CANDIDATE_ITEM = "div.chat-list-item, li.chat-item, div[class*='chat-item'], div[class*='chat-list-']"
    CANDIDATE_NAME = "span.name, h3.name, .candidate-name, [class*='name']"
    
    # 聊天区域 - 按钮区
    BTN_REQUEST_RESUME = "button:has-text('求简历'), button:has-text('索要简历'), span:has-text('求简历')"
    BTN_ATTACH_RESUME = "a:has-text('附件简历'), button:has-text('附件简历'), span:has-text('附件简历')"
    BTN_ONLINE_RESUME = "a:has-text('在线简历'), button:has-text('在线简历')"
    BTN_WECHAT = "button:has-text('换微信'), span:has-text('换微信'), [class*='wechat']"
    
    # 弹窗
    POPUP_CONFIRM = "button:has-text('确定'), button:has-text('确认'), div.confirm-btn, [class*='confirm']"
    POPUP_CANCEL = "button:has-text('取消'), button:has-text('取消')"
    POPUP_DIALOG = "div.dialog, div.modal, div[class*='dialog'], div[class*='modal']"
    
    # 简历预览
    RESUME_PREVIEW = "div.resume-preview, div[class*='resume-preview'], iframe#resumePreview, embed[type='application/pdf']"
    RESUME_DOWNLOAD = "button:has-text('下载'), a:has-text('下载'), [class*='download'], [title*='下载'], [aria-label*='下载']"
    
    # 简历预览外的灰色蒙层
    PREVIEW_OVERLAY = "div.overlay, div[class*='overlay'], div.mask, div[class*='mask']"
    
    # 右侧聊天面板
    CHAT_PANEL = "div.chat-panel, div[class*='chat-panel'], div[class*='chat-main']"
    
    def __init__(self, headless: bool = False, slow_mo: int = 300):
        self.headless = headless
        self.slow_mo = slow_mo
        self.page = None
        self.browser = None
        self.context = None
        self.playwright = None
        self.stats = {"processed": 0, "downloaded": 0, "requested": 0, 
                       "wechat": 0, "failed": 0, "skipped": 0}
        self.candidate_count = 0  # 实时记录处理到的序号
    
    # ---- 生命周期 ----
    
    def start(self, url: str = "https://www.zhipin.com"):
        """启动浏览器; 返回页面对象"""
        from playwright.sync_api import sync_playwright
        
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--window-size=1920,1080',
            ]
        )
        self.context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        # 注入反检测脚本
        self.context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = {runtime: {}};
        """)
        
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)
        
        # 打开BOSS直聘
        log(f"打开BOSS直聘: {url}")
        self.page.goto(url, wait_until="domcontentloaded")
        log("浏览器已启动，请登录...", "WARN")
        
        return self.page
    
    def stop(self):
        """关闭浏览器"""
        try:
            if self.page: self.page.close()
            if self.context: self.context.close()
            if self.browser: self.browser.close()
            if self.playwright: self.playwright.stop()
        except:
            pass
        log("浏览器已关闭")
    
    def wait_login(self, timeout_seconds: int = 300):
        """等待用户在浏览器中登录，超时后抛出异常"""
        log("请在浏览器中扫码/密码登录BOSS直聘...", "WARN")
        
        # 等待跳转到登录后页面（检测沟通入口）
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                current_url = self.page.url
                log(f"当前URL: {current_url[:80]}")
                
                # 检测是否登录成功（看页面URL是否包含chat/geek/wap等）
                if any(kw in current_url for kw in ['web/chat', 'web/geek', 'chat', 'geek/list']):
                    log("检测到已登录！", "OK")
                    return True
                
                # 如果页面包含招聘者相关文字
                body_text = self.page.inner_text('body')
                if any(kw in body_text for kw in ['推荐牛人', '沟通', '职位管理', '简历']):
                    log("检测到登录成功（文字匹配）！", "OK")
                    return True
                
                # 等待并重试
                time.sleep(2)
            except Exception as e:
                log(f"等待登录: {e}", "WARN")
                time.sleep(2)
        
        raise TimeoutError("登录超时，请重新运行")
    
    # ---- 核心步骤 ----
    
    def goto_chat_page(self):
        """进入沟通页面"""
        log("进入沟通页面...")
        
        # 直接导航到沟通页
        self.page.goto("https://www.zhipin.com/web/chat/", wait_until="domcontentloaded")
        time.sleep(2)
        
        # 等待候选人列表加载
        try:
            self.page.wait_for_function(
                "() => document.querySelectorAll('[class*=\"chat\"]').length > 0 || document.querySelectorAll('li').length > 5",
                timeout=10000
            )
        except:
            pass
        
        log("沟通页面已加载")
        return True
    
    def count_candidates(self) -> int:
        """统计左侧沟通列表有多少候选人"""
        try:
            # 尝试多种选择器
            selectors = [
                "li.chat-list-item",
                "div[class*='chat-item']",
                "div[class*='session-item']",
                "div.chat-session-list > div",
                "ul li",  # 宽泛匹配，但只看左侧区域
            ]
            
            for sel in selectors:
                items = self.page.query_selector_all(sel)
                if len(items) > 3:
                    log(f"候选人列表: {len(items)} 人 (选择器: {sel})")
                    return len(items)
            
            # 兜底: 用XPath找所有列表项
            count = self.page.evaluate("""
                () => {
                    // 左侧列表区域通常是 nav + main 结构
                    const main = document.querySelector('main') || document.body;
                    const items = main.querySelectorAll('li, [role="listitem"], [class*="item"], [class*="list-"]');
                    return items.length;
                }
            """)
            log(f"候选人列表(页面分析): {count} 人")
            return count or 0
        except Exception as e:
            log(f"统计候选人失败: {e}", "WARN")
            return 0
    
    def navigate_to_candidate(self, index: int):
        """
        点击左侧列表中的第 index 个候选人（0-based）
        返回是否成功
        """
        self.candidate_count = index + 1
        log(f"选中候选人 #{index+1}...")
        
        try:
            # 策略1: 用精确选择器
            items = self.page.query_selector_all(self.CANDIDATE_ITEM)
            if items and len(items) > index:
                items[index].click()
                time.sleep(1.5)
                log(f"点击候选人 #{index+1}", "ACT")
                return True
            
            # 策略2: 用 evaluate 点击
            clicked = self.page.evaluate(f"""
                () => {{
                    // 找到左侧聊天列表的所有可点击项
                    const lists = document.querySelectorAll('main li, [class*="chat"] li, [class*="session"] li, [class*="list-item"]');
                    const items = Array.from(lists).filter(el => {{
                        const rect = el.getBoundingClientRect();
                        // 只取左侧区域 (x < 400)
                        return rect.left < 400 && rect.width > 50 && rect.height > 20;
                    }});
                    if (items.length > {index}) {{
                        items[{index}].click();
                        return true;
                    }}
                    return false;
                }}
            """)
            
            if clicked:
                time.sleep(1.5)
                log(f"点击候选人 #{index+1} (动态选择)", "ACT")
                return True
            
            # 策略3: 直接JS点击坐标
            log("尝试坐标点击...", "WARN")
            # 先获取左侧列表范围
            result = self.page.evaluate(f"""
                () => {{
                    const items = Array.from(document.querySelectorAll('li, div[class*="item"], div[class*="list-"]'));
                    const leftItems = items.filter(el => {{
                        const r = el.getBoundingClientRect();
                        return r.left < 400 && r.width > 50 && r.height > 20;
                    }});
                    if (leftItems.length > {index}) {{
                        const r = leftItems[{index}].getBoundingClientRect();
                        return {{x: r.left + r.width/2, y: r.top + r.height/2, text: el => el.textContent?.trim().substring(0,20)}};
                    }}
                    return null;
                }}
            """)
            
            if result:
                self.page.mouse.click(result['x'], result['y'])
                time.sleep(1.5)
                log(f"坐标点击候选人 #{index+1}", "ACT")
                return True
            
            log(f"无法定位候选人 #{index+1}", "ERR")
            return False
            
        except Exception as e:
            log(f"导航到候选人失败: {e}", "ERR")
            return False
    
    def get_candidate_name(self) -> str:
        """获取当前选中候选人的名字"""
        try:
            name = self.page.evaluate("""
                () => {
                    // 找聊天面板顶部的候选人名字
                    const nameEl = document.querySelector(
                        'h3.name, span.name, [class*="candidate-name"], ' +
                        '[class*="user-name"], .chat-header span, .session-header span'
                    );
                    return nameEl ? nameEl.textContent.trim() : '未知';
                }
            """)
            return str(name or "未知")
        except:
            return "未知"
    
    def get_resume(self, candidate_name: str) -> Dict:
        """
        获取简历 - 核心方法
        
        Returns: {"status": "downloaded"|"requested"|"already_has"|"failed", "detail": str}
        """
        log(f"📄 [{candidate_name}] 获取简历...")
        
        # === 策略A: 检查是否有深蓝色"附件简历"按钮（已有简历可下载）===
        try:
            # 检测附件简历按钮是否存在且可点击
            if self._try_attach_resume(candidate_name):
                return {"status": "downloaded", "detail": "简历已下载"}
        except Exception as e:
            log(f"附件简历流程异常: {e}", "WARN")
        
        # === 策略B: 没有简历/浅蓝按钮 → 点"求简历"===
        try:
            if self._try_request_resume(candidate_name):
                return {"status": "requested", "detail": "已发送简历请求"}
        except Exception as e:
            log(f"求简历流程异常: {e}", "WARN")
        
        log(f"[{candidate_name}] ❌ 获取简历失败", "ERR")
        return {"status": "failed", "detail": "所有策略失败"}
    
    def _try_attach_resume(self, name: str) -> bool:
        """尝试点击附件简历并下载"""
        
        # 1. 找附件简历按钮
        btn = None
        for sel, label in [
            (self.BTN_ATTACH_RESUME, "附件简历(文字)"),
            ("[class*='attach']", "附件简历(CSS)"),
            ("a[href*='resume']", "简历链接"),
        ]:
            try:
                btn = self.page.query_selector(sel)
                if btn:
                    log(f"找到{label}: {btn.text_content()[:20] if btn.text_content() else '未知'}", "OK")
                    break
            except:
                continue
        
        if not btn:
            log("未找到附件简历按钮", "WARN")
            return False
        
        # 2. 检查按钮颜色（深蓝=已发送，浅蓝=在线简历）
        button_color = self.page.evaluate("""
            (selector) => {
                const el = document.querySelector(selector);
                if (!el) return 'unknown';
                const style = window.getComputedStyle(el);
                const bg = style.backgroundColor;
                const color = style.color;
                return JSON.stringify({bg, color, text: el.textContent?.trim()});
            }
        """, self.BTN_ATTACH_RESUME)
        
        log(f"按钮状态: {button_color}", "DEBUG")
        
        # 3. 点击附件简历
        btn.click()
        time.sleep(2)
        
        # 4. 检测是否弹出了简历预览
        if self._is_resume_preview_open():
            log(f"[{name}] ✅ 简历预览已弹出", "OK")
            return self._download_from_preview(name)
        
        # 5. 如果没有简历预览，可能是弹出了确认弹窗（候选人还没发）
        if self._is_confirm_popup_open():
            log(f"[{name}] 简历尚未发送，弹出确认弹窗", "INFO")
            self._click_confirm()
            return True
        
        log(f"[{name}] 点击附件简历后无反应", "WARN")
        return False
    
    def _is_resume_preview_open(self) -> bool:
        """检测是否弹出了简历预览窗口"""
        try:
            # 方法1: 检查iframe/embed
            for sel in ["iframe", "embed[type='application/pdf']", "object[type='application/pdf']"]:
                if self.page.query_selector(sel):
                    return True
            
            # 方法2: 检查下载按钮出现
            for sel in ["button:has-text('下载')", "[class*='download']", "[title*='下载']"]:
                if self.page.query_selector(sel):
                    return True
            
            # 方法3: 检查大浅色区域（PDF预览特征）
            has_preview = self.page.evaluate("""
                () => {
                    // 检测是否有iframe或embed渲染了简历
                    const frames = document.querySelectorAll('iframe, embed, object');
                    for (const f of frames) {
                        const rect = f.getBoundingClientRect();
                        if (rect.width > 300 && rect.height > 300) return true;
                    }
                    // 检测是否有蒙层+大弹窗
                    const overlays = document.querySelectorAll('.overlay, [class*="overlay"], .mask, [class*="mask"]');
                    if (overlays.length > 0) return true;
                    // 检测是否有全屏预览容器
                    const previews = document.querySelectorAll('[class*="resume"]');
                    for (const p of previews) {
                        const r = p.getBoundingClientRect();
                        if (r.width > 400 && r.height > 300) return true;
                    }
                    return false;
                }
            """)
            return bool(has_preview)
        except:
            return False
    
    def _is_confirm_popup_open(self) -> bool:
        """检测是否有确认弹窗"""
        try:
            for sel in [self.POPUP_DIALOG, "div[class*='dialog']", "div[class*='confirm']", self.POPUP_CONFIRM]:
                el = self.page.query_selector(sel)
                if el and el.is_visible():
                    return True
            
            has_popup = self.page.evaluate("""
                () => {
                    // 检查是否有模态弹窗
                    const dialogs = document.querySelectorAll('.dialog, [class*="dialog"], .modal, [class*="modal"]');
                    for (const d of dialogs) {
                        const r = d.getBoundingClientRect();
                        if (r.width > 200 && r.height > 100) return true;
                    }
                    // 检查"确定向牛人请求简历"这样的文字
                    const body = document.body.textContent || '';
                    return body.includes('确定向') && body.includes('请求简历');
                }
            """)
            return bool(has_popup)
        except:
            return False
    
    def _click_confirm(self, wait: float = 1.5):
        """点击弹窗中的确定/确认按钮"""
        try:
            btn = self.page.query_selector(self.POPUP_CONFIRM)
            if btn:
                btn.click()
                log("点击确认按钮", "ACT")
                time.sleep(wait)
            else:
                # 键盘Enter
                self.page.keyboard.press("Enter")
                log("按Enter确认", "ACT")
                time.sleep(wait)
        except Exception as e:
            log(f"点击确认失败: {e}", "WARN")
            self.page.keyboard.press("Enter")
            time.sleep(wait)
    
    def _download_from_preview(self, name: str) -> bool:
        """从简历预览中下载PDF"""
        
        # 1. 找下载按钮
        download_btn = None
        for sel in [
            self.RESUME_DOWNLOAD,
            "[class*='download']",
            "button[class*='down']",
            "a[download]",
            "a[href$='.pdf']",
        ]:
            try:
                dbtn = self.page.query_selector(sel)
                if dbtn and dbtn.is_visible():
                    download_btn = dbtn
                    log(f"找到下载按钮: {dbtn.text_content()[:20] if dbtn.text_content() else 'icon'}", "OK")
                    break
            except:
                continue
        
        if download_btn:
            # 用Playwright的下载事件监听下载
            try:
                with self.page.expect_download(timeout=8000) as download_info:
                    download_btn.click()
                
                download = download_info.value
                
                # 保存到 Downloads 目录
                os.makedirs(os.path.expanduser("~/Downloads/BossResumes"), exist_ok=True)
                save_path = os.path.expanduser(f"~/Downloads/BossResumes/{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
                download.save_as(save_path)
                log(f"[{name}] ✅ 简历已下载: {save_path}", "OK")
                time.sleep(1)
            except Exception as e:
                log(f"下载失败: {e}，尝试点击下载按钮", "WARN")
                try:
                    download_btn.click()
                    time.sleep(3)
                    log(f"[{name}] 已触发下载（浏览器默认保存）", "OK")
                except:
                    pass
        else:
            log("未找到下载按钮", "WARN")
        
        # 2. 退出预览（点击灰色蒙层或外部区域）
        self._close_preview()
        return True
    
    def _close_preview(self):
        """关闭简历预览"""
        # 点击蒙层/遮罩
        for sel in [self.PREVIEW_OVERLAY, "div.overlay", "div.mask", "[class*='overlay']", "[class*='mask']"]:
            try:
                overlay = self.page.query_selector(sel)
                if overlay:
                    overlay.click(position={"x": 10, "y": 10})
                    log("已点击蒙层关闭预览", "ACT")
                    time.sleep(1)
                    return
            except:
                continue
        
        # 按ESC键
        try:
            self.page.keyboard.press("Escape")
            log("按ESC关闭预览", "ACT")
            time.sleep(1)
        except:
            pass
    
    def _try_request_resume(self, name: str) -> bool:
        """尝试点击'求简历'按钮"""
        
        # 1. 找"求简历"按钮
        for sel, label in [
            (self.BTN_REQUEST_RESUME, "求简历"),
            ("button:has-text('求简历')", "求简历(button)"),
            ("[class*='request-resume']", "request-resume"),
        ]:
            try:
                btn = self.page.query_selector(sel)
                if btn and btn.is_visible():
                    log(f"找到{label}按钮", "OK")
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    time.sleep(1.5)
                    
                    # 确认弹窗
                    if self._is_confirm_popup_open():
                        log(f"[{name}] ✅ 弹出确认窗", "OK")
                        self._click_confirm()
                        return True
                    else:
                        log(f"[{name}] 点击无确认弹窗", "WARN")
                    break
            except:
                continue
        
        return False
    
    def exchange_wechat(self, name: str) -> bool:
        """换微信"""
        log(f"📱 [{name}] 换微信...")
        time.sleep(0.5)
        
        for sel, label in [
            (self.BTN_WECHAT, "换微信"),
            ("[class*='wechat']", "wechat类"),
            ("button:has-text('微信')", "微信"),
        ]:
            try:
                btn = self.page.query_selector(sel)
                if btn:
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    log(f"点击{label}按钮", "ACT")
                    time.sleep(1.5)
                    
                    # 确认弹窗："确定与对方交换微信吗？"
                    if self._is_confirm_popup_open():
                        log(f"[{name}] ✅ 微信交换确认窗弹出", "OK")
                        self._click_confirm()
                        log(f"[{name}] ✅ 微信交换完成", "OK")
                        return True
                    else:
                        log(f"[{name}] 无确认弹窗，可能已直接发送", "INFO")
                        return True
            except:
                continue
        
        log(f"[{name}] ❌ 换微信失败", "ERR")
        return False
    
    def scroll_to_show_more_candidates(self):
        """滚动左侧候选人列表显示更多"""
        try:
            self.page.evaluate("""
                () => {
                    // 找左侧列表容器并滚动
                    const scrolls = document.querySelectorAll('[class*="scroll"], [class*="list"], main nav, main > div');
                    for (const s of scrolls) {
                        const r = s.getBoundingClientRect();
                        if (r.left < 400) {
                            s.scrollTop += 200;
                            return true;
                        }
                    }
                    // 兜底: 滚动main
                    const main = document.querySelector('main');
                    if (main) main.scrollBy(0, 200);
                }
            """)
            time.sleep(1)
            log("已滚动候选人列表", "ACT")
        except:
            pass
    
    def process_all_candidates(self, max_count: int = 100) -> Dict:
        """
        主流程：批量处理候选人
        
        Returns: 统计结果
        """
        log("=" * 60)
        log("🚀 BOSS直聘 · 简历获取轮转系统 v2.0")
        log(f"   上限: {max_count} 人")
        log("=" * 60)
        
        self.stats = {"processed": 0, "downloaded": 0, "requested": 0,
                       "wechat": 0, "failed": 0, "skipped": 0}
        
        # 先统计总数
        total_candidates = self.count_candidates()
        if total_candidates == 0:
            log("未检测到候选人，尝试滚动...", "WARN")
            self.scroll_to_show_more_candidates()
            total_candidates = self.count_candidates()
        
        actual_max = min(max_count, total_candidates or max_count)
        log(f"目标处理: {actual_max} 人 (列表中{total_candidates}人)")
        
        # 逐个处理
        for i in range(actual_max):
            log(f"\n{'─'*50}")
            log(f"👤 [{i+1}/{actual_max}] 处理中...")
            log(f"{'─'*50}")
            
            try:
                # Step 1: 导航到候选人
                if not self.navigate_to_candidate(i):
                    self.stats["failed"] += 1
                    continue
                
                # Step 2: 获取候选人名字
                candidate_name = self.get_candidate_name()
                log(f"当前候选人: {candidate_name}")
                
                # Step 3: 获取简历
                resume_status = self.get_resume(candidate_name)
                
                # 更新统计
                if resume_status["status"] == "downloaded":
                    self.stats["downloaded"] += 1
                elif resume_status["status"] == "requested":
                    self.stats["requested"] += 1
                elif resume_status["status"] == "already_has":
                    self.stats["downloaded"] += 1
                else:
                    self.stats["failed"] += 1
                
                # Step 4: 换微信
                time.sleep(0.5)
                wechat_success = self.exchange_wechat(candidate_name)
                if wechat_success:
                    self.stats["wechat"] += 1
                
                self.stats["processed"] += 1
                
                # 第5个候选人后滚动一次列表
                if i > 0 and i % 5 == 0:
                    self.scroll_to_show_more_candidates()
                
            except Exception as e:
                log(f"❌ 处理异常: {e}", "ERR")
                import traceback
                traceback.print_exc()
                self.stats["failed"] += 1
            
            # 候选人之间的延迟（防止被风控）
            delay = random.uniform(2, 4)
            log(f"⏳ 等待 {delay:.1f} 秒...")
            time.sleep(delay)
        
        # 输出统计
        self._print_stats()
        return self.stats
    
    def _print_stats(self):
        """输出统计信息"""
        log(f"\n{'='*50}")
        log(f"🎉 处理完成!")
        log(f"  处理总数:  {self.stats['processed']}")
        log(f"  简历已下载: {self.stats['downloaded']}")
        log(f"  简历已请求: {self.stats['requested']}")
        log(f"  微信已换:   {self.stats['wechat']}")
        log(f"  失败:       {self.stats['failed']}")
        log(f"{'='*50}")
        
        json_log(self.stats)

    def debug_candidates(self):
        """调试模式：检测候选人列表结构"""
        
        log("===== 候选人列表调试 =====")
        
        # 分析页面结构
        structure = self.page.evaluate("""
            () => {
                const result = {};
                
                // 1. 所有li元素
                const allLis = document.querySelectorAll('li');
                result.li_count = allLis.length;
                
                // 2. 左侧区域的元素
                const leftItems = [];
                document.querySelectorAll('li, [role="listitem"], [class*="item"], [class*="list-"], div[class*="session"]').forEach(el => {
                    const r = el.getBoundingClientRect();
                    if (r.left < 400 && r.width > 50) {
                        leftItems.push({
                            tag: el.tagName,
                            text: (el.textContent || '').trim().substring(0, 30),
                            rect: {left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height)},
                            classes: (el.className || '').substring(0, 60),
                        });
                    }
                });
                result.left_items = leftItems;
                
                // 3. 当前页面URL
                result.url = window.location.href;
                
                // 4. 页面标题
                result.title = document.title;
                
                // 5. 按钮检测
                const allButtons = [];
                document.querySelectorAll('button, a[href], span[class*="btn"]').forEach(el => {
                    const text = (el.textContent || '').trim();
                    if (text && text.length < 20 && (
                        text.includes('简历') || text.includes('微信') || text.includes('沟通')
                        || text.includes('下载') || text.includes('确定') || text.includes('确认')
                    )) {
                        const r = el.getBoundingClientRect();
                        allButtons.push({
                            text,
                            rect: {left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height)},
                            tag: el.tagName,
                        });
                    }
                });
                result.buttons = allButtons;
                
                return result;
            }
        """)
        
        log(f"URL: {structure.get('url', '?')}")
        log(f"页面标题: {structure.get('title', '?')}")
        log(f"全部li元素数: {structure.get('li_count', '?')}")
        
        log(f"\n左侧列表项 ({len(structure.get('left_items', []))} 项):")
        for item in structure.get('left_items', [])[:15]:
            r = item['rect']
            log(f"  {item['tag']:6s} | ({r['left']:4d},{r['top']:4d}) {r['width']:3d}x{r['height']:3d} | {item['text'][:25]:25s} | {item['classes']}")
        
        log(f"\n检测到的按钮 ({len(structure.get('buttons', []))} 个):")
        for btn in structure.get('buttons', [])[:20]:
            r = btn['rect']
            log(f"  [{btn['tag']:6s}] {btn['text']:12s} | ({r['left']:4d},{r['top']:4d}) {r['width']:3d}x{r['height']:3d}")
        
        return structure


# ============================================================
# 命令行入口
# ============================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="BOSS直聘 · 简历获取轮转系统 v2.0")
    parser.add_argument("--limit", type=int, default=10, help="处理上限人数")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--debug", action="store_true", help="调试模式：只分析页面结构，不执行操作")
    parser.add_argument("--slow", type=int, default=300, help="操作延迟(ms)")
    args = parser.parse_args()
    
    collector = BossResumeCollector(headless=args.headless, slow_mo=args.slow)
    
    try:
        # 启动
        collector.start()
        
        # 等待登录（300秒超时）
        collector.wait_login(timeout_seconds=300)
        
        # 调试模式：分析页面结构
        if args.debug:
            collector.goto_chat_page()
            time.sleep(2)
            collector.debug_candidates()
            return
        
        # 进入沟通页面
        collector.goto_chat_page()
        time.sleep(2)
        
        # 批量处理
        stats = collector.process_all_candidates(max_count=args.limit)
        
        if stats["processed"] > 0:
            log("\n🎉 全部完成!")
        else:
            log("\n⚠️ 未处理任何候选人")
            log("提示: 请检查浏览器中是否有沟通记录")
    
    except KeyboardInterrupt:
        log("\n用户中断", "WARN")
    except Exception as e:
        log(f"严重错误: {e}", "ERR")
        import traceback
        traceback.print_exc()
    finally:
        collector.stop()


if __name__ == "__main__":
    main()
