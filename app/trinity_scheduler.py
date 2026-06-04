"""
三位一体调度器 v1.0
Trinity Scheduler — BOSS直聘智能招聘系统

整合三个独立Agent:
- Greet Agent: 自动打招呼
- Resume Agent: 自动获取简历
- Chat Agent: AI多轮对话
"""
import os
import sys
import time
import json
import random
import threading
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from enum import Enum
from dataclasses import dataclass
import logging

# 路径设置
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings

# ============================================================
# 日志配置
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(ROOT / 'logs' / 'trinity.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================
# 候选人状态枚举
# ============================================================

class CandidateStatus(str, Enum):
    NEW = "new"                      # 新发现
    GREETED = "greeted"               # 已打招呼
    RESUME_REQUESTED = "resume_requested"  # 已请求简历
    RESUME_DOWNLOADED = "resume_downloaded"  # 已下载简历
    WECHAT_EXCHANGED = "wechat_exchanged"   # 已换微信
    CHATTING = "chatting"             # 对话中
    INTERVIEWED = "interviewed"       # 已面试
    HIRED = "hired"                   # 已录用
    REJECTED = "rejected"             # 已拒绝

class TaskType(str, Enum):
    GREET = "greet"
    RESUME = "resume"
    CHAT = "chat"

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

# ============================================================
# 统一数据库管理
# ============================================================

class UnifiedDatabase:
    """统一数据库管理"""
    
    DB_PATH = ROOT / "data" / "trinity.db"
    
    def __init__(self):
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_tables()
    
    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_tables(self):
        """初始化数据库表"""
        with self._get_conn() as conn:
            # 候选人主表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS candidates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    boss_id TEXT UNIQUE,
                    name TEXT,
                    school TEXT,
                    degree TEXT,
                    years INTEGER,
                    position TEXT,
                    company TEXT,
                    status TEXT DEFAULT 'new',
                    greet_count INTEGER DEFAULT 0,
                    chat_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 打招呼记录
            conn.execute('''
                CREATE TABLE IF NOT EXISTS greet_records (
                    id INTEGER PRIMARY KEY,
                    candidate_id INTEGER REFERENCES candidates(id),
                    greet_time TEXT,
                    success INTEGER,
                    message TEXT,
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 简历记录
            conn.execute('''
                CREATE TABLE IF NOT EXISTS resume_records (
                    id INTEGER PRIMARY KEY,
                    candidate_id INTEGER REFERENCES candidates(id),
                    action TEXT,
                    file_path TEXT,
                    wechat TEXT,
                    success INTEGER,
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 对话记录
            conn.execute('''
                CREATE TABLE IF NOT EXISTS chat_records (
                    id INTEGER PRIMARY KEY,
                    candidate_id INTEGER REFERENCES candidates(id),
                    role TEXT,
                    content TEXT,
                    ai_generated INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 任务队列表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS task_queue (
                    id INTEGER PRIMARY KEY,
                    task_type TEXT,
                    candidate_id INTEGER REFERENCES candidates(id),
                    priority INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    params TEXT,
                    result TEXT,
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    started_at TEXT,
                    completed_at TEXT
                )
            ''')
            
            # 系统配置表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS system_config (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 创建索引
            conn.execute('CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_status ON task_queue(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tasks_type ON task_queue(task_type)')
            
            conn.commit()
            logger.info(f"数据库初始化完成: {self.DB_PATH}")
    
    # ========== 候选人操作 ==========
    
    def add_candidate(self, boss_id: str, name: str, school: str = None, 
                      degree: str = None, years: int = None, 
                      position: str = None, company: str = None) -> int:
        """添加候选人，返回ID"""
        with self._get_conn() as conn:
            try:
                cursor = conn.execute('''
                    INSERT INTO candidates (boss_id, name, school, degree, years, position, company)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (boss_id, name, school, degree, years, position, company))
                conn.commit()
                logger.info(f"添加候选人: {name} ({boss_id})")
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # 已存在，更新信息
                conn.execute('''
                    UPDATE candidates SET name=?, school=?, degree=?, years=?, position=?, company=?, updated_at=CURRENT_TIMESTAMP
                    WHERE boss_id=?
                ''', (name, school, degree, years, position, company, boss_id))
                conn.commit()
                cursor = conn.execute('SELECT id FROM candidates WHERE boss_id=?', (boss_id,))
                return cursor.fetchone()['id']
    
    def update_status(self, candidate_id: int, status: str):
        """更新候选人状态"""
        with self._get_conn() as conn:
            conn.execute('''
                UPDATE candidates SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?
            ''', (status, candidate_id))
            conn.commit()
    
    def get_candidate(self, candidate_id: int) -> Optional[Dict]:
        """获取候选人详情"""
        with self._get_conn() as conn:
            cursor = conn.execute('SELECT * FROM candidates WHERE id=?', (candidate_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def get_candidates_by_status(self, status: str) -> List[Dict]:
        """按状态获取候选人"""
        with self._get_conn() as conn:
            cursor = conn.execute('SELECT * FROM candidates WHERE status=? ORDER BY created_at DESC', (status,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_all_candidates(self, limit: int = 100) -> List[Dict]:
        """获取所有候选人"""
        with self._get_conn() as conn:
            cursor = conn.execute('SELECT * FROM candidates ORDER BY created_at DESC LIMIT ?', (limit,))
            return [dict(row) for row in cursor.fetchall()]
    
    # ========== 任务操作 ==========
    
    def add_task(self, task_type: str, candidate_id: int, priority: int = 0, 
                 params: Dict = None) -> int:
        """添加任务到队列"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                INSERT INTO task_queue (task_type, candidate_id, priority, params)
                VALUES (?, ?, ?, ?)
            ''', (task_type, candidate_id, priority, json.dumps(params) if params else None))
            conn.commit()
            logger.info(f"添加任务: {task_type} for candidate {candidate_id}")
            return cursor.lastrowid
    
    def get_pending_task(self) -> Optional[Dict]:
        """获取下一个待处理任务"""
        with self._get_conn() as conn:
            cursor = conn.execute('''
                SELECT * FROM task_queue 
                WHERE status='pending' AND retry_count < max_retries
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            ''')
            row = cursor.fetchone()
            return dict(row) if row else None
    
    def start_task(self, task_id: int):
        """开始执行任务"""
        with self._get_conn() as conn:
            conn.execute('''
                UPDATE task_queue SET status='running', started_at=CURRENT_TIMESTAMP WHERE id=?
            ''', (task_id,))
            conn.commit()
    
    def complete_task(self, task_id: int, result: Dict = None):
        """完成任务"""
        with self._get_conn() as conn:
            conn.execute('''
                UPDATE task_queue SET status='completed', result=?, completed_at=CURRENT_TIMESTAMP WHERE id=?
            ''', (json.dumps(result) if result else None, task_id))
            conn.commit()
    
    def fail_task(self, task_id: int, error: str):
        """任务失败"""
        with self._get_conn() as conn:
            conn.execute('''
                UPDATE task_queue SET status='failed', error=?, retry_count=retry_count+1 WHERE id=?
            ''', (error, task_id))
            conn.commit()
    
    def retry_task(self, task_id: int):
        """重试任务"""
        with self._get_conn() as conn:
            conn.execute('''
                UPDATE task_queue SET status='pending', error=NULL WHERE id=? AND retry_count < max_retries
            ''', (task_id,))
            conn.commit()
    
    # ========== 统计操作 ==========
    
    def get_stats(self) -> Dict:
        """获取统计数据"""
        with self._get_conn() as conn:
            stats = {}
            
            # 候选人统计
            cursor = conn.execute('SELECT COUNT(*) as total FROM candidates')
            stats['total_candidates'] = cursor.fetchone()['total']
            
            cursor = conn.execute('SELECT status, COUNT(*) as count FROM candidates GROUP BY status')
            stats['by_status'] = {row['status']: row['count'] for row in cursor.fetchall()}
            
            # 今日统计
            cursor = conn.execute('''
                SELECT COUNT(*) as count FROM greet_records 
                WHERE date(created_at) = date('now')
            ''')
            stats['today_greet'] = cursor.fetchone()['count']
            
            cursor = conn.execute('''
                SELECT COUNT(*) as count FROM chat_records 
                WHERE date(created_at) = date('now')
            ''')
            stats['today_chat'] = cursor.fetchone()['count']
            
            cursor = conn.execute('''
                SELECT COUNT(*) as count FROM resume_records 
                WHERE action='downloaded' AND date(created_at) = date('now')
            ''')
            stats['today_resume'] = cursor.fetchone()['count']
            
            # 任务队列统计
            cursor = conn.execute('SELECT status, COUNT(*) as count FROM task_queue GROUP BY status')
            stats['task_queue'] = {row['status']: row['count'] for row in cursor.fetchall()}
            
            return stats
    
    # ========== 配置操作 ==========
    
    def get_config(self, key: str, default: str = None) -> Optional[str]:
        """获取配置"""
        with self._get_conn() as conn:
            cursor = conn.execute('SELECT value FROM system_config WHERE key=?', (key,))
            row = cursor.fetchone()
            return row['value'] if row else default
    
    def set_config(self, key: str, value: str):
        """设置配置"""
        with self._get_conn() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO system_config (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (key, value))
            conn.commit()


# ============================================================
# 基础Agent类
# ============================================================

class BaseAgent:
    """Agent基类"""
    
    def __init__(self, db: UnifiedDatabase):
        self.db = db
        self.running = False
        self.interval = 60  # 默认60秒检查一次
    
    def run_once(self) -> Dict:
        """执行一次任务，子类实现"""
        raise NotImplementedError
    
    def run_continuous(self):
        """持续运行"""
        self.running = True
        logger.info(f"{self.__class__.__name__} 开始持续运行")
        
        while self.running:
            try:
                result = self.run_once()
                if result:
                    logger.info(f"{self.__class__.__name__} 执行完成: {result}")
            except Exception as e:
                logger.error(f"{self.__class__.__name__} 执行出错: {e}")
            
            time.sleep(self.interval)
    
    def stop(self):
        """停止运行"""
        self.running = False
        logger.info(f"{self.__class__.__name__} 已停止")


# ============================================================
# 三位一体调度器
# ============================================================

class TrinityScheduler:
    """三位一体调度器"""
    
    def __init__(self):
        self.db = UnifiedDatabase()
        self.agents: Dict[str, BaseAgent] = {}
        self.threads: Dict[str, threading.Thread] = {}
        self.running = False
        
        # 加载配置
        self.daily_greet_cap = int(self.db.get_config('daily_greet_cap', '80'))
        self.school_whitelist = json.loads(
            self.db.get_config('school_whitelist', '[]')
        ) or self._default_school_whitelist()
    
    def _default_school_whitelist(self) -> List[str]:
        """默认学校白名单"""
        return [
            "清华大学", "北京大学", "浙江大学", "复旦大学", 
            "上海交通大学", "南京大学", "中国科学技术大学",
            "哈尔滨工业大学", "西安交通大学", "北京航空航天大学",
            "同济大学", "华中科技大学", "中山大学", "华南理工大学", "武汉大学",
            "香港大学", "香港科技大学", "香港中文大学", "台湾大学",
            "牛津", "剑桥", "MIT", "斯坦福", "哈佛", "普林斯顿", "耶鲁",
        ]
    
    def register_agent(self, name: str, agent: BaseAgent):
        """注册Agent"""
        self.agents[name] = agent
        logger.info(f"注册Agent: {name}")
    
    def start_all(self):
        """启动所有Agent"""
        self.running = True
        logger.info("=== 三位一体调度器启动 ===")
        
        for name, agent in self.agents.items():
            thread = threading.Thread(target=agent.run_continuous, daemon=True)
            thread.start()
            self.threads[name] = thread
            logger.info(f"Agent {name} 已启动")
    
    def stop_all(self):
        """停止所有Agent"""
        self.running = False
        for name, agent in self.agents.items():
            agent.stop()
        logger.info("=== 三位一体调度器已停止 ===")
    
    def run_daily_workflow(self):
        """每日工作流"""
        logger.info("开始每日工作流")
        
        # 1. 早9点：执行打招呼
        self._run_greet_batch()
        
        # 2. 持续：处理简历请求
        self._run_resume_batch()
        
        # 3. 持续：AI对话跟进
        self._run_chat_batch()
    
    def _run_greet_batch(self):
        """批量打招呼"""
        if 'greet' not in self.agents:
            logger.warning("Greet Agent未注册")
            return
        
        # 检查今日上限
        stats = self.db.get_stats()
        remaining = self.daily_greet_cap - stats.get('today_greet', 0)
        
        if remaining <= 0:
            logger.info(f"今日打招呼已达上限: {self.daily_greet_cap}")
            return
        
        logger.info(f"今日剩余打招呼额度: {remaining}")
        self.agents['greet'].run_once()
    
    def _run_resume_batch(self):
        """批量获取简历"""
        if 'resume' not in self.agents:
            logger.warning("Resume Agent未注册")
            return
        
        self.agents['resume'].run_once()
    
    def _run_chat_batch(self):
        """批量对话"""
        if 'chat' not in self.agents:
            logger.warning("Chat Agent未注册")
            return
        
        self.agents['chat'].run_once()
    
    def get_status(self) -> Dict:
        """获取系统状态"""
        stats = self.db.get_stats()
        stats['agents'] = {
            name: {
                'running': agent.running,
                'interval': agent.interval
            }
            for name, agent in self.agents.items()
        }
        return stats


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    # 创建调度器
    scheduler = TrinityScheduler()
    
    # 测试数据库
    db = scheduler.db
    
    # 添加测试候选人
    test_id = db.add_candidate(
        boss_id="test_001",
        name="张三",
        school="清华大学",
        degree="硕士",
        years=5,
        position="高级工程师",
        company="字节跳动"
    )
    
    # 获取统计
    stats = db.get_stats()
    print(f"统计: {json.dumps(stats, indent=2, ensure_ascii=False)}")
    
    print("\n✅ 三位一体调度器测试完成")
