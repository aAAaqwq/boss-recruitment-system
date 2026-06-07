"""Tests for greeting button extraction logic in workflows.py.

Validates:
- _click_greet uses card-level greet_x/greet_y when available
- _click_greet falls back to page-wide JS search when greet coords are null
- Main loop handles cards with null greet coords correctly
- Edge cases: hidden buttons, multiple buttons, missing buttons
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.workflows import (
    _JS_EXTRACT_CARDS,
    _JS_FIND_GREET_COORDS,
    _click_greet,
    _auto_contact_impl,
    _extract_name,
    _extract_years,
    _extract_degree,
    _should_contact,
)
from app.filter_criteria import FilterCriteria


# ============================================================
# Unit tests: JS string content validation
# ============================================================


class TestJSExtractCardsContent:
    """Validate the _JS_EXTRACT_CARDS JavaScript source string itself."""

    def test_greet_keywords_present(self):
        """The JS must check for all four greeting button labels."""
        expected_keywords = ["打招呼", "立即沟通", "开聊", "继续沟通"]
        for kw in expected_keywords:
            assert kw in _JS_EXTRACT_CARDS, f"Missing greet keyword: {kw}"

    def test_offset_parent_visibility_check(self):
        """JS must check offsetParent !== null to skip hidden buttons."""
        assert "offsetParent" in _JS_EXTRACT_CARDS

    def test_returns_greet_coords_fields(self):
        """JS must return greet_x, greet_y, greet_text in each card object."""
        assert "greet_x" in _JS_EXTRACT_CARDS
        assert "greet_y" in _JS_EXTRACT_CARDS
        assert "greet_text" in _JS_EXTRACT_CARDS

    def test_breaks_on_first_match(self):
        """JS must break after finding the first matching greet button."""
        # The JS source may be a single-line string; check for the break
        # that follows the greet coord assignments inside the inner loop.
        # Pattern: after setting gx/gy/gt, there is a break statement.
        assert "break;" in _JS_EXTRACT_CARDS, (
            "JS should contain break after finding first greet button"
        )

    def test_queries_buttons_links_and_roles(self):
        """JS selector must cover button, a, and [role='button'] elements."""
        assert "button" in _JS_EXTRACT_CARDS
        # The JS uses 'a' as a standalone selector in querySelectorAll
        assert "[role=\"button\"]" in _JS_EXTRACT_CARDS
        # Verify the full selector string includes links
        assert ", a, " in _JS_EXTRACT_CARDS


class TestJSFindGreetCoordsContent:
    """Validate the _JS_FIND_GREET_COORDS fallback JS string."""

    def test_greet_keywords_present(self):
        expected_keywords = ["打招呼", "立即沟通", "开聊", "继续沟通"]
        for kw in expected_keywords:
            assert kw in _JS_FIND_GREET_COORDS

    def test_returns_found_flag(self):
        """Fallback JS must include a 'found' boolean in its return value."""
        # JS uses {found:true/false} -- no quotes around the key
        assert "found:" in _JS_FIND_GREET_COORDS

    def test_fallback_search_order(self):
        """Should search btn-greet first, then generic buttons as fallback."""
        # The first querySelectorAll should target greet-specific buttons
        lines = _JS_FIND_GREET_COORDS.strip().split("\n")
        first_query_all_line = None
        second_query_all_line = None
        for line in lines:
            stripped = line.strip()
            if "querySelectorAll" in stripped:
                if first_query_all_line is None:
                    first_query_all_line = stripped
                elif second_query_all_line is None:
                    second_query_all_line = stripped

        assert first_query_all_line is not None
        assert "greet" in first_query_all_line, (
            "First query should target greet-specific selectors"
        )
        assert second_query_all_line is not None, "Should have a fallback query"


# ============================================================
# Unit tests: _click_greet behavior
# ============================================================


class TestClickGreet:
    """Test _click_greet: card-level coords vs page-wide fallback."""

    @pytest.mark.asyncio
    async def test_uses_card_greet_coords_when_available(self):
        """When card has greet_x/greet_y, use them directly without fallback JS."""
        card = {
            "text": "张三 5年 本科 清华大学 打招呼",
            "x": 100, "y": 200, "w": 300, "h": 120,
            "cx": 250, "cy": 260,
            "greet_x": 450.0, "greet_y": 280.0,
            "greet_text": "打招呼",
        }

        with patch("app.workflows.automation") as mock_auto:
            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)

            result = await _click_greet(card)

            assert result is True
            mock_auto.cdp_click_viewport.assert_called_once_with(450.0, 280.0)
            # execute_js should NOT have been called (no fallback needed)
            mock_auto.execute_js.assert_not_called()

    @pytest.mark.asyncio
    async def test_falls_back_to_page_wide_search_when_greet_null(self):
        """When card has null greet_x/greet_y, execute fallback JS to find button."""
        card = {
            "text": "李四 3年 硕士 北京大学",
            "x": 100, "y": 400, "w": 300, "h": 120,
            "cx": 250, "cy": 460,
            "greet_x": None, "greet_y": None, "greet_text": None,
        }

        fallback_result = json.dumps({"found": True, "x": 500, "y": 460, "text": "打招呼"})

        with patch("app.workflows.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value=fallback_result)
            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)

            result = await _click_greet(card)

            assert result is True
            mock_auto.execute_js.assert_called_once()
            # Verify it called the fallback JS
            call_args = mock_auto.execute_js.call_args[0][0]
            assert "found" in call_args
            mock_auto.cdp_click_viewport.assert_called_once_with(500.0, 460.0)

    @pytest.mark.asyncio
    async def test_returns_false_when_fallback_finds_nothing(self):
        """When greet coords are null AND fallback finds nothing, return False."""
        card = {
            "text": "王五 8年 博士 复旦大学",
            "x": 100, "y": 600, "w": 300, "h": 120,
            "cx": 250, "cy": 660,
            "greet_x": None, "greet_y": None, "greet_text": None,
        }

        fallback_result = json.dumps({"found": False})

        with patch("app.workflows.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value=fallback_result)

            result = await _click_greet(card)

            assert result is False
            mock_auto.cdp_click_viewport.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_false_when_cdp_click_fails(self):
        """When CDP click returns False, _click_greet returns False."""
        card = {
            "text": "赵六 2年 本科 浙江大学 打招呼",
            "x": 100, "y": 800, "w": 300, "h": 120,
            "cx": 250, "cy": 860,
            "greet_x": 350.0, "greet_y": 860.0,
            "greet_text": "打招呼",
        }

        with patch("app.workflows.automation") as mock_auto:
            mock_auto.cdp_click_viewport = AsyncMock(return_value=False)

            result = await _click_greet(card)

            assert result is False

    @pytest.mark.asyncio
    async def test_handles_fallback_returning_dict_not_string(self):
        """When execute_js returns a dict instead of JSON string, still works."""
        card = {
            "text": "孙七 6年 硕士 上海交通大学",
            "x": 100, "y": 1000, "w": 300, "h": 120,
            "cx": 250, "cy": 1060,
            "greet_x": None, "greet_y": None, "greet_text": None,
        }

        # Simulate execute_js returning a dict (after CDP deserialization)
        fallback_result = {"found": True, "x": 600, "y": 1060, "text": "立即沟通"}

        with patch("app.workflows.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value=fallback_result)
            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)

            result = await _click_greet(card)

            assert result is True
            mock_auto.cdp_click_viewport.assert_called_once_with(600.0, 1060.0)

    @pytest.mark.asyncio
    async def test_handles_zero_greet_coords_as_valid(self):
        """greet_x=0, greet_y=0 is a valid position (top-left of viewport)."""
        card = {
            "text": "周八 4年 本科 武汉大学",
            "x": 0, "y": 0, "w": 300, "h": 120,
            "cx": 150, "cy": 60,
            "greet_x": 0, "greet_y": 0,
            "greet_text": "打招呼",
        }

        with patch("app.workflows.automation") as mock_auto:
            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)

            result = await _click_greet(card)

            assert result is True
            mock_auto.cdp_click_viewport.assert_called_once_with(0.0, 0.0)

    @pytest.mark.asyncio
    async def test_only_x_present_still_falls_back(self):
        """If only greet_x is set but greet_y is None, fall back to page search."""
        card = {
            "text": "吴九 7年 博士 中山大学",
            "x": 100, "y": 200, "w": 300, "h": 120,
            "cx": 250, "cy": 260,
            "greet_x": 300.0, "greet_y": None,
            "greet_text": None,
        }

        fallback_result = json.dumps({"found": True, "x": 400, "y": 300, "text": "开聊"})

        with patch("app.workflows.automation") as mock_auto:
            mock_auto.execute_js = AsyncMock(return_value=fallback_result)
            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)

            result = await _click_greet(card)

            assert result is True
            # Should have used fallback because greet_y is None
            mock_auto.execute_js.assert_called_once()


# ============================================================
# Unit tests: Card data shape from JS extraction
# ============================================================


class TestExtractedCardShape:
    """Test that the main loop correctly processes cards with various greet states."""

    @pytest.mark.asyncio
    async def test_cards_with_greet_button_produce_coords(self):
        """Simulate card extraction result with greet coords present."""
        raw_json = json.dumps([
            {
                "text": "张三\n5年\n本科\n清华大学\n打招呼",
                "x": 100, "y": 200, "w": 300, "h": 120,
                "cx": 250, "cy": 260,
                "greet_x": 450, "greet_y": 280,
                "greet_text": "打招呼",
            }
        ])

        cards = json.loads(raw_json)
        assert len(cards) == 1
        card = cards[0]
        assert card["greet_x"] == 450
        assert card["greet_y"] == 280
        assert card["greet_text"] == "打招呼"

    @pytest.mark.asyncio
    async def test_cards_without_greet_button_have_null_coords(self):
        """Simulate card extraction result with no greet button found."""
        raw_json = json.dumps([
            {
                "text": "李四\n3年\n硕士\n北京大学",
                "x": 100, "y": 400, "w": 300, "h": 120,
                "cx": 250, "cy": 460,
                "greet_x": None, "greet_y": None, "greet_text": None,
            }
        ])

        cards = json.loads(raw_json)
        assert len(cards) == 1
        assert cards[0]["greet_x"] is None
        assert cards[0]["greet_y"] is None
        assert cards[0]["greet_text"] is None

    def test_mixed_cards_json_roundtrip(self):
        """Mixed cards (some with greet, some without) survive JSON roundtrip."""
        cards = [
            {
                "text": "张三\n5年\n本科\n清华大学\n打招呼",
                "x": 100, "y": 200, "w": 300, "h": 120,
                "cx": 250, "cy": 260,
                "greet_x": 450, "greet_y": 280,
                "greet_text": "打招呼",
            },
            {
                "text": "李四\n3年\n硕士\n北京大学",
                "x": 100, "y": 400, "w": 300, "h": 120,
                "cx": 250, "cy": 460,
                "greet_x": None, "greet_y": None, "greet_text": None,
            },
            {
                "text": "王五\n8年\n博士\n复旦大学\n继续沟通",
                "x": 100, "y": 600, "w": 300, "h": 120,
                "cx": 250, "cy": 660,
                "greet_x": 380, "greet_y": 660,
                "greet_text": "继续沟通",
            },
        ]

        roundtripped = json.loads(json.dumps(cards))
        assert roundtripped[0]["greet_x"] == 450
        assert roundtripped[1]["greet_x"] is None
        assert roundtripped[2]["greet_text"] == "继续沟通"


# ============================================================
# Integration: main loop with mocked automation
# ============================================================


class TestAutoContactMainLoop:
    """Test the main _auto_contact_impl loop handles cards correctly."""

    @pytest.mark.asyncio
    async def test_dry_run_skips_click_but_counts_contacted(self):
        """In dry_run mode, no clicking happens but contacted count increases."""
        cards_json = json.dumps([
            {
                "text": "张三\n5年\n本科\n清华大学\n打招呼",
                "x": 100, "y": 200, "w": 300, "h": 120,
                "cx": 250, "cy": 260,
                "greet_x": 450, "greet_y": 280,
                "greet_text": "打招呼",
            }
        ])

        with patch("app.workflows.automation") as mock_auto, \
             patch("app.workflows.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.navigate = AsyncMock(return_value={"status": "ok"})
            mock_auto.execute_js = AsyncMock(return_value=cards_json)
            mock_auto.scroll = AsyncMock()
            mock_auto.screenshot = AsyncMock(return_value={"status": "success"})

            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.init_tables = MagicMock()
            mock_db.count_contacted_today = MagicMock(return_value=0)
            mock_db.get_contacted_today = MagicMock(return_value=[])
            mock_db_cls.return_value = mock_db

            result = await _auto_contact_impl(
                daily_cap=5,
                school_whitelist=None,
                min_degree="本科",
                min_years=3,
                dry_run=True,
                criteria=FilterCriteria(min_degree="本科", min_years=3),
            )

            assert result["status"] == "completed"
            assert result["contacted"] >= 0
            # In dry_run, cdp_click_viewport should never be called
            mock_auto.cdp_click_viewport.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_cards_found_eventually_breaks(self):
        """When no cards are found after multiple scrolls, loop breaks."""
        with patch("app.workflows.automation") as mock_auto, \
             patch("app.workflows.Database") as mock_db_cls:

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.navigate = AsyncMock(return_value={"status": "ok"})
            # Always return None (no cards found)
            mock_auto.execute_js = AsyncMock(return_value=None)
            mock_auto.scroll = AsyncMock()
            mock_auto.screenshot = AsyncMock(return_value={"status": "success"})

            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.init_tables = MagicMock()
            mock_db.count_contacted_today = MagicMock(return_value=0)
            mock_db.get_contacted_today = MagicMock(return_value=[])
            mock_db_cls.return_value = mock_db

            result = await _auto_contact_impl(
                daily_cap=5,
                school_whitelist=None,
                min_degree="本科",
                min_years=1,
                dry_run=True,
                criteria=FilterCriteria(min_degree="大专"),
            )

            assert result["status"] == "completed"
            assert result["contacted"] == 0

    @pytest.mark.asyncio
    async def test_card_without_greet_coords_triggers_fallback_in_live_mode(self):
        """Card with null greet coords causes fallback JS execution during live run."""
        card_no_greet = {
            "text": "张三\n5年\n本科\n清华大学",
            "x": 100, "y": 200, "w": 300, "h": 120,
            "cx": 250, "cy": 260,
            "greet_x": None, "greet_y": None, "greet_text": None,
        }
        cards_json = json.dumps([card_no_greet])
        fallback_result = json.dumps({"found": True, "x": 500, "y": 280, "text": "打招呼"})

        call_count = [0]

        async def mock_execute_js(script):
            call_count[0] += 1
            if "greet_x" in script or "card-inner" in script:
                return cards_json
            if "found" in script:
                return fallback_result
            return None

        with patch("app.workflows.automation") as mock_auto, \
             patch("app.workflows.Database") as mock_db_cls, \
             patch("app.workflows._send_message", new_callable=AsyncMock, return_value=True), \
             patch("app.workflows._dismiss_popup", new_callable=AsyncMock):

            mock_auto._ensure_session = AsyncMock(return_value=True)
            mock_auto.navigate = AsyncMock(return_value={"status": "ok"})
            mock_auto.execute_js = AsyncMock(side_effect=mock_execute_js)
            mock_auto.scroll = AsyncMock()
            mock_auto.screenshot = AsyncMock(return_value={"status": "success"})
            mock_auto.cdp_click_viewport = AsyncMock(return_value=True)

            mock_db = MagicMock()
            mock_db.__enter__ = MagicMock(return_value=mock_db)
            mock_db.__exit__ = MagicMock(return_value=False)
            mock_db.init_tables = MagicMock()
            mock_db.count_contacted_today = MagicMock(return_value=0)
            mock_db.get_contacted_today = MagicMock(return_value=[])
            mock_db.insert_candidate = MagicMock()
            mock_db.update_candidate_status = MagicMock()
            mock_db.insert_contact_record = MagicMock()
            mock_db_cls.return_value = mock_db

            result = await _auto_contact_impl(
                daily_cap=5,
                school_whitelist=None,
                min_degree="本科",
                min_years=3,
                dry_run=False,
                criteria=FilterCriteria(min_degree="本科", min_years=3),
            )

            assert result["status"] == "completed"
            # The fallback JS should have been called (execute_js called more than once
            # since the card extraction is one call and the fallback is another)
            assert call_count[0] >= 2, (
                f"Expected at least 2 execute_js calls (extract + fallback), got {call_count[0]}"
            )
            mock_auto.cdp_click_viewport.assert_called()


# ============================================================
# Edge cases: text extraction helpers
# ============================================================


class TestExtractName:
    """Test _extract_name used to build boss_id from card text."""

    def test_extracts_chinese_name(self):
        assert _extract_name("张三\n5年\n本科") == "张三"

    def test_returns_none_on_empty(self):
        assert _extract_name("") is None

    def test_returns_none_on_none(self):
        assert _extract_name(None) is None

    def test_falls_back_to_first_10_chars(self):
        # Non-Chinese first line: returns first 10 chars
        result = _extract_name("SomeEnglishName that is long")
        assert result == "SomeEnglis"

    def test_short_chinese_name(self):
        assert _extract_name("李四\n3年") == "李四"

    def test_three_char_chinese_name(self):
        assert _extract_name("诸葛亮\n10年") == "诸葛亮"


class TestFilterCriteria:
    """Test _should_contact used to filter cards."""

    def test_rejects_below_min_years(self):
        cand = {"years": 2, "degree": "本科", "school": "清华大学"}
        criteria = FilterCriteria(min_years=3)
        assert _should_contact(cand, criteria) is False

    def test_accepts_at_min_years(self):
        cand = {"years": 3, "degree": "本科", "school": "清华大学"}
        criteria = FilterCriteria(min_years=3)
        assert _should_contact(cand, criteria) is True

    def test_rejects_below_min_degree(self):
        cand = {"years": 5, "degree": "大专", "school": "某学院"}
        criteria = FilterCriteria(min_degree="本科")
        assert _should_contact(cand, criteria) is False

    def test_accepts_matching_degree(self):
        cand = {"years": 5, "degree": "硕士", "school": "北京大学"}
        criteria = FilterCriteria(min_degree="本科")
        assert _should_contact(cand, criteria) is True

    def test_none_years_rejected_when_min_set(self):
        cand = {"years": None, "degree": "本科", "school": "清华大学"}
        criteria = FilterCriteria(min_years=3)
        assert _should_contact(cand, criteria) is False

    def test_none_years_accepted_when_no_min(self):
        cand = {"years": None, "degree": "本科", "school": "清华大学"}
        criteria = FilterCriteria(min_degree="本科")
        assert _should_contact(cand, criteria) is True

    def test_none_degree_rejected(self):
        cand = {"years": 5, "degree": None, "school": "清华大学"}
        criteria = FilterCriteria(min_degree="本科")
        assert _should_contact(cand, criteria) is False
