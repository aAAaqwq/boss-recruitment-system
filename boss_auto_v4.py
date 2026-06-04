#!/usr/bin/env python3
"""
BOSS直聘自动化系统 v2.2
使用现有Chrome浏览器（绕过企业版限制）

使用方法：
1. 先手动打开Chrome浏览器
2. 在地址栏输入: chrome://flags/#enable-automation
3. 关闭"Enable Automation"选项
4. 重启Chrome
5. 运行此脚本
"""

import time
import random
import argparse
import json
import os
import subprocess

# Selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# ============================================================
# 配置
# ============================================================

DEFAULT_CONFIG = {
    "boss_url": "https://www.zhipin.com",
    "daily_greet_cap": 80,
    "school_whitelist": [
        "清华大学", "北京大学", "浙江大学", "复旦大学",
        "上海交通大学", "南京大学", "中国科学技术大学",
    ],
    "delay_min": 1.5,
    "delay_max": 4.0,
}

CONFIG_PATH = os.path.expanduser("~/.boss-recruitment/config.json")

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return DEFAULT_CONFIG

# ============================================================
# BOSS直聘自动化类
# ============================================================

class BossAutomation:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.driver = None
        self.stats = {"greeted": 0, "start_time": None}
    
    def start(self):
        """启动浏览器"""
        print("🚀 启动浏览器...")
        
        # 配置Chrome选项
        options = Options()
        
        # 反检测设置
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        
        # 设置User-Agent
        options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # 禁用自动化标志
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # 启动Chrome
        self.driver = webdriver.Chrome(options=options)
        
        # 执行反检测脚本
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': '''
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                window.chrome = {runtime: {}};
            '''
        })
        
        self.stats["start_time"] = time.time()
        print("✅ 浏览器已启动（反检测模式）")
    
    def login(self):
        """登录BOSS直聘"""
        print("🌐 打开BOSS直聘...")
        self.driver.get(self.config["boss_url"])
        
        # 等待页面加载
        time.sleep(3)
        
        print(f"📍 当前页面: {self.driver.title}")
        
        # 检测是否已登录
        try:
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".user-info, .nav-figure"))
            )
            print("✅ 已登录")
            return
        except:
            pass
        
        # 等待用户登录
        print("\n" + "="*50)
        print("📱 请在浏览器中登录BOSS直聘")
        print("="*50)
        print("⏳ 等待登录（自动检测）...")
        
        for i in range(120):
            time.sleep(1)
            try:
                self.driver.find_element(By.CSS_SELECTOR, ".user-info, .nav-figure")
                print("✅ 检测到登录成功")
                return
            except:
                if (i + 1) % 10 == 0:
                    print(f"   已等待 {i + 1} 秒...")
        
        print("⚠️ 登录超时")
    
    def auto_greet(self, count=80):
        """自动打招呼"""
        print("\n" + "="*50)
        print("👋 开始自动打招呼")
        print("="*50)
        
        self.driver.get(f"{self.config['boss_url']}/web/geek/recommend")
        time.sleep(3)
        
        greeted = 0
        while greeted < count:
            # 获取候选人
            candidates = self.driver.find_elements(By.CSS_SELECTOR, ".job-card-wrapper")
            print(f"📋 找到 {len(candidates)} 个候选人")
            
            for c in candidates:
                if greeted >= count:
                    break
                
                try:
                    name = c.find_elements(By.CSS_SELECTOR, ".name")
                    print(f"👤 {name[0].text if name else '未知'}")
                    
                    btn = c.find_elements(By.CSS_SELECTOR, ".start-chat-btn")
                    if btn:
                        btn[0].click()
                        greeted += 1
                        self.stats["greeted"] = greeted
                        print(f"✅ 已打招呼: {greeted}/{count}")
                        time.sleep(random.uniform(1.5, 4.0))
                except Exception as e:
                    print(f"⚠️ {e}")
            
            if greeted < count:
                try:
                    next_btn = self.driver.find_element(By.CSS_SELECTOR, ".next")
                    next_btn.click()
                    time.sleep(2)
                except:
                    break
        
        print(f"✅ 打招呼完成: {greeted} 人")
    
    def close(self):
        if self.driver:
            self.driver.quit()
        print(f"\n📊 统计: 打招呼 {self.stats['greeted']} 人")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="greet")
    parser.add_argument("--count", type=int, default=10)
    args = parser.parse_args()
    
    bot = BossAutomation()
    try:
        bot.start()
        bot.login()
        if args.mode == "greet":
            bot.auto_greet(count=args.count)
    finally:
        bot.close()

if __name__ == "__main__":
    main()
