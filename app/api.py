"""
BOSS直聘三位一体系统 - Web API v2.0
FastAPI后端，提供统一的RESTful接口 + 自动化任务控制
"""
import os, sys, json, subprocess, sqlite3, asyncio, platform
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
import threading

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# Import authentication module
from app.auth import verify_token, create_access_token, verify_credentials
# Import logging
from app.logging_config import api_logger
# Import automation singleton
from app.automation import automation
# Import school whitelists for filter config (lightweight, no heavy deps)
from app.filter_criteria import DOMESTIC_ELITE_SCHOOLS, US_ELITE_SCHOOLS, UK_ELITE_SCHOOLS, OTHER_ELITE_SCHOOLS

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

# CORS配置：从环境变量读取允许的来源
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8001,http://localhost:8321,http://localhost:3101").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# 模板和静态文件
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# ============================================================
# 平台自适应配置
# ============================================================
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

# 使用统一的boss.py脚本
AUTOMATION_SCRIPT = BASE_DIR / "boss.py"
PLATFORM_NAME = platform.system()  # macOS, Linux, etc.

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
                # 使用 boss.py 的 all 命令运行完整流程
                self.process = await asyncio.create_subprocess_exec(
                    sys.executable, str(script_path), "all", "--limit", "30",
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
    # 候选人表
    conn.execute('''CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, boss_id TEXT UNIQUE, name TEXT,
        school TEXT, degree TEXT, years INTEGER, position TEXT, company TEXT,
        status TEXT DEFAULT 'new', created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    # 对话记录表
    conn.execute('''CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT, candidate_name TEXT, round_index INTEGER DEFAULT 0,
        action TEXT, ai_message TEXT, candidate_message TEXT, detail TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    # 运行时状态表
    conn.execute('''CREATE TABLE IF NOT EXISTS runtime_state (
        key TEXT PRIMARY KEY, value TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
    # 已处理候选人表
    conn.execute('''CREATE TABLE IF NOT EXISTS processed_candidates (
        candidate_key TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
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

init_db()

# ============================================================
# API端点
# ============================================================
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """主页 - 简化版Web UI"""
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

@app.get("/api/automation/status")
async def automation_status(current_user: dict = Depends(verify_token)):
    return manager.get_status()

@app.post("/api/automation/start")
async def start_automation(current_user: dict = Depends(verify_token)):
    """启动自动化任务（异步非阻塞，需要认证）"""
    return await manager.start()

@app.post("/api/automation/stop")
async def stop_automation(current_user: dict = Depends(verify_token)):
    """停止自动化任务（异步非阻塞，需要认证）"""
    return await manager.stop()

@app.get("/api/candidates")
async def get_candidates(
    status: Optional[str] = None,
    limit: int = 100,
    current_user: dict = Depends(verify_token)
):
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
async def get_stats(current_user: dict = Depends(verify_token)):
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

# ============================================================
# 认证相关端点
# ============================================================
class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str


@app.post("/api/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """用户登录 - 返回JWT访问令牌"""
    if verify_credentials(req.username, req.password):
        token = create_access_token({"sub": req.username})
        return LoginResponse(access_token=token, token_type="bearer")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="认证失败：用户名或密码错误"
    )


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/health")
async def api_health():
    """健康检查端点（API路径）"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# ============================================================
# 简化版核心功能端点（无需认证）
# ============================================================
class WorkflowRequest(BaseModel):
    limit: int = 10


# ============================================================
# 浏览器连接API端点
# ============================================================

class BrowserConnectRequest(BaseModel):
    headless: bool = False


@app.post("/api/browser/connect")
async def connect_browser(req: BrowserConnectRequest = None):
    """连接到本地浏览器或启动新的

    Chrome需要以调试模式启动（使用CDP）：
    macOS:
    /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222
    Linux:
    google-chrome --remote-debugging-port=9222

    如果没有检测到已打开的Chrome，将启动新的浏览器实例。
    """
    if req is None:
        req = BrowserConnectRequest()
    return await automation.connect(headless=req.headless if req else False)


@app.get("/api/browser/status")
async def get_browser_status():
    """获取浏览器连接状态"""
    return automation.get_status()


@app.post("/api/browser/disconnect")
async def disconnect_browser():
    """断开浏览器连接"""
    return await automation.disconnect()


# ---- VNC Config ----

@app.get("/api/vnc/config")
async def get_vnc_config(request: Request):
    """获取VNC连接配置（密码来自环境变量，不设硬编码默认值）"""
    vnc_password = os.environ.get("VNC_PASSWORD")
    if not vnc_password:
        raise HTTPException(
            status_code=500,
            detail="VNC_PASSWORD 环境变量未设置。请在 .env 或 docker-compose.yml 中配置。"
        )
    # 动态获取 hostname，支持远程部署
    host_header = request.headers.get("host", "localhost:8321")
    hostname = host_header.split(":")[0]
    return {
        "host": hostname,
        "port": 5901,
        "password": vnc_password,
        "novnc_url": f"http://{hostname}:6901/?autoconnect=true&reconnect=true&show_dot=true"
    }


class ScreenshotRequest(BaseModel):
    full_page: bool = False


@app.post("/api/browser/screenshot")
async def browser_screenshot(req: ScreenshotRequest = None):
    """获取当前页面截图

    返回base64编码的PNG图片
    """
    if req is None:
        req = ScreenshotRequest()
    return await automation.screenshot(full_page=req.full_page)


class NavigateRequest(BaseModel):
    url: str


@app.post("/api/browser/navigate")
async def browser_navigate(req: NavigateRequest):
    """导航到指定URL"""
    return await automation.navigate(req.url)


class ExecuteScriptRequest(BaseModel):
    script: str


@app.post("/api/browser/execute")
async def browser_execute_script(req: ExecuteScriptRequest):
    """在页面中执行JavaScript"""
    return await automation.execute_js(req.script)


@app.post("/api/browser/open-boss")
async def open_boss_browser():
    """打开BOSS直聘 - 在VNC桌面中启动Chrome并导航到zhipin.com

    启动系统Chrome浏览器（可见于VNC桌面），启用CDP远程调试端口9222，
    然后通过Playwright连接到该浏览器实例，供后续自动化控制使用。

    流程：
    1. 清理可能占用9222端口的旧Chrome进程
    2. 在X11桌面（DISPLAY=:1）中启动Chrome，直接打开zhipin.com
    3. 等待CDP调试端口就绪（最多30秒）
    4. 通过browser_manager连接到已启动的Chrome
    """
    import subprocess, time, socket

    # 平台适配：选择正确的Chrome可执行文件
    if IS_MACOS:
        chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    else:
        # Linux容器中: Playwright Chromium 已软链接为 google-chrome
        chrome_bin = "google-chrome"

    # 1. 清理可能占用调试端口的旧Chrome进程
    try:
        subprocess.run(
            ["pkill", "-f", "remote-debugging-port=9222"],
            capture_output=True, timeout=5
        )
        time.sleep(1)
    except Exception:
        pass  # 没有旧进程，忽略

    # 如果automation已经连接到现有Chrome，先断开
    if automation._connected:
        await automation.disconnect()

    # 2. 启动Chrome在X11桌面中（VNC可见）
    display = os.environ.get("DISPLAY", ":1")
    env = os.environ.copy()
    env["DISPLAY"] = display

    chrome_args = [
        chrome_bin,
        "--remote-debugging-port=9222",
        "--remote-debugging-address=0.0.0.0",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1280,720",
        "--window-position=0,0",
        "--no-first-run",
        "--no-default-browser-check",
        "--user-data-dir=/app/data/chrome-profile",
        "https://www.zhipin.com/",
    ]

    try:
        subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError:
        return {"status": "error", "message": f"未找到Chrome浏览器: {chrome_bin}"}
    except Exception as e:
        return {"status": "error", "message": f"启动Chrome失败: {str(e)}"}

    # 3. 等待CDP调试端口就绪（最多30秒）
    cdp_ready = False
    for _ in range(30):
        time.sleep(1)
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("localhost", 9222))
            sock.close()
            if result == 0:
                cdp_ready = True
                break
        except Exception:
            pass

    if not cdp_ready:
        return {
            "status": "error",
            "message": "Chrome进程已启动但CDP调试端口未就绪（30秒超时），请检查VNC桌面",
        }

    # 4. 通过CDP连接到已启动的Chrome
    connect_result = await automation.connect()

    return {
        "status": "ok",
        "message": "Chrome已启动并打开BOSS直聘，可在VNC桌面中查看",
        "cdp_ready": cdp_ready,
        "connect_result": connect_result,
    }


# ============================================================
# 兼容旧端点（已弃用）
# ============================================================

@app.post("/api/browser/open")
async def open_browser():
    """[已弃用] 打开浏览器进行登录

    请使用 POST /api/browser/connect 替代
    """
    result = await automation.connect()
    # 如果成功连接，导航到BOSS直聘登录页
    if result.get("status") == "connected":
        await automation.navigate("https://www.zhipin.com/")
    return result


@app.get("/api/browser/check-login")
async def check_browser_login():
    """检测 BOSS直聘登录状态"""
    return await automation.check_login()


@app.post("/api/workflow/say-hello")
async def say_hello(req: WorkflowRequest):
    """主动打招呼"""
    try:
        api_logger.info(f"启动打招呼任务，上限 {req.limit} 人")
        # TODO: 实现实际的打招呼逻辑
        return {"status": "started", "message": f"打招呼任务已启动，上限 {req.limit} 人"}
    except Exception as e:
        api_logger.error(f"打招呼任务失败: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/workflow/get-resumes")
async def get_resumes(req: WorkflowRequest):
    """批量获取简历"""
    try:
        api_logger.info(f"启动简历获取任务，上限 {req.limit} 人")
        # TODO: 实现实际的简历获取逻辑
        return {"status": "started", "message": f"简历获取任务已启动，上限 {req.limit} 人"}
    except Exception as e:
        api_logger.error(f"简历获取任务失败: {e}")
        return {"status": "error", "message": str(e)}


@app.post("/api/workflow/reply-messages")
async def reply_messages(req: WorkflowRequest):
    """批量回复未读消息"""
    try:
        api_logger.info(f"启动消息回复任务，上限 {req.limit} 人")
        # TODO: 实现实际的消息回复逻辑
        return {"status": "started", "message": f"消息回复任务已启动，上限 {req.limit} 人"}
    except Exception as e:
        api_logger.error(f"消息回复任务失败: {e}")
        return {"status": "error", "message": str(e)}


# ============================================================
# 简历管理端点
# ============================================================

class BatchResumeRequest(BaseModel):
    """批量获取简历请求"""
    limit: int = 10
    candidate_ids: Optional[List[str]] = None  # 指定候选人ID列表


class ResumeInfo(BaseModel):
    """简历信息"""
    id: int
    candidate_name: str
    file_name: str
    file_path: str
    file_size: int
    status: str  # downloaded, requested, failed
    created_at: str


# 全局简历任务状态
resume_task_status = {"status": "idle", "processed": 0, "total": 0, "message": ""}


@app.post("/api/resume/batch")
async def batch_download_resumes(
    req: BatchResumeRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(verify_token)
):
    """
    批量获取简历

    启动后台任务，批量下载候选人简历
    """
    global resume_task_status

    # 检查是否有正在运行的任务
    if resume_task_status["status"] == "running":
        return {"status": "error", "message": "已有任务正在运行"}

    try:
        # 启动后台任务
        def run_resume_task():
            global resume_task_status
            try:
                import subprocess
                import sys

                resume_task_status = {
                    "status": "running",
                    "processed": 0,
                    "total": req.limit,
                    "message": f"正在处理 {req.limit} 个候选人...",
                    "start_time": datetime.now().isoformat()
                }
                api_logger.info(f"启动批量简历下载任务，上限 {req.limit} 人")

                # 直接运行 resume_collector.py
                script_path = BASE_DIR / "app" / "resume_collector.py"

                if not script_path.exists():
                    resume_task_status["status"] = "error"
                    resume_task_status["message"] = f"脚本不存在: {script_path}"
                    api_logger.error(f"简历收集脚本不存在: {script_path}")
                    return

                result = subprocess.run(
                    [sys.executable, str(script_path), "--max", str(req.limit)],
                    capture_output=True,
                    text=True,
                    timeout=1800,  # 30分钟超时
                    cwd=str(BASE_DIR)
                )

                if result.returncode == 0:
                    resume_task_status["status"] = "completed"
                    resume_task_status["message"] = "任务完成"
                    resume_task_status["end_time"] = datetime.now().isoformat()
                    api_logger.info(f"简历下载任务完成")
                else:
                    resume_task_status["status"] = "error"
                    resume_task_status["message"] = f"任务失败: {result.stderr[-200:]}"
                    api_logger.error(f"简历下载任务失败: {result.stderr}")

            except subprocess.TimeoutExpired:
                resume_task_status["status"] = "error"
                resume_task_status["message"] = "任务超时"
                api_logger.error("简历下载任务超时")
            except Exception as e:
                resume_task_status["status"] = "error"
                resume_task_status["message"] = str(e)
                api_logger.error(f"简历下载任务失败: {e}")

        # 在后台线程中运行
        import threading
        thread = threading.Thread(target=run_resume_task, daemon=True)
        thread.start()

        return {
            "status": "started",
            "message": f"批量简历下载任务已启动，上限 {req.limit} 人",
            "task_id": "resume_batch_1"
        }

    except Exception as e:
        api_logger.error(f"启动批量简历下载失败: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/resume/status")
async def get_resume_task_status(current_user: dict = Depends(verify_token)):
    """获取批量简历任务状态"""
    return resume_task_status


@app.get("/api/resume/list")
async def list_resumes(
    status: Optional[str] = None,
    limit: int = 100,
    current_user: dict = Depends(verify_token)
):
    """
    获取已下载简历列表

    Args:
        status: 筛选状态 (downloaded, requested, failed)
        limit: 返回数量上限

    Returns:
        List of resume information dictionaries
    """
    conn = get_db()
    try:
        # 查询简历操作记录
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
                # 根据候选人名字查找简历文件
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
                "file_path": file_path or "",
                "file_size": file_size,
                "status": "downloaded" if file_exists else "requested",
                "created_at": row["created_at"]
            })

        return resumes

    finally:
        conn.close()


@app.get("/api/resume/download/{resume_id}")
async def download_resume(
    resume_id: int,
    current_user: dict = Depends(verify_token)
):
    """
    下载简历文件

    Args:
        resume_id: 简历记录ID
    """
    from fastapi.responses import FileResponse

    conn = get_db()
    try:
        # 获取简历记录
        row = conn.execute(
            "SELECT * FROM resume_operations WHERE id = ?",
            (resume_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="简历记录不存在")

        candidate_name = row["candidate_name"]

        # 查找简历文件
        resumes_dir = DATA_DIR / "resumes"
        file_path = None

        for ext in [".pdf", ".doc", ".docx"]:
            potential_file = resumes_dir / f"{candidate_name}{ext}"
            if potential_file.exists():
                file_path = potential_file
                break

        if not file_path or not file_path.exists():
            raise HTTPException(status_code=404, detail="简历文件不存在")

        # 返回文件
        return FileResponse(
            path=str(file_path),
            filename=file_path.name,
            media_type="application/octet-stream"
        )

    finally:
        conn.close()


@app.get("/api/resume/stats")
async def get_resume_stats(current_user: dict = Depends(verify_token)):
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


# ============================================================
# 筛选打招呼功能
# ============================================================

class FilterContactRequest(BaseModel):
    """筛选打招呼请求参数

    当前支持: school_whitelist, min_degree, min_years
    后续可扩展: age_range, tech_stack, industry, job_title_keywords
    """
    daily_cap: Optional[int] = 80
    school_whitelist: Optional[List[str]] = None
    min_degree: Optional[str] = "本科"
    min_years: Optional[int] = 3
    dry_run: Optional[bool] = False
    # ---- 预留扩展字段 ----
    age_range: Optional[Tuple[int, int]] = None       # (min_age, max_age)
    tech_stack: Optional[List[str]] = None              # ["Python", "React", ...]
    industry: Optional[List[str]] = None                # ["互联网", "金融", ...]
    job_title_keywords: Optional[List[str]] = None      # ["工程师", "产品经理", ...]


class FilterContactResponse(BaseModel):
    """筛选打招呼响应"""
    task_id: str
    status: str
    message: str
    preview: Optional[Dict] = None


# 任务状态存储
_filter_tasks: Dict[str, Dict] = {}


def generate_task_id() -> str:
    """生成任务ID"""
    import uuid
    return str(uuid.uuid4())[:8]


@app.post("/api/filter/contact", response_model=FilterContactResponse)
async def start_filter_contact(
    req: FilterContactRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(verify_token)
):
    """
    启动筛选打招呼任务

    参数:
        daily_cap: 每日上限 (默认80)
        school_whitelist: 学校白名单 (默认配置中的名校)
        min_degree: 最低学历 (默认本科)
        min_years: 最低工作年限 (默认3年)
        dry_run: 是否预览模式 (默认False)

    返回:
        task_id: 任务ID用于查询进度
        status: 任务状态
        message: 状态消息
        preview: 预览结果(dry_run模式时)
    """
    try:
        api_logger.info(f"用户 {current_user['sub']} 启动筛选打招呼任务")

        # 生成任务ID
        task_id = generate_task_id()

        # 设置默认学校白名单（国内+海外名校）
        if req.school_whitelist is None:
            req.school_whitelist = DOMESTIC_ELITE_SCHOOLS + US_ELITE_SCHOOLS + UK_ELITE_SCHOOLS

        # 构建可扩展筛选条件
        criteria = FilterCriteria(
            school_whitelist=req.school_whitelist,
            min_degree=req.min_degree,
            min_years=req.min_years,
            age_range=req.age_range,
            tech_stack=req.tech_stack,
            industry=req.industry,
            job_title_keywords=req.job_title_keywords,
        )

        # 初始化任务状态
        _filter_tasks[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "progress": 0,
            "started_at": datetime.now().isoformat(),
            "params": req.dict(),
            "result": None,
            "error": None
        }

        # 添加后台任务
        background_tasks.add_task(
            _execute_filter_contact,
            task_id,
            req.daily_cap,
            criteria,
            req.dry_run
        )

        return FilterContactResponse(
            task_id=task_id,
            status="queued",
            message=f"筛选打招呼任务已加入队列，任务ID: {task_id}"
        )

    except Exception as e:
        api_logger.error(f"启动筛选打招呼任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _execute_filter_contact(
    task_id: str,
    daily_cap: int,
    criteria: "FilterCriteria",
    dry_run: bool
):
    """执行筛选打招呼任务（后台运行）"""
    try:
        # 更新状态为运行中
        _filter_tasks[task_id]["status"] = "running"
        _filter_tasks[task_id]["progress"] = 10

        # 导入workflow模块 - Phase 1 使用 try/except 包装
        try:
            from app.workflows import workflow_3_1_auto_contact
        except ImportError as e:
            _filter_tasks[task_id]["status"] = "error"
            _filter_tasks[task_id]["error"] = f"工作流模块未就绪: {e}"
            _filter_tasks[task_id]["completed_at"] = datetime.now().isoformat()
            api_logger.error(f"任务 {task_id} 失败: 工作流模块未就绪")
            return

        api_logger.info(f"任务 {task_id} 开始执行筛选打招呼")

        # 执行workflow
        result = workflow_3_1_auto_contact(
            daily_cap=daily_cap,
            criteria=criteria,
            dry_run=dry_run
        )

        # 更新任务状态
        _filter_tasks[task_id]["status"] = result.get("status", "unknown")
        _filter_tasks[task_id]["progress"] = 100
        _filter_tasks[task_id]["result"] = result
        _filter_tasks[task_id]["completed_at"] = datetime.now().isoformat()

        api_logger.info(f"任务 {task_id} 完成: {result.get('status')}")

    except Exception as e:
        api_logger.error(f"任务 {task_id} 执行失败: {e}")
        _filter_tasks[task_id]["status"] = "failed"
        _filter_tasks[task_id]["error"] = str(e)
        _filter_tasks[task_id]["completed_at"] = datetime.now().isoformat()


@app.get("/api/filter/status/{task_id}")
async def get_filter_status(task_id: str, current_user: dict = Depends(verify_token)):
    """
    查询筛选任务状态

    参数:
        task_id: 任务ID

    返回:
        任务状态、进度、结果等信息
    """
    if task_id not in _filter_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = _filter_tasks[task_id]
    return {
        "task_id": task["task_id"],
        "status": task["status"],
        "progress": task.get("progress", 0),
        "started_at": task.get("started_at"),
        "completed_at": task.get("completed_at"),
        "result": task.get("result"),
        "error": task.get("error"),
        "params": task.get("params")
    }


@app.get("/api/filter/config")
async def get_filter_config(current_user: dict = Depends(verify_token)):
    """
    获取筛选配置

    返回:
        默认的学校白名单（国内+海外名校）、学历选项、工作年限选项、
        以及可扩展的筛选维度
    """
    return {
        "school_whitelist": {
            "domestic": DOMESTIC_ELITE_SCHOOLS,
            "us": US_ELITE_SCHOOLS,
            "uk": UK_ELITE_SCHOOLS,
            "other": OTHER_ELITE_SCHOOLS,
            "all": DOMESTIC_ELITE_SCHOOLS + US_ELITE_SCHOOLS + UK_ELITE_SCHOOLS + OTHER_ELITE_SCHOOLS,
        },
        "degree_options": ["博士", "硕士", "本科", "大专"],
        "min_degree_default": "本科",
        "years_options": [1, 2, 3, 5, 10],
        "min_years_default": 3,
        "daily_cap_default": 80,
        "daily_cap_range": [10, 20, 50, 80, 100, 150],
        # 可扩展的筛选维度（当前全部可选）
        "available_filters": [
            {"key": "school_whitelist", "label": "学校白名单", "type": "multi_select", "enabled": True},
            {"key": "min_degree", "label": "最低学历", "type": "select", "enabled": True},
            {"key": "min_years", "label": "最低工作年限", "type": "number", "enabled": True},
            {"key": "age_range", "label": "年龄范围", "type": "range", "enabled": False, "note": "后续扩展"},
            {"key": "tech_stack", "label": "技术栈", "type": "multi_select", "enabled": False, "note": "后续扩展"},
            {"key": "industry", "label": "行业经验", "type": "multi_select", "enabled": False, "note": "后续扩展"},
            {"key": "job_title_keywords", "label": "职位关键词", "type": "multi_select", "enabled": False, "note": "后续扩展"},
        ],
    }


@app.put("/api/filter/config")
async def update_filter_config(
    config: Dict[str, Any],
    current_user: dict = Depends(verify_token)
):
    """
    更新筛选配置（保存到数据库runtime_state表）

    参数:
        school_whitelist: 学校白名单
        min_degree: 最低学历
        min_years: 最低工作年限
        daily_cap: 每日上限

    返回:
        更新后的配置
    """
    try:
        conn = get_db()
        config_json = json.dumps(config)

        # 保存到runtime_state表
        conn.execute(
            "INSERT OR REPLACE INTO runtime_state (key, value, updated_at) VALUES (?, ?, ?)",
            ("filter_config", config_json, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()

        api_logger.info(f"用户 {current_user['sub']} 更新筛选配置")

        return {"status": "success", "config": config}

    except Exception as e:
        api_logger.error(f"更新筛选配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# AI批量回复端点
# ============================================================

class BatchReplyRequest(BaseModel):
    """批量回复请求"""
    limit: int = 10
    candidate_ids: Optional[List[str]] = None
    template_id: Optional[int] = None
    custom_template: Optional[str] = None
    dry_run: bool = False


class TemplateRequest(BaseModel):
    """模板保存请求"""
    name: str
    content: str


class ReplyResult(BaseModel):
    """单个回复结果"""
    boss_id: str
    candidate_name: str
    success: bool
    reply_content: Optional[str]
    error_message: Optional[str]


class BatchReplyResponse(BaseModel):
    """批量回复响应"""
    total: int
    success_count: int
    failed_count: int
    results: List[ReplyResult]
    message: str


@app.post("/api/chat/batch", response_model=BatchReplyResponse)
async def batch_reply_messages(
    req: BatchReplyRequest,
    current_user: dict = Depends(verify_token)
):
    """批量AI回复消息"""
    from app.chat_service import chat_service

    try:
        candidates = chat_service.get_unread_messages()

        if req.candidate_ids:
            candidates = [c for c in candidates if c.get("boss_id") in req.candidate_ids]

        candidates = candidates[:req.limit]

        if not candidates:
            return BatchReplyResponse(
                total=0, success_count=0, failed_count=0,
                results=[], message="没有待回复的消息"
            )

        # 获取模板
        template_content = None
        if req.template_id:
            templates = chat_service.get_templates()
            template = next((t for t in templates if t["id"] == req.template_id), None)
            if template:
                template_content = template["content"]
        elif req.custom_template:
            template_content = req.custom_template

        results = []
        success_count = 0
        failed_count = 0

        for candidate in candidates:
            boss_id = candidate.get("boss_id", "")
            candidate_name = candidate.get("candidate_name") or candidate.get("name", "未知")

            history = chat_service.get_conversation_history(candidate_name, limit=10)
            formatted_history = []
            for h in reversed(history):
                if h.get("candidate_message"):
                    formatted_history.append({"role": "user", "content": h["candidate_message"]})
                if h.get("ai_message"):
                    formatted_history.append({"role": "assistant", "content": h["ai_message"]})

            last_candidate_msg = "你好，我对这个职位很感兴趣，想了解更多详情。"

            reply_content, error = await chat_service.generate_reply(
                candidate_name=candidate_name,
                candidate_message=last_candidate_msg,
                history=formatted_history,
                template=template_content
            )

            if not reply_content:
                failed_count += 1
                results.append(ReplyResult(
                    boss_id=boss_id, candidate_name=candidate_name,
                    success=False, reply_content=None, error_message=error
                ))
                continue

            send_success = True
            send_error = None
            if not req.dry_run:
                send_success, send_error = await chat_service.send_to_boss(boss_id, reply_content)

            if send_success:
                chat_service.save_conversation(
                    boss_id=boss_id, candidate_name=candidate_name,
                    candidate_message=last_candidate_msg,
                    ai_message=reply_content, action="auto_reply"
                )

            if send_success:
                success_count += 1
                results.append(ReplyResult(
                    boss_id=boss_id, candidate_name=candidate_name,
                    success=True, reply_content=reply_content, error_message=None
                ))
            else:
                failed_count += 1
                results.append(ReplyResult(
                    boss_id=boss_id, candidate_name=candidate_name,
                    success=False, reply_content=reply_content, error_message=send_error
                ))

        return BatchReplyResponse(
            total=len(candidates),
            success_count=success_count,
            failed_count=failed_count,
            results=results,
            message=f"批量回复完成，成功{success_count}条，失败{failed_count}条"
        )

    except Exception as e:
        api_logger.error(f"批量回复失败: {e}")
        return BatchReplyResponse(
            total=0, success_count=0, failed_count=0,
            results=[], message=f"批量回复失败: {str(e)}"
        )


@app.get("/api/chat/history")
async def get_chat_history(
    candidate_name: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(verify_token)
):
    """获取对话历史"""
    from app.chat_service import chat_service

    try:
        history = chat_service.get_conversation_history(candidate_name=candidate_name, limit=limit)
        return {"total": len(history), "candidate_name": candidate_name, "history": history}
    except Exception as e:
        api_logger.error(f"获取对话历史失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/template")
async def save_template(
    req: TemplateRequest,
    current_user: dict = Depends(verify_token)
):
    """保存回复模板"""
    from app.chat_service import chat_service

    try:
        template_id = chat_service.save_template(
            name=req.name,
            content=req.content,
            user_id=current_user.get("sub", "default")
        )
        return {"id": template_id, "name": req.name, "content": req.content, "message": "模板保存成功"}
    except Exception as e:
        api_logger.error(f"保存模板失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chat/templates")
async def get_templates(current_user: dict = Depends(verify_token)):
    """获取所有回复模板"""
    from app.chat_service import chat_service

    try:
        templates = chat_service.get_templates(user_id=current_user.get("sub", "default"))
        return {"templates": templates}
    except Exception as e:
        api_logger.error(f"获取模板失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/template/list")
async def get_template_list(current_user: dict = Depends(verify_token)):
    """获取所有回复模板（兼容端点）"""
    from app.chat_service import chat_service

    try:
        templates = chat_service.get_templates(user_id=current_user.get("sub", "default"))
        return {"templates": templates}
    except Exception as e:
        api_logger.error(f"获取模板失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
