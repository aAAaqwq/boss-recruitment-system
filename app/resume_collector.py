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

from app.automation import automation
from app.chat_nav import navigate_to_chat, get_contacts, click_contact, check_limit_popup, dismiss_popup, click_communicating_filter
from app.database import Database
from app.logging_config import logger

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
RESUMES_DIR = DATA_DIR / "resumes"


# ========== JS 提取脚本（主文档优先，兼容非iframe聊天页） ==========

_JS_FIND_RESUME_BTNS = """
(function() {
    var vw = Math.max(window.innerWidth, 1000);
    function findInDoc(doc) {
        var rightArea = null;
        var panels = doc.querySelectorAll('div, section');
        for (var p = 0; p < panels.length; p++) {
            var pr = panels[p].getBoundingClientRect();
            if (pr.x > vw * 0.35 && pr.width > 200 && pr.height > 300) {
                rightArea = panels[p]; break;
            }
        }
        var root = rightArea || doc.body;
        var btns = root.querySelectorAll('button, a, span, div[class*="btn"], div[class*="resume"]');
        var results = [];
        for (var i = 0; i < btns.length; i++) {
            var t = (btns[i].innerText || '').trim();
            if (t === '在线简历' || t === '附件简历' || t === '查看简历' || t === '查看附件') {
                var r = btns[i].getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    results.push({text: t, x: r.x + r.width/2, y: r.y + r.height/2, type: t});
                }
            }
        }
        // 优先"附件简历"/"查看附件"
        results.sort(function(a, b) {
            var pa = (a.text === '附件简历' || a.text === '查看附件') ? 0 : 1;
            var pb = (b.text === '附件简历' || b.text === '查看附件') ? 0 : 1;
            return pa - pb;
        });
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

# 逐次提取单个联系人坐标 — 优先主文档 .geek-item-wrap（与 get_contacts 一致）
_JS_FIND_CONTACT_BY_NAME = """
(function() {
    var targetName = {NAME_PLACEHOLDER};
    var vw = Math.max(window.innerWidth, 1000);

    function findInDoc(doc) {
        // 优先用 .geek-item-wrap（与 get_contacts 保持一致的选择器）
        var items = doc.querySelectorAll('.geek-item-wrap');
        if (items.length > 0) {
            for (var i = 0; i < items.length; i++) {
                var t = (items[i].innerText || '').trim();
                if (t.indexOf(targetName) >= 0) {
                    var r = items[i].getBoundingClientRect();
                    if (r.width > 80 && r.height > 30) {
                        var parts = t.split(/[\\n]+/).filter(function(l) { return l.trim().length > 0; });
                        var name = parts[0] || '';
                        var topEl = items[i].querySelector('.geek-item-top');
                        if (topEl) {
                            var topText = (topEl.innerText || '').trim();
                            var topParts = topText.split(/[\\n]+/);
                            if (topParts[0]) name = topParts[0].trim();
                        }
                        return {
                            name: name,
                            text: t,
                            x: r.x + r.width / 2,
                            y: r.y + r.height / 2,
                            visible: r.y > 0 && r.y < window.innerHeight
                        };
                    }
                }
            }
        }
        // 回退: 扫描左侧区域所有 div/li/a
        var leftBoundary = vw * 0.45;
        var allEls = doc.querySelectorAll('div, li, a');
        for (var j = 0; j < allEls.length; j++) {
            var rr = allEls[j].getBoundingClientRect();
            var tt = (allEls[j].innerText || '').trim();
            if (rr.x >= 0 && rr.x < leftBoundary
                && rr.width > 60 && rr.height > 20
                && tt.length > 1 && tt.indexOf(targetName) >= 0) {
                return {
                    name: (tt.split('\\n')[0] || '').trim(),
                    text: tt,
                    x: rr.x + rr.width / 2,
                    y: rr.y + rr.height / 2,
                    visible: rr.y > 0 && rr.y < window.innerHeight
                };
            }
        }
        return null;
    }

    // 先搜主文档（BOSS直聘聊天页在主文档中）
    var result = findInDoc(document);
    if (result) return result;

    // 回退: iframe
    var iframe = document.querySelector('.frame-box iframe') || document.querySelector('iframe');
    if (iframe && iframe.contentDocument) {
        var ifResult = findInDoc(iframe.contentDocument);
        if (ifResult) return ifResult;
    }
    return null;
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


def _update_candidate_resume(db: Database, candidate_name: str, resume_path: str = "", boss_id: str = "") -> None:
    """更新 candidates 表中的简历路径和状态（安全写入，失败不抛异常）。"""
    try:
        db.cursor.execute(
            """INSERT INTO candidates (boss_id, candidate_name, status, resume_path, updated_at)
               VALUES (?, ?, 'resume_downloaded', ?, datetime('now'))
               ON CONFLICT(boss_id) DO UPDATE SET
               resume_path = excluded.resume_path,
               status = 'resume_downloaded',
               updated_at = excluded.updated_at""",
            (boss_id or candidate_name, candidate_name, resume_path),
        )
        db.conn.commit()
        logger.info(f"[F6] candidates表已更新: {candidate_name} resume={resume_path}")
    except Exception as e:
        logger.debug(f"[F6] 更新candidates表忽略: {e}")


async def collect_resumes(max_count: int = 10, dry_run: bool = False) -> Dict:
    """收集简历主流程

    Args:
        max_count: 最多处理人数
        dry_run: 干跑模式（只扫描不操作）

    Returns:
        {status, downloaded, skipped, failed, total_scanned, details: [...]}
    """
    RESUMES_DIR.mkdir(parents=True, exist_ok=True)

    # 确保浏览器连接
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接，请先打开BOSS直聘"}

    # 注意: 不在此处调用 check_login()，因为它会导航到 /web/chat/recommend，
    # 然后 navigate_to_chat() 再次导航到同一 URL，双重导航干扰 BOSS直聘的
    # 异步联系人列表加载，导致 get_contacts() 返回 0。

    # 启用 CDP 下载拦截 — 文件自动保存到 data/resumes/
    if not dry_run:
        dl_result = await automation.enable_download_interception(str(RESUMES_DIR))
        logger.info(f"[F6] CDP下载拦截: {dl_result.get('status')} → {RESUMES_DIR}")

    # 导航到聊天页
    nav_result = await navigate_to_chat()
    if nav_result.get("status") != "ok":
        # 备用: 直接导航 /web/chat/index
        logger.info("[F6] navigate_to_chat 失败，尝试备用导航 /web/chat/index")
        nav2 = await automation.navigate("https://www.zhipin.com/web/chat/index")
        if nav2.get("status") == "error":
            return {"status": "error", "message": "无法访问聊天页，可能需登录"}
        await asyncio.sleep(3)

    # 筛选"沟通中" — 只有沟通过的联系人才有简历权限
    comm_result = await click_communicating_filter()
    if comm_result.get("status") == "ok":
        await asyncio.sleep(2)
        contacts = await get_contacts()
    else:
        logger.warning("[F6] '沟通中'筛选未命中，使用全部联系人")
        contacts = nav_result.get("contacts", [])

    if not contacts:
        logger.info("[F6] 未找到联系人，尝试备用提取...")
        await asyncio.sleep(3)
        contacts = await get_contacts()

    # 初始化数据库
    db = Database()
    db.connect()
    db.init_tables()

    downloaded = 0
    skipped = 0
    failed = 0
    details = []

    # 按 hasUnread 排序 — 未读优先（最可能发了简历）
    contacts.sort(key=lambda c: (c.get("hasUnread", False), len(c.get("text", ""))), reverse=True)
    unread_count = sum(1 for c in contacts if c.get("hasUnread"))
    logger.info(f"[F6] 找到 {len(contacts)} 个联系人（{unread_count} 未读），上限 {max_count}")

    for i, contact in enumerate(contacts[:max_count]):
        contact_name = (contact.get("name", "") or contact.get("text", "") or f"contact_{i}").strip()
        logger.info(f"[F6] 处理 ({i+1}/{min(len(contacts), max_count)}): {contact_name}"
                    f" {'[未读]' if contact.get('hasUnread') else ''}")

        # 检查去重
        try:
            existing = db.get_resume_ops(contact_name)
        except Exception:
            existing = []
        if existing:
            already_downloaded = any(
                r.get("resume_downloaded") or r.get("action") == "downloaded"
                for r in existing
            )
            if already_downloaded:
                skipped += 1
                details.append({"name": contact_name, "action": "skipped", "reason": "已下载过"})
                logger.info(f"[F6] 跳过 {contact_name}: 已下载")
                continue

        # Fix 2: 逐次提取坐标 — 每次点击前重新查找联系人位置
        fresh_contact = await _refind_contact(contact_name)
        if not fresh_contact:
            logger.warning(f"[F6] 逐次查找联系人失败: {contact_name}, 回退到原始坐标")
            fresh_contact = contact

        # 0. 联系人不可见 → 滚动左侧列表使其落入视口
        if not fresh_contact.get("visible", True):
            logger.info(f"[F6] {contact_name} 在 y={fresh_contact.get('y')}，滚动列表使其可见")
            await _scroll_contact_into_view(contact_name, fresh_contact)
            await asyncio.sleep(1)
            # 重新获取坐标
            fresh_contact = await _refind_contact(contact_name)
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

        # 点击第一个简历按钮（使用 CDP viewport 点击）
        btn = btns[0]
        logger.info(f"[F6] {contact_name} 点击简历按钮: {btn.get('text')} ({btn.get('type')})")
        try:
            ok = await automation.cdp_click_viewport(float(btn["x"]), float(btn["y"]))
            if not ok:
                logger.warning(f"[F6] CDP点击简历按钮失败: ({btn['x']}, {btn['y']})")
                failed += 1
                continue
            await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"[F6] 点击简历按钮失败: {e}")
            failed += 1
            continue

        # 弹窗/模态框出现后，扫描是否有"附件简历"入口
        # 处理"在线简历"弹窗上也有"附件简历"按钮的情况
        if btn.get("text") != "附件简历" and btn.get("text") != "查看附件":
            try:
                modal_btn = await automation.execute_js(_JS_FIND_MODAL_ATTACHMENT)
                if isinstance(modal_btn, dict) and modal_btn.get("found"):
                    logger.info(f"[F6] {contact_name} 弹窗上发现附件入口: {modal_btn.get('text')}")
                    await automation.cdp_click_viewport(
                        float(modal_btn["x"]), float(modal_btn["y"])
                    )
                    await asyncio.sleep(3)
                    # 更新 btn 为实际点击的附件按钮
                    btn = {"text": modal_btn.get("text", "附件简历"), "x": modal_btn["x"], "y": modal_btn["y"]}
            except Exception as e:
                logger.debug(f"[F6] 扫描弹窗附件按钮失败: {e}")

        # 检测弹出内容类型 — 区分 4 种 Case
        case_info = await _detect_resume_case()
        case_type = case_info.get("case_type", "unknown")
        logger.info(f"[F6] {contact_name} 弹出类型: {case_type}")

        if case_type == "pdf_preview":
            # Case-1: PDF预览 — 下载
            ok = await _handle_case1_download(
                contact_name, btn, db, details, downloaded
            )
            if ok:
                downloaded += 1
            else:
                failed += 1

        elif case_type == "request_popup":
            # Case-2: "向牛人请求简历" 弹窗 — 点确认
            await _handle_case2_confirm(
                contact_name, case_info, btn, db, details
            )

        elif case_type == "request_pending":
            # Case-3: "附件简历请求中" — 跳过
            logger.info(f"[F6] {contact_name}: 简历请求中，跳过")
            details.append({"name": contact_name, "action": "requested_pending"})
            _record_resume_op(db, contact_name, "requested_pending",
                              btn_text=btn.get("text"))

        elif case_type == "need_reply":
            # Case-4: "双方回复后可以向TA请求" — 跳过
            logger.info(f"[F6] {contact_name}: 沟通不足，无法索取简历")
            details.append({"name": contact_name, "action": "need_reply"})
            _record_resume_op(db, contact_name, "need_reply",
                              btn_text=btn.get("text"))

        elif case_type == "online_resume":
            # Case-5: 在线简历模态框 — 只有结构化数据，无附件可下载
            # 先尝试在模态框上再找一次下载/附件按钮（可能之前没扫到）
            dl = None
            try:
                dl = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
            except Exception:
                pass
            if dl and dl.get("found"):
                logger.info(f"[F6] {contact_name}: 在线简历弹窗上找到下载按钮，尝试下载")
                try:
                    await automation.cdp_click_viewport(float(dl["x"]), float(dl["y"]))
                    dl_result = await automation.wait_for_download(str(RESUMES_DIR), timeout=30.0)
                    file_verified = dl_result.get("status") == "downloaded"
                    if file_verified:
                        _update_candidate_resume(db, contact_name, resume_path=dl_result.get("path", ""), boss_id=contact_name)
                        downloaded += 1
                        details.append({"name": contact_name, "action": "downloaded", "btn_type": btn.get("text"),
                                        "file_verified": True, "case": "online_resume_then_download"})
                        db.insert_resume_op(candidate_name=contact_name, action="downloaded", resume_downloaded=True,
                                            detail=json.dumps({"case": "online_resume_then_download", "time": datetime.now().isoformat()}))
                    else:
                        details.append({"name": contact_name, "action": "online_resume_viewed", "btn_type": btn.get("text")})
                        _record_resume_op(db, contact_name, "online_resume_viewed", btn_text=btn.get("text"))
                except Exception:
                    details.append({"name": contact_name, "action": "online_resume_viewed", "btn_type": btn.get("text")})
                    _record_resume_op(db, contact_name, "online_resume_viewed", btn_text=btn.get("text"))
            else:
                logger.info(f"[F6] {contact_name}: 仅在线简历（无附件），截图记录")
                details.append({"name": contact_name, "action": "online_resume_viewed", "btn_type": btn.get("text")})
                _record_resume_op(db, contact_name, "online_resume_viewed", btn_text=btn.get("text"))

        else:
            # 未知: 尝试查找下载按钮，兼容旧逻辑
            dl = None
            try:
                dl = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
            except Exception:
                pass

            if dl and dl.get("found"):
                downloaded += 1
                await _click_download(contact_name, btn, db, details)
            else:
                details.append({
                    "name": contact_name, "action": "unknown_case",
                    "btn_type": btn.get("text"),
                })
                _record_resume_op(db, contact_name, "requested",
                                  btn_text=btn.get("text"))

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
        "total_scanned": len(contacts[:max_count]),
        "details": details,
    }


_JS_SCROLL_TO_CONTACT = """
(function() {
    var targetName = {NAME_PLACEHOLDER};
    // 找到联系人列表容器并滚动使目标可见
    var items = document.querySelectorAll('.geek-item-wrap');
    for (var i = 0; i < items.length; i++) {
        var t = (items[i].innerText || '').trim();
        if (t.indexOf(targetName) >= 0) {
            items[i].scrollIntoView({block: 'nearest', behavior: 'instant'});
            return {scrolled: true, name: (t.split('\\n')[0] || '').trim()};
        }
    }
    return {scrolled: false};
})()
"""

async def _scroll_contact_into_view(contact_name: str, fresh_contact: Dict) -> None:
    """滚动联系人列表使目标联系人落入视口，然后重新查找坐标。"""
    try:
        safe_name = json.dumps(contact_name)
        script = _JS_SCROLL_TO_CONTACT.replace("{NAME_PLACEHOLDER}", safe_name)
        result = await automation.execute_js(script)
        if isinstance(result, dict) and result.get("scrolled"):
            logger.info(f"[F6] 已滚动联系人列表: {contact_name}")
    except Exception as e:
        logger.debug(f"[F6] 滚动联系人失败: {e}")


async def _refind_contact(contact_name: str) -> Optional[Dict]:
    """逐次提取单个联系人的最新坐标（解决一次性提取过期问题）。

    每次点击前调用，通过姓名在聊天列表中重新查找，返回视口坐标。
    """
    try:
        safe_name = json.dumps(contact_name)  # JSON 编码防止 JS 注入
        script = _JS_FIND_CONTACT_BY_NAME.replace("{NAME_PLACEHOLDER}", safe_name)
        result = await automation.execute_js(script)
        if isinstance(result, dict) and result.get("x") is not None:
            return result
    except Exception as e:
        logger.debug(f"[F6] _refind_contact({contact_name}) 失败: {e}")
    return None


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


async def _handle_case1_download(
    contact_name: str,
    btn: Dict,
    db: Database,
    details: list,
    current_downloaded: int,
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
            dl_result = await automation.wait_for_download(
                str(RESUMES_DIR), timeout=30.0
            )
            file_verified = dl_result.get("status") == "downloaded"
            verify_method = dl_result.get("method", "unknown")

            if file_verified:
                # 同步到 candidates 表
                _update_candidate_resume(
                    db, contact_name,
                    resume_path=dl_result.get("path", ""),
                    boss_id=contact_name,
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
            )
            return file_verified
        except Exception as e:
            logger.warning(f"[F6] 下载失败: {e}")
            details.append({"name": contact_name, "action": "download_failed"})
            db.insert_resume_op(
                candidate_name=contact_name, action="download_failed",
                resume_downloaded=False, detail=str(e),
            )
            return False
    else:
        # PDF预览但没有下载按钮 — 可能是在线简历渲染
        details.append({
            "name": contact_name, "action": "online_resume_viewed",
            "btn_type": btn.get("text"),
        })
        db.insert_resume_op(
            candidate_name=contact_name, action="viewed",
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
) -> None:
    """Case-2: "向牛人请求简历"弹窗 → 点确认 → 检测是否有PDF。"""
    confirm_x = case_info.get("x")
    confirm_y = case_info.get("y")

    if confirm_x is not None and confirm_y is not None:
        try:
            ok = await automation.cdp_click_viewport(float(confirm_x), float(confirm_y))
            if not ok:
                logger.warning(f"[F6] CDP点击确认按钮失败")
            await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"[F6] 确认按钮点击失败: {e}")

        # 确认后PDF可能弹出 → 再检测一次
        post_case = await _detect_resume_case()
        if post_case.get("case_type") == "pdf_preview":
            logger.info(f"[F6] {contact_name}: 确认后PDF弹出，尝试下载")
            try:
                dl = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
                if dl and dl.get("found"):
                    ok = await automation.cdp_click_viewport(float(dl["x"]), float(dl["y"]))
                    if not ok:
                        logger.warning(f"[F6] CDP点击下载按钮(confirm后)失败")
                    await asyncio.sleep(4)
                    # 确认下载
                    dl_result = await automation.wait_for_download(str(RESUMES_DIR), timeout=15.0)
                    file_verified = dl_result.get("status") == "downloaded"
                    if file_verified:
                        _update_candidate_resume(
                            db, contact_name,
                            resume_path=dl_result.get("path", ""),
                            boss_id=contact_name,
                        )
                    details.append({
                        "name": contact_name,
                        "action": "downloaded_after_confirm",
                        "btn_type": btn.get("text"),
                        "file_verified": file_verified,
                    })
                    db.insert_resume_op(
                        candidate_name=contact_name, action="downloaded",
                        resume_downloaded=True,
                        detail=json.dumps({
                            "case": "request_popup_then_pdf",
                            "time": datetime.now().isoformat(),
                        }),
                    )
                    return
            except Exception:
                pass

    # 确认后无PDF → 记录为已请求
    details.append({
        "name": contact_name, "action": "requested",
        "btn_type": btn.get("text"),
    })
    db.insert_resume_op(
        candidate_name=contact_name, action="requested",
        resume_downloaded=False,
        detail=json.dumps({
            "case": "request_popup",
            "btn": btn.get("text"),
            "time": datetime.now().isoformat(),
        }),
    )


async def _click_download(
    contact_name: str,
    btn: Dict,
    db: Database,
    details: list,
) -> None:
    """旧逻辑兜底: 尝试点击下载按钮。"""
    existing_files = set(RESUMES_DIR.iterdir()) if RESUMES_DIR.exists() else set()
    try:
        dl = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
        if dl and dl.get("found"):
            await automation.click(int(dl["x"]), int(dl["y"]))
            await asyncio.sleep(4)

            new_files = set(RESUMES_DIR.iterdir()) if RESUMES_DIR.exists() else set()
            file_appeared = bool(new_files - existing_files)

            details.append({
                "name": contact_name, "action": "downloaded",
                "btn_type": btn.get("text"), "file_verified": file_appeared,
            })
            db.insert_resume_op(
                candidate_name=contact_name, action="downloaded",
                resume_downloaded=True,
                detail=json.dumps({
                    "case": "unknown_fallback",
                    "file_verified": file_appeared,
                    "time": datetime.now().isoformat(),
                }),
            )
    except Exception as e:
        logger.warning(f"[F6] 兜底下载失败: {e}")


def _record_resume_op(
    db: Database,
    contact_name: str,
    action: str,
    btn_text: str = None,
) -> None:
    """安全记录简历操作到DB。"""
    try:
        db.insert_resume_op(
            candidate_name=contact_name,
            action=action,
            resume_downloaded=False,
            detail=json.dumps({
                "btn": btn_text,
                "time": datetime.now().isoformat(),
            }),
        )
    except Exception as exc:
        logger.warning(f"[F6] DB记录失败 ({contact_name} {action}): {exc}")
