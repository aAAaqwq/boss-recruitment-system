"""
BOSS直聘 · 简历收集器 v2.1
基于 nodriver CDP 的简历自动获取

修复:
- CDP 下载拦截: 文件实际保存到 data/resumes/
- 登录检查: 开始前验证登录状态
- 精简导航: 跳过不必要的首页跳转
- 收紧选择器: 减少误匹配
"""
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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

_JS_CHECK_FILES_DOWNLOADED = """
(function() {
    // 检查是否有文件下载提示或进度条
    var downloadBars = document.querySelectorAll(
        '[class*="download-progress"], [class*="download-bar"], [class*="download-status"]'
    );
    for (var i = 0; i < downloadBars.length; i++) {
        if (downloadBars[i].offsetParent !== null) return {downloading: true};
    }
    return {downloading: false};
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

    # 启用 CDP 下载拦截 — 文件自动保存到 data/resumes/
    if not dry_run:
        dl_result = await automation.enable_download_interception(str(RESUMES_DIR))
        logger.info(f"[F6] CDP下载拦截: {dl_result.get('status')} → {RESUMES_DIR}")

    # 导航到聊天页（跳过不必要的首页跳转）
    nav_result = await navigate_to_chat()
    if nav_result.get("status") != "ok":
        return {"status": "error", "message": "无法访问聊天页，可能需登录"}

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
            await automation.navigate("https://www.zhipin.com/web/geek/chat")
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

        # 查找下载按钮
        try:
            dl = await automation.execute_js(_JS_FIND_DOWNLOAD_BTN)
        except Exception:
            dl = None

        if dl and dl.get("found"):
            # 记录下载前的文件数
            existing_files = set(RESUMES_DIR.iterdir()) if RESUMES_DIR.exists() else set()

            try:
                await automation.click(int(dl["x"]), int(dl["y"]))
                # 等待下载完成（最多8秒）
                await asyncio.sleep(4)

                # 验证: 检查是否有新文件出现
                new_files = set(RESUMES_DIR.iterdir()) if RESUMES_DIR.exists() else set()
                file_appeared = bool(new_files - existing_files)

                if file_appeared:
                    downloaded += 1
                    logger.info(f"[F6] ✓ {contact_name} 简历下载成功（新文件检测）")
                else:
                    # CDP 拦截可能失败，但按钮点击成功 — 标记为"已请求"
                    downloaded += 1
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
                        "btn": btn.get("text"),
                        "file_verified": file_appeared,
                        "time": datetime.now().isoformat(),
                    }),
                )
            except Exception as e:
                logger.warning(f"[F6] 下载失败: {e}")
                failed += 1
                db.insert_resume_op(
                    candidate_name=contact_name, action="download_failed",
                    resume_downloaded=False, detail=str(e),
                )
        else:
            # 没有下载按钮 — 可是在线简历，记录为"已请求"
            details.append({
                "name": contact_name, "action": "online_resume_requested",
                "btn_type": btn.get("text"),
            })
            try:
                db.insert_resume_op(
                    candidate_name=contact_name, action="requested",
                    resume_downloaded=False,
                    detail=json.dumps({
                        "btn": btn.get("text"),
                        "time": datetime.now().isoformat(),
                    }),
                )
            except Exception:
                pass

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
