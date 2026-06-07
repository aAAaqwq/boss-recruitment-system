"""三大核心工作流"""
import asyncio
import json
import random
import re
import time as _time
from typing import List, Dict, Optional, Tuple

from app.config import settings
from app.automation import automation
from app.database import Database
from app.logging_config import logger
import httpx

from app.filter_criteria import (
    ALL_ELITE_SCHOOLS, FilterCriteria, match_school as _match_school,
)


# ========== 3.1 主动筛选沟通流程 ==========

# JS: 在 iframe 内提取候选人卡片 + 打招呼按钮坐标
# /web/chat/recommend 页面结构: 主页面 > .frame-box > iframe(src=/web/frame/recommend/)
# 候选人卡片和打招呼按钮都在 iframe 内部
_JS_EXTRACT_CARDS = """
(function() {
    var greets = ['打招呼','立即沟通','开聊','继续沟通'];
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    var doc = iframe && iframe.contentDocument ? iframe.contentDocument : document;
    // iframe 元素偏移: getBoundingClientRect 在 iframe.contentDocument 元素上返回
    // iframe 视口坐标, 需要加上 iframe 元素在主视口中的偏移量才是 CDP viewport 坐标
    var ox = 0, oy = 0;
    if (iframe) {
        var ir = iframe.getBoundingClientRect();
        ox = ir.x; oy = ir.y;
    }
    var cards = Array.from(doc.querySelectorAll('.card-inner'));
    if (cards.length === 0) {
        cards = Array.from(doc.querySelectorAll('.candidate-card-wrap'));
    }
    if (cards.length === 0) {
        cards = Array.from(doc.querySelectorAll('[class*="card-inner"]'));
    }
    return JSON.stringify(cards.map(function(c) {
        var r = c.getBoundingClientRect();
        var container = c;
        for (var p = c.parentElement; p; p = p.parentElement) {
            if (p.classList && (p.classList.contains('candidate-card-wrap') || p.classList.contains('card-item'))) {
                container = p; break;
            }
        }
        var gx = null, gy = null, gt = null;
        var btns = container.querySelectorAll('button.btn-greet, button[class*="greet"]');
        if (btns.length === 0) btns = container.querySelectorAll('button[class*="btn"], a[class*="greet"]');
        if (btns.length === 0) btns = container.querySelectorAll('button, a, [role="button"]');
        for (var j = 0; j < btns.length; j++) {
            var t = (btns[j].innerText||'').trim();
            if (greets.indexOf(t) >= 0 && btns[j].offsetParent !== null) {
                var br = btns[j].getBoundingClientRect();
                gx = br.x + br.width / 2 + ox;
                gy = br.y + br.height / 2 + oy;
                gt = t;
                break;
            }
        }
        return {
            text: c.innerText||'', x: r.x + ox, y: r.y + oy, w: r.width, h: r.height,
            cx: r.x+r.width/2+ox, cy: r.y+r.height/2+oy,
            greet_x: gx, greet_y: gy, greet_text: gt
        };
    }));
})()
"""

# JS: 在 iframe 内滚动候选列表
_JS_SCROLL_IFRAME = """
(function() {
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    var doc = iframe && iframe.contentDocument ? iframe.contentDocument : document;
    var scrollable = doc.querySelector('.list-wrap') || doc.querySelector('.candidate-body') || doc.querySelector('.recommend-list-wrap') || doc.documentElement;
    scrollable.scrollTop += 400;
    return scrollable.scrollTop;
})()
"""


def workflow_3_1_auto_contact(
    daily_cap: int = 80,
    school_whitelist: List[str] = None,
    min_degree: str = "本科",
    min_years: int = 3,
    dry_run: bool = True,
    criteria: Optional[FilterCriteria] = None,
) -> Dict:
    """3.1 主动筛选沟通流程 - 批量打招呼(同步入口)"""
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

    # 检查浏览器(使用 _ensure_session 进行健康探测)
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接或会话失效, 请先打开BOSS直聘"}

    # 检查今日已联系数量
    with Database() as db:
        db.init_tables()
        already = db.count_contacted_today()
        contacted_ids = set(db.get_contacted_today())
    remaining = max(0, daily_cap - already)
    if remaining <= 0:
        return {"status": "completed", "message": f"今日已达上限({already}/{daily_cap})",
                "contacted": 0, "skipped": 0, "failed": 0, "total_scanned": 0}
    logger.info(f"[F5] 今日已联系{already}人, 剩余{remaining}")

    # 导航到招聘者推荐牛人页面
    # /web/chat/recommend 包含候选人推荐列表 + 聊天窗口
    # 点击打招呼后聊天输入框就在当前页面, 不需要跨 frame
    nav = await automation.navigate("https://www.zhipin.com/web/chat/recommend")
    if nav.get("status") == "error":
        return {"status": "error", "message": f"导航失败: {nav.get('message')}"}
    # 等待页面动态加载 iframe(/web/frame/recommend/), 3秒不够
    await asyncio.sleep(8)

    # 主循环
    contacted = skipped = failed = 0
    seen = set()
    no_new = 0
    js_fail = 0  # JS 提取失败计数 (与 no_new 分离)
    start_time = _time.monotonic()
    TIMEOUT_SECONDS = 600  # 10 分钟全局超时
    last_screenshot_at = 0  # 上次截图时的 total 数

    while contacted < remaining:
        # 全局超时保护
        if _time.monotonic() - start_time > TIMEOUT_SECONDS:
            logger.warning(f"[F5] 超时退出 ({TIMEOUT_SECONDS}s)")
            break

        # 提取卡片
        try:
            raw = await automation.execute_js(_JS_EXTRACT_CARDS)
            # execute_js 返回的可能是 JSON 字符串(绕过 CDP 反序列化问题)
            if isinstance(raw, str):
                cards = json.loads(raw)
            elif isinstance(raw, list):
                cards = raw
            else:
                cards = None
        except Exception as e:
            logger.warning(f"[F5] JS提取失败: {e}")
            cards = None

        if not cards:
            js_fail += 1
            if js_fail >= 3:
                logger.warning("[F5] JS连续3次失败, 尝试重新检测iframe...")
                # 尝试检测iframe是否还在
                iframe_ok = await automation.execute_js(
                    "!!(document.querySelector('.frame-box iframe') || document.querySelector('iframe'))"
                )
                if not iframe_ok:
                    logger.error("[F5] iframe 不存在, 退出")
                    break
            if js_fail >= 10:
                logger.error("[F5] JS连续10次失败, 退出")
                break
            await automation.execute_js(_JS_SCROLL_IFRAME)
            await asyncio.sleep(2)
            continue

        # 卡片提取成功, 重置 JS 失败计数
        js_fail = 0

        # 去重
        new_cards = []
        for c in cards:
            fp = c.get("text", "")[:50].strip()
            if fp and fp not in seen:
                seen.add(fp)
                new_cards.append(c)
        if not new_cards:
            no_new += 1
            if no_new >= 5:
                break
            await automation.execute_js(_JS_SCROLL_IFRAME)
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
            # boss_id: 优先姓名, 否则用卡片文本指纹hash (跨次稳定)
            fingerprint = card.get("text", "")[:50].strip()
            boss_id = cand["name"] or f"unk_{hash(fingerprint) & 0xFFFFFF}"

            if boss_id in contacted_ids or not _should_contact(cand, criteria):
                skipped += 1
                continue

            # 卡片上没有可见的打招呼按钮 → 跳过
            if card.get("greet_x") is None or card.get("greet_y") is None:
                logger.debug(f"[F5] 跳过无按钮卡片: {cand['name']}")
                skipped += 1
                continue

            logger.info(f"[F5] 符合: {boss_id[:1]}** yrs={cand['years']} deg={cand['degree']} sch={cand['school']}")

            if dry_run:
                contacted += 1
                contacted_ids.add(boss_id)
                continue

            # CDP 点击打招呼按钮(坐标在 iframe 内, CDP viewport 点击可穿透 iframe)
            gx, gy = card["greet_x"], card["greet_y"]
            logger.info(f"[F5] 点击打招呼: ({gx:.0f},{gy:.0f}) text={card.get('greet_text')}")
            if await automation.cdp_click_viewport(float(gx), float(gy)):
                contacted += 1
                contacted_ids.add(boss_id)
                # 写 DB 记录, 保证每日上限计数准确
                try:
                    with Database() as db:
                        db.init_tables()
                        db.insert_contact_record(
                            boss_id=boss_id, action="contacted", success=True,
                        )
                except Exception as db_err:
                    logger.warning(f"[F5] DB写入失败: {db_err}")
                logger.info(f"[F5] 成功({contacted}/{remaining}): {boss_id[:1]}**")
            else:
                failed += 1
                logger.warning(f"[F5] 点击失败: {boss_id[:1]}**")

            await asyncio.sleep(random.uniform(2, 4))

        # 每5个新增截图
        total = contacted + skipped + failed
        if total - last_screenshot_at >= 5:
            try:
                await automation.screenshot(path=f"/tmp/f5_progress_{contacted}.png")
                last_screenshot_at = total
            except Exception:
                pass

        # 滚动 iframe 内的候选列表
        await automation.execute_js(_JS_SCROLL_IFRAME)
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
    """从卡片文本提取姓名 — 跳过薪资等非姓名行"""
    if not text:
        return None
    salary_kw = ('面议', '薪资', 'K', 'k', '元/', '万', '·', '/', '-')
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        # 跳过薪资行 (含数字+单位, 或薪资关键词)
        if any(kw in line for kw in salary_kw):
            continue
        if re.search(r'\d+[-~]\d+', line):  # "15-20K", "3-5年"
            continue
        m = re.search(r'([一-龥]{2,4})', line)
        if m:
            return m.group(1)
    # fallback: 文本中任意2-4个连续中文字符
    m = re.search(r'([一-龥]{2,4})', text)
    return m.group(1) if m else None


# ========== 辅助函数(解析 + 筛选) ==========


def _extract_years(text: str) -> Optional[int]:
    m = re.search(r'(\d+)\s*年', text)
    return int(m.group(1)) if m else None


def _extract_degree(text: str) -> Optional[str]:
    for d in ("博士", "硕士", "本科", "大专"):
        if d in text:
            return d
    return None


def _extract_school(text: str) -> Optional[str]:
    """提取学校(中文XX大学/学院 + 英文校名/缩写)"""
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
    sys_prompt = flow.get("system_prompt", "你是一名招聘官, 回复简洁、自然、像真人.")
    instruction = (f"当前对话目标: {target_round.get('id')} - {target_round.get('ask','')}\n"
                   f"请基于候选人最新消息生成一句简洁自然的回复, 不要超过 80 字.\n"
                   f"严禁向候选人索要微信、电话、转账或任何敏感联系方式.")
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
