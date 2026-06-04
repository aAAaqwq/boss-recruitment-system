"""
快速测试脚本 - 验证Playwright能否正常工作
"""
from playwright.sync_api import sync_playwright
import time

def test_playwright():
    print("🔍 测试Playwright...")
    
    with sync_playwright() as p:
        # 启动浏览器
        print("✅ 启动浏览器...")
        browser = p.chromium.launch(headless=True)  # 改为无头模式
        page = browser.new_page()
        
        # 访问BOSS直聘
        print("✅ 访问BOSS直聘...")
        page.goto("https://www.zhipin.com")
        
        # 等待3秒
        print("✅ 页面加载成功，等待3秒...")
        time.sleep(3)
        
        # 截图
        print("✅ 截图保存...")
        page.screenshot(path="test_screenshot.png")
        
        # 关闭浏览器
        browser.close()
        
        print("✅ 测试完成！Playwright工作正常！")

if __name__ == "__main__":
    test_playwright()
