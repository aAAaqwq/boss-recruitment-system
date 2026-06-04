"""
BOSS直聘系统 - 统一日志配置
提供结构化日志，替代print()语句
"""
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# ============================================================
# 配置
# ============================================================
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


# ============================================================
# 日志配置
# ============================================================
def setup_logging(
    name: str = "boss_system",
    level: int = logging.INFO,
    log_to_file: bool = True,
    log_to_console: bool = True
) -> logging.Logger:
    """配置日志系统

    Args:
        name: 日志器名称
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: 是否输出到文件
        log_to_console: 是否输出到控制台

    Returns:
        配置好的logger实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # 文件处理器 - 按日期分割
    if log_to_file:
        log_file = LOG_DIR / f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # 控制台处理器
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


# ============================================================
# 全局日志实例
# ============================================================
# 主系统日志
logger = setup_logging("boss_system")

# 各模块专用日志
automation_logger = setup_logging("automation")
vision_logger = setup_logging("vision")
database_logger = setup_logging("database")
api_logger = setup_logging("api")


# ============================================================
# 便捷函数
# ============================================================
def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取日志器实例

    Args:
        name: 日志器名称，None则返回主日志器

    Returns:
        Logger实例
    """
    if name is None:
        return logger
    return setup_logging(name)


# ============================================================
# 上下文管理器用于临时日志级别
# ============================================================
class LogLevelContext:
    """临时修改日志级别的上下文管理器"""

    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.new_level = level
        self.old_level = None

    def __enter__(self):
        self.old_level = self.logger.level
        self.logger.setLevel(self.new_level)
        return self.logger

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.setLevel(self.old_level)
