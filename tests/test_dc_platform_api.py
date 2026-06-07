"""DC Platform API 单元测试

覆盖 3101 数据总控平台的 6 个新增端点:
1. GET /api/tasks/status - 返回聚合的 F5/F6/F7 状态
2. GET /api/stats/daily-trend - 返回趋势数组，包含正确形状
3. GET /api/contact-records - 返回记录列表，支持 action/date 过滤
4. GET /api/conversations - 返回按 candidate_name 分组的 sessions
5. PUT /api/config/daily-caps - 保存并读取 caps
6. GET /api/config/daily-caps - 返回当前 caps

使用 FastAPI TestClient 模式，模拟 JWT 依赖，使用内存 SQLite
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch
from pathlib import Path

from fastapi.testclient import TestClient


# ══════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════

@pytest.fixture
def mock_current_user():
    """模拟认证用户"""
    return {"sub": "test_user"}


@pytest.fixture
def in_memory_db():
    """内存 SQLite 数据库"""
    import sqlite3
    # 使用 check_same_thread=False 以支持 TestClient 的多线程请求
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # 创建测试所需表
    conn.execute("""CREATE TABLE candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, boss_id TEXT UNIQUE, name TEXT,
        school TEXT, degree TEXT, years INTEGER, position TEXT, company TEXT,
        status TEXT DEFAULT 'new', created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    conn.execute("""CREATE TABLE conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_name TEXT, round_index INTEGER DEFAULT 0,
        action TEXT, ai_message TEXT, candidate_message TEXT, detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    conn.execute("""CREATE TABLE runtime_state (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    conn.execute("""CREATE TABLE processed_candidates (
        candidate_key TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    conn.execute("""CREATE TABLE resume_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_name TEXT,
        action TEXT,
        resume_downloaded INTEGER DEFAULT 0,
        wechat_exchanged INTEGER DEFAULT 0,
        detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.execute("""CREATE TABLE contact_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_name TEXT,
        action TEXT,
        action_date TEXT,
        detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    conn.commit()
    return conn


@pytest.fixture
def populated_db(in_memory_db):
    """填充测试数据的数据库"""
    # 插入 conversations 数据
    in_memory_db.execute(
        """INSERT INTO conversations (candidate_name, action, created_at)
           VALUES (?, ?, ?)""",
        ("Alice", "auto_reply", datetime.now().isoformat())
    )
    in_memory_db.execute(
        """INSERT INTO conversations (candidate_name, action, created_at)
           VALUES (?, ?, ?)""",
        ("Bob", "auto_reply", datetime.now().isoformat())
    )
    in_memory_db.execute(
        """INSERT INTO conversations (candidate_name, action, created_at)
           VALUES (?, ?, ?)""",
        ("Alice", "auto_reply", (datetime.now()).isoformat())
    )

    # 插入 contact_records 数据
    in_memory_db.execute(
        """INSERT INTO contact_records (candidate_name, action, action_date, created_at)
           VALUES (?, ?, ?, ?)""",
        ("Charlie", "greet", "2026-06-07", datetime.now().isoformat())
    )
    in_memory_db.execute(
        """INSERT INTO contact_records (candidate_name, action, action_date, created_at)
           VALUES (?, ?, ?, ?)""",
        ("David", "greet", "2026-06-06", datetime.now().isoformat())
    )
    in_memory_db.execute(
        """INSERT INTO contact_records (candidate_name, action, action_date, created_at)
           VALUES (?, ?, ?, ?)""",
        ("Eve", "request_resume", "2026-06-07", datetime.now().isoformat())
    )

    # 插入 runtime_state 数据 (每日上限配置)
    import json
    in_memory_db.execute(
        """INSERT INTO runtime_state (key, value, updated_at)
           VALUES (?, ?, ?)""",
        ("daily_caps", json.dumps({
            "daily_contact_cap": 100,
            "daily_chat_rounds_cap": 10
        }), datetime.now().isoformat())
    )

    in_memory_db.commit()
    return in_memory_db


@pytest.fixture
def test_app(in_memory_db, mock_current_user):
    """创建测试应用实例，覆盖数据库和认证依赖"""
    from app import api
    from app.auth import verify_token

    # 使用 monkey patch 替换 DB_PATH
    original_db_path = api.DB_PATH
    api.DB_PATH = ":memory:"

    # 使用 monkey patch 替换 get_db 函数
    # 关键：每次都返回同一个 in_memory_db 连接
    original_get_db = api.get_db

    def patched_get_db():
        return in_memory_db

    api.get_db = patched_get_db

    # 覆盖 verify_token 依赖
    def override_verify_token():
        return mock_current_user

    api.app.dependency_overrides[verify_token] = override_verify_token

    # 确保数据库表已创建
    in_memory_db.execute("""CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, boss_id TEXT UNIQUE, name TEXT,
        school TEXT, degree TEXT, years INTEGER, position TEXT, company TEXT,
        status TEXT DEFAULT 'new', created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    in_memory_db.execute("""CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_name TEXT, round_index INTEGER DEFAULT 0,
        action TEXT, ai_message TEXT, candidate_message TEXT, detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    in_memory_db.execute("""CREATE TABLE IF NOT EXISTS runtime_state (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    in_memory_db.execute("""CREATE TABLE IF NOT EXISTS processed_candidates (
        candidate_key TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")

    in_memory_db.execute("""CREATE TABLE IF NOT EXISTS resume_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_name TEXT,
        action TEXT,
        resume_downloaded INTEGER DEFAULT 0,
        wechat_exchanged INTEGER DEFAULT 0,
        detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    in_memory_db.execute("""CREATE TABLE IF NOT EXISTS contact_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_name TEXT,
        action TEXT,
        action_date TEXT,
        detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")

    in_memory_db.commit()

    # 关键修复：使用 mock wrapper 来拦截 close() 调用
    # 因为 sqlite3.Connection.close 是只读属性
    from unittest.mock import MagicMock
    mock_conn = MagicMock(wraps=in_memory_db)
    # 让大部分属性和方法直接访问原始连接
    for attr in dir(in_memory_db):
        if not attr.startswith('_') and attr != 'close':
            try:
                setattr(mock_conn, attr, getattr(in_memory_db, attr))
            except (AttributeError, TypeError):
                pass
    # 让 close 成为 no-op
    mock_conn.close = lambda: None
    # 重写 execute 等方法以使用原始连接
    mock_conn.execute = in_memory_db.execute
    mock_conn.commit = in_memory_db.commit
    mock_conn.row_factory = in_memory_db.row_factory

    # 更新 patched_get_db 返回 mock 连接
    api.get_db = lambda: mock_conn

    yield api.app

    # 清理：真正关闭连接
    in_memory_db.close()
    api.DB_PATH = original_db_path
    api.get_db = original_get_db
    api.app.dependency_overrides.clear()


@pytest.fixture
def client(test_app):
    """FastAPI TestClient"""
    return TestClient(test_app)


# ══════════════════════════════════════════════════
# 1. GET /api/tasks/status - 聚合 F5/F6/F7 状态
# ══════════════════════════════════════════════════

class TestTasksStatus:
    """测试 GET /api/tasks/status 端点"""

    def test_returns_aggregated_status(self, client):
        """返回聚合的 F5/F6/F7 状态，包含所有必需字段"""
        response = client.get("/api/tasks/status")
        assert response.status_code == 200

        data = response.json()
        assert "f5_filter" in data
        assert "f6_resume" in data
        assert "f7_reply" in data
        assert "browser" in data

    def test_f5_status_shape(self, client):
        """F5 状态包含 status 字段"""
        response = client.get("/api/tasks/status")
        data = response.json()
        f5 = data["f5_filter"]
        assert "status" in f5
        # 默认应该返回 idle 或其他有效状态
        assert f5["status"] in ["idle", "running", "queued", "error", "completed"]

    def test_f6_status_shape(self, client):
        """F6 状态包含标准字段"""
        response = client.get("/api/tasks/status")
        data = response.json()
        f6 = data["f6_resume"]
        assert "status" in f6
        assert "processed" in f6
        assert "total" in f6
        assert "message" in f6

    def test_f7_status_shape(self, client):
        """F7 状态包含标准字段"""
        response = client.get("/api/tasks/status")
        data = response.json()
        f7 = data["f7_reply"]
        assert "status" in f7
        assert "replied" in f7
        assert "failed" in f7
        assert "skipped" in f7
        assert "total" in f7

    def test_browser_status_shape(self, client):
        """浏览器状态包含 connected 布尔值"""
        response = client.get("/api/tasks/status")
        data = response.json()
        browser = data["browser"]
        assert "connected" in browser
        assert isinstance(browser["connected"], bool)


# ══════════════════════════════════════════════════
# 2. GET /api/stats/daily-trend - 趋势数据
# ══════════════════════════════════════════════════

class TestDailyTrend:
    """测试 GET /api/stats/daily-trend 端点"""

    def test_returns_trend_array(self, client):
        """返回 trend 数组和 days 字段"""
        response = client.get("/api/stats/daily-trend?days=7")
        assert response.status_code == 200

        data = response.json()
        assert "trend" in data
        assert "days" in data
        assert isinstance(data["trend"], list)
        assert data["days"] == 7

    def test_trend_array_length_matches_days(self, client):
        """trend 数组长度等于 days 参数"""
        for days in [1, 3, 7, 14]:
            response = client.get(f"/api/stats/daily-trend?days={days}")
            data = response.json()
            assert len(data["trend"]) == days

    def test_trend_item_shape(self, client):
        """每个趋势项包含所有必需字段"""
        response = client.get("/api/stats/daily-trend?days=7")
        data = response.json()

        for item in data["trend"]:
            assert "date" in item
            assert "contacted" in item
            assert "resumes" in item
            assert "replies" in item
            assert "reply_rate" in item
            # 数值类型检查
            assert isinstance(item["contacted"], int)
            assert isinstance(item["resumes"], int)
            assert isinstance(item["replies"], int)
            assert isinstance(item["reply_rate"], (int, float))

    def test_reply_rate_calculation(self, client):
        """回复率计算正确: replies / contacted * 100"""
        response = client.get("/api/stats/daily-trend?days=7")
        data = response.json()

        for item in data["trend"]:
            if item["contacted"] > 0:
                expected_rate = round(item["replies"] / item["contacted"] * 100, 1)
                assert item["reply_rate"] == expected_rate
            else:
                assert item["reply_rate"] == 0.0

    def test_days_parameter_bounds(self, client):
        """days 参数在 1-30 范围内"""
        # 有效范围
        response = client.get("/api/stats/daily-trend?days=1")
        assert response.status_code == 200

        response = client.get("/api/stats/daily-trend?days=30")
        assert response.status_code == 200

        # 超出范围 (FastAPI 会自动验证，但这里确认行为)
        response = client.get("/api/stats/daily-trend?days=100")
        # FastAPI Query 约束会返回 422
        assert response.status_code == 422


# ══════════════════════════════════════════════════
# 3. GET /api/contact-records - 联系记录
# ══════════════════════════════════════════════════

class TestContactRecords:
    """测试 GET /api/contact-records 端点"""

    def test_returns_records_list(self, client, populated_db):
        """返回 records 列表和 total 字段"""
        response = client.get("/api/contact-records")
        assert response.status_code == 200

        data = response.json()
        assert "records" in data
        assert "total" in data
        assert isinstance(data["records"], list)

    def test_records_shape(self, client, populated_db):
        """每条记录包含所有必需字段"""
        response = client.get("/api/contact-records")
        data = response.json()

        for record in data["records"]:
            assert "id" in record
            assert "candidate_name" in record
            assert "action" in record
            assert "action_date" in record
            assert "created_at" in record

    def test_action_filter(self, client, populated_db):
        """action 过滤器生效"""
        # 获取所有记录
        all_response = client.get("/api/contact-records")
        all_data = all_response.json()

        # 使用 action=greet 过滤
        filtered_response = client.get("/api/contact-records?action=greet")
        filtered_data = filtered_response.json()

        # 验证过滤后的记录都匹配 action
        for record in filtered_data["records"]:
            assert record["action"] == "greet"

        # 过滤后数量应小于等于全部
        assert filtered_data["total"] <= all_data["total"]

    def test_date_filter(self, client, populated_db):
        """date 过滤器生效"""
        response = client.get("/api/contact-records?date=2026-06-07")
        data = response.json()

        # 验证返回的记录日期匹配
        for record in data["records"]:
            assert "2026-06-07" in record["action_date"]

    def test_combined_filters(self, client, populated_db):
        """action 和 date 组合过滤"""
        response = client.get("/api/contact-records?action=greet&date=2026-06-07")
        data = response.json()

        for record in data["records"]:
            assert record["action"] == "greet"
            assert "2026-06-07" in record["action_date"]

    def test_limit_parameter(self, client, populated_db):
        """limit 参数限制返回数量"""
        response = client.get("/api/contact-records?limit=2")
        data = response.json()

        assert len(data["records"]) <= 2

    def test_empty_result(self, client):
        """无匹配记录时返回空数组"""
        response = client.get("/api/contact-records?action=nonexistent")
        data = response.json()

        assert data["records"] == []
        assert data["total"] == 0


# ══════════════════════════════════════════════════
# 4. GET /api/conversations - 对话会话
# ══════════════════════════════════════════════════

class TestConversations:
    """测试 GET /api/conversations 端点"""

    def test_returns_sessions_grouped_by_candidate(self, client, populated_db):
        """返回按 candidate_name 分组的 sessions"""
        response = client.get("/api/conversations")
        assert response.status_code == 200

        data = response.json()
        assert "sessions" in data
        assert "total" in data
        assert isinstance(data["sessions"], list)

    def test_session_shape(self, client, populated_db):
        """每个 session 包含聚合字段"""
        response = client.get("/api/conversations")
        data = response.json()

        for session in data["sessions"]:
            assert "candidate_name" in session
            assert "rounds" in session
            assert "first_at" in session
            assert "last_at" in session
            # rounds 应该是正整数
            assert isinstance(session["rounds"], int)
            assert session["rounds"] >= 1

    def test_sessions_are_unique_per_candidate(self, client, populated_db):
        """每个候选人只出现一次"""
        response = client.get("/api/conversations")
        data = response.json()

        candidate_names = [s["candidate_name"] for s in data["sessions"]]
        # 验证无重复
        assert len(candidate_names) == len(set(candidate_names))

    def test_ordered_by_last_at_desc(self, client, populated_db):
        """按 last_at 降序排列"""
        response = client.get("/api/conversations")
        data = response.json()

        if len(data["sessions"]) >= 2:
            # 提取 last_at 时间戳
            last_ats = [s["last_at"] for s in data["sessions"]]
            # 验证降序 (后面的应该早于或等于前面的)
            assert last_ats[0] >= last_ats[1]

    def test_limit_parameter(self, client, populated_db):
        """limit 参数限制返回数量"""
        response = client.get("/api/conversations?limit=1")
        data = response.json()

        assert len(data["sessions"]) <= 1

    def test_empty_result(self, client, in_memory_db):
        """无对话记录时返回空数组"""
        # 使用空的内存数据库（无数据填充）
        response = client.get("/api/conversations")
        data = response.json()

        assert data["sessions"] == []
        assert data["total"] == 0


# ══════════════════════════════════════════════════
# 5. PUT /api/config/daily-caps - 保存每日上限
# ══════════════════════════════════════════════════

class TestUpdateDailyCaps:
    """测试 PUT /api/config/daily-caps 端点"""

    def test_saves_caps_to_db(self, client, in_memory_db):
        """保存配置到 runtime_state 表"""
        payload = {
            "daily_contact_cap": 120,
            "daily_chat_rounds_cap": 15,
        }

        response = client.put("/api/config/daily-caps", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "success"
        assert data["caps"]["daily_contact_cap"] == 120
        assert data["caps"]["daily_chat_rounds_cap"] == 15

        # 验证数据库中已保存（直接查询 in_memory_db）
        row = in_memory_db.execute(
            "SELECT value FROM runtime_state WHERE key = 'daily_caps'"
        ).fetchone()

        assert row is not None
        import json
        saved_caps = json.loads(row["value"])
        assert saved_caps["daily_contact_cap"] == 120
        assert saved_caps["daily_chat_rounds_cap"] == 15

    def test_updates_existing_caps(self, client, in_memory_db):
        """更新已存在的配置"""
        # 先插入一个配置
        import json
        in_memory_db.execute(
            """INSERT INTO runtime_state (key, value, updated_at)
               VALUES (?, ?, ?)""",
            ("daily_caps", json.dumps({
                "daily_contact_cap": 50,
                "daily_chat_rounds_cap": 3
            }), datetime.now().isoformat())
        )
        in_memory_db.commit()

        # 更新
        payload = {
            "daily_contact_cap": 200,
            "daily_chat_rounds_cap": 20,
        }

        response = client.put("/api/config/daily-caps", json=payload)
        assert response.status_code == 200

        # 验证更新后的值（直接查询 in_memory_db）
        row = in_memory_db.execute(
            "SELECT value FROM runtime_state WHERE key = 'daily_caps'"
        ).fetchone()

        saved_caps = json.loads(row["value"])
        assert saved_caps["daily_contact_cap"] == 200
        assert saved_caps["daily_chat_rounds_cap"] == 20

    def test_returns_saved_caps(self, client, in_memory_db):
        """响应包含保存的配置"""
        payload = {
            "daily_contact_cap": 90,
            "daily_chat_rounds_cap": 8,
        }

        response = client.put("/api/config/daily-caps", json=payload)
        data = response.json()

        assert "caps" in data
        assert data["caps"]["daily_contact_cap"] == 90
        assert data["caps"]["daily_chat_rounds_cap"] == 8


# ══════════════════════════════════════════════════
# 6. GET /api/config/daily-caps - 读取每日上限
# ══════════════════════════════════════════════════

class TestGetDailyCaps:
    """测试 GET /api/config/daily-caps 端点"""

    def test_returns_current_caps(self, client, populated_db):
        """返回当前保存的配置"""
        response = client.get("/api/config/daily-caps")
        assert response.status_code == 200

        data = response.json()
        assert "status" in data
        assert "caps" in data
        assert "daily_contact_cap" in data["caps"]
        assert "daily_chat_rounds_cap" in data["caps"]

        # populated_db 中设置的值
        assert data["caps"]["daily_contact_cap"] == 100
        assert data["caps"]["daily_chat_rounds_cap"] == 10

    def test_returns_default_when_not_set(self, client, in_memory_db):
        """未设置时返回默认值"""
        response = client.get("/api/config/daily-caps")
        assert response.status_code == 200

        data = response.json()
        assert "caps" in data
        assert data["caps"]["daily_contact_cap"] == 80  # 默认值
        assert data["caps"]["daily_chat_rounds_cap"] == 5  # 默认值

    def test_roundtrip_put_then_get(self, client, in_memory_db):
        """PUT 后 GET 返回相同值"""
        put_payload = {
            "daily_contact_cap": 150,
            "daily_chat_rounds_cap": 12,
        }

        # PUT
        put_response = client.put("/api/config/daily-caps", json=put_payload)
        assert put_response.status_code == 200

        # GET
        get_response = client.get("/api/config/daily-caps")
        get_data = get_response.json()

        # 验证值一致
        assert get_data["caps"]["daily_contact_cap"] == 150
        assert get_data["caps"]["daily_chat_rounds_cap"] == 12
