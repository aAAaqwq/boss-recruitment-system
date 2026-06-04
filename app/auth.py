"""
BOSS直聘系统 - JWT认证模块
提供JWT令牌创建和验证功能
"""
import os
from datetime import datetime, timedelta
from typing import Optional

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

API_USERNAME = os.getenv("API_USERNAME", "admin")
API_PASSWORD = os.getenv("API_PASSWORD")
if not API_PASSWORD or API_PASSWORD == "admin123":
    raise RuntimeError(
        "API_PASSWORD 未设置或使用了默认弱密码。"
        "请在 .env 文件或环境变量中设置一个强密码。"
    )

security = HTTPBearer(auto_error=False)


# ============================================================
# 令牌操作
# ============================================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """创建JWT访问令牌

    Args:
        data: 要编码的数据（通常包含sub等信息）
        expires_delta: 可选的过期时间增量

    Returns:
        JWT令牌字符串
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> dict:
    """验证JWT令牌

    Args:
        credentials: HTTP Bearer认证凭据

    Returns:
        解码后的令牌payload

    Raises:
        HTTPException: 令牌无效或过期时
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )
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


def verify_credentials(username: str, password: str) -> bool:
    """验证用户名和密码

    Args:
        username: 用户名
        password: 密码

    Returns:
        验证成功返回True，否则返回False
    """
    return username == API_USERNAME and password == API_PASSWORD
