"""F7 批量AI回复 单元测试 + 集成测试

覆盖:
  - chat_workflow: _merge_histories, _build_history_from_messages, batch_reply_workflow
  - chat_workflow: _batch_reply_impl 主流程 (mock automation)
  - chat_service: generate_reply, save_conversation, templates
  - chat_nav: check_limit_popup, dismiss_popup, clear_input, type_and_send
"""
import json
import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock, call

from app.chat_workflow import (
    _merge_histories,
    _build_history_from_messages,
    _batch_reply_impl,
    batch_reply_workflow,
)
from app.chat_stage import (
    compute_stage,
    reply_redundant,
    load_candidate_context,
    STAGE_FALLBACK,
    RESUME_PATTERNS,
    WECHAT_PATTERNS,
)


# ══════════════════════════════════════════════════
# _merge_histories 测试
# ══════════════════════════════════════════════════

class TestMergeHistories:
    """测试 DB 历史 + 浏览器历史合并"""

    def test_dedup_by_role_and_content(self):
        db_history = [
            {"role": "assistant", "content": "你好"},
            {"role": "user", "content": "我感兴趣"},
        ]
        browser_history = [
            {"role": "user", "content": "我感兴趣"},  # 重复
            {"role": "user", "content": "这是我的简历"},
        ]
        result = _merge_histories(db_history, browser_history)
        # 去重后应有 3 条（"我感兴趣" 只出现一次）
        assert len(result) == 3
        contents = [e["content"] for e in result]
        assert contents.count("我感兴趣") == 1

    def test_db_first_browser_second(self):
        """DB 历史在前，浏览器历史在后"""
        db_history = [
            {"role": "assistant", "content": "早期消息"},
        ]
        browser_history = [
            {"role": "user", "content": "最新消息"},
        ]
        result = _merge_histories(db_history, browser_history)
        assert result[0]["content"] == "早期消息"
        assert result[-1]["content"] == "最新消息"

    def test_empty_inputs_return_empty(self):
        assert _merge_histories([], []) == []
        assert _merge_histories([], []) == []

    def test_respects_max_entries(self):
        """保留最近 max_entries 条"""
        db_history = [
            {"role": "assistant", "content": f"msg_{i}"}
            for i in range(15)
        ]
        browser_history = [
            {"role": "user", "content": f"browser_{i}"}
            for i in range(15)
        ]
        result = _merge_histories(db_history, browser_history, max_entries=10)
        assert len(result) <= 10

    def test_skips_empty_content(self):
        db_history = [
            {"role": "assistant", "content": ""},
            {"role": "user", "content": "有效内容"},
        ]
        browser_history = [
            {"role": "user", "content": ""},
        ]
        result = _merge_histories(db_history, browser_history)
        assert len(result) == 1
        assert result[0]["content"] == "有效内容"

    def test_default_max_entries_is_20(self):
        """默认保留20条"""
        db_history = [
            {"role": "assistant", "content": f"m{i}"}
            for i in range(30)
        ]
        result = _merge_histories(db_history, [])
        assert len(result) <= 20

    def test_different_role_not_duplicate(self):
        """相同内容不同 role 不是重复"""
        db_history = [
            {"role": "assistant", "content": "好的"},
        ]
        browser_history = [
            {"role": "user", "content": "好的"},
        ]
        result = _merge_histories(db_history, browser_history)
        assert len(result) == 2

    def test_db_wins_over_browser_for_duplicates(self):
        """DB 先处理，相同 (role, content) 的浏览器条目被跳过，DB 版本保留"""
        db_history = [
            {"role": "user", "content": "msg", "source": "db"},
        ]
        browser_history = [
            {"role": "user", "content": "msg", "source": "browser"},
        ]
        result = _merge_histories(db_history, browser_history)
        assert len(result) == 1
        # DB 先处理，所以 DB 版本被保留
        assert result[0]["source"] == "db"


# ══════════════════════════════════════════════════
# _build_history_from_messages 测试
# ══════════════════════════════════════════════════

class TestBuildHistory:
    """测试浏览器消息 → AI history 格式转换"""

    def test_isMe_true_becomes_assistant(self):
        messages = [
            {"text": "你好，感兴趣吗", "isMe": True},
            {"text": "是的，很感兴趣", "isMe": False},
        ]
        result = _build_history_from_messages(messages)
        assert result[0]["role"] == "assistant"
        assert result[1]["role"] == "user"

    def test_skips_empty_text(self):
        messages = [
            {"text": "", "isMe": False},
            {"text": "   ", "isMe": True},
            {"text": "有效消息", "isMe": False},
        ]
        result = _build_history_from_messages(messages)
        assert len(result) == 1
        assert result[0]["content"] == "有效消息"

    def test_empty_input_returns_empty(self):
        assert _build_history_from_messages([]) == []

    def test_preserves_content_text(self):
        messages = [
            {"text": "Hello World!", "isMe": True},
        ]
        result = _build_history_from_messages(messages)
        assert result[0]["content"] == "Hello World!"

    def test_strips_whitespace_from_text(self):
        messages = [
            {"text": "  前后空格  ", "isMe": False},
        ]
        result = _build_history_from_messages(messages)
        assert result[0]["content"] == "前后空格"


# ══════════════════════════════════════════════════
# _batch_reply_impl 主流程 — Mock 测试
# ══════════════════════════════════════════════════

class TestBatchReplyImplErrors:
    """测试错误/边界路径"""

    @pytest.mark.asyncio
    async def test_browser_not_connected(self):
        with patch("app.chat_workflow.automation") as mock_auto:
            mock_auto._ensure_session = AsyncMock(return_value=False)
            result = await _batch_reply_impl(max_count=3)
            assert result["status"] == "error"
            assert "浏览器未连接" in result["message"]

    @pytest.mark.asyncio
    async def test_not_logged_in(self):
        with patch("app.chat_workflow.automation") as mock_auto:
            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": False})
            result = await _batch_reply_impl(max_count=3)
            assert result["status"] == "error"
            assert "未登录" in result["message"]

    @pytest.mark.asyncio
    async def test_navigate_to_chat_fails(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav:
            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "error", "message": "导航失败"}
            result = await _batch_reply_impl(max_count=3)
            assert result["status"] == "error"
            assert "导航" in result["message"]

    @pytest.mark.asyncio
    async def test_no_unread_messages_returns_early(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts:
            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok", "contact_count": 3}
            # 所有联系人都没有未读
            mock_contacts.return_value = [
                {"name": "A", "hasUnread": False},
                {"name": "B", "hasUnread": False},
            ]
            result = await _batch_reply_impl(max_count=3)
            assert result["status"] == "completed"
            assert result["replied"] == 0
            assert "没有未读" in result.get("message", "")


class TestBatchReplyImplLimitPopup:
    """测试限制弹窗检测"""

    @pytest.mark.asyncio
    async def test_limit_popup_terminates_loop(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts, \
             patch("app.chat_workflow.check_limit_popup") as mock_limit, \
             patch("app.chat_workflow.dismiss_popup") as mock_dismiss:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            mock_contacts.return_value = [
                {"name": "A", "hasUnread": True, "x": 100, "y": 100},
            ]
            # 检测到限制弹窗
            mock_limit.return_value = "已达上限"
            mock_auto.screenshot = AsyncMock()

            result = await _batch_reply_impl(max_count=3)
            # 弹窗被关闭
            mock_dismiss.assert_called_once()
            assert result["replied"] == 0


class TestBatchReplyImplAlreadyReplied:
    """测试已回复跳过逻辑"""

    @pytest.mark.asyncio
    async def test_last_message_is_me_skips(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts, \
             patch("app.chat_workflow.check_limit_popup") as mock_limit, \
             patch("app.chat_workflow.click_contact") as mock_click, \
             patch("app.chat_workflow.get_messages") as mock_msgs:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            mock_contacts.return_value = [
                {"name": "张三", "hasUnread": True, "x": 100, "y": 100},
            ]
            mock_limit.return_value = None
            mock_click.return_value = True
            # 最后一条是我们发的
            mock_msgs.return_value = [
                {"text": "你好，我对这个岗位感兴趣", "isMe": False},
                {"text": "好的，稍后回复", "isMe": True},
            ]
            mock_auto.screenshot = AsyncMock()

            result = await _batch_reply_impl(max_count=1)
            assert result["skipped"] >= 1

    @pytest.mark.asyncio
    async def test_empty_messages_skips(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts, \
             patch("app.chat_workflow.check_limit_popup") as mock_limit, \
             patch("app.chat_workflow.click_contact") as mock_click, \
             patch("app.chat_workflow.get_messages") as mock_msgs:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            mock_contacts.return_value = [
                {"name": "李四", "hasUnread": True, "x": 100, "y": 100},
            ]
            mock_limit.return_value = None
            mock_click.return_value = True
            mock_msgs.return_value = []  # 无消息
            mock_auto.screenshot = AsyncMock()

            result = await _batch_reply_impl(max_count=1)
            assert result["skipped"] >= 1


class TestBatchReplyImplAIFallback:
    """测试 AI 生成降级逻辑"""

    @pytest.mark.asyncio
    async def test_ai_fails_uses_template_fallback(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts, \
             patch("app.chat_workflow.check_limit_popup") as mock_limit, \
             patch("app.chat_workflow.click_contact") as mock_click, \
             patch("app.chat_workflow.get_messages") as mock_msgs, \
             patch("app.chat_workflow.load_candidate_context") as mock_load, \
             patch("app.chat_workflow.compute_stage") as mock_stage, \
             patch("app.chat_workflow.reply_redundant") as mock_redundant, \
             patch("app.chat_workflow.chat_service") as mock_svc, \
             patch("app.chat_workflow.type_and_send") as mock_send:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            mock_contacts.return_value = [
                {"name": "Test", "hasUnread": True, "x": 100, "y": 100},
            ]
            mock_limit.return_value = None
            mock_click.return_value = True
            mock_msgs.return_value = [
                {"text": "这个岗位还有吗", "isMe": False},
            ]
            mock_load.return_value = {
                "has_resume": False, "has_wechat": False,
                "wechat": "", "status": "", "db_chat_history": [],
            }
            mock_stage.return_value = ("early_stage", "阶段: early_stage")
            mock_redundant.return_value = False

            # AI 失败 → 返回 (None, "error")
            mock_svc.generate_reply = AsyncMock(return_value=(None, "API error"))
            mock_svc.save_conversation = MagicMock()

            mock_send.return_value = {"status": "ok"}
            mock_auto.screenshot = AsyncMock()

            result = await _batch_reply_impl(max_count=1)
            assert result["replied"] == 1
            # 应使用模板兜底
            assert any(
                r.get("generation_method") == "template_fallback"
                for r in result.get("results", [])
            )

    @pytest.mark.asyncio
    async def test_redundant_reply_uses_stage_fallback(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts, \
             patch("app.chat_workflow.check_limit_popup") as mock_limit, \
             patch("app.chat_workflow.click_contact") as mock_click, \
             patch("app.chat_workflow.get_messages") as mock_msgs, \
             patch("app.chat_workflow.load_candidate_context") as mock_load, \
             patch("app.chat_workflow.compute_stage") as mock_stage, \
             patch("app.chat_workflow.reply_redundant") as mock_redundant, \
             patch("app.chat_workflow.chat_service") as mock_svc, \
             patch("app.chat_workflow.type_and_send") as mock_send:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            mock_contacts.return_value = [
                {"name": "Test", "hasUnread": True, "x": 100, "y": 100},
            ]
            mock_limit.return_value = None
            mock_click.return_value = True
            mock_msgs.return_value = [
                {"text": "你好", "isMe": False},
            ]
            mock_load.return_value = {
                "has_resume": True, "has_wechat": False,
            }
            mock_stage.return_value = ("has_resume_no_wechat", "阶段: has_resume_no_wechat")
            mock_redundant.return_value = True  # 冗余!

            mock_svc.generate_reply = AsyncMock(
                return_value=("方便发简历吗？", "")
            )
            mock_send.return_value = {"status": "ok"}
            mock_auto.screenshot = AsyncMock()

            result = await _batch_reply_impl(max_count=1)
            assert result["replied"] == 1
            assert any(
                r.get("generation_method") == "stage_fallback"
                for r in result.get("results", [])
            )


class TestBatchReplyImplSendFlow:
    """测试发送流程"""

    @pytest.mark.asyncio
    async def test_successful_reply(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts, \
             patch("app.chat_workflow.check_limit_popup") as mock_limit, \
             patch("app.chat_workflow.click_contact") as mock_click, \
             patch("app.chat_workflow.get_messages") as mock_msgs, \
             patch("app.chat_workflow.load_candidate_context") as mock_load, \
             patch("app.chat_workflow.compute_stage") as mock_stage, \
             patch("app.chat_workflow.reply_redundant") as mock_redundant, \
             patch("app.chat_workflow.chat_service") as mock_svc, \
             patch("app.chat_workflow.type_and_send") as mock_send, \
             patch("app.chat_workflow.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            mock_contacts.return_value = [
                {"name": "候选人A", "hasUnread": True, "x": 100, "y": 100},
            ]
            mock_limit.return_value = None
            mock_click.return_value = True
            mock_msgs.return_value = [
                {"text": "你们还招人吗", "isMe": False},
            ]
            mock_load.return_value = {
                "has_resume": False, "has_wechat": False,
                "wechat": "", "status": "", "db_chat_history": [],
            }
            mock_stage.return_value = ("early_stage", "阶段: early_stage")
            mock_redundant.return_value = False
            mock_svc.generate_reply = AsyncMock(
                return_value=("您好，我们还在招聘，方便聊一下吗？", "")
            )
            mock_svc.save_conversation = MagicMock()
            mock_send.return_value = {"status": "ok"}

            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_auto.screenshot = AsyncMock()

            result = await _batch_reply_impl(max_count=1)
            assert result["replied"] == 1
            assert result["failed"] == 0
            results = result.get("results", [])
            assert len(results) == 1
            assert results[0]["success"] is True
            assert results[0]["generation_method"] == "ai"

    @pytest.mark.asyncio
    async def test_send_failure_counts_failed(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts, \
             patch("app.chat_workflow.check_limit_popup") as mock_limit, \
             patch("app.chat_workflow.click_contact") as mock_click, \
             patch("app.chat_workflow.get_messages") as mock_msgs, \
             patch("app.chat_workflow.load_candidate_context") as mock_load, \
             patch("app.chat_workflow.compute_stage") as mock_stage, \
             patch("app.chat_workflow.reply_redundant") as mock_redundant, \
             patch("app.chat_workflow.chat_service") as mock_svc, \
             patch("app.chat_workflow.type_and_send") as mock_send:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            mock_contacts.return_value = [
                {"name": "Test", "hasUnread": True, "x": 100, "y": 100},
            ]
            mock_limit.return_value = None
            mock_click.return_value = True
            mock_msgs.return_value = [
                {"text": "你好", "isMe": False},
            ]
            mock_load.return_value = {
                "has_resume": False, "has_wechat": False,
            }
            mock_stage.return_value = ("early_stage", "...")
            mock_redundant.return_value = False
            mock_svc.generate_reply = AsyncMock(
                return_value=("你好！", "")
            )
            # 发送失败
            mock_send.return_value = {"status": "error", "message": "输入框未找到"}
            mock_auto.screenshot = AsyncMock()

            result = await _batch_reply_impl(max_count=1, dry_run=False)
            assert result["failed"] >= 1

    @pytest.mark.asyncio
    async def test_dry_run_no_actual_send(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts, \
             patch("app.chat_workflow.check_limit_popup") as mock_limit, \
             patch("app.chat_workflow.click_contact") as mock_click, \
             patch("app.chat_workflow.get_messages") as mock_msgs, \
             patch("app.chat_workflow.load_candidate_context") as mock_load, \
             patch("app.chat_workflow.compute_stage") as mock_stage, \
             patch("app.chat_workflow.reply_redundant") as mock_redundant, \
             patch("app.chat_workflow.chat_service") as mock_svc:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            mock_contacts.return_value = [
                {"name": "Test", "hasUnread": True, "x": 100, "y": 100},
            ]
            mock_limit.return_value = None
            mock_click.return_value = True
            mock_msgs.return_value = [
                {"text": "你好", "isMe": False},
            ]
            mock_load.return_value = {"has_resume": False, "has_wechat": False}
            mock_stage.return_value = ("early_stage", "...")
            mock_redundant.return_value = False
            mock_svc.generate_reply = AsyncMock(
                return_value=("你好！", "")
            )
            mock_auto.screenshot = AsyncMock()

            result = await _batch_reply_impl(max_count=1, dry_run=True)
            assert result["replied"] == 1
            assert result["dry_run"] is True
            # save_conversation 不应被调用
            mock_svc.save_conversation.assert_not_called()


class TestBatchReplyImplDbContext:
    """测试 DB 上下文加载 + 阶段推算集成"""

    @pytest.mark.asyncio
    async def test_load_candidate_context_failure_uses_defaults(self):
        with patch("app.chat_workflow.automation") as mock_auto, \
             patch("app.chat_workflow.navigate_to_chat") as mock_nav, \
             patch("app.chat_workflow.get_contacts") as mock_contacts, \
             patch("app.chat_workflow.check_limit_popup") as mock_limit, \
             patch("app.chat_workflow.click_contact") as mock_click, \
             patch("app.chat_workflow.get_messages") as mock_msgs, \
             patch("app.chat_workflow.load_candidate_context") as mock_load, \
             patch("app.chat_workflow.compute_stage") as mock_stage, \
             patch("app.chat_workflow.reply_redundant") as mock_redundant, \
             patch("app.chat_workflow.chat_service") as mock_svc, \
             patch("app.chat_workflow.type_and_send") as mock_send, \
             patch("app.chat_workflow.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            mock_contacts.return_value = [
                {"name": "Test", "hasUnread": True, "x": 100, "y": 100},
            ]
            mock_limit.return_value = None
            mock_click.return_value = True
            mock_msgs.return_value = [
                {"text": "你好", "isMe": False},
            ]
            # DB 上下文加载失败
            mock_load.side_effect = Exception("DB error")
            mock_stage.return_value = ("early_stage", "...")
            mock_redundant.return_value = False
            mock_svc.generate_reply = AsyncMock(
                return_value=("你好！", "")
            )
            mock_svc.save_conversation = MagicMock()
            mock_send.return_value = {"status": "ok"}

            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_auto.screenshot = AsyncMock()

            result = await _batch_reply_impl(max_count=1)
            # 应继续执行，使用默认上下文
            assert result["replied"] == 1


# ══════════════════════════════════════════════════
# chat_service.generate_reply 测试 (mock HTTP)
# ══════════════════════════════════════════════════

class TestGenerateReply:
    """测试 DeepSeek API 回复生成"""

    @pytest.mark.asyncio
    async def test_returns_template_directly(self):
        from app.chat_service import ChatService
        svc = ChatService()
        reply, error = await svc.generate_reply(
            candidate_name="Test",
            candidate_message="你好",
            template="自定义模板内容",
        )
        assert reply == "自定义模板内容"
        assert error == ""
        await svc.close()

    @pytest.mark.asyncio
    async def test_no_api_key_returns_error(self):
        from app.chat_service import ChatService
        svc = ChatService()
        with patch("app.chat_service.settings") as mock_settings:
            mock_settings.DEEPSEEK_API_KEY = ""
            reply, error = await svc.generate_reply(
                candidate_name="Test",
                candidate_message="你好",
            )
        assert reply is None
        assert "API_KEY" in error
        await svc.close()

    @pytest.mark.asyncio
    async def test_successful_api_call(self):
        from app.chat_service import ChatService
        svc = ChatService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "您好，请问有什么可以帮您？"}}],
        }

        with patch("app.chat_service.settings") as mock_settings:
            mock_settings.DEEPSEEK_API_KEY = "sk-test"
            mock_settings.DEEPSEEK_BASE_URL = "https://api.test.com"
            mock_settings.DEEPSEEK_MODEL = "deepseek-chat"
            svc.client.post = AsyncMock(return_value=mock_response)

            reply, error = await svc.generate_reply(
                candidate_name="张三",
                candidate_message="这个岗位还在招人吗",
            )
        assert reply == "您好，请问有什么可以帮您？"
        assert error == ""
        await svc.close()

    @pytest.mark.asyncio
    async def test_api_http_error(self):
        from app.chat_service import ChatService
        svc = ChatService()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch("app.chat_service.settings") as mock_settings:
            mock_settings.DEEPSEEK_API_KEY = "sk-test"
            mock_settings.DEEPSEEK_BASE_URL = "https://api.test.com"
            svc.client.post = AsyncMock(return_value=mock_response)

            reply, error = await svc.generate_reply(
                candidate_name="Test",
                candidate_message="你好",
            )
        assert reply is None
        assert "API调用失败" in error
        await svc.close()

    @pytest.mark.asyncio
    async def test_api_exception_returns_error(self):
        from app.chat_service import ChatService
        svc = ChatService()

        with patch("app.chat_service.settings") as mock_settings:
            mock_settings.DEEPSEEK_API_KEY = "sk-test"
            mock_settings.DEEPSEEK_BASE_URL = "https://api.test.com"
            svc.client.post = AsyncMock(
                side_effect=Exception("Connection refused")
            )

            reply, error = await svc.generate_reply(
                candidate_name="Test",
                candidate_message="你好",
            )
        assert reply is None
        assert "API调用异常" in error
        await svc.close()

    @pytest.mark.asyncio
    async def test_stage_context_injected_into_system_prompt(self):
        from app.chat_service import ChatService
        svc = ChatService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "好的，方便约面试吗？"}}],
        }

        with patch("app.chat_service.settings") as mock_settings:
            mock_settings.DEEPSEEK_API_KEY = "sk-test"
            mock_settings.DEEPSEEK_BASE_URL = "https://api.test.com"
            mock_settings.DEEPSEEK_MODEL = "deepseek-chat"
            svc.client.post = AsyncMock(return_value=mock_response)

            reply, _ = await svc.generate_reply(
                candidate_name="张三",
                candidate_message="我有3年经验",
                stage_context="阶段: ready_for_interview\n已知: 已收到简历\n注意: 推动约面试",
            )

            # 验证 system prompt 包含阶段信息
            call_args = svc.client.post.call_args
            messages = call_args[1]["json"]["messages"]
            system_msg = messages[0]["content"]
            assert "ready_for_interview" in system_msg

        await svc.close()

    @pytest.mark.asyncio
    async def test_history_included_in_messages(self):
        from app.chat_service import ChatService
        svc = ChatService()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "好的"}}],
        }

        with patch("app.chat_service.settings") as mock_settings:
            mock_settings.DEEPSEEK_API_KEY = "sk-test"
            mock_settings.DEEPSEEK_BASE_URL = "https://api.test.com"
            mock_settings.DEEPSEEK_MODEL = "deepseek-chat"
            svc.client.post = AsyncMock(return_value=mock_response)

            history = [
                {"role": "assistant", "content": "你好"},
                {"role": "user", "content": "我很感兴趣"},
            ]
            await svc.generate_reply(
                candidate_name="Test",
                candidate_message="最新消息",
                history=history,
            )

            call_args = svc.client.post.call_args
            messages = call_args[1]["json"]["messages"]
            # system + history + user message
            assert len(messages) >= 3

        await svc.close()


# ══════════════════════════════════════════════════
# chat_nav 额外测试
# ══════════════════════════════════════════════════

class TestCheckLimitPopup:
    """测试 check_limit_popup（扩展测试）"""

    @pytest.mark.asyncio
    async def test_hit_returns_keyword(self):
        from app.chat_nav import check_limit_popup
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value='{"hit": true, "keyword": "已达上限", "text": "今日已达上限"}'
            )
            result = await check_limit_popup()
            assert result == "已达上限"

    @pytest.mark.asyncio
    async def test_no_hit_returns_none(self):
        from app.chat_nav import check_limit_popup
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value='{"hit": false}'
            )
            result = await check_limit_popup()
            assert result is None

    @pytest.mark.asyncio
    async def test_dict_result_works(self):
        from app.chat_nav import check_limit_popup
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value={"hit": True, "keyword": "次数已用完"}
            )
            result = await check_limit_popup()
            assert result == "次数已用完"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_none(self):
        from app.chat_nav import check_limit_popup
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value="not valid json {"
            )
            result = await check_limit_popup()
            assert result is None


class TestDismissPopup:
    """测试 dismiss_popup"""

    @pytest.mark.asyncio
    async def test_executes_js_and_escape(self):
        from app.chat_nav import dismiss_popup
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock()
            mock_auto.press_key = AsyncMock()

            await dismiss_popup()

            mock_auto.execute_js.assert_called_once()
            mock_auto.press_key.assert_called_once_with("Escape")

    @pytest.mark.asyncio
    async def test_exception_does_not_propagate(self):
        from app.chat_nav import dismiss_popup
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                side_effect=Exception("JS error")
            )

            # 不应抛出异常
            await dismiss_popup()


class TestClearInput:
    """测试 clear_input"""

    @pytest.mark.asyncio
    async def test_js_ok_presses_backspace(self):
        from app.chat_nav import clear_input
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value='{"ok": true}'
            )
            mock_auto.press_key = AsyncMock()

            result = await clear_input()
            assert result is True
            mock_auto.press_key.assert_called_once_with("BackSpace")

    @pytest.mark.asyncio
    async def test_js_not_ok_returns_false(self):
        from app.chat_nav import clear_input
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value='{"ok": false, "reason": "not_found"}'
            )
            result = await clear_input()
            assert result is False

    @pytest.mark.asyncio
    async def test_dict_result_works(self):
        from app.chat_nav import clear_input
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value={"ok": True}
            )
            mock_auto.press_key = AsyncMock()

            result = await clear_input()
            assert result is True

    @pytest.mark.asyncio
    async def test_exception_returns_false(self):
        from app.chat_nav import clear_input
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                side_effect=Exception("CDP error")
            )
            result = await clear_input()
            assert result is False


class TestTypeAndSend:
    """测试 type_and_send"""

    @pytest.mark.asyncio
    async def test_no_input_returns_error(self):
        from app.chat_nav import type_and_send
        with patch("app.chat_nav.find_input") as mock_find:
            mock_find.return_value = {"input": None, "send": None}
            result = await type_and_send("你好")
            assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_with_send_button(self):
        from app.chat_nav import type_and_send, find_input
        with patch("app.chat_nav.automation") as mock_auto, \
             patch("app.chat_nav.clear_input") as mock_clear:
            mock_auto.click = AsyncMock()
            mock_auto.type_text = AsyncMock()
            mock_auto.press_key = AsyncMock()
            mock_clear.return_value = True

            # 需要 mock find_input 返回有 send 按钮
            with patch("app.chat_nav.find_input") as mock_find:
                mock_find.return_value = {
                    "input": {"x": 400, "y": 500},
                    "send": {"x": 600, "y": 500},
                }
                result = await type_and_send("测试消息")
            assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_without_send_button_uses_return(self):
        from app.chat_nav import type_and_send
        with patch("app.chat_nav.automation") as mock_auto, \
             patch("app.chat_nav.clear_input") as mock_clear, \
             patch("app.chat_nav.find_input") as mock_find:
            mock_auto.click = AsyncMock()
            mock_auto.type_text = AsyncMock()
            mock_auto.press_key = AsyncMock()
            mock_clear.return_value = True
            mock_find.return_value = {
                "input": {"x": 400, "y": 500},
                "send": None,  # 无发送按钮
            }
            result = await type_and_send("测试消息")
            assert result["status"] == "ok"
            # 应使用 Return 键
            mock_auto.press_key.assert_called_with("Return")


# ══════════════════════════════════════════════════
# batch_reply_workflow 同步包装器测试
# ══════════════════════════════════════════════════

class TestBatchReplyWorkflowSync:
    """测试同步入口包装器"""

    def test_batch_reply_workflow_function_exists(self):
        """batch_reply_workflow 是有效的同步入口"""
        import inspect
        assert callable(batch_reply_workflow)
        sig = inspect.signature(batch_reply_workflow)
        params = list(sig.parameters.keys())
        assert "max_count" in params
        assert "dry_run" in params


# ══════════════════════════════════════════════════
# load_candidate_context 测试
# ══════════════════════════════════════════════════

class TestLoadCandidateContext:
    """测试从 DB 加载候选人上下文"""

    def test_returns_defaults_when_no_data(self):
        db = MagicMock()
        db.cursor = MagicMock()
        db.cursor.execute.return_value = db.cursor
        db.cursor.fetchone.return_value = None
        db.get_resume_ops.return_value = []
        db.get_chat_session.return_value = None

        ctx = load_candidate_context(db, uid=None, name="Unknown")
        assert ctx["has_resume"] is False
        assert ctx["has_wechat"] is False

    def test_detects_resume_from_candidate_record(self):
        db = MagicMock()
        db.cursor = MagicMock()
        # 有 resume_path
        db.cursor.fetchone.return_value = {
            "resume_path": "/data/resumes/张三.pdf",
            "status": "active",
        }
        db.get_resume_ops.return_value = []
        db.get_chat_session.return_value = None

        ctx = load_candidate_context(db, uid="uid123", name="张三")
        assert ctx["has_resume"] is True

    def test_detects_wechat_from_ops(self):
        db = MagicMock()
        db.cursor = MagicMock()
        db.cursor.fetchone.return_value = None
        db.get_resume_ops.return_value = [
            {"wechat_exchanged": True},
        ]
        db.get_chat_session.return_value = None

        ctx = load_candidate_context(db, uid=None, name="李四")
        assert ctx["has_wechat"] is True

    def test_loads_db_chat_history(self):
        db = MagicMock()
        db.cursor = MagicMock()
        db.cursor.fetchone.return_value = None
        db.get_resume_ops.return_value = []
        db.get_chat_session.return_value = {
            "history": [
                {"role": "assistant", "content": "你好"},
            ],
        }

        ctx = load_candidate_context(db, uid=None, name="王五")
        assert len(ctx["db_chat_history"]) == 1

    def test_db_exceptions_yield_defaults(self):
        db = MagicMock()
        db.cursor = MagicMock()
        db.cursor.execute.side_effect = Exception("DB error")
        db.get_resume_ops.side_effect = Exception("DB error")
        db.get_chat_session.side_effect = Exception("DB error")

        ctx = load_candidate_context(db, uid=None, name="Error")
        assert ctx["has_resume"] is False
        assert ctx["has_wechat"] is False
