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
    
    # 对话流配置
    CHAT_BOT_FLOW_PATH = os.getenv("CHAT_BOT_FLOW_PATH", "config/chat_bot_flow.json")
    
    # 屏幕配置
    SCREEN_PROFILE_PATH = os.getenv("SCREEN_PROFILE_PATH", "config/screen_profile.json")
    
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
