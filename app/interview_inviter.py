"""批量约面试工作流 — 对标记为"可约面"的候选人发起约面试（测试模式）"""
import asyncio
import json
from datetime import datetime
from typing import Dict

from app.automation import automation, cancel_event
from app.chat_nav import (
    navigate_to_chat, get_contacts, click_contact,
    check_limit_popup, dismiss_popup,
    click_received_resume_filter,
    refind_contact, scroll_contact_into_view,
)
from app.database import Database
from app.logging_config import logger

# JS: 在聊天页找"约面试"按钮 — 输入框上方功能区
_JS_FIND_INTERVIEW_BTN = """
(function() {
    var btns = document.querySelectorAll('button, a, span[role="button"], div[role="button"], [class*="btn"]');
    for (var i = 0; i < btns.length; i++) {
        var t = (btns[i].innerText || '').trim();
        if (t.indexOf('约面试') >= 0 && btns[i].offsetParent !== null) {
            var r = btns[i].getBoundingClientRect();
            return {found: true, text: t, x: r.x + r.width/2, y: r.y + r.height/2,
                    tag: btns[i].tagName, className: btns[i].className};
        }
    }
    // 回退：搜索输入框上方的工具栏区域
    var toolbar = document.querySelector('.chat-toolbar, .chat-operation-bar, [class*="toolbar"], [class*="operation"]');
    if (toolbar) {
        var tbs = toolbar.querySelectorAll('button, a, span[role="button"], div[role="button"]');
        for (var j = 0; j < tbs.length; j++) {
            var tt = (tbs[j].innerText || '').trim();
            if (tt.indexOf('约面试') >= 0 && tbs[j].offsetParent !== null) {
                var tr = tbs[j].getBoundingClientRect();
                return {found: true, text: tt, x: tr.x + tr.width/2, y: tr.y + tr.height/2,
                        tag: tbs[j].tagName, className: tbs[j].className};
            }
        }
    }
    return {found: false};
})()
"""

# JS: 在弹窗对话框找"取消"按钮
_JS_FIND_CANCEL_BTN = """
(function() {
    var dialogs = document.querySelectorAll('[class*="dialog"], [class*="modal"], [class*="popup"], [class*="overlay"], [class*="wrapper"]');
    for (var i = 0; i < dialogs.length; i++) {
        var d = dialogs[i];
        if (d.offsetParent === null || (d.style.display && d.style.display === 'none')) continue;
        var r = d.getBoundingClientRect();
        if (r.width < 50 || r.height < 50) continue;
        var btns = d.querySelectorAll('button, a, span[role="button"]');
        for (var j = 0; j < btns.length; j++) {
            var t = (btns[j].innerText || '').trim();
            if (t === '取消' && btns[j].offsetParent !== null) {
                var br = btns[j].getBoundingClientRect();
                return {found: true, text: t, x: br.x + br.width/2, y: br.y + br.height/2,
                        tag: btns[j].tagName};
            }
        }
        // 回退：找"取消"文本的任意元素
        var allEls = d.querySelectorAll('*');
        for (var k = 0; k < allEls.length; k++) {
            if ((allEls[k].innerText || '').trim() === '取消' && allEls[k].children.length === 0) {
                var er = allEls[k].getBoundingClientRect();
                return {found: true, text: '取消', x: er.x + er.width/2, y: er.y + er.height/2,
                        tag: allEls[k].tagName};
            }
        }
    }
    return {found: false};
})()
"""

# JS: 在约面试弹窗中找指定面试类型按钮（"线下面试" / "线上面试"）
_JS_CLICK_INTERVIEW_TYPE = """
(function() {
    var targetType = '%s';
    var dialogs = document.querySelectorAll('[class*="dialog"], [class*="modal"], [class*="popup"], [class*="overlay"], [class*="wrapper"]');
    for (var i = 0; i < dialogs.length; i++) {
        var d = dialogs[i];
        if (d.offsetParent === null || (d.style.display && d.style.display === 'none')) continue;
        var r = d.getBoundingClientRect();
        if (r.width < 50 || r.height < 50) continue;
        // 优先找 radio-item label（精确匹配），再回退到通用搜索
        var candidates = [];
        var all = d.querySelectorAll('label[class*="radio-item"], label[class*="radio"], span[class*="radio-item"]');
        for (var j = 0; j < all.length; j++) {
            var t = (all[j].innerText || '').trim();
            if (t === targetType || t.indexOf(targetType) >= 0) {
                candidates.push({el: all[j], text: t, priority: t === targetType ? 0 : 1});
            }
        }
        // 回退：通用按钮搜索
        if (candidates.length === 0) {
            var generic = d.querySelectorAll('button, a, span, label, div[class*="btn"]');
            for (var k = 0; k < generic.length; k++) {
                var gt = (generic[k].innerText || '').trim();
                if ((gt === targetType || gt.indexOf(targetType) >= 0) && gt.length < 20) {
                    candidates.push({el: generic[k], text: gt, priority: gt === targetType ? 0 : 1});
                }
            }
        }
        // 按优先级排序（精确匹配优先），取第一个
        candidates.sort(function(a, b) { return a.priority - b.priority; });
        if (candidates.length > 0) {
            var best = candidates[0];
            var br = best.el.getBoundingClientRect();
            var evt = new MouseEvent('click', {bubbles: true, cancelable: true, view: window,
                clientX: br.x + br.width/2, clientY: br.y + br.height/2, button: 0});
            best.el.dispatchEvent(evt);
            try { best.el.click(); } catch(e) {}
            return {found: true, text: best.text};
        }
    }
    return {found: false};
})()
"""

# JS: 获取日期选择器输入框坐标
_JS_GET_DATE_TRIGGER = """
(function() {
    var dialogs = document.querySelectorAll('[class*="dialog"], [class*="modal"], [class*="popup"]');
    for (var i = 0; i < dialogs.length; i++) {
        var d = dialogs[i];
        if (d.offsetParent === null || (d.style.display && d.style.display === 'none')) continue;
        var trigger = d.querySelector('.datepicker-wrap .input-wrap') || d.querySelector('.ui-date-picker-v2 .input-wrap') || d.querySelector('.datepicker-wrap input.input');
        if (trigger && trigger.offsetParent !== null) {
            var br = trigger.getBoundingClientRect();
            return {found: true, x: br.x + br.width/2, y: br.y + br.height/2};
        }
    }
    return {found: false};
})()
"""

# JS: 获取"开始时间"下拉框坐标
_JS_GET_TIME_TRIGGER = """
(function() {
    var dialogs = document.querySelectorAll('[class*="dialog"], [class*="modal"], [class*="popup"]');
    for (var i = 0; i < dialogs.length; i++) {
        var d = dialogs[i];
        if (d.offsetParent === null) continue;
        var trigger = d.querySelector('.time-select-container .dropdown-select') || d.querySelector('.time-select-container input.time-select') || d.querySelector('.time-select-container');
        if (trigger && trigger.offsetParent !== null) {
            var br = trigger.getBoundingClientRect();
            return {found: true, x: br.x + br.width/2, y: br.y + br.height/2};
        }
    }
    return {found: false};
})()
"""

# JS: 获取时间面板中指定小时选项坐标（先滚动再获取）
_JS_GET_HOUR = """
(function() {
    var target = '%s';
    var container = document.querySelector('.time-container');
    if (!container) return {found: false};
    var lis = container.querySelectorAll('li');
    for (var i = 0; i < lis.length; i++) {
        var t = (lis[i].innerText||'').trim();
        if (t !== target) continue;
        var r = lis[i].getBoundingClientRect();
        if (r.x < 1100) {
            lis[i].scrollIntoView({block: 'nearest', behavior: 'instant'});
            r = lis[i].getBoundingClientRect();
            return {found: true, text: t, x: r.x + r.width/2, y: r.y + r.height/2};
        }
    }
    return {found: false};
})()
"""

# JS: 获取时间面板中指定分钟选项坐标（先滚动再获取）
_JS_GET_MINUTE = """
(function() {
    var target = '%s';
    var container = document.querySelector('.time-container');
    if (!container) return {found: false};
    var lis = container.querySelectorAll('li');
    for (var i = 0; i < lis.length; i++) {
        var t = (lis[i].innerText||'').trim();
        if (t !== target) continue;
        var r = lis[i].getBoundingClientRect();
        if (r.x >= 1100) {
            lis[i].scrollIntoView({block: 'nearest', behavior: 'instant'});
            r = lis[i].getBoundingClientRect();
            return {found: true, text: t, x: r.x + r.width/2, y: r.y + r.height/2};
        }
    }
    return {found: false};
})()
"""

# JS: 获取"今"今天日期坐标
_JS_CLICK_TODAY = """
(function() {
    var cells = document.querySelectorAll('.cell.day.today');
    for (var i = 0; i < cells.length; i++) {
        var r = cells[i].getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            return {found: true, text: '今天', x: r.x + r.width/2, y: r.y + r.height/2};
        }
    }
    return {found: false};
})()
"""

# JS: 读取日历面板当前显示的月份/年份（只搜日历容器内部，兼容中文月份）
_JS_GET_CALENDAR_MONTH = """
(function() {
    var CN = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12};
    var containers = document.querySelectorAll('.datepicker-wrap, .ui-date-picker-v2');
    for (var i = 0; i < containers.length; i++) {
        var c = containers[i];
        var cr = c.getBoundingClientRect();
        if (cr.width < 100) continue;
        var els = c.querySelectorAll('span, div');
        for (var j = 0; j < els.length; j++) {
            var text = (els[j].innerText || '').trim();
            // 1) 中文月份优先: "2026年 六月"（用非贪婪避免跳过月份名）
            var cm = text.match(/(\d{4})\D*?([一二三四五六七八九十]{1,3})月?/);
            if (cm && CN[cm[2]]) {
                return {found: true, year: parseInt(cm[1]), month: CN[cm[2]], text: text};
            }
            // 2) 数字月份: "2026年6月" 或 "2026/6"（严格限定月紧跟在年后）
            var m = text.match(/(\d{4})\s*[年\/\-]?\s*(\d{1,2})\s*月/);
            if (m && parseInt(m[2]) >= 1 && parseInt(m[2]) <= 12) {
                return {found: true, year: parseInt(m[1]), month: parseInt(m[2]), text: text};
            }
        }
    }
    return {found: false};
})()
"""

# JS: 在日历面板中查找指定日期单元格坐标
_JS_CLICK_DATE = """
(function() {
    var targetDate = '%s';
    var parts = targetDate.split('-');
    var targetDay = String(parseInt(parts[2]));
    // 在所有可见日历面板中搜索
    var cells = document.querySelectorAll('.cell.day');
    for (var i = 0; i < cells.length; i++) {
        var cell = cells[i];
        var text = (cell.innerText || '').trim();
        if (text !== targetDay) continue;
        var cls = cell.className || '';
        // 只跳过明确置灰/不可用的日期
        if (cls.indexOf('disabled') >= 0) continue;
        var r = cell.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            return {found: true, text: text, x: r.x + r.width/2, y: r.y + r.height/2};
        }
    }
    return {found: false};
})()
"""

# JS: 在日历面板中找下个月箭头的坐标（用于CDP点击）
_JS_FIND_NEXT_MONTH = """
(function() {
    // BOSS日历下月箭头是 SPAN.next 或类似元素
    var arrows = document.querySelectorAll('.next, [class*="next"]');
    for (var i = 0; i < arrows.length; i++) {
        var r = arrows[i].getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && r.width < 80 && r.height < 40) {
            return {found: true, x: r.x + r.width/2, y: r.y + r.height/2,
                    tag: arrows[i].tagName};
        }
    }
    return {found: false};
})()
"""


async def _batch_invite_interview_impl(max_count: int = 10, user_id: int = None, interview_type: str = None, interview_time: str = None, interview_date: str = None) -> Dict:
    """批量约面试核心逻辑（测试模式：点取消不真约）"""
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接"}

    # 导航聊天页
    nav_result = await navigate_to_chat()
    if nav_result.get("status") != "ok":
        await automation.navigate("https://www.zhipin.com/web/chat/index")
        await asyncio.sleep(3)

    # 点"已获取简历"筛选
    filter_result = await click_received_resume_filter()
    if filter_result.get("status") == "ok":
        await asyncio.sleep(2)
        contacts = await get_contacts()
    else:
        contacts = nav_result.get("contacts", [])

    if not contacts:
        return {"status": "completed", "message": "没有联系人",
                "invited": 0, "skipped": 0, "failed": 0, "total_scanned": 0}

    db = Database()
    db.connect()
    db.init_tables()

    # 获取可约面候选人列表
    recommend = db.get_recommend_interview_candidates(user_id=user_id)
    recommend_ids = {r["boss_id"] for r in recommend}
    logger.info(f"[F9] 可约面候选人: {len(recommend_ids)} 人")

    if not recommend_ids:
        db.close()
        return {"status": "completed", "message": "没有标记为可约面的候选人",
                "invited": 0, "skipped": 0, "failed": 0, "total_scanned": 0}

    invited = 0
    skipped = 0
    failed = 0
    details = []

    targets = []
    for c in contacts:
        name = (c.get("name", "") or "").strip()
        dedup_boss_id = c.get("boss_id") or name
        if dedup_boss_id in recommend_ids:
            if db.has_resume_operation(dedup_boss_id, "interview_invited", user_id=user_id):
                logger.info(f"[F9] 跳过已约面: {name}")
                skipped += 1
                details.append({"name": name, "action": "skipped", "reason": "已约面"})
            else:
                targets.append(c)

    logger.info(f"[F9] 目标 {len(targets)} 人")

    for i, contact in enumerate(targets):
        if cancel_event.is_set():
            break
        if invited >= max_count:
            break

        contact_name = (contact.get("name", "") or "").strip()
        boss_id = contact.get("boss_id") or contact_name
        logger.info(f"[F9] ({i+1}/{len(targets)}): {contact_name}")

        limit_kw = await check_limit_popup()
        if limit_kw:
            logger.warning(f"[F9] 限制弹窗: {limit_kw}")
            await dismiss_popup()
            break

        # 查找+点击联系人
        fresh = await refind_contact(contact_name)
        if not fresh:
            fresh = contact
        if not fresh.get("visible", True):
            await scroll_contact_into_view(contact_name)
            await asyncio.sleep(1)
            fresh = await refind_contact(contact_name)
            if not fresh:
                fresh = contact

        if not await click_contact(contact_name, fresh.get("x", 0), fresh.get("y", 0)):
            logger.warning(f"[F9] 点击失败: {contact_name}")
            failed += 1
            continue
        await asyncio.sleep(2)

        # 找"约面试"按钮
        intv_btn = await automation.execute_js(_JS_FIND_INTERVIEW_BTN)
        if not isinstance(intv_btn, dict) or not intv_btn.get("found"):
            logger.warning(f"[F9] {contact_name}: 未找到约面试按钮")
            failed += 1
            details.append({"name": contact_name, "action": "no_interview_btn"})
            continue

        logger.info(f"[F9] {contact_name}: 找到约面试按钮 -> ({intv_btn['x']:.0f}, {intv_btn['y']:.0f})")
        await automation.cdp_click_viewport(float(intv_btn["x"]), float(intv_btn["y"]))
        await asyncio.sleep(2)

        # 如果指定了面试类型，在弹窗中点对应按钮
        if interview_type:
            type_js = _JS_CLICK_INTERVIEW_TYPE % interview_type
            type_btn = await automation.execute_js(type_js)
            if isinstance(type_btn, dict) and type_btn.get("found"):
                logger.info(f"[F9] {contact_name}: 已点击'{type_btn['text']}'")
                await asyncio.sleep(0.5)

        # 展开日期选择器：点 datepicker input
        date_info = await automation.execute_js(_JS_GET_DATE_TRIGGER)
        if isinstance(date_info, dict) and date_info.get("found"):
            dx = date_info.get("x"); dy = date_info.get("y")
            if dx and dy:
                await automation.cdp_click_viewport(float(dx), float(dy))
                logger.info(f"[F9] {contact_name}: 已展开日期选择器 → ({dx:.0f},{dy:.0f})")
            await asyncio.sleep(1.2)

        # 选日期
        if interview_date:
            parts = interview_date.split('-')
            target_year = int(parts[0])
            target_month = int(parts[1])

            # 先检查日历面板当前显示的是哪个月
            cal_month = await automation.execute_js(_JS_GET_CALENDAR_MONTH)
            logger.info(f"[F9] {contact_name}: 日历面板显示 → {cal_month}")

            # 月份不对则切月份
            if isinstance(cal_month, dict) and cal_month.get("found"):
                disp_year = cal_month.get("year", 0)
                disp_month = cal_month.get("month", 0)
                if target_year != disp_year or target_month != disp_month:
                    nav = await automation.execute_js(_JS_FIND_NEXT_MONTH)
                    logger.info(f"[F9] {contact_name}: 需从{disp_month}月切到{target_month}月, 找箭头 → {nav}")
                    if isinstance(nav, dict) and nav.get("found"):
                        await automation.cdp_click_viewport(float(nav["x"]), float(nav["y"]))
                        logger.info(f"[F9] {contact_name}: 已点击下个月箭头 tag={nav.get('tag')} ({nav.get('w')}x{nav.get('h')})")
                        await asyncio.sleep(0.8)
                    else:
                        logger.warning(f"[F9] {contact_name}: 未找到下个月箭头!")
                else:
                    logger.info(f"[F9] {contact_name}: 日历已显示{target_month}月，无需切换")

            # 找目标日期单元格
            date_js = _JS_CLICK_DATE % interview_date
            date_found = await automation.execute_js(date_js)
            logger.info(f"[F9] {contact_name}: 查找日期 {interview_date} → {date_found}")

            if isinstance(date_found, dict) and date_found.get("found"):
                dx = date_found.get("x"); dy = date_found.get("y")
                if dx and dy:
                    await automation.cdp_click_viewport(float(dx), float(dy))
                    logger.info(f"[F9] {contact_name}: 已选日期: {date_found['text']}号 → ({dx:.0f},{dy:.0f})")
                await asyncio.sleep(0.5)
            else:
                # 回退到"今"
                logger.warning(f"[F9] {contact_name}: 未找到日期 {interview_date}，回退到今天")
                today_info = await automation.execute_js(_JS_CLICK_TODAY)
                if isinstance(today_info, dict) and today_info.get("found"):
                    tx = today_info.get("x"); ty = today_info.get("y")
                    if tx and ty:
                        await automation.cdp_click_viewport(float(tx), float(ty))
                    await asyncio.sleep(0.5)
        else:
            # 默认今天
            today_info = await automation.execute_js(_JS_CLICK_TODAY)
            if isinstance(today_info, dict) and today_info.get("found"):
                tx = today_info.get("x"); ty = today_info.get("y")
                if tx and ty:
                    await automation.cdp_click_viewport(float(tx), float(ty))
                    logger.info(f"[F9] {contact_name}: 已选日期: 今天")
                await asyncio.sleep(0.5)

        # 展开时间选择器：点"开始时间"下拉框
        time_info = await automation.execute_js(_JS_GET_TIME_TRIGGER)
        if isinstance(time_info, dict) and time_info.get("found"):
            tix = time_info.get("x"); tiy = time_info.get("y")
            if tix and tiy:
                await automation.cdp_click_viewport(float(tix), float(tiy))
                logger.info(f"[F9] {contact_name}: 已展开时间选择器 → ({tix:.0f},{tiy:.0f})")
            await asyncio.sleep(1.0)

        # 选面试时间：按参数指定的小时和分钟
        if interview_time and ':' in str(interview_time):
            parts = str(interview_time).split(':')
            sel_hour = parts[0]; sel_min = parts[1] if len(parts) > 1 else '05'
        else:
            sel_hour = '08'; sel_min = '05'

        hour_js = _JS_GET_HOUR % sel_hour
        hour_info = await automation.execute_js(hour_js)
        if isinstance(hour_info, dict) and hour_info.get("found"):
            hx = hour_info.get("x"); hy = hour_info.get("y")
            if hx and hy:
                await asyncio.sleep(0.15)
                await automation.cdp_click_viewport(float(hx), float(hy))
                logger.info(f"[F9] {contact_name}: 已选小时: {sel_hour} → ({hx:.0f},{hy:.0f})")
            await asyncio.sleep(0.3)
        else:
            logger.warning(f"[F9] {contact_name}: 未找到小时选项 '{sel_hour}'")

        min_js = _JS_GET_MINUTE % sel_min
        min_info = await automation.execute_js(min_js)
        if isinstance(min_info, dict) and min_info.get("found"):
            mx = min_info.get("x"); my = min_info.get("y")
            if mx and my:
                await asyncio.sleep(0.15)
                await automation.cdp_click_viewport(float(mx), float(my))
                logger.info(f"[F9] {contact_name}: 已选分钟: {sel_min} → ({mx:.0f},{my:.0f})")
            await asyncio.sleep(0.5)
        else:
            logger.warning(f"[F9] {contact_name}: 未找到分钟选项 '{sel_min}'")

        # 找弹窗"取消"按钮
        cancel_btn = await automation.execute_js(_JS_FIND_CANCEL_BTN)
        if isinstance(cancel_btn, dict) and cancel_btn.get("found"):
            logger.info(f"[F9] {contact_name}: 找到取消按钮 -> ({cancel_btn['x']:.0f}, {cancel_btn['y']:.0f})")
            await automation.cdp_click_viewport(float(cancel_btn["x"]), float(cancel_btn["y"]))
            await asyncio.sleep(1)
        else:
            # 没找到取消按钮，尝试按 Escape
            logger.info(f"[F9] {contact_name}: 未找到取消按钮，按Escape关闭")
            await automation.press_key("Escape")
            await asyncio.sleep(1)

        # 记录
        db.set_candidate_interview_status(boss_id, "interview_invited", user_id=user_id)
        db.insert_resume_op(
            boss_id=boss_id, candidate_name=contact_name,
            action="interview_invited", resume_downloaded=False,
            detail=json.dumps({"time": datetime.now().isoformat()}),
            user_id=user_id,
        )
        invited += 1
        details.append({"name": contact_name, "action": "interview_invited"})
        logger.info(f"[F9] {contact_name}: 已约面(测试)")

    db.close()
    return {
        "status": "completed",
        "invited": invited,
        "skipped": skipped,
        "failed": failed,
        "total_scanned": len(targets),
        "details": details,
    }
