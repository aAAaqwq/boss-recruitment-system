"""已获取简历下载 — 针对已同意分享简历的联系人，直接下载。

与 resume_collector.py（申请简历）不同，本模块处理的是简历请求已被接受、
对方已上传附件简历的情况。流程更简单：点联系人 → 点附件简历 →
PDF预览中出现灰色下载箭头 → 点击下载 → 关闭预览 → 下一个。
"""
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from app.automation import automation, cancel_event
from app.chat_nav import (
    navigate_to_chat, get_contacts, click_contact,
    check_limit_popup, dismiss_popup,
    click_received_resume_filter,
    refind_contact, scroll_contact_into_view,
)
from app.database import Database
from app.logging_config import logger

RESUMES_DIR = Path(__file__).parent.parent / "data" / "resumes"

def _resumes_dir(user_id: int = None) -> Path:
    """按用户隔离的简历目录"""
    if user_id:
        d = RESUMES_DIR / str(user_id)
    else:
        d = RESUMES_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d

# 在 attachment-resume-btns 工具栏中查找下载按钮（基于真实DOM扫描）
# 下载图标: SVG use xlink:href="#icon-attacthment-download"，位于主文档 .attachment-resume-btns 内
_JS_FIND_PDF_DOWNLOAD_ARROW = """
(function() {
    // BOSS直聘PDF预览: 下载按钮在 .attachment-resume-btns 工具栏的第3个popover中
    // SVG use 元素的 xlink:href="#icon-attacthment-download"
    var toolbar = document.querySelector('.attachment-resume-btns');
    if (!toolbar) return {found: false};

    var popovers = toolbar.querySelectorAll('.popover.icon-content');
    for (var i = 0; i < popovers.length; i++) {
        var useEl = popovers[i].querySelector('use');
        if (useEl) {
            var href = useEl.getAttribute('xlink:href') || useEl.getAttribute('href') || '';
            if (href.indexOf('download') >= 0) {
                var r = popovers[i].getBoundingClientRect();
                return {found: true, text: href, x: r.x + r.width/2, y: r.y + r.height/2,
                        tag: popovers[i].tagName, className: popovers[i].className};
            }
        }
    }

    // 回退: 第3个popover就是下载按钮 (全屏→打印→下载)
    if (popovers.length >= 3) {
        var lr = popovers[2].getBoundingClientRect();
        return {found: true, text: 'popover-3rd-download', x: lr.x + lr.width/2, y: lr.y + lr.height/2,
                tag: popovers[2].tagName};
    }

    return {found: false};
})()
"""


def _update_candidate_resume(db: Database, candidate_name: str, resume_path: str, boss_id: str = None, user_id: int = None):
    """更新 candidates 表的简历路径和状态"""
    try:
        db.cursor.execute(
            """INSERT INTO candidates (boss_id, candidate_name, status, resume_path, updated_at, user_id)
               VALUES (%s, %s, 'resume_downloaded', %s, NOW(), %s)
               ON CONFLICT(boss_id) DO UPDATE SET
               resume_path = excluded.resume_path,
               status = 'resume_downloaded',
               updated_at = excluded.updated_at""",
            (boss_id or candidate_name, candidate_name, resume_path, user_id),
        )
        db.conn.commit()
    except Exception as e:
        logger.debug(f"[DL] 更新candidates表忽略: {e}")


async def collect_received_resumes(max_count: int = 10, dry_run: bool = False, user_id: int = None) -> Dict:
    """下载已获取的简历 — 主流程

    1. 导航聊天页 → 点"已获取简历"筛选 → 拉联系人
    2. 对比数据库跳过已下载过的
    3. 逐个点击 → 点附件简历 → PDF预览 → 点下载箭头 → 关闭预览
    """
    resumes_dir = _resumes_dir(user_id)

    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接，请先打开BOSS直聘"}

    # 启用 CDP 下载拦截
    if not dry_run:
        dl_result = await automation.enable_download_interception(str(resumes_dir))
        logger.info(f"[DL] CDP下载拦截: {dl_result.get('status')} → {resumes_dir}")

    # 导航到聊天页
    nav_result = await navigate_to_chat()
    if nav_result.get("status") != "ok":
        await automation.navigate("https://www.zhipin.com/web/chat/index")
        await asyncio.sleep(3)

    # 点击"已获取简历"筛选
    filter_result = await click_received_resume_filter()
    if filter_result.get("status") == "ok":
        await asyncio.sleep(2)
        contacts = await get_contacts()
    else:
        logger.warning("[DL] '已获取简历'筛选未命中")
        contacts = nav_result.get("contacts", [])

    if not contacts:
        return {"status": "completed", "message": "没有已获取简历的联系人",
                "downloaded": 0, "skipped": 0, "failed": 0, "total_scanned": 0}

    # 初始化数据库
    db = Database()
    db.connect()
    db.init_tables()

    downloaded = 0
    skipped = 0
    failed = 0
    details = []

    # 过滤已下载过的（用平台唯一ID去重）
    targets = []
    for c in contacts:
        name = (c.get("name", "") or "").strip()
        if not name:
            continue
        dedup_boss_id = c.get("boss_id") or name
        try:
            ops = db.get_resume_ops(boss_id=dedup_boss_id)
        except Exception:
            ops = []
        already_done = any(
            r.get("resume_downloaded") or r.get("action") == "downloaded"
            for r in ops
        )
        if already_done:
            logger.info(f"[DL] 跳过已下载: {name}")
            skipped += 1
            details.append({"name": name, "action": "skipped", "reason": "已下载过"})
        else:
            targets.append(c)

    logger.info(f"[DL] {len(contacts)}人 → 过滤后 {len(targets)}人，目标下载 {max_count}份")

    for i, contact in enumerate(targets):
        # 检查取消信号
        if cancel_event.is_set():
            logger.info("[DL] 检测到取消信号，停止")
            break
        if downloaded >= max_count:
            logger.info(f"[DL] 已达到目标 {max_count} 份")
            break

        contact_name = (contact.get("name", "") or "").strip()
        boss_id = contact.get("boss_id") or contact_name  # 优先使用BOSS平台唯一ID
        if contact_name == "__DIAG__":
            logger.info(f"[DL] 🔍 诊断: subtitle={contact.get('subtitle', '')}")
        logger.info(f"[DL] 处理 ({i+1}/{len(targets)}, 已下载{downloaded}/{max_count}): {contact_name}")

        # 限制弹窗检测
        limit_kw = await check_limit_popup()
        if limit_kw:
            logger.warning(f"[DL] 检测到限制弹窗: {limit_kw}，终止")
            await dismiss_popup()
            break

        # 逐次查找 + 滚动
        fresh = await refind_contact(contact_name)
        if not fresh:
            fresh = contact
        if not fresh.get("visible", True):
            await scroll_contact_into_view(contact_name)
            await asyncio.sleep(1)
            fresh = await refind_contact(contact_name)
            if not fresh:
                fresh = contact

        # 点击联系人 + 验证名字匹配（防止点错人）
        clicked_ok = False
        for retry in range(3):
            if retry > 0:
                await scroll_contact_into_view(contact_name)
                await asyncio.sleep(0.8)
                fresh = await refind_contact(contact_name)
                if not fresh:
                    fresh = contact
            if not await click_contact(contact_name, fresh.get("x", 0), fresh.get("y", 0)):
                continue
            await asyncio.sleep(2)
            # 验证聊天框顶部名字
            from app.chat_workflow import _JS_GET_CHAT_NAME
            chat_name = await automation.execute_js(_JS_GET_CHAT_NAME)
            current = (chat_name.get("name") or "").strip() if isinstance(chat_name, dict) else ""
            if current and (contact_name in current or current in contact_name):
                clicked_ok = True
                logger.info(f"[DL] 联系人匹配: {current} == {contact_name}")
                break
            logger.warning(f"[DL] 名字不匹配: 期望={contact_name} 实际={current}，重试{retry+1}/3")
            await automation.press_key("Escape")
            await asyncio.sleep(1)
        if not clicked_ok:
            logger.warning(f"[DL] 点击联系人失败或名字不匹配: {contact_name}")
            failed += 1
            continue

        if dry_run:
            details.append({"name": contact_name, "action": "would_download"})
            continue

        # 查找并点击"附件简历"按钮
        from app.resume_collector import _JS_FIND_RESUME_BTNS
        btns = await automation.execute_js(_JS_FIND_RESUME_BTNS)
        btns = btns if isinstance(btns, list) else []
        if not btns:
            logger.warning(f"[DL] {contact_name}: 无简历按钮")
            failed += 1
            continue

        btn = btns[0]
        logger.info(f"[DL] {contact_name} 点击简历按钮: {btn.get('text')}")
        try:
            ok = await automation.cdp_click_viewport(float(btn["x"]), float(btn["y"]))
            if not ok:
                logger.warning(f"[DL] CDP点击失败")
                failed += 1
                continue
            await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"[DL] 点击异常: {e}")
            failed += 1
            continue

        # PDF预览出现 → 等待内容加载完成再找下载箭头
        await asyncio.sleep(3)

        # 去重：检查文件是否已存在
        file_exists = any(
            (resumes_dir / f"{contact_name}{ext}").exists()
            for ext in [".pdf", ".doc", ".docx"]
        )
        if file_exists:
            logger.info(f"[DL] 跳过: {contact_name} 文件已存在")
            skipped += 1
            details.append({"name": contact_name, "action": "skipped", "reason": "文件已存在"})
            await automation.press_key("Escape")
            await asyncio.sleep(1)
            continue

        arrow = await automation.execute_js(_JS_FIND_PDF_DOWNLOAD_ARROW)
        if isinstance(arrow, dict) and arrow.get("found"):
            logger.info(f"[DL] {contact_name} 找到下载箭头: {arrow.get('text')} -> ({arrow['x']:.0f},{arrow['y']:.0f})")
            try:
                # 记录下载前的文件快照（防止关闭预览期间文件已完成）
                dl_dir = Path(str(resumes_dir))
                before = set(dl_dir.iterdir()) if dl_dir.exists() else set()
                await automation.cdp_click_viewport(float(arrow["x"]), float(arrow["y"]))

                # 关闭PDF预览 — 先关掉，下载在后台进行
                await asyncio.sleep(1)
                await automation.cdp_click_viewport(1550, 300)
                await asyncio.sleep(1)

                # 等待下载完成
                dl_result = await automation.wait_for_download(str(resumes_dir), timeout=30.0, before_files=before)
                file_verified = dl_result.get("status") == "downloaded"
                if file_verified:
                    _update_candidate_resume(db, contact_name,
                                             resume_path=dl_result.get("path", ""),
                                             boss_id=boss_id, user_id=user_id)
                    downloaded += 1
                    details.append({"name": contact_name, "action": "downloaded",
                                    "file_verified": True, "path": dl_result.get("path")})
                    db.insert_resume_op(
                        boss_id=boss_id, candidate_name=contact_name, action="downloaded",
                        resume_downloaded=True,
                        detail=json.dumps({"time": datetime.now().isoformat(),
                                           "path": dl_result.get("path", "")}),
                        user_id=user_id,
                    )
                    logger.info(f"[DL] {contact_name} 下载成功 ({dl_result.get('size', 0)} bytes)")
                else:
                    logger.warning(f"[DL] {contact_name} 下载未确认: {dl_result.get('message')}")
                    failed += 1
                    details.append({"name": contact_name, "action": "download_unconfirmed"})
            except Exception as e:
                logger.warning(f"[DL] {contact_name} 下载失败: {e}")
                failed += 1
        else:
            logger.warning(f"[DL] {contact_name}: PDF预览中未找到下载箭头")
            # 回退：尝试用 _JS_FIND_DOWNLOAD_BTN
            from app.resume_collector import _JS_FIND_DOWNLOAD_BTN
            dl_btn = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
            if isinstance(dl_btn, dict) and dl_btn.get("found"):
                logger.info(f"[DL] {contact_name} 回退下载按钮: {dl_btn.get('text')}")
                try:
                    await automation.cdp_click_viewport(float(dl_btn["x"]), float(dl_btn["y"]))
                    dl_result = await automation.wait_for_download(str(resumes_dir), timeout=30.0)
                    if dl_result.get("status") == "downloaded":
                        _update_candidate_resume(db, contact_name,
                                                 resume_path=dl_result.get("path", ""),
                                                 boss_id=boss_id, user_id=user_id)
                        downloaded += 1
                        details.append({"name": contact_name, "action": "downloaded",
                                        "file_verified": True, "path": dl_result.get("path")})
                        db.insert_resume_op(boss_id=boss_id, candidate_name=contact_name, action="downloaded",
                                            resume_downloaded=True,
                                            detail=json.dumps({"time": datetime.now().isoformat()}),
                                            user_id=user_id)
                except Exception:
                    failed += 1
            else:
                failed += 1
                details.append({"name": contact_name, "action": "no_download_arrow"})

    db.close()

    return {
        "status": "completed",
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "total_scanned": len(targets),
        "details": details,
    }
