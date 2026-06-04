#!/usr/bin/env python3
"""
BOSS直聘 · AI多轮对话 v6.0 - Linux Docker版
=============================================
改造点：
- macOS Vision OCR → Tesseract OCR
- 有头 Chrome（noVNC 可见）
- nodriver 替代 pyautogui（部分）
- 完整 Docker 兼容
"""
import time
import sys
import os
import json
import asyncio
import subprocess
import sqlite3
import re
from datetime import datetime
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()

# Linux 版模块
from app.vision_linux import screen_ocr, find_confirm_button, OcrTextBox
from app.screen_linux import activate_chrome, move_and_click, scroll_down, scroll_up

import pyautogui
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1

import httpx

# ============================================================
# 配置
# ============================================================

BASE_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DB_PATH = os.path.join(DATA_DIR, "boss_recruitment.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

MAX_CANDIDATES = 50
MAX_CHAT_ROUNDS = 3
NEW_MSG_WAIT = 5
PAGE_SIZE = 8
ROW_PITCH = 79

SLOT_CURSOR = 0

AI_KEY = os.getenv("DEEPSEEK_API_KEY", "")
AI_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
AI_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

SYSTEM_PROMPT = '''你是AI全栈开发工程师岗位的招聘HR，在BOSS直聘上与候选人聊天。

回复规则：
1. 回复简洁自然，不超过60字，像真人HR
2. 第一轮：自我介绍 + 请对方介绍技术背景
3. 后续：根据对方回复针对性追问
4. 绝对不要出现"注意"、"对方未回复"等系统提示语
5. 不要自问自答，不要替候选人说话
6. 绝对不要索要微信、电话等敏感信息
7. 自我介绍时只说"我是招聘HR"，不要加公司名称'''

# ============================================================
# 日志
# ============================================================

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌","CHAT":"💬",
            "DEBUG":"🔍","STEP":"📌","AI":"🤖","SKIP":"⏭️","ACT":"🖱️"}.get(level,"ℹ️")
    print(f"[{ts}] {icon} {msg}")

    # 写入日志文件
    log_file = os.path.join(LOGS_DIR, f"run_{datetime.now().strftime('%Y%m%d')}.log")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] [{level}] {msg}\n")

# ============================================================
# 数据库
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        boss_id TEXT UNIQUE,
        name TEXT,
        school TEXT,
        degree TEXT,
        years INTEGER,
        position TEXT,
        company TEXT,
        status TEXT DEFAULT 'new',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_name TEXT,
        round_index INTEGER DEFAULT 0,
        action TEXT,
        ai_message TEXT,
        candidate_message TEXT,
        detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS processed_candidates (
        candidate_key TEXT PRIMARY KEY,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

def save_conversation(candidate_name: str, round_idx: int, action: str,
                       ai_msg: str = "", cand_msg: str = "", detail: str = ""):
    conn = get_db()
    conn.execute('''INSERT INTO conversations
        (candidate_name, round_index, action, ai_message, candidate_message, detail)
        VALUES (?, ?, ?, ?, ?, ?)''',
        (candidate_name, round_idx, action, ai_msg, cand_msg, detail))
    conn.commit()
    conn.close()

def is_processed(candidate_key: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT 1 FROM processed_candidates WHERE candidate_key = ?",
        (candidate_key,)
    ).fetchone()
    conn.close()
    return row is not None

def mark_processed(candidate_key: str):
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO processed_candidates (candidate_key) VALUES (?)",
        (candidate_key,)
    )
    conn.commit()
    conn.close()

# ============================================================
# AI 对话
# ============================================================

def call_deepseek(messages: list) -> str:
    """调用 DeepSeek API"""
    if not AI_KEY:
        return "（API Key 未配置）"

    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(
                f"{AI_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {AI_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": AI_MODEL,
                    "messages": messages,
                    "max_tokens": 150,
                    "temperature": 0.7
                }
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"DeepSeek API 调用失败: {e}", "ERR")
        return ""

def generate_reply(history: list, candidate_msg: str) -> str:
    """生成 AI 回复"""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({"role": "user", "content": candidate_msg})

    reply = call_deepseek(messages)
    return reply.strip()

# ============================================================
# 屏幕操作
# ============================================================

def capture_chat_area() -> dict:
    """捕获聊天区域"""
    # 1920x1080 布局：聊天区域在右侧
    return screen_ocr(region=(950, 100, 970, 880))

def capture_candidate_list() -> dict:
    """捕获候选人列表区域"""
    # 左侧候选人列表
    return screen_ocr(region=(0, 100, 400, 880))

def get_chat_text() -> str:
    """获取聊天区域文本"""
    result = capture_chat_area()
    return result.get("full_text", "")

def click_candidate_slot(slot_idx: int):
    """点击指定槽位的候选人"""
    # 第一个候选人的 Y 坐标
    base_y = 165
    y = base_y + slot_idx * ROW_PITCH
    x = 200  # 候选人列表中心 X

    log(f"点击槽位 {slot_idx}: ({x}, {y})", "ACT")
    move_and_click(x, y)

def click_chat_input():
    """点击聊天输入框"""
    # 输入框位置
    x, y = 1450, 950
    move_and_click(x, y)

def send_message(text: str):
    """发送消息（使用 pbcopy + Cmd+V）"""
    # 在 Linux 下用 xclip
    subprocess.run(["xclip", "-selection", "clipboard"],
                   input=text.encode(), check=True)
    time.sleep(0.2)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    pyautogui.press("enter")

def click_confirm_button():
    """点击确定按钮"""
    btn = find_confirm_button(region=(1300, 800, 350, 200))
    if btn:
        x, y = btn
        log(f"点击确定按钮: ({x}, {y})", "ACT")
        move_and_click(x, y)

# ============================================================
# 主流程
# ============================================================

def check_inappropriate(text: str) -> bool:
    """检查是否不合适"""
    keywords = ["不合适", "不考虑", "暂无意向", "已读不回", "没有兴趣"]
    return any(kw in text for kw in keywords)

def extract_candidate_info(text: str) -> dict:
    """从候选人列表区域提取信息"""
    # 简化版：提取名字
    lines = text.split("\n")
    name = lines[0].strip() if lines else "未知"
    return {"name": name}

def process_candidate(slot_idx: int) -> bool:
    """处理单个候选人"""
    global SLOT_CURSOR

    log(f"处理槽位 {slot_idx}", "STEP")

    # 点击候选人
    click_candidate_slot(slot_idx)
    time.sleep(1)

    # 获取聊天内容
    chat_result = capture_chat_area()
    chat_text = chat_result.get("full_text", "")

    if not chat_text:
        log("聊天区域为空，跳过", "SKIP")
        return False

    # 检查是否不合适
    if check_inappropriate(chat_text):
        log("检测到不合适关键词，跳过", "SKIP")
        return False

    # 提取候选人信息
    candidate_info = extract_candidate_info(chat_text)
    candidate_name = candidate_info.get("name", f"候选人{slot_idx}")
    candidate_key = f"{candidate_name}_{slot_idx}"

    # 检查是否已处理
    if is_processed(candidate_key):
        log(f"候选人 {candidate_name} 已处理，跳过", "SKIP")
        return False

    log(f"候选人: {candidate_name}", "CHAT")

    # 判断是否需要 AI 回复
    # 简化版：直接生成回复
    history = []
    ai_reply = generate_reply(history, "你好，我对你这个职位很感兴趣")

    if ai_reply:
        log(f"AI 回复: {ai_reply[:50]}...", "AI")
        click_chat_input()
        time.sleep(0.3)
        send_message(ai_reply)
        time.sleep(0.5)

        # 尝试点击确定
        click_confirm_button()

        # 记录
        save_conversation(candidate_name, 0, "ai_reply", ai_msg=ai_reply)
        mark_processed(candidate_key)
        return True

    return False

def run_automation():
    """运行自动化主循环"""
    global SLOT_CURSOR

    log("=" * 60, "INFO")
    log("BOSS直聘 AI对话自动化 v6.0 - Linux Docker版", "OK")
    log("=" * 60, "INFO")

    # 激活 Chrome
    log("激活 Chrome 浏览器...", "STEP")
    browser, tab = activate_chrome()
    time.sleep(3)

    # 导航到 BOSS 直聘
    log("导航到 BOSS 直聘...", "STEP")
    asyncio.run(tab.get("https://www.zhipin.com/web/chat/"))
    time.sleep(5)

    # 主循环
    processed_count = 0

    while processed_count < MAX_CANDIDATES:
        log(f"--- 开始第 {processed_count + 1} 个候选人 ---", "STEP")

        # 处理当前槽位
        if process_candidate(SLOT_CURSOR):
            processed_count += 1

        # 更新槽位光标
        SLOT_CURSOR = (SLOT_CURSOR + 1) % PAGE_SIZE

        # 如果回到第一个槽位，翻页
        if SLOT_CURSOR == 0:
            log("翻页...", "STEP")
            scroll_down()
            time.sleep(2)

        # 间隔
        time.sleep(NEW_MSG_WAIT)

    log(f"完成！共处理 {processed_count} 个候选人", "OK")

if __name__ == "__main__":
    try:
        run_automation()
    except Exception as e:
        log(f"运行错误: {e}", "ERR")
        import traceback
        log(traceback.format_exc(), "ERR")
        sys.exit(1)
