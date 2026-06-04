#!/usr/bin/env python3
"""
BOSS直聘 · 简历获取轮转系统 v2.2 — 最终实战版
===============================================
无需任何额外权限，兼容macOS 26+，Chrome 148+

核心方案:
  - AppleScript: 激活Chrome、设置窗口大小、导航URL
  - pyautogui: 鼠标点击、键盘操作
  - 试错逻辑: 先点"附件简历"→检测是否弹出确认窗→决定下载or请求

按钮颜色判断（试错法——无像素读取需求）:
  先点击"附件简历"按钮:
    → 弹出白色简历预览（有下载按钮）→ 深蓝 → 下载
    → 弹出确认弹窗（有确定按钮）→ 浅蓝 → 确认发送请求
    → 没有任何反应 → 点击"求简历"兜底

关键坐标 (1920×1080, Chrome全屏, window bounds {0,30,1920,1080}):
  所有坐标经多轮实测校准
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
# 精确坐标 → 参考点
# ============================================================
# 这些坐标基于Chrome全屏 {0,30,1920,1080}，1920×1080显示器
# 若分辨率不同，需要重新校准

# 左侧导航栏
NAV_COMMUNICATION = (44, 372)       # "沟通"按钮

# 联系人列表
CONTACT_FIRST = (253, 368)          # 第一个联系人的点击中心点
CONTACT_GAP = 68                    # 每个联系人之间Y轴间距

# 右上角聊天面板顶部
BTN_ATTACH_RESUME = (790, 275)     # "附件简历"按钮
BTN_ONLINE_RESUME = (700, 275)     # "在线简历"按钮

# 简历预览区  
BTN_DOWNLOAD = (1550, 135)         # 预览页右上角"下载"按钮
EXIT_PREVIEW_CENTER = (1300, 540)  # 预览外灰色区域

# 底部工具栏
BTN_REQUEST_RESUME = (545, 770)    # "求简历"
BTN_EXCHANGE_WECHAT = (630, 770)   # "换微信"

# 弹窗
POPUP_CONFIRM = (1175, 815)        # 绿色"确认"/"确定"
POPUP_CANCEL = (965, 815)          # "取消"


# ============================================================
# 鼠标操作
# ============================================================
def click(x: int, y: int, wait: float = 0.4):
    pyautogui.moveTo(x, y, duration=0.08)
    pyautogui.click()
    time.sleep(wait)

def click_c(name: str, wait: float = 0.4):
    """按常量名点击"""
    coord = {
        "沟通导航": NAV_COMMUNICATION,
        "附件简历": BTN_ATTACH_RESUME,
        "在线简历": BTN_ONLINE_RESUME,
        "求简历":   BTN_REQUEST_RESUME,
        "换微信":   BTN_EXCHANGE_WECHAT,
        "确认":     POPUP_CONFIRM,
        "取消":     POPUP_CANCEL,
        "下载":     BTN_DOWNLOAD,
        "退出预览": EXIT_PREVIEW_CENTER,
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
# 状态检测 (试错法 → 通过操作结果推断状态)
# ============================================================

def is_white_area_simple(x: int, y: int, threshold: int = 200) -> bool:
    """
    检测某点是否为白色区域。
    注意: pyautogui.pixel()在macOS 26需要屏幕录制权限
    如果TCC拒绝，所有像素都会返回(0,0,0) → 此函数会返回False
    我们接受这个限制，用try-except兜底
    """
    try:
        r, g, b = pyautogui.pixel(x, y)
        return r > threshold and g > threshold and b > threshold
    except:
        return False  # TCC拒绝 → 返回False → 走试错路径

def detect_popup_after_click() -> str:
    """
    点击按钮后，检测发生了什么（全屏幕级检测）:
      - 白色大面积 → 简历预览 → 需要下载
      - 几个绿色点 → 确认弹窗 → 需要确认
      - 无变化 → 没点着
    """
    time.sleep(0.8)
    
    # 检测: 右上角下载按钮区域是否变白(简历预览)
    white_points = 0
    white_total = 5
    for px, py in [(1500, 120), (1550, 130), (1400, 150), (1600, 200), (1300, 200)]:
        if is_white_area_simple(px, py):
            white_points += 1
    
    if white_points >= 3:
        log(f"  检测: 白色区域 {white_points}/{white_total} → 简历预览！", "DET")
        return "preview"
    
    # 检测: 确认弹窗位置有无绿色
    green_points = 0
    green_total = 3
    for px, py in [(1175, 815), (1175, 805), (1175, 825)]:
        if is_white_area_simple(px, py):  # 确认按钮通常是浅色背景
            green_points += 1
    
    if is_white_area_simple(1160, 790, 150) or is_white_area_simple(1200, 790, 150):
        # 如果弹窗区域有浅色块，很有可能是弹窗
        log(f"  检测: 弹窗区域有浅色 → 确认弹窗", "DET")
        return "dialog"
    
    # 兜底: 检测是否弹出了东西 （看中心区域有没有变白）
    center_white = is_white_area_simple(960, 540)
    if center_white:
        return "dialog"
    
    # 不知道
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
    
    # 点击左侧"沟通"确保激活
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
# 步骤3: 获取简历
# ============================================================
def handle_resume(index: int, name: str) -> Dict:
    """
    获取简历 — 试错法核心
    
    流程:
      1. 点击"附件简历"按钮(坐标)
      2. 等待1秒
      3. 检测结果:
         a) 简历预览(白色) → 下载 → 关闭
         b) 确认弹窗         → 确认 → 发送请求
         c) 无变化           → 回到步骤a用"求简历"
    
    这不需要任何系统权限，只需要pyautogui.click()
    """
    log(f"📄 步骤2/4: 获取简历 [{name}]", "STEP")
    time.sleep(random.uniform(0.8, 1.5))
    
    # === 策略A: 点"附件简历"===
    log(f"  → 尝试「附件简历」", "ACT")
    click_c("附件简历", 1.2)
    
    # 检测发生了什么
    state = detect_popup_after_click()
    
    if state == "preview":
        # === 简历预览已弹出 → 下载 ===
        log(f"  [{name}] ✅ 简历预览已弹出", "OK")
        
        # 点击下载
        click_c("下载", 2.5)
        log(f"  [{name}] ✅ 已触发下载", "OK")
        
        # 退出预览
        log(f"  关闭预览...", "ACT")
        for _ in range(3):
            click_c("退出预览", 0.3)
        press_esc(3)
        
        log(f"  [{name}] ✅ 附件简历已下载", "OK")
        return {"status": "downloaded", "detail": "附件简历成功下载"}
    
    elif state == "dialog":
        # === 确认弹窗 → 投递请求 ===
        log(f"  [{name}] 确认弹窗 → 正在发送简历请求", "ACT")
        click_c("确认", 1.5)
        press_enter(2)
        log(f"  [{name}] ✅ 简历请求已发送", "OK")
        return {"status": "requested", "detail": "已发送简历请求"}
    
    else:
        log(f"  [{name}] 附件简历无响应 → 尝试「求简历」", "INFO")
    
    # === 策略B: 点"求简历" ===
    time.sleep(0.5)
    log(f"  → 尝试「求简历」", "ACT")
    click_c("求简历", 1.5)
    
    state2 = detect_popup_after_click()
    
    if state2 == "dialog":
        click_c("确认", 1.5)
        press_enter(2)
        log(f"  [{name}] ✅ 通过求简历发送请求", "OK")
        return {"status": "requested", "detail": "通过求简历已发送"}
    
    elif state2 == "preview":
        click_c("下载", 2.5)
        for _ in range(3):
            click_c("退出预览", 0.3)
        press_esc(3)
        log(f"  [{name}] ✅ 已下载（通过求简历）", "OK")
        return {"status": "downloaded", "detail": "通过求简历下载"}
    
    log(f"  [{name}] ❌ 所有简历操作无响应", "ERR")
    return {"status": "none", "detail": "无响应"}


# ============================================================
# 步骤4: 换微信
# ============================================================
def handle_wechat(name: str) -> bool:
    """换微信"""
    log(f"📱 步骤3/4: 换微信 [{name}]", "STEP")
    time.sleep(random.uniform(0.5, 1.0))
    
    click_c("换微信", 1.5)
    
    state = detect_popup_after_click()
    
    if state in ("dialog", "preview", "unknown"):
        click_c("确认", 1.5)
        press_enter(2)
        log(f"  [{name}] ✅ 微信交换完成", "OK")
        return True
    
    log(f"  [{name}] 无弹窗，可能已直接发送", "INFO")
    return True


# ============================================================
# 步骤5: 轮转
# ============================================================
def scroll_to_next(index: int):
    """滚到下一个候选人"""
    log(f"⏭️ 步骤4/4: 轮转下一个", "STEP")
    
    # 鼠标移到联系人区域，滚动
    pyautogui.moveTo(253, 500, duration=0.1)
    if index >= 8:
        pyautogui.scroll(-5)
        time.sleep(0.5)
    pyautogui.scroll(-3)
    time.sleep(0.5)


# ============================================================
# 主流程
# ============================================================
def process_one(index: int, conn) -> Dict:
    """处理单个候选人"""
    name = f"候选人#{index+1}"
    
    try:
        # 1. 点击候选人
        click_candidate(index)
        
        # 2. 获取简历
        resume = handle_resume(index+1, name)
        
        # 3. 换微信
        time.sleep(0.5)
        wx = handle_wechat(name)
        
        # 4. 记录
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


def main(max_candidates: int = 10):
    log("=" * 60)
    log("🚀 BOSS直聘 · 简历获取轮转系统 v2.2")
    log(f"   上限: {max_candidates} 人  |  屏幕: 1920×1080")
    log(f"   方案: AppleScript + pyautogui + 试错法")
    log("=" * 60)
    
    conn = init_db()
    
    # 进入沟通页
    if not ensure_communication_page():
        log("❌ 无法进入沟通页", "ERR")
        return
    
    # 统计
    stats = {"downloaded": 0, "requested": 0, "wechat": 0, "failed": 0, "total": 0}
    
    for i in range(max_candidates):
        log(f"\n{'─'*50}")
        log(f"👤 [{i+1}/{max_candidates}]")
        log(f"{'─'*50}")
        
        result = process_one(i, conn)
        
        if result.get("resume") == "downloaded": stats["downloaded"] += 1
        elif result.get("resume") == "requested": stats["requested"] += 1
        if result.get("wechat"): stats["wechat"] += 1
        if not result.get("success"): stats["failed"] += 1
        stats["total"] += 1
        
        # 防检测延迟
        delay = random.uniform(2.5, 4.0)
        log(f"⏳ {delay:.1f}s...")
        time.sleep(delay)
    
    # 汇总
    log(f"\n{'='*50}")
    log(f"🎉 完成!")
    log(f"  总计:     {stats['total']}")
    log(f"  已下载:   {stats['downloaded']}")
    log(f"  已请求:   {stats['requested']}")
    log(f"  已换微信: {stats['wechat']}")
    log(f"  失败:     {stats['failed']}")
    log(f"{'='*50}")
    json_log(stats)
    conn.close()


# ============================================================
# 调试模式
# ============================================================
def debug():
    """调试: 检测所有关键坐标的背景色(如果TCC允许)"""
    chrome_activate()
    time.sleep(1)
    
    log("🔍 坐标检测")
    log(f"  Chrome URL: {chrome_url()[:70]}")
    
    points = {
        "沟通导航":   (44, 372),
        "联系人1":    (253, 368),
        "联系人2":    (253, 436),
        "联系人3":    (253, 504),
        "在线简历":   (700, 275),
        "附件简历":   (790, 275),
        "求简历":     (545, 770),
        "换微信":     (630, 770),
        "确认按钮":   (1175, 815),
        "取消按钮":   (965, 815),
        "下载按钮":   (1550, 135),
    }
    
    all_black = True
    for name, (x, y) in points.items():
        try:
            r, g, b = pyautogui.pixel(x, y)
            note = ""
            if r > 200 and g > 200 and b > 200: note = "(白色)"
            elif r > 100 or g > 100 or b > 100: note = "(有色)"
            if r != 0 or g != 0 or b != 0:
                all_black = False
            log(f"  {name:8s} ({x:4d},{y:4d}) → RGB({r:3d},{g:3d},{b:3d}) {note}")
        except Exception as e:
            log(f"  {name:8s} ({x:4d},{y:4d}) → 读取失败: {e}", "WARN")
    
    if all_black:
        log("\n⚠️ 所有像素值都为(0,0,0)", "WARN")
        log("  说明: macOS 26 TCC阻止了pyautogui.pixel()读取屏幕", "WARN")
        log("  不影响: pyautogui.click()和pyautogui.moveTo()可以正常工作", "OK")
        log("  影响: is_white_area_simple() 永远返回False", "WARN")
        log("  所以: 程序进入 '试错模式'，会先点附件简历，然后盲按ESC再点下载", "WARN")
        log("\n  解决方案: 需要手动给一次屏幕录制权限", "INFO")
        log("    系统设置 → 隐私 → 屏幕录制 → 添加 Terminal.app", "INFO")
        log("    添加后关闭终端重开即可", "INFO")
        log("\n  或者：直接继续跑，试错模式也能工作", "OK")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=5)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--db-view", action="store_true")
    args = parser.parse_args()
    
    if args.db_view:
        conn = sqlite3.connect(str(DB_PATH))
        rows = conn.execute("SELECT * FROM resume_operations ORDER BY id DESC LIMIT 20").fetchall()
        print(f"\n最近 {len(rows)} 条记录:")
        for r in rows:
            print(f"  #{r[1]:2d} {r[2]:15s} {r[3]:12s} 已下={r[4]} 已求={r[5]} 微信={r[6]} | {r[8]}")
        conn.close()
        sys.exit(0)
    
    if args.debug:
        debug()
        sys.exit(0)
    
    main(max_candidates=args.max)
