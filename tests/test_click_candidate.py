#!/usr/bin/env python3
"""
BOSS直聘沟通自动化 — 第一步：点击候选人

只做一件事：在候选人列表中点击第1个候选人
先用OCR确认候选人名位置，再点击
"""

import time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.screen import activate_chrome, move_and_click
from app.vision import screen_ocr, _capture_region
import pyautogui

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")

# ==============================
# 第一步：扫描候选人列表位置
# ==============================
def step1_find_candidates():
    """
    用OCR扫描候选人列表区域，找出所有候选人
    候选人列表在左半边，x范围大约60-420
    """
    log("=" * 50)
    log("扫描候选人列表")
    log("=" * 50)
    
    # 扫描左半边全部区域
    result = screen_ocr(
        region=(0, 300, 420, 750),  # x=0-420, y=300-1050
        min_confidence=1.0,
        scale=4,  # 高清OCR
        preprocess=True
    )
    
    log(f"OCR识别到 {len(result['boxes'])} 个文本")
    
    # 打印所有结果
    for box in result["boxes"][:50]:
        tx, ty = box.center_x, box.center_y
        log(f"  [{tx:4d},{ty:4d}] \"{box.text}\" (conf={box.confidence:.0f})")
    
    # 找候选人名字：短中文文本（2-4字），在x=80-400之间，不在导航栏（x<80）
    candidates = []
    for box in result["boxes"]:
        text = box.text.strip()
        x, y = box.center_x, box.center_y
        
        # 跳过导航栏（x<90）
        if x < 90:
            continue
        # 跳过顶部区域
        if y < 320:
            continue
        # 跳过非中文或太长
        if not any('\u4e00' <= c <= '\u9fff' for c in text):
            continue
        if len(text) > 6 or len(text) < 2:
            continue
        # 跳过已知非候选人文字
        if text in ["全部", "未读", "全部", "职位", "批量", "搜索"]:
            continue
        
        candidates.append({"name": text, "x": x, "y": y})
    
    # 按y排序，去重（间距>30px）
    candidates.sort(key=lambda c: c["y"])
    filtered = []
    for c in candidates:
        if not filtered or c["y"] - filtered[-1]["y"] > 30:
            filtered.append(c)
    
    log(f"\n识别到 {len(filtered)} 个候选人:")
    for i, c in enumerate(filtered):
        log(f"  #{i+1}: {c['name']} @ ({c['x']}, {c['y']})")
    
    return filtered

# ==============================
# 第二步：点击候选人
# ==============================
def step2_click_candidate(candidate):
    """OCR定位候选人名 → 点击名字附近"""
    name, x, y = candidate["name"], candidate["x"], candidate["y"]
    
    log(f"\n点击候选人: {name}")
    log(f"  OCR位置: ({x}, {y})")
    
    # 在名字周围再搜一次确认
    verify = screen_ocr(
        region=(x-60, y-30, 120, 60),
        min_confidence=3.0, scale=3, preprocess=True
    )
    for box in verify["boxes"]:
        log(f"  确认OCR: [{box.center_x},{box.center_y}] \"{box.text}\"")
    
    # 点击名字左侧（头像/卡片空白区）——用你的表：x≈60-200
    click_x = max(120, x - 100)  # 名字左边100px
    click_y = y
    
    log(f"  点击位置: ({click_x}, {click_y})")
    
    # 先移动过去，不点
    pyautogui.moveTo(click_x, click_y)
    time.sleep(1)
    log("  已移动到位置，等待确认...")
    time.sleep(3)  # 给你时间看位置对不对
    
    # 点的瞬间
    pyautogui.click()
    log("  ✅ 已点击")
    time.sleep(2)
    
    log("\n点击后，请截图发给我看看效果！")

# ==============================
# 主流程
# ==============================
def main():
    log("BOSS直聘候选人点击测试")
    log("只做第一步：找到候选人并点击")
    
    activate_chrome()
    time.sleep(1)
    
    # 第一步：找候选人
    candidates = step1_find_candidates()
    
    if not candidates:
        log("\n❌ 没有找到候选人。请检查：")
        log("  1. 是否在沟通页？")
        log("  2. 当前页面是否有候选人列表？")
        log("  3. 浏览器窗口是否在1920x1080分辨率？")
        return
    
    # 第二步：点击第1个候选人
    step2_click_candidate(candidates[0])

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n⚠️ 用户中断")
    except Exception as e:
        log(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
