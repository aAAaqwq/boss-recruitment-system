"""
BOSS直聘 · 简历收集器 v2.3
基于 nodriver CDP 的简历自动获取

修复 (v2.3):
- 优先点击"附件简历"，只有不存在时才点"在线简历"
- 在线简历弹窗上扫描"附件简历"入口，点击后走下载流程
- 在线简历模态框识别 (online_resume)，无附件时截图记录
- 复用 chat_nav.click_contact() 替代原生 CDP 点击
- 使用 navigate_to_chat() 返回的 contacts，消除重复 get_contacts() 调用
- 限流弹窗检测 + 终止循环
- 关闭弹窗等待时间加长 (3次Escape + 渐增间隔 + 2s稳定等待)
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import httpx

from app.automation import automation, cancel_event
from app.config import settings
from app.chat_nav import (
    navigate_to_chat, get_contacts, click_contact,
    check_limit_popup, dismiss_popup,
    click_communicating_filter, click_new_greet_filter,
    get_messages, type_and_send,
    refind_contact, scroll_contact_into_view,
)
from app.database import Database
from app.logging_config import logger

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
RESUMES_DIR = DATA_DIR / "resumes"

def _resumes_dir(user_id: int = None) -> Path:
    """按用户隔离的简历目录"""
    if user_id:
        d = DATA_DIR / "resumes" / str(user_id)
    else:
        d = RESUMES_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


# ========== JS 提取脚本（主文档优先，兼容非iframe聊天页） ==========

_JS_FIND_RESUME_BTNS = """
(function() {
    function findInDoc(doc) {
        var btns = doc.querySelectorAll('button, a, span, div[class*="btn"], div[class*="resume"]');
        var results = [];
        for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].innerText || '').trim();
            if (t === '附件简历' || t === '查看附件') {
                var r = btns[i].getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    results.push({text: t, x: r.x + r.width/2, y: r.y + r.height/2, type: t});
                }
            }
        }
        return results;
    }
    var results = findInDoc(document);
    if (results.length > 0) return results;
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) return findInDoc(iframe.contentDocument);
    return results;
})()
"""

# 在弹窗/模态框中扫描"附件简历"按钮 — 针对点"在线简历"后弹窗上也有附件入口的情况
_JS_FIND_MODAL_ATTACHMENT = """
(function() {
    var vw = Math.max(window.innerWidth, 1000);
    var docs = [document];
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) docs.push(iframe.contentDocument);

    for (var d = 0; d < docs.length; d++) {
        var doc = docs[d];
        // 扫描弹窗/模态框内的按钮
        var all = doc.querySelectorAll(
            'button, a, span, div[class*="btn"], div[class*="tab"], [class*="resume"], '
            + '[class*="modal"] button, [class*="dialog"] button, [class*="popup"] button, '
            + '[class*="drawer"] button, [class*="panel"] button'
        );
        for (var i = 0; i < all.length; i++) {
            var t = (all[i].innerText || '').trim();
            // 匹配"附件简历"或下载相关按钮
            if (t === '附件简历' || t === '查看附件' || t === '下载简历' || t === '下载附件'
                || t === '下载' || t === '导出') {
                var r = all[i].getBoundingClientRect();
                if (r.width > 0 && r.height > 0 && r.x > vw * 0.3) {
                    return {
                        found: true,
                        text: t,
                        x: r.x + r.width / 2,
                        y: r.y + r.height / 2
                    };
                }
            }
        }
    }
    return {found: false};
})()
"""

_JS_FIND_DOWNLOAD_BTN = """
(function() {
    var docs = [document];
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) docs.push(iframe.contentDocument);
    for (var d = 0; d < docs.length; d++) {
        var doc = docs[d];
        var btns = doc.querySelectorAll('button, a, [class*="download"], [class*="save"]');
        for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].innerText || '').trim();
            if (t === '下载' || t === '保存' || t === '导出' || t === '下载简历') {
                var r = btns[i].getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    return {found: true, x: r.x + r.width/2, y: r.y + r.height/2, text: t};
                }
            }
        }
        var links = doc.querySelectorAll('a[download]');
        for (var j = 0; j < links.length; j++) {
            var rr = links[j].getBoundingClientRect();
            if (rr.width > 0 && rr.height > 0) {
                return {found: true, x: rr.x + rr.width/2, y: rr.y + rr.height/2, text: 'download_link'};
            }
        }
    }
    return {found: false};
})()
"""

# 点击"附件简历"后检测弹出内容类型
_JS_DETECT_RESUME_CASE = """
(function() {
    var docs = [document];
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) docs.push(iframe.contentDocument);
    for (var d = 0; d < docs.length; d++) {
        var pdfElements = docs[d].querySelectorAll(
            'embed[type="application/pdf"], iframe[src*="pdf"], [class*="pdf"], [data-type="pdf"]'
        );
        if (pdfElements.length > 0) return {case_type: 'pdf_preview'};
    }
    var allText = '';
    for (var d = 0; d < docs.length; d++) {
        allText += ' ' + (docs[d].body.innerText || '');
    }
    for (var d = 0; d < docs.length; d++) {
        var confirmBtns = docs[d].querySelectorAll('button, [class*="btn"]');
        for (var i = 0; i < confirmBtns.length; i++) {
            var t = (confirmBtns[i].innerText || '').trim();
            if (t === '确认' || t === '确定') {
                if (allText.indexOf('请求简历') >= 0 || allText.indexOf('向牛人') >= 0) {
                    var r = confirmBtns[i].getBoundingClientRect();
                    return {case_type: 'request_popup', x: r.x + r.width/2, y: r.y + r.height/2, text: t};
                }
            }
        }
    }
    if (allText.indexOf('请求中') >= 0 || allText.indexOf('简历请求') >= 0) {
        return {case_type: 'request_pending'};
    }
    if (allText.indexOf('双方回复后') >= 0 || allText.indexOf('回复后可以') >= 0) {
        return {case_type: 'need_reply'};
    }
    // 检测在线简历模态框 — 通常包含"个人信息"/"工作经历"/"教育经历"等结构化内容
    if (allText.indexOf('个人信息') >= 0 || allText.indexOf('工作经历') >= 0
        || allText.indexOf('教育经历') >= 0 || allText.indexOf('个人优势') >= 0
        || allText.indexOf('期望工作') >= 0) {
        return {case_type: 'online_resume'};
    }
    return {case_type: 'unknown'};
})()
"""

# JS: 点击BOSS引导提示的"我知道了"按钮，避免遮挡确认按钮
_JS_CLICK_I_KNOW = """
(function() {
    var docs = [document];
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) docs.push(iframe.contentDocument);
    for (var d = 0; d < docs.length; d++) {
        var all = docs[d].querySelectorAll('button, a, span, div');
        for (var i = 0; i < all.length; i++) {
            if ((all[i].innerText || '').trim() === '我知道了') {
                var r = all[i].getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    all[i].click();
                    return {dismissed: true};
                }
            }
        }
    }
    return {dismissed: false};
})()
"""

# 验证右侧聊天面板是否已切换（主文档优先）
_JS_VERIFY_CHAT_PANEL = """
(function() {
    var expectedName = {NAME_PLACEHOLDER};
    var vw = Math.max(window.innerWidth, 1000);

    function checkDoc(doc, label) {
        // 检查右侧面板是否包含目标候选人名字
        var allEls = doc.querySelectorAll('div, span, h1, h2, h3, h4, p, a');
        for (var i = 0; i < allEls.length; i++) {
            var r = allEls[i].getBoundingClientRect();
            var t = (allEls[i].innerText || '').trim();
            if (r.x > vw * 0.3 && r.y < 200 && t.length > 1 && t.indexOf(expectedName) >= 0) {
                return {switched: true, method: 'name_in_right_panel_' + label};
            }
        }
        return null;
    }

    // 先查主文档
    var result = checkDoc(document, 'main');
    if (result) return result;

    // 回退: iframe
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var ifResult = checkDoc(iframe.contentDocument, 'iframe');
        if (ifResult) return ifResult;
    }

    if (window.location.href.indexOf('/chat') >= 0) {
        return {switched: true, method: 'url_match'};
    }
    return {switched: false};
})()
"""


def _update_candidate_resume(db: Database, candidate_name: str, resume_path: str = "", boss_id: str = "", user_id: int = None) -> None:
    """更新 candidates 表中的简历路径和状态（安全写入，失败不抛异常）。"""
    try:
        db.cursor.execute(
            """INSERT INTO candidates (boss_id, candidate_name, status, resume_path, updated_at, user_id)
               VALUES (%s, %s, 'resume_downloaded', %s, NOW(), %s)
               ON CONFLICT(boss_id) DO UPDATE SET
               resume_path = excluded.resume_path,
               status = 'resume_downloaded',
               updated_at = excluded.updated_at,
               user_id = COALESCE(excluded.user_id, candidates.user_id)""",
            (boss_id or candidate_name, candidate_name, resume_path, user_id),
        )
        db.conn.commit()
        logger.info(f"[F6] candidates表已更新: {candidate_name} resume={resume_path}")
    except Exception as e:
        logger.debug(f"[F6] 更新candidates表忽略: {e}")


async def collect_resumes(max_count: int = 10, dry_run: bool = False, user_id: int = None) -> Dict:
    """收集简历主流程

    Args:
        max_count: 最多处理人数
        dry_run: 干跑模式（只扫描不操作）

    Returns:
        {status, downloaded, skipped, failed, total_scanned, details: [...]}
    """
    resumes_dir = _resumes_dir(user_id)

    # 确保浏览器连接
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接，请先打开BOSS直聘"}

    # 注意: 不在此处调用 check_login()，因为它会导航到 /web/chat/recommend，
    # 然后 navigate_to_chat() 再次导航到同一 URL，双重导航干扰 BOSS直聘的
    # 异步联系人列表加载，导致 get_contacts() 返回 0。

    # 启用 CDP 下载拦截 — 文件自动保存到 data/resumes/
    if not dry_run:
        dl_result = await automation.enable_download_interception(str(resumes_dir))
        logger.info(f"[F6] CDP下载拦截: {dl_result.get('status')} → {resumes_dir}")

    # 导航到聊天页
    nav_result = await navigate_to_chat()
    if nav_result.get("status") != "ok":
        # 备用: 直接导航 /web/chat/index
        logger.info("[F6] navigate_to_chat 失败，尝试备用导航 /web/chat/index")
        nav2 = await automation.navigate("https://www.zhipin.com/web/chat/index")
        if nav2.get("status") == "error":
            return {"status": "error", "message": "无法访问聊天页，可能需登录"}
        await asyncio.sleep(3)

    # 初始化数据库
    db = Database()
    db.connect()
    db.init_tables()

    downloaded = 0
    skipped = 0
    failed = 0
    details = []

    # === 阶段1: "沟通中"筛选 → 对比数据库，跳过已处理过的 ===
    comm_result = await click_communicating_filter()
    if comm_result.get("status") == "ok":
        await asyncio.sleep(2)
        comm_contacts = await get_contacts()
    else:
        comm_contacts = []
    if not comm_contacts:
        comm_contacts = nav_result.get("contacts", [])

    # 过滤掉数据库中已处理过的（downloaded 或 requested）
    contacts = []
    for c in comm_contacts:
        name = (c.get("name", "") or "").strip()
        if not name:
            continue
        dedup_boss_id = c.get("boss_id") or name  # 优先用平台ID去重
        try:
            ops = db.get_resume_ops(boss_id=dedup_boss_id)
        except Exception:
            ops = []
        already_processed = any(
            r.get("action") in ("downloaded", "requested", "rejected", "farewell") or r.get("resume_downloaded")
            for r in ops
        )
        if already_processed:
            logger.info(f"[F6] 跳过已处理: {name}")
            details.append({"name": name, "action": "skipped", "reason": "已处理过"})
            skipped += 1
        else:
            contacts.append(c)

    logger.info(f"[F6] 阶段1(沟通中): {len(comm_contacts)}人 → 过滤后 {len(contacts)}人待处理")

    # === 阶段2: 如果还没达到上限，补充"新招呼" ===
    if len(contacts) < max_count:
        greet_result = await click_new_greet_filter()
        if greet_result.get("status") == "ok":
            await asyncio.sleep(2)
            greet_contacts = await get_contacts()
            remaining = max_count - len(contacts)
            # "新招呼"的联系人一定没处理过，直接加入
            greet_added = 0
            for c in greet_contacts:
                name = (c.get("name", "") or "").strip()
                if not name:
                    continue
                contacts.append(c)
                greet_added += 1
                if greet_added >= remaining:
                    break
            logger.info(f"[F6] 阶段2(新招呼): 补充 {greet_added}人")
        else:
            logger.info("[F6] 阶段2(新招呼): 未找到筛选按钮，跳过")

    if not contacts:
        db.close()
        return {
            "status": "completed", "message": "没有待处理的联系人",
            "downloaded": 0, "skipped": skipped, "failed": 0,
            "total_scanned": 0, "resume_ops": 0, "details": details,
        }

    logger.info(f"[F6] 待处理 {len(contacts)} 人，目标获取 {max_count} 份简历")

    resume_ops = 0  # 成功获取/请求简历的人数（不含跳过和失败）
    for i, contact in enumerate(contacts):
        # 检查取消信号
        if cancel_event.is_set():
            logger.info("[F6] 检测到取消信号，停止遍历")
            break
        # 已达到目标，停止遍历
        if resume_ops >= max_count:
            logger.info(f"[F6] 已达到目标 {max_count} 份，停止遍历")
            break
        contact_name = (contact.get("name", "") or contact.get("text", "") or f"contact_{i}").strip()
        boss_id = contact.get("boss_id") or contact_name  # 优先使用BOSS平台唯一ID
        logger.info(f"[F6] 处理 ({i+1}/{len(contacts)}, 已获取{resume_ops}/{max_count}): {contact_name}")

        # 检查去重（用平台唯一ID）
        try:
            existing = db.get_resume_ops(boss_id=boss_id, user_id=user_id)
        except Exception:
            existing = []
        if existing:
            already_processed = any(
                r.get("resume_downloaded") or r.get("action") in ("downloaded", "requested", "rejected", "farewell")
                for r in existing
            )
            if already_processed:
                skipped += 1
                details.append({"name": contact_name, "action": "skipped", "reason": "已处理过"})
                logger.info(f"[F6] 跳过 {contact_name}: 已处理过")
                continue

        # Fix 2: 逐次提取坐标 — 每次点击前重新查找联系人位置
        fresh_contact = await refind_contact(contact_name)
        if not fresh_contact:
            logger.warning(f"[F6] 逐次查找联系人失败: {contact_name}, 回退到原始坐标")
            fresh_contact = contact

        # 0. 联系人不可见 → 滚动左侧列表使其落入视口
        if not fresh_contact.get("visible", True):
            logger.info(f"[F6] {contact_name} 在 y={fresh_contact.get('y')}，滚动列表使其可见")
            await scroll_contact_into_view(contact_name)
            await asyncio.sleep(1)
            # 重新获取坐标
            fresh_contact = await refind_contact(contact_name)
            if not fresh_contact:
                fresh_contact = contact
            logger.info(f"[F6] {contact_name} 滚动后 y={fresh_contact.get('y')}")

        # 1. 限制弹窗检测 — 命中则终止循环
        limit_kw = await check_limit_popup()
        if limit_kw:
            logger.warning(f"[F6] 检测到限制弹窗: {limit_kw}，终止")
            await dismiss_popup()
            break

        # a. 点击联系人 — 复用 chat_nav 已验证的 click_contact()
        if not await click_contact(
            contact_name, fresh_contact.get("x", 0), fresh_contact.get("y", 0)
        ):
            logger.warning(f"[F6] 点击联系人失败: {contact_name}")
            failed += 1
            continue

        # b. 验证右侧面板是否切换到该联系人（必须用 name_in_right_panel，不用 url_match）
        safe_name = json.dumps(contact_name)
        verify_script = _JS_VERIFY_CHAT_PANEL.replace("{NAME_PLACEHOLDER}", safe_name)
        verify = await automation.execute_js(verify_script)
        verify_ok = isinstance(verify, dict) and verify.get("switched") and verify.get("method") != "url_match"
        if not verify_ok:
            logger.warning(f"[F6] 点击后右侧面板未切换到 {contact_name} (method={verify.get('method') if isinstance(verify, dict) else '?'})，重试")
            if not await click_contact(
                contact_name, fresh_contact.get("x", 0), fresh_contact.get("y", 0)
            ):
                logger.warning(f"[F6] 重试点击 {contact_name} 失败")
                failed += 1
                continue
            await asyncio.sleep(1)
            verify2 = await automation.execute_js(verify_script)
            verify2_ok = isinstance(verify2, dict) and verify2.get("switched") and verify2.get("method") != "url_match"
            if not verify2_ok:
                logger.warning(f"[F6] 两次点击后仍未切换到 {contact_name}，跳过")
                failed += 1
                continue
            logger.info(f"[F6] 重试后面板切换成功: {verify2.get('method')}")
        else:
            logger.info(f"[F6] 面板切换验证: {verify.get('method')}")

        # AI上下文判断 + 顺手回复
        try:
            msgs = await get_messages()
            # 找最后一条非系统消息
            last_msg = None
            if msgs:
                for m in reversed(msgs):
                    t = (m.get("text", "") or "").strip()
                    if t and len(t) > 2:
                        last_msg = m
                        break

            ai_decision = "PROCEED"
            if msgs:
                ai_decision = await _check_resume_appropriate(contact_name, msgs)

            if ai_decision == "FAREWELL":
                # 我们已发过祝福告别，不回复也不取简历
                logger.info(f"[F6] {contact_name}: 已告别过，跳过")
                _record_resume_op(db, contact_name, "farewell", btn_text="ai_farewell", boss_id=boss_id, user_id=user_id)
                skipped += 1
                details.append({"name": contact_name, "action": "skipped", "reason": "已祝福告别"})
                continue
            elif ai_decision == "REJECTION":
                # 对方表达不合适/拒绝 → 礼貌回复后跳过
                logger.info(f"[F6] {contact_name}: 对方拒绝，礼貌回复后跳过")
                await type_and_send("好的，了解了，打扰您了")
                await asyncio.sleep(1.5)
                _record_resume_op(db, contact_name, "rejected", btn_text="ai_rejection", boss_id=boss_id, user_id=user_id)
                skipped += 1
                details.append({"name": contact_name, "action": "skipped", "reason": "对方拒绝"})
                continue
            elif last_msg and not last_msg.get("isMe"):
                # 正常情况，对方最后发言 → 顺手回复再取简历
                quick_reply = "收到，我先看看您的简历，稍后详细回复您。"
                logger.info(f"[F6] {contact_name}: 对方最后发言，顺手回复")
                await type_and_send(quick_reply)
                await asyncio.sleep(1.5)
            else:
                logger.info(f"[F6] {contact_name}: 已回复过，直接取简历")
        except Exception as e:
            logger.debug(f"[F6] 上下文判断/顺手回复异常: {e}")

        if dry_run:
            details.append({"name": contact_name, "action": "would_download"})
            continue

        # 查找简历按钮
        try:
            btns = await automation.execute_js(_JS_FIND_RESUME_BTNS)
            btns = btns if isinstance(btns, list) else []
        except Exception:
            btns = []
        logger.info(f"[F6] {contact_name} 简历按钮: {len(btns)} 个")

        if not btns:
            details.append({"name": contact_name, "action": "no_resume_btn"})
            skipped += 1
            continue

        # 点击"附件简历"按钮
        btn = btns[0]
        logger.info(f"[F6] {contact_name} 点击: {btn.get('text')}")

        # 点击前先关引导（"我知道了"）
        guide = await automation.execute_js(_JS_CLICK_I_KNOW)
        if isinstance(guide, dict) and guide.get("dismissed"):
            logger.info(f"[F6] {contact_name}: 已关闭引导提示")
            await asyncio.sleep(0.5)

        try:
            ok = await automation.cdp_click_viewport(float(btn["x"]), float(btn["y"]))
            if not ok:
                logger.warning(f"[F6] CDP点击附件简历失败: ({btn['x']}, {btn['y']})")
                failed += 1
                continue
            await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"[F6] 点击附件简历失败: {e}")
            failed += 1
            continue

        # 检测弹出内容
        case_info = await _detect_resume_case()
        case_type = case_info.get("case_type", "unknown")
        logger.info(f"[F6] {contact_name} 弹出类型: {case_type}")

        if case_type == "pdf_preview":
            # Case-1: PDF预览 — 下载
            ok = await _handle_case1_download(
                contact_name, btn, db, details, downloaded, boss_id=boss_id, user_id=user_id
            )
            if ok:
                downloaded += 1
                resume_ops += 1
            else:
                failed += 1

        elif case_type == "request_popup":
            # Case-2: "向牛人请求简历" 弹窗 — 点确认
            await _handle_case2_confirm(
                contact_name, case_info, btn, db, details, boss_id=boss_id, user_id=user_id
            )
            resume_ops += 1

        elif case_type == "request_pending":
            # Case-3: "简历请求中" — 跳过
            logger.info(f"[F6] {contact_name}: 简历请求中，跳过")
            details.append({"name": contact_name, "action": "requested_pending"})
            _record_resume_op(db, contact_name, "requested_pending",
                              btn_text=btn.get("text"), boss_id=boss_id, user_id=user_id)

        elif case_type == "need_reply":
            # Case-4: "双方回复后可以请求" — 跳过
            logger.info(f"[F6] {contact_name}: 沟通不足，无法索取简历")
            details.append({"name": contact_name, "action": "need_reply"})
            _record_resume_op(db, contact_name, "need_reply",
                              btn_text=btn.get("text"), boss_id=boss_id, user_id=user_id)

        else:
            logger.info(f"[F6] {contact_name}: 无附件简历 (case={case_type})，跳过")
            details.append({"name": contact_name, "action": "no_attachment", "case_type": case_type})

        # 关闭预览 + 返回聊天列表
        try:
            await _close_resume_and_return()
        except Exception:
            pass

        # 定期截图
        if (downloaded + failed) > 0 and (downloaded + failed) % 3 == 0:
            try:
                await automation.screenshot(path=f"/tmp/f6_progress_{downloaded}.png")
            except Exception:
                pass

    # 最终截图
    try:
        await automation.screenshot(path="/tmp/f6_final.png")
    except Exception:
        pass

    return {
        "status": "completed",
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "total_scanned": i + 1,
        "resume_ops": resume_ops,
        "details": details,
    }


async def _close_resume_and_return() -> None:
    """关闭简历预览并等待聊天列表恢复稳定。

    多次 Escape + 渐增等待，确保 BOSS直聘 React UI 完成关闭动画和重渲染。
    联系人列表需要重新渲染后才能正确读取下一个联系人的坐标。
    """
    for i in range(3):
        try:
            await automation.press_key("Escape")
            await asyncio.sleep(0.8 + i * 0.4)  # 渐增: 0.8s, 1.2s, 1.6s
        except Exception:
            break
    # 确保 DOM 稳定后再处理下一个联系人
    await asyncio.sleep(2.0)


async def _detect_resume_case() -> Dict:
    """检测点击"附件简历"后的弹出内容类型。

    Returns:
        {case_type: str, ...} case_type 为以下之一:
          pdf_preview, request_popup, request_pending, need_reply, unknown
    """
    try:
        result = await automation.execute_js(_JS_DETECT_RESUME_CASE)
        if isinstance(result, dict):
            return result
    except Exception as e:
        logger.debug(f"[F6] Case检测失败: {e}")
    return {"case_type": "unknown"}


_CHAT_NOISE = {
    "没有更多了", "全部职位", "全部", "未读", "已读",
    "沟通中", "不限", "筛选", "发送", "我知道了",
    "求简历", "换电话", "换微信", "不合适",
    "刚刚活跃", "今日活跃", "在线",
    "同意", "拒绝", "接收", "忽略",
    "在线简历", "附件简历", "工作经历", "未填写工作经历",
    "沟通职位：", "期望：",
    "送达", "约面试",
    "简历请求已发送",
    "设置邮箱",
    "对方想发送附件简历给您，您是否同意",
    "对方想发送附件简历给您",
    "您可以在线预览牛人简历， 设置邮箱 后投递的简历会同时发送到您的邮箱。",
    "您可以在线预览牛人简历，设置邮箱后投递的简历会同时发送到您的邮箱。",
    "后投递的简历会同时发送到您的邮箱。",
}


def _is_chat_noise(text: str) -> bool:
    """判断文本是否为UI噪音（按钮、标签、系统提示等非对话内容）"""
    if not text or not text.strip():
        return True
    t = text.strip()
    if t in _CHAT_NOISE:
        return True
    if "撤回了一条消息" in t:
        return True
    if len(t) <= 8 and (t.endswith(("月", "日")) or ":" in t or t.isdigit()):
        return True
    import re
    if re.match(r'^\d{1,2}岁$', t): return True
    if re.match(r'^\d{1,2}年(应届生)?$', t): return True
    if t in ("本科", "硕士", "博士", "大专"): return True
    if re.match(r'^[一-龥]{2,8}(大学|学院)$', t): return True
    return False


async def _check_resume_appropriate(contact_name: str, msgs: list) -> str:
    """AI判断对话状态，返回 FAREWELL / REJECTION / PROCEED。

    FAREWELL: 招聘方已发祝福告别（如"祝你找到心仪的岗位"）→ 不回复、不取简历
    REJECTION: 候选人表达拒绝（如"不合适""不考虑"）→ 礼貌回复后跳过
    PROCEED: 正常情况 → 继续取简历
    """
    if not msgs:
        return "PROCEED"

    # 过滤UI噪音（按钮、系统提示等）
    lines = []
    for m in msgs:
        role = "招聘方" if m.get("isMe") else "候选人"
        text = (m.get("text", "") or "").strip()
        if not text or _is_chat_noise(text):
            continue
        lines.append(f"[{role}] {text}")
    lines = lines[-8:]  # 取最近8条有效消息
    if not lines:
        return "PROCEED"

    dialog = "\n".join(lines)
    logger.info(f"[F6] {contact_name} AI上下文判断，对话({len(lines)}条):\n{dialog}")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.DEEPSEEK_BASE_URL}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.DEEPSEEK_MODEL,
                    "messages": [
                        {"role": "system", "content": (
                            "你是招聘助手。根据对话判断是否应继续向候选人请求简历，只回复一个词。\n\n"
                            "FAREWELL — 招聘方明确发了结束对话的祝福告别，例如：\n"
                            '  "祝你找到心仪的岗位""祝你好运""我们不太合适，抱歉""感谢你的关注，再见"等\n\n'
                            "REJECTION — 候选人明确表示拒绝此岗位或不感兴趣，例如：\n"
                            '  "不合适""不考虑了""算了""已经找到工作了""不感兴趣"等\n'
                            '  注意：候选人说「不是做X」来描述自己的工作内容（如「我们不是做单一产品」）不属于拒绝\n\n'
                            "PROCEED — 以上两种情况都不符合，正常沟通中"
                        )},
                        {"role": "user", "content": dialog},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 10,
                },
            )
        if resp.status_code == 200:
            result = resp.json()["choices"][0]["message"]["content"].strip().upper()
            if result in ("FAREWELL", "REJECTION", "PROCEED"):
                logger.info(f"[F6] {contact_name}: AI判断 → {result}")
                return result
    except Exception as e:
        logger.debug(f"[F6] AI上下文判断失败: {e}，默认继续")
    return "PROCEED"


async def _handle_case1_download(
    contact_name: str,
    btn: Dict,
    db: Database,
    details: list,
    current_downloaded: int,
    boss_id: str = None,
    user_id: int = None,
) -> bool:
    """Case-1: PDF预览弹出 → 查找下载按钮 → CDP事件确认下载。

    Returns:
        True 表示下载成功（CDP事件或目录轮询确认），False 表示失败。
    """
    try:
        dl = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
    except Exception:
        dl = None

    if dl and dl.get("found"):
        try:
            # 点击下载按钮
            ok = await automation.cdp_click_viewport(float(dl["x"]), float(dl["y"]))
            if not ok:
                logger.warning(f"[F6] CDP点击下载按钮失败")

            # Fix 1: 使用 CDP事件+目录轮询双重确认下载
            rdir = _resumes_dir(user_id)
            before_snap = set(rdir.iterdir()) if rdir.exists() else set()
            await asyncio.sleep(0.3)
            dl_result = await automation.wait_for_download(
                str(rdir), timeout=30.0, before_files=before_snap
            )
            file_verified = dl_result.get("status") == "downloaded"
            verify_method = dl_result.get("method", "unknown")

            if file_verified:
                # 同步到 candidates 表
                _update_candidate_resume(
                    db, contact_name,
                    resume_path=dl_result.get("path", ""),
                    boss_id=boss_id,
                )
                logger.info(
                    f"[F6] {contact_name} 简历下载成功 "
                    f"({dl_result.get('size', 0)} bytes, method={verify_method})"
                )
            else:
                logger.warning(
                    f"[F6] {contact_name} 下载未确认: "
                    f"{dl_result.get('message', 'unknown')} (method={verify_method})"
                )

            details.append({
                "name": contact_name, "action": "downloaded",
                "btn_type": btn.get("text"),
                "file_verified": file_verified,
                "verify_method": verify_method,
            })
            db.insert_resume_op(
                boss_id=boss_id,
                candidate_name=contact_name,
                action="downloaded",
                resume_downloaded=file_verified,
                detail=json.dumps({
                    "case": "pdf_preview",
                    "btn": btn.get("text"),
                    "file_verified": file_verified,
                    "verify_method": verify_method,
                    "download_result": dl_result,
                    "time": datetime.now().isoformat(),
                }),
                user_id=user_id,
            )
            return file_verified
        except Exception as e:
            logger.warning(f"[F6] 下载失败: {e}")
            details.append({"name": contact_name, "action": "download_failed"})
            db.insert_resume_op(
                boss_id=boss_id, candidate_name=contact_name, action="download_failed",
                resume_downloaded=False, detail=str(e), user_id=user_id,
            )
            return False
    else:
        # PDF预览但没有下载按钮 — 可能是在线简历渲染
        details.append({
            "name": contact_name, "action": "online_resume_viewed",
            "btn_type": btn.get("text"),
        })
        db.insert_resume_op(
            boss_id=boss_id, candidate_name=contact_name, action="viewed",
            resume_downloaded=False,
            detail=json.dumps({
                "case": "pdf_preview_no_download_btn",
                "btn": btn.get("text"),
                "time": datetime.now().isoformat(),
            }),
        )
        return False


async def _handle_case2_confirm(
    contact_name: str,
    case_info: Dict,
    btn: Dict,
    db: Database,
    details: list,
    boss_id: str = None,
    user_id: int = None,
) -> None:
    """Case-2: "向牛人请求简历"弹窗 → 点确认 → 记录已请求。"""
    confirm_x = case_info.get("x")
    confirm_y = case_info.get("y")

    if confirm_x is not None and confirm_y is not None:
        # 先关BOSS引导提示，避免遮挡确认按钮
        guide = await automation.execute_js(_JS_CLICK_I_KNOW)
        if isinstance(guide, dict) and guide.get("dismissed"):
            logger.info(f"[F6] {contact_name}: 已关闭引导提示")
            await asyncio.sleep(0.5)
        try:
            ok = await automation.cdp_click_viewport(float(confirm_x), float(confirm_y))
            if not ok:
                logger.warning(f"[F6] {contact_name}: CDP点击确认按钮失败")
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"[F6] {contact_name}: 确认按钮点击失败: {e}")

    # 记录已请求简历
    details.append({
        "name": contact_name, "action": "requested",
        "btn_type": btn.get("text"),
    })
    db.insert_resume_op(
        boss_id=boss_id, candidate_name=contact_name, action="requested",
        resume_downloaded=False,
        detail=json.dumps({
            "case": "request_popup",
            "btn": btn.get("text"),
            "time": datetime.now().isoformat(),
        }),
        user_id=user_id,
    )


async def _click_download(
    contact_name: str,
    btn: Dict,
    db: Database,
    details: list,
    boss_id: str = None,
    user_id: int = None,
) -> None:
    """旧逻辑兜底: 尝试点击下载按钮。"""
    rdir = _resumes_dir(user_id)
    existing_files = set(rdir.iterdir()) if rdir.exists() else set()
    try:
        dl = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
        if dl and dl.get("found"):
            await automation.click(int(dl["x"]), int(dl["y"]))
            await asyncio.sleep(4)

            new_files = set(rdir.iterdir()) if rdir.exists() else set()
            file_appeared = bool(new_files - existing_files)

            details.append({
                "name": contact_name, "action": "downloaded",
                "btn_type": btn.get("text"), "file_verified": file_appeared,
            })
            db.insert_resume_op(
                boss_id=boss_id, candidate_name=contact_name, action="downloaded",
                resume_downloaded=True,
                detail=json.dumps({
                    "case": "unknown_fallback",
                    "file_verified": file_appeared,
                    "time": datetime.now().isoformat(),
                }),
                user_id=user_id,
            )
    except Exception as e:
        logger.warning(f"[F6] 兜底下载失败: {e}")


def _record_resume_op(
    db: Database,
    contact_name: str,
    action: str,
    btn_text: str = None,
    boss_id: str = None,
    user_id: int = None,
) -> None:
    """安全记录简历操作到DB。"""
    try:
        db.insert_resume_op(
            boss_id=boss_id,
            candidate_name=contact_name,
            action=action,
            resume_downloaded=False,
            detail=json.dumps({
                "btn": btn_text,
                "time": datetime.now().isoformat(),
            }),
            user_id=user_id,
        )
    except Exception as exc:
        logger.warning(f"[F6] DB记录失败 ({contact_name} {action}): {exc}")
