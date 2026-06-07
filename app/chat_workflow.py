"""F7 批量AI聊天回复工作流

修复:
- AI失败时自动降级到模板回复
- 生成方式标记 (ai / template_fallback / stage_fallback)
- DB上下文加载 + 对话阶段推算 (防止重复请求已有信息)
- 冗余回复检测 + 阶段兜底替换
- 已回复跳过 (避免重复回复)
"""
import asyncio
import random
from typing import Dict, List, Optional

from app.automation import automation
from app.chat_nav import (
    navigate_to_chat, get_contacts, get_messages,
    type_and_send, click_contact,
    check_limit_popup, dismiss_popup,
)
from app.chat_service import chat_service
from app.chat_stage import (
    load_candidate_context, compute_stage, reply_redundant,
    STAGE_FALLBACK,
)
from app.database import Database
from app.logging_config import logger

# 默认兜底模板（AI失败时使用）
_DEFAULT_FALLBACK_TEMPLATES = [
    "您好，感谢您的关注！我正在查看您的消息，稍后会给您详细回复。",
    "您好，感谢您对职位的关注。我会尽快了解您的情况并回复您。",
    "感谢您的来信！我会仔细查看并尽快给您回复。祝好！",
]


def _build_history_from_messages(messages: List[Dict]) -> List[Dict]:
    """将浏览器获取的消息列表转换为标准 history 格式。

    浏览器消息格式: {text, isMe, x, y}
    AI history 格式: {role: "assistant"|"user", content: "..."}

    Args:
        messages: 浏览器获取的消息列表。

    Returns:
        标准化后的历史记录列表。
    """
    history: List[Dict] = []
    for msg in messages:
        text = msg.get("text", "").strip()
        if not text:
            continue
        role = "assistant" if msg.get("isMe") else "user"
        history.append({"role": role, "content": text})
    return history


async def _batch_reply_impl(
    max_count: int = 10,
    template: Optional[str] = None,
    dry_run: bool = True,
) -> Dict:
    """批量回复未读消息核心逻辑 (async)

    1. 连接浏览器 + 检查登录
    2. 导航到聊天页
    3. 获取联系人列表，筛选有未读消息的
    4. 对每个联系人: 点击 → 获取消息 → 加载DB上下文 → 推算阶段
       → AI生成回复 → 冗余检查 → 发送 → 保存
    5. 返回统计结果
    """
    logger.info(f"[F7] 启动 | max={max_count} dry={dry_run} template={bool(template)}")

    # 1. 连接浏览器 + 检查登录
    # 线程安全: 重置连接状态，防止 ThreadPoolExecutor 复用陈旧会话
    automation.reset_for_thread()
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

    # 初始化DB连接（循环外创建，避免反复开关）
    db = Database()
    db.connect()
    db.init_tables()

    for i, contact in enumerate(unread):
        name = contact.get("name", "未知")
        subtitle = contact.get("subtitle", "")
        contact_x = contact.get("x", 0)
        contact_y = contact.get("y", 0)
        boss_id = name  # 使用姓名作为boss_id

        logger.info(f"[F7] ({i+1}/{len(unread)}) 处理: {name} ({subtitle})")

        # 0. 限制弹窗检测 — 命中则终止循环
        limit_kw = await check_limit_popup()
        if limit_kw:
            logger.warning(f"[F7] 检测到限制弹窗: {limit_kw}，终止批量回复")
            await dismiss_popup()
            break

        # a. 点击联系人
        if not await click_contact(name, contact_x, contact_y):
            logger.warning(f"[F7] 点击联系人失败: {name}")
            failed += 1
            results.append({"name": name, "success": False, "error": "点击联系人失败"})
            continue

        await asyncio.sleep(2)

        # b. 获取完整聊天消息
        messages = await get_messages()

        # b'. 已回复检测 — 最后一条是我们发的 → 跳过
        last_msg = messages[-1] if messages else None
        if last_msg:
            last_is_me = last_msg.get("isMe", False)
            last_sender = "boss" if last_is_me else "candidate"
        else:
            last_sender = ""

        if last_sender == "boss":
            logger.info(f"[F7] {name}: 最后一条是我们发的，已回复过，跳过")
            skipped += 1
            results.append({"name": name, "success": False, "error": "already_replied"})
            continue

        # 提取候选人最新消息
        candidate_msg = ""
        for msg in reversed(messages):
            if not msg.get("isMe"):
                candidate_msg = msg.get("text", "").strip()
                break

        if not candidate_msg:
            logger.info(f"[F7] {name}: 未找到候选人消息，跳过")
            skipped += 1
            results.append({"name": name, "success": False, "error": "未找到候选人消息"})
            continue

        logger.info(f"[F7] {name} 的最新消息: {candidate_msg[:60]}...")

        # c. 构建聊天历史 + 加载DB上下文 + 推算对话阶段
        chat_history = _build_history_from_messages(messages)
        try:
            ctx = load_candidate_context(db, uid=None, name=name)
        except Exception as e:
            logger.warning(f"[F7] 加载DB上下文失败: {e}")
            ctx = {
                "has_resume": False, "has_wechat": False,
                "wechat": "", "status": "", "db_chat_history": [],
            }

        # 合并 DB 历史与浏览器历史（去重保序，保留最近 20 条）
        db_history = ctx.get("db_chat_history", [])
        merged: List[Dict] = _merge_histories(db_history, chat_history)

        # 推算对话阶段
        stage, stage_context_str = compute_stage(ctx, merged)
        logger.info(f"[F7] {name} 阶段: {stage}")

        # d. 生成AI回复（失败时自动降级到模板）
        reply, error = await chat_service.generate_reply(
            candidate_name=name,
            candidate_message=candidate_msg,
            history=merged[-10:],
            template=template,
            stage_context=stage_context_str,
        )
        generation_method = "ai"

        if not reply:
            # PRD要求: AI生成为主，话术模板作为兜底
            logger.warning(f"[F7] AI回复生成失败: {error}，降级到模板回复")
            reply = random.choice(_DEFAULT_FALLBACK_TEMPLATES)
            generation_method = "template_fallback"

        # e. 冗余检查 — 已有简历/微信时，AI 仍索要则替换为阶段兜底
        if reply_redundant(reply, ctx):
            fallback = STAGE_FALLBACK.get(stage)
            if fallback:
                logger.info(f"[F7] 冗余回复替换为阶段兜底: {stage}")
                reply = fallback
                generation_method = "stage_fallback"

        logger.info(f"[F7] 回复({generation_method}): {reply[:60]}...")

        # f. 发送消息（dry_run 模式跳过实际发送）
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

        # g. 保存到数据库（dry_run 模式跳过持久化，避免记录未实际发送的回复）
        if not dry_run:
            try:
                chat_service.save_conversation(
                    boss_id=boss_id,
                    candidate_name=name,
                    candidate_message=candidate_msg,
                    ai_message=reply,
                    action="auto_reply",
                )
                # 同时记录到 contact_records
                db.insert_contact_record(
                    boss_id=boss_id, action="replied", success=True,
                )
            except Exception as e:
                logger.warning(f"[F7] DB保存失败: {e}")

        results.append({
            "name": name, "success": True, "reply": reply,
            "candidate_msg": candidate_msg[:100],
            "generation_method": generation_method,
            "stage": stage,
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


def _merge_histories(
    db_history: List[Dict],
    browser_history: List[Dict],
    max_entries: int = 20,
) -> List[Dict]:
    """合并 DB 历史与浏览器历史，去重保序。

    使用 (role, content) 元组作为去重键，保留最近 max_entries 条。

    Args:
        db_history: 从 chat_sessions 表获取的历史。
        browser_history: 从浏览器 DOM 提取的历史。
        max_entries: 最大保留条数。

    Returns:
        合并后的历史列表。
    """
    seen = set()
    merged: List[Dict] = []

    # 先加 DB 历史（更早的记录）
    for entry in db_history:
        key = (entry.get("role", ""), entry.get("content", ""))
        if key not in seen and key[1]:
            seen.add(key)
            merged.append(entry)

    # 再加浏览器历史（更近的记录，覆盖 DB 中的重复部分）
    for entry in browser_history:
        key = (entry.get("role", ""), entry.get("content", ""))
        if key not in seen and key[1]:
            seen.add(key)
            merged.append(entry)

    # 保留最近的条目
    return merged[-max_entries:]


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
