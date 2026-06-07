"""数据库操作模块"""
import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from app.config import settings


class Database:
    """数据库管理类"""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.DATABASE_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self.cursor = None
    
    def connect(self):
        """连接数据库"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.cursor = self.conn.cursor()
        return self
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
    
    def __enter__(self):
        return self.connect()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    def init_tables(self):
        """初始化数据库表"""
        
        # candidates表（候选人库）
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                boss_id TEXT NOT NULL UNIQUE,
                candidate_name TEXT,
                school TEXT,
                degree TEXT,
                years INTEGER,
                current_role TEXT,
                expected_role TEXT,
                expected_city TEXT,
                skills TEXT,
                status TEXT DEFAULT 'discovered',
                contacted_at TEXT,
                resume_path TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_boss_id ON candidates(boss_id)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON candidates(status)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_school ON candidates(school)")
        
        # contact_records表（联系记录）
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                boss_id TEXT NOT NULL,
                action TEXT NOT NULL,
                action_date TEXT NOT NULL,
                success BOOLEAN DEFAULT 1,
                error_message TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_boss_id_action ON contact_records(boss_id, action)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_action_date ON contact_records(action_date)")
        
        # chat_sessions表（对话会话）
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                boss_id TEXT NOT NULL UNIQUE,
                candidate_name TEXT,
                current_round_id TEXT,
                round_index INTEGER DEFAULT 0,
                history TEXT,
                last_screen_text TEXT,
                rounds_sent_today INTEGER DEFAULT 0,
                last_sent_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_boss_id_chat ON chat_sessions(boss_id)")

        # resume_operations表（简历操作记录 — F6去重依据）
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS resume_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_name TEXT,
                action TEXT,
                resume_downloaded INTEGER DEFAULT 0,
                wechat_exchanged INTEGER DEFAULT 0,
                detail TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_resume_candidate ON resume_operations(candidate_name)"
        )

        # conversations表（F7 对话记录）
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_name TEXT,
                action TEXT,
                ai_message TEXT,
                candidate_message TEXT,
                detail TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        self.conn.commit()
    
    # ========== 候选人操作 ==========
    
    def insert_candidate(self, **kwargs):
        """插入候选人"""
        fields = ['boss_id', 'candidate_name', 'school', 'degree', 'years',
                  'current_role', 'expected_role', 'expected_city', 'skills', 'status']
        
        values = {k: kwargs.get(k) for k in fields if k in kwargs}
        
        if 'skills' in values and isinstance(values['skills'], list):
            values['skills'] = json.dumps(values['skills'])
        
        placeholders = ', '.join(['?' for _ in values])
        columns = ', '.join(values.keys())
        
        self.cursor.execute(
            f"INSERT OR IGNORE INTO candidates ({columns}) VALUES ({placeholders})",
            tuple(values.values())
        )
        self.conn.commit()
    
    def update_candidate_status(self, boss_id: str, status: str):
        """更新候选人状态"""
        self.cursor.execute(
            "UPDATE candidates SET status = ?, updated_at = ? WHERE boss_id = ?",
            (status, datetime.now().isoformat(), boss_id)
        )
        self.conn.commit()
    
    def update_resume_path(self, boss_id: str, resume_path: str):
        """更新简历路径"""
        self.cursor.execute(
            "UPDATE candidates SET resume_path = ?, status = 'resume_downloaded', updated_at = ? WHERE boss_id = ?",
            (resume_path, datetime.now().isoformat(), boss_id)
        )
        self.conn.commit()
    
    def get_candidate(self, boss_id: str) -> Optional[Dict]:
        """获取候选人信息"""
        self.cursor.execute("SELECT * FROM candidates WHERE boss_id = ?", (boss_id,))
        row = self.cursor.fetchone()
        if not row:
            return None
        
        candidate = dict(row)
        if candidate.get('skills'):
            candidate['skills'] = json.loads(candidate['skills'])
        return candidate
    
    # ========== 联系记录操作 ==========
    
    def insert_contact_record(self, boss_id: str, action: str, success: bool = True, error_message: str = None):
        """插入联系记录"""
        today = datetime.now().date().isoformat()
        self.cursor.execute(
            "INSERT INTO contact_records (boss_id, action, action_date, success, error_message) VALUES (?, ?, ?, ?, ?)",
            (boss_id, action, today, success, error_message)
        )
        self.conn.commit()
    
    def count_contacted_today(self) -> int:
        """统计今日已联系人数"""
        today = datetime.now().date().isoformat()
        self.cursor.execute(
            "SELECT COUNT(DISTINCT boss_id) as count FROM contact_records WHERE action = 'contacted' AND action_date = ?",
            (today,)
        )
        return self.cursor.fetchone()['count']
    
    def get_contacted_today(self) -> List[str]:
        """获取今日已联系的boss_id列表"""
        today = datetime.now().date().isoformat()
        self.cursor.execute(
            "SELECT DISTINCT boss_id FROM contact_records WHERE action = 'contacted' AND action_date = ?",
            (today,)
        )
        return [row['boss_id'] for row in self.cursor.fetchall()]
    
    # ========== 聊天会话操作 ==========
    
    def get_chat_session(self, boss_id: str) -> Optional[Dict]:
        """获取聊天会话"""
        self.cursor.execute("SELECT * FROM chat_sessions WHERE boss_id = ?", (boss_id,))
        row = self.cursor.fetchone()
        if not row:
            return None
        
        session = dict(row)
        if session.get('history'):
            session['history'] = json.loads(session['history'])
        else:
            session['history'] = []
        
        # 如果是新的一天，重置今日计数
        today = datetime.now().date().isoformat()
        if session.get('last_sent_date') != today:
            session['rounds_sent_today'] = 0
        
        return session
    
    def save_chat_session(self, session: Dict):
        """保存聊天会话"""
        today = datetime.now().date().isoformat()
        
        history_json = json.dumps(session.get('history', []), ensure_ascii=False)
        
        self.cursor.execute("""
            INSERT OR REPLACE INTO chat_sessions
            (boss_id, candidate_name, current_round_id, round_index, history, 
             last_screen_text, rounds_sent_today, last_sent_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session['boss_id'],
            session.get('candidate_name'),
            session.get('current_round_id'),
            session.get('round_index', 0),
            history_json,
            session.get('last_screen_text', ''),
            session.get('rounds_sent_today', 0),
            today,
            datetime.now().isoformat()
        ))
        self.conn.commit()
    
    # ========== 简历操作 ==========

    def insert_resume_op(self, candidate_name: str, action: str, resume_downloaded: bool = False,
                         wechat_exchanged: bool = False, detail: str = None):
        """插入简历操作记录"""
        self.cursor.execute(
            """INSERT INTO resume_operations
               (candidate_name, action, resume_downloaded, wechat_exchanged, detail)
               VALUES (?, ?, ?, ?, ?)""",
            (candidate_name, action, int(resume_downloaded), int(wechat_exchanged), detail)
        )
        self.conn.commit()

    def get_resume_ops(self, candidate_name: str = None) -> List[Dict]:
        """查询简历操作记录（按候选人去重）"""
        if candidate_name:
            self.cursor.execute(
                "SELECT * FROM resume_operations WHERE candidate_name = ? ORDER BY created_at DESC",
                (candidate_name,)
            )
        else:
            self.cursor.execute(
                "SELECT * FROM resume_operations ORDER BY created_at DESC LIMIT 100"
            )
        return [dict(row) for row in self.cursor.fetchall()]

    # ========== 统计查询 ==========
    
    def get_daily_stats(self, date: str = None) -> Dict:
        """获取每日统计"""
        if not date:
            date = datetime.now().date().isoformat()
        
        # 联系人数
        self.cursor.execute(
            "SELECT COUNT(DISTINCT boss_id) as count FROM contact_records WHERE action = 'contacted' AND action_date = ?",
            (date,)
        )
        contacted = self.cursor.fetchone()['count']
        
        # 回复人数
        self.cursor.execute(
            "SELECT COUNT(DISTINCT boss_id) as count FROM contact_records WHERE action = 'replied' AND action_date = ?",
            (date,)
        )
        replied = self.cursor.fetchone()['count']
        
        # 简历获取数
        self.cursor.execute(
            "SELECT COUNT(DISTINCT boss_id) as count FROM contact_records WHERE action = 'resume_downloaded' AND action_date = ?",
            (date,)
        )
        resume_downloaded = self.cursor.fetchone()['count']
        
        # 聊天轮数
        self.cursor.execute(
            "SELECT COUNT(*) as count FROM contact_records WHERE action = 'chat_sent' AND action_date = ?",
            (date,)
        )
        chat_rounds = self.cursor.fetchone()['count']
        
        return {
            "date": date,
            "contacted": contacted,
            "replied": replied,
            "resume_downloaded": resume_downloaded,
            "chat_rounds": chat_rounds,
            "reply_rate": round(replied / contacted * 100, 2) if contacted > 0 else 0,
            "resume_rate": round(resume_downloaded / replied * 100, 2) if replied > 0 else 0
        }
