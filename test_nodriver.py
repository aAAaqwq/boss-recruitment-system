#!/usr/bin/env python3
import os, sys, traceback

os.environ['DISPLAY'] = ':1'

try:
    print("导入 nodriver...")
    import nodriver as uc
    print("nodriver 导入成功")

    print("启动 Chrome...")
    browser = uc.start(headless=False)
    print(f"浏览器启动成功: {browser}")

    print("获取标签页...")
    tab = browser.main_tab
    print(f"标签页: {tab}")

    print("导航到百度...")
    import asyncio
    asyncio.get_event_loop().run_until_complete(tab.goto("https://www.baidu.com"))
    print("导航成功")

except Exception as e:
    print(f"错误: {e}")
    traceback.print_exc()
    sys.exit(1)
