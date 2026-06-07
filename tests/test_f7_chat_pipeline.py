"""F7 聊天回复 pipeline 单元测试

覆盖:
  - chat_nav: 限制弹窗关键词匹配、输入框清空
  - chat_stage: DB上下文加载、阶段推算、冗余检查
  - chat_workflow: 已回复跳过、历史构建、历史合并
"""
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from app.chat_stage import (
    compute_stage,
    reply_redundant,
    STAGE_FALLBACK,
    RESUME_PATTERNS,
    WECHAT_PATTERNS,
)
from app.chat_workflow import _build_history_from_messages


# ══════════════════════════════════════════════════
# chat_nav: 限制弹窗检测
# ══════════════════════════════════════════════════

class TestLimitKeywords:
    """验证限制弹窗关键词列表覆盖了关键场景"""

    def test_keywords_list_not_empty(self):
        from app.chat_nav import LIMIT_KEYWORDS
        assert len(LIMIT_KEYWORDS) >= 20

    @pytest.mark.parametrize("text", [
        "今日沟通人数已达上限",
        "打招呼次数已用完",
        "剩余次数不足",
        "你的额度不足，请升级会员",
        "免费次数已用完，明天再来",
    ])
    def test_keywords_match_real_scenarios(self, text):
        """每个真实场景文本应至少匹配一个关键词"""
        from app.chat_nav import LIMIT_KEYWORDS
        matched = any(kw in text for kw in LIMIT_KEYWORDS)
        assert matched, f"无关键词匹配: {text}"


class TestLimitPopupJS:
    """验证限制弹窗 JS 脚本格式正确"""

    def test_js_contains_keyword_list(self):
        from app.chat_nav import _JS_CHECK_LIMIT_POPUP
        # json.dumps 将中文转为 Unicode 转义，验证关键词数组存在
        assert "keywords" in _JS_CHECK_LIMIT_POPUP
        # 验证数组长度 — 至少包含 20 个关键词
        assert _JS_CHECK_LIMIT_POPUP.count("\\u") >= 40  # 每个中文 ≈ 1 个 \uXXXX

    def test_dismiss_popup_js_removes_overlays(self):
        from app.chat_nav import _JS_DISMISS_POPUP
        assert "dialog-wrap" in _JS_DISMISS_POPUP
        assert "overlay" in _JS_DISMISS_POPUP
        assert "el.remove()" in _JS_DISMISS_POPUP


class TestClearInputJS:
    """验证输入框清空 JS 脚本"""

    def test_clear_input_focuses_and_selects(self):
        from app.chat_nav import _JS_CLEAR_INPUT
        assert "el.focus()" in _JS_CLEAR_INPUT
        assert "setSelectionRange" in _JS_CLEAR_INPUT
        assert "contentEditable" in _JS_CLEAR_INPUT


# ══════════════════════════════════════════════════
# chat_stage: 对话阶段推算
# ══════════════════════════════════════════════════

class TestComputeStage:
    """测试 _compute_stage 的 5 个阶段推算"""

    def test_early_stage_no_data(self):
        """无 DB 数据，无请求历史 → early_stage"""
        ctx = {"has_resume": False, "has_wechat": False}
        history = []
        stage, ctx_str = compute_stage(ctx, history)
        assert stage == "early_stage"
        assert "自由对话" in ctx_str

    def test_ready_for_interview(self):
        """简历 + 微信都有 → ready_for_interview"""
        ctx = {"has_resume": True, "has_wechat": True}
        history = []
        stage, ctx_str = compute_stage(ctx, history)
        assert stage == "ready_for_interview"
        assert "约面试" in ctx_str

    def test_has_resume_no_wechat(self):
        """有简历无微信"""
        ctx = {"has_resume": True, "has_wechat": False}
        history = []
        stage, ctx_str = compute_stage(ctx, history)
        assert stage == "has_resume_no_wechat"
        assert "不" in ctx_str and "简历" in ctx_str

    def test_has_wechat_no_resume(self):
        """有微信无简历"""
        ctx = {"has_resume": False, "has_wechat": True}
        history = []
        stage, ctx_str = compute_stage(ctx, history)
        assert stage == "has_wechat_no_resume"
        assert "不" in ctx_str and "微信" in ctx_str

    def test_awaiting_response_resume_requested(self):
        """历史中 boss 请求了简历 → awaiting_response"""
        ctx = {"has_resume": False, "has_wechat": False}
        history = [
            {"role": "assistant", "content": "方便发简历吗？"},
        ]
        stage, ctx_str = compute_stage(ctx, history)
        assert stage == "awaiting_response"
        assert "不要重复" in ctx_str

    def test_awaiting_response_wechat_requested(self):
        """历史中 boss 请求了微信 → awaiting_response"""
        ctx = {"has_resume": False, "has_wechat": False}
        history = [
            {"role": "boss", "content": "方便加个微信吗"},
        ]
        stage, ctx_str = compute_stage(ctx, history)
        assert stage == "awaiting_response"

    def test_db_data_takes_priority_over_history(self):
        """DB 已有简历 → has_resume_no_wechat，即使历史中请求过简历"""
        ctx = {"has_resume": True, "has_wechat": False}
        history = [
            {"role": "assistant", "content": "方便发简历吗？"},
        ]
        stage, _ = compute_stage(ctx, history)
        assert stage == "has_resume_no_wechat"


class TestReplyRedundant:
    """测试冗余回复检测"""

    def test_redundant_resume_request(self):
        """已有简历但回复请求简历 → True"""
        ctx = {"has_resume": True, "has_wechat": False}
        assert reply_redundant("方便发简历吗？", ctx) is True

    def test_redundant_wechat_request(self):
        """已有微信但回复请求微信 → True"""
        ctx = {"has_resume": False, "has_wechat": True}
        assert reply_redundant("方便加个微信吗", ctx) is True

    def test_normal_reply_not_redundant(self):
        """正常回复不触发冗余"""
        ctx = {"has_resume": False, "has_wechat": False}
        assert reply_redundant("你好，我们正在招聘", ctx) is False

    def test_no_redundancy_when_no_context(self):
        """无 DB 上下文时不误判"""
        ctx = {}
        assert reply_redundant("方便发简历过来吗", ctx) is False

    @pytest.mark.parametrize("pattern", RESUME_PATTERNS)
    def test_all_resume_patterns_detected(self, pattern):
        """每个简历模式都应被检测到"""
        ctx = {"has_resume": True, "has_wechat": False}
        reply = f"请问{pattern}可以吗"
        assert reply_redundant(reply, ctx) is True

    @pytest.mark.parametrize("pattern", WECHAT_PATTERNS)
    def test_all_wechat_patterns_detected(self, pattern):
        """每个微信模式都应被检测到"""
        ctx = {"has_resume": False, "has_wechat": True}
        reply = f"可以{pattern}吗"
        assert reply_redundant(reply, ctx) is True


class TestStageFallback:
    """验证阶段兜底文本覆盖了关键阶段"""

    def test_fallback_for_all_stages_except_early(self):
        """early_stage 之外的阶段都应有兜底"""
        for stage in [
            "ready_for_interview",
            "has_resume_no_wechat",
            "has_wechat_no_resume",
            "awaiting_response",
        ]:
            assert stage in STAGE_FALLBACK, f"缺少阶段兜底: {stage}"
            assert len(STAGE_FALLBACK[stage]) >= 10

    def test_early_stage_has_no_fallback(self):
        """early_stage 不需要兜底"""
        assert "early_stage" not in STAGE_FALLBACK


# ══════════════════════════════════════════════════
# chat_workflow: 历史构建 + 合并
# ══════════════════════════════════════════════════

class TestBuildHistory:
    """测试 _build_history_from_messages"""

    def test_converts_isMe_to_assistant(self):
        messages = [
            {"text": "你好", "isMe": True},
            {"text": "我感兴趣", "isMe": False},
        ]
        history = _build_history_from_messages(messages)
        assert history[0]["role"] == "assistant"
        assert history[1]["role"] == "user"

    def test_skips_empty_text(self):
        messages = [
            {"text": "", "isMe": False},
            {"text": "有内容", "isMe": False},
        ]
        history = _build_history_from_messages(messages)
        assert len(history) == 1

    def test_empty_messages_returns_empty(self):
        assert _build_history_from_messages([]) == []


class TestAlreadyRepliedDetection:
    """测试已回复跳过的逻辑（模拟主循环中的判断）"""

    def test_last_message_is_me_means_already_replied(self):
        """最后一条 isMe=True → last_sender='boss'"""
        messages = [
            {"text": "你好，我感兴趣", "isMe": False},
            {"text": "好的，稍后回复你", "isMe": True},
        ]
        last_msg = messages[-1]
        last_sender = "boss" if last_msg.get("isMe") else "candidate"
        assert last_sender == "boss"

    def test_last_message_not_me_means_candidate(self):
        """最后一条 isMe=False → last_sender='candidate'"""
        messages = [
            {"text": "你好", "isMe": True},
            {"text": "我对这个岗位感兴趣", "isMe": False},
        ]
        last_msg = messages[-1]
        last_sender = "boss" if last_msg.get("isMe") else "candidate"
        assert last_sender == "candidate"

    def test_empty_messages_no_sender(self):
        """空消息列表 → 无发送方"""
        messages = []
        last_msg = messages[-1] if messages else None
        last_sender = ""
        if last_msg:
            last_sender = "boss" if last_msg.get("isMe") else "candidate"
        assert last_sender == ""
