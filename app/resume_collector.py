"""
BOSS直聘 · 简历收集器 v2.2
基于 nodriver CDP 的简历自动获取

修复:
- CDP 下载拦截: 文件实际保存到 data/resumes/
- 登录检查: 开始前验证登录状态
- 精简导航: 跳过不必要的首页跳转
- 收紧选择器: 减少误匹配
- 4种Case区分: PDF预览/请求弹窗/请求中/沟通不足
"""
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict

from app.automation import automation
from app.chat_nav import navigate_to_chat, get_contacts
from app.database import Database
from app.logging_config import logger

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
RESUMES_DIR = DATA_DIR / "resumes"


# ========== JS 提取脚本（收紧版） ==========

_JS_FIND_RESUME_BTNS = """
(function() {
    // 在聊天详情区域查找简历相关按钮（限制在右侧面板）
    var chatPanel = document.querySelector(
        '[class*="chat-detail"], [class*="chat-content"], [class*="message-panel"], '
        + '[class*="dialog-content"], [class*="right-panel"]'
    );
    var root = chatPanel || document.body;
    var btns = root.querySelectorAll('button, a, span, [class*="btn"], [class*="resume"]');
    var results = [];
    for (var i = 0; i < btns.length; i++) {
        var t = (btns[i].innerText || '').trim();
        // 精确匹配: 只取"在线简历"和"附件简历"，不泛匹配"简历"
        if (t === '在线简历' || t === '附件简历' || t === '查看简历' || t === '查看附件') {
            var r = btns[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                results.push({text: t, x: r.x + r.width/2, y: r.y + r.height/2, type: t});
            }
        }
    }
    return results;
})()
"""

_JS_FIND_DOWNLOAD_BTN = """
(function() {
    // 在简历预览中找到下载按钮
    var btns = document.querySelectorAll('button, a, [class*="download"], [class*="save"]');
    for (var i = 0; i < btns.length; i++) {
        var t = (btns[i].innerText || '').trim();
        if (t === '下载' || t === '保存' || t === '导出' || t === '下载简历') {
            var r = btns[i].getBoundingClientRect();
            if (r.width > 0 && r.height > 0) {
                return {found: true, x: r.x + r.width/2, y: r.y + r.height/2, text: t};
            }
        }
    }
    // Fallback: 查找带 download 属性的元素
    var links = document.querySelectorAll('a[download]');
    for (var j = 0; j < links.length; j++) {
        var rr = links[j].getBoundingClientRect();
        if (rr.width > 0 && rr.height > 0) {
            return {found: true, x: rr.x + rr.width/2, y: rr.y + rr.height/2, text: 'download_link'};
        }
    }
    return {found: false};
})()
"""

# 点击"附件简历"后检测弹出内容类型
_JS_DETECT_RESUME_CASE = """
(function() {
    // Case-1: PDF预览 (优先检测 — PDF元素存在时直接判定，避免被覆盖文本干扰)
    var pdfElements = document.querySelectorAll(
        'embed[type="application/pdf"], iframe[src*="pdf"], [class*="pdf"], [data-type="pdf"]'
    );
    if (pdfElements.length > 0) {
        return {case_type: 'pdf_preview'};
    }

    var allText = document.body.innerText || '';

    // Case-2: "向牛人请求简历" 弹窗
    var confirmBtns = document.querySelectorAll('button, [class*="btn"]');
    for (var i = 0; i < confirmBtns.length; i++) {
        var t = (confirmBtns[i].innerText || '').trim();
        if (t === '确认' || t === '确定') {
            if (allText.indexOf('请求简历') >= 0 || allText.indexOf('向牛人') >= 0) {
                var r = confirmBtns[i].getBoundingClientRect();
                return {
                    case_type: 'request_popup',
                    x: r.x + r.width/2, y: r.y + r.height/2,
                    text: t
                };
            }
        }
    }
    // Case-3: "附件简历请求中"
    if (allText.indexOf('请求中') >= 0 || allText.indexOf('简历请求') >= 0) {
        return {case_type: 'request_pending'};
    }
    // Case-4: "双方回复后可以向TA请求"
    if (allText.indexOf('双方回复后') >= 0 || allText.indexOf('回复后可以') >= 0) {
        return {case_type: 'need_reply'};
    }
    // 未知
    return {case_type: 'unknown'};
})()
"""


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

    # 登录检查 — 防止在登录页误操作
    login_status = await automation.check_login()
    if not login_status.get("logged_in"):
        return {"status": "error", "message": "BOSS直聘未登录，请先在VNC中扫码登录"}

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

    # 初始化数据库
    db = Database()
    db.connect()
    db.init_tables()

    downloaded = 0
    skipped = 0
    failed = 0
    details = []

    # 获取联系人列表
    contacts = await get_contacts()

    if not contacts:
        logger.info("[F6] 未找到联系人，尝试备用导航...")
        try:
            await automation.navigate("https://www.zhipin.com/web/chat/index")
            await asyncio.sleep(4)
            contacts = await get_contacts()
        except Exception as e:
            logger.warning(f"[F6] 备用联系人提取失败: {e}")

    logger.info(f"[F6] 找到 {len(contacts)} 个联系人，上限 {max_count}")

    for i, contact in enumerate(contacts[:max_count]):
        contact_name = (contact.get("name", "") or contact.get("text", "") or f"contact_{i}").strip()
        logger.info(f"[F6] 处理 ({i+1}/{min(len(contacts), max_count)}): {contact_name}")

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

        # 点击联系人
        try:
            await automation.click(int(contact["x"]), int(contact["y"]))
            await asyncio.sleep(2)
        except Exception as e:
            logger.warning(f"[F6] 点击失败: {e}")
            failed += 1
            continue

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

        # 点击第一个简历按钮
        btn = btns[0]
        try:
            await automation.click(int(btn["x"]), int(btn["y"]))
            await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"[F6] 点击简历按钮失败: {e}")
            failed += 1
            continue

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

        # 关闭预览
        try:
            await automation.press_key("Escape")
            await asyncio.sleep(1)
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
    """Case-1: PDF预览弹出 → 查找下载按钮 → 下载文件。

    Returns:
        True 表示下载成功（或按钮已点击），False 表示失败。
    """
    existing_files = set(RESUMES_DIR.iterdir()) if RESUMES_DIR.exists() else set()

    try:
        dl = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
    except Exception:
        dl = None

    if dl and dl.get("found"):
        try:
            await automation.click(int(dl["x"]), int(dl["y"]))
            await asyncio.sleep(4)

            new_files = set(RESUMES_DIR.iterdir()) if RESUMES_DIR.exists() else set()
            file_appeared = bool(new_files - existing_files)

            if file_appeared:
                logger.info(f"[F6] {contact_name} 简历下载成功（新文件检测）")
            else:
                logger.info(f"[F6] {contact_name} 下载按钮已点击（文件可能在Chrome默认目录）")

            details.append({
                "name": contact_name, "action": "downloaded",
                "btn_type": btn.get("text"), "file_verified": file_appeared,
            })
            db.insert_resume_op(
                candidate_name=contact_name,
                action="downloaded",
                resume_downloaded=True,
                detail=json.dumps({
                    "case": "pdf_preview",
                    "btn": btn.get("text"),
                    "file_verified": file_appeared,
                    "time": datetime.now().isoformat(),
                }),
            )
        except Exception as e:
            logger.warning(f"[F6] 下载失败: {e}")
            details.append({"name": contact_name, "action": "download_failed"})
            db.insert_resume_op(
                candidate_name=contact_name, action="download_failed",
                resume_downloaded=False, detail=str(e),
            )
            return False
        return True
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
            await automation.click(int(confirm_x), int(confirm_y))
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
                    await automation.click(int(dl["x"]), int(dl["y"]))
                    await asyncio.sleep(4)
                    details.append({
                        "name": contact_name,
                        "action": "downloaded_after_confirm",
                        "btn_type": btn.get("text"),
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
