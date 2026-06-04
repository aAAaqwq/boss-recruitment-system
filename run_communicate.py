#!/usr/bin/env python3
"""
BOSS直聘沟通自动化 v3.0 — 实测坐标版
基于 2026-05-22 08:42 新截图 file_68 精确分析

页面布局（1920x1080）：
  左侧导航栏: x≈0-90, 深色背景
    - 沟通: (43, 372)
  候选人列表: x≈90-420
    - 候选人名: x≈303, y从351开始, 间距79px
    - 点击在x≈200（头像+空白区域）
  右侧聊天面板: x≈420-1920
    - 附件简历: (802, 262)
    - 换微信: (613, 807)
    - 发送: (812, 954)

操作流程：
  1. 已在沟通页 → 直接扫候选人列表
  2. 固定间距遍历候选人（x=200, y=351+79*i）
  3. 对每个候选人：点击→附件简历→换微信→下一人
  4. OCR校验+固定坐标兜底
"""

import time
import sys
import os
import random
import datetime
from typing import Optional, Tuple, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.screen import activate_chrome, move_and_click
from app.vision import screen_ocr
import pyautogui


# ============================================================
# 日志
# ============================================================
def log(msg: str, level: str = "INFO"):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    icon = {"INFO": "ℹ️", "OK": "✅", "WARN": "⚠️", "ERR": "❌", "DEBUG": "🔍", "STEP": "📌"}.get(level, "•")
    print(f"[{ts}] {icon} {msg}")


# ============================================================
# ⭐ 截图实测坐标（精确到像素）
# ============================================================

# 左侧导航栏
NAV = {
    "推荐牛人": (43, 275),
    "沟通":      (43, 372),   # ✅ 已选中，不要重复点
    "意向沟通":  (43, 421),
    "互动":      (43, 469),
    "牛人管理":  (43, 517),
    "工具箱":    (43, 614),
}

# 候选人列表
CANDIDATES = {
    "click_x":      200,    # 点击候选人卡片的位置（非名字本身，x=160-240间取中）
    "first_y":      351,    # 第一个候选人（许凯博）的y坐标
    "spacing":      79,     # 候选人间距精确值
    "count":        8,      # 每屏可见候选人数量
    # 滚动
    "scroll_x":     250,    # 在候选人列表中滚动
    "scroll_y":     800,
}

# 右侧面板顶部按钮
HEADER = {
    "在线简历":     (748, 262),
    "附件简历":     (802, 262),
}

# 右侧面板侧边
SIDE = {
    "历史":         (848, 267),
    "收藏":         (848, 339),
    "分享":         (848, 375),
    "更多":         (848, 412),
}

# 底部操作栏
BOTTOM = {
    "表情":         (434, 807),
    "常用语":       (457, 807),
    "图片":         (479, 807),
    "加号":         (501, 807),
    "求简历":       (542, 807),
    "换电话":       (577, 807),
    "换微信":       (613, 807),
    "约面试":       (654, 807),
    "不合适":       (814, 807),
}

# 输入区域
INPUT = {
    "输入框":       (630, 890),
    "发送":         (812, 954),
}

# 弹窗（之前截图分析）
DIALOG = {
    "取消":         (778, 390),
    "确认":         (808, 390),
}

# 换微信弹窗（之前截图分析）
WECHAT = {
    "取消":         (1184, 807),
    "确定":         (1249, 807),
}

# 简历预览弹窗（图4分析）
RESUME = {
    "下载":         (658, 148),
    "关闭":         (662, 192),
}


# ============================================================
# OCR辅助
# ============================================================

def find_text(text: str, region: Tuple[int, int, int, int], 
              exact: bool = False, confidence: float = 3.0) -> Optional[Tuple[int, int]]:
    """在指定区域搜文字，返回中心坐标"""
    result = screen_ocr(region=region, min_confidence=confidence, scale=3, preprocess=True)
    for box in result["boxes"]:
        if exact:
            if box.text == text:
                return (box.center_x, box.center_y)
        else:
            if text in box.text:
                return (box.center_x, box.center_y)
    return None


def find_text_batch(texts: list, region: Tuple[int, int, int, int],
                    confidence: float = 3.0) -> Optional[Tuple[int, int]]:
    """批量搜文字"""
    result = screen_ocr(region=region, min_confidence=confidence, scale=3, preprocess=True)
    for box in result["boxes"]:
        for t in texts:
            if t in box.text:
                return (box.center_x, box.center_y)
    return None


def verify_goutong_page() -> bool:
    """验证当前在沟通页——左侧导航'沟通'应被选中（白色高亮）"""
    # OCR搜"沟通"确认位置
    pos = find_text("沟通", (0, 300, 100, 150), confidence=5.0)
    if pos:
        log(f"✅ 确认在沟通页，'沟通'在 ({pos[0]}, {pos[1]})", "OK")
        return True
    
    # 不在沟通页？尝试点一下
    log("⚠️ 未确认沟通页，尝试点击沟通...", "WARN")
    nav_pos = find_text("沟通", (0, 100, 100, 600), confidence=3.0)
    if nav_pos:
        move_and_click(nav_pos[0], nav_pos[1])
        time.sleep(2.0)
        return True
    
    # 固定坐标兜底
    move_and_click(43, 372)
    time.sleep(2.0)
    return True


# ============================================================
# 核心步骤
# ============================================================

def click_candidate(index: int, y_coord: int):
    """点击第N个候选人（x固定=200，y=351+79*i）"""
    x = CANDIDATES["click_x"]
    y = y_coord
    log(f"📌 点击 #候选{index+1} @ ({x}, {y})", "STEP")
    
    # 先用OCR确认候选人名字是否存在，作为校验
    name_pos = find_text("许凯博" if index == 0 else "", 
                         (240, y - 30, 120, 60), confidence=3.0)
    
    move_and_click(x, y)
    time.sleep(1.5)
    return True


def click_attach_resume():
    """点击'附件简历'按钮"""
    log(f"📌 点击附件简历 @ {HEADER['附件简历']}", "STEP")
    
    # 策略A: OCR搜"附件简历"
    pos = find_text("附件简历", (700, 230, 150, 70))
    if pos:
        log(f"  OCR找到: ({pos[0]}, {pos[1]})", "OK")
        move_and_click(pos[0], pos[1])
        time.sleep(1.5)
        return True
    
    # 策略B: 固定坐标
    log(f"  固定坐标: {HEADER['附件简历']}", "INFO")
    move_and_click(HEADER["附件简历"][0], HEADER["附件简历"][1])
    time.sleep(1.5)
    return True


def click_online_resume():
    """点击'在线简历'按钮"""
    pos = find_text("在线简历", (700, 230, 100, 70))
    if pos:
        move_and_click(pos[0], pos[1])
    else:
        move_and_click(HEADER["在线简历"][0], HEADER["在线简历"][1])
    time.sleep(1.5)


def handle_resume_dialog():
    """
    处理确认弹窗（"方便发一份你的简历过来吗？"）
    取消: (778, 390)  确认: (808, 390)
    """
    log("检查确认弹窗...", "DEBUG")
    
    # 找"确认"或"确定"按钮
    confirm_pos = find_text_batch(["确认", "确定"], (740, 350, 150, 80))
    if confirm_pos:
        log(f"✅ 弹窗存在，点击确认 @ ({confirm_pos[0]}, {confirm_pos[1]})", "OK")
        move_and_click(confirm_pos[0], confirm_pos[1])
        time.sleep(1.5)
        return True
    
    # OCR没找到，可能弹窗已消失或不存在
    log("  无弹窗（可能已处理或不需要）", "DEBUG")
    return False


def handle_wechat_exchange():
    """
    换微信流程
    换微信按钮: (613, 807)
    弹窗确定: (1249, 807)
    """
    log(f"📌 点击换微信 @ (613, 807)", "STEP")
    move_and_click(BOTTOM["换微信"][0], BOTTOM["换微信"][1])
    time.sleep(2.0)
    
    # 换微信弹窗确定按钮
    pos = find_text_batch(["确定", "确认"], (1150, 770, 150, 70))
    if pos:
        log(f"  OCR找到确定: ({pos[0]}, {pos[1]})", "OK")
        move_and_click(pos[0], pos[1])
    else:
        log(f"  固定坐标: (1249, 807)", "INFO")
        move_and_click(1249, 807)
    
    time.sleep(1.0)


def scroll_candidates():
    """在候选人列表中滚动"""
    log("📌 滚动候选人列表...", "STEP")
    pyautogui.moveTo(CANDIDATES["scroll_x"], CANDIDATES["scroll_y"])
    pyautogui.scroll(-5)
    time.sleep(2.0)
    log("  ✅ 已滚动", "OK")


# ============================================================
# 主流程
# ============================================================

def main():
    log("=" * 60)
    log("BOSS直聘沟通自动化 v3.0")
    log("截图实测坐标版 | 1920x1080")
    log("=" * 60)
    
    activate_chrome()
    time.sleep(1)
    
    # 步骤0: 确认在沟通页（可能在也可能不在）
    verify_goutong_page()
    
    max_people = 50
    processed = 0
    scroll_count = 0
    max_scrolls = 20
    
    while processed < max_people and scroll_count < max_scrolls:
        log(f"\n{'='*60}")
        log(f"第 {scroll_count+1} 屏")
        log(f"{'='*60}")
        
        # 从第一个候选人开始遍历
        for i in range(CANDIDATES["count"]):
            if processed >= max_people:
                break
            
            y = CANDIDATES["first_y"] + i * CANDIDATES["spacing"]
            
            processed += 1
            log(f"\n{'─'*50}")
            log(f"处理 #{processed}: 候选{i+1} @ y={y}")
            log(f"{'─'*50}")
            
            # 1. 点候选人
            click_candidate(i, y)
            
            # 2. 点附件简历
            click_attach_resume()
            
            # 3. 处理确认弹窗
            handle_resume_dialog()
            
            # 4. 换微信
            handle_wechat_exchange()
            
            # 5. 随机延迟
            delay = random.uniform(2.0, 5.0)
            log(f"⏳ 等待 {delay:.1f}s...")
            time.sleep(delay)
        
        if processed >= max_people:
            break
        
        # 滚动到下一屏
        scroll_count += 1
        scroll_candidates()
        
        # 滚动后调整first_y（新候选人起始位置与之前相同）
        # 保持固定间距不变
    
    log(f"\n{'='*60}")
    log(f"✅ 完成！处理 {processed} 人")
    log(f"{'='*60}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("⚠️ 用户中断", "WARN")
    except Exception as e:
        log(f"❌ 错误: {e}", "ERR")
        import traceback
        traceback.print_exc()
