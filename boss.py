#!/usr/bin/env python3
"""
BOSS直聘自动化系统 - 统一CLI入口
====================================
一站式处理：筛选、简历收集、AI对话
"""
import argparse
import sys
from pathlib import Path

# 确保app模块可导入
sys.path.insert(0, str(Path(__file__).parent))


def cmd_filter(args):
    """智能筛选 - Phase 2 实现"""
    print("⚠️  智能筛选功能将在 Phase 2 实现，请使用 Web API: POST /api/filter/contact")


def cmd_resume(args):
    """简历收集 - Phase 2 实现"""
    print("⚠️  简历收集功能将在 Phase 2 实现，请使用 Web API: POST /api/resume/batch")


def cmd_chat(args):
    """AI对话 - Phase 2 实现"""
    print("⚠️  AI对话功能将在 Phase 2 实现，请使用 Web API: POST /api/chat/batch")


def cmd_all(args):
    """完整流程 - Phase 2 实现"""
    print("⚠️  完整流程功能将在 Phase 2 实现，请使用 Web API: POST /api/automation/start")


def cmd_api(args):
    """启动Web API服务"""
    import uvicorn
    from app.api import app

    host = args.host or "0.0.0.0"
    port = args.port or 8001
    reload = args.reload

    print(f"🚀 启动API服务: http://{host}:{port}")
    print(f"📖 API文档: http://{host}:{port}/docs")
    uvicorn.run(app, host=host, port=port, reload=reload)


def cmd_doctor(args):
    """系统诊断 - 检查依赖和配置"""
    from app.logging_config import logger

    print("🏥 系统诊断")
    print()

    # Python版本
    print("Python版本:")
    print(f"  {sys.version}")
    print()

    # 关键依赖
    print("关键依赖:")
    modules = {
        'nodriver': '浏览器自动化',
        'fastapi': 'Web API',
        'pydantic': '数据验证',
        'dotenv': '环境变量',
        'jose': 'JWT认证',
        'httpx': 'HTTP客户端'
    }

    for module, desc in modules.items():
        try:
            __import__(module)
            print(f"  ✅ {module} ({desc})")
        except ImportError:
            print(f"  ❌ {module} ({desc}) - 请运行: pip install {module}")

    print()

    # nodriver浏览器
    print("nodriver:")
    try:
        import nodriver
        print("  ✅ nodriver 已安装")
    except ImportError:
        print("  ❌ 请运行: pip install nodriver")

    print()

    # 配置文件
    print("配置文件:")
    from dotenv import load_dotenv
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        print(f"  ✅ .env 存在")
        load_dotenv()
        import os
        if os.getenv("DEEPSEEK_API_KEY"):
            print(f"  ✅ DEEPSEEK_API_KEY 已配置")
        else:
            print(f"  ⚠️  请在.env中配置 DEEPSEEK_API_KEY")
    else:
        print(f"  ❌ .env 缺失 - 请复制 .env.example 并填入配置")

    print()

    # 目录检查
    print("目录检查:")
    for dir_name in ["logs", "data"]:
        dir_path = Path(__file__).parent / dir_name
        if dir_path.exists():
            print(f"  ✅ {dir_name}/ 目录存在")
        else:
            print(f"  ⚠️  {dir_name}/ 目录不存在 - 将自动创建")


def cmd_clean(args):
    """清理缓存和临时文件"""
    import shutil
    from app.logging_config import logger

    print("🧹 清理缓存...")

    # Python缓存
    for cache_dir in ["__pycache__", "app/__pycache__", ".pytest_cache"]:
        cache_path = Path(__file__).parent / cache_dir
        if cache_path.exists():
            shutil.rmtree(cache_path)
            print(f"  ✅ 删除 {cache_dir}")

    # .pyc文件
    for pyc_file in Path(__file__).parent.rglob("*.pyc"):
        pyc_file.unlink()
        print(f"  ✅ 删除 {pyc_file.relative_to(Path(__file__).parent)}")

    print("✅ 清理完成")


def main():
    parser = argparse.ArgumentParser(
        description="BOSS直聘自动化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  boss filter --limit 50              # 智能筛选50人
  boss resume --headless             # 后台收集简历
  boss chat --rounds 3               # 3轮AI对话
  boss all --limit 30                # 完整流程
  boss api --port 8001               # 启动API服务
  boss doctor                        # 系统诊断
  boss clean                         # 清理缓存
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # 筛选命令
    p_filter = subparsers.add_parser("filter", help="智能筛选候选人")
    p_filter.add_argument("--limit", type=int, default=50, help="处理上限")
    p_filter.add_argument("--headless", action="store_true", help="无头模式")

    # 简历命令
    p_resume = subparsers.add_parser("resume", help="收集简历")
    p_resume.add_argument("--limit", type=int, default=30, help="处理上限")
    p_resume.add_argument("--headless", action="store_true", help="无头模式")

    # 对话命令
    p_chat = subparsers.add_parser("chat", help="AI对话")
    p_chat.add_argument("--limit", type=int, default=20, help="处理上限")
    p_chat.add_argument("--rounds", type=int, default=3, help="对话轮数")

    # 完整流程
    p_all = subparsers.add_parser("all", help="完整流程")
    p_all.add_argument("--limit", type=int, default=30, help="处理上限")

    # API命令
    p_api = subparsers.add_parser("api", help="启动Web API服务")
    p_api.add_argument("--host", type=str, help="绑定地址")
    p_api.add_argument("--port", type=int, help="端口号")
    p_api.add_argument("--reload", action="store_true", help="自动重载")

    # 诊断命令
    subparsers.add_parser("doctor", help="系统诊断")

    # 清理命令
    subparsers.add_parser("clean", help="清理缓存")

    args = parser.parse_args()

    # 路由到对应的命令处理函数
    if args.command == "filter":
        cmd_filter(args)
    elif args.command == "resume":
        cmd_resume(args)
    elif args.command == "chat":
        cmd_chat(args)
    elif args.command == "all":
        cmd_all(args)
    elif args.command == "api":
        cmd_api(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "clean":
        cmd_clean(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
