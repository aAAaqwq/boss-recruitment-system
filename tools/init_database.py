"""初始化数据库"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Database
from app.config import settings


def main():
    """初始化数据库"""
    print("正在初始化数据库...")
    print(f"数据库路径: {settings.DATABASE_PATH}")
    
    with Database() as db:
        db.init_tables()
    
    print("✅ 数据库初始化完成！")
    print("\n创建的表:")
    print("  - candidates (候选人库)")
    print("  - contact_records (联系记录)")
    print("  - chat_sessions (对话会话)")


if __name__ == "__main__":
    main()
