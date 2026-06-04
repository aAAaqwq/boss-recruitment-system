#!/usr/bin/env python3
"""
BOSS直聘自动化系统 - 龙虾Skill入口

使用方式：
    import boss_recruitment
    
    # 创建实例
    bot = boss_recruitment.BossAutomation()
    
    # 启动
    await bot.start()
    await bot.login()
    
    # 执行功能
    await bot.auto_greet()    # 自动打招呼
    await bot.auto_resume()   # 自动获取简历
    await bot.auto_chat()     # AI自动对话
    
    # 关闭
    await bot.close()
"""

from boss_auto_v2 import BossAutomation, load_config, save_config

__version__ = "2.0.0"
__author__ = "轩辕"
__all__ = ["BossAutomation", "load_config", "save_config"]

# 龙虾Skill入口
async def main():
    """龙虾Skill主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="BOSS直聘自动化系统 v2.0")
    parser.add_argument("--mode", choices=["greet", "resume", "chat", "all"], 
                        default="all", help="运行模式")
    parser.add_argument("--headless", action="store_true", 
                        help="无头模式")
    parser.add_argument("--count", type=int, default=80,
                        help="处理数量")
    args = parser.parse_args()
    
    # 创建实例
    config = load_config()
    bot = BossAutomation(config)
    
    try:
        # 启动
        await bot.start(headless=args.headless)
        await bot.login()
        
        # 执行
        if args.mode == "greet" or args.mode == "all":
            await bot.auto_greet(count=args.count)
        
        if args.mode == "resume" or args.mode == "all":
            await bot.auto_resume(count=min(10, args.count))
        
        if args.mode == "chat" or args.mode == "all":
            await bot.auto_chat(count=min(10, args.count))
        
    finally:
        await bot.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
