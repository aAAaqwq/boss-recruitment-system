#!/usr/bin/env python3
"""
测试简历API端点
"""
import sqlite3
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "boss_recruitment.db"


def init_db():
    """初始化数据库"""
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    # 候选人表
    conn.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, boss_id TEXT UNIQUE, name TEXT,
        school TEXT, degree TEXT, years INTEGER, position TEXT, company TEXT,
        status TEXT DEFAULT 'new', created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    # 简历操作表
    conn.execute('''CREATE TABLE IF NOT EXISTS resume_operations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_name TEXT,
        action TEXT,
        resume_downloaded INTEGER DEFAULT 0,
        wechat_exchanged INTEGER DEFAULT 0,
        detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()


def test_insert():
    """测试插入数据"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """INSERT INTO resume_operations (candidate_name, action, resume_downloaded, detail)
           VALUES (?, ?, ?, ?)""",
        ("张三", "downloaded_resume", 1, "测试简历下载")
    )
    conn.execute(
        """INSERT INTO resume_operations (candidate_name, action, resume_downloaded, detail)
           VALUES (?, ?, ?, ?)""",
        ("李四", "requested_resume", 0, "测试简历请求")
    )
    conn.commit()
    conn.close()
    print("✅ 测试数据插入成功")


def test_query():
    """测试查询数据"""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """SELECT * FROM resume_operations ORDER BY created_at DESC LIMIT 10"""
    ).fetchall()

    print(f"\n📄 简历记录 ({len(rows)} 条):")
    for row in rows:
        print(f"  [{row['id']}] {row['candidate_name']} - {row['action']} - 下载:{row['resume_downloaded']}")

    conn.close()


def test_stats():
    """测试统计查询"""
    conn = sqlite3.connect(str(DB_PATH))

    total = conn.execute("SELECT COUNT(*) FROM resume_operations").fetchone()[0]
    downloaded = conn.execute(
        "SELECT COUNT(*) FROM resume_operations WHERE resume_downloaded = 1"
    ).fetchone()[0]

    print(f"\n📊 统计:")
    print(f"  总操作数: {total}")
    print(f"  已下载: {downloaded}")

    conn.close()


if __name__ == "__main__":
    print("🧪 测试简历API端点")
    print("=" * 50)

    init_db()
    test_insert()
    test_query()
    test_stats()

    print("\n✅ 所有测试完成")
