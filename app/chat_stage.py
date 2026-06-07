"""
F7 对话阶段推算模块

从 DB 加载候选人上下文，结合聊天历史推算对话阶段，
防止 AI 重复请求已有信息（简历/微信）。

阶段定义:
  - ready_for_interview: 简历 + 微信都有 → 推动约面试
  - has_resume_no_wechat: 有简历无微信 → 不问简历，推动面试/微信
  - has_wechat_no_resume: 有微信无简历 → 不问微信，聊岗位细节
  - awaiting_response: 已请求简历/微信等待回复 → 不重复请求
  - early_stage: 无数据无约束 → 自由对话
"""

from typing import Dict, List, Optional, Tuple

from app.database import Database
from app.logging_config import logger


# ========== 冗余检测模式 ==========

RESUME_PATTERNS: Tuple[str, ...] = (
    "方便发简历",
    "发一份简历",
    "简历发",
    "你的简历",
    "发简历过来",
)

WECHAT_PATTERNS: Tuple[str, ...] = (
    "加微信",
    "交换微信",
    "方便加个微信",
    "微信号多少",
    "你的微信",
)


# ========== 阶段兜底文本 ==========

STAGE_FALLBACK: Dict[str, str] = {
    "ready_for_interview": (
        "简历和微信都收到了，方便的话我们约个时间聊聊具体岗位细节？"
    ),
    "has_resume_no_wechat": (
        "简历收到了，具体岗位细节可以进一步沟通，你觉得怎么样？"
    ),
    "has_wechat_no_resume": (
        "好的，具体岗位细节可以进一步聊，方便说说你主要的项目经历吗？"
    ),
    "awaiting_response": (
        "好的，等你方便回复的时候我们再继续聊～"
    ),
}


def load_candidate_context(
    db: Database,
    uid: Optional[str],
    name: str,
) -> Dict:
    """从 DB 加载候选人上下文信息。

    查询 candidates 表获取简历路径和状态，查询 resume_operations 表
    获取微信交换记录，查询 chat_sessions 表获取历史聊天记录。

    Args:
        db: 已连接的 Database 实例（调用方负责 connect + init_tables）。
        uid: 候选人唯一标识（boss_id），优先使用。
        name: 候选人姓名，uid 为空时回退使用。

    Returns:
        包含 has_resume, has_wechat, wechat, status, db_chat_history 的字典。
    """
    has_resume: bool = False
    has_wechat: bool = False
    wechat: str = ""
    status: str = ""
    db_chat_history: List[Dict] = []

    # 1. 从 candidates 表查基本信息
    candidate: Optional[Dict] = None
    if uid:
        candidate = db.get_candidate(uid)
    if not candidate and name:
        # 按姓名查找（非唯一，取第一条）
        try:
            db.cursor.execute(
                "SELECT * FROM candidates WHERE candidate_name = ? LIMIT 1",
                (name,),
            )
            row = db.cursor.fetchone()
            if row:
                candidate = dict(row)
        except Exception:
            candidate = None

    if candidate:
        # has_resume: 有简历路径即为 True
        has_resume = bool(candidate.get("resume_path"))
        status = candidate.get("status", "")

    # 2. 从 resume_operations 表查微信交换记录
    search_name = name or ""
    try:
        ops = db.get_resume_ops(search_name)
        for op in ops:
            if op.get("wechat_exchanged"):
                has_wechat = True
                break
    except Exception:
        logger.debug(f"[chat_stage] 查询微信记录失败: {search_name}")

    # 3. 从 chat_sessions 表获取 DB 中的聊天历史
    lookup_id = uid or name or ""
    if lookup_id:
        try:
            session = db.get_chat_session(lookup_id)
            if session and session.get("history"):
                db_chat_history = session["history"]
        except Exception:
            logger.debug(f"[chat_stage] 查询聊天历史失败: {lookup_id}")

    return {
        "has_resume": has_resume,
        "has_wechat": has_wechat,
        "wechat": wechat,
        "status": status,
        "db_chat_history": db_chat_history,
    }


def compute_stage(
    ctx: Dict,
    chat_history: List[Dict],
) -> Tuple[str, str]:
    """根据 DB 上下文和聊天历史推算对话阶段。

    阶段优先级（从高到低）:
      1. ready_for_interview — 简历和微信都有
      2. has_resume_no_wechat — 有简历无微信
      3. has_wechat_no_resume — 有微信无简历
      4. awaiting_response — 历史中已请求过简历/微信
      5. early_stage — 默认

    Args:
        ctx: load_candidate_context 返回的上下文字典。
        chat_history: 聊天记录列表，每项含 role + content。

    Returns:
        (stage_name, stage_context_str) 元组。
        stage_context_str 格式: "阶段: {stage}\n已知: {items}\n注意: {hint}"
    """
    has_resume: bool = ctx.get("has_resume", False)
    has_wechat: bool = ctx.get("has_wechat", False)

    # 检查是否已发出简历/微信请求（在"我"发的消息中）
    resume_requested: bool = False
    wechat_requested: bool = False
    for msg in chat_history:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role in ("assistant", "boss"):
            content_lower = content.lower()
            if any(p in content_lower for p in RESUME_PATTERNS):
                resume_requested = True
            if any(p in content_lower for p in WECHAT_PATTERNS):
                wechat_requested = True

    # 按优先级推算阶段
    if has_resume and has_wechat:
        stage = "ready_for_interview"
        known = "已收到简历, 已交换微信"
        hint = "不要再问简历或微信，直接推动约面试"
    elif has_resume and not has_wechat:
        stage = "has_resume_no_wechat"
        known = "已收到简历"
        hint = "不要再问简历，可以推动约面试或交换微信"
    elif has_wechat and not has_resume:
        stage = "has_wechat_no_resume"
        known = "已交换微信"
        hint = "不要再问微信，聊具体岗位细节"
    elif resume_requested or wechat_requested:
        stage = "awaiting_response"
        requested_items: List[str] = []
        if resume_requested:
            requested_items.append("简历")
        if wechat_requested:
            requested_items.append("微信")
        known = f"已请求: {', '.join(requested_items)}"
        hint = "不要重复请求已索要的信息"
    else:
        stage = "early_stage"
        known = "无"
        hint = "自由对话，自然推进"

    context_str = f"阶段: {stage}\n已知: {known}\n注意: {hint}"
    return stage, context_str


def reply_redundant(reply: str, ctx: Dict) -> bool:
    """检查 AI 回复是否冗余请求了候选人已提供的信息。

    如果候选人已有简历但回复中索要简历，或者已有微信但回复中
    索要微信，则判定为冗余。

    Args:
        reply: AI 生成的回复文本。
        ctx: load_candidate_context 返回的上下文字典。

    Returns:
        True 表示回复冗余，应替换为阶段兜底文本。
    """
    if ctx.get("has_resume") and any(p in reply for p in RESUME_PATTERNS):
        logger.info("[chat_stage] 冗余检测: 已有简历但AI仍索要简历")
        return True

    if ctx.get("has_wechat") and any(p in reply for p in WECHAT_PATTERNS):
        logger.info("[chat_stage] 冗余检测: 已有微信但AI仍索要微信")
        return True

    return False
