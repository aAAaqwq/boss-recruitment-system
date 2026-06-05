"""
BOSS直聘 · 简历收集器 v2.0
基于 nodriver CDP 的简历自动获取
"""
import asyncio
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.automation import automation
from app.database import Database
from app.logging_config import logger

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
RESUMES_DIR = DATA_DIR / "resumes"


# ========== JS 提取脚本 ==========

_JS_FIND_RESUME_BTNS = """
(function() {
    // 在聊天面板右侧/顶部查找简历相关按钮
    var btns = document.querySelectorAll('button, a, span, [class*="btn"], [class*="resume"]');
    var results = [];
    for (var i = 0; i < btns.length; i++) {
        var t = (btns[i].innerText || '').trim();
        if (t.includes('在线简历') || t.includes('附件简历') || t.includes('简历')) {
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
        if (t.includes('下载') || t.includes('保存') || t.includes('导出')) {
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

_JS_FIND_CONTACT_LIST = """
(function() {
    // 提取左侧联系人列表
    var items = document.querySelectorAll(
        '[class*="contact"], [class*="chat-item"], [class*="conversation"], '
        + '[class*="user-item"], [class*="dialog-item"], [class*="list-item"]'
    );
    var contacts = [];
    for (var i = 0; i < items.length; i++) {
        var r = items[i].getBoundingClientRect();
        var t = (items[i].innerText || '').trim();
        if (r.width > 100 && r.height > 40 && t.length > 0) {
            contacts.push({text: t.split('\\n')[0], x: r.x + r.width/2, y: r.y + r.height/2});
        }
    }
    if (contacts.length === 0) {
        // Fallback: any clickable items on the left side
        var all = document.querySelectorAll('[class*="item"], [class*="row"], [class*="entry"]');
        for (var j = 0; j < all.length; j++) {
            var ar = all[j].getBoundingClientRect();
            var at = (all[j].innerText || '').trim();
            if (ar.x < 450 && ar.width > 100 && ar.height > 40 && at.length > 0) {
                contacts.push({text: at.split('\\n')[0], x: ar.x + ar.width/2, y: ar.y + ar.height/2});
            }
        }
    }
    return contacts;
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

    # 确保浏览器连接（Chrome 已通过 --user-data-dir 保持登录态）
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接，请先打开BOSS直聘"}

    # 先导航到 zhipin.com，导入 cookie，再导航到聊天页
    await automation.navigate("https://www.zhipin.com/")
    await asyncio.sleep(3)
    cookie_result = await automation.import_cookies()
    logger.info(f"[F6] Cookie导入: {cookie_result.get('imported', 0)}/{cookie_result.get('total', 0)} 条")
    await asyncio.sleep(2)

    for chat_url in [
        "https://www.zhipin.com/web/geek/chat",
        "https://www.zhipin.com/web/chat/recommend",
        "https://www.zhipin.com/web/user/chat",
    ]:
        nav = await automation.navigate(chat_url)
        await asyncio.sleep(4)
        if nav.get("status") == "ok":
            current = await automation.execute_js("window.location.href") or ""
            logger.info(f"[F6] 导航结果: {current}")
            if "login" not in current.lower() and "zhipin.com/web/chat" in current:
                break
        logger.info(f"[F6] 重试导航...")
    else:
        return {"status": "error", "message": "无法访问聊天页，可能需登录"}

    # 初始化数据库
    db = Database()
    db.init_tables()

    downloaded = 0
    skipped = 0
    failed = 0
    details = []

    # 获取联系人列表（try/except 保护每个JS调用）
    contacts = []
    try:
        result = await automation.execute_js(_JS_FIND_CONTACT_LIST)
        contacts = result if isinstance(result, list) else []
    except Exception as e:
        logger.warning(f"[F6] JS提取联系人失败: {e}")

    if not contacts:
        logger.info("[F6] 未找到联系人，尝试备用导航...")
        try:
            await automation.navigate("https://www.zhipin.com/web/geek/chat")
            await asyncio.sleep(4)
            result = await automation.execute_js(_JS_FIND_CONTACT_LIST)
            contacts = result if isinstance(result, list) else []
        except Exception as e:
            logger.warning(f"[F6] 备用联系人提取失败: {e}")

    logger.info(f"[F6] 找到 {len(contacts)} 个联系人，上限 {max_count}")

    for i, contact in enumerate(contacts[:max_count]):
        contact_name = (contact.get("text", "") or f"contact_{i}").strip()
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

        # 查找下载按钮
        try:
            dl = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
        except Exception:
            dl = None
        if dl and dl.get("found"):
            try:
                await automation.click(int(dl["x"]), int(dl["y"]))
                await asyncio.sleep(2)
                downloaded += 1
                details.append({"name": contact_name, "action": "downloaded", "btn_type": btn.get("text")})
                db.insert_resume_op(
                    candidate_name=contact_name,
                    action="downloaded",
                    resume_downloaded=True,
                    detail=json.dumps({"btn": btn.get("text"), "time": datetime.now().isoformat()}),
                )
            except Exception as e:
                logger.warning(f"[F6] 下载失败: {e}")
                failed += 1
                db.insert_resume_op(
                    candidate_name=contact_name, action="download_failed",
                    resume_downloaded=False, detail=str(e),
                )
        else:
            details.append({"name": contact_name, "action": "online_resume_requested", "btn_type": btn.get("text")})
            try:
                db.insert_resume_op(
                    candidate_name=contact_name, action="requested",
                    resume_downloaded=False,
                    detail=json.dumps({"btn": btn.get("text"), "time": datetime.now().isoformat()}),
                )
            except Exception:
                pass

        # 关闭预览
        try:
            await automation.press_key("Escape")
            await asyncio.sleep(1)
        except Exception:
            pass

        # 截图
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
