#!/usr/bin/env python3
"""
BOSS直聘 · 沟通页简历获取轮转系统 v3.0
========================================
专注 STEP 4-8：沟通页遍历候选人 → 获取简历 → 换微信

技术栈: pyautogui点击 + CGDisplayCreateImage/numpy像素验证
不依赖: OCR / AppleScript点击 / System Events

全流程:
  STEP 4: 左导航点"沟通" → 进入沟通页
  STEP 5: 点击左侧候选人 → 右侧加载详情
  STEP 6: 检测"附件简历"按钮颜色
    ├─ 深蓝 → 点附件简历 → 预览弹出 → 点下载 → 退出
    └─ 浅蓝/灰 → 点附件简历 → 弹窗 → 确认 / 或直接回落
  STEP 7: 点"换微信" → 确认
  STEP 8: 滚到下一候选人
"""
import os, sys, time, json, random, subprocess, sqlite3
from datetime import datetime
from typing import Optional, Tuple
from pathlib import Path

import pyautogui
pyautogui.PAUSE = 0.05
pyautogui.FAILSAFE = True

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
from app.screen_capture import ScreenShot


# ============================================================
# 坐标系统 (1920×1080, Chrome窗口 {0,30,1920,1080})
# ============================================================

# --- 左侧导航栏 ---
NAV_RECOMMEND = (45, 295)      # "推荐牛人"
NAV_COMMUNICATE = (45, 375)    # "沟通"

# --- 沟通页: 候选人列表 (第二列) ---
# 候选人列表从x≈200-450，头像在左边
# 第一个候选人点击位置: 头像中心附近
CANDIDATE_LIST_X = 250         # 候选列X坐标
CANDIDATE_FIRST_Y = 340        # 第一候选人Y
CANDIDATE_GAP = 70             # 候选人间距（像素）

# --- 沟通页: 右上角按钮 ---
BTN_ONLINE_RESUME = (1395, 260)    # "在线简历" 湖蓝色
BTN_ATTACH_RESUME = (1500, 260)    # "附件简历" 深蓝/浅蓝/灰

# --- 简历预览 (深蓝→下载) ---
BTN_DOWNLOAD = (1550, 135)     # 预览窗口右上角下载
PREVIEW_EXIT = (1300, 540)     # 预览外部灰色区

# --- 底部工具栏 ---
BTN_QUICK_REPLY = (480, 770)   # "你好啊，可以聊一聊~"
BTN_EXCHANGE_WECHAT = (610, 770)   # "换微信"
BTN_SEND_MSG = (815, 955)      # 输入框 发送

# --- 弹窗 ---
POPUP_CONFIRM = (1175, 815)     # 绿色"确认"按钮
POPUP_CANCEL = (965, 815)      # 灰色"取消"


# ============================================================
# 日志 + DB
# ============================================================

DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "boss_recruitment.db"
DATA_DIR.mkdir(exist_ok=True)

def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌","ACT":"🖱️",
            "DET":"🔍","SKIP":"⏭️","STEP":"📌","WAIT":"⏳"}.get(level, "•")
    print(f"[{ts}] {icon} {msg}")

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute('''CREATE TABLE IF NOT EXISTS resume_ops (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        no INTEGER, name TEXT, action TEXT,
        dl INTEGER DEFAULT 0, req INTEGER DEFAULT 0,
        wx INTEGER DEFAULT 0, detail TEXT,
        ts TEXT DEFAULT (datetime('now','localtime'))
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS error_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        no INTEGER, step TEXT, error TEXT,
        ts TEXT DEFAULT (datetime('now','localtime'))
    )''')
    conn.commit()
    return conn


# ============================================================
# Chrome控制 (AppleScript)
# ============================================================

def osa(script: str) -> str:
    try:
        r = subprocess.run(['osascript', '-e', script],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except:
        return ""

def chrome_activate():
    """激活并最大化Chrome"""
    osa('''
        tell application "Google Chrome"
            activate
            set bounds of window 1 to {0, 30, 1920, 1080}
        end tell
    ''')
    time.sleep(1)

def chrome_url() -> str:
    return osa('tell application "Google Chrome" to get URL of active tab of window 1')


# ============================================================
# 鼠标操作
# ============================================================

def click(x: int, y: int, wait: float = 0.5):
    """用 pyautogui 点击"""
    pyautogui.moveTo(x, y, duration=0.08)
    pyautogui.click()
    time.sleep(wait)

def press_esc(times: int = 3):
    for _ in range(times):
        pyautogui.press("esc")
        time.sleep(0.2)

def press_enter():
    pyautogui.press("return")
    time.sleep(0.5)


# ============================================================
# 屏幕状态检测 (numpy像素)
# ============================================================

def snap() -> ScreenShot:
    """快速截屏"""
    return ScreenShot()

def read_pixel(x: int, y: int) -> Tuple[int, int, int]:
    """读取屏幕像素（替代 pyautogui.pixel）"""
    return snap().pixel(x, y)


# ----- 导航栏状态检测 -----

def is_on_communicate_page() -> bool:
    """检测是否在沟通页（通过左侧导航选中状态）"""
    url = chrome_url()
    if "chat/index" in url:
        return True
    if "chat/recommend" in url:
        return False
    return False

def nav_to(name: str):
    """点击左侧导航"""
    if name == "沟通":
        click(*NAV_COMMUNICATE, 1.5)
    elif name == "推荐牛人":
        click(*NAV_RECOMMEND, 1.5)
    time.sleep(2)


# ----- 按钮颜色检测 -----

def detect_attach_resume_color() -> str:
    """
    检测"附件简历"按钮颜色
    Returns: "deep_blue" | "light_blue" | "grey" | "unknown"
    """
    r, g, b = read_pixel(*BTN_ATTACH_RESUME)
    log(f"  附件简历 RGB=({r},{g},{b})", "DET")
    
    # 深蓝特征: B通道dominant
    if b > 120 and b > r + 20 and b > g + 10:
        return "deep_blue"
    # 浅蓝/湖蓝特征: G略高
    if g > 150 and b > 150:
        return "light_blue"
    # 灰色按钮
    if r + g + b < 350:
        return "grey"
    # 无法判断(可能是背景)
    return "unknown"


def detect_popup() -> str:
    """
    点击后检测弹窗状态
    Returns: "preview" | "dialog" | "none"
    """
    time.sleep(0.8)
    ss = snap()
    
    # 检测1: 预览区白色高亮
    preview_bright = ss.region_brightness(1150, 250, 500, 500)
    log(f"  预览区亮度={preview_bright:.0f}", "DET")
    
    if preview_bright > 180:
        return "preview"
    
    # 检测2: 下载区高亮
    dl_bright = ss.region_brightness(1500, 120, 120, 80)
    if dl_bright > 170:
        return "preview"
    
    # 检测3: 确认按钮绿色
    cr, cg, cb = ss.pixel(*POPUP_CONFIRM)
    if cg > 170 and cg > cr + 30:
        log(f"  确认按钮绿色 ({cr},{cg},{cb})", "DET")
        return "dialog"
    
    # 检测4: 弹窗区域背景亮度
    dialog_bright = ss.region_brightness(1070, 770, 200, 120)
    if dialog_bright > 150:
        log(f"  弹窗区域亮度={dialog_bright:.0f}", "DET")
        return "dialog"
    
    return "none"


def detect_candidate_exists(index: int) -> bool:
    """检测第index个候选人是否存在（通过像素变化）"""
    y = CANDIDATE_FIRST_Y + index * CANDIDATE_GAP
    r, g, b = read_pixel(CANDIDATE_LIST_X, y)
    # 背景色≈(200,145,85)亮度≈155，候选人头像颜色不同
    brightness = 0.299*r + 0.587*g + 0.114*b
    r_next, g_next, b_next = read_pixel(CANDIDATE_LIST_X, y + CANDIDATE_GAP)
    b_next_bright = 0.299*r_next + 0.587*g_next + 0.114*b_next
    
    # 如果连续两个位置都是背景色，没人
    if abs(brightness - b_next_bright) < 10:
        return False
    return True


# ============================================================
# STEP 4-8 核心流程
# ============================================================

def step4_enter_communicate():
    """STEP 4: 进入沟通页"""
    log("📌 STEP 4: 进入沟通页", "STEP")
    
    url = chrome_url()
    log(f"当前: {url}", "INFO")
    
    if "chat/index" not in url:
        nav_to("沟通")
    
    time.sleep(2)
    return True


def step5_click_candidate(index: int):
    """STEP 5: 点击左侧候选人"""
    y = CANDIDATE_FIRST_Y + index * CANDIDATE_GAP
    log(f"📌 STEP 5: 点击候选人 #{index+1} (y={y})", "STEP")
    click(CANDIDATE_LIST_X, y, 1.5)
    return True


def step6_handle_resume(index: int) -> dict:
    """
    STEP 6: 获取简历
    Returns: {"status": "downloaded"|"requested"|"skipped"|"failed", "detail": "..."}
    """
    log(f"📌 STEP 6: 获取简历", "STEP")
    time.sleep(0.5)
    
    # 先检测按钮颜色
    color = detect_attach_resume_color()
    log(f"  颜色判断: {color}", "DET")
    
    # == 策略A: 直接点附件简历 ==
    click(*BTN_ATTACH_RESUME, 1.0)
    popup = detect_popup()
    log(f"  弹窗检测: {popup}", "DET")
    
    # 如果是预览（简历弹出来了）
    if popup == "preview":
        click(*BTN_DOWNLOAD, 2.5)
        log(f"  ✅ 简历已下载", "OK")
        # 退出预览
        for _ in range(3):
            click(*PREVIEW_EXIT, 0.3)
        press_esc(3)
        time.sleep(0.5)
        return {"status": "downloaded", "detail": "附件简历→下载"}
    
    # 如果是确认弹窗
    if popup == "dialog":
        click(*POPUP_CONFIRM, 1.5)
        press_enter(2)
        log(f"  ✅ 简历请求已发送", "OK")
        return {"status": "requested", "detail": "附件简历→请求"}
    
    # 无弹窗 → 可能候选人还没回复 → 尝试换微信后跳过
    log(f"  无弹窗 → 候选人可能未回复", "WARN")
    return {"status": "skipped", "detail": "附件简历无反应"}


def step7_exchange_wechat() -> bool:
    """STEP 7: 换微信"""
    log(f"📌 STEP 7: 换微信", "STEP")
    
    click(*BTN_EXCHANGE_WECHAT, 1.5)
    popup = detect_popup()
    
    if popup == "dialog":
        click(*POPUP_CONFIRM, 1.5)
        press_enter(2)
        log(f"  ✅ 微信已交换", "OK")
        return True
    
    if popup == "preview":
        click(*POPUP_CONFIRM, 1.5)
        return True
    
    log(f"  无弹窗，可能已自动发送", "INFO")
    return True


def step8_scroll_to_next(index: int):
    """STEP 8: 滚到下一候选人"""
    log(f"📌 STEP 8: 滚到下一候选人", "STEP")
    
    if index >= 8:  # 每8人滚一次
        pyautogui.scroll(-5)
        time.sleep(0.5)
    pyautogui.scroll(-2)
    time.sleep(0.8)


# ============================================================
# 完整流程：处理一个候选人
# ============================================================

def process_candidate(index: int, conn) -> dict:
    """处理单个候选人 (STEP 5-7)"""
    name = f"候选人#{index+1}"
    result = {"no": index+1, "name": name, "resume": "failed", "wechat": False, "success": False}
    
    try:
        step5_click_candidate(index)
        resume = step6_handle_resume(index)
        
        time.sleep(0.5)
        wechat_ok = step7_exchange_wechat()
        
        # 记录数据库
        dl = 1 if resume["status"] == "downloaded" else 0
        req = 1 if resume["status"] == "requested" else 0
        conn.execute(
            "INSERT INTO resume_ops VALUES (NULL,?,?,?,?,?,?,?,datetime('now','localtime'))",
            (index+1, name, resume["status"], dl, req, 1 if wechat_ok else 0, resume.get("detail",""))
        )
        conn.commit()
        
        result["resume"] = resume["status"]
        result["wechat"] = wechat_ok
        result["success"] = True
        log(f"✅ [{index+1}] 简历={resume['status']} 微信={'✅' if wechat_ok else '❌'}", "OK")
        
    except Exception as e:
        log(f"❌ [{index+1}] 异常: {e}", "ERR")
        conn.execute("INSERT INTO error_log VALUES (NULL,?,?,?,datetime('now','localtime'))",
                     (index+1, "process", str(e)))
        conn.commit()
        import traceback; traceback.print_exc()
    
    return result


# ============================================================
# 主入口
# ============================================================

def main(max_candidates: int = 10):
    log("="*60)
    log("🚀 BOSS直聘沟通页 · 简历获取轮转 v3.0")
    log(f"   上限: {max_candidates}人 | 1920×1080 | pyautogui+numpy")
    log("="*60)
    
    conn = init_db()
    chrome_activate()
    
    # STEP 4
    step4_enter_communicate()
    time.sleep(1)
    
    stats = {"downloaded": 0, "requested": 0, "skipped": 0, "wechat": 0, "total": 0}
    
    for i in range(max_candidates):
        log(f"\n{'─'*50}")
        log(f"🎯 候选人 #{i+1}/{max_candidates}")
        
        # 尝试处理候选人（列表到底会点击到背景，无后续弹窗）
        result = process_candidate(i, conn)
        stats["total"] += 1
        if result["resume"] == "downloaded": stats["downloaded"] += 1
        elif result["resume"] == "requested": stats["requested"] += 1
        else: stats["skipped"] += 1
        if result["wechat"]: stats["wechat"] += 1
        
        log(f"📊 [{i+1}] 已处理 | 下载{stats['downloaded']} 请求{stats['requested']} 跳过{stats['skipped']} 微信{stats['wechat']}")
        
        if i < max_candidates - 1:
            step8_scroll_to_next(i)
        
        time.sleep(random.uniform(0.5, 1.0))
    
    log(f"\n{'='*50}")
    log(f"🏁 完成! {stats['downloaded']}下载 {stats['requested']}请求 {stats['skipped']}跳过 微信{stats['wechat']}")
    log(f"数据: {DB_PATH}")
    log("="*50)
    
    conn.close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=5, help="最大处理人数")
    args = ap.parse_args()
    
    main(args.max)
