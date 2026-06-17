"""数据库操作模块 — PostgreSQL"""
import json
from datetime import datetime
from typing import Optional, List, Dict

import psycopg2
import psycopg2.extras
from app.config import settings


class Database:
    """PostgreSQL 数据库管理类"""

    def __init__(self, db_path: str = None):
        self.conn = None
        self.cursor = None

    def connect(self):
        self.conn = psycopg2.connect(
            host=settings.PG_HOST,
            port=settings.PG_PORT,
            dbname=settings.PG_DB,
            user=settings.PG_USER,
            password=settings.PG_PASSWORD,
        )
        self.conn.autocommit = False
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return self

    def close(self):
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self.connect()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.conn.rollback()
        self.close()

    # ========== 建表 ==========

    def init_tables(self):
        # users
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(100),
                role VARCHAR(20) DEFAULT 'user',
                is_active BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # boss_accounts
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS boss_accounts (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
                account_name VARCHAR(100),
                boss_identity VARCHAR(100),
                cdp_host VARCHAR(100) DEFAULT '127.0.0.1',
                cdp_port INTEGER DEFAULT 9222,
                profile_dir VARCHAR(500),
                cookies_file VARCHAR(500),
                use_external_browser BOOLEAN DEFAULT false,
                is_default BOOLEAN DEFAULT false,
                enabled BOOLEAN DEFAULT true,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # candidates
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id SERIAL PRIMARY KEY,
                boss_id TEXT NOT NULL UNIQUE,
                candidate_name TEXT,
                school TEXT,
                degree TEXT,
                years INTEGER,
                current_title TEXT,
                expected_role TEXT,
                expected_city TEXT,
                skills TEXT,
                status TEXT DEFAULT 'discovered',
                contacted_at TEXT,
                resume_path TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_boss_id ON candidates(boss_id)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON candidates(status)")
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_school ON candidates(school)")

        # contact_records
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_records (
                id SERIAL PRIMARY KEY,
                boss_id TEXT NOT NULL,
                action TEXT NOT NULL,
                action_date TEXT NOT NULL,
                success BOOLEAN DEFAULT true,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_boss_id_action ON contact_records(boss_id, action)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_action_date ON contact_records(action_date)"
        )

        # chat_sessions
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id SERIAL PRIMARY KEY,
                boss_id TEXT NOT NULL UNIQUE,
                candidate_name TEXT,
                current_round_id TEXT,
                round_index INTEGER DEFAULT 0,
                history TEXT,
                last_screen_text TEXT,
                rounds_sent_today INTEGER DEFAULT 0,
                last_sent_date TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_boss_id_chat ON chat_sessions(boss_id)")

        # resume_operations
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS resume_operations (
                id SERIAL PRIMARY KEY,
                boss_id TEXT,
                candidate_name TEXT,
                action TEXT,
                resume_downloaded BOOLEAN DEFAULT false,
                wechat_exchanged BOOLEAN DEFAULT false,
                detail TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_resume_candidate ON resume_operations(candidate_name)"
        )
        self.cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_resume_boss_id ON resume_operations(boss_id)"
        )

        # conversations
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id SERIAL PRIMARY KEY,
                candidate_name TEXT,
                action TEXT,
                ai_message TEXT,
                candidate_message TEXT,
                detail TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # runtime_state
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS runtime_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # processed_candidates
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_candidates (
                candidate_key TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

        # reply_templates
        self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS reply_templates (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                user_id TEXT DEFAULT 'default',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(name, user_id)
            )
        """)

        self.conn.commit()

    # ========== 候选人操作 ==========

    def insert_candidate(self, **kwargs):
        fields = ['boss_id', 'candidate_name', 'school', 'degree', 'years',
                  'current_title', 'expected_role', 'expected_city', 'skills', 'status']
        values = {k: kwargs.get(k) for k in fields if k in kwargs}
        if 'skills' in values and isinstance(values['skills'], list):
            values['skills'] = json.dumps(values['skills'])

        columns = ', '.join(values.keys())
        placeholders = ', '.join(['%s'] * len(values))
        self.cursor.execute(
            f"INSERT INTO candidates ({columns}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
            tuple(values.values())
        )
        self.conn.commit()

    def update_candidate_status(self, boss_id: str, status: str):
        self.cursor.execute(
            "UPDATE candidates SET status = %s, updated_at = %s WHERE boss_id = %s",
            (status, datetime.now().isoformat(), boss_id)
        )
        self.conn.commit()

    def update_resume_path(self, boss_id: str, resume_path: str):
        self.cursor.execute(
            "UPDATE candidates SET resume_path = %s, status = 'resume_downloaded', updated_at = %s WHERE boss_id = %s",
            (resume_path, datetime.now().isoformat(), boss_id)
        )
        self.conn.commit()

    def get_candidate(self, boss_id: str) -> Optional[Dict]:
        self.cursor.execute("SELECT * FROM candidates WHERE boss_id = %s", (boss_id,))
        row = self.cursor.fetchone()
        if not row:
            return None
        candidate = dict(row)
        if candidate.get('skills'):
            candidate['skills'] = json.loads(candidate['skills'])
        return candidate

    # ========== 联系记录操作 ==========

    def insert_contact_record(self, boss_id: str, action: str, success: bool = True, error_message: str = None):
        today = datetime.now().date().isoformat()
        self.cursor.execute(
            "INSERT INTO contact_records (boss_id, action, action_date, success, error_message) VALUES (%s, %s, %s, %s, %s)",
            (boss_id, action, today, success, error_message)
        )
        self.conn.commit()

    def count_contacted_today(self) -> int:
        today = datetime.now().date().isoformat()
        self.cursor.execute(
            "SELECT COUNT(DISTINCT boss_id) as count FROM contact_records WHERE action = 'contacted' AND action_date = %s",
            (today,)
        )
        row = self.cursor.fetchone()
        return row['count'] if row else 0

    def get_contacted_today(self) -> List[str]:
        today = datetime.now().date().isoformat()
        self.cursor.execute(
            "SELECT DISTINCT boss_id FROM contact_records WHERE action = 'contacted' AND action_date = %s",
            (today,)
        )
        return [row['boss_id'] for row in self.cursor.fetchall()]

    # ========== 聊天会话操作 ==========

    def get_chat_session(self, boss_id: str) -> Optional[Dict]:
        self.cursor.execute("SELECT * FROM chat_sessions WHERE boss_id = %s", (boss_id,))
        row = self.cursor.fetchone()
        if not row:
            return None
        session = dict(row)
        if session.get('history'):
            session['history'] = json.loads(session['history'])
        else:
            session['history'] = []
        today = datetime.now().date().isoformat()
        if session.get('last_sent_date') != today:
            session['rounds_sent_today'] = 0
        return session

    def save_chat_session(self, session: Dict):
        today = datetime.now().date().isoformat()
        history_json = json.dumps(session.get('history', []), ensure_ascii=False)
        self.cursor.execute("""
            INSERT INTO chat_sessions
            (boss_id, candidate_name, current_round_id, round_index, history,
             last_screen_text, rounds_sent_today, last_sent_date, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (boss_id) DO UPDATE SET
                candidate_name = EXCLUDED.candidate_name,
                current_round_id = EXCLUDED.current_round_id,
                round_index = EXCLUDED.round_index,
                history = EXCLUDED.history,
                last_screen_text = EXCLUDED.last_screen_text,
                rounds_sent_today = EXCLUDED.rounds_sent_today,
                last_sent_date = EXCLUDED.last_sent_date,
                updated_at = EXCLUDED.updated_at
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
                         wechat_exchanged: bool = False, detail: str = None, boss_id: str = None):
        self.cursor.execute(
            """INSERT INTO resume_operations
               (boss_id, candidate_name, action, resume_downloaded, wechat_exchanged, detail)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (boss_id, candidate_name, action, resume_downloaded, wechat_exchanged, detail)
        )
        self.conn.commit()

    def get_resume_ops(self, candidate_name: str = None, boss_id: str = None) -> List[Dict]:
        if boss_id:
            self.cursor.execute(
                "SELECT * FROM resume_operations WHERE boss_id = %s ORDER BY created_at DESC",
                (boss_id,)
            )
        elif candidate_name:
            self.cursor.execute(
                "SELECT * FROM resume_operations WHERE candidate_name = %s ORDER BY created_at DESC",
                (candidate_name,)
            )
        else:
            self.cursor.execute(
                "SELECT * FROM resume_operations ORDER BY created_at DESC LIMIT 100"
            )
        return [dict(row) for row in self.cursor.fetchall()]

    # ========== 用户操作 ==========

    def get_user_by_username(self, username: str) -> Optional[Dict]:
        self.cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict]:
        self.cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = self.cursor.fetchone()
        return dict(row) if row else None

    def create_user(self, username: str, password_hash: str, display_name: str = None,
                    role: str = 'user') -> Dict:
        self.cursor.execute(
            """INSERT INTO users (username, password_hash, display_name, role)
               VALUES (%s, %s, %s, %s) RETURNING id, username, display_name, role, is_active, created_at""",
            (username, password_hash, display_name, role)
        )
        self.conn.commit()
        return dict(self.cursor.fetchone())

    def list_users(self) -> List[Dict]:
        self.cursor.execute(
            "SELECT id, username, display_name, role, is_active, created_at, updated_at FROM users ORDER BY id"
        )
        return [dict(row) for row in self.cursor.fetchall()]

    def update_user(self, user_id: int, **kwargs) -> bool:
        allowed = {'username', 'password_hash', 'display_name', 'role', 'is_active'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        updates['updated_at'] = datetime.now().isoformat()
        set_clause = ', '.join(f"{k} = %s" for k in updates)
        self.cursor.execute(
            f"UPDATE users SET {set_clause} WHERE id = %s",
            (*updates.values(), user_id)
        )
        self.conn.commit()
        return self.cursor.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        self.cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    # ========== BOSS账号操作 ==========

    def create_boss_account(self, **kwargs) -> Dict:
        fields = ['user_id', 'account_name', 'boss_identity', 'cdp_host', 'cdp_port',
                  'profile_dir', 'cookies_file', 'use_external_browser', 'is_default', 'enabled']
        values = {k: kwargs[k] for k in fields if k in kwargs}
        columns = ', '.join(values.keys())
        placeholders = ', '.join(['%s'] * len(values))
        self.cursor.execute(
            f"INSERT INTO boss_accounts ({columns}) VALUES ({placeholders}) RETURNING *",
            tuple(values.values())
        )
        self.conn.commit()
        return dict(self.cursor.fetchone())

    def list_boss_accounts(self, user_id: int = None) -> List[Dict]:
        if user_id:
            self.cursor.execute(
                "SELECT * FROM boss_accounts WHERE user_id = %s ORDER BY id", (user_id,)
            )
        else:
            self.cursor.execute("SELECT * FROM boss_accounts ORDER BY id")
        return [dict(row) for row in self.cursor.fetchall()]

    def update_boss_account(self, account_id: int, **kwargs) -> bool:
        allowed = {'account_name', 'boss_identity', 'cdp_host', 'cdp_port',
                   'profile_dir', 'cookies_file', 'use_external_browser', 'is_default', 'enabled'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False
        updates['updated_at'] = datetime.now().isoformat()
        set_clause = ', '.join(f"{k} = %s" for k in updates)
        self.cursor.execute(
            f"UPDATE boss_accounts SET {set_clause} WHERE id = %s",
            (*updates.values(), account_id)
        )
        self.conn.commit()
        return self.cursor.rowcount > 0

    def delete_boss_account(self, account_id: int) -> bool:
        self.cursor.execute("DELETE FROM boss_accounts WHERE id = %s", (account_id,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    # ========== 统计查询 ==========

    def get_daily_stats(self, date: str = None) -> Dict:
        if not date:
            date = datetime.now().date().isoformat()

        self.cursor.execute(
            "SELECT COUNT(DISTINCT boss_id) as count FROM contact_records WHERE action = 'contacted' AND action_date = %s",
            (date,)
        )
        contacted = self.cursor.fetchone()['count']

        self.cursor.execute(
            "SELECT COUNT(DISTINCT boss_id) as count FROM contact_records WHERE action = 'replied' AND action_date = %s",
            (date,)
        )
        replied = self.cursor.fetchone()['count']

        self.cursor.execute(
            "SELECT COUNT(DISTINCT boss_id) as count FROM contact_records WHERE action = 'resume_downloaded' AND action_date = %s",
            (date,)
        )
        resume_downloaded = self.cursor.fetchone()['count']

        self.cursor.execute(
            "SELECT COUNT(*) as count FROM contact_records WHERE action = 'chat_sent' AND action_date = %s",
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

    # ========== 通用执行（供 api.py 迁移用） ==========

    def execute(self, sql: str, params: tuple = None):
        self.cursor.execute(sql, params)
        return self.cursor

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def commit(self):
        self.conn.commit()
