"""
BOSS直聘三位一体系统 - Web API v2.0
FastAPI后端，提供统一的RESTful接口 + 自动化任务控制
"""
import os, sys, json, subprocess, asyncio, platform
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
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# Import authentication module
from app.auth import verify_token, create_access_token, verify_credentials, ensure_admin_user
# Import logging
from app.logging_config import api_logger
# Import automation singleton
from app.automation import automation
# Import database
from app.database import Database
# Import school whitelists for filter config (lightweight, no heavy deps)
from app.filter_criteria import DOMESTIC_ELITE_SCHOOLS, US_ELITE_SCHOOLS, UK_ELITE_SCHOOLS, OTHER_ELITE_SCHOOLS, FilterCriteria

# 海外名校合并（美国+英国+其他）
INTERNATIONAL_ELITE_SCHOOLS = US_ELITE_SCHOOLS + UK_ELITE_SCHOOLS + OTHER_ELITE_SCHOOLS

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

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
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:8000,http://localhost:8001,http://localhost:8321,http://localhost:3101").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
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
# 浏览器任务互斥锁 — 同一时刻只有一个F5/F6/F7任务占用浏览器
# ============================================================
_browser_task_lock = threading.Lock()
_active_task_type: Optional[str] = None
_LOCK_TIMEOUT_SECONDS = 600  # 10 分钟锁超时
_lock_acquired_at: Optional[float] = None  # 锁获取时间


def _force_unlock_if_stale():
    """如果锁被持有超过 _LOCK_TIMEOUT_SECONDS，强制释放（防死锁）"""
    global _active_task_type, _lock_acquired_at
    if _lock_acquired_at and _browser_task_lock.locked():
        import time as _time
        if _time.time() - _lock_acquired_at > _LOCK_TIMEOUT_SECONDS:
            api_logger.warning(f"锁超时 ({_LOCK_TIMEOUT_SECONDS}s)，强制释放 (task={_active_task_type})")
            try:
                _browser_task_lock.release()
            except RuntimeError:
                pass
            _active_task_type = None
            _lock_acquired_at = None


@app.post("/api/browser/force-unlock")
async def force_unlock_browser():
    """强制释放浏览器任务锁（紧急恢复用）"""
    global _active_task_type, _lock_acquired_at
    try:
        if _browser_task_lock.locked():
            _browser_task_lock.release()
    except RuntimeError:
        pass
    _active_task_type = None
    _lock_acquired_at = None
    return {"status": "ok", "message": "浏览器锁已强制释放"}


@app.post("/api/tasks/cancel")
async def cancel_current_task(current_user: dict = Depends(verify_token)):
    """取消当前正在运行的自动化任务（F5/F6/F7/F8）

    设置取消信号，后台线程会在下一个检查点检测到并停止。
    """
    from app.automation import cancel_event
    cancel_event.set()
    api_logger.info(f"[Cancel] 取消信号已设置 (当前任务: {_active_task_type})")
    return {"status": "ok", "message": f"取消信号已发出，{_active_task_type or '无'} 任务将在下一个检查点停止"}

# ============================================================
# 数据库
# ============================================================
def get_db():
    """获取数据库连接（PostgreSQL）"""
    db = Database()
    db.connect()
    return db

@app.on_event("startup")
def on_startup():
    ensure_admin_user()

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
    """获取候选人列表 — 聚合 candidates + contact_records + resume_operations

    Returns:
        candidates 列表，每项包含: name, school, degree, years, position, status, resume_path, contacted_at
    """
    conn = get_db()
    try:
        # 主查询: candidates 关联 contact_records 和 resume_operations
        query = """
            SELECT
                c.boss_id,
                c.candidate_name,
                c.school,
                c.degree,
                c.years,
                c.expected_role,
                c.status as candidate_status,
                c.resume_path as candidate_resume_path,
                cr.action as contact_status,
                cr.action_date as contacted_at,
                cr.created_at,
                ro.candidate_name as resume_name,
                ro.resume_downloaded,
                ro.action as resume_action,
                ro.detail,
                ro.created_at as resume_at
            FROM candidates c
            LEFT JOIN (
                SELECT boss_id, action, action_date, created_at,
                       ROW_NUMBER() OVER (PARTITION BY boss_id ORDER BY created_at DESC) as rn
                FROM contact_records
            ) cr ON (cr.boss_id = c.boss_id AND cr.rn = 1)
            LEFT JOIN (
                SELECT candidate_name, resume_downloaded, action, detail, created_at, id,
                       ROW_NUMBER() OVER (PARTITION BY candidate_name ORDER BY id DESC) as rn
                FROM resume_operations
            ) ro ON (ro.candidate_name = c.boss_id AND ro.rn = 1)
            ORDER BY c.updated_at DESC
            LIMIT %s
        """
        rows = conn.execute(query, (limit,)).fetchall()

        candidates = []
        for row in rows:
            row_dict = dict(row)
            detail = {}
            try:
                if row_dict.get("detail"):
                    detail = json.loads(row_dict["detail"])
            except (json.JSONDecodeError, TypeError):
                pass

            # 从 detail JSON 中提取简历文件名
            resume_filename = ""
            dl_result = detail.get("download_result", {})
            if isinstance(dl_result, dict):
                resume_filename = Path(dl_result.get("path", "")).name or ""

            # resume_path 优先从 candidates 表取，其次从 detail 中取
            resume_path = row_dict.get("candidate_resume_path") or detail.get("path", "") or ""

            candidates.append({
                "boss_id": row_dict["boss_id"] or "",
                "name": row_dict["candidate_name"] or row_dict["boss_id"] or "",
                "school": row_dict.get("school") or "",
                "degree": row_dict.get("degree") or "",
                "years": row_dict.get("years") or 0,
                "position": row_dict.get("expected_role") or "",
                "status": row_dict.get("candidate_status") or row_dict.get("contact_status") or "unknown",
                "resume_downloaded": bool(row_dict["resume_downloaded"]),
                "resume_path": resume_path,
                "resume_filename": resume_filename,
                "resume_action": row_dict["resume_action"] or "",
                "contacted_at": row_dict["contacted_at"],
                "created_at": row_dict["created_at"],
            })

        # 回退: 如果 candidates 表为空，从 contact_records + resume_operations 获取
        if not candidates:
            rows = conn.execute(
                "SELECT candidate_name as boss_id, candidate_name, action, resume_downloaded, detail, created_at "
                "FROM resume_operations ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
            for row in rows:
                row_dict = dict(row)
                detail = {}
                try:
                    if row_dict.get("detail"):
                        detail = json.loads(row_dict["detail"])
                except (json.JSONDecodeError, TypeError):
                    pass
                dl_result = detail.get("download_result", {})
                resume_filename = ""
                if isinstance(dl_result, dict):
                    resume_filename = Path(dl_result.get("path", "")).name or ""

                candidates.append({
                    "boss_id": row_dict["boss_id"] or row_dict["candidate_name"] or "",
                    "name": row_dict["candidate_name"] or "",
                    "school": "",
                    "degree": "",
                    "years": 0,
                    "position": "",
                    "status": row_dict["action"] or "unknown",
                    "resume_downloaded": bool(row_dict["resume_downloaded"]),
                    "resume_path": detail.get("path", resume_filename) if detail else "",
                    "resume_filename": resume_filename,
                    "resume_action": row_dict["action"] or "",
                    "contacted_at": row_dict["created_at"],
                    "created_at": row_dict["created_at"],
                })

        return {"candidates": candidates, "source": "candidates" if rows else "resume_operations", "total": len(candidates)}
    finally:
        conn.close()

@app.get("/api/stats")
async def get_stats(current_user: dict = Depends(verify_token)):
    """获取统计数据 — 优先 contact_records，回退 processed_candidates"""
    conn = get_db()
    try:
        # 优先查 contact_records（F5 正式运行后会有数据）
        cr_count = conn.execute("SELECT COUNT(*) FROM contact_records").fetchone()[0]
        if cr_count > 0:
            total = conn.execute(
                "SELECT COUNT(DISTINCT boss_id) FROM contact_records"
            ).fetchone()[0]
            by_status = conn.execute(
                "SELECT action as status, COUNT(*) as count FROM contact_records GROUP BY action"
            ).fetchall()
            today_processed = conn.execute(
                "SELECT COUNT(DISTINCT boss_id) FROM contact_records WHERE action = 'contacted' AND action_date = CURRENT_DATE::text"
            ).fetchone()[0]
            return {
                "total_candidates": total,
                "by_status": {row['status']: row['count'] for row in by_status},
                "today_processed": today_processed,
            }

        # 回退: processed_candidates
        total = conn.execute("SELECT COUNT(*) FROM processed_candidates").fetchone()[0]
        today_processed = conn.execute(
            "SELECT COUNT(*) FROM processed_candidates WHERE created_at::date = CURRENT_DATE"
        ).fetchone()[0]
        # 简历下载统计
        resume_count = conn.execute(
            "SELECT COUNT(*) FROM resume_operations WHERE resume_downloaded = true"
        ).fetchone()[0]
        return {
            "total_candidates": total,
            "by_status": {"contacted": total, "resume_downloaded": resume_count},
            "today_processed": today_processed,
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
    user = verify_credentials(req.username, req.password)
    if user:
        token = create_access_token({
            "sub": user["username"],
            "user_id": user["id"],
            "role": user["role"],
        })
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
    dry_run: bool = False
    custom_template: Optional[str] = None


# ============================================================
# 浏览器连接API端点
# ============================================================

class BrowserConnectRequest(BaseModel):
    headless: bool = False


@app.post("/api/browser/connect")
async def connect_browser(req: BrowserConnectRequest = None):
    """连接到 Chrome DevTools Protocol (CDP)

    连接到已运行的 Chrome 浏览器实例（CDP 端口 9222）。
    Chrome 可通过以下方式启动：
    macOS: /Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222
    Linux: google-chrome --remote-debugging-port=9222
    Docker: 容器内已自动启动 Chrome + CDP
    """
    return await automation.connect()


@app.get("/api/browser/status")
async def get_browser_status():
    """获取浏览器连接状态（含真实session探测）"""
    return await automation.get_status()


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
    return await automation.screenshot()


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


@app.post("/api/browser/type-send")
async def browser_type_send(req: ExecuteScriptRequest):
    """输入文本并按Enter发送 — 用于测试AI回复"""
    from app.chat_nav import type_and_send
    return await type_and_send(req.script)


@app.post("/api/browser/open-boss")
async def open_boss_browser():
    """打开BOSS直聘 - 复用已有Chrome或启动新实例，然后导航到zhipin.com

    智能流程：
    1. 如果 automation 已连接且有活跃 session → 直接导航
    2. 如果 CDP 9222 端口有 Chrome 但未连接 → connect() 复用
    3. 否则 → connect() 自动启动新 Chrome（带 --no-sandbox）
    4. 导航到 zhipin.com + 注入 cookie
    """
    import socket

    # Step 1: 已连接且session存活 → 直接导航
    if automation._connected:
        try:
            await asyncio.wait_for(automation.page.evaluate("1"), timeout=3)
            api_logger.info("open-boss: 复用现有活跃CDP session")
        except Exception:
            # session 已死，重连
            await automation.disconnect()
            connect_result = await automation.connect()
            if connect_result.get("status") not in ("connected", "already_connected"):
                return {"status": "error", "message": f"CDP重连失败: {connect_result}"}
    else:
        # Step 2/3: connect() 内部自动检测并启动 Chrome
        connect_result = await automation.connect()
        if connect_result.get("status") not in ("connected", "already_connected"):
            return {"status": "error", "message": f"Chrome启动/连接失败: {connect_result}"}

    # Step 4: 导航到 zhipin.com
    nav_result = await automation.navigate("https://www.zhipin.com/")
    await asyncio.sleep(3)

    # Step 5: 注入已保存的 cookie
    cookie_result = None
    try:
        cookie_result = await automation.import_cookies()
        api_logger.info(f"Cookie注入结果: {cookie_result}")
        if cookie_result and cookie_result.get("imported", 0) > 0:
            await asyncio.sleep(1)
            await automation.execute_js("location.reload()")
            await asyncio.sleep(2)
    except Exception as e:
        api_logger.warning(f"Cookie注入失败（非致命）: {e}")

    return {
        "status": "ok",
        "message": "Chrome已启动并打开BOSS直聘，可在VNC桌面中查看",
        "connect_result": connect_result if not automation._connected else {"status": "already_connected"},
        "nav_result": nav_result,
        "cookie_injection": cookie_result,
    }


@app.get("/api/browser/check-login")
async def check_browser_login():
    """检测 BOSS直聘登录状态"""
    return await automation.check_login()


@app.post("/api/browser/export-cookies")
async def export_cookies():
    """导出当前浏览器的所有 cookie 到 /app/data/cookies.json

    用于持久化登录态：在浏览器已登录时调用，
    将 cookie 导出为 JSON 文件保存到 Docker volume 中。
    """
    return await automation.export_cookies()


@app.post("/api/browser/import-cookies")
async def import_cookies():
    """从 /app/data/cookies.json 恢复 cookie 到浏览器

    用于恢复登录态：浏览器启动后调用，
    将之前导出的 cookie 写入浏览器以恢复登录状态。
    """
    return await automation.import_cookies()


# ============================================================
# F7 批量AI回复任务状态
# ============================================================
_reply_task_status: Dict[str, Any] = {
    "status": "idle", "replied": 0, "failed": 0, "skipped": 0,
    "total": 0, "message": "", "results": [],
}


@app.post("/api/workflow/reply-messages")
async def reply_messages(req: WorkflowRequest, current_user: dict = Depends(verify_token)):
    """批量回复未读消息 — 独立线程执行

    在独立线程中运行 batch_reply_workflow，避免阻塞 FastAPI 事件循环。
    通过 GET /api/workflow/reply-status 查询进度。
    """
    global _reply_task_status, _active_task_type, _lock_acquired_at

    _force_unlock_if_stale()
    if not _browser_task_lock.acquire(blocking=False):
        return {"status": "error", "message": f"浏览器正被 {_active_task_type} 任务占用，请稍后重试"}

    if _reply_task_status.get("status") == "running":
        try:
            _browser_task_lock.release()
        except RuntimeError:
            pass
        return {"status": "error", "message": "已有回复任务正在运行"}

    _active_task_type = "F7-reply"
    _lock_acquired_at = __import__('time').time()
    _reply_task_status = {
        "status": "running",
        "replied": 0,
        "failed": 0,
        "skipped": 0,
        "total": req.limit,
        "message": f"正在处理最多 {req.limit} 个联系人...",
        "results": [],
        "start_time": datetime.now().isoformat(),
    }
    api_logger.info(f"[F7] 启动批量回复任务，上限 {req.limit} 人")

    import threading as _th
    _th.Thread(
        target=_run_reply_in_thread,
        args=(req.limit, req.dry_run, req.custom_template),
        daemon=True,
    ).start()

    return {
        "status": "started",
        "message": f"批量回复任务已启动，上限 {req.limit} 人",
    }


def _run_reply_in_thread(max_count: int, dry_run: bool = False, custom_template: Optional[str] = None):
    """在独立线程中运行批量回复工作流"""
    global _reply_task_status, _active_task_type
    import asyncio as _asyncio

    async def _thread_main():
        from app.automation import cancel_event
        cancel_event.clear()
        try:
            from app.chat_workflow import _batch_reply_impl
        except ImportError as e:
            _reply_task_status["status"] = "error"
            _reply_task_status["message"] = f"回复工作流模块未就绪: {e}"
            api_logger.error(f"[F7] 失败: 模块导入错误: {e}")
            return

        try:
            # 线程安全地重置浏览器状态，在新事件循环中重新连接
            automation.reset_for_thread()
            conn = await automation.connect()
            if conn.get("status") not in ("connected", "already_connected"):
                _reply_task_status["status"] = "error"
                _reply_task_status["message"] = "浏览器连接失败"
                return

            await automation.import_cookies()

            result = await _batch_reply_impl(
                max_count=max_count,
                template=custom_template,
                dry_run=dry_run,
            )

            _reply_task_status["status"] = result.get("status", "completed")
            _reply_task_status["replied"] = result.get("replied", 0)
            _reply_task_status["failed"] = result.get("failed", 0)
            _reply_task_status["skipped"] = result.get("skipped", 0)
            _reply_task_status["total"] = result.get("total_scanned", 0)
            _reply_task_status["message"] = result.get("message", "")
            _reply_task_status["results"] = result.get("results", [])
            _reply_task_status["end_time"] = datetime.now().isoformat()
            api_logger.info(f"[F7] 完成: {_reply_task_status['message']}")

        except Exception as e:
            import traceback
            _reply_task_status["status"] = "error"
            _reply_task_status["message"] = str(e)
            api_logger.error(f"[F7] 失败: {e}\n{traceback.format_exc()}")

    try:
        _asyncio.run(_thread_main())
    except Exception as e:
        _reply_task_status["status"] = "error"
        _reply_task_status["message"] = str(e)
        api_logger.error(f"[F7] 线程失败: {e}")
    finally:
        global _active_task_type, _lock_acquired_at
        _active_task_type = None
        _lock_acquired_at = None
        try:
            _browser_task_lock.release()
        except RuntimeError:
            pass


@app.get("/api/workflow/reply-status")
async def get_reply_status():
    """获取批量回复任务状态"""
    return _reply_task_status


# ============================================================
# 简历管理端点
# ============================================================

class BatchResumeRequest(BaseModel):
    """批量获取简历请求"""
    limit: int = 10
    candidate_ids: Optional[List[str]] = None  # 指定候选人ID列表
    dry_run: bool = False  # 干跑模式（只扫描不操作）


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
    current_user: dict = Depends(verify_token)
):
    """
    批量获取简历

    在独立线程中运行，避免阻塞 FastAPI 事件循环。
    遍历聊天联系人，检测简历按钮，下载或请求简历。
    """
    global resume_task_status, _active_task_type, _lock_acquired_at

    _force_unlock_if_stale()
    if not _browser_task_lock.acquire(blocking=False):
        return {"status": "error", "message": f"浏览器正被 {_active_task_type} 任务占用，请稍后重试"}

    if resume_task_status["status"] == "running":
        _browser_task_lock.release()
        return {"status": "error", "message": "已有简历任务正在运行"}

    _active_task_type = "F6-resume"
    _lock_acquired_at = __import__('time').time()
    resume_task_status = {
        "status": "running",
        "processed": 0,
        "total": req.limit,
        "message": f"正在处理 {req.limit} 个候选人...",
        "start_time": datetime.now().isoformat()
    }
    api_logger.info(f"启动批量简历下载任务，上限 {req.limit} 人")

    # 在独立线程中运行（nodriver 对象绑定到事件循环）
    import threading as _th
    _th.Thread(
        target=_run_resume_in_thread,
        args=(req.limit, req.dry_run if hasattr(req, 'dry_run') else False),
        daemon=True
    ).start()

    return {
        "status": "started",
        "message": f"批量简历下载任务已启动，上限 {req.limit} 人",
    }


def _run_resume_in_thread(max_count: int, dry_run: bool = False):
    """在独立线程中运行简历收集"""
    global resume_task_status, _active_task_type
    import asyncio as _asyncio

    async def _thread_main():
        from app.automation import cancel_event
        cancel_event.clear()
        try:
            from app.resume_collector import collect_resumes
        except ImportError as e:
            resume_task_status["status"] = "error"
            resume_task_status["message"] = f"简历收集模块未就绪: {e}"
            api_logger.error(f"F6 失败: 模块导入错误: {e}")
            return

        try:
            # 线程安全地重置浏览器状态
            automation.reset_for_thread()
            conn = await automation.connect()
            if conn.get("status") not in ("connected", "already_connected"):
                resume_task_status["status"] = "error"
                resume_task_status["message"] = "浏览器连接失败"
                return

            # F6: 检查登录状态（与F7保持一致）
            login_status = await automation.check_login()
            if not login_status.get("logged_in"):
                resume_task_status["status"] = "error"
                resume_task_status["message"] = "BOSS直聘未登录，请先在VNC中扫码登录"
                return

            result = await collect_resumes(max_count=max_count, dry_run=dry_run)

            resume_task_status["status"] = result.get("status", "completed")
            resume_task_status["processed"] = result.get("downloaded", 0)
            resume_task_status["total"] = max_count
            resume_task_status["message"] = (
                f"下载:{result.get('downloaded',0)} "
                f"跳过:{result.get('skipped',0)} "
                f"失败:{result.get('failed',0)} "
                f"扫描:{result.get('total_scanned',0)}"
            )
            resume_task_status["result"] = result
            resume_task_status["end_time"] = datetime.now().isoformat()
            api_logger.info(f"F6 完成: {resume_task_status['message']}")

        except Exception as e:
            resume_task_status["status"] = "error"
            resume_task_status["message"] = str(e)
            api_logger.error(f"F6 失败: {e}")

    try:
        _asyncio.run(_thread_main())
    except Exception as e:
        resume_task_status["status"] = "error"
        resume_task_status["message"] = str(e)
        api_logger.error(f"F6 线程失败: {e}")
    finally:
        global _active_task_type, _lock_acquired_at
        _active_task_type = None
        _lock_acquired_at = None
        try:
            _browser_task_lock.release()
        except RuntimeError:
            pass


@app.get("/api/resume/status")
async def get_resume_task_status(current_user: dict = Depends(verify_token)):
    """获取批量简历任务状态"""
    return resume_task_status


# ============================================================
# F8 已获取简历下载 (resume_downloader.py)
# ============================================================
_received_resume_task_status: Dict[str, Any] = {
    "status": "idle", "downloaded": 0, "skipped": 0, "failed": 0,
    "total": 0, "message": "", "details": [],
}


@app.post("/api/resume/received")
async def download_received_resumes(
    req: BatchResumeRequest,
    current_user: dict = Depends(verify_token),
):
    """下载已获取的简历 — 针对已同意分享简历的联系人

    与 /api/resume/batch（申请简历）不同，本端点处理的是对方已上传附件简历的情况。
    流程：联系人 → 附件简历 → PDF预览 → 下载 → 关闭预览 → 下一个
    """
    global _received_resume_task_status, _active_task_type, _lock_acquired_at

    _force_unlock_if_stale()
    if not _browser_task_lock.acquire(blocking=False):
        return {"status": "error", "message": f"浏览器正被 {_active_task_type} 任务占用，请稍后重试"}

    if _received_resume_task_status.get("status") == "running":
        try:
            _browser_task_lock.release()
        except RuntimeError:
            pass
        return {"status": "error", "message": "已有下载任务正在运行"}

    _active_task_type = "F8-download-received"
    _lock_acquired_at = __import__('time').time()
    _received_resume_task_status = {
        "status": "running",
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
        "total": req.limit,
        "message": f"正在下载最多 {req.limit} 份已获取简历...",
        "details": [],
        "start_time": datetime.now().isoformat(),
    }
    api_logger.info(f"[F8] 启动已获取简历下载任务，上限 {req.limit} 人")

    import threading as _th
    _th.Thread(
        target=_run_received_resume_in_thread,
        args=(req.limit, req.dry_run if hasattr(req, 'dry_run') else False),
        daemon=True,
    ).start()

    return {
        "status": "started",
        "message": f"已获取简历下载任务已启动，上限 {req.limit} 人",
    }


def _run_received_resume_in_thread(max_count: int, dry_run: bool = False):
    """在独立线程中运行已获取简历下载"""
    global _received_resume_task_status, _active_task_type
    import asyncio as _asyncio

    async def _thread_main():
        from app.automation import cancel_event
        cancel_event.clear()
        try:
            from app.resume_downloader import collect_received_resumes
        except ImportError as e:
            _received_resume_task_status["status"] = "error"
            _received_resume_task_status["message"] = f"简历下载模块未就绪: {e}"
            api_logger.error(f"[F8] 失败: 模块导入错误: {e}")
            return

        try:
            automation.reset_for_thread()
            conn = await automation.connect()
            if conn.get("status") not in ("connected", "already_connected"):
                _received_resume_task_status["status"] = "error"
                _received_resume_task_status["message"] = "浏览器连接失败"
                return

            login_status = await automation.check_login()
            if not login_status.get("logged_in"):
                _received_resume_task_status["status"] = "error"
                _received_resume_task_status["message"] = "BOSS直聘未登录，请先在VNC中扫码登录"
                return

            result = await collect_received_resumes(max_count=max_count, dry_run=dry_run)

            _received_resume_task_status["status"] = result.get("status", "completed")
            _received_resume_task_status["downloaded"] = result.get("downloaded", 0)
            _received_resume_task_status["skipped"] = result.get("skipped", 0)
            _received_resume_task_status["failed"] = result.get("failed", 0)
            _received_resume_task_status["total"] = result.get("total_scanned", 0)
            _received_resume_task_status["message"] = (
                f"下载:{result.get('downloaded',0)} "
                f"跳过:{result.get('skipped',0)} "
                f"失败:{result.get('failed',0)} "
                f"扫描:{result.get('total_scanned',0)}"
            )
            _received_resume_task_status["details"] = result.get("details", [])
            _received_resume_task_status["end_time"] = datetime.now().isoformat()
            api_logger.info(f"[F8] 完成: {_received_resume_task_status['message']}")

        except Exception as e:
            import traceback
            _received_resume_task_status["status"] = "error"
            _received_resume_task_status["message"] = str(e)
            api_logger.error(f"[F8] 失败: {e}\n{traceback.format_exc()}")

    try:
        _asyncio.run(_thread_main())
    except Exception as e:
        _received_resume_task_status["status"] = "error"
        _received_resume_task_status["message"] = str(e)
        api_logger.error(f"[F8] 线程失败: {e}")
    finally:
        global _active_task_type, _lock_acquired_at
        _active_task_type = None
        _lock_acquired_at = None
        try:
            _browser_task_lock.release()
        except RuntimeError:
            pass


@app.get("/api/resume/received-status")
async def get_received_resume_status(current_user: dict = Depends(verify_token)):
    """获取已获取简历下载任务状态"""
    return _received_resume_task_status


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
                   WHERE action LIKE %s
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (f"%{status}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM resume_operations
                   ORDER BY created_at DESC
                   LIMIT %s""",
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
            "SELECT * FROM resume_operations WHERE id = %s",
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
            if row["resume_downloaded"]:
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
    daily_cap: Optional[int] = 80        # 每日封顶上限
    batch_limit: Optional[int] = 20      # 单次处理数量
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
            req.school_whitelist = DOMESTIC_ELITE_SCHOOLS + INTERNATIONAL_ELITE_SCHOOLS

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

        # 在独立线程中运行，避免阻塞 FastAPI 事件循环
        # nodriver 对象绑定到事件循环，必须在独立线程中创建新的事件循环
        import threading
        thread = threading.Thread(
            target=_run_filter_contact_in_thread,
            args=(task_id, req.daily_cap, req.batch_limit, criteria, req.dry_run),
            daemon=True
        )

        # 获取浏览器任务锁（非阻塞，先检测超时）
        global _lock_acquired_at
        _force_unlock_if_stale()
        if not _browser_task_lock.acquire(blocking=False):
            del _filter_tasks[task_id]
            raise HTTPException(status_code=409, detail=f"浏览器正被 {_active_task_type} 任务占用，请稍后重试")
        _active_task_type = "F5-filter"
        _lock_acquired_at = __import__('time').time()

        thread.start()

        return FilterContactResponse(
            task_id=task_id,
            status="queued",
            message=f"筛选打招呼任务已加入队列，任务ID: {task_id}"
        )

    except Exception as e:
        api_logger.error(f"启动筛选打招呼任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _run_filter_contact_in_thread(
    task_id: str,
    daily_cap: int,
    batch_limit: int,
    criteria: "FilterCriteria",
    dry_run: bool
):
    """在独立线程中运行筛选打招呼任务，避免阻塞 FastAPI 事件循环。

    nodriver 的 browser/page 对象绑定到创建时的事件循环。
    在线程中通过 asyncio.run() 创建独立事件循环，并在其中重新连接浏览器。
    """
    import asyncio as _asyncio

    async def _thread_main():
        """线程主协程：连接浏览器 → 执行工作流"""
        from app.automation import cancel_event
        cancel_event.clear()
        # 在线程的事件循环中重新连接浏览器（线程安全）
        _filter_tasks[task_id]["progress"] = 5
        automation.reset_for_thread()
        conn_result = await automation.connect()
        if conn_result.get("status") not in ("connected", "already_connected"):
            _filter_tasks[task_id]["status"] = "error"
            _filter_tasks[task_id]["error"] = f"浏览器连接失败: {conn_result.get('message', '未知')}"
            _filter_tasks[task_id]["completed_at"] = datetime.now().isoformat()
            api_logger.error(f"任务 {task_id} 失败: 浏览器连接失败")
            return

        # === F5 线程隔离修复：先导入 cookie，再检查登录 ===
        # 问题：新创建的浏览器实例没有 cookie，check_login 会失败
        # 解决：connect → import_cookies → navigate → wait → check_login → retry

        # Step 1: 立即导入已保存的 cookie
        await automation.import_cookies()
        api_logger.info(f"任务 {task_id} 已导入 cookie（连接后立即）")

        # Step 2: 显式导航到推荐页并等待 cookie 生效
        await automation.navigate("https://www.zhipin.com/web/chat/recommend")
        import asyncio as _asyncio_thread
        await _asyncio_thread.sleep(5)  # 等待页面加载 + cookie 应用

        # Step 3: 检查登录状态（带重试）
        login_checked = False
        for attempt in range(3):  # 最多 3 次尝试
            login_status = await automation.check_login()
            if login_status.get("logged_in"):
                login_checked = True
                api_logger.info(f"任务 {task_id} 登录检测成功 (尝试 {attempt + 1}/3)")
                break
            if attempt < 2:  # 不是最后一次尝试
                api_logger.warning(f"任务 {task_id} 登录检测失败，5秒后重试 ({attempt + 1}/3)")
                await _asyncio_thread.sleep(5)

        if not login_checked:
            _filter_tasks[task_id]["status"] = "error"
            _filter_tasks[task_id]["error"] = "BOSS直聘未登录，请先在VNC中扫码登录"
            _filter_tasks[task_id]["completed_at"] = datetime.now().isoformat()
            api_logger.error(f"任务 {task_id} 失败: 未登录（3次重试后）")
            return

        _filter_tasks[task_id]["progress"] = 20

        # 导入并执行workflow core
        try:
            from app.workflows import _auto_contact_impl
        except ImportError as e:
            _filter_tasks[task_id]["status"] = "error"
            _filter_tasks[task_id]["error"] = f"工作流模块未就绪: {e}"
            _filter_tasks[task_id]["completed_at"] = datetime.now().isoformat()
            api_logger.error(f"任务 {task_id} 失败: 工作流模块未就绪")
            return

        api_logger.info(f"任务 {task_id} 开始执行筛选打招呼 (独立线程, 已连接浏览器)")

        result = await _auto_contact_impl(
            daily_cap=daily_cap,
            batch_limit=batch_limit,
            school_whitelist=criteria.school_whitelist,
            min_degree=criteria.min_degree,
            min_years=criteria.min_years,
            dry_run=dry_run,
            criteria=criteria,
        )

        _filter_tasks[task_id]["status"] = result.get("status", "unknown")
        _filter_tasks[task_id]["progress"] = 100
        _filter_tasks[task_id]["result"] = result
        _filter_tasks[task_id]["completed_at"] = datetime.now().isoformat()
        api_logger.info(f"任务 {task_id} 完成: {result.get('status')}")

    try:
        _filter_tasks[task_id]["status"] = "running"
        _filter_tasks[task_id]["progress"] = 5
        _asyncio.run(_thread_main())
    except Exception as e:
        api_logger.error(f"任务 {task_id} 执行失败: {e}")
        _filter_tasks[task_id]["status"] = "failed"
        _filter_tasks[task_id]["error"] = str(e)
        _filter_tasks[task_id]["completed_at"] = datetime.now().isoformat()
    finally:
        global _active_task_type, _lock_acquired_at
        _active_task_type = None
        _lock_acquired_at = None
        try:
            _browser_task_lock.release()
        except RuntimeError:
            pass


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


@app.get("/api/filter/config/defaults")
async def get_filter_config_defaults():
    """
    获取筛选配置的默认值（不需要认证）

    返回:
        学校白名单、学历选项、工作年限选项等默认值
    """
    return {
        "school_whitelist": {
            "domestic": DOMESTIC_ELITE_SCHOOLS,
            "international": INTERNATIONAL_ELITE_SCHOOLS,
        },
        "degree_options": ["博士", "硕士", "本科", "大专"],
        "min_degree_default": "本科",
        "years_options": [1, 2, 3, 5, 10],
        "min_years_default": 3,
        "daily_cap_default": 80,
        "daily_cap_range": [10, 20, 50, 80, 100, 150],
    }


@app.get("/api/filter/config")
async def get_filter_config(current_user: dict = Depends(verify_token)):
    """
    获取筛选配置（合并数据库已保存配置 + 默认值）【需要认证】

    返回:
        学校白名单、学历选项、工作年限选项、以及当前生效的筛选参数
    """
    # 默认值
    result = {
        "school_whitelist": {
            "domestic": DOMESTIC_ELITE_SCHOOLS,
            "international": INTERNATIONAL_ELITE_SCHOOLS,
        },
        "degree_options": ["博士", "硕士", "本科", "大专"],
        "min_degree_default": "本科",
        "years_options": [1, 2, 3, 5, 10],
        "min_years_default": 3,
        "daily_cap_default": 80,
        "daily_cap_range": [10, 20, 50, 80, 100, 150],
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

    # 从 runtime_state 读取已保存的配置，覆盖默认值
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT value FROM runtime_state WHERE key = %s", ("filter_config",)
        ).fetchone()
        conn.close()
        if row:
            saved = json.loads(row[0])
            # 用已保存的值覆盖对应默认值
            if "min_degree" in saved:
                result["min_degree_default"] = saved["min_degree"]
            if "min_years" in saved:
                result["min_years_default"] = saved["min_years"]
            if "daily_cap" in saved:
                result["daily_cap_default"] = saved["daily_cap"]
            # 如果保存了自定义学校白名单，也返回
            if "school_whitelist" in saved and isinstance(saved["school_whitelist"], list):
                result["saved_school_whitelist"] = saved["school_whitelist"]
            # 保留完整的 saved config 供前端同步
            result["saved"] = saved
    except Exception as e:
        api_logger.warning(f"读取已保存筛选配置失败(使用默认值): {e}")

    return result


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
            "INSERT INTO runtime_state (key, value, updated_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
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


@app.post("/api/chat/batch")
async def batch_reply_messages(
    req: BatchReplyRequest,
    current_user: dict = Depends(verify_token)
):
    """批量AI回复消息 — 委托到浏览器自动化工作流

    此端点已统一到 /api/workflow/reply-messages 的线程执行机制。
    保留此路由以兼容前端调用，返回任务启动状态。
    """
    # 直接委托到线程执行的 F7 工作流
    workflow_req = WorkflowRequest(
        limit=req.limit,
        dry_run=req.dry_run,
        custom_template=req.custom_template,
    )
    return await reply_messages(workflow_req, current_user=current_user)


@app.get("/api/chat/history")
async def get_chat_history(
    candidate_name: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(verify_token)
):
    """获取对话历史 — 返回前端兼容的 {role, content} 格式"""
    from app.chat_service import chat_service

    try:
        db_rows = chat_service.get_conversation_history(candidate_name=candidate_name, limit=limit)
        # 转换为前端期望的 {role, content} 格式
        history = []
        for row in db_rows:
            if row.get("ai_message"):
                history.append({"role": "assistant", "content": row["ai_message"], "time": row.get("created_at")})
            if row.get("candidate_message"):
                history.append({"role": "user", "content": row["candidate_message"], "time": row.get("created_at")})
        # 按时间排序
        history.sort(key=lambda h: h.get("time", ""))
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


# ============================================================
# 3101 数据总控平台 — 扩展端点
# ============================================================

@app.get("/api/tasks/status")
async def get_all_tasks_status(current_user: dict = Depends(verify_token)):
    """统一任务状态 — 聚合 F5/F6/F7 + 浏览器状态"""
    try:
        # F5: 取最新一条 filter task
        f5_latest = None
        if _filter_tasks:
            f5_latest = max(_filter_tasks.values(), key=lambda t: t.get("started_at", ""))
        f5_status = f5_latest if f5_latest else {"status": "idle"}

        return {
            "f5_filter": f5_status,
            "f6_resume": resume_task_status,
            "f8_received": _received_resume_task_status,
            "f7_reply": _reply_task_status,
            "browser": {"connected": automation._connected},
        }
    except Exception as e:
        api_logger.error(f"获取任务状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/daily-trend")
async def get_daily_trend(
    days: int = Query(default=7, ge=1, le=30),
    current_user: dict = Depends(verify_token)
):
    """7日趋势数据 — 按日聚合联系/简历/对话统计"""
    conn = get_db()
    try:
        trend = []
        for i in range(days - 1, -1, -1):
            from datetime import date as _date, timedelta as _td
            date_label = (_date.today() - _td(days=i)).strftime("%Y-%m-%d")

            contacted = conn.execute(
                "SELECT COUNT(*) FROM processed_candidates WHERE created_at::date = %s",
                (date_label,),
            ).fetchone()[0]

            resumes = conn.execute(
                "SELECT COUNT(*) FROM resume_operations WHERE resume_downloaded = true AND created_at::date = %s",
                (date_label,),
            ).fetchone()[0]

            replies = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE action = 'auto_reply' AND created_at::date = %s",
                (date_label,),
            ).fetchone()[0]

            reply_rate = round(replies / contacted * 100, 1) if contacted > 0 else 0.0

            trend.append({
                "date": date_label,
                "contacted": contacted,
                "resumes": resumes,
                "replies": replies,
                "reply_rate": reply_rate,
            })
        return {"trend": trend, "days": days}
    except Exception as e:
        api_logger.error(f"获取每日趋势失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/contact-records")
async def get_contact_records(
    action: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    current_user: dict = Depends(verify_token),
):
    """打招呼 / 联系记录"""
    conn = get_db()
    try:
        query = "SELECT * FROM contact_records"
        conditions: list = []
        params: list = []

        if action:
            conditions.append("action = %s")
            params.append(action)
        if date:
            conditions.append("action_date = %s")
            params.append(date)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        return {"records": [dict(row) for row in rows], "total": len(rows)}
    except Exception as e:
        api_logger.error(f"查询contact_records失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/conversations")
async def get_conversation_sessions(
    limit: int = Query(50, ge=1, le=200),
    current_user: dict = Depends(verify_token),
):
    """对话会话列表 — 按候选人分组（含OCR乱码清洗）"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT candidate_name,
                      COUNT(*) as rounds,
                      MIN(created_at) as first_at,
                      MAX(created_at) as last_at
               FROM conversations
               GROUP BY candidate_name
               ORDER BY last_at DESC
               LIMIT %s""",
            (limit * 3,),  # 多取3倍数据，清洗后再截断
        ).fetchall()

        # 清洗逻辑：过滤OCR乱码 + 截断过长名称
        OCR_GARBAGE_MARKERS = [
            "g:", "--no-sandbox", "Stability and security",
            "security will suffer", "every time you restart",
            "客服 热线", "验证码登录", "BOSS号我要找", "我要招聘",
            "and security will",
        ]

        def clean_name(name: str) -> str | None:
            if not name:
                return None
            if len(name) > 100:
                return None
            for marker in OCR_GARBAGE_MARKERS:
                if marker in name:
                    return None
            return name[:30] if len(name) > 30 else name

        cleaned = []
        for row in rows:
            clean = clean_name(row["candidate_name"])
            if clean:
                cleaned.append({**dict(row), "candidate_name": clean})
            if len(cleaned) >= limit:
                break

        return {"sessions": cleaned, "total": len(cleaned)}
    except Exception as e:
        api_logger.error(f"查询对话会话失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


class DailyCapsRequest(BaseModel):
    daily_contact_cap: int = Field(default=80, ge=1)
    daily_chat_rounds_cap: int = Field(default=5, ge=1)


@app.put("/api/config/daily-caps")
async def update_daily_caps(
    req: DailyCapsRequest,
    current_user: dict = Depends(verify_token),
):
    """动态修改每日上限 — 保存到 runtime_state"""
    conn = get_db()
    try:
        caps = {
            "daily_contact_cap": req.daily_contact_cap,
            "daily_chat_rounds_cap": req.daily_chat_rounds_cap,
        }
        conn.execute(
            "INSERT INTO runtime_state (key, value, updated_at) VALUES (%s, %s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
            ("daily_caps", json.dumps(caps), datetime.now().isoformat()),
        )
        conn.commit()
        api_logger.info(f"用户 {current_user['sub']} 更新每日上限: {caps}")
        return {"status": "success", "caps": caps}
    except Exception as e:
        api_logger.error(f"更新每日上限失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/config/daily-caps")
async def get_daily_caps(current_user: dict = Depends(verify_token)):
    """读取当前每日上限配置"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT value FROM runtime_state WHERE key = 'daily_caps'"
        ).fetchone()
        if row:
            caps = json.loads(row["value"])
        else:
            caps = {"daily_contact_cap": 80, "daily_chat_rounds_cap": 5}
        return {"status": "success", "caps": caps}
    except Exception as e:
        api_logger.error(f"获取每日上限失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================
# 3101 数据总控平台专用端点
# ============================================================

@app.get("/api/tasks/status")
async def get_all_tasks_status(current_user: dict = Depends(verify_token)):
    """统一任务状态 — 聚合 F5/F6/F7 + 浏览器 + 登录状态

    返回:
        f5_filter: 最新筛选任务状态
        f6_resume: 简历收集任务状态
        f7_reply: AI回复任务状态
        browser: 浏览器连接状态
        login: BOSS登录状态
    """
    # F5 筛选任务状态（获取最新一条）
    f5_status = {"status": "idle"}
    if _filter_tasks:
        latest_task = max(_filter_tasks.values(), key=lambda x: x.get("started_at", ""))
        f5_status = {
            "status": latest_task.get("status", "unknown"),
            "progress": latest_task.get("progress", 0),
            "task_id": latest_task.get("task_id"),
            "result": latest_task.get("result"),
            "error": latest_task.get("error"),
        }

    # F6 简历收集状态
    f6_status = {
        "status": resume_task_status.get("status", "idle"),
        "processed": resume_task_status.get("processed", 0),
        "total": resume_task_status.get("total", 0),
        "message": resume_task_status.get("message", ""),
    }

    # F7 AI回复状态
    f7_status = {
        "status": _reply_task_status.get("status", "idle"),
        "replied": _reply_task_status.get("replied", 0),
        "failed": _reply_task_status.get("failed", 0),
        "skipped": _reply_task_status.get("skipped", 0),
        "total": _reply_task_status.get("total", 0),
        "message": _reply_task_status.get("message", ""),
    }

    # 浏览器连接状态
    browser_status = {
        "connected": automation._connected,
    }

    # 登录状态（仅当浏览器已连接时检测）
    login_status = {"logged_in": False}
    if automation._connected:
        try:
            login_result = await automation.check_login()
            login_status["logged_in"] = login_result.get("logged_in", False)
        except Exception:
            login_status["logged_in"] = False

    return {
        "f5_filter": f5_status,
        "f6_resume": f6_status,
        "f8_received": _received_resume_task_status,
        "f7_reply": f7_status,
        "browser": browser_status,
        "login": login_status,
    }


@app.get("/api/stats/daily-trend")
async def get_daily_trend(
    days: int = Query(default=7, ge=1, le=30),
    current_user: dict = Depends(verify_token)
):
    """7日趋势数据 — 按日聚合联系/简历/对话统计

    参数:
        days: 查询天数（默认7天，最大30天）

    返回:
        List of {date, contacted, resumes, replies, reply_rate}
    """
    conn = get_db()
    try:
        trend = []
        from datetime import date, timedelta

        for i in range(days):
            d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d")

            # 联系人数（优先 contact_records，回退 processed_candidates）
            contacted = 0
            cr_count = conn.execute("SELECT COUNT(*) FROM contact_records").fetchone()[0]
            if cr_count > 0:
                contacted = conn.execute(
                    "SELECT COUNT(DISTINCT boss_id) FROM contact_records WHERE action_date = %s",
                    (d,)
                ).fetchone()[0]
            else:
                contacted = conn.execute(
                    "SELECT COUNT(*) FROM processed_candidates WHERE created_at::date = %s",
                    (d,)
                ).fetchone()[0]

            # 简历下载数
            resumes = conn.execute(
                "SELECT COUNT(*) FROM resume_operations WHERE resume_downloaded = true AND created_at::date = %s",
                (d,)
            ).fetchone()[0]

            # AI回复数（conversations 中 ai_message 非空）
            replies = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE created_at::date = %s AND ai_message IS NOT NULL AND ai_message != ''",
                (d,)
            ).fetchone()[0]

            # 回复率 = 回复数 / 联系人数
            reply_rate = round(replies / contacted * 100, 1) if contacted > 0 else 0

            trend.append({
                "date": d,
                "contacted": contacted,
                "resumes": resumes,
                "replies": replies,
                "reply_rate": reply_rate,
            })

        return trend[::-1]  # 按日期正序返回

    except Exception as e:
        api_logger.error(f"查询趋势数据失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ============================================================
# 用户管理
# ============================================================
class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: str = "user"

class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    display_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


@app.get("/api/users")
async def list_users(current_user: dict = Depends(verify_token)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    with Database() as db:
        return {"users": db.list_users()}


@app.post("/api/users")
async def create_user(req: CreateUserRequest, current_user: dict = Depends(verify_token)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    from app.auth import hash_password
    with Database() as db:
        existing = db.get_user_by_username(req.username)
        if existing:
            raise HTTPException(status_code=400, detail=f"用户名 {req.username} 已存在")
        user = db.create_user(
            username=req.username,
            password_hash=hash_password(req.password),
            display_name=req.display_name,
            role=req.role,
        )
        return {"user": user}


@app.put("/api/users/{user_id}")
async def update_user(user_id: int, req: UpdateUserRequest, current_user: dict = Depends(verify_token)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    updates = {}
    if req.username is not None:
        updates["username"] = req.username
    if req.password is not None:
        from app.auth import hash_password
        updates["password_hash"] = hash_password(req.password)
    if req.display_name is not None:
        updates["display_name"] = req.display_name
    if req.role is not None:
        updates["role"] = req.role
    if req.is_active is not None:
        updates["is_active"] = req.is_active
    if not updates:
        raise HTTPException(status_code=400, detail="无更新内容")
    with Database() as db:
        ok = db.update_user(user_id, **updates)
        if not ok:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"message": "用户已更新"}


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: int, current_user: dict = Depends(verify_token)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    with Database() as db:
        ok = db.delete_user(user_id)
        if not ok:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {"message": "用户已删除"}


# ============================================================
# BOSS账号管理
# ============================================================
class CreateBossAccountRequest(BaseModel):
    user_id: int
    account_name: Optional[str] = None
    cdp_host: str = "127.0.0.1"
    cdp_port: int = 9222
    profile_dir: Optional[str] = None
    cookies_file: Optional[str] = None
    use_external_browser: bool = False
    is_default: bool = False
    enabled: bool = True

class UpdateBossAccountRequest(BaseModel):
    account_name: Optional[str] = None
    boss_identity: Optional[str] = None
    cdp_host: Optional[str] = None
    cdp_port: Optional[int] = None
    profile_dir: Optional[str] = None
    cookies_file: Optional[str] = None
    use_external_browser: Optional[bool] = None
    is_default: Optional[bool] = None
    enabled: Optional[bool] = None


@app.get("/api/boss-accounts")
async def list_boss_accounts(
    user_id: Optional[int] = None,
    current_user: dict = Depends(verify_token),
):
    with Database() as db:
        return {"accounts": db.list_boss_accounts(user_id=user_id)}


@app.post("/api/boss-accounts")
async def create_boss_account(req: CreateBossAccountRequest, current_user: dict = Depends(verify_token)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    with Database() as db:
        account = db.create_boss_account(**req.dict(exclude_none=True))
        return {"account": account}


@app.put("/api/boss-accounts/{account_id}")
async def update_boss_account(account_id: int, req: UpdateBossAccountRequest, current_user: dict = Depends(verify_token)):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="无更新内容")
    with Database() as db:
        ok = db.update_boss_account(account_id, **updates)
        if not ok:
            raise HTTPException(status_code=404, detail="账号不存在")
        return {"message": "账号已更新"}


@app.delete("/api/boss-accounts/{account_id}")
async def delete_boss_account(account_id: int, current_user: dict = Depends(verify_token)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可操作")
    with Database() as db:
        ok = db.delete_boss_account(account_id)
        if not ok:
            raise HTTPException(status_code=404, detail="账号不存在")
        return {"message": "账号已删除"}


# ============================================================
# 岗位话术文件管理 — 绑定 job_info/ 文件夹
# ============================================================

JOB_INFO_DIR = BASE_DIR / "job_info"


class JobInfoSaveRequest(BaseModel):
    """岗位话术保存请求"""
    filename: str   # 不含 .txt 后缀
    content: str


class JobInfoSelectRequest(BaseModel):
    """选择当前使用的岗位"""
    filename: str   # 不含 .txt 后缀


@app.get("/api/job-info/files")
async def list_job_info_files(current_user: dict = Depends(verify_token)):
    """列出 job_info/ 下所有 .txt 文件"""
    try:
        files = []
        if JOB_INFO_DIR.exists():
            for f in sorted(JOB_INFO_DIR.glob("*.txt")):
                name = f.stem  # 去掉 .txt
                if name == ".selected":
                    continue
                stat = f.stat()
                files.append({
                    "filename": name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        # 读取当前选中的岗位
        selected = None
        sel_file = JOB_INFO_DIR / ".selected"
        if sel_file.exists():
            selected = sel_file.read_text(encoding="utf-8").strip()
        return {"files": files, "selected": selected}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/job-info/files/{filename}")
async def get_job_info_file(filename: str, current_user: dict = Depends(verify_token)):
    """读取指定 .txt 文件内容"""
    filepath = JOB_INFO_DIR / f"{filename}.txt"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文件 {filename}.txt 不存在")
    try:
        return {
            "filename": filename,
            "content": filepath.read_text(encoding="utf-8"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/job-info/files")
async def save_job_info_file(
    req: JobInfoSaveRequest,
    current_user: dict = Depends(verify_token),
):
    """创建或更新 .txt 文件"""
    if not req.filename or not req.filename.strip():
        raise HTTPException(status_code=400, detail="文件名不能为空")
    safe_name = req.filename.strip().replace("/", "_").replace("\\", "_")
    filepath = JOB_INFO_DIR / f"{safe_name}.txt"
    try:
        JOB_INFO_DIR.mkdir(parents=True, exist_ok=True)
        filepath.write_text(req.content, encoding="utf-8")
        # 如果是第一个文件或没有选中项，自动设为当前岗位
        sel_file = JOB_INFO_DIR / ".selected"
        if not sel_file.exists():
            sel_file.write_text(safe_name, encoding="utf-8")
        return {"filename": safe_name, "message": f"已保存 {safe_name}.txt"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/job-info/files/{filename}")
async def delete_job_info_file(filename: str, current_user: dict = Depends(verify_token)):
    """删除指定 .txt 文件"""
    filepath = JOB_INFO_DIR / f"{filename}.txt"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文件 {filename}.txt 不存在")
    try:
        filepath.unlink()
        # 如果删除的是当前选中项，清除选择
        sel_file = JOB_INFO_DIR / ".selected"
        if sel_file.exists() and sel_file.read_text(encoding="utf-8").strip() == filename:
            sel_file.unlink()
        return {"message": f"已删除 {filename}.txt"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/job-info/select")
async def select_job_info(
    req: JobInfoSelectRequest,
    current_user: dict = Depends(verify_token),
):
    """设置当前使用的岗位话术文件"""
    filepath = JOB_INFO_DIR / f"{req.filename}.txt"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"文件 {req.filename}.txt 不存在")
    sel_file = JOB_INFO_DIR / ".selected"
    sel_file.write_text(req.filename.strip(), encoding="utf-8")
    return {"selected": req.filename.strip(), "message": f"已切换到 {req.filename}"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
