"""
BOSS直聘浏览器自动化核心模块
"""
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext
from typing import Optional, List, Dict
import time
from .config import BOSS_URL, HEADLESS, SLOW_MO, TIMEOUT, GREETING_TEMPLATES
from .utils import log, random_delay, check_school_whitelist, extract_candidate_info


class BossRPA:
    """BOSS直聘RPA自动化"""
    
    def __init__(self, headless: bool = HEADLESS):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        
    def start(self):
        """启动浏览器"""
        log("启动浏览器...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless,
            slow_mo=SLOW_MO,
        )
        self.context = self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(TIMEOUT)
        log("浏览器启动成功", "SUCCESS")
        
    def stop(self):
        """关闭浏览器"""
        if self.page:
            self.page.close()
        if self.context:
            self.context.close()
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        log("浏览器已关闭", "SUCCESS")
        
    def login(self):
        """
        登录BOSS直聘
        注意：需要手动扫码登录
        """
        log("打开BOSS直聘...")
        self.page.goto(BOSS_URL)
        
        # 等待用户手动登录
        log("请在浏览器中完成登录（扫码或密码）", "WARNING")
        log("登录完成后，按Enter继续...", "WARNING")
        input()
        
        # 验证登录状态
        try:
            self.page.wait_for_selector("text=消息", timeout=5000)
            log("登录成功", "SUCCESS")
            return True
        except:
            log("登录失败，请重试", "ERROR")
            return False
            
    def goto_recommend_page(self):
        """进入推荐牛人页面"""
        log("进入推荐牛人页面...")
        
        # 点击"推荐"或"发现"
        try:
            recommend_btn = self.page.locator("text=推荐").first
            recommend_btn.click()
            log("点击推荐按钮", "SUCCESS")
        except:
            log("未找到推荐按钮，尝试其他方式", "WARNING")
            self.page.goto(f"{BOSS_URL}/web/geek/recommend")
        
        random_delay(2, 3)
        
    def open_filter_panel(self):
        """打开筛选面板"""
        log("打开筛选面板...")
        
        try:
            # 查找筛选按钮（可能的文本：筛选、高级筛选）
            filter_btn = self.page.locator("text=/筛选|高级筛选/").first
            filter_btn.click()
            log("筛选面板已打开", "SUCCESS")
            random_delay(1, 2)
            return True
        except Exception as e:
            log(f"打开筛选面板失败: {e}", "ERROR")
            return False
            
    def set_education_filter(self):
        """设置学历筛选（985/211/本科）"""
        log("设置学历筛选...")
        
        try:
            # 查找并点击985选项
            try:
                option_985 = self.page.locator("text=985").first
                option_985.click()
                log("已勾选985", "SUCCESS")
                random_delay(0.5, 1)
            except:
                log("未找到985选项", "WARNING")
            
            # 查找并点击211选项
            try:
                option_211 = self.page.locator("text=211").first
                option_211.click()
                log("已勾选211", "SUCCESS")
                random_delay(0.5, 1)
            except:
                log("未找到211选项", "WARNING")
            
            # 查找并点击本科选项
            try:
                option_bachelor = self.page.locator("text=本科").first
                option_bachelor.click()
                log("已勾选本科", "SUCCESS")
                random_delay(0.5, 1)
            except:
                log("未找到本科选项", "WARNING")
                
            return True
        except Exception as e:
            log(f"设置学历筛选失败: {e}", "ERROR")
            return False
            
    def confirm_filter(self):
        """点击确定按钮确认筛选"""
        log("确认筛选...")
        
        try:
            # 查找确定按钮（可能的文本：确定、确认、应用）
            confirm_btn = self.page.locator("button:has-text('确定'), button:has-text('确认'), button:has-text('应用')").first
            confirm_btn.click()
            log("筛选已确认", "SUCCESS")
            random_delay(2, 3)
            return True
        except Exception as e:
            log(f"确认筛选失败: {e}", "ERROR")
            # 尝试按Enter键
            try:
                self.page.keyboard.press("Enter")
                log("使用Enter键确认", "SUCCESS")
                random_delay(2, 3)
                return True
            except:
                return False
                
    def get_candidate_cards(self) -> List:
        """获取当前页面的候选人卡片"""
        try:
            # 等待候选人卡片加载
            self.page.wait_for_selector(".geek-item, .candidate-item, [class*='geek'], [class*='candidate']", timeout=5000)
            
            # 获取所有候选人卡片
            cards = self.page.locator(".geek-item, .candidate-item, [class*='geek-card'], [class*='candidate-card']").all()
            log(f"找到 {len(cards)} 个候选人卡片", "SUCCESS")
            return cards
        except Exception as e:
            log(f"获取候选人卡片失败: {e}", "ERROR")
            return []
            
    def extract_school_from_card(self, card) -> Optional[str]:
        """从候选人卡片中提取学校信息"""
        try:
            # 获取卡片的所有文本
            text = card.inner_text()
            
            # 检查是否在白名单中
            matched_school = check_school_whitelist(text)
            
            if matched_school:
                log(f"匹配到白名单学校: {matched_school}", "SUCCESS")
                return matched_school
            else:
                log(f"未匹配到白名单学校", "DEBUG")
                return None
                
        except Exception as e:
            log(f"提取学校信息失败: {e}", "ERROR")
            return None
            
    def click_greet_button(self, card):
        """点击打招呼按钮"""
        try:
            # 查找打招呼按钮（可能的文本：打招呼、立即沟通、开始聊天）
            greet_btn = card.locator("button:has-text('打招呼'), button:has-text('立即沟通'), button:has-text('开始聊天')").first
            greet_btn.click()
            log("点击打招呼按钮", "SUCCESS")
            random_delay(1, 2)
            return True
        except Exception as e:
            log(f"点击打招呼按钮失败: {e}", "ERROR")
            return False
            
    def send_greeting_message(self, message: str):
        """发送打招呼消息"""
        try:
            # 查找输入框
            input_box = self.page.locator("textarea, input[type='text']").first
            input_box.fill(message)
            random_delay(0.5, 1)
            
            # 查找发送按钮
            send_btn = self.page.locator("button:has-text('发送'), button:has-text('确定')").first
            send_btn.click()
            log("消息已发送", "SUCCESS")
            random_delay(2, 3)
            return True
        except Exception as e:
            log(f"发送消息失败: {e}", "ERROR")
            return False
            
    def scan_and_greet(self, limit: int = 50) -> Dict:
        """
        扫描并打招呼
        
        返回统计信息：
        {
            "scanned": 扫描总数,
            "matched": 匹配白名单数,
            "greeted": 成功打招呼数,
            "failed": 失败数,
        }
        """
        stats = {
            "scanned": 0,
            "matched": 0,
            "greeted": 0,
            "failed": 0,
        }
        
        log(f"开始扫描候选人（限制{limit}个）...")
        
        while stats["scanned"] < limit:
            # 获取当前页面的候选人卡片
            cards = self.get_candidate_cards()
            
            if not cards:
                log("未找到候选人卡片，可能已到底部", "WARNING")
                break
            
            for card in cards:
                if stats["scanned"] >= limit:
                    break
                    
                stats["scanned"] += 1
                log(f"扫描第 {stats['scanned']} 个候选人...")
                
                # 提取学校信息
                school = self.extract_school_from_card(card)
                
                if school:
                    stats["matched"] += 1
                    log(f"匹配到白名单学校: {school}", "SUCCESS")
                    
                    # 点击打招呼
                    if self.click_greet_button(card):
                        # 发送消息
                        import random
                        message = random.choice(GREETING_TEMPLATES).format(
                            position="Python开发工程师",
                            salary="25-40K",
                            company="我们公司"
                        )
                        
                        if self.send_greeting_message(message):
                            stats["greeted"] += 1
                        else:
                            stats["failed"] += 1
                            
                        # 关闭对话框
                        try:
                            close_btn = self.page.locator("button:has-text('关闭'), button:has-text('取消'), .close-btn").first
                            close_btn.click()
                            random_delay(0.5, 1)
                        except:
                            pass
                    else:
                        stats["failed"] += 1
                else:
                    log("未匹配白名单，跳过", "DEBUG")
                
                random_delay(1, 2)
            
            # 滚动到底部加载更多
            log("滚动加载更多...")
            self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            random_delay(2, 3)
        
        log("扫描完成", "SUCCESS")
        log(f"统计: 扫描{stats['scanned']}个，匹配{stats['matched']}个，成功{stats['greeted']}个，失败{stats['failed']}个")
        
        return stats
