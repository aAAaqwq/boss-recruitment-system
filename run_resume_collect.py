#!/usr/bin/env python3
"""
BOSS直聘 · 简历获取轮转系统 — 启动脚本 v1.0

使用方法:
  python3 run_resume_collect.py              # 处理前10人
  python3 run_resume_collect.py --max 20      # 处理前20人
  python3 run_resume_collect.py --dry-run     # 仅扫描预览
  python3 run_resume_collect.py --debug       # 调试模式（每一步截图）
"""
import sys, os

# 加到项目根目录
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.resume_collector import main, ensure_boss_chat_page, scan_contacts, log, init_db
import argparse


def dry_run():
    """预览模式 - 只扫描联系人不操作"""
    log("🔍 ===== DRY RUN 预览模式 =====")
    ensure_boss_chat_page()
    contacts = scan_contacts()
    
    print(f"\n{'='*50}")
    print(f"📋 扫描到 {len(contacts)} 个联系人:")
    print(f"{'='*50}")
    for c in contacts:
        print(f"  [{c['index']+1:2d}] {c['name']:8s}  y={c['y']:<4d}  '{c['text']}'")
    
    print(f"\n将依次执行每个联系人的流程：")
    print(f"  1. 点击 → 进入聊天")
    print(f"  2. 检查「附件简历」→ 深蓝=下载 / 浅蓝=请求")
    print(f"  3. 点击「换微信」→ 确认")
    print(f"  4. 自动滚到下一人")
    
    # 用OCR验证下当前看到的按钮状态
    print(f"\n🔍 进一步分析第一个联系人的按钮状态...")
    from app.vision import screen_ocr
    from app.resume_collector import ScreenConfig
    scr = ScreenConfig()
    
    if contacts:
        # 点击第一个联系人看一眼
        import pyautogui
        pyautogui.moveTo(contacts[0]['y'], contacts[0]['y'] - 80)
        time.sleep(0.005)
        # 实际OCR
        result = screen_ocr((int(820*scr.scale_x), int(200*scr.scale_y), 
                            int(1080*scr.scale_x), int(750*scr.scale_y)), min_confidence=25)
        print(f"\n第一个联系人 ({contacts[0]['name']}) 聊天面板按钮:")
        buttons_found = []
        for box in sorted(result["boxes"], key=lambda b: b.center_y):
            text = box.text
            if any(kw in text for kw in ["附件", "简历", "求简历", "在线", "换微信", "确认", "确定"]):
                buttons_found.append(f"  [{box.confidence:.0f}%] ({box.center_x},{box.center_y}) {box.text}")
        
        if buttons_found:
            for b in buttons_found:
                print(b)
        else:
            print("  (未识别到按钮 — 可能需要先进入聊天页面)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BOSS直聘 · 简历获取轮转系统")
    parser.add_argument("--max", type=int, default=10, help="最多处理人数 (默认: 10)")
    parser.add_argument("--dry-run", action="store_true", help="dry run预览模式")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    args = parser.parse_args()
    
    if args.dry_run:
        dry_run()
    else:
        log("🚀 BOSS直聘 · 简历获取轮转系统 启动")
        log(f"   处理上限: {args.max} 人")
        if args.debug:
            log("   调试模式: 开启")
        main(max_candidates=args.max)
