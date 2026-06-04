#!/usr/bin/env python3
"""
BOSS直聘三位一体系统 - 串行模式 v1.1

串行执行流程：
  Step 1: Greet (打招呼) → 完成所有候选人
  Step 2: Resume (获取简历) → 完成所有已打招呼的候选人
  Step 3: Chat (AI对话) → 完成所有有简历的候选人

同一个账号内串行，不同账号可并行
"""
import time
import sys
import os
import json
from datetime import datetime
from pathlib import Path
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent / "app"))

from app.trinity_scheduler import UnifiedDatabase
from app.trinity_agents import GreetAgent, ResumeAgent, ChatAgent, HAS_VISION

# ============================================================
# 串行调度器
# ============================================================

class SerialTrinityScheduler:
    """串行三位一体调度器"""
    
    def __init__(self):
        self.db = UnifiedDatabase()
        self.greet_agent = GreetAgent(self.db)
        self.resume_agent = ResumeAgent(self.db)
        self.chat_agent = ChatAgent(self.db)
        
        self.current_step = "idle"
        self.step_results = {}
        
    def run_serial(self, dry_run: bool = False) -> Dict:
        """串行执行完整流程"""
        print("\n" + "="*60)
        print("🚀 BOSS直聘三位一体系统 - 串行模式")
        print("="*60)
        print(f"📅 执行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"🔍 视觉模块: {'已加载 ✅' if HAS_VISION else '未加载 ❌'}")
        print("="*60)
        
        if not HAS_VISION:
            print("\n❌ 错误: 视觉模块未加载，无法执行真实操作")
            print("请确保以下文件存在:")
            print("  - app/screen.py")
            print("  - app/vision.py")
            return {"status": "failed", "reason": "vision_module_not_loaded"}
        
        # Step 1: 打招呼
        self.current_step = "greet"
        print("\n" + "-"*40)
        print("📌 Step 1/3: 自动打招呼")
        print("-"*40)
        result = self.greet_agent.run_once(dry_run=dry_run)
        self.step_results["greet"] = result
        
        if result.get("status") not in ["completed", "preview"]:
            print(f"❌ 打招呼失败: {result}")
            return self.step_results
        
        # Step 2: 获取简历
        self.current_step = "resume"
        print("\n" + "-"*40)
        print("📌 Step 2/3: 获取简历")
        print("-"*40)
        result = self.resume_agent.run_once()
        self.step_results["resume"] = result
        
        if result.get("status") not in ["completed", "no_candidates"]:
            print(f"❌ 获取简历失败: {result}")
            return self.step_results
        
        # Step 3: AI对话
        self.current_step = "chat"
        print("\n" + "-"*40)
        print("📌 Step 3/3: AI对话")
        print("-"*40)
        result = self.chat_agent.run_once()
        self.step_results["chat"] = result
        
        self.current_step = "completed"
        
        print("\n" + "="*60)
        print("✅ 串行流程全部完成!")
        print("="*60)
        
        return self.step_results
    
    def get_status(self) -> Dict:
        """获取当前状态"""
        stats = self.db.get_stats()
        return {
            "current_step": self.current_step,
            "step_results": self.step_results,
            "stats": stats,
            "vision_available": HAS_VISION
        }

# ============================================================
# 主程序
# ============================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="BOSS直聘三位一体串行系统")
    parser.add_argument("--dry-run", action="store_true", help="预览模式（不实际执行）")
    args = parser.parse_args()
    
    scheduler = SerialTrinityScheduler()
    
    # 串行执行
    results = scheduler.run_serial(dry_run=args.dry_run)
    
    print("\n" + "="*60)
    print("📊 最终结果")
    print("="*60)
    print(json.dumps(results, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
