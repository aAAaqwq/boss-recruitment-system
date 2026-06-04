#!/usr/bin/env python3
"""
BOSS直聘 · AI多轮对话 v5.2
========================
修复：
- 翻页后重新找锚点，确保点击到新的候选人
- 候选人信息从左侧列表区域读取，避免串人
- 不合适判断用左侧列表文字（学校/岗位关键词）
- 消息检测：OCR连续3次一致才判定无新消息
"""
import time, sys, os, json, subprocess, sqlite3, re
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv
load_dotenv()
from app.screen import activate_chrome, move_and_click
from app.vision import screen_ocr
import pyautogui
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.1
import httpx

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "boss_recruitment.db")
MAX_CANDIDATES = 50
MAX_CHAT_ROUNDS = 3
NEW_MSG_WAIT = 5

# 关键修复：固定8槽位模式（不管页面实际显示几个，都按8个槽位遍历）
# 槽位0-7固定点击，满8个强制翻页，cursor归零
# 这样确保不会漏掉任何物理位置的候选人
PAGE_SIZE = 8
ROW_PITCH = 79

# 槽位光标（0-7循环），与GLOBAL_IDX解耦
SLOT_CURSOR = 0

# 全局数据库连接（用于状态保存）
DB_CONN = None

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

def log(msg, level="INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    icon = {"INFO":"ℹ️","OK":"✅","WARN":"⚠️","ERR":"❌","CHAT":"💬",
            "DEBUG":"🔍","STEP":"📌","AI":"🤖","SKIP":"⏭️","ACT":"🖱️"}.get(level,"ℹ️")
    print(f"[{ts}] {icon} {msg}")

def init_db(conn=None):
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    should_close = False
    if conn is None:
        conn = sqlite3.connect(DB_PATH)
        should_close = True
    conn.execute('''CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_name TEXT,
        round_index INTEGER DEFAULT 0, action TEXT,
        ai_message TEXT, candidate_message TEXT, detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS chat_sessions (
        candidate_name TEXT PRIMARY KEY, round_index INTEGER DEFAULT 0,
        history_json TEXT DEFAULT '[]', last_screen_text TEXT DEFAULT '',
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS runtime_state (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS processed_candidates (
        candidate_key TEXT PRIMARY KEY,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    if should_close:
        return conn
    return conn


def save_runtime_state(conn, value, key="global_idx"):
    """保存运行时状态，支持多key"""
    conn.execute(
        "INSERT OR REPLACE INTO runtime_state (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (key, str(value))
    )
    conn.commit()


def load_runtime_state(conn):
    """加载所有运行时状态"""
    cur = conn.execute("SELECT key, value FROM runtime_state")
    state = {}
    for row in cur.fetchall():
        k, v = row
        if k in ["global_idx", "slot_cursor"]:
            state[k] = int(v) if str(v).isdigit() else 0
        else:
            state[k] = v
    # 默认值
    if "global_idx" not in state:
        state["global_idx"] = 0
    if "slot_cursor" not in state:
        state["slot_cursor"] = 0
    return state


def mark_candidate_processed(conn, candidate_name, fingerprint):
    keys = []
    if candidate_name:
        keys.append(candidate_name.strip())
    if fingerprint:
        keys.append(fingerprint.strip())
    for k in keys:
        if not k:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO processed_candidates (candidate_key, created_at) VALUES (?, CURRENT_TIMESTAMP)",
            (k,)
        )
    conn.commit()


def load_processed_candidates(conn):
    cur = conn.execute("SELECT candidate_key FROM processed_candidates")
    return {row[0] for row in cur.fetchall() if row and row[0]}


def normalize_text_for_compare(text):
    # OCR 常见抖动：空格、标点、大小写，不应被视作新消息
    t = (text or "").lower()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[^\w\u4e00-\u9fff]", "", t)
    return t


def should_skip_candidate(candidate_name, fingerprint, processed):
    if candidate_name and candidate_name in processed:
        return True
    if fingerprint and fingerprint in processed:
        return True
    return False

def get_session(conn, name):
    cur = conn.execute("SELECT round_index, history_json, last_screen_text FROM chat_sessions WHERE candidate_name=?", (name,))
    row = cur.fetchone()
    if row:
        return {"round_index": row[0], "history": json.loads(row[1]) if row[1] else [], "last_screen_text": row[2] or ""}
    return {"round_index": 0, "history": [], "last_screen_text": ""}

def save_session(conn, name, ri, history, last_text=""):
    conn.execute("INSERT OR REPLACE INTO chat_sessions (candidate_name, round_index, history_json, last_screen_text, updated_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                 (name, ri, json.dumps(history, ensure_ascii=False), last_text))
    conn.commit()

def chrome():
    activate_chrome(); time.sleep(0.8)

def ocr(region, min_conf=6.0, scale=3, pre=True):
    return screen_ocr(region=region, min_confidence=min_conf, scale=scale, preprocess=pre)

def call_ai(history, info_text=""):
    if not AI_KEY: return None
    msgs = [{"role": "system", "content": SYSTEM_PROMPT + (f"\n\n候选人背景: {info_text[:200]}" if info_text else "")}]
    for turn in (history[-6:] if len(history) > 6 else history):
        msgs.append({"role": turn["role"], "content": turn["content"][:300]})
    try:
        r = httpx.post(f"{AI_URL}/v1/chat/completions",
            headers={"Authorization": f"Bearer {AI_KEY}", "Content-Type": "application/json"},
            json={"model": AI_MODEL, "messages": msgs, "temperature": 0.7, "max_tokens": 150}, timeout=30)
        r.raise_for_status()
        reply = r.json()["choices"][0]["message"]["content"].strip()
        if any(w in reply for w in ["微信","wx","电话","手机号","转账","支付","加我"]): return None
        return reply
    except Exception as e:
        log(f"⚠️ AI失败: {e}", "WARN"); return None

# ============================================================
# 翻页 & 点击候选人（修复版）
# ============================================================

GLOBAL_IDX = 0

def click_goutong():
    log("点「沟通」", "STEP")
    r = ocr((0, 200, 160, 700), min_conf=8.0)
    for b in r.get('boxes', []):
        if "沟通" in (b.text or ""):
            move_and_click(b.center_x, b.center_y); time.sleep(1.5); return
    move_and_click(60, 398); time.sleep(1.5)

def find_anchor():
    """找锚点 - 扩大扫描区域，降低置信度"""
    # 扫描左侧列表顶部区域，找"全部职位"或"沟通"等锚点文字
    r = ocr((0, 100, 500, 600), min_conf=3.0)
    for b in r.get('boxes', []):
        t = (b.text or "").strip()
        if "全部职位" in t or "职位" in t or "沟通" in t:
            log(f"找到锚点: '{t}' @ ({b.center_x},{b.center_y})", "DEBUG")
            return b
    return None

def scroll_one_page():
    """翻一页 - 使用保守滚动量避免跨越多页"""
    a = find_anchor()
    sx = int((a.center_x + 150) if a else 500)
    sy = int((a.center_y + 380) if a else 650)
    pyautogui.moveTo(sx, sy)
    # 保守滚动：每次只滚动约3个槽位的高度，避免翻多页
    pyautogui.scroll(-40)
    time.sleep(1.5)

def get_list_text(region):
    """读候选人列表区域文字"""
    r = ocr(region, min_conf=5.0)
    return " ".join(b.text for b in r.get("boxes", []))

def get_chat_window_name() -> str:
    """获取当前聊天窗口顶部的候选人名字"""
    # 扫描聊天窗口顶部区域 (x=600-900, y=100-200)
    r = ocr((600, 100, 300, 100), min_conf=3.0)
    text = " ".join(b.text for b in r.get("boxes", []))
    # 提取名字（通常是最前面的1-4个汉字）
    names = re.findall(r'[\u4e00-\u9fa5]{1,4}', text)
    if names:
        # 过滤掉常见非人名词
        skip = ["官网", "中转站", "招聘", "规范", "客服", "面试", "未读", "沟", "通"]
        for n in names:
            if n not in skip:
                return n
    return ""

def wait_for_chat_switch(expected_name: str, max_wait: float = 5.0) -> bool:
    """
    等待聊天窗口切换到指定的候选人
    通过轮询聊天窗口顶部名字来确认
    """
    start = time.time()
    while time.time() - start < max_wait:
        current_name = get_chat_window_name()
        if current_name and (current_name in expected_name or expected_name in current_name):
            log(f"✅ 聊天窗口已切换到: {current_name}", "DEBUG")
            return True
        time.sleep(0.5)
    log(f"⚠️ 聊天窗口切换超时，期望: {expected_name}", "WARN")
    return False

def scan_slot_info(slot_in_page: int, anchor_y: int) -> dict:
    """
    扫描左侧列表中指定槽位的候选人信息。
    精确扫描单个槽位，避免相邻槽位干扰。
    """
    # 每个槽位高度约79px，精确扫描单个槽位
    slot_y = anchor_y + 80 + slot_in_page * ROW_PITCH
    # 缩小扫描区域：只扫描当前槽位的高度 (y-20 到 y+60)
    slot_region = (90, int(slot_y) - 20, 450, 80)
    
    r = ocr(slot_region, min_conf=3.0, scale=2)
    text = " ".join(b.text for b in r.get("boxes", []))
    
    if not text.strip():
        r = ocr(slot_region, min_conf=2.0, scale=2)
        text = " ".join(b.text for b in r.get("boxes", []))
    
    info = {"name": "", "school": "", "degree": "", "raw": text}
    
    log(f"槽位{slot_in_page+1} OCR原始: {text[:200]}", "DEBUG")
    
    # 排除非候选人（关键词匹配）
    filter_keywords = ["全部职位", "新招呼", "筛选", "排序", "全部", "新"]
    if any(k in text for k in filter_keywords) and len(text) < 50:
        log(f"槽位{slot_in_page+1} 不是候选人，跳过", "SKIP")
        info["name"] = "__FILTER__"
        return info
    
    # 提取学历（优先）
    for kw in ["博士", "硕士", "本科", "大专", "专科"]:
        if kw in text:
            info["degree"] = kw
            break
    
    # 提取学校
    m = re.search(r'([\u4e00-\u9fa5]{2,10}(?:大学|学院|学校|职院|职业技术学院|技工学校))', text)
    if m:
        info["school"] = m.group(1)
    
    # 提取名字（排除常见非人名词，优先选择更像人名的）
    words = re.findall(r'[\u4e00-\u9fa5]{1,4}', text)
    skip_words = ["全部", "职位", "沟通", "新招呼", "技术", "工程师", "实习生", "未读", "已读", "新", "招呼", "你好", "你好呀", "您好", "您女", "你女", "通", "您", "汉作头", "软件", "开发", "经理", "主管", "总监", "技术实习", "理", "人", "由", "人力", "送"]
    
    # 优先选择不在skip_words中的词
    for w in words:
        if w not in skip_words and len(w) >= 1:
            info["name"] = w
            break
    
    # 如果名字还是空的，尝试其他方式
    if not info["name"]:
        # 尝试从文本中提取第一个不是过滤词的中文词
        for w in words:
            if w not in skip_words:
                info["name"] = w
                break
    
    # 判定规则：
    # 1. 如果OCR结果极短(<2字)且全是过滤词 → 可能是UI元素，标记过滤
    # 2. 如果OCR结果为空 → 可能是OCR失败，不要过滤，让主流程尝试点击
    # 3. 如果名字在过滤列表 → 标记过滤
    if not text.strip():
        # OCR完全失败，不过滤，让主流程尝试点击
        log(f"槽位{slot_in_page+1} OCR为空，尝试点击", "WARN")
        info["name"] = "_OCR_FAIL_"  # 特殊标记，主流程会尝试点击
        return info
    
    if info["name"] in ["全部", "未读", "新", "招呼", "你好", "你好呀", "您好", "您女", "你女", "您", "人力", "送", "通"]:
        log(f"槽位{slot_in_page+1} 名字识别异常 '{info['name']}'，标记为过滤", "SKIP")
        info["name"] = "__FILTER__"
        return info
    
    # 如果名字为空，标记为过滤
    if not info["name"]:
        log(f"槽位{slot_in_page+1} 名字为空，标记为过滤", "SKIP")
        info["name"] = "__FILTER__"
        return info
    
    # 检查名字是否在skip_words中（二次检查）
    if info["name"] in skip_words:
        log(f"槽位{slot_in_page+1} 名字'{info['name']}'在过滤词列表中，标记为过滤", "SKIP")
        info["name"] = "__FILTER__"
        return info
    
    return info


def click_next_candidate() -> tuple:
    """
    点击下一个候选人 - V1.1兼容版（槽位光标模式）
    
    核心改进：
    - 槽位光标 SLOT_CURSOR 独立循环 0-7
    - 满8槽位强制翻页，cursor归零
    - GLOBAL_IDX 只统计实际点击的候选人（不用于槽位计算）
    - 这样即使OCR失败/跳过，也不会漏掉物理位置的候选人
    """
    global GLOBAL_IDX, SLOT_CURSOR
    chrome(); time.sleep(0.3)

    # 找锚点
    anchor = find_anchor()
    if not anchor:
        log("⚠️ 无锚点，使用固定坐标", "WARN")
        base_x, base_y = 520, 320
        
        # 槽位光标驱动翻页
        if SLOT_CURSOR == 0 and GLOBAL_IDX > 0:
            log(f"↘️ 翻页 (无锚点模式，槽位光标复位)", "STEP")
            scroll_one_page()
            time.sleep(0.8)
        
        # 使用槽位光标计算位置
        x, y = base_x, base_y + SLOT_CURSOR * ROW_PITCH
        
        move_and_click(x, y)
        GLOBAL_IDX += 1
        SLOT_CURSOR = (SLOT_CURSOR + 1) % PAGE_SIZE
        save_runtime_state(DB_CONN, GLOBAL_IDX)
        save_runtime_state(DB_CONN, SLOT_CURSOR, key="slot_cursor")
        time.sleep(2)
        unique_tag = f"cand_{GLOBAL_IDX}_{int(time.time()*1000)%10000}"
        return (unique_tag, y, {})  # 返回空info

    ax, ay = anchor.center_x, anchor.center_y
    log(f"锚点({ax},{ay}) idx={GLOBAL_IDX} slot={SLOT_CURSOR}", "DEBUG")

    # 槽位光标驱动翻页：满8槽位翻页，cursor归零
    if SLOT_CURSOR == 0 and GLOBAL_IDX > 0:
        log(f"↘️ 已完成当前页{PAGE_SIZE}个槽位，滚动到下一页", "STEP")
        scroll_one_page()
        time.sleep(0.8)
        anchor = find_anchor()
        if anchor:
            ax, ay = anchor.center_x, anchor.center_y
            log(f"新锚点({ax},{ay})", "DEBUG")

    # 计算当前槽位坐标（基于SLOT_CURSOR，不是GLOBAL_IDX）
    cx = int(ax + 35)
    cy = int(ay + 80 + SLOT_CURSOR * ROW_PITCH)
    
    # 扫描槽位信息
    slot_info = scan_slot_info(SLOT_CURSOR, ay)
    log(f"槽位{SLOT_CURSOR+1}信息: 名字={slot_info['name'] or '?'} 学校={slot_info['school'] or '?'} 学历={slot_info['degree'] or '?'}", "DEBUG")
    
    # 槽位光标永远+1（确保遍历所有物理位置）
    current_slot = SLOT_CURSOR
    SLOT_CURSOR = (SLOT_CURSOR + 1) % PAGE_SIZE
    save_runtime_state(DB_CONN, SLOT_CURSOR, key="slot_cursor")
    
    # 如果是非候选人项（如"全部职位"），跳过点击
    if slot_info.get("name") == "__FILTER__":
        log(f"⛔ 槽位{current_slot+1} 不是候选人，跳过点击", "SKIP")
        return (None, cy, slot_info)
    
    # 如果明确是大专/专科，点击"不合适"后跳过
    if slot_info["degree"] in ["大专", "专科"]:
        log(f"⛔ 槽位{current_slot+1} 学历{slot_info['degree']}，点击不合适", "SKIP")
        # 先点击候选人打开聊天窗口
        move_and_click(cx, cy)
        time.sleep(2)
        # 点击不合适
        click_not_suitable()
        return (None, cy, slot_info)
    
    # OCR失败时，也尝试点击（可能是候选人但OCR没识别好）
    if slot_info.get("name") == "_OCR_FAIL_":
        log(f"⚠️ 槽位{current_slot+1} OCR失败，尝试点击", "WARN")
    
    log(f"槽位点击：槽位{current_slot+1}/{PAGE_SIZE} (全局idx={GLOBAL_IDX}) → ({cx},{cy})", "ACT")

    # 点击候选人
    move_and_click(cx, cy)
    time.sleep(2.5)

    # 生成唯一tag
    if slot_info["name"]:
        candidate_name = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', slot_info["name"])[:20]
        unique_tag = f"{candidate_name}_{GLOBAL_IDX}_{int(time.time()*1000)%10000}"
    else:
        unique_tag = f"cand_{GLOBAL_IDX}_{int(time.time()*1000)%10000}"
    
    log(f"候选人: {unique_tag}", "DEBUG")

    # 只有真正点击候选人才增加GLOBAL_IDX
    GLOBAL_IDX += 1
    save_runtime_state(DB_CONN, GLOBAL_IDX)
    return (unique_tag, cy, slot_info)


# ============================================================
# 候选人扫描（点击后在聊天窗口扫描）
# ============================================================

def get_degree_from_chrome() -> str:
    """通过 Chrome DevTools Protocol 获取当前候选人学历"""
    import requests
    
    try:
        # 获取已打开的 Chrome 调试端口
        resp = requests.get("http://127.0.0.1:9222/json/list", timeout=2)
        tabs = resp.json()
        
        for tab in tabs:
            if "boss" in tab.get("url", ""):
                ws_url = tab.get("webSocketDebuggerUrl")
                if ws_url:
                    # 使用 CDP 执行 JavaScript
                    import websocket
                    ws = websocket.create_connection(ws_url, timeout=5)
                    
                    # 获取页面内容
                    ws.send(json.dumps({
                        "id": 1,
                        "method": "Runtime.evaluate",
                        "params": {
                            "expression": """
                                (() => {
                                    // 尝试从页面中找到学历信息
                                    const elements = document.querySelectorAll('*');
                                    for (const el of elements) {
                                        const text = el.textContent || '';
                                        if (text.includes('本科') || text.includes('硕士') || 
                                            text.includes('大专') || text.includes('博士')) {
                                            const match = text.match(/(博士|硕士|本科|大专|专科)/);
                                            if (match) return match[1];
                                        }
                                    }
                                    return '';
                                })()
                            """,
                            "returnByValue": True
                        }
                    }))
                    
                    result = json.loads(ws.recv())
                    ws.close()
                    
                    degree = result.get("result", {}).get("value", "")
                    if degree:
                        log(f"CDP 获取到学历: {degree}", "INFO")
                        return degree
    except Exception as e:
        log(f"CDP 获取失败: {e}", "WARN")
    
    return ""

def scan_degree_from_chat_header() -> str:
    """点击候选人后，在右侧聊天窗口顶部扫描学历信息"""
    # 先尝试通过 Chrome DevTools Protocol 获取
    degree = get_degree_from_chrome()
    if degree:
        return degree
    
    # 回退到 OCR
    regions = [
        (800, 100, 600, 120),
        (700, 120, 500, 100),
        (900, 120, 500, 100),
    ]
    
    for region in regions:
        r = ocr(region, min_conf=5.0, scale=2)
        text = " ".join(b.text for b in r.get("boxes", []))
        log(f"聊天顶部OCR({region[0]},{region[1]}): {text[:100]}", "DEBUG")
        
        for kw in ["博士", "硕士", "本科", "大专", "专科"]:
            if kw in text:
                log(f"识别到学历: {kw}", "INFO")
                return kw
    
    return ""

# ============================================================
# 候选人扫描 + 不合适（用列表区域文字）
# ============================================================

def scan_candidate_label(click_y: int = 0) -> dict:
    """
    扫描当前选中的候选人的信息。
    从左侧候选人列表区域读取学校和学历。
    """
    # 左侧候选人列表区域：x=90-420, y根据槽位动态计算
    # 直接扫描整个列表区域，不依赖click_y
    region = (90, 200, 330, 600)  # 扫描整个左侧列表
    r = ocr(region, min_conf=10.0)
    text = " ".join(b.text for b in r.get("boxes", []))
    
    info = {"school": "", "degree": "", "raw": text[:200]}
    
    m = re.search(r'([\u4e00-\u9fa5]{2,8}(?:大学|学院))', text)
    if m: info["school"] = m.group(1)
    
    for kw in ["本科","硕士","博士","大专"]:
        if kw in text: info["degree"] = kw; break
    
    return info

def is_bad(info) -> tuple:
    """判断是否不合适 - 放宽条件，避免误杀"""
    # 只有明确的大专才过滤
    if info["degree"] == "大专": 
        return True, "大专"
    # 空白不直接过滤，可能是OCR没识别到，继续聊
    # 返回False让所有人都进入聊天流程
    return False, None


# ============================================================
# 聊天
# ============================================================

def find_not_suitable_btn():
    """找不合适按钮 - 扩大搜索区域，支持动态定位"""
    # 扩大搜索区域：底部操作栏整行 (x:600-1200, y:790-850)
    r = ocr((600, 790, 600, 60), min_conf=10.0, scale=3)
    for b in r.get('boxes', []):
        t = (b.text or "").strip()
        if "不合适" in t or "合适" in t:
            log(f"OCR找到'不合适' @ ({b.center_x},{b.center_y}) 文字:'{t}'", "DEBUG")
            return (b.center_x, b.center_y)
    
    # 如果没找到，尝试找"约面试"按钮，推算不合适位置
    # 约面试通常在 x≈950, 不合适在 x≈1100 左右
    for b in r.get('boxes', []):
        t = (b.text or "").strip()
        if "约面试" in t or "面试" in t:
            # 不合适在约面试右边约150px
            estimated_x = b.center_x + 150
            log(f"通过'约面试'推算不合适 @ ({estimated_x},{b.center_y})", "DEBUG")
            return (estimated_x, b.center_y)
    
    # 最后的fallback - 根据实际屏幕坐标
    fallback_x, fallback_y = 1571, 833
    log(f"⚠️ 未找到不合适按钮，使用默认坐标 ({fallback_x}, {fallback_y})", "WARN")
    return (fallback_x, fallback_y)

def click_not_suitable():
    """点击不合适按钮，然后确认（支持三击+确认弹窗处理）"""
    # 先尝试用OCR找"不合适"按钮
    btn_x, btn_y = find_not_suitable_btn()
    
    # 三击：BOSS直聘"不合适"按钮需要多次点击才能生效
    log(f"三击不合适按钮 @ ({btn_x},{btn_y})", "ACT")
    for i in range(3):
        move_and_click(btn_x, btn_y)
        time.sleep(0.2)
    time.sleep(1.5)
    
    # 可能有确认弹窗，扩大搜索区域找"确定/确认/是的"按钮
    # 弹窗通常在屏幕中央偏右
    r = ocr((1000, 600, 400, 300), min_conf=10.0, scale=3)
    confirm_keywords = ["确定", "确认", "是的", "是", "确定不合适"]
    for b in r.get("boxes", []):
        t = (b.text or "").strip()
        if any(k in t for k in confirm_keywords):
            log(f"确认弹窗 '{t}' @ ({b.center_x},{b.center_y})", "ACT")
            move_and_click(b.center_x, b.center_y)
            time.sleep(0.5)
            break
    time.sleep(1.0)

def get_chat_text():
    """读聊天区域（仅聊天气泡区域）"""
    r = ocr((800, 150, 700, 600), min_conf=15.0)
    skip = ["求简历","换电话","换微信","约面试","不合适","发送短信",
            "表情","常用语","图片","加号","送达","已读","牛人","提醒","试试","方式"]
    boxes = sorted(r.get("boxes", []), key=lambda b: b.center_y, reverse=True)
    msgs, seen = [], set()
    for b in boxes[:25]:
        t = b.text.strip()
        if not t or t in seen or len(t) < 3: continue
        if any(k in t for k in skip): continue
        seen.add(t); msgs.append(t)
    return "\n".join(msgs[:4])

def has_new_msg(session):
    """检测新消息：对 OCR 抖动做归一化后再比较"""
    cur = get_chat_text()
    if not cur.strip():
        return False, ""

    last = (session.get("last_screen_text", "") or "").strip()
    if not last:
        return True, cur

    cur_norm = normalize_text_for_compare(cur)
    last_norm = normalize_text_for_compare(last)

    if not last_norm:
        return True, cur

    if cur_norm != last_norm:
        return True, cur

    return False, cur

def send_msg(text):
    pyautogui.moveTo(630, 890, duration=0.15)
    pyautogui.click(); time.sleep(0.5)
    pyautogui.hotkey('command', 'a'); time.sleep(0.1)
    pyautogui.press('delete'); time.sleep(0.2)
    subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True); time.sleep(0.2)
    subprocess.run(['osascript', '-e', 'tell application "System Events" to keystroke "v" using command down'])
    time.sleep(0.8)
    pyautogui.hotkey('command', 'enter')
    log(f"发送: {text[:60]}...", "CHAT")
    time.sleep(2.0)


# ============================================================
# 主流程
# ============================================================

def main():
    log("="*60)
    log("BOSS直聘 · AI对话 v5.3")
    log(f"模型: {AI_MODEL}")
    log("="*60)

    conn = init_db()
    global DB_CONN
    DB_CONN = conn
    sw, sh = pyautogui.size()
    log(f"屏幕: {sw}x{sh}")
    if not AI_KEY: log("⚠️ 无API Key", "ERR"); return

    # 恢复运行状态（支持断点续跑）
    global GLOBAL_IDX, SLOT_CURSOR
    state = load_runtime_state(conn)
    GLOBAL_IDX = state.get("global_idx", 0)
    SLOT_CURSOR = state.get("slot_cursor", 0)
    log(f"当前状态: GLOBAL_IDX={GLOBAL_IDX}, SLOT_CURSOR={SLOT_CURSOR}", "INFO")

    chrome()
    click_goutong()
    time.sleep(1)

    stats = {"chat":0, "bad":0, "noreply":0, "fail":0, "skip":0}

    for i in range(MAX_CANDIDATES):
        log(f"\n{'='*60}")
        log(f"#{i+1}")
        log(f"{'='*60}")

        # 1. 翻页+点击候选人（返回槽位信息，避免串人）
        tag, cy, slot_info = click_next_candidate()
        
        # 如果tag为None，说明已识别为大专并跳过
        if tag is None:
            log(f"  ⛔ 跳过: 非候选人或学历大专", "SKIP")
            stats["bad"] += 1
            continue
        
        time.sleep(1)

        # 2. 验证聊天窗口是否切换到正确的候选人
        expected_name = slot_info.get("name", "")
        if expected_name and expected_name not in ["_OCR_FAIL_", "__FILTER__", ""]:
            switched = wait_for_chat_switch(expected_name, max_wait=4.0)
            if not switched:
                log(f"  ⚠️ 聊天窗口可能未切换，尝试重新点击", "WARN")
                # 重新点击一次
                chrome()
                move_and_click(300, cy)  # 重新点击左侧列表同一位置
                time.sleep(2)
                switched = wait_for_chat_switch(expected_name, max_wait=3.0)
                if not switched:
                    log(f"  ❌ 无法切换到候选人 {expected_name}，跳过", "ERR")
                    stats["fail"] += 1
                    continue

        # 3. 点击后扫描聊天窗口顶部获取学历（补充识别）
        chat_degree = scan_degree_from_chat_header()
        if chat_degree and not slot_info.get("degree"):
            slot_info["degree"] = chat_degree
            log(f"  聊天窗口识别到学历: {chat_degree}", "INFO")
        
        # 如果聊天窗口识别到大专，也过滤掉
        if slot_info.get("degree") in ["大专", "专科"]:
            log(f"  ⛔ 聊天窗口识别到大专，标记不合适", "SKIP")
            chrome()
            click_not_suitable()
            stats["bad"] += 1
            continue

        # 4. 使用点击前扫描的槽位信息（避免串人）
        info = slot_info if slot_info else scan_candidate_label(cy)
        log(f"  学校:{info['school'] or '?'} 学历:{info['degree'] or '?'}", "DEBUG")

        # 5. 不合适判断
        bad, reason = is_bad(info)
        if bad:
            log(f"  ⛔ 不合适: {reason}", "SKIP")
            chrome()
            click_not_suitable()
            stats["bad"] += 1
            continue

        # 4. 准备聊天背景信息
        bg = f"学校:{info['school']} 学历:{info['degree']}"

        # 5. 多轮对话
        session = get_session(conn, tag)
        log(f"  已有{session['round_index']}轮", "DEBUG")
        
        # 如果是新候选人（round_index=0），确保清空 last_screen_text
        # 避免读到上一个候选人的消息
        if session["round_index"] == 0:
            session["last_screen_text"] = ""
            log(f"  新候选人，清空历史状态", "DEBUG")

        for ri in range(session["round_index"], MAX_CHAT_ROUNDS):
            new_txt = ""
            if ri > 0:
                time.sleep(NEW_MSG_WAIT)
                fresh, new_txt = has_new_msg(session)
                if not fresh:
                    log(f"  牛人未回复", "SKIP")
                    stats["noreply"] += 1
                    break
                session["history"].append({"role": "user", "content": new_txt})

            if ri == 0 and not session["history"]:
                reply = call_ai([], bg)
                if not reply: reply = "您好，我们正在招聘AI全栈开发工程师，方便聊聊您的技术背景吗？"
            else:
                reply = call_ai(session["history"], bg)
                if not reply: stats["fail"] += 1; break

            send_msg(reply)
            session["history"].append({"role": "assistant", "content": reply})
            conn.execute("INSERT INTO conversations (candidate_name,round_index,action,ai_message,candidate_message) VALUES (?,?,?,?,?)",
                         (tag, ri, "chat", reply, (new_txt or "")[:200]))
            conn.commit()
            save_session(conn, tag, ri+1, session["history"], new_txt)
            stats["chat"] += 1
            log(f"  ✅ 第{ri+1}轮", "OK")

    log(f"\n{'='*60}")
    log(f"🎉 对话:{stats['chat']} 不合适(大专):{stats['bad']} 未回复:{stats['noreply']} 失败:{stats['fail']}")
    log(f"{'='*60}")
    conn.close()

if __name__ == "__main__":
    try: main()
    except KeyboardInterrupt: log("⚠️ 中断", "WARN")
    except Exception as e: log(f"❌ 错误: {e}", "ERR"); import traceback; traceback.print_exc()
