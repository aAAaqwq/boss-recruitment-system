#!/usr/bin/env python3
"""
BOSS直聘自动化招聘系统 v2.0
基于Playwright - 跨平台、轻量化、易部署

功能：
- 自动打招呼
- 自动获取简历  
- AI自动对话

安装依赖：
    pip install playwright
    playwright install chromium

使用方式：
    python boss_auto_v2.py --mode greet|resume|chat|all
"""

import asyncio
import random
import argparse
import json
import os
from datetime import datetime
from typing import Optional, List, Dict

# Playwright
try:
    from playwright.async_api import async_playwright, Page, Browser
except ImportError:
    print("❌ 请先安装Playwright: pip install playwright")
    print("   然后运行: playwright install chromium")
    exit(1)

# ============================================================
# 配置
# ============================================================

DEFAULT_CONFIG = {
    "boss_url": "https://www.zhipin.com",
    "daily_greet_cap": 80,
    "school_whitelist": [
        "清华大学", "北京大学", "浙江大学", "复旦大学",
        "上海交通大学", "南京大学", "中国科学技术大学",
        "哈尔滨工业大学", "西安交通大学", "武汉大学",
        "华中科技大学", "中山大学", "同济大学", "南开大学",
        "天津大学", "北京航空航天大学", "北京理工大学",
        "中国人民大学", "东南大学", "四川大学",
    ],
    "delay_min": 1.5,
    "delay_max": 4.0,
    "headless": False,
    "viewport": {"width": 1920, "height": 1080},
}

# 配置文件路径
CONFIG_PATH = os.path.expanduser("~/.boss-recruitment/config.json")


def load_config() -> dict:
    """加载配置"""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            user_config = json.load(f)
            # 合并默认配置
            config = DEFAULT_CONFIG.copy()
            config.update(user_config)
            return config
    return DEFAULT_CONFIG


def save_config(config: dict):
    """保存配置"""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ============================================================
# BOSS直聘自动化类
# ============================================================

class BossAutomation:
    """BOSS直聘自动化"""
    
    def __init__(self, config: dict = None):
        self.config = config or load_config()
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.stats = {
            "greeted": 0,
            "resumes": 0,
            "replied": 0,
            "start_time": None,
        }
    
    async def start(self, headless: bool = None):
        """启动浏览器"""
        self.playwright = await async_playwright().start()
        
        # 使用配置或参数
        if headless is None:
            headless = self.config.get("headless", False)
        
        # 启动Chrome - 使用系统Chrome（解决Apple Silicon兼容性问题）
        import platform
        import os
        
        # 反检测参数
        anti_detect_args = [
            '--no-sandbox',
            '--disable-blink-features=AutomationControlled',  # 关键：隐藏自动化特征
            '--disable-infobars',
            '--disable-dev-shm-usage',
            '--disable-browser-side-navigation',
            '--disable-gpu',
            '--window-size=1920,1080',
        ]
        
        if platform.system() == "Darwin" and platform.machine() == "arm64":
            # Apple Silicon Mac - 使用系统Chrome
            chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
            if os.path.exists(chrome_path):
                self.browser = await self.playwright.chromium.launch(
                    headless=headless,
                    executable_path=chrome_path,
                    args=anti_detect_args
                )
            else:
                self.browser = await self.playwright.chromium.launch(
                    headless=headless,
                    args=anti_detect_args
                )
        else:
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=anti_detect_args
            )
        
        # 创建新页面
        self.page = await self.browser.new_page()
        
        # 反检测：隐藏webdriver特征
        await self.page.add_init_script('''
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
            window.chrome = {runtime: {}};
            Object.defineProperty(navigator, 'permissions', {
                get: () => ({
                    query: () => Promise.resolve({state: 'granted'})
                })
            });
        ''')
        
        # 设置正常的User-Agent
        await self.page.set_extra_http_headers({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        # 设置视口
        viewport = self.config.get("viewport", {"width": 1920, "height": 1080})
        await self.page.set_viewport_size(viewport)
        
        # 记录开始时间
        self.stats["start_time"] = datetime.now()
        
        print("✅ 浏览器已启动")
    
    async def login(self):
        """登录BOSS直聘"""
        if not self.page:
            raise Exception("浏览器未启动")
        
        print("🌐 打开BOSS直聘...")
        await self.page.goto(self.config["boss_url"])
        
        # 等待页面加载
        await self.page.wait_for_load_state("networkidle")
        
        # 检查是否已登录
        try:
            # 查找登录状态的元素
            user_info = await self.page.query_selector(".user-info, .nav-figure, .geek-info")
            if user_info:
                print("✅ 已登录BOSS直聘")
                return
        except:
            pass
        
        # 等待用户登录（自动检测登录状态）
        print("\n" + "="*50)
        print("📱 请在浏览器中登录BOSS直聘")
        print("="*50)
        print("支持以下登录方式：")
        print("  - 微信扫码")
        print("  - 手机验证码")
        print("  - 账号密码")
        print("")
        print("⏳ 等待登录中（自动检测登录状态）...")
        
        # 等待登录状态检测（最多等待120秒）
        logged_in = False
        for i in range(120):
            await asyncio.sleep(1)
            # 检测是否登录成功
            try:
                # 查找登录后的用户信息元素
                user_info = await self.page.query_selector(".user-info, .nav-figure, .geek-info, .user-nav")
                if user_info:
                    logged_in = True
                    break
                # 或者检测URL变化
                url = self.page.url
                if "web/geek" in url or "web/user" in url:
                    logged_in = True
                    break
            except:
                pass
            
            # 每10秒提示一次
            if (i + 1) % 10 == 0:
                print(f"   已等待 {i + 1} 秒...")
        
        if logged_in:
            print("✅ 检测到登录成功")
        else:
            print("⚠️ 登录超时，请手动登录后重试")
    
    async def auto_greet(self, count: int = None) -> int:
        """自动打招呼"""
        print("\n" + "="*50)
        print("👋 开始自动打招呼")
        print("="*50)
        
        if count is None:
            count = self.config.get("daily_greet_cap", 80)
        
        # 导航到推荐页面
        print("📍 导航到推荐候选人页面...")
        await self.page.goto(f"{self.config['boss_url']}/web/geek/recommend")
        await self.page.wait_for_load_state("networkidle")
        
        greeted = 0
        page_num = 1
        
        while greeted < count:
            print(f"\n📄 第 {page_num} 页")
            
            # 等待候选人卡片加载
            await self.page.wait_for_selector(".job-card-wrapper, .candidate-card", timeout=10000)
            
            # 获取候选人列表
            candidates = await self.page.query_selector_all(".job-card-wrapper")
            if not candidates:
                candidates = await self.page.query_selector_all(".candidate-card")
            
            print(f"📋 找到 {len(candidates)} 个候选人")
            
            for candidate in candidates:
                if greeted >= count:
                    break
                
                try:
                    # 获取候选人信息
                    name_elem = await candidate.query_selector(".name, .geek-name")
                    school_elem = await candidate.query_selector(".school, .geek-info-col")
                    
                    name = await name_elem.inner_text() if name_elem else "未知"
                    school_text = ""
                    if school_elem:
                        school_text = await school_elem.inner_text()
                    
                    print(f"\n👤 候选人: {name}")
                    if school_text:
                        print(f"   信息: {school_text[:50]}...")
                    
                    # 检查学校白名单
                    school_whitelist = self.config.get("school_whitelist", [])
                    if school_whitelist and not any(s in school_text for s in school_whitelist):
                        print(f"   ⏭️ 跳过: 学校不在白名单")
                        continue
                    
                    # 点击打招呼按钮
                    greet_btn = await candidate.query_selector(".start-chat-btn, .greet-btn, button[class*='chat']")
                    if greet_btn:
                        await greet_btn.click()
                        greeted += 1
                        self.stats["greeted"] = greeted
                        print(f"   ✅ 已打招呼: {greeted}/{count}")
                        
                        # 随机延迟
                        delay = random.uniform(
                            self.config.get("delay_min", 1.5),
                            self.config.get("delay_max", 4.0)
                        )
                        await asyncio.sleep(delay)
                    
                except Exception as e:
                    print(f"   ⚠️ 处理失败: {e}")
                    continue
            
            # 滚动到下一页或点击下一页按钮
            if greeted < count:
                next_btn = await self.page.query_selector(".ui-pagination-next, .next, a[rel='next']")
                if next_btn:
                    await next_btn.click()
                    await asyncio.sleep(2)
                    page_num += 1
                else:
                    # 滚动加载更多
                    await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await asyncio.sleep(2)
                    page_num += 1
        
        print(f"\n✅ 打招呼完成: {greeted} 人")
        return greeted
    
    async def auto_resume(self, count: int = 10) -> int:
        """自动获取简历"""
        print("\n" + "="*50)
        print("📄 开始获取简历")
        print("="*50)
        
        # 导航到沟通页面
        print("📍 导航到沟通页面...")
        await self.page.goto(f"{self.config['boss_url']}/web/geek/chat")
        await self.page.wait_for_load_state("networkidle")
        
        # 获取联系人列表
        contacts = await self.page.query_selector_all(".chat-item, .contact-item, li[class*='chat']")
        print(f"📋 找到 {len(contacts)} 个联系人")
        
        processed = 0
        for i, contact in enumerate(contacts[:count]):
            try:
                # 点击联系人
                await contact.click()
                await asyncio.sleep(1)
                
                # 查找"获取简历"按钮
                resume_btn = await self.page.query_selector(".get-resume-btn, button[class*='resume'], a[class*='resume']")
                if resume_btn:
                    await resume_btn.click()
                    processed += 1
                    self.stats["resumes"] = processed
                    print(f"✅ 已获取简历: {processed} ({i+1}/{min(count, len(contacts))})")
                    await asyncio.sleep(random.uniform(1, 2))
                else:
                    print(f"⏭️ 联系人 {i+1}: 未找到简历按钮")
                
            except Exception as e:
                print(f"⚠️ 处理联系人 {i+1} 失败: {e}")
                continue
        
        print(f"\n✅ 获取简历完成: {processed} 人")
        return processed
    
    async def auto_chat(self, count: int = 10) -> int:
        """AI自动对话"""
        print("\n" + "="*50)
        print("💬 开始AI自动对话")
        print("="*50)
        
        # 导航到沟通页面
        await self.page.goto(f"{self.config['boss_url']}/web/geek/chat")
        await self.page.wait_for_load_state("networkidle")
        
        # 获取有新消息的联系人
        contacts = await self.page.query_selector_all(".chat-item.unread, .contact-item.unread, li[class*='unread']")
        
        if not contacts:
            print("📭 没有新消息")
            return 0
        
        print(f"📬 找到 {len(contacts)} 个新消息")
        
        replied = 0
        for i, contact in enumerate(contacts[:count]):
            try:
                # 点击联系人
                await contact.click()
                await asyncio.sleep(1)
                
                # 获取最新消息
                messages = await self.page.query_selector_all(".message-item, .chat-message, div[class*='message']")
                if messages:
                    last_message = messages[-1]
                    text = await last_message.inner_text()
                    print(f"\n📩 收到消息: {text[:100]}...")
                    
                    # 生成回复（简化版）
                    reply = self._generate_reply(text)
                    
                    # 输入回复
                    input_box = await self.page.query_selector(".chat-input, textarea, input[type='text']")
                    if input_box:
                        await input_box.fill(reply)
                        await asyncio.sleep(0.5)
                        
                        # 发送
                        send_btn = await self.page.query_selector(".send-btn, button[type='submit']")
                        if send_btn:
                            await send_btn.click()
                            replied += 1
                            self.stats["replied"] = replied
                            print(f"✅ 已回复: {replied}")
                            await asyncio.sleep(random.uniform(1, 2))
                
            except Exception as e:
                print(f"⚠️ 处理消息失败: {e}")
                continue
        
        print(f"\n✅ AI对话完成: {replied} 人")
        return replied
    
    def _generate_reply(self, message: str) -> str:
        """生成回复（简化版，可以接入真正的AI）"""
        replies = [
            "您好，感谢您的关注！请问您对我们公司感兴趣吗？",
            "您好，看到您的消息了，方便详细聊聊吗？",
            "您好，我们的岗位还在招聘中，您可以发送简历吗？",
            "您好，感谢回复！请问您目前是在职还是离职状态？",
        ]
        return random.choice(replies)
    
    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        
        # 打印统计
        print("\n" + "="*50)
        print("📊 运行统计")
        print("="*50)
        if self.stats["start_time"]:
            duration = datetime.now() - self.stats["start_time"]
            print(f"运行时间: {duration}")
        print(f"打招呼: {self.stats['greeted']} 人")
        print(f"获取简历: {self.stats['resumes']} 人")
        print(f"回复消息: {self.stats['replied']} 人")
        print("="*50)


# ============================================================
# 主程序
# ============================================================

async def main():
    parser = argparse.ArgumentParser(description="BOSS直聘自动化系统 v2.0")
    parser.add_argument("--mode", choices=["greet", "resume", "chat", "all"], 
                        default="all", help="运行模式")
    parser.add_argument("--headless", action="store_true", 
                        help="无头模式（不显示浏览器窗口）")
    parser.add_argument("--count", type=int, default=80,
                        help="打招呼/处理数量")
    args = parser.parse_args()
    
    # 加载配置
    config = load_config()
    
    # 创建自动化实例
    bot = BossAutomation(config)
    
    try:
        # 启动浏览器
        await bot.start(headless=args.headless)
        
        # 登录
        await bot.login()
        
        # 根据模式执行
        if args.mode == "greet" or args.mode == "all":
            await bot.auto_greet(count=args.count)
        
        if args.mode == "resume" or args.mode == "all":
            await bot.auto_resume(count=min(10, args.count))
        
        if args.mode == "chat" or args.mode == "all":
            await bot.auto_chat(count=min(10, args.count))
        
    finally:
        await bot.close()


if __name__ == "__main__":
    asyncio.run(main())
