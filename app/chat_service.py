"""
AI批量回复服务
整合DeepSeek API生成回复、BOSS直聘发送、对话记录保存
"""
import json
import httpx
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from app.config import settings
from app.database import Database
from app.logging_config import logger


_COMPANY_PROFILE_CACHE: Optional[str] = None


def _load_company_profile() -> str:
    """加载公司/岗位背景信息 — 读取 job_info/.selected 中指定的文件"""
    try:
        with open('/app/job_info/.selected', encoding='utf-8') as f:
            selected = f.read().strip()
        if selected:
            path = f'/app/job_info/{selected}.txt'
            with open(path, encoding='utf-8') as f:
                return f.read().strip()
    except Exception:
        pass
    # 兼容回退
    try:
        with open('/app/job_info/company_profile.txt', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return ""


class ChatService:
    """AI对话服务"""

    def __init__(self):
        self.db = Database()

    async def close(self):
        """关闭HTTP客户端（已改为按请求创建，无需持久连接）"""
        pass

    async def generate_reply(
        self,
        candidate_name: str,
        candidate_message: str,
        history: Optional[List[Dict]] = None,
        template: Optional[str] = None,
        stage_context: Optional[str] = None,
    ) -> Tuple[Optional[str], str]:
        """
        使用DeepSeek生成回复

        Args:
            candidate_name: 候选人姓名
            candidate_message: 候选人最新消息
            history: 对话历史 [{"role": "assistant", "content": "..."}]
            template: 自定义回复模板（优先使用）
            stage_context: 对话阶段上下文（注入system prompt）

        Returns:
            (reply_content, error_message)
        """
        if template:
            logger.info(f"[ChatService] 使用自定义模板，跳过AI")
            return template, ""

        if not settings.DEEPSEEK_API_KEY:
            return None, "DEEPSEEK_API_KEY未配置"

        # 与 test_llm.py 完全一致：先加载岗位信息作为前提注入
        company_context = _load_company_profile()
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

        messages = [{"role": "system", "content": system_prompt}]

        # 注入历史对话（先于当前消息，保持时序）
        if history:
            for turn in history[-10:]:
                messages.append({"role": turn["role"], "content": turn["content"]})

        messages.append({
            "role": "user",
            "content": f"候选人说：{candidate_message}",
        })

        # 临时验证日志：与 test_llm.py 输出对比
        logger.info(f"[ChatService] LLM_INPUT ({len(messages)} msgs):")
        for im, _m in enumerate(messages):
            logger.info(f"[ChatService]   [{im}] [{_m['role']}] {_m['content'][:200]}")

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.DEEPSEEK_BASE_URL}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": settings.DEEPSEEK_MODEL,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 150
                    }
                )

            if response.status_code == 200:
                data = response.json()
                reply = data["choices"][0]["message"]["content"].strip()
                return reply, ""
            else:
                error_msg = response.text or f"HTTP {response.status_code}"
                return None, f"API调用失败: {error_msg}"

        except Exception as e:
            logger.error(f"DeepSeek API调用异常: {e}")
            return None, f"API调用异常: {str(e)}"

    async def send_to_boss(self, boss_id: str, message: str) -> Tuple[bool, str]:
        """
        发送消息到BOSS直聘

        Args:
            boss_id: 候选人BOSS ID
            message: 要发送的消息

        Returns:
            (success, error_message)
        """
        try:
            # 这里需要调用实际的BOSS直聘发送接口
            # 目前返回模拟状态
            logger.info(f"模拟发送消息到 {boss_id}: {message}")
            return True, ""

        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False, str(e)

    def save_conversation(
        self,
        boss_id: str,
        candidate_name: str,
        candidate_message: str,
        ai_message: str,
        action: str = "auto_reply"
    ) -> int:
        """
        保存对话记录到数据库

        Args:
            boss_id: 候选人BOSS ID
            candidate_name: 候选人姓名
            candidate_message: 候选人消息
            ai_message: AI生成的回复
            action: 操作类型

        Returns:
            conversation_id
        """
        with self.db as db:
            db.cursor.execute("""
                INSERT INTO conversations
                (candidate_name, action, ai_message, candidate_message, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                candidate_name,
                action,
                ai_message,
                candidate_message,
                json.dumps({"boss_id": boss_id}),
                datetime.now().isoformat()
            ))
            db.conn.commit()
            return db.cursor.lastrowid

    def get_conversation_history(
        self,
        candidate_name: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        获取对话历史

        Args:
            candidate_name: 候选人姓名（可选）
            limit: 最大返回数量

        Returns:
            对话历史列表
        """
        with self.db as db:
            if candidate_name:
                rows = db.cursor.execute("""
                    SELECT * FROM conversations
                    WHERE candidate_name = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (candidate_name, limit)).fetchall()
            else:
                rows = db.cursor.execute("""
                    SELECT * FROM conversations
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()

            return [dict(row) for row in rows]

    def get_unread_messages(self) -> List[Dict]:
        """
        获取未读消息列表

        Returns:
            未读消息列表 [{boss_id, candidate_name, message, ...}]
        """
        with self.db as db:
            # 从candidates表获取需要回复的候选人
            rows = db.cursor.execute("""
                SELECT c.* FROM candidates c
                WHERE c.status IN ('replied', 'chatting')
                ORDER BY c.updated_at DESC
                LIMIT 100
            """).fetchall()

            return [dict(row) for row in rows]

    def save_template(self, name: str, content: str, user_id: str = "default") -> int:
        """
        保存回复模板

        Args:
            name: 模板名称
            content: 模板内容
            user_id: 用户ID

        Returns:
            template_id
        """
        with self.db as db:
            # 确保reply_templates表存在
            db.cursor.execute("""
                CREATE TABLE IF NOT EXISTS reply_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    user_id TEXT DEFAULT 'default',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name, user_id)
                )
            """)

            db.cursor.execute("""
                INSERT OR REPLACE INTO reply_templates (name, content, user_id, updated_at)
                VALUES (?, ?, ?, ?)
            """, (name, content, user_id, datetime.now().isoformat()))

            db.conn.commit()
            return db.cursor.lastrowid

    def get_templates(self, user_id: str = "default") -> List[Dict]:
        """获取所有回复模板"""
        with self.db as db:
            db.cursor.execute("""
                CREATE TABLE IF NOT EXISTS reply_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    user_id TEXT DEFAULT 'default',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name, user_id)
                )
            """)

            rows = db.cursor.execute("""
                SELECT * FROM reply_templates
                WHERE user_id = ?
                ORDER BY updated_at DESC
            """, (user_id,)).fetchall()

            return [dict(row) for row in rows]


# 全局实例
chat_service = ChatService()
