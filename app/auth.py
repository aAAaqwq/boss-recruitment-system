"""
BOSS直聘系统 - JWT认证模块
bcrypt 密码哈希 + users 表认证
"""
import os
from datetime import datetime, timedelta
from typing import Optional, Dict

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# 配置
# ============================================================
SECRET_KEY = os.getenv("API_SECRET_KEY")
if not SECRET_KEY or SECRET_KEY == "your-secret-key-change-this-min-32-chars-long":
    raise RuntimeError(
        "API_SECRET_KEY 未设置或使用了默认占位值。"
        "请在 .env 文件或环境变量中设置一个强随机密钥 (≥32字符)。"
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

security = HTTPBearer(auto_error=False)


# ============================================================
# 密码哈希
# ============================================================
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def check_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))


# ============================================================
# 令牌操作
# ============================================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="令牌已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"无效的令牌: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ============================================================
# 用户认证（查询 users 表）
# ============================================================
def verify_credentials(username: str, password: str) -> Optional[Dict]:
    """验证用户名和密码，返回用户信息或 None"""
    from app.database import Database
    try:
        with Database() as db:
            user = db.get_user_by_username(username)
            if not user:
                return None
            if not user.get('is_active', True):
                return None
            if check_password(password, user['password_hash']):
                return {
                    "id": user['id'],
                    "username": user['username'],
                    "display_name": user.get('display_name'),
                    "role": user['role'],
                }
            return None
    except Exception:
        return None


def ensure_admin_user():
    """首次启动时自动创建管理员账号（从环境变量读取）"""
    from app.database import Database
    admin_username = os.getenv("API_USERNAME", "admin")
    admin_password = os.getenv("API_PASSWORD", "")

    with Database() as db:
        db.init_tables()
        existing = db.get_user_by_username(admin_username)
        if not existing:
            user = db.create_user(
                username=admin_username,
                password_hash=hash_password(admin_password),
                display_name="管理员",
                role="admin",
            )
            _create_user_dirs(user["id"])


def _create_user_dirs(user_id: int):
    """为新用户创建隔离的资源目录"""
    from pathlib import Path
    import os
    data_dir = Path(os.environ.get("DATA_DIR", "/app/data"))
    dirs = [
        data_dir / "resumes" / str(user_id),
        Path("/app/job_info") / str(user_id),
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


def register_user(username: str, password: str, display_name: str = None) -> Dict:
    """注册新用户"""
    from app.database import Database
    with Database() as db:
        db.init_tables()
        existing = db.get_user_by_username(username)
        if existing:
            return {"status": "error", "message": "用户名已存在"}
        user = db.create_user(
            username=username,
            password_hash=hash_password(password),
            display_name=display_name or username,
            role="user",
        )
        _create_user_dirs(user["id"])
        return {"status": "ok", "user": user}

