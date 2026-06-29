"""三大核心工作流"""
import asyncio
import json
import random
import re
import time as _time
from typing import List, Dict, Optional, Tuple

from app.config import settings
from app.automation import automation, cancel_event
from app.database import Database
from app.logging_config import logger
import httpx

from app.filter_criteria import (
    ALL_ELITE_SCHOOLS, FilterCriteria, match_school as _match_school,
)
from app.chat_nav import check_limit_popup, dismiss_popup


# ========== 3.1 主动筛选沟通流程 ==========

# JS: 在 iframe 内提取候选人卡片 + 打招呼按钮坐标
# /web/chat/recommend 页面结构: 主页面 > .frame-box > iframe(src=/web/frame/recommend/)
# 候选人卡片和打招呼按钮都在 iframe 内部
#
# 关键修复: 只返回"打招呼按钮在可视区域内"的卡片。
# 之前返回所有卡片(含已滚出视口的)，导致 greet_y 为负数，
# cdp_click_viewport 点击负坐标 → 点击失败。
_JS_EXTRACT_CARDS = """
(function() {
    var greets = ['打招呼','立即沟通','开聊','继续沟通'];
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    var doc = iframe && iframe.contentDocument ? iframe.contentDocument : document;
    var ox = 0, oy = 0;
    if (iframe) {
        var ir = iframe.getBoundingClientRect();
        ox = ir.x; oy = ir.y;
    }
    // 主视口尺寸（CDP 坐标边界）
    var vx = window.innerWidth, vy = window.innerHeight;
    var cards = Array.from(doc.querySelectorAll('.card-inner'));
    if (cards.length === 0) {
        cards = Array.from(doc.querySelectorAll('.candidate-card-wrap'));
    }
    if (cards.length === 0) {
        cards = Array.from(doc.querySelectorAll('[class*="card-inner"]'));
    }
    // 从卡片DOM提取BOSS平台唯一ID（增强版）
    function extractBossId(el) {
        // 辅助：如果值是 "数字-数字" 格式（如 data-id="28717495-0"），提取数字部分
        function cleanId(v) {
            if (!v) return v;
            var m = v.match(/^(\d+)-\d+$/);
            return m ? m[1] : v;
        }
        // 1. 扫描元素自身所有属性
        for (var a = 0; a < (el.attributes || []).length; a++) {
            var an = el.attributes[a].name;
            var av = el.attributes[a].value;
            if (!av || av.length < 5) continue;
            if (/^(data-)?(uid|userid|user-id|securityid|security-id|encryptid|encrypt-id|encrypt_uid|eid|geekid|chatid|id)$/i.test(an)) {
                return cleanId(av);
            }
        }
        // 2. 从链接href提取 (query params + path segments)
        var links = el.querySelectorAll('a[href]');
        for (var l = 0; l < links.length; l++) {
            var h = links[l].getAttribute('href') || '';
            var m = h.match(/[?&](securityId|encryptId|encryptBossId|uid|userId|bossId)=([^&?#]+)/i);
            if (m && m[2]) return m[2];
            var pm = h.match(/\/(geek|chat|boss|user)\/([a-zA-Z0-9_-]{10,})/i);
            if (pm && pm[2]) return pm[2];
        }
        // 3. 扫描子元素属性（2层深）
        var kids = el.querySelectorAll('[data-uid],[data-security-id],[data-encrypt-id],[data-id],[data-user-id]');
        for (var k = 0; k < kids.length; k++) {
            for (var b = 0; b < (kids[k].attributes || []).length; b++) {
                var kan = kids[k].attributes[b].name;
                var kav = kids[k].attributes[b].value;
                if (!kav || kav.length < 5) continue;
                if (/^(data-)?(uid|userid|securityid|security-id|encryptid|encrypt-id|encrypt_uid|eid|geekid|chatid|id)$/i.test(kan)) {
                    return cleanId(kav);
                }
            }
        }
        // 4. 父元素（3层）
        for (var p = el.parentElement, d = 0; p && d < 3; p = p.parentElement, d++) {
            for (var c = 0; c < (p.attributes || []).length; c++) {
                var pn = p.attributes[c].name;
                var pv = p.attributes[c].value;
                if (!pv || pv.length < 5) continue;
                if (/^(data-)?(uid|userid|securityid|security-id|encryptid|encrypt-id|encrypt_uid|eid|geekid|chatid|id)$/i.test(pn)) {
                    return cleanId(pv);
                }
            }
        }
        // 5. React fiber内部状态
        try {
            var fiberKey = Object.keys(el).find(function(k) { return k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'); });
            if (fiberKey) {
                var fiber = el[fiberKey];
                for (var ff = fiber, fd = 0; ff && fd < 10; ff = ff.return || ff._debugOwner, fd++) {
                    var mp = ff.memoizedProps;
                    if (mp) {
                        var idSource = mp.securityId || mp.encryptId || mp.encryptBossId || mp.uid || mp.userId || mp.bossId || mp.geekId;
                        if (idSource && typeof idSource === 'string' && idSource.length > 5) return idSource;
                        if (mp.children && typeof mp.children === 'object') {
                            var cid = mp.children.securityId || mp.children.encryptId || mp.children.uid;
                            if (cid && typeof cid === 'string' && cid.length > 5) return cid;
                        }
                    }
                }
            }
        } catch(e) {}
        return null;
    }
    var result = [];
    for (var i = 0; i < cards.length; i++) {
        var c = cards[i];
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
        // 只返回打招呼按钮在视口内的卡片
        // 按钮 y 在 [oy, vy) 范围内才可被 CDP 点击
        if (gx !== null && gy !== null && gy >= oy && gy < vy && gx >= ox && gx < vx) {
            var bossId = extractBossId(container) || extractBossId(c);
            result.push({
                text: (c.innerText||'').trim(), x: r.x + ox, y: r.y + oy, w: r.width, h: r.height,
                cx: r.x+r.width/2+ox, cy: r.y+r.height/2+oy,
                greet_x: gx, greet_y: gy, greet_text: gt,
                boss_id: bossId
            });
        }
    }
    return JSON.stringify(result);
})()
"""

# JS: 监听 + 自动记录新出现的弹窗（打招呼后BOSS可能弹出"推荐牛人"等模态）
_JS_POPUP_WATCHER_INSTALL = """
(function() {
    window.__f5_popups = [];
    function record(el) {
        var c = typeof el.className === 'string' ? el.className : '';
        var t = (el.innerText || '').trim().slice(0, 100);
        window.__f5_popups.push({cls: c, tag: el.tagName, txt: t});
    }
    function scan(doc) {
        var all = doc.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i], s = getComputedStyle(el);
            if (s.display === 'none') continue;
            var z = parseInt(s.zIndex) || 0;
            if ((s.position === 'fixed' || s.position === 'absolute') && z > 200 && el.offsetWidth > 100 && el.offsetHeight > 80) {
                record(el);
            }
        }
    }
    // 扫描主文档
    scan(document);
    // 扫描 iframe
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) scan(iframe.contentDocument);
    // MutationObserver 监听新增弹窗
    var observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(m) {
            for (var i = 0; i < m.addedNodes.length; i++) {
                var node = m.addedNodes[i];
                if (node.nodeType === 1) {
                    var s = getComputedStyle(node);
                    var z = parseInt(s.zIndex) || 0;
                    if ((s.position === 'fixed' || s.position === 'absolute') && z > 200) {
                        record(node);
                        // 同时递归扫描子元素
                        var children = node.querySelectorAll('*');
                        for (var j = 0; j < children.length; j++) record(children[j]);
                    }
                }
            }
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
    // 也对 iframe 内监听
    var iframe2 = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe2 && iframe2.contentDocument && iframe2.contentDocument.body) {
        observer.observe(iframe2.contentDocument.body, { childList: true, subtree: true });
    }
    return JSON.stringify({installed: true, existing: window.__f5_popups.length});
})()
"""

# JS: 读取观察器捕获的弹窗信息 + 暴力关闭所有弹窗
_JS_POPUP_WATCHER_DISMISS = """
(function() {
    var popups = window.__f5_popups || [];
    var closed = 0;
    // 从记录的弹窗中提取 class 名，构建精准选择器
    var exactSelectors = [];
    var seen = {};
    popups.forEach(function(p) {
        if (p.cls && !seen[p.cls]) {
            seen[p.cls] = true;
            // 取第一个 class 名作为选择器（避免复合选择器过长）
            var firstCls = p.cls.split(' ')[0];
            if (firstCls && firstCls.length > 2) {
                exactSelectors.push('.' + firstCls);
            }
        }
    });
    // 通用选择器 + 精准选择器
    var baseSelectors = '.dialog-wrap,[class*=overlay],[class*=mask],[class*=backdrop],.boss-popup__wrapper,[class*=modal],[class*=drawer],[class*=popup],.t-popup,[class*=recommend-popup],[class*=guide],[class*=notice]';
    var selector = baseSelectors + (exactSelectors.length > 0 ? ',' + exactSelectors.join(',') : '');
    // 暴力扫描：移除所有 fixed/absolute + 高z-index + 大尺寸的遮罩（排除侧边栏和水印）
    function removePopups(doc) {
        var all = doc.querySelectorAll('*');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            var s = getComputedStyle(el);
            var z = parseInt(s.zIndex) || 0;
            if (s.display === 'none') continue;
            var cls = typeof el.className === 'string' ? el.className : '';
            // 跳过已知安全元素：侧边栏、水印
            if (cls.indexOf('side-wrap') >= 0 || cls.indexOf('__wm') >= 0) continue;
            if (cls.indexOf('chat-global-wrap') >= 0) continue;
            // 移除弹窗/遮罩
            if ((s.position === 'fixed' || s.position === 'absolute') && z > 200 && el.offsetWidth > 80 && el.offsetHeight > 60) {
                el.remove();
                closed++;
            }
        }
    }
    removePopups(document);
    // 也扫描 iframe
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) removePopups(iframe.contentDocument);
    window.__f5_popups = [];
    return JSON.stringify({closed: closed, last_popups: popups});
})()
"""

# JS: 根据卡片文本指纹重新定位打招呼按钮（避免弹窗后坐标偏移）
_JS_REFIND_GREET_BTN = """
(function() {
    var fp = '%s';
    var greets = ['打招呼','立即沟通','开聊','继续沟通'];
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    var doc = iframe && iframe.contentDocument ? iframe.contentDocument : document;
    var ox = iframe ? iframe.getBoundingClientRect().x : 0;
    var oy = iframe ? iframe.getBoundingClientRect().y : 0;
    var cards = Array.from(doc.querySelectorAll('.card-inner'));
    if (cards.length === 0) cards = Array.from(doc.querySelectorAll('.candidate-card-wrap'));
    if (cards.length === 0) cards = Array.from(doc.querySelectorAll('[class*="card-inner"]'));
    if (cards.length === 0) cards = Array.from(doc.querySelectorAll('.recommend-card'));
    for (var i = 0; i < cards.length; i++) {
        var c = cards[i];
        var t = (c.innerText||'').trim();
        if (t.substring(0,50).trim() !== fp) continue;
        var btns = c.querySelectorAll('button, [class*="btn"], [class*="greet"]');
        for (var j = 0; j < btns.length; j++) {
            var btnText = (btns[j].innerText||'').trim();
            if (greets.indexOf(btnText) >= 0 && btns[j].offsetParent !== null) {
                var br = btns[j].getBoundingClientRect();
                return JSON.stringify({found: true, gx: br.x + br.width/2 + ox, gy: br.y + br.height/2 + oy, greet_text: btnText});
            }
        }
    }
    return JSON.stringify({found: false});
})()
"""

# JS: 直接通过 DOM 点击打招呼按钮（绕过 z-index 弹窗遮挡）
# 相比 CDP 坐标点击，element.click() + dispatchEvent 直接作用于目标元素，
# 不受上方弹窗/遮罩的 z-index 影响
_JS_CLICK_GREET_BTN = """
(function() {
    var fp = '%s';
    var greets = ['打招呼','立即沟通','开聊','继续沟通'];
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    var doc = iframe && iframe.contentDocument ? iframe.contentDocument : document;
    var cards = Array.from(doc.querySelectorAll('.card-inner'));
    if (cards.length === 0) cards = Array.from(doc.querySelectorAll('.candidate-card-wrap'));
    if (cards.length === 0) cards = Array.from(doc.querySelectorAll('[class*="card-inner"]'));
    if (cards.length === 0) cards = Array.from(doc.querySelectorAll('.recommend-card'));
    for (var i = 0; i < cards.length; i++) {
        var c = cards[i];
        var t = (c.innerText||'').trim();
        if (t.substring(0,50).trim() !== fp) continue;
        var btns = c.querySelectorAll('button, [class*="btn"], [class*="greet"], [class*="chat-btn"]');
        for (var j = 0; j < btns.length; j++) {
            var btnText = (btns[j].innerText||'').trim();
            if (greets.indexOf(btnText) >= 0 && btns[j].offsetParent !== null) {
                var rect = btns[j].getBoundingClientRect();
                var cx = rect.left + rect.width / 2;
                var cy = rect.top + rect.height / 2;
                // 1. 先发送完整的 MouseEvent（兼容 React 合成事件）
                var evt = new MouseEvent('click', {
                    bubbles: true, cancelable: true, view: window,
                    clientX: cx, clientY: cy, button: 0
                });
                btns[j].dispatchEvent(evt);
                // 2. 再调用原生 click()（兼容直接绑定的 onclick）
                try { btns[j].click(); } catch(e) {}
                return JSON.stringify({found: true, clicked: true, btn_text: btnText});
            }
        }
        // 如果精确文本匹配失败，尝试模糊匹配（按钮文本包含关键词）
        for (var j2 = 0; j2 < btns.length; j2++) {
            var btnText2 = (btns[j2].innerText||'').trim();
            var matched = false;
            for (var g = 0; g < greets.length; g++) {
                if (btnText2.indexOf(greets[g]) >= 0) { matched = true; break; }
            }
            if (matched && btns[j2].offsetParent !== null) {
                var rect2 = btns[j2].getBoundingClientRect();
                var cx2 = rect2.left + rect2.width / 2;
                var cy2 = rect2.top + rect2.height / 2;
                var evt2 = new MouseEvent('click', {
                    bubbles: true, cancelable: true, view: window,
                    clientX: cx2, clientY: cy2, button: 0
                });
                btns[j2].dispatchEvent(evt2);
                try { btns[j2].click(); } catch(e) {}
                return JSON.stringify({found: true, clicked: true, btn_text: btnText2, fuzzy: true});
            }
        }
    }
    return JSON.stringify({found: false});
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

# JS: 将 iframe 内候选列表滚回顶部（重新开始扫描）
_JS_SCROLL_TOP = """
(function() {
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    var doc = iframe && iframe.contentDocument ? iframe.contentDocument : document;
    var scrollable = doc.querySelector('.list-wrap') || doc.querySelector('.candidate-body') || doc.querySelector('.recommend-list-wrap') || doc.documentElement;
    scrollable.scrollTop = 0;
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
    batch_limit: int = 20,
) -> Dict:
    """3.1 主动筛选沟通流程 - 批量打招呼(同步入口)"""
    import concurrent.futures

    coro = _auto_contact_impl(
        daily_cap=daily_cap, school_whitelist=school_whitelist,
        min_degree=min_degree, min_years=min_years,
        dry_run=dry_run, criteria=criteria, batch_limit=batch_limit,
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
    batch_limit: int = 20, user_id: int = None,
) -> Dict:
    """批量打招呼核心逻辑 (async)"""
    if criteria is None:
        criteria = FilterCriteria(
            school_whitelist=school_whitelist or None,
            min_degree=min_degree, min_years=min_years,
        )
    logger.info(f"[F5] 启动 | 每日上限={daily_cap} 本次={batch_limit} dry={dry_run} filters={criteria.get_active_filters()}")

    # 检查浏览器(使用 _ensure_session 进行健康探测)
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接或会话失效, 请先打开BOSS直聘"}

    # 检查今日已联系数量
    with Database() as db:
        db.init_tables()
        already = db.count_contacted_today()
        contacted_ids = set(db.get_contacted_today())
    daily_remaining = max(0, daily_cap - already)
    if daily_remaining <= 0:
        return {"status": "completed", "message": f"今日已达上限({already}/{daily_cap})",
                "contacted": 0, "skipped": 0, "failed": 0, "total_scanned": 0}
    # 本次实际目标 = min(单次数量, 每日剩余)
    target = min(batch_limit, daily_remaining)
    logger.info(f"[F5] 今日已联系{already}人, 每日剩余{daily_remaining}, 本次目标{target}")

    # 导航到招聘者推荐牛人页面
    nav = await automation.navigate("https://www.zhipin.com/web/chat/recommend")
    if nav.get("status") == "error":
        return {"status": "error", "message": f"导航失败: {nav.get('message')}"}
    # 等待页面动态加载 iframe(/web/frame/recommend/)
    await asyncio.sleep(8)

    # 将列表滚回顶部，确保从第一个候选人开始
    await automation.execute_js(_JS_SCROLL_TOP)
    await asyncio.sleep(2)

    # 主循环
    contacted = skipped = failed = 0
    seen = set()
    no_new = 0
    js_fail = 0  # JS 提取失败计数 (与 no_new 分离)
    start_time = _time.monotonic()
    TIMEOUT_SECONDS = 600  # 10 分钟全局超时
    last_screenshot_at = 0  # 上次截图时的 total 数
    limit_reached = False  # BOSS 限制弹窗标记

    while contacted < target and not limit_reached:
        # 检查取消信号
        if cancel_event.is_set():
            logger.info("[F5] 检测到取消信号，停止")
            break
        # 全局超时保护
        if _time.monotonic() - start_time > TIMEOUT_SECONDS:
            logger.warning(f"[F5] 超时退出 ({TIMEOUT_SECONDS}s)")
            break

        # 限制弹窗检测 -- BOSS "已达上限" 等提示
        limit_kw = await check_limit_popup()
        if limit_kw:
            logger.warning(f"[F5] 检测到限制弹窗: {limit_kw}，终止打招呼")
            await dismiss_popup()
            limit_reached = True
            break

        # 提取可见卡片（JS 已过滤：只返回按钮在视口内的卡片）
        try:
            raw = await automation.execute_js(_JS_EXTRACT_CARDS)
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
                logger.warning("[F5] JS连续3次无可见卡片, 尝试重新检测iframe...")
                iframe_ok = await automation.execute_js(
                    "!!(document.querySelector('.frame-box iframe') || document.querySelector('iframe'))"
                )
                if not iframe_ok:
                    logger.error("[F5] iframe 不存在, 退出")
                    break
            if js_fail >= 10:
                logger.error("[F5] 连续10次无可见卡片, 退出")
                break
            # 没有可见卡片 → 滚动加载更多
            await automation.execute_js(_JS_SCROLL_IFRAME)
            await asyncio.sleep(2)
            continue

        # 卡片提取成功, 重置失败计数
        js_fail = 0

        # 去重
        new_cards = []
        for c in cards:
            fp = c.get("text", "").strip()[:50]
            if fp and fp not in seen:
                seen.add(fp)
                new_cards.append(c)
        if not new_cards:
            no_new += 1
            # 连续 3 次无新卡片 → 刷新推荐页面获取新一批候选人
            if no_new >= 3 and contacted < target:
                logger.info(f"[F5] 连续{no_new}次无新卡片，刷新推荐页面获取新候选人...")
                nav = await automation.navigate("https://www.zhipin.com/web/chat/recommend")
                if nav.get("status") == "error":
                    logger.warning(f"[F5] 刷新导航失败: {nav.get('message')}")
                await asyncio.sleep(8)  # 等待页面+iframe 重新加载
                await automation.execute_js(_JS_SCROLL_TOP)
                await asyncio.sleep(2)
                no_new = 0  # 重置计数器
                continue
            if no_new >= 10:
                logger.error(f"[F5] 连续{no_new}次无新卡片（含刷新重试），退出")
                break
            # 先滚动尝试加载更多
            await automation.execute_js(_JS_SCROLL_IFRAME)
            await asyncio.sleep(2)
            continue
        no_new = 0
        logger.info(f"[F5] 发现{len(new_cards)}个可见卡片 (按钮在视口内)")

        # 从当前可见卡片中找一个符合条件且未联系的，点击后立即 break
        # 回到外层 while 重新提取卡片坐标（因为"为您推荐"等内嵌元素会改变布局）
        clicked_this_round = False
        for card in new_cards:
            # 检查取消信号
            if cancel_event.is_set():
                logger.info("[F5] 检测到取消信号，停止")
                break
            if contacted >= target:
                break
            txt = card.get("text", "")
            cand = {
                "name": _extract_name(txt), "years": _extract_years(txt),
                "degree": _extract_degree(txt), "school": _extract_school(txt),
            }
            fingerprint = card.get("text", "").strip()[:50]
            boss_id = card.get("boss_id") or cand["name"] or f"unk_{hash(fingerprint) & 0xFFFFFF}"

            if boss_id in contacted_ids or not _should_contact(cand, criteria):
                skipped += 1
                continue

            gx, gy = card.get("greet_x"), card.get("greet_y")
            if gx is None or gy is None:
                skipped += 1
                continue

            logger.info(f"[F5] 符合: {boss_id[:1]}** yrs={cand['years']} deg={cand['degree']} sch={cand['school']}")

            if dry_run:
                contacted += 1
                contacted_ids.add(boss_id)
                logger.info(f"[F5] dry_run 模拟点击: ({gx:.0f},{gy:.0f}) btn={card.get('greet_text')}")
                clicked_this_round = True
                break

            # CDP 点击（当前 DOM 中的最新坐标）
            logger.info(f"[F5] CDP点击: ({gx:.0f},{gy:.0f}) btn={card.get('greet_text')}")
            if await automation.cdp_click_viewport(float(gx), float(gy)):
                contacted += 1
                contacted_ids.add(boss_id)
                try:
                    with Database() as db:
                        db.init_tables()
                        db.insert_contact_record(
                            boss_id=boss_id, action="contacted", success=True, user_id=user_id,
                        )
                        db.insert_candidate(
                            boss_id=boss_id, candidate_name=cand["name"],
                            school=cand["school"], degree=cand["degree"],
                            years=cand["years"], status="contacted", user_id=user_id,
                        )
                except Exception as db_err:
                    logger.warning(f"[F5] DB写入失败: {db_err}")
                logger.info(f"[F5] 成功({contacted}/{target}): {boss_id[:1]}**")

                # 点击后等待 + 检测限制弹窗
                await asyncio.sleep(0.8)
                limit_kw2 = await check_limit_popup()
                if limit_kw2:
                    logger.warning(f"[F5] 检测到限制弹窗: {limit_kw2}，终止打招呼")
                    await dismiss_popup()
                    limit_reached = True
                    break
                # 重要: break 出 for 循环, 回到外层 while 重新提取卡片
                # 因为"为您推荐"等内嵌元素已改变页面布局, 旧坐标不可用
                clicked_this_round = True
                break
            else:
                failed += 1
                logger.warning(f"[F5] CDP点击失败: {boss_id[:1]}**")

        # 本轮没点击任何人 → 滚动加载更多
        if not clicked_this_round:
            await automation.execute_js(_JS_SCROLL_IFRAME)
            await asyncio.sleep(random.uniform(1, 2))

        # 每5个新增截图
        total = contacted + skipped + failed
        if total - last_screenshot_at >= 5:
            try:
                await automation.screenshot(path=f"/tmp/f5_progress_{contacted}.png")
                last_screenshot_at = total
            except Exception:
                pass

        await asyncio.sleep(random.uniform(1.5, 3))

    try:
        await automation.screenshot(path="/tmp/f5_final.png")
    except Exception:
        pass

    return {
        "status": "completed" if not limit_reached else "limit_reached",
        "contacted": contacted, "skipped": skipped,
        "failed": failed, "total_scanned": contacted + skipped + failed,
        "dry_run": dry_run, "cap_used": f"{already + contacted}/{daily_cap}",
        "limit_reached": limit_reached,
    }


def _extract_name(text: str) -> Optional[str]:
    """从卡片文本提取姓名 -- 跳过薪资等非姓名行"""
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
