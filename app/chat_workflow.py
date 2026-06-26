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

from app.automation import automation, cancel_event
from app.chat_nav import (
    navigate_to_chat, get_messages,
    type_and_send, click_contact,
    check_limit_popup, dismiss_popup,
    refind_contact, scroll_contact_into_view,
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


# ===== 与 test_batch_reply.py 完全一致的 LLM pipeline =====

def _filter_messages(messages: List[Dict]) -> List[Dict]:
    """过滤消息列表，去除UI噪音"""
    filtered: List[Dict] = []
    for m in messages:
        t = m.get('text', '').strip()
        if _is_ui_noise(t):
            continue
        filtered.append(m)
    return filtered


def _build_history_from_filtered(filtered: List[Dict]) -> List[Dict]:
    """从过滤后的消息构建对话历史"""
    history: List[Dict] = []
    for m in filtered[-12:]:
        role = 'assistant' if m.get('isMe') else 'user'
        history.append({'role': role, 'content': m.get('text', '')})
    return history


def _load_company_context(user_id: int = None) -> str:
    """加载公司/岗位背景信息 — 读取按用户隔离的 job_info/{user_id}/.selected"""
    bases = []
    if user_id:
        bases.append(f'/app/job_info/{user_id}')
        bases.append(f'job_info/{user_id}')
    bases.extend(['/app/job_info', 'job_info'])
    for base in bases:
        try:
            sel_path = f'{base}/.selected'
            with open(sel_path, encoding='utf-8') as f:
                selected = f.read().strip()
            if selected:
                filepath = f'{base}/{selected}.txt'
                with open(filepath, encoding='utf-8') as f:
                    return f.read().strip()
        except Exception:
            continue
    return ''


def _build_llm_messages(history: List[Dict], candidate_msg: str, company_context: str) -> List[Dict]:
    """构建发送给DeepSeek的完整messages数组"""
    system_prompt = (
        (company_context + '\n\n' if company_context else '') +
        '你是一名专业的招聘官，正在通过BOSS直聘与候选人交流。'
        '要求：'
        '1. 回复简洁自然，不超过80字'
        '2. 语气友好、专业，像真人对话'
        '3. 严禁向候选人索要微信、电话、转账或任何敏感联系方式'
        '4. 不承诺offer录用'
        '5. 回复时结合公司和岗位背景信息，根据候选人问题进行针对性回复'
    )

    messages: List[Dict] = [{"role": "system", "content": system_prompt}]
    for turn in history[-10:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": f"候选人说：{candidate_msg}"})
    return messages


async def _call_deepseek(messages: List[Dict]) -> str:
    """调用DeepSeek API生成回复（与test_batch_reply.py参数完全一致）"""
    import httpx as _httpx
    from app.config import settings

    async with _httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.DEEPSEEK_BASE_URL}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.DEEPSEEK_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 150,
            },
        )
    if response.status_code == 200:
        data = response.json()
        reply = data["choices"][0]["message"]["content"].strip()
        return reply
    else:
        raise RuntimeError(f"API调用失败: HTTP {response.status_code} - {response.text}")


_UI_SKIP_EXACT: set = {
    "没有更多了", "全部职位", "全部", "未读", "已读",
    "沟通中", "不限", "筛选", "发送", "我知道了",
    "求简历", "换电话", "换微信", "不合适",
    "刚刚活跃", "今日活跃", "在线",
    "同意", "拒绝", "接收", "忽略",
    "对方想发送附件简历给您", "对方想发送附件简历给您，您是否同意",
    "您可以在这里直接对牛人发起",
    "在线简历", "附件简历", "工作经历", "未填写工作经历",
    "沟通职位：", "期望：",
    "送达", "约面试",
    # 简历请求相关的系统提示（非对话内容）
    "简历请求已发送",
    "您可以在线预览牛人简历， 设置邮箱 后投递的简历会同时发送到您的邮箱。",
    "您可以在线预览牛人简历，设置邮箱后投递的简历会同时发送到您的邮箱。",
    # BOSS系统快捷回复（输入框预置，非候选人真实消息）
    "不好意思，不太合适哦",
    "好的，我们再聊聊",
    "抱歉，暂时不考虑",
    "我对这个职位很感兴趣",
    "我们加个微信详细聊吧",
    "请问这个职位还招人吗",
}


def _is_ui_noise(text: str) -> bool:
    """判断文本是否为UI噪音（标签/按钮/系统提示等非对话内容）"""
    if not text or not text.strip():
        return True
    t = text.strip()
    if t in _UI_SKIP_EXACT:
        return True
    if len(t) <= 8 and (t.endswith(("月", "日")) or ":" in t or t.isdigit()):
        return True
    import re as _re
    if _re.match(r'^\d{1,2}岁$', t): return True
    if _re.match(r'^\d{1,2}年(应届生)?$', t): return True
    if t in ("本科", "硕士", "博士", "大专"): return True
    if _re.match(r'^[一-龥]{2,8}(大学|学院)$', t): return True
    return False


def _build_history_from_messages(messages: List[Dict]) -> List[Dict]:
    """将浏览器获取的消息列表转换为标准 history 格式，同时过滤UI噪音。

    浏览器消息格式: {text, isMe, x, y}
    AI history 格式: {role: "assistant"|"user", content: "..."}
    """
    history: List[Dict] = []
    for msg in messages:
        text = msg.get("text", "").strip()
        if _is_ui_noise(text):
            continue
        role = "assistant" if msg.get("isMe") else "user"
        history.append({"role": role, "content": text})
    return history


async def _batch_reply_impl(
    max_count: int = 10,
    template: Optional[str] = None,
    dry_run: bool = True,
    user_id: int = None,
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

    # 1. 检查浏览器会话（连接由调用方 _run_reply_in_thread 统一管理）
    # 注意: 不在此处调用 reset_for_thread()，避免破坏调用方已建立的连接
    if not await automation._ensure_session():
        return {"status": "error", "message": "浏览器未连接或会话失效，请先打开BOSS直聘"}

    # 注意: 不在此处调用 check_login()，因为它会导航到 /web/chat/recommend，
    # 然后 navigate_to_chat() 再次导航到同一 URL，双重导航干扰 BOSS直聘的
    # 异步联系人列表加载，导致 get_contacts() 返回 0。

    # 2. 导航到聊天页 + 筛选未读
    nav = await navigate_to_chat(filter_unread=True)
    if nav.get("status") == "error":
        return {"status": "error", "message": f"导航到聊天页失败: {nav.get('message')}"}

    contacts = nav.get("contacts", [])
    valid_contacts = [c for c in contacts if isinstance(c, dict)]
    logger.info(f"[F7] 聊天页就绪，{len(valid_contacts)}个未读联系人")

    # 无未读时回退到全部联系人
    if not valid_contacts:
        logger.info("[F7] 无未读，回退到全部联系人")
        nav = await navigate_to_chat()
        contacts = nav.get("contacts", [])
        valid_contacts = [c for c in contacts if isinstance(c, dict)]
        logger.info(f"[F7] 全部联系人: {len(valid_contacts)} 个")

    if not valid_contacts:
        return {
            "status": "completed", "message": "没有联系人",
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

    try:
        logger.info(f"[F7] 候选 {len(valid_contacts)} 个未读联系人，目标回复 {max_count} 个")

        contact_idx = 0
        for contact in valid_contacts:
            # 检查取消信号
            if cancel_event.is_set():
                logger.info("[F7] 检测到取消信号，停止")
                break
            # 已回复够数，退出
            if replied >= max_count:
                break

            contact_idx += 1
            name = contact.get("name", "未知")
            subtitle = contact.get("subtitle", "")
            contact_x = contact.get("x", 0)
            contact_y = contact.get("y", 0)
            boss_id = contact.get("boss_id") or name  # 优先使用平台唯一ID

            logger.info(f"[F7] ({contact_idx}/{len(valid_contacts)}, 已回复{replied}/{max_count}) 处理: {name} ({subtitle})")

            # 0. 限制弹窗检测 — 命中则终止循环
            limit_kw = await check_limit_popup()
            if limit_kw:
                logger.warning(f"[F7] 检测到限制弹窗: {limit_kw}，终止批量回复")
                await dismiss_popup()
                break

            # a. 重新定位+滚动（消息可能压下去旧联系人）
            fresh = await refind_contact(name)
            if fresh and fresh.get("x"):
                contact_x, contact_y = fresh["x"], fresh["y"]
            if not fresh or not fresh.get("visible", True):
                await scroll_contact_into_view(name)
                await asyncio.sleep(0.5)
                fresh = await refind_contact(name)
                if fresh and fresh.get("x"):
                    contact_x, contact_y = fresh["x"], fresh["y"]

            # b. 点击联系人
            if not await click_contact(name, contact_x, contact_y):
                logger.warning(f"[F7] 点击联系人失败: {name}")
                failed += 1
                results.append({"name": name, "success": False, "error": "点击联系人失败"})
                continue

            await asyncio.sleep(2)

            # c. 获取完整聊天消息
            messages = await get_messages()
            logger.info(f"[F7] {name}: 提取到 {len(messages)} 条消息")
            for mi, m in enumerate(messages):
                logger.info(f"[F7]   [{mi}] {'[我]' if m.get('isMe') else '[对方]'} "
                            f"x={m.get('x')} y={m.get('y')}: {(m.get('text', '') or '')[:50]}")

            # 提取候选人最新消息
            candidate_msg = ""
            for msg in reversed(messages):
                if not msg.get("isMe"):
                    text = msg.get("text", "").strip()
                    if _is_ui_noise(text):
                        continue
                    candidate_msg = text
                    break

            if not candidate_msg:
                logger.info(f"[F7] {name}: 未找到候选人消息，跳过")
                skipped += 1
                results.append({"name": name, "success": False, "error": "未找到候选人消息"})
                continue

            logger.info(f"[F7] {name} 的最新消息: {candidate_msg[:80]}...")

            # c. 构建LLM上下文（与test_batch_reply.py完全一致）
            # 过滤消息
            filtered = _filter_messages(messages)
            # 构建对话历史
            history = _build_history_from_filtered(filtered)
            # 加载公司岗位信息
            company_context = _load_company_context(user_id=user_id)
            # 构建LLM messages
            llm_messages = _build_llm_messages(history, candidate_msg, company_context)

            logger.info(f"[F7] {name} LLM上下文 ({len(llm_messages)} 条):")
            for imi, _m in enumerate(llm_messages):
                logger.info(f"[F7]   [{imi}] [{_m['role'][:1].upper()}] {_m['content'][:120]}")

            # d. 调用DeepSeek生成回复（始终走AI，忽略前端模板）
            try:
                reply = await _call_deepseek(llm_messages)
                generation_method = "ai"
            except Exception as e:
                logger.warning(f"[F7] AI回复生成失败: {e}，降级到模板回复")
                reply = random.choice(_DEFAULT_FALLBACK_TEMPLATES)
                generation_method = "template_fallback"

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
                        user_id=user_id,
                    )
                    # 同时记录到 contact_records
                    db.insert_contact_record(
                        boss_id=boss_id, action="replied", success=True, user_id=user_id,
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
            "total_scanned": contact_idx,
            "dry_run": dry_run,
            "results": results,
            "message": f"批量回复完成: 成功{replied}, 失败{failed}, 跳过{skipped}, 共扫描{contact_idx}人",
        }
        logger.info(f"[F7] 完成: {summary['message']}")
        return summary
    finally:
        db.close()


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
