"""
BOSS直聘三位一体系统 - Web API v2.0
FastAPI后端，提供统一的RESTful接口 + 自动化任务控制
"""
import os, sys, json, subprocess, sqlite3, asyncio, platform
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import threading

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "boss_recruitment.db"

DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ============================================================
# FastAPI应用
# ============================================================
app = FastAPI(
    title="BOSS直聘三位一体系统",
    description="整合打招呼、获取简历、AI对话的自动化招聘系统",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# 平台自适应配置
# ============================================================
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

# 根据平台选择正确的脚本
if IS_MACOS:
    AUTOMATION_SCRIPT = BASE_DIR / "run_chat_and_resume.py"
    PLATFORM_NAME = "macOS"
elif IS_LINUX:
    AUTOMATION_SCRIPT = BASE_DIR / "run_linux.py"
    PLATFORM_NAME = "Linux"
else:
    # 默认使用 macOS 版本
    AUTOMATION_SCRIPT = BASE_DIR / "run_chat_and_resume.py"
    PLATFORM_NAME = "Unknown (fallback to macOS)"

# ============================================================
# 自动化任务管理器（异步非阻塞版）
# ============================================================
class AutomationManager:
    def __init__(self):
        self.process = None
        self.log_file = None
        self.started_at = None
        self.status = "stopped"
        self._lock = asyncio.Lock()

    async def start(self):
        """异步启动自动化进程，不阻塞主事件循环"""
        async with self._lock:
            # 检查是否已在运行
            if self.process and self.process.returncode is None:
                return {"status": "already_running", "pid": self.process.pid}

            script_path = AUTOMATION_SCRIPT
            log_path = LOGS_DIR / f"automation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

            # 使用 asyncio.create_subprocess_exec 异步启动
            try:
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable, str(script_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=str(BASE_DIR),
                    env={**os.environ, "PYTHONUNBUFFERED": "1"}
                )
                self.started_at = datetime.now()
                self.status = "running"

                # 后台任务：将子进程输出写入日志文件
                asyncio.create_task(self._log_output(self.process, log_path))

                return {
                    "status": "started",
                    "pid": self.process.pid,
                    "log_file": str(log_path),
                    "script": str(script_path),
                    "platform": PLATFORM_NAME,
                    "message": "自动化任务已后台启动"
                }
            except Exception as e:
                self.status = "error"
                return {"status": "error", "message": f"启动失败: {str(e)}"}

    async def _log_output(self, process, log_path):
        """后台任务：将子进程输出异步写入日志"""
        try:
            with open(log_path, 'w') as f:
                while True:
                    try:
                        line = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
                        if not line:
                            break
                        f.write(line.decode('utf-8', errors='replace'))
                        f.flush()
                    except asyncio.TimeoutError:
                        # 检查进程是否还在运行
                        if process.returncode is not None:
                            break
                        continue
        except Exception as e:
            pass  # 日志写入失败不影响主流程

    async def stop(self):
        """异步停止自动化进程"""
        async with self._lock:
            if not self.process or self.process.returncode is not None:
                self.status = "stopped"
                return {"status": "already_stopped"}

            try:
                self.process.terminate()
                # 等待最多5秒
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()
                self.status = "stopped"
                return {"status": "stopped", "pid": self.process.pid}
            except Exception as e:
                return {"status": "error", "message": f"停止失败: {str(e)}"}

    def get_status(self):
        """获取当前状态（同步方法，因为只是读取状态）"""
        if not self.process:
            return {"status": "stopped", "pid": None}
        if self.process.returncode is None:
            return {
                "status": "running",
                "pid": self.process.pid,
                "started_at": self.started_at.isoformat() if self.started_at else None,
                "uptime": str(datetime.now() - self.started_at) if self.started_at else None
            }
        else:
            self.status = "stopped"
            return {"status": "stopped", "exit_code": self.process.returncode}

manager = AutomationManager()

# ============================================================
# 数据库
# ============================================================
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, boss_id TEXT UNIQUE, name TEXT,
        school TEXT, degree TEXT, years INTEGER, position TEXT, company TEXT,
        status TEXT DEFAULT 'new', created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_name TEXT, round_index INTEGER DEFAULT 0,
        action TEXT, ai_message TEXT, candidate_message TEXT, detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS runtime_state (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.execute('''CREATE TABLE IF NOT EXISTS processed_candidates (
        candidate_key TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

init_db()

# ============================================================
# API端点
# ============================================================
@app.get("/")
async def root():
    return {
        "name": "BOSS直聘三位一体系统",
        "version": "2.1.0",
        "platform": PLATFORM_NAME,
        "script": str(AUTOMATION_SCRIPT),
        "docs": "/docs"
    }

@app.get("/api/automation/status")
async def automation_status():
    return manager.get_status()

@app.post("/api/automation/start")
async def start_automation():
    """启动自动化任务（异步非阻塞）"""
    return await manager.start()

@app.post("/api/automation/stop")
async def stop_automation():
    """停止自动化任务（异步非阻塞）"""
    return await manager.stop()

@app.get("/api/candidates")
async def get_candidates(status: Optional[str] = None, limit: int = 100):
    conn = get_db()
    try:
        if status:
            rows = conn.execute("SELECT * FROM candidates WHERE status = ? LIMIT ?", (status, limit)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM candidates LIMIT ?", (limit,)).fetchall()
        return {"candidates": [dict(row) for row in rows]}
    finally:
        conn.close()

@app.get("/api/stats")
async def get_stats():
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        by_status = conn.execute(
            "SELECT status, COUNT(*) as count FROM candidates GROUP BY status"
        ).fetchall()
        today_processed = conn.execute(
            "SELECT COUNT(*) FROM processed_candidates WHERE date(created_at) = date('now')"
        ).fetchone()[0]
        return {
            "total_candidates": total,
            "by_status": {row['status']: row['count'] for row in by_status},
            "today_processed": today_processed
        }
    finally:
        conn.close()

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
