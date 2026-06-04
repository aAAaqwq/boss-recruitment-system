#!/usr/bin/env python3
"""
BOSS直聘三位一体整合系统 v1.0
一键启动: 打招呼 + 获取简历 + AI对话

使用方法:
    python run_trinity.py --mode all    # 启动所有Agent
    python run_trinity.py --mode greet  # 只启动打招呼
    python run_trinity.py --mode resume # 只启动获取简历
    python run_trinity.py --mode chat   # 只启动AI对话
"""
import sys
import os
import time
import json
import argparse
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "app"))

from app.trinity_scheduler import UnifiedDatabase, TrinityScheduler
from app.trinity_agents import GreetAgent, ResumeAgent, ChatAgent

def main():
    parser = argparse.ArgumentParser(description="BOSS直聘三位一体系统")
    parser.add_argument("--mode", choices=["all", "greet", "resume", "chat"], 
                        default="all", help="运行模式")
    args = parser.parse_args()
    
    print("=" * 60)
    print("🚀 BOSS直聘三位一体系统 v1.0")
    print("=" * 60)
    print()
    
    # 初始化数据库
    db = UnifiedDatabase()
    print("✅ 数据库初始化完成")
    
    # 创建调度器
    scheduler = TrinityScheduler()
    print("✅ 调度器初始化完成")
    
    # 注册Agent
    if args.mode in ["all", "greet"]:
        scheduler.register_agent("greet", GreetAgent(db))
        print("✅ Greet Agent已注册")
    
    if args.mode in ["all", "resume"]:
        scheduler.register_agent("resume", ResumeAgent(db))
        print("✅ Resume Agent已注册")
    
    if args.mode in ["all", "chat"]:
        scheduler.register_agent("chat", ChatAgent(db))
        print("✅ Chat Agent已注册")
    
    print()
    print("=" * 60)
    print("🟢 系统已启动，按Ctrl+C停止")
    print("=" * 60)
    
    # 启动所有Agent
    scheduler.start_all()
    
    # 保持运行
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 正在停止...")
        scheduler.stop_all()
        print("✅ 系统已停止")

if __name__ == "__main__":
    main()
