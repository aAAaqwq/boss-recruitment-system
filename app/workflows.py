"""三大核心工作流"""
import asyncio
import json
import random
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from app.config import settings
from app.database import Database
from app.automation import automation
from app.logging_config import logger
import httpx

from app.filter_criteria import (
    ALL_ELITE_SCHOOLS, FilterCriteria, match_school as _match_school,
)


# ========== 3.1 主动筛选沟通流程 ==========

# JS: 提取候选人卡片（多种选择器fallback）
_JS_EXTRACT_CARDS = """
(function() {
    var sels = ['.card-inner','.recommend-card','.geek-card','.card-wrap',
        '[class*="card-inner"]','[class*="recommend-card"]','[class*="geek-card"]',
        '.rec-card-inner','.candidate-card','.recommend-list .card',
        '[class*="rec-card"]','[class*="boss-card"]','[class*="talent-card"]'];
    var cards = [];
    for (var i = 0; i < sels.length; i++) {
        var f = document.querySelectorAll(sels[i]);
        if (f.length > 0) { cards = Array.from(f); break; }
    }
    if (cards.length === 0) {
        cards = Array.from(document.querySelectorAll('[class*="card"]')).filter(function(el) {
            var r = el.getBoundingClientRect();
            return r.width > 200 && r.height > 80 && r.width < 800 && r.height < 400;
        });
    }
    return cards.map(function(c) {
        var r = c.getBoundingClientRect();
        return { text: c.innerText||'', x: r.x, y: r.y, w: r.width, h: r.height,
                 cx: r.x+r.width/2, cy: r.y+r.height/2 };
    });
})()
"""

# JS: 查找打招呼按钮
_JS_FIND_GREET_BTN = """
(function() {
    var btns = document.querySelectorAll(
        'button,[class*="btn"],[class*="greet"],[class*="hello"],a,[class*="chat"]'
    );
    for (var i = 0; i < btns.length; i++) {
        var t = (btns[i].innerText||'').trim();
        if (t==='打招呼'||t==='立即沟通'||t==='沟通'||t==='开聊'||t==='继续沟通') {
            var r = btns[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                return {found:true,x:r.x+r.width/2,y:r.y+r.height/2,text:t};
            }
        }
    }
    return {found:false};
})()
"""

# 输入框 / 发送按钮选择器
_INPUT_SELS = [
    '.chat-input','[class*="chat-input"]','[class*="input"] textarea',
    '[class*="input"] [contenteditable]','textarea[class*="input"]',
    '.input-area textarea','[class*="message-input"]','[class*="editor"]',
    'textarea','[contenteditable="true"]',
]
_SEND_SELS = ['[class*="send"]','button[class*="send"]','[class*="btn-send"]','[class*="submit"]']

# 预设招呼语
_GREETINGS = [
    "你好，我在BOSS直聘上看到你的简历，觉得你的背景很匹配我们团队，想和你聊聊，方便吗？",
    "你好！你的经历很吸引人，我们正在招聘相关岗位，期待与你交流。",
    "你好，我是XX公司的招聘负责人，你的背景很符合我们的需求，有兴趣聊聊吗？",
]


def workflow_3_1_auto_contact(
    daily_cap: int = 80,
    school_whitelist: List[str] = None,
    min_degree: str = "本科",
    min_years: int = 3,
    dry_run: bool = True,
    criteria: Optional[FilterCriteria] = None,
) -> Dict:
    """3.1 主动筛选沟通流程 — 批量打招呼（同步入口）"""
    import concurrent.futures

    coro = _auto_contact_impl(
        daily_cap=daily_cap, school_whitelist=school_whitelist,
        min_degree=min_degree, min_years=min_years,
        dry_run=dry_run, criteria=criteria,
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result(timeout=600)
    return asyncio.run(coro)


async def _auto_contact_impl(
    daily_cap: int, school_whitelist: List[str], min_degree: str,
    min_years: int, dry_run: bool, criteria: Optional[FilterCriteria],
) -> Dict:
    """批量打招呼核心逻辑 (async)"""
    if criteria is None:
        criteria = FilterCriteria(
            school_whitelist=school_whitelist or None,
            min_degree=min_degree, min_years=min_years,
        )
    logger.info(f"[F5] 启动 | cap={daily_cap} dry={dry_run} filters={criteria.get_active_filters()}")

    # 检查浏览器（使用 _ensure_session 进行健康探测）
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接或会话失效，请先打开BOSS直聘"}

    # 检查今日已联系数量
    with Database() as db:
        db.init_tables()
        already = db.count_contacted_today()
        contacted_ids = set(db.get_contacted_today())
    remaining = max(0, daily_cap - already)
    if remaining <= 0:
        return {"status": "completed", "message": f"今日已达上限({already}/{daily_cap})",
                "contacted": 0, "skipped": 0, "failed": 0, "total_scanned": 0}
    logger.info(f"[F5] 今日已联系{already}人，剩余{remaining}")

    # 导航
    nav = await automation.navigate("https://www.zhipin.com/web/geek/recommend")
    if nav.get("status") == "error":
        nav = await automation.navigate("https://www.zhipin.com/web/chat/recommend")
    if nav.get("status") == "error":
        return {"status": "error", "message": f"导航失败: {nav.get('message')}"}
    await asyncio.sleep(3)

    # 主循环
    contacted = skipped = failed = 0
    seen = set()
    no_new = 0

    while contacted < remaining:
        # 提取卡片
        try:
            cards = await automation.execute_js(_JS_EXTRACT_CARDS)
        except Exception as e:
            logger.warning(f"[F5] JS提取失败: {e}")
            cards = None

        if not cards:
            no_new += 1
            if no_new >= 5:
                break
            await automation.scroll("down", 5)
            await asyncio.sleep(2)
            continue

        # 去重
        new_cards = [c for c in cards if (fp := c.get("text", "")[:50].strip()) and fp not in seen and not seen.add(fp)]
        if not new_cards:
            no_new += 1
            if no_new >= 5:
                break
            await automation.scroll("down", 3)
            await asyncio.sleep(2)
            continue
        no_new = 0
        logger.info(f"[F5] 发现{len(new_cards)}个新卡片")

        for card in new_cards:
            if contacted >= remaining:
                break
            txt = card.get("text", "")
            cand = {
                "name": _extract_name(txt), "years": _extract_years(txt),
                "degree": _extract_degree(txt), "school": _extract_school(txt),
            }
            boss_id = cand["name"] or f"unk_{id(card)}"

            if boss_id in contacted_ids or not _should_contact(cand, criteria):
                skipped += 1
                continue

            logger.info(f"[F5] 符合: {cand['name']} yrs={cand['years']} deg={cand['degree']} sch={cand['school']}")

            if dry_run:
                contacted += 1
                contacted_ids.add(boss_id)
                continue

            # 点击打招呼按钮
            if not await _click_greet(card):
                failed += 1
                continue
            await asyncio.sleep(1.5)

            # 发送招呼语
            if await _send_message(random.choice(_GREETINGS)):
                contacted += 1
                contacted_ids.add(boss_id)
                try:
                    with Database() as db2:
                        db2.init_tables()
                        db2.insert_candidate(boss_id=boss_id, candidate_name=cand["name"],
                                             school=cand["school"], degree=cand["degree"],
                                             years=cand["years"], status="contacted")
                        db2.update_candidate_status(boss_id, "contacted")
                        db2.insert_contact_record(boss_id=boss_id, action="contacted", success=True)
                except Exception as e:
                    logger.warning(f"[F5] DB写入失败: {e}")
                logger.info(f"[F5] 成功({contacted}/{remaining}): {cand['name']}")
            else:
                failed += 1
                await _dismiss_popup()

            await asyncio.sleep(random.uniform(2, 4))

        # 每5个截图
        total = contacted + skipped + failed
        if total > 0 and total % 5 == 0:
            try:
                await automation.screenshot(path=f"/tmp/f5_progress_{contacted}.png")
            except Exception:
                pass

        await automation.scroll("down", 3)
        await asyncio.sleep(random.uniform(1.5, 3))

    try:
        await automation.screenshot(path="/tmp/f5_final.png")
    except Exception:
        pass

    return {
        "status": "completed", "contacted": contacted, "skipped": skipped,
        "failed": failed, "total_scanned": contacted + skipped + failed,
        "dry_run": dry_run, "cap_used": f"{already + contacted}/{daily_cap}",
    }


def _extract_name(text: str) -> Optional[str]:
    """从卡片文本提取姓名"""
    if not text:
        return None
    first_line = text.split("\n")[0].strip()
    m = re.search(r'^([一-龥]{2,4})', first_line)
    return m.group(1) if m else (first_line[:10] or None)


async def _click_greet(card: Dict) -> bool:
    """点击打招呼按钮"""
    btn = await automation.execute_js(_JS_FIND_GREET_BTN)
    if btn and btn.get("found"):
        try:
            await automation.click(int(btn["x"]), int(btn["y"]))
            return True
        except Exception:
            pass
    # fallback: 卡片右侧
    cx, cy = card.get("cx", 0), card.get("cy", 0)
    if cx and cy:
        try:
            await automation.click(int(cx + card.get("w", 300) * 0.35), int(cy))
            return True
        except Exception:
            pass
    return False


async def _send_message(message: str) -> bool:
    """在弹窗输入框中输入招呼语并发送"""
    for sel in _INPUT_SELS:
        try:
            if await automation.find_element(sel, timeout=2):
                await automation.click_element(sel)
                await asyncio.sleep(0.5)
                break
        except Exception:
            continue
    else:
        return False

    try:
        await automation.type_text(message)
        await asyncio.sleep(random.uniform(0.5, 1.0))
    except Exception:
        return False

    for sel in _SEND_SELS:
        try:
            if await automation.find_element(sel, timeout=2):
                await automation.click_element(sel)
                await asyncio.sleep(1)
                return True
        except Exception:
            continue
    # fallback: Enter
    await automation.press_key("Return")
    await asyncio.sleep(1)
    return True


async def _dismiss_popup() -> None:
    """按Escape关闭残留弹窗"""
    try:
        await automation.press_key("Escape")
        await asyncio.sleep(0.5)
    except Exception:
        pass


# ========== 辅助函数（解析 + 筛选） ==========

def _parse_candidates(boxes: List) -> List[Dict]:
    """解析候选人信息（按Y坐标分行）"""
    rows = {}
    for box in boxes:
        key = box.center_y // 50
        rows.setdefault(key, []).append(box)
    candidates = []
    for row_boxes in rows.values():
        row_boxes.sort(key=lambda b: b.center_x)
        raw = " ".join(b.text for b in row_boxes)
        cand = {"name": row_boxes[0].text if row_boxes else None,
                "years": _extract_years(raw), "degree": _extract_degree(raw),
                "school": _extract_school(raw), "raw_text": raw}
        for box in row_boxes:
            if "打招呼" in box.text or "立即沟通" in box.text:
                cand["button_x"], cand["button_y"] = box.center_x, box.center_y
                break
        if cand.get("button_x"):
            candidates.append(cand)
    return candidates


def _extract_years(text: str) -> Optional[int]:
    m = re.search(r'(\d+)\s*年', text)
    return int(m.group(1)) if m else None


def _extract_degree(text: str) -> Optional[str]:
    for d in ("博士", "硕士", "本科", "大专"):
        if d in text:
            return d
    return None


def _extract_school(text: str) -> Optional[str]:
    """提取学校（中文XX大学/学院 + 英文校名/缩写）"""
    m = re.search(r'([一-龥]{2,8}(?:大学|学院|学校))', text)
    if m:
        return m.group(1)
    for pat in [r'((?:[A-Z][a-z]+\s){0,4}(?:University|College|Institute|School)(?:\s(?:of|at|in)\s[A-Z][a-z]+)?)',
                r'(Caltech|ETH\s?Zurich|EPFL|KAIST)', r'\b(Oxford|Cambridge)\b',
                r'\b(UPenn|UChicago|UMich)\b']:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    m = re.search(r'\b([A-Z]{2,7})\b', text)
    if m:
        return m.group(1).strip()
    m = re.search(r'\b(LSE|UCL|HKU|CUHK|HKUST|ANU|UNSW|JHU)\b', text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def _should_contact(candidate: Dict, criteria: "FilterCriteria") -> bool:
    """判断是否应该联系"""
    if criteria.min_years is not None:
        if candidate.get('years') is None or candidate['years'] < criteria.min_years:
            return False
    if criteria.min_degree:
        rank = {"博士": 4, "硕士": 3, "本科": 2, "大专": 1}
        deg = candidate.get('degree')
        if deg not in rank or rank[deg] < rank.get(criteria.min_degree, 0):
            return False
    if criteria.school_whitelist:
        if not _match_school(candidate.get('school', ''), criteria.school_whitelist):
            return False
    return True


# ========== 3.3 智能聊天Bot流程 ==========

async def workflow_3_3_chat_bot(
    boss_id: str, candidate_name: str,
    chat_region: Tuple[int, int, int, int] = (420, 140, 560, 350),
    auto_send: bool = False, dry_run: bool = True,
) -> Dict:
    """3.3 AI自动对话流程 (stub)"""
    return {"status": "not_implemented", "message": "AI对话功能将在 Phase 2 实现", "phase": 1}


def _generate_reply(flow: Dict, target_round: Dict, history: List[Dict]) -> Optional[str]:
    """使用LLM生成回复"""
    if not settings.DEEPSEEK_API_KEY:
        return target_round.get("ask")
    sys_prompt = flow.get("system_prompt", "你是一名招聘官，回复简洁、自然、像真人。")
    instruction = (f"当前对话目标: {target_round.get('id')} - {target_round.get('ask','')}\n"
                   f"请基于候选人最新消息生成一句简洁自然的回复，不要超过 80 字。\n"
                   f"严禁向候选人索要微信、电话、转账或任何敏感联系方式。")
    messages = [{"role": "system", "content": sys_prompt + "\n" + instruction}]
    for turn in history[-10:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    try:
        resp = httpx.post(f"{settings.DEEPSEEK_BASE_URL}/v1/chat/completions",
                          headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                                   "Content-Type": "application/json"},
                          json={"model": settings.DEEPSEEK_MODEL, "messages": messages,
                                "temperature": 0.5, "max_tokens": 200}, timeout=30.0)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return None


def _safety_check(text: str, flow: Dict) -> Tuple[Optional[str], str]:
    """安全检查"""
    guardrails = flow.get("guardrails", {})
    if guardrails.get("do_not_promise_offer", True):
        for kw in ["offer", "录用", "保证", "一定能"]:
            if (kw in text.lower() if kw.isascii() else kw in text):
                return None, f"promise:{kw}"
    for phrase in guardrails.get("banned_phrases", []):
        if phrase in text:
            return None, f"banned_phrase:{phrase}"
    cleaned = text.strip().strip("\"' \n")
    return (cleaned, "") if cleaned else (None, "empty_draft")
