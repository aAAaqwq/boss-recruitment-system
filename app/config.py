"""配置管理模块"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Settings:
    """系统配置"""
    
    # DeepSeek API配置
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    
    # 数据库配置
    DATABASE_PATH = os.getenv("DATABASE_PATH", "data/boss_recruitment.db")
    PG_HOST = os.getenv("PG_HOST", "localhost")
    PG_PORT = int(os.getenv("PG_PORT", "5432"))
    PG_DB = os.getenv("PG_DB", "boss_recruitment")
    PG_USER = os.getenv("PG_USER", "boss")
    PG_PASSWORD = os.getenv("PG_PASSWORD", "boss123")
    # 每日上限
    DAILY_CONTACT_CAP = int(os.getenv("DAILY_CONTACT_CAP", "80"))
    DAILY_CHAT_ROUNDS_CAP = int(os.getenv("DAILY_CHAT_ROUNDS_CAP", "5"))
    
    # 下载目录
    DOWNLOAD_DIR = os.path.expanduser(os.getenv("DOWNLOAD_DIR", "~/Downloads"))
    
    @classmethod
    def validate(cls):
        """验证配置"""
        errors = []
        
        if not cls.DEEPSEEK_API_KEY:
            errors.append("DEEPSEEK_API_KEY未配置")
        
        if not Path(cls.DATABASE_PATH).parent.exists():
            Path(cls.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
        
        if errors:
            raise ValueError(f"配置错误: {', '.join(errors)}")
        
        return True

settings = Settings()
