#!/usr/bin/env python3
"""
BOSS直聘 · 简历获取轮转系统 — 启动入口 v2.3
============================================

用法:
  python3 run.py                          # 处理5个候选人(颜色检测模式)
  python3 run.py --max 20                 # 处理20个
  python3 run.py --method pixel           # 颜色检测模式(推荐,需TCC权限)
  python3 run.py --method trial           # 试错模式(无权限依赖)
  python3 run.py --debug                  # 调试检测
  python3 run.py --db-view                # 查看数据库记录
"""
import sys, os

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
os.environ['PYTHONUNBUFFERED'] = '1'

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="BOSS直聘 简历获取系统 v2.3")
    parser.add_argument("--max", type=int, default=5, help="处理上限人数")
    parser.add_argument("--method", default="pixel", choices=["pixel", "trial"], 
                        help="pixel=颜色检测(需TCC) / trial=试错模式")
    parser.add_argument("--debug", action="store_true", help="调试检测模式")
    parser.add_argument("--db-view", action="store_true", help="查看数据库记录")
    args = parser.parse_args()
    
    if args.db_view:
        import sqlite3
        from pathlib import Path
        db_path = Path(ROOT) / "data" / "boss_recruitment.db"
        if not db_path.exists():
            print("📭 数据库不存在")
            sys.exit(0)
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT * FROM resume_operations ORDER BY id DESC LIMIT 30").fetchall()
        if not rows:
            print("📭 数据库为空")
        else:
            print(f"\n📊 最近 {len(rows)} 条:")
            print(f" {'ID':>3} {'#':>3} {'姓名':18s} {'操作':14s} {'下载':>3} {'请求':>3} {'微信':>3} {'时间':20s}")
            print(f" {'-'*3} {'-'*3} {'-'*18} {'-'*14} {'-'*3} {'-'*3} {'-'*3} {'-'*20}")
            for r in rows:
                print(f" {r[0]:3d} {r[1]:3d} {str(r[2] or '-'):18s} {str(r[3] or '-'):14s} {r[4]:3d} {r[5]:3d} {r[6]:3d} {str(r[8] or ''):20s}")
        conn.close()
        sys.exit(0)
    
    from app.resume_collector_v2 import main, log
    
    if args.debug:
        log("🔍 调试模式: 请直接运行调试脚本")
        sys.exit(0)
    
    log(f"🚀 BOSS直聘获取系统 v2.3")
    log(f"   上限: {args.max}人 | 方法: {args.method}")
    
    main(max_candidates=args.max, method=args.method)
