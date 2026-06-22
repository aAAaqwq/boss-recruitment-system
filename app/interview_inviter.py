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


async def _batch_invite_interview_impl(max_count: int = 10, user_id: int = None, interview_type: str = None) -> Dict:
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
            else:
                logger.warning(f"[F9] {contact_name}: 未找到'{interview_type}'按钮")

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
