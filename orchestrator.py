#!/usr/bin/env python3
"""
BOSS直聘 AI招聘全流程编排器 v1.0
================================
完整 MVP 流程:
  STEP 1-3 (run_automation_final.py): 推荐牛人 → 打招呼
  STEP 4-8 (communicate_collector.py): 沟通页 → 获取简历 → 换微信

用法:
  python3 orchestrator.py                     # 全流程：招呼80人 → 沟通页5人
  python3 orchestrator.py --max-greet 40      # 打40个招呼
  python3 orchestrator.py --max-collect 10    # 取10人简历
  python3 orchestrator.py --greet-only        # 只打招呼，不取简历
  python3 orchestrator.py --collect-only      # 只取简历（跳过打招呼）
  python3 orchestrator.py --step1-3           # 只跑 STEP 1-3（推荐→筛选→打招呼）
  python3 orchestrator.py --step4-8           # 只跑 STEP 4-8（沟通页遍历）
"""
import sys, os, time, random
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from app.screen import activate_chrome, move_and_click, scroll
from app.vision import screen_ocr

from app.communicate_collector import main as collect_main
from app.communicate_collector import chrome_activate, chrome_url, log
from app.communicate_collector import NAV_RECOMMEND, NAV_COMMUNICATE
from app.communicate_collector import click, read_pixel


# ============================================================
# STEP 1-3: 推荐牛人→筛选→打招呼
# 基于 run_automation_final.py 的精简版
# ============================================================

def step1_click_recommend():
    """点左侧推荐牛人"""
    log('📌 STEP 1: 点击推荐牛人', 'STEP')
    click(*NAV_RECOMMEND, 2.0)
    time.sleep(1.5)
    
    url = chrome_url()
    log(f"  URL: {url[:70]}", "INFO")
    
    if "chat/recommend" in url or "recommend" in url:
        log("  ✅ 已在推荐牛人页", "OK")
        return True
    log("  ⚠️ 可能不是推荐页", "WARN")
    return False


def step2_open_filter():
    """点筛选按钮 + 勾选985/211 + 确定"""
    log("📌 STEP 2: 筛选(985/211)", "STEP")
    
    # 先用固定区域扫描"筛选"按钮
    # BOSS的筛选按钮在右上角 (x≈1500-1800, y≈100-200)
    for attempt in range(5):
        result = screen_ocr(
            region=(1400, 90, 400, 150),
            min_confidence=5.0, scale=3, preprocess=True
        )
        for box in result["boxes"]:
            if "筛选" in box.text or "筛 选" in box.text:
                log(f"  ✅ 找到筛选按钮: ({box.center_x},{box.center_y})", "OK")
                move_and_click(box.center_x, box.center_y, 0.1)
                time.sleep(2)
                break
        else:
            if attempt < 4:
                log(f"  未找到筛选 第{attempt+1}次重试...", "WARN")
                time.sleep(0.5)
                continue
            log("  ❌ 5次尝试后找不到筛选", "ERR")
            return False
        break
    
    # 等待筛选面板打开
    time.sleep(2)
    
    # OCR读筛选面板
    result = screen_ocr(
        region=(960, 100, 960, 700),
        min_confidence=3.0, scale=3, preprocess=True
    )
    
    log(f"  筛选面板: {len(result['boxes'])}个元素", "DET")
    
    targets = {"985": False, "211": False, "本科": False}
    for box in result["boxes"]:
        for t in targets:
            if t in box.text and box.confidence >= 5.0 and not targets[t]:
                log(f"  ✅ 找到[{t}]... 准备点击", "DET")
                # 如果是小选项框，点击
                move_and_click(box.center_x, box.center_y, 0.1)
                time.sleep(0.3)
                targets[t] = True
    
    # 找"确定"按钮
    time.sleep(1)
    for attempt in range(5):
        result2 = screen_ocr(
            region=(960, 600, 960, 250),
            min_confidence=5.0, scale=3, preprocess=True
        )
        confirm_found = False
        for box in result2["boxes"]:
            if "确定" in box.text or "应用" in box.text:
                log(f"  ✅ 找到确认按钮: ({box.center_x},{box.center_y})", "OK")
                move_and_click(box.center_x, box.center_y, 0.1)
                confirm_found = True
                break
        if confirm_found:
            break
        log(f"  找确定 第{attempt+1}次...", "WARN")
        time.sleep(0.5)
    
    time.sleep(2)
    return True


def step3_greet_candidates(max_greet: int = 80):
    """STEP 3: 对候选人打招呼"""
    log(f"📌 STEP 3: 打招呼 (上限{max_greet}人)", "STEP")
    
    contacted = 0
    skipped = 0
    max_scrolls = 30
    
    from app.screen import scroll as py_scroll
    
    for scroll_count in range(max_scrolls):
        if contacted >= max_greet:
            log(f"  ✅ 已打满{max_greet}人", "OK")
            break
        
        # OCR扫描当前屏
        result = screen_ocr(
            region=(200, 200, 1500, 700),
            min_confidence=8.0, scale=3, preprocess=True
        )
        
        # 找"打招呼"按钮 → 按y排序
        greet_buttons = sorted(
            [(b.center_x, b.center_y) for b in result["boxes"]
             if "招呼" in b.text and "继续" not in b.text],
            key=lambda p: p[1]
        )
        
        log(f"  扫描#{scroll_count+1}: 发现{len(greet_buttons)}个打招呼", "DET")
        
        for gx, gy in greet_buttons:
            if contacted >= max_greet:
                break
            
            log(f"  [#{contacted+1}] 打招呼 ({gx},{gy})", "ACT")
            move_and_click(gx, gy)
            contacted += 1
            
            # 随机间隔3-6秒
            delay = random.uniform(3.0, 6.0)
            log(f"  ⏳ 等待{delay:.1f}s", "WAIT")
            time.sleep(delay)
        
        # 滚动
        py_scroll(-3)
        time.sleep(1.5)
    
    log(f"  ✅ STEP 3 完成: 已联系{contacted}人 跳过{skipped}人", "OK")
    return contacted


# ============================================================
# 主入口
# ============================================================

def main():
    import argparse
    ap = argparse.ArgumentParser(description="BOSS直聘 AI招聘全流程")
    ap.add_argument("--max-greet", type=int, default=80, help="招呼上限")
    ap.add_argument("--max-collect", type=int, default=5, help="简历获取上限")
    ap.add_argument("--greet-only", action="store_true", help="只打招呼")
    ap.add_argument("--collect-only", action="store_true", help="只取简历")
    ap.add_argument("--step1-3", action="store_true", help="只跑STEP1-3")
    ap.add_argument("--step4-8", action="store_true", help="只跑STEP4-8")
    args = ap.parse_args()
    
    log("="*60)
    log("🚀 BOSS直聘 AI招聘全流程编排器 v1.0")
    log("="*60)
    
    activate_chrome()
    time.sleep(1)
    
    run_step1_3 = args.step1_3 or (not args.collect_only and not args.step4_8)
    run_step4_8 = args.step4_8 or (not args.greet_only and not args.step1_3)
    
    # === Phase 1: STEP 1-3 (推荐牛人→打招呼) ===
    if run_step1_3:
        if not step1_click_recommend():
            log("⚠️ 无法进推荐页，尝试继续...", "WARN")
        
        step2_open_filter()
        time.sleep(2)
        
        greeted = step3_greet_candidates(args.max_greet)
        log(f"🎯 打招呼阶段: {greeted}人", "OK")
    
    # === Phase 2: STEP 4-8 (沟通页→取简历) ===
    if run_step4_8:
        log("\n" + "="*50)
        log("🔄 进入Phase 2: 沟通页取简历", "STEP")
        log("="*50)
        
        collect_main(max_candidates=args.max_collect)
    
    log("="*60)
    log("🏁 全流程完成")
    log("="*60)


if __name__ == "__main__":
    main()
