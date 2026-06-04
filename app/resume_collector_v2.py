#!/usr/bin/env python3
"""
BOSS直聘 · 简历获取轮转系统 v2.3 — Vision OCR + 原生截图版
============================================================
macOS 26.2 + Chrome 148 兼容版

核心升级 (vs v2.2):
  1. ✅ screen_capture.py — 用CGDisplayCreateImage+numpy替代PIL ImageGrab
  2. ✅ Vision OCR 用于弹窗文字检测 (修复HDR色彩空间)
  3. ✅ 原生像素读取替代pyautogui.pixel() (避免TCC拦截)
  4. ✅ 区域亮度检测替代颜色猜测试错法

关键坐标 (1920×1080, Chrome全屏, window bounds {0,30,1920,1080}):
"""
import os, sys, time, json, random, subprocess, sqlite3, re
from datetime import datetime
from typing import Optional, Tuple, List, Dict
from pathlib import Path

import pyautogui
pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = True

# ============================================================
# 项目路径
# ============================================================
ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "boss_recruitment.db"
DATA_DIR.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT))

# 导入原生截图模块
from app.screen_capture import ScreenShot, VisionOCR


# ============================================================
# 日志
# ============================================================
def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌","ACT":"🖱️","WAIT":"⏳",
            "DB":"💾","DET":"🔍","SKIP":"⏭️","STEP":"📌"}.get(level, "•")
    print(f"[{ts}] {icon} {msg}")

def json_log(data: dict):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] 💾 {json.dumps(data, ensure_ascii=False)}")


# ============================================================
# 数据库
# ============================================================
def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute('''CREATE TABLE IF NOT EXISTS resume_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_no INTEGER,
        candidate_name TEXT,
        action TEXT,
        resume_downloaded INTEGER DEFAULT 0,
        resume_requested INTEGER DEFAULT 0,
        wechat_exchanged INTEGER DEFAULT 0,
        detail TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS error_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_no INTEGER,
        step TEXT,
        error TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )''')
    conn.commit()
    return conn

def log_db(conn, no, name, action, dl=0, req=0, wx=0, detail=""):
    conn.execute("INSERT INTO resume_operations VALUES (NULL,?,?,?,?,?,?,?,datetime('now','localtime'))",
                 (no, name, action, dl, req, wx, detail))
    conn.commit()

def log_err(conn, no, step, err):
    conn.execute("INSERT INTO error_log VALUES (NULL,?,?,?,datetime('now','localtime'))", (no, step, str(err)))
    conn.commit()


# ============================================================
# Chrome控制 (AppleScript)
# ============================================================
def osa(script: str) -> str:
    try:
        r = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except:
        return ""

def chrome_activate():
    osa('''
        tell application "Google Chrome"
            activate
            set bounds of window 1 to {0, 30, 1920, 1080}
        end tell
    ''')
    time.sleep(1)

def chrome_url():
    return osa('tell application "Google Chrome" to get URL of active tab of window 1')

def chrome_goto(url: str):
    osa(f'tell application "Google Chrome" to open location "{url}"')
    time.sleep(2.5)


# ============================================================
# 坐标系统 (1920×1080基准)
# ============================================================
# 左侧导航栏
NAV_COMMUNICATION = (44, 372)       # "沟通"按钮

# 联系人列表
CONTACT_FIRST = (253, 368)          # 第一个联系人
CONTACT_GAP = 68                    # Y轴间距

# 聊天面板顶部
BTN_ATTACH_RESUME = (790, 275)     # "附件简历"
BTN_ONLINE_RESUME = (700, 275)     # "在线简历"

# 简历预览区  
BTN_DOWNLOAD = (1550, 135)         # "下载"
EXIT_PREVIEW = (1300, 540)         # 预览外灰色区

# 底部工具栏
BTN_REQUEST_RESUME = (545, 770)    # "求简历"
BTN_EXCHANGE_WECHAT = (630, 770)   # "换微信"

# 弹窗
POPUP_CONFIRM = (1175, 815)        # "确认"/"确定"
POPUP_CANCEL = (965, 815)          # "取消"


# ============================================================
# 鼠标操作
# ============================================================
def click(x: int, y: int, wait: float = 0.4):
    pyautogui.moveTo(x, y, duration=0.08)
    pyautogui.click()
    time.sleep(wait)

def click_c(name: str, wait: float = 0.4):
    coord = {
        "沟通导航": NAV_COMMUNICATION,
        "附件简历": BTN_ATTACH_RESUME,
        "在线简历": BTN_ONLINE_RESUME,
        "求简历":   BTN_REQUEST_RESUME,
        "换微信":   BTN_EXCHANGE_WECHAT,
        "确认":     POPUP_CONFIRM,
        "取消":     POPUP_CANCEL,
        "下载":     BTN_DOWNLOAD,
        "退出预览": EXIT_PREVIEW,
    }.get(name)
    if coord:
        click(coord[0], coord[1], wait)

def press_esc(times: int = 2):
    for _ in range(times):
        pyautogui.press("esc")
        time.sleep(0.3)

def press_enter(times: int = 2):
    for _ in range(times):
        pyautogui.press("return")
        time.sleep(0.3)


# ============================================================
# 屏幕状态检测 (ScreenShot + Vision OCR)
# ============================================================

def capture_screen() -> ScreenShot:
    """快速截屏"""
    return ScreenShot()

def detect_popup_after_click() -> str:
    """
    点击按钮后，用原生截图检测发生了什么:
      - "preview" → 简历预览弹出 (右下角有下载按钮)
      - "dialog"  → 确认弹窗 (有确定/取消按钮)
      - "unknown" → 无变化
    """
    time.sleep(0.8)
    ss = capture_screen()
    
    # === 检测A: 预览区亮度变化 (简历预览弹出时中间变白色) ===
    preview_brightness = ss.region_brightness(1150, 250, 500, 500)
    log(f"  亮度: 预览区={preview_brightness:.0f}", "DET")
    
    if preview_brightness > 180:
        log(f"  检测: 预览区高亮({preview_brightness:.0f}) → 简历预览！", "DET")
        return "preview"
    
    # === 检测B: 下载按钮区域变亮 ===
    dl_brightness = ss.region_brightness(1500, 120, 120, 80)
    if dl_brightness > 180:
        log(f"  检测: 下载区高亮({dl_brightness:.0f}) → 简历预览！", "DET")
        return "preview"
    
    # === 检测C: OCR扫描右下角→底部区域 ===
    ocr_results = VisionOCR.recognize(ss.cg_image, min_confidence=0.5)
    ocr_texts = [r["text"] for r in ocr_results if r["y"] > 700]  # 底部区域
    
    for text in ocr_texts:
        if "确定" in text or "确认" in text or "发送" in text:
            log(f"  OCR检测: 发现「{text}」→ 确认弹窗", "DET")
            return "dialog"
    
    # === 检测D: 确认按钮区域亮度/颜色变化 ===
    # 确认按钮通常是浅蓝绿色背景
    confirm_r, confirm_g, confirm_b = ss.pixel(*POPUP_CONFIRM)
    if confirm_g > 180 and confirm_g > confirm_r:
        log(f"  RGB检测: 确认按钮绿色({confirm_r},{confirm_g},{confirm_b}) → 弹窗", "DET")
        return "dialog"
    
    # === 检测E: 弹窗边框区域亮度 ===
    dialog_brightness = ss.region_brightness(1070, 770, 200, 100)
    if dialog_brightness > 160:
        log(f"  检测: 弹窗区域中亮({dialog_brightness:.0f}) → 可能弹窗", "DET")
        return "dialog"
    
    # 无变化
    return "unknown"


def detect_resume_button_status() -> str:
    """
    检测"附件简历"按钮状态:
      - "deep_blue" → 深蓝(已发送简历) → 点后会弹出简历预览
      - "light_blue" → 浅蓝(没发过简历) → 点后会弹出确认窗
      - "unknown" → 无法判断
    """
    ss = capture_screen()
    r, g, b = ss.pixel(*BTN_ATTACH_RESUME)
    
    # 深蓝特征: B > R 且 B > G (蓝色通道dominant)
    if b > r and b > g:
        log(f"  RGB:({r},{g},{b}) → 深蓝(已发简历)", "DET")
        return "deep_blue"
    
    # 浅蓝特征: B > G 但 R 也高 (浅蓝色背景)
    if b > g and r > g:
        log(f"  RGB:({r},{g},{b}) → 浅蓝(未发)", "DET")
        return "light_blue"
    
    # 其他颜色
    log(f"  RGB:({r},{g},{b}) → 无法判断颜色", "DET")
    return "unknown"


# ============================================================
# 步骤1: 进入沟通页
# ============================================================
def ensure_communication_page():
    """确保在BOSS沟通页面"""
    chrome_activate()
    url = chrome_url()
    
    if 'zhipin.com' not in url:
        chrome_goto("https://www.zhipin.com/web/chat/")
    elif 'chat' not in url:
        chrome_goto("https://www.zhipin.com/web/chat/")
    
    log(f"当前: {chrome_url()[:70]}", "OK")
    time.sleep(1)
    click_c("沟通导航", 1.5)
    return True


# ============================================================
# 步骤2: 点击候选人
# ============================================================
def click_candidate(index: int):
    """点击左侧列表第index个候选人"""
    y = CONTACT_FIRST[1] + index * CONTACT_GAP
    click(CONTACT_FIRST[0], y, 1.5)
    log(f"点击候选人 #{index+1} (y={y})", "ACT")


# ============================================================
# 步骤3: 获取简历 (双模式)
# ============================================================
def handle_resume_pixel(index: int, name: str) -> Dict:
    """
    方案A — 颜色检测模式 (需要TCC屏幕录制权限)
    先截屏检测附件简历按钮颜色 → 深蓝直接下载 / 浅蓝确认请求
    """
    log(f"📄 [颜色模式] 获取简历 [{name}]", "STEP")
    time.sleep(random.uniform(0.5, 1.0))
    
    # 检测按钮颜色
    status = detect_resume_button_status()
    
    if status == "deep_blue":
        # === 深蓝 → 已发送简历 → 点击下载 ===
        log(f"  [{name}] 深蓝按钮 → 已发送简历", "OK")
        click_c("附件简历", 1.5)
        
        state = detect_popup_after_click()
        
        if state == "preview":
            click_c("下载", 2.5)
            log(f"  [{name}] ✅ 下载成功", "OK")
            for _ in range(3):
                click_c("退出预览", 0.3)
            press_esc(3)
            return {"status": "downloaded", "detail": "深蓝-已下载"}
        
        elif state == "dialog":
            click_c("确认", 1.5)
            press_enter(2)
            log(f"  [{name}] ✅ 请求已发送", "OK")
            return {"status": "requested", "detail": "深蓝-确认请求"}
        
        else:
            log(f"  [{name}] 点附件简历无反应 → 尝试求简历", "WARN")
    
    # 浅蓝或未知 → 直接点击(会弹出确认窗)
    click_c("附件简历", 1.5)
    state = detect_popup_after_click()
    
    if state == "dialog":
        click_c("确认", 1.5)
        press_enter(2)
        log(f"  [{name}] ✅ 简历请求已发送", "OK")
        return {"status": "requested", "detail": "附件简历→确认"}
    
    elif state == "preview":
        click_c("下载", 2.5)
        log(f"  [{name}] ✅ 下载成功", "OK")
        for _ in range(3):
            click_c("退出预览", 0.3)
        press_esc(3)
        return {"status": "downloaded", "detail": "附件简历→下载"}
    
    # 兜底: 求简历
    log(f"  [{name}] 附件简历无响应 → 尝试求简历", "INFO")
    click_c("求简历", 1.5)
    state2 = detect_popup_after_click()
    
    if state2 == "dialog":
        click_c("确认", 1.5)
        press_enter(2)
        return {"status": "requested", "detail": "求简历→确认"}
    elif state2 == "preview":
        click_c("下载", 2.5)
        for _ in range(3):
            click_c("退出预览", 0.3)
        press_esc(3)
        return {"status": "downloaded", "detail": "求简历→下载"}
    
    log(f"  [{name}] ❌ 所有操作无响应", "ERR")
    return {"status": "none", "detail": "无响应"}


# ============================================================
# 步骤4: 换微信
# ============================================================
def handle_wechat(name: str) -> bool:
    """换微信流程"""
    log(f"📱 换微信 [{name}]", "STEP")
    time.sleep(random.uniform(0.5, 1.0))
    
    click_c("换微信", 1.5)
    state = detect_popup_after_click()
    
    if state in ("dialog", "preview", "unknown"):
        click_c("确认", 1.5)
        press_enter(2)
        log(f"  [{name}] ✅ 微信交换完成", "OK")
        return True
    
    log(f"  [{name}] 无弹窗，可能已自动发送", "INFO")
    return True


# ============================================================
# 步骤5: 轮转
# ============================================================
def scroll_to_next(index: int):
    """滚到下一个候选人"""
    log(f"⏭️ 轮转下一个", "STEP")
    pyautogui.moveTo(253, 500, duration=0.1)
    if index >= 8:
        pyautogui.scroll(-5)
        time.sleep(0.5)
    pyautogui.scroll(-3)
    time.sleep(0.5)


# ============================================================
# 主流程
# ============================================================
def process_one(index: int, conn, method: str = "pixel"):
    """处理单个候选人"""
    name = f"候选人#{index+1}"
    
    try:
        click_candidate(index)
        
        if method == "pixel":
            resume = handle_resume_pixel(index+1, name)
        else:
            # 默认试错法 (之前的逻辑)
            from app.resume_collector_v2_bak import handle_resume
            resume = {"status": "error", "detail": "备份模式"}
        
        time.sleep(0.5)
        wx = handle_wechat(name)
        
        dl = 1 if resume["status"] == "downloaded" else 0
        req = 1 if resume["status"] == "requested" else 0
        log_db(conn, index+1, name, resume["status"], dl, req, 1 if wx else 0, resume.get("detail", ""))
        
        log(f"✅ [{index+1}] 简历={resume['status']} 微信={'✅' if wx else '❌'}", "OK")
        return {"name": name, "resume": resume["status"], "wechat": wx, "success": True}
        
    except Exception as e:
        log(f"❌ [{index+1}] 异常: {e}", "ERR")
        log_err(conn, index+1, "process", str(e))
        import traceback
        traceback.print_exc()
        return {"name": name, "resume": "error", "wechat": False, "success": False}


def main(max_candidates: int = 10, method: str = "pixel"):
    log("=" * 60)
    log("🚀 BOSS直聘 · 简历获取轮转系统 v2.3")
    log(f"   上限: {max_candidates} 人  |  屏幕: 1920×1080")
    log(f"   模式: {method}")
    log("=" * 60)
    
    conn = init_db()
    
    if not ensure_communication_page():
        log("❌ 无法进入沟通页", "ERR")
        return
    
    stats = {"downloaded": 0, "requested": 0, "wechat": 0, "failed": 0, "total": 0}
    
    for i in range(max_candidates):
        log(f"\n{'─'*50}")
        log(f"🎯 候选人 #{i+1}/{max_candidates}", "STEP")
        
        result = process_one(i, conn, method)
        stats["total"] += 1
        
        if result["resume"] == "downloaded":
            stats["downloaded"] += 1
            stats["wechat"] += 1 if result["wechat"] else 0
        elif result["resume"] == "requested":
            stats["requested"] += 1
            stats["wechat"] += 1 if result["wechat"] else 0
        else:
            stats["failed"] += 1
        
        log(f"📊 [{i+1}/{max_candidates}] 已下载{stats['downloaded']} / 已请求{stats['requested']} / 微信{stats['wechat']}", "INFO")
        
        # 滚动到下一个
        if i < max_candidates - 1:
            scroll_to_next(i)
        
        # 间隔
        time.sleep(random.uniform(0.5, 1.5))
    
    log(f"\n{'='*50}")
    log(f"🏁 运行完成! {stats['downloaded']}下载 / {stats['requested']}请求 / {stats['wechat']}微信 / {stats['failed']}失败")
    log(f"数据: {DB_PATH}")
    log("=" * 50)
    
    conn.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=10, help="最大处理人数")
    parser.add_argument("--method", default="pixel", choices=["pixel", "trial"])
    args = parser.parse_args()
    main(args.max, args.method)
