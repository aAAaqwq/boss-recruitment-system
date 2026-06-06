"""F7 批量AI聊天回复工作流

修复:
- AI失败时自动降级到模板回复
- 生成方式标记 (ai / template_fallback)
"""
import asyncio
import random
from datetime import datetime
from typing import Dict, Optional

from app.automation import automation
from app.chat_nav import (
    navigate_to_chat, get_contacts, get_messages,
    type_and_send, click_contact,
)
from app.chat_service import chat_service
from app.database import Database
from app.logging_config import logger

# 默认兜底模板（AI失败时使用）
_DEFAULT_FALLBACK_TEMPLATES = [
    "您好，感谢您的关注！我正在查看您的消息，稍后会给您详细回复。",
    "您好，感谢您对职位的关注。我会尽快了解您的情况并回复您。",
    "感谢您的来信！我会仔细查看并尽快给您回复。祝好！",
]


async def _batch_reply_impl(
    max_count: int = 10,
    template: Optional[str] = None,
    dry_run: bool = True,
) -> Dict:
    """批量回复未读消息核心逻辑 (async)

    1. 连接浏览器 + 检查登录
    2. 导航到聊天页
    3. 获取联系人列表，筛选有未读消息的
    4. 对每个联系人: 点击 → 获取消息 → AI生成回复 → 发送 → 保存
    5. 返回统计结果
    """
    logger.info(f"[F7] 启动 | max={max_count} dry={dry_run} template={bool(template)}")

    # 1. 连接浏览器 + 检查登录
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接或会话失效，请先打开BOSS直聘"}

    login_status = await automation.check_login()
    if not login_status.get("logged_in"):
        return {"status": "error", "message": "BOSS直聘未登录，请先在VNC中扫码登录"}

    # 2. 导航到聊天页
    nav = await navigate_to_chat()
    if nav.get("status") == "error":
        return {"status": "error", "message": f"导航到聊天页失败: {nav.get('message')}"}
    logger.info(f"[F7] 聊天页就绪，{nav.get('contact_count', 0)}个联系人")

    # 3. 获取联系人列表，筛选有未读消息的
    contacts = await get_contacts()
    # 防御: 确保每个contact是dict
    valid_contacts = [c for c in contacts if isinstance(c, dict)]
    unread = [c for c in valid_contacts if c.get("hasUnread")]
    unread = unread[:max_count]
    logger.info(f"[F7] 共{len(valid_contacts)}个联系人，{len(unread)}个有未读消息")

    if not unread:
        return {
            "status": "completed", "message": "没有未读消息",
            "replied": 0, "failed": 0, "skipped": 0, "total_scanned": 0,
        }

    # 4. 对每个联系人执行回复
    replied = 0
    failed = 0
    skipped = 0
    results = []

    for i, contact in enumerate(unread):
        name = contact.get("name", "未知")
        subtitle = contact.get("subtitle", "")
        contact_x = contact.get("x", 0)
        contact_y = contact.get("y", 0)
        boss_id = name  # 使用姓名作为boss_id

        logger.info(f"[F7] ({i+1}/{len(unread)}) 处理: {name} ({subtitle})")

        # a. 点击联系人
        if not await click_contact(name, contact_x, contact_y):
            logger.warning(f"[F7] 点击联系人失败: {name}")
            failed += 1
            results.append({"name": name, "success": False, "error": "点击联系人失败"})
            continue

        await asyncio.sleep(2)

        # b. 获取最新消息
        messages = await get_messages()
        candidate_msg = ""
        for msg in reversed(messages):
            if not msg.get("isMe"):
                candidate_msg = msg.get("text", "").strip()
                break

        if not candidate_msg:
            # 没有找到候选人消息，可能是空对话或对方还没发消息
            logger.info(f"[F7] {name}: 未找到候选人消息，跳过")
            skipped += 1
            results.append({"name": name, "success": False, "error": "未找到候选人消息"})
            continue

        logger.info(f"[F7] {name} 的最新消息: {candidate_msg[:60]}...")

        # c. 生成AI回复（失败时自动降级到模板）
        reply, error = await chat_service.generate_reply(
            candidate_name=name,
            candidate_message=candidate_msg,
            history=None,
            template=template,
        )
        generation_method = "ai"

        if not reply:
            # PRD要求: AI生成为主，话术模板作为兜底
            logger.warning(f"[F7] AI回复生成失败: {error}，降级到模板回复")
            reply = random.choice(_DEFAULT_FALLBACK_TEMPLATES)
            generation_method = "template_fallback"

        logger.info(f"[F7] 回复({generation_method}): {reply[:60]}...")

        # d. 发送消息（dry_run 模式跳过实际发送）
        if dry_run:
            logger.info(f"[F7] [DRY-RUN] 将发送: {reply}")
            replied += 1
        else:
            send_result = await type_and_send(reply)
            if send_result.get("status") != "ok":
                logger.warning(f"[F7] 发送失败: {send_result.get('message')}")
                failed += 1
                results.append({
                    "name": name, "success": False,
                    "error": send_result.get("message", "发送失败"),
                    "reply": reply,
                })
                continue
            replied += 1
            logger.info(f"[F7] 已发送回复给 {name}")

        # e. 保存到数据库
        try:
            chat_service.save_conversation(
                boss_id=boss_id,
                candidate_name=name,
                candidate_message=candidate_msg,
                ai_message=reply,
                action="auto_reply",
            )
            # 同时记录到 contact_records
            with Database() as db:
                db.init_tables()
                db.insert_contact_record(
                    boss_id=boss_id, action="replied", success=True,
                )
        except Exception as e:
            logger.warning(f"[F7] DB保存失败: {e}")

        results.append({
            "name": name, "success": True, "reply": reply,
            "candidate_msg": candidate_msg[:100],
            "generation_method": generation_method,
        })

        # 间隔休息，模拟人类操作
        await asyncio.sleep(random.uniform(1.5, 4))

    # 截图记录最终状态
    try:
        await automation.screenshot(path="/tmp/f7_final.png")
    except Exception:
        pass

    summary = {
        "status": "completed",
        "replied": replied,
        "failed": failed,
        "skipped": skipped,
        "total_scanned": len(unread),
        "dry_run": dry_run,
        "results": results,
        "message": f"批量回复完成: 成功{replied}, 失败{failed}, 跳过{skipped}, 共扫描{len(unread)}人",
    }
    logger.info(f"[F7] 完成: {summary['message']}")
    return summary


def batch_reply_workflow(
    max_count: int = 10,
    template: Optional[str] = None,
    dry_run: bool = True,
) -> Dict:
    """批量回复未读消息 — 同步入口

    在调用方已有事件循环时使用 ThreadPoolExecutor 避免嵌套事件循环冲突。
    """
    import concurrent.futures

    coro = _batch_reply_impl(
        max_count=max_count, template=template, dry_run=dry_run,
    )
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result(timeout=600)
    return asyncio.run(coro)
