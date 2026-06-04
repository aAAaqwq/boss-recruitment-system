#!/usr/bin/env python3
"""
测试简历API端点逻辑（不依赖FastAPI运行）
"""
import sqlite3
import sys
from pathlib import Path
from typing import Optional, List

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "boss_recruitment.db"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库"""
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "resumes").mkdir(exist_ok=True)

    conn = get_db()
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


def list_resumes(status: Optional[str] = None, limit: int = 100) -> List[dict]:
    """获取已下载简历列表"""
    conn = get_db()
    try:
        if status:
            rows = conn.execute(
                """SELECT * FROM resume_operations
                   WHERE action LIKE ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (f"%{status}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM resume_operations
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()

        resumes = []
        for row in rows:
            # 检查文件是否存在
            file_path = None
            file_size = 0
            file_exists = False

            # 尝试匹配简历文件
            resumes_dir = DATA_DIR / "resumes"
            if resumes_dir.exists():
                candidate_name = row["candidate_name"]
                for ext in [".pdf", ".doc", ".docx"]:
                    potential_file = resumes_dir / f"{candidate_name}{ext}"
                    if potential_file.exists():
                        file_path = str(potential_file)
                        file_size = potential_file.stat().st_size
                        file_exists = True
                        break

            resumes.append({
                "id": row["id"],
                "candidate_name": row["candidate_name"],
                "file_name": Path(file_path).name if file_path else "",
                "file_path": file_path,
                "file_size": file_size,
                "status": "downloaded" if file_exists else "requested",
                "created_at": row["created_at"]
            })

        return resumes

    finally:
        conn.close()


def get_resume_stats() -> dict:
    """获取简历统计信息"""
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM resume_operations").fetchone()[0]

        # 统计各状态数量
        downloaded = 0
        requested = 0

        rows = conn.execute("SELECT action, resume_downloaded FROM resume_operations").fetchall()
        for row in rows:
            if row["resume_downloaded"] == 1:
                downloaded += 1
            elif "requested" in row["action"]:
                requested += 1

        # 统计实际文件数
        resumes_dir = DATA_DIR / "resumes"
        file_count = 0
        if resumes_dir.exists():
            file_count = len([f for f in resumes_dir.iterdir() if f.is_file()])

        return {
            "total_operations": total,
            "downloaded": downloaded,
            "requested": requested,
            "file_count": file_count
        }

    finally:
        conn.close()


def test_endpoints():
    """测试所有端点逻辑"""
    print("🧪 测试简历API端点逻辑")
    print("=" * 60)

    # 初始化
    init_db()

    # 插入测试数据
    conn = get_db()
    test_data = [
        ("张三", "downloaded_resume", 1, "简历已下载"),
        ("李四", "requested_resume", 0, "已请求简历"),
        ("王五", "downloaded_resume", 1, "简历已下载"),
        ("赵六", "requested_resume", 0, "已请求简历"),
    ]
    for name, action, downloaded, detail in test_data:
        conn.execute(
            """INSERT INTO resume_operations (candidate_name, action, resume_downloaded, detail)
               VALUES (?, ?, ?, ?)""",
            (name, action, downloaded, detail)
        )
    conn.commit()
    conn.close()
    print("✅ 测试数据插入成功")

    # 测试列表端点
    print("\n📄 测试 list_resumes():")
    resumes = list_resumes()
    for r in resumes:
        print(f"  [{r['id']}] {r['candidate_name']} - {r['status']} - 文件: {r['file_name'] or '无'}")

    # 测试筛选列表端点
    print("\n📄 测试 list_resumes(status='downloaded'):")
    downloaded = list_resumes(status="downloaded")
    for r in downloaded:
        print(f"  [{r['id']}] {r['candidate_name']} - {r['status']}")

    # 测试统计端点
    print("\n📊 测试 get_resume_stats():")
    stats = get_resume_stats()
    print(f"  总操作数: {stats['total_operations']}")
    print(f"  已下载: {stats['downloaded']}")
    print(f"  已请求: {stats['requested']}")
    print(f"  实际文件数: {stats['file_count']}")

    print("\n✅ 所有端点测试完成")


if __name__ == "__main__":
    test_endpoints()
