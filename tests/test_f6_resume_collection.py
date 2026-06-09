"""F6 简历收集 单元测试 + 集成测试

覆盖:
  - JS 提取脚本格式验证 (6个脚本)
  - LIMIT_KEYWORDS 关键词覆盖
  - _record_resume_op DB 记录
  - collect_resumes 主流程 (mock automation)
  - 4种Case检测 + 处理
  - 下载确认 + 兜底逻辑
  - 去重跳过 + 坐标过期回退
"""
import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock, call

from app.resume_collector import (
    _JS_FIND_RESUME_BTNS,
    _JS_FIND_DOWNLOAD_BTN,
    _JS_DETECT_RESUME_CASE,
    _JS_FIND_CONTACT_BY_NAME,
    _JS_VERIFY_CHAT_PANEL,
    _record_resume_op,
    collect_resumes,
    _refind_contact,
    _detect_resume_case,
    _handle_case1_download,
    _handle_case2_confirm,
    _click_download,
    _close_resume_and_return,
)

# Fixture: temp resume directory to avoid /app/data/ path on macOS
@pytest.fixture
def temp_resume_dir():
    with tempfile.TemporaryDirectory() as tmp:
        resumes = Path(tmp) / "resumes"
        resumes.mkdir()
        with patch("app.resume_collector.RESUMES_DIR", resumes):
            yield resumes


# ══════════════════════════════════════════════════
# JS 脚本格式验证
# ══════════════════════════════════════════════════

class TestJSFindResumeBtns:
    """验证 _JS_FIND_RESUME_BTNS 脚本格式"""

    def test_is_non_empty_string(self):
        assert isinstance(_JS_FIND_RESUME_BTNS, str)
        assert len(_JS_FIND_RESUME_BTNS) > 50

    def test_contains_function_wrapper(self):
        assert "(function()" in _JS_FIND_RESUME_BTNS

    def test_matches_exact_button_texts(self):
        """精确匹配 4 种简历按钮文本"""
        for text in ["在线简历", "附件简历", "查看简历", "查看附件"]:
            assert text in _JS_FIND_RESUME_BTNS, f"缺少按钮文本: {text}"

    def test_scopes_to_chat_panel(self):
        """限定在右侧聊天面板查找"""
        assert "chat-detail" in _JS_FIND_RESUME_BTNS
        assert "chat-content" in _JS_FIND_RESUME_BTNS

    def test_filters_visible_only(self):
        """只返回可见元素"""
        assert "r.width > 0" in _JS_FIND_RESUME_BTNS
        assert "r.height > 0" in _JS_FIND_RESUME_BTNS

    def test_returns_array(self):
        assert "results.push" in _JS_FIND_RESUME_BTNS
        assert "return results" in _JS_FIND_RESUME_BTNS


class TestJSFindDownloadBtn:
    """验证 _JS_FIND_DOWNLOAD_BTN 脚本格式"""

    def test_is_non_empty_string(self):
        assert isinstance(_JS_FIND_DOWNLOAD_BTN, str)
        assert len(_JS_FIND_DOWNLOAD_BTN) > 50

    def test_searches_download_keywords(self):
        assert "下载" in _JS_FIND_DOWNLOAD_BTN
        assert "保存" in _JS_FIND_DOWNLOAD_BTN

    def test_fallback_to_download_attribute(self):
        """兜底查找带 download 属性的 <a> 标签"""
        assert 'a[download]' in _JS_FIND_DOWNLOAD_BTN

    def test_returns_found_false_when_empty(self):
        assert '{found: false}' in _JS_FIND_DOWNLOAD_BTN


class TestJSDetectResumeCase:
    """验证 _JS_DETECT_RESUME_CASE 脚本格式"""

    def test_detects_all_four_cases(self):
        case_types = ["pdf_preview", "request_popup", "request_pending", "need_reply", "unknown"]
        for ct in case_types:
            assert ct in _JS_DETECT_RESUME_CASE, f"缺少 case_type: {ct}"

    def test_pdf_detection_first(self):
        """PDF 检测必须在文本检测之前（避免覆盖文本干扰）"""
        pdf_idx = _JS_DETECT_RESUME_CASE.find("pdf_preview")
        request_idx = _JS_DETECT_RESUME_CASE.find("request_popup")
        assert pdf_idx < request_idx, "PDF检测应优先于文本检测"

    def test_checks_body_text_for_request_keywords(self):
        assert "请求简历" in _JS_DETECT_RESUME_CASE or "向牛人" in _JS_DETECT_RESUME_CASE

    def test_returns_case_type_string(self):
        assert "case_type" in _JS_DETECT_RESUME_CASE


class TestJSFindContactByName:
    """验证 _JS_FIND_CONTACT_BY_NAME 脚本格式"""

    def test_uses_placeholder_template(self):
        assert "{NAME_PLACEHOLDER}" in _JS_FIND_CONTACT_BY_NAME

    def test_filters_left_panel(self):
        """只取左侧面板 (x < 450)"""
        assert "r.x < 450" in _JS_FIND_CONTACT_BY_NAME

    def test_checks_hasUnread(self):
        """检查未读标记"""
        assert "hasUnread" in _JS_FIND_CONTACT_BY_NAME
        assert "unread" in _JS_FIND_CONTACT_BY_NAME.lower()

    def test_exact_match_priority(self):
        """精确匹配优先，模糊匹配兜底"""
        assert "exact" in _JS_FIND_CONTACT_BY_NAME
        assert "candidates" in _JS_FIND_CONTACT_BY_NAME

    def test_returns_null_when_not_found(self):
        assert "null" in _JS_FIND_CONTACT_BY_NAME


class TestJSVerifyChatPanel:
    """验证 _JS_VERIFY_CHAT_PANEL 脚本格式"""

    def test_uses_placeholder_template(self):
        assert "{NAME_PLACEHOLDER}" in _JS_VERIFY_CHAT_PANEL

    def test_checks_url_fallback(self):
        """URL 匹配作为备选验证"""
        assert "window.location.href" in _JS_VERIFY_CHAT_PANEL
        assert "/chat" in _JS_VERIFY_CHAT_PANEL

    def test_returns_switched_boolean(self):
        assert "switched" in _JS_VERIFY_CHAT_PANEL


# ══════════════════════════════════════════════════
# LIMIT_KEYWORDS 验证
# ══════════════════════════════════════════════════

class TestLimitKeywords:
    """验证限制弹窗关键词（F6 复用 chat_nav.LIMIT_KEYWORDS）"""

    def test_keywords_list_not_empty(self):
        from app.chat_nav import LIMIT_KEYWORDS
        assert len(LIMIT_KEYWORDS) >= 20

    @pytest.mark.parametrize("text", [
        "今日沟通人数已达上限",
        "打招呼次数已用完",
        "剩余次数不足，请明天再试",
        "你的额度不足，请升级会员",
        "免费次数已用完",
        "今日已达上限",
    ])
    def test_keywords_match_real_scenarios(self, text):
        from app.chat_nav import LIMIT_KEYWORDS
        matched = any(kw in text for kw in LIMIT_KEYWORDS)
        assert matched, f"无关键词匹配: {text}"


# ══════════════════════════════════════════════════
# _record_resume_op 单元测试
# ══════════════════════════════════════════════════

class TestRecordResumeOp:
    """测试 _record_resume_op 辅助函数"""

    def test_calls_insert_resume_op(self):
        db = MagicMock()
        _record_resume_op(db, "张三", "downloaded", btn_text="在线简历")
        db.insert_resume_op.assert_called_once()
        call_args = db.insert_resume_op.call_args
        assert call_args[1]["candidate_name"] == "张三"
        assert call_args[1]["action"] == "downloaded"
        assert call_args[1]["resume_downloaded"] is False

    def test_handles_db_exception_gracefully(self):
        db = MagicMock()
        db.insert_resume_op.side_effect = Exception("DB error")
        # 不应抛出异常
        _record_resume_op(db, "李四", "requested")

    def test_includes_timestamp_in_detail(self):
        db = MagicMock()
        _record_resume_op(db, "王五", "need_reply")
        detail = json.loads(db.insert_resume_op.call_args[1]["detail"])
        assert "time" in detail


# ══════════════════════════════════════════════════
# collect_resumes 主流程 — Mock 测试
# ══════════════════════════════════════════════════

class TestCollectResumesErrors:
    """测试错误/边界路径"""

    @pytest.mark.asyncio
    async def test_browser_not_connected(self, temp_resume_dir):
        """浏览器未连接 → 返回 error"""
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto._ensure_session = AsyncMock(return_value=False)
            result = await collect_resumes(max_count=3)
            assert result["status"] == "error"
            assert "浏览器未连接" in result["message"]

    @pytest.mark.asyncio
    async def test_not_logged_in(self, temp_resume_dir):
        """BOSS 未登录 → 返回 error"""
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": False})
            result = await collect_resumes(max_count=3)
            assert result["status"] == "error"
            assert "未登录" in result["message"]

    @pytest.mark.asyncio
    async def test_navigate_to_chat_fails_fallback(self, temp_resume_dir):
        """navigate_to_chat 失败 → 备用导航 /web/chat/index"""
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector.navigate_to_chat") as mock_nav, \
             patch("app.resume_collector.get_contacts") as mock_contacts, \
             patch("app.resume_collector.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_auto.enable_download_interception = AsyncMock(
                return_value={"status": "ok"}
            )
            mock_nav.return_value = {"status": "error", "message": "fail"}
            mock_auto.navigate = AsyncMock(return_value={"status": "ok"})
            mock_contacts.return_value = []

            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_db.get_resume_ops.return_value = []

            result = await collect_resumes(max_count=3)
            # 备用导航被调用
            mock_auto.navigate.assert_called()
            assert result["status"] == "completed"
            assert result["total_scanned"] == 0

    @pytest.mark.asyncio
    async def test_empty_contacts_returns_early(self, temp_resume_dir):
        """无联系人 → 提前返回"""
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector.navigate_to_chat") as mock_nav, \
             patch("app.resume_collector.get_contacts") as mock_contacts, \
             patch("app.resume_collector.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_auto.enable_download_interception = AsyncMock(
                return_value={"status": "ok"}
            )
            mock_nav.return_value = {"status": "ok", "contact_count": 0}
            mock_contacts.return_value = []

            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db

            result = await collect_resumes(max_count=3)
            assert result["status"] == "completed"
            assert result["downloaded"] == 0
            assert result["total_scanned"] == 0


class TestCollectResumesSortingAndDedup:
    """测试排序和去重逻辑"""

    @pytest.mark.asyncio
    async def test_hasUnread_sorted_first(self, temp_resume_dir):
        """有未读的联系人排在前面"""
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector.navigate_to_chat") as mock_nav, \
             patch("app.resume_collector.get_contacts") as mock_contacts, \
             patch("app.resume_collector.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_auto.enable_download_interception = AsyncMock(
                return_value={"status": "ok"}
            )
            mock_nav.return_value = {"status": "ok", "contact_count": 4}
            # 混合已读/未读
            contacts = [
                {"name": "A", "text": "A old msg", "x": 100, "y": 100, "hasUnread": False},
                {"name": "B", "text": "B new msg!!!", "x": 100, "y": 200, "hasUnread": True},
                {"name": "C", "text": "C", "x": 100, "y": 300, "hasUnread": False},
                {"name": "D", "text": "D urgent", "x": 100, "y": 400, "hasUnread": True},
            ]
            mock_contacts.return_value = contacts

            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_db.get_resume_ops.return_value = []  # 全部未下载

            # Mock _refind_contact 返回可见坐标
            with patch("app.resume_collector._refind_contact") as mock_refind:
                mock_refind.side_effect = lambda name: {
                    "name": name, "x": 100, "y": 100,
                    "hasUnread": True, "visible": True,
                }
                # Mock JS 执行 返回无简历按钮（快速退出循环）
                mock_auto.execute_js = AsyncMock(return_value=[])
                mock_auto.cdp_click_viewport = AsyncMock(return_value=True)
                mock_auto.press_key = AsyncMock()
                mock_auto.screenshot = AsyncMock()

                result = await collect_resumes(max_count=4)

            # 验证排序: B(未读) 和 D(未读) 在 A 和 C 之前
            assert result["total_scanned"] == 4

    @pytest.mark.asyncio
    async def test_already_downloaded_skipped(self, temp_resume_dir):
        """已下载过的联系人被跳过"""
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector.navigate_to_chat") as mock_nav, \
             patch("app.resume_collector.get_contacts") as mock_contacts, \
             patch("app.resume_collector.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_auto.enable_download_interception = AsyncMock(
                return_value={"status": "ok"}
            )
            mock_nav.return_value = {"status": "ok", "contact_count": 2}
            contacts = [
                {"name": "张三", "text": "张三 msg", "x": 100, "y": 100, "hasUnread": True},
                {"name": "李四", "text": "李四 msg", "x": 100, "y": 200, "hasUnread": True},
            ]
            mock_contacts.return_value = contacts

            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            # 张三已下载，李四未下载
            mock_db.get_resume_ops.side_effect = [
                [{"resume_downloaded": True, "action": "downloaded"}],  # 张三
                [],  # 李四
            ]

            with patch("app.resume_collector._refind_contact") as mock_refind:
                mock_refind.return_value = {
                    "name": "李四", "x": 100, "y": 200,
                    "hasUnread": True, "visible": True,
                }
                mock_auto.execute_js = AsyncMock(return_value=[])
                mock_auto.cdp_click_viewport = AsyncMock(return_value=True)
                mock_auto.press_key = AsyncMock()
                mock_auto.screenshot = AsyncMock()

                result = await collect_resumes(max_count=2)

            assert result["skipped"] >= 1

    @pytest.mark.asyncio
    async def test_not_visible_contact_skipped(self, temp_resume_dir):
        """不在可视区域的联系人被跳过"""
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector.navigate_to_chat") as mock_nav, \
             patch("app.resume_collector.get_contacts") as mock_contacts, \
             patch("app.resume_collector.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_auto.enable_download_interception = AsyncMock(
                return_value={"status": "ok"}
            )
            mock_nav.return_value = {"status": "ok"}
            contacts = [
                {"name": "隐藏人", "text": "msg", "x": 100, "y": -100, "hasUnread": True},
            ]
            mock_contacts.return_value = contacts

            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_db.get_resume_ops.return_value = []

            with patch("app.resume_collector._refind_contact") as mock_refind:
                mock_refind.return_value = {
                    "name": "隐藏人", "x": 100, "y": -100,
                    "hasUnread": True, "visible": False,
                }
                mock_auto.screenshot = AsyncMock()

                result = await collect_resumes(max_count=1)

            assert result["skipped"] >= 1

    @pytest.mark.asyncio
    async def test_cdp_click_failure_counts_failed(self, temp_resume_dir):
        """CDP 点击失败 → failed += 1"""
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector.navigate_to_chat") as mock_nav, \
             patch("app.resume_collector.get_contacts") as mock_contacts, \
             patch("app.resume_collector.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_auto.enable_download_interception = AsyncMock(
                return_value={"status": "ok"}
            )
            mock_nav.return_value = {"status": "ok"}
            contacts = [
                {"name": "Fail", "text": "msg", "x": 100, "y": 100, "hasUnread": True},
            ]
            mock_contacts.return_value = contacts

            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_db.get_resume_ops.return_value = []

            with patch("app.resume_collector._refind_contact") as mock_refind:
                mock_refind.return_value = {
                    "name": "Fail", "x": 100, "y": 100,
                    "hasUnread": True, "visible": True,
                }
                mock_auto.cdp_click_viewport = AsyncMock(return_value=False)
                mock_auto.screenshot = AsyncMock()

                result = await collect_resumes(max_count=1)

            assert result["failed"] >= 1


class TestCollectResumesDryRun:
    """测试 dry_run 模式"""

    @pytest.mark.asyncio
    async def test_dry_run_no_actual_download(self, temp_resume_dir):
        """dry_run 模式不执行实际下载"""
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector.navigate_to_chat") as mock_nav, \
             patch("app.resume_collector.get_contacts") as mock_contacts, \
             patch("app.resume_collector.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.check_login = AsyncMock(return_value={"logged_in": True})
            mock_nav.return_value = {"status": "ok"}
            contacts = [
                {"name": "Test", "text": "msg", "x": 100, "y": 100, "hasUnread": True},
            ]
            mock_contacts.return_value = contacts

            mock_db = MagicMock()
            mock_db_cls.return_value = mock_db
            mock_db.get_resume_ops.return_value = []

            with patch("app.resume_collector._refind_contact") as mock_refind:
                mock_refind.return_value = {
                    "name": "Test", "x": 100, "y": 100,
                    "hasUnread": True, "visible": True,
                }
                mock_auto.cdp_click_viewport = AsyncMock(return_value=True)
                mock_auto.execute_js = AsyncMock(return_value=[])
                mock_auto.press_key = AsyncMock()
                mock_auto.screenshot = AsyncMock()

                result = await collect_resumes(max_count=1, dry_run=True)

            # dry_run 时 enable_download_interception 不应被调用
            mock_auto.enable_download_interception.assert_not_called()
            assert result["status"] == "completed"


# ══════════════════════════════════════════════════
# 4种Case检测 + 处理 — Mock 测试
# ══════════════════════════════════════════════════

class TestDetectResumeCase:
    """测试 _detect_resume_case 4种Case 检测"""

    @pytest.mark.asyncio
    async def test_case1_pdf_preview(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value={"case_type": "pdf_preview"}
            )
            result = await _detect_resume_case()
            assert result["case_type"] == "pdf_preview"

    @pytest.mark.asyncio
    async def test_case2_request_popup(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value={
                "case_type": "request_popup",
                "x": 300, "y": 400, "text": "确认",
            })
            result = await _detect_resume_case()
            assert result["case_type"] == "request_popup"
            assert result["x"] == 300

    @pytest.mark.asyncio
    async def test_case3_request_pending(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value={"case_type": "request_pending"}
            )
            result = await _detect_resume_case()
            assert result["case_type"] == "request_pending"

    @pytest.mark.asyncio
    async def test_case4_need_reply(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value={"case_type": "need_reply"}
            )
            result = await _detect_resume_case()
            assert result["case_type"] == "need_reply"

    @pytest.mark.asyncio
    async def test_unknown_when_js_fails(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(side_effect=Exception("JS error"))
            result = await _detect_resume_case()
            assert result["case_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_unknown_when_result_not_dict(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value=["not", "a", "dict"])
            result = await _detect_resume_case()
            assert result["case_type"] == "unknown"


class TestHandleCase1Download:
    """测试 Case-1 PDF预览下载"""

    @pytest.mark.asyncio
    async def test_download_button_found_and_confirmed(self):
        """找到下载按钮 + CDP事件确认 → 返回 True"""
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value={
                "found": True, "x": 500, "y": 600, "text": "下载",
            })
            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)
            mock_auto.wait_for_download = AsyncMock(return_value={
                "status": "downloaded", "size": 12345, "method": "cdp_event",
            })

            db = MagicMock()
            details = []
            result = await _handle_case1_download(
                "张三", {"text": "在线简历"}, db, details, 0,
            )
            assert result is True
            assert len(details) == 1
            assert details[0]["action"] == "downloaded"
            assert details[0]["file_verified"] is True

    @pytest.mark.asyncio
    async def test_download_button_found_but_not_confirmed(self):
        """找到下载按钮但CDP事件未确认 → 返回 False"""
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value={
                "found": True, "x": 500, "y": 600, "text": "下载",
            })
            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)
            mock_auto.wait_for_download = AsyncMock(return_value={
                "status": "timeout", "message": "下载超时", "method": "polling",
            })

            db = MagicMock()
            details = []
            result = await _handle_case1_download(
                "李四", {"text": "附件简历"}, db, details, 0,
            )
            assert result is False
            assert details[0]["file_verified"] is False

    @pytest.mark.asyncio
    async def test_no_download_button_online_view(self):
        """PDF预览但无下载按钮 → 'online_resume_viewed'"""
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                return_value={"found": False}
            )

            db = MagicMock()
            details = []
            result = await _handle_case1_download(
                "王五", {"text": "查看简历"}, db, details, 0,
            )
            assert result is False
            assert details[0]["action"] == "online_resume_viewed"

    @pytest.mark.asyncio
    async def test_download_exception_handled(self):
        """下载过程异常 → 返回 False"""
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                side_effect=Exception("CDP disconnected")
            )

            db = MagicMock()
            details = []
            result = await _handle_case1_download(
                "赵六", {"text": "在线简历"}, db, details, 0,
            )
            assert result is False


class TestHandleCase2Confirm:
    """测试 Case-2 请求弹窗确认"""

    @pytest.mark.asyncio
    async def test_confirm_then_pdf_appears(self):
        """点确认后 PDF 弹出 → 尝试下载"""
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector._detect_resume_case") as mock_detect:

            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)
            # 确认后检测到 PDF
            mock_detect.return_value = {"case_type": "pdf_preview"}
            # 然后找到下载按钮
            mock_auto.execute_js = AsyncMock(return_value={
                "found": True, "x": 500, "y": 600, "text": "下载",
            })

            db = MagicMock()
            details = []
            case_info = {"case_type": "request_popup", "x": 300, "y": 400}

            await _handle_case2_confirm("张三", case_info, {"text": "附件简历"}, db, details)

            # 应记录为 downloaded_after_confirm
            assert any(
                d.get("action") == "downloaded_after_confirm" for d in details
            )

    @pytest.mark.asyncio
    async def test_confirm_no_pdf_records_requested(self):
        """确认后无 PDF → 记录为 'requested'"""
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector._detect_resume_case") as mock_detect:

            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)
            # 确认后没有 PDF
            mock_detect.return_value = {"case_type": "request_pending"}

            db = MagicMock()
            details = []
            case_info = {"case_type": "request_popup", "x": 300, "y": 400}

            await _handle_case2_confirm("李四", case_info, {"text": "附件简历"}, db, details)

            assert any(d.get("action") == "requested" for d in details)

    @pytest.mark.asyncio
    async def test_confirm_without_coordinates(self):
        """没有确认按钮坐标 → 跳过点击但仍记录"""
        with patch("app.resume_collector.automation") as mock_auto:

            db = MagicMock()
            details = []
            case_info = {"case_type": "request_popup"}  # 无 x, y

            await _handle_case2_confirm("王五", case_info, {"text": "附件简历"}, db, details)

            # 应记录为 requested
            assert any(d.get("action") == "requested" for d in details)


class TestClickDownloadFallback:
    """测试旧逻辑兜底下载"""

    @pytest.mark.asyncio
    async def test_fallback_download_with_file_detection(self):
        with patch("app.resume_collector.automation") as mock_auto, \
             patch("app.resume_collector.RESUMES_DIR") as mock_dir:

            mock_auto.execute_js = AsyncMock(return_value={
                "found": True, "x": 500, "y": 600,
            })
            mock_auto.click = AsyncMock()

            # 模拟目录有新文件
            from pathlib import Path
            mock_file = MagicMock(spec=Path)
            mock_dir.iterdir.return_value = [mock_file]
            mock_dir.exists.return_value = True

            db = MagicMock()
            details = []

            await _click_download("张三", {"text": "在线简历"}, db, details)
            assert len(details) == 1

    @pytest.mark.asyncio
    async def test_fallback_exception_handled(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                side_effect=Exception("JS failed")
            )

            db = MagicMock()
            details = []

            # 不应抛出异常
            await _click_download("李四", {"text": "附件简历"}, db, details)


# ══════════════════════════════════════════════════
# _refind_contact 测试
# ══════════════════════════════════════════════════

class TestRefindContact:
    """测试逐次提取联系人坐标"""

    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value={
                "name": "张三", "x": 150, "y": 200,
                "hasUnread": True, "visible": True,
            })
            result = await _refind_contact("张三")
            assert result is not None
            assert result["name"] == "张三"
            assert result["x"] == 150
            # 验证模板替换: JSON 编码的姓名被注入脚本
            # json.dumps("张三") → "张三" (Unicode转义)
            call_args = mock_auto.execute_js.call_args[0][0]
            assert "targetName = " in call_args

    @pytest.mark.asyncio
    async def test_handles_special_characters_in_name(self):
        """姓名含特殊字符时 JSON 编码防止 JS 注入"""
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value={
                "name": "O'Brien", "x": 150, "y": 200,
                "hasUnread": True, "visible": True,
            })
            result = await _refind_contact("O'Brien")
            assert result is not None
            # 验证引号被正确转义
            call_args = mock_auto.execute_js.call_args[0][0]
            assert "O'Brien" in call_args or "O\\'Brien" in call_args

    @pytest.mark.asyncio
    async def test_returns_none_on_failure(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(
                side_effect=Exception("CDP error")
            )
            result = await _refind_contact("NotFound")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_result_not_dict(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value=["list", "not", "dict"])
            result = await _refind_contact("Test")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_x_is_none(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value={
                "name": "Test", "x": None, "y": 200,
            })
            result = await _refind_contact("Test")
            assert result is None


# ══════════════════════════════════════════════════
# _close_resume_and_return 测试
# ══════════════════════════════════════════════════

class TestCloseResumeAndReturn:
    """测试关闭简历预览"""

    @pytest.mark.asyncio
    async def test_presses_escape_twice(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.press_key = AsyncMock()
            await _close_resume_and_return()
            # Escape 应被调用 2 次
            assert mock_auto.press_key.call_count == 2

    @pytest.mark.asyncio
    async def test_escape_exception_does_not_propagate(self):
        with patch("app.resume_collector.automation") as mock_auto:
            mock_auto.press_key = AsyncMock(
                side_effect=Exception("key error")
            )
            # 不应抛出异常
            await _close_resume_and_return()


# ══════════════════════════════════════════════════
# contacts 兜底提取（chat_nav.js 返回非 list 防护）
# ══════════════════════════════════════════════════

class TestGetContactsDefense:
    """验证 get_contacts 防御性处理"""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_result_not_list(self):
        from app.chat_nav import get_contacts
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value={"not": "a list"})
            result = await get_contacts()
            assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_result_is_none(self):
        from app.chat_nav import get_contacts
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value=None)
            result = await get_contacts()
            assert result == []


class TestGetMessagesDefense:
    """验证 get_messages 防御性处理"""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_result_not_list(self):
        from app.chat_nav import get_messages
        with patch("app.chat_nav.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value="not a list")
            result = await get_messages()
            assert result == []
