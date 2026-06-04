"""
Boss直聘 · 简历获取轮转系统 v1.1
===================================
基于丘总2026-05-19 17:34新截图建立的坐标系
屏幕: 1920x1080

核心流程：
  点击沟通 → 点击联系人 → 
  ├─ 深蓝"附件简历" → 预览 → 下载 → 退出预览
  ├─ 浅蓝"在线简历" → 点"确认"弹窗 → 请求成功
  └─ 底部"求简历"  → 点"确认"弹窗 → 请求成功
  → 点击"换微信" → 绿色"确认"
  → 滚动到下一联系人 → 重复
"""
import sys, os, time, json, subprocess, sqlite3, re
from datetime import datetime
from typing import Optional, Tuple, List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.screen import activate_chrome, move_and_click
import pyautogui

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "boss_recruitment.db")

# ============================================================
# 精确坐标（基于1920x1080）
# ============================================================

# 导航
NAV_COMMUNICATION = (44, 369)      # 左侧"沟通"导航

# 联系人列表
CONTACT_LIST_X = 253               # 联系人x中心
CONTACT_FIRST_Y = 358              # 第一个联系人y（黄天珑）
CONTACT_GAP = 68                   # 联系人间距

# 聊天面板右上角按钮
BTN_ONLINE_RESUME = (740, 270)     # "在线简历" 浅蓝
BTN_ATTACH_RESUME = (797, 270)     # "附件简历" 深蓝

# 聊天面板底部工具栏
BTN_REQUEST_RESUME = (543, 770)    # "求简历"
BTN_EXCHANGE_WECHAT = (616, 770)   # "换微信"
BTN_SEND = (812, 908)              # 输入框旁边的"发送"

# 简历预览
BTN_DOWNLOAD_PREVIEW = (1550, 130) # 预览弹出的简历右上角下载
EXIT_PREVIEW = (1300, 540)         # 预览外灰色区域，点击退出

# 弹窗确认
POPUP_CONFIRM = (1170, 810)        # 绿色"确认"/"确定"按钮

# OCR区域（备用）
OCR_CONTACT_LIST = (88, 324, 418-88, 460-324)     # 左侧联系人列表区域 (x,y,w,h)
OCR_CHAT_PANEL = (418, 200, 840-418, 800-200)     # 右侧聊天面板
OCR_PREVIEW = (200, 50, 1520, 900)                # 简历预览区域


# ============================================================
# 日志
# ============================================================

def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌","ACT":"🖱️","WAIT":"⏳","DB":"💾"}.get(level, "ℹ️")
    print(f"[{ts}] {icon} {msg}")


# ============================================================
# 数据库
# ============================================================

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS resume_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_name TEXT,
        action TEXT,
        resume_downloaded INTEGER DEFAULT 0,
        wechat_exchanged INTEGER DEFAULT 0,
        detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    return conn


# ============================================================
# Chrome + 导航
# ============================================================

def ensure_boss_page():
    """激活Chrome并点"沟通""""
    activate_chrome()
    time.sleep(2)
    
    # 点击"沟通"
    pyautogui.moveTo(NAV_COMMUNICATION[0], NAV_COMMUNICATION[1], duration=0.2)
    pyautogui.click()
    time.sleep(2)
    log(f"已点击「沟通」导航", "ACT")


# ============================================================
# 步骤1: 点击指定联系人
# ============================================================

def click_contact(index: int):
    """
    点击第index个联系人（0-based）
    第0个: y=358, 间距68
    """
    y = CONTACT_FIRST_Y + index * CONTACT_GAP
    pyautogui.moveTo(CONTACT_LIST_X, y, duration=0.15)
    pyautogui.click()
    time.sleep(2)
    log(f"点击联系人 #{index+1} (y={y})", "ACT")


# ============================================================
# 步骤2: 获取简历（两种状态）
# ============================================================

def get_resume(candidate_name: str) -> Dict:
    """
    获取简历流程
    
    Returns: {"status": "downloaded"|"requested"|"no_button", "detail": ...}
    """
    log(f"📄 获取简历: {candidate_name}", "INFO")
    
    # ---- 策略A: 深蓝"附件简历"（已有简历可直接下载）----
    pyautogui.moveTo(BTN_ATTACH_RESUME[0], BTN_ATTACH_RESUME[1], duration=0.15)
    pyautogui.click()
    time.sleep(2.5)  # 等待简历预览弹出
    
    # 检查是否真正弹出了简历（如果按钮是灰色/浅蓝，点击会弹出确认弹窗而不是简历预览）
    # OCR检测是否有"确认"弹窗
    try:
        if _detect_confirm_popup():
            log(f"{candidate_name}: 简历尚未发送，点了后会弹出确认弹窗", "INFO")
            # 点"确认"发送请求
            pyautogui.moveTo(POPUP_CONFIRM[0], POPUP_CONFIRM[1], duration=0.15)
            pyautogui.click()
            time.sleep(2)
            log(f"已向 {candidate_name} 发送简历请求", "OK")
            
            _record_action(candidate_name, "requested_resume", 0, 0)
            return {"status": "requested", "detail": "已发送简历请求"}
        
        # 检查是否弹出简历预览（全屏大图）
        if _detect_resume_preview():
            log(f"{candidate_name}: 简历已存在，下载中...", "OK")
            
            # 点击右上角下载按钮
            pyautogui.moveTo(BTN_DOWNLOAD_PREVIEW[0], BTN_DOWNLOAD_PREVIEW[1], duration=0.15)
            pyautogui.click()
            time.sleep(3)
            
            # 退出预览
            _exit_resume_preview()
            
            _record_action(candidate_name, "downloaded_resume", 1, 0)
            return {"status": "downloaded", "detail": "简历已下载"}
        
    except Exception as e:
        log(f"附件简历检测异常: {e}", "WARN")
    
    # ---- 没有触发任何响应，试试"求简历"----
    log(f"尝试底部「求简历」按钮", "ACT")
    pyautogui.moveTo(BTN_REQUEST_RESUME[0], BTN_REQUEST_RESUME[1], duration=0.15)
    pyautogui.click()
    time.sleep(1.5)
    
    if _detect_confirm_popup():
        pyautogui.moveTo(POPUP_CONFIRM[0], POPUP_CONFIRM[1], duration=0.15)
        pyautogui.click()
        time.sleep(1.5)
        log(f"已通过「求简历」向 {candidate_name} 发送请求", "OK")
        _record_action(candidate_name, "requested_resume_v2", 0, 0)
        return {"status": "requested", "detail": "已发送简历请求（求简历）"}
    
    log(f"未识别到有效简历按钮反应", "WARN")
    return {"status": "no_button", "detail": "无反应"}


def _detect_confirm_popup() -> bool:
    """
    检测屏幕中央是否有确认弹窗
    检查POPUP_CONFIRM区域的按钮颜色（绿色）或OCR识别"确认"
    """
    try:
        # 检查点附近是否有典型绿色像素（确认按钮通常为绿色）
        green_x, green_y = POPUP_CONFIRM
        screen = pyautogui.screenshot(region=(green_x-50, green_y-50, 100, 100))
        
        # 检查绿色像素比例
        green_pixels = 0
        for px in screen.getdata():
            r, g, b = px[:3]
            if g > 150 and r < 100:  # 绿色特征
                green_pixels += 1
        
        total = screen.width * screen.height
        green_ratio = green_pixels / total
        
        if green_ratio > 0.05:
            log(f"检测到确认弹窗（绿色像素:{green_ratio:.1%}）", "OK")
            return True
    except:
        pass
    
    return False


def _detect_resume_preview() -> bool:
    """
    检测是否弹出了简历预览（全屏半透明蒙层+简历PDF/图片）
    检查PREVIEW区域是否有大量白色/浅色内容
    """
    try:
        screen = pyautogui.screenshot(region=(500, 100, 920, 700))
        white_pixels = 0
        for px in screen.getdata():
            r, g, b = px[:3]
            if r > 200 and g > 200 and b > 200:
                white_pixels += 1
        
        total = screen.width * screen.height
        white_ratio = white_pixels / total
        
        if white_ratio > 0.3:
            log(f"检测到简历预览（白色占比:{white_ratio:.1%}）", "OK")
            return True
    except:
        pass
    
    return False


def _exit_resume_preview():
    """退出简历预览 - 点击灰色背景"""
    pyautogui.moveTo(EXIT_PREVIEW[0], EXIT_PREVIEW[1], duration=0.15)
    pyautogui.click()
    time.sleep(1.5)
    log("已退出简历预览", "ACT")


# ============================================================
# 步骤3: 换微信
# ============================================================

def exchange_wechat(candidate_name: str) -> bool:
    """点击换微信 → 绿色确认"""
    log(f"📱 换微信: {candidate_name}", "INFO")
    
    # 点击"换微信"
    pyautogui.moveTo(BTN_EXCHANGE_WECHAT[0], BTN_EXCHANGE_WECHAT[1], duration=0.15)
    pyautogui.click()
    time.sleep(1.5)
    
    # 找绿色"确认"按钮
    pyautogui.moveTo(POPUP_CONFIRM[0], POPUP_CONFIRM[1], duration=0.15)
    pyautogui.click()
    time.sleep(1.5)
    
    log(f"✅ {candidate_name} 微信交换完成", "OK")
    _record_action(candidate_name, "wechat_exchanged", 0, 1)
    return True


# ============================================================
# 工具函数
# ============================================================

def _record_action(name: str, action: str, downloaded: int, wechat: int, detail: str = ""):
    """记录操作到数据库"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT INTO resume_operations (candidate_name, action, resume_downloaded, wechat_exchanged, detail) VALUES (?, ?, ?, ?, ?)",
                    (name, action, downloaded, wechat, detail))
        conn.commit()
        conn.close()
    except Exception as e:
        log(f"写入数据库失败: {e}", "WARN")


def scroll_to_next(current_index: int):
    """滚动到下一联系人"""
    # 滚动一下保证下一人可见
    pyautogui.scroll(-3, x=CONTACT_LIST_X, y=CONTACT_FIRST_Y + current_index * CONTACT_GAP)
    time.sleep(0.5)
    log(f"滚到下一联系人", "ACT")


# ============================================================
# 主流程
# ============================================================

def process_candidate(name: str, index: int) -> Dict:
    """处理单个候选人"""
    result = {"name": name, "index": index, "resume": None, "wechat": False}
    
    # 点击联系人
    click_contact(index)
    
    # 获取简历
    resume_result = get_resume(name)
    result["resume"] = resume_result
    
    # 等待一下再换微信
    time.sleep(1)
    
    # 换微信
    try:
        exchange_wechat(name)
        result["wechat"] = True
    except Exception as e:
        log(f"换微信失败: {e}", "ERR")
    
    scroll_to_next(index)
    return result


def main(max_candidates: int = 10):
    log("=" * 60)
    log("🎯 BOSS直聘 · 简历获取轮转系统 v1.1")
    log(f"  上限: {max_candidates} 人")
    log("=" * 60)
    
    conn = init_db()
    
    # 激活Chrome + 点"沟通"
    ensure_boss_page()
    
    # 逐个处理联系人
    stats = {"downloaded": 0, "requested": 0, "wechat": 0, "failed": 0}
    
    for i in range(max_candidates):
        log(f"\n{'─'*50}")
        log(f"👤 [{i+1}/{max_candidates}] 处理中...")
        log(f"{'─'*50}")
        
        try:
            name = f"候选人#{i+1}"  # 未识别名字，用编号
            result = process_candidate(name, i)
            
            rs = result.get("resume", {}).get("status", "?")
            if rs == "downloaded": stats["downloaded"] += 1
            elif rs == "requested": stats["requested"] += 1
            if result.get("wechat"): stats["wechat"] += 1
            
            log(f"✅ 完成: 简历={rs}, 微信={'已换' if result.get('wechat') else '-'}")
            
        except Exception as e:
            log(f"❌ 异常: {e}", "ERR")
            import traceback
            traceback.print_exc()
            stats["failed"] += 1
        
        time.sleep(1.5)
    
    # 汇总
    log(f"\n{'='*50}")
    log(f"🎉 完成!")
    log(f"  简历已下载: {stats['downloaded']}")
    log(f"  简历已请求: {stats['requested']}")
    log(f"  微信已换:   {stats['wechat']}")
    log(f"  失败:       {stats['failed']}")
    log(f"{'='*50}")
    conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=5, help="处理人数")
    parser.add_argument("--debug", action="store_true", help="调试模式-先截图")
    args = parser.parse_args()
    
    if args.debug:
        # 调试模式：截全屏看看OCR能不能认
        log("🔍 调试模式 - 截图分析")
        ensure_boss_page()
        try:
            from app.vision import screen_ocr
            result = screen_ocr((88, 324, 330, 460-324), min_confidence=25)
            log(f"OCR识别 {len(result['boxes'])} 个文本", "OK")
            for box in sorted(result["boxes"], key=lambda b: b.center_y):
                if box.confidence >= 20:
                    log(f"  [{box.confidence:.0f}%] ({box.center_x},{box.center_y}) {box.text}", "OK")
        except Exception as e:
            log(f"OCR不可用: {e}", "WARN")
            log("将使用纯坐标模式运行", "INFO")
        main(max_candidates=args.max)
    else:
        main(max_candidates=args.max)
