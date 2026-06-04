# BOSS直聘自动化系统 - UX 优化方案

## 现状分析

### 入口点混乱
当前系统存在多个入口文件，用户不清楚应该使用哪个：

| 入口文件 | 用途 | 状态 |
|---------|------|------|
| `main.py` | v2.0 简历收集（Playwright） | 推荐新用户 |
| `run_linux.py` | Linux Docker版对话 | Docker环境 |
| `run_chat_and_resume.py` | 简历+对话组合 | 功能完整 |
| `run_trinity.py` | 三位一体系统 | 最新架构 |
| `start.sh` | 一键启动脚本 | 便捷入口 |

### 核心问题
1. **入口点过多**：用户不知道从哪里开始
2. **配置分散**：.env配置项没有文档说明
3. **缺少统一CLI**：没有单一命令处理所有场景
4. **工作流不清晰**：筛选、简历、对话三大流程如何组合使用不明确

---

## 优化方案

### 1. 统一CLI入口 `boss.py`

创建单一入口文件，处理所有使用场景：

```python
#!/usr/bin/env python3
"""
BOSS直聘自动化系统 - 统一CLI入口
==================================
一站式处理：筛选、简历收集、AI对话
"""
import argparse
import sys
from pathlib import Path

# 子命令
def cmd_filter(args):
    """智能筛选 - 学校白名单+关键词过滤"""
    from app.workflows import FilterWorkflow
    workflow = FilterWorkflow(limit=args.limit, headless=args.headless)
    workflow.run()

def cmd_resume(args):
    """简历收集 - 自动下载简历+换微信"""
    from app.workflows import ResumeWorkflow
    workflow = ResumeWorkflow(limit=args.limit, headless=args.headless)
    workflow.run()

def cmd_chat(args):
    """AI对话 - 多轮智能沟通"""
    from app.workflows import ChatWorkflow
    workflow = ChatWorkflow(limit=args.limit, rounds=args.rounds)
    workflow.run()

def cmd_all(args):
    """完整流程 - 筛选→简历→对话"""
    from app.workflows import FullWorkflow
    workflow = FullWorkflow(limit=args.limit)
    workflow.run()

def main():
    parser = argparse.ArgumentParser(
        description="BOSS直聘自动化系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  boss filter --limit 50              # 智能筛选50人
  boss resume --headless             # 后台收集简历
  boss chat --rounds 3               # 3轮AI对话
  boss all --limit 30                # 完整流程
  boss --version                     # 查看版本
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
    
    args = parser.parse_args()
    
    if args.command == "filter":
        cmd_filter(args)
    elif args.command == "resume":
        cmd_resume(args)
    elif args.command == "chat":
        cmd_chat(args)
    elif args.command == "all":
        cmd_all(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
```

### 2. 配置文件优化

#### `.env.example` 完整模板

```bash
# ============================================================
# BOSS直聘自动化系统 - 环境配置
# ============================================================
# 复制此文件为 .env 并填入你的配置

# ----------------------------------------------------------
# AI配置（必需）
# ----------------------------------------------------------
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# ----------------------------------------------------------
# 浏览器配置
# ----------------------------------------------------------
HEADLESS=false                    # 是否无头模式
BROWSER_TIMEOUT=15000            # 页面超时(ms)
OPERATION_DELAY=300               # 操作延迟(ms)

# ----------------------------------------------------------
# 工作流配置
# ----------------------------------------------------------
MAX_CANDIDATES=50                 # 每次处理上限
MAX_CHAT_ROUNDS=3                 # 每人对话轮数
NEW_MSG_WAIT=5                    # 等待新消息(秒)

# ----------------------------------------------------------
# 筛选规则
# ----------------------------------------------------------
# 学校白名单（逗号分隔）
SCHOOL_WHITELIST=清华大学,北京大学,浙江大学,上海交通大学,复旦大学

# 关键词过滤（逗号分隔）
REQUIRE_KEYWORDS=全栈,Python,TypeScript
EXCLUDE_KEYWORDS=外包,实习,初级

# ----------------------------------------------------------
# 数据存储
# ----------------------------------------------------------
DB_PATH=data/boss_recruitment.db
LOG_DIR=logs
RESUME_DIR=~/Downloads/BossResumes

# ----------------------------------------------------------
# 系统配置
# ----------------------------------------------------------
DEBUG=false                       # 调试模式
LOG_LEVEL=INFO                    # 日志级别
```

### 3. 快速开始指南 `QUICKSTART.md`

```markdown
# BOSS直聘自动化系统 - 快速开始

## 1. 安装（首次）

\`\`\`bash
# 克隆或下载项目
cd boss-recruitment-system

# 安装依赖
pip3 install -r requirements.txt

# 安装Playwright浏览器
python3 -m playwright install chromium

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY
\`\`\`

## 2. 运行

\`\`\`bash
# 方式一：统一CLI（推荐）
python3 boss.py resume --limit 30      # 收集简历
python3 boss.py chat --rounds 3        # AI对话
python3 boss.py all --limit 30         # 完整流程

# 方式二：使用启动脚本
./start.sh all                         # 启动所有Agent

# 方式三：直接运行主程序
python3 main.py --limit 10             # 简历收集
\`\`\`

## 3. 首次登录

首次运行会自动打开浏览器，你需要：
1. 在打开的Chrome中扫码/密码登录
2. 登录成功后程序自动开始工作

## 4. 查看结果

- 简历：`~/Downloads/BossResumes/`
- 数据库：`data/boss_recruitment.db`
- 日志：`logs/`

## 工作流说明

### 筛选（filter）
根据学校白名单和关键词智能过滤候选人

### 简历（resume）
自动下载附件简历、求简历、换微信

### 对话（chat）
AI多轮智能沟通，自动跟进候选人

### 完整流程（all）
筛选 → 简历 → 对话，一站式自动化
```

### 4. 入口脚本设计 `boss.sh`

```bash
#!/bin/bash
# BOSS直聘自动化系统 - 统一启动脚本

set -e

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 工作目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 帮助信息
show_help() {
    cat << EOF
${BLUE}BOSS直聘自动化系统${NC}

用法: ./boss.sh [命令] [选项]

命令:
  filter      智能筛选候选人
  resume      收集简历（推荐新用户）
  chat        AI对话
  all         完整流程
  api         启动Web API
  doctor      系统诊断
  clean       清理缓存

选项:
  --limit N   处理上限人数（默认30）
  --headless  无头模式（后台运行）

示例:
  ./boss.sh resume --limit 50
  ./boss.sh all
  ./boss.sh doctor

EOF
}

# 系统检查
check_system() {
    echo -e "${YELLOW}🔍 系统检查...${NC}"
    
    # Python
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}❌ 未找到 python3${NC}"
        exit 1
    fi
    
    # 依赖
    python3 -c "import playwright" 2>/dev/null || {
        echo -e "${RED}❌ 缺少依赖，运行: pip3 install -r requirements.txt${NC}"
        exit 1
    }
    
    # 配置文件
    if [ ! -f .env ]; then
        echo -e "${YELLOW}⚠️  未找到.env文件，从模板创建...${NC}"
        cp .env.example .env
        echo -e "${YELLOW}⚠️  请编辑.env填入API密钥${NC}"
    fi
    
    # 目录
    mkdir -p logs data
    
    echo -e "${GREEN}✅ 系统检查完成${NC}"
}

# 系统诊断
run_doctor() {
    echo -e "${BLUE}🏥 系统诊断${NC}"
    echo ""
    
    echo "Python版本:"
    python3 --version
    
    echo ""
    echo "关键依赖:"
    python3 -c "
import sys
modules = ['playwright', 'httpx', 'dotenv']
for m in modules:
    try:
        __import__(m)
        print(f'  ✅ {m}')
    except:
        print(f'  ❌ {m}')
"
    
    echo ""
    echo "Playwright浏览器:"
    python3 -m playwright install --help &> /dev/null && \
        echo "  ✅ Chromium已安装" || echo "  ❌ 请运行: python3 -m playwright install chromium"
    
    echo ""
    echo "配置文件:"
    [ -f .env ] && echo "  ✅ .env存在" || echo "  ❌ .env缺失"
    [ -f .env ] && grep -q "DEEPSEEK_API_KEY=sk" .env && \
        echo "  ⚠️  请填入有效API密钥" || echo "  ✅ API密钥已配置"
}

# 清理缓存
run_clean() {
    echo -e "${YELLOW}🧹 清理缓存...${NC}"
    rm -rf __pycache__
    rm -rf app/__pycache__
    rm -rf .pytest_cache
    rm -f *.pyc
    echo -e "${GREEN}✅ 缓存已清理${NC}"
}

# 主逻辑
main() {
    local command=${1:-help}
    shift || true
    
    case "$command" in
        filter|resume|chat|all)
            check_system
            echo -e "${GREEN}🚀 启动 $command 模式...${NC}"
            python3 boss.py "$command" "$@"
            ;;
        api)
            check_system
            echo -e "${GREEN}🚀 启动API服务...${NC}"
            python3 -m uvicorn app.api:app --host 0.0.0.0 --port 8001 --reload
            ;;
        doctor)
            run_doctor
            ;;
        clean)
            run_clean
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            echo -e "${RED}❌ 未知命令: $command${NC}"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
```

---

## 实施优先级

### P0（立即）
1. 创建 `boss.py` 统一入口
2. 更新 `.env.example` 添加详细注释
3. 创建 `boss.sh` 启动脚本

### P1（本周）
1. 创建 `QUICKSTART.md` 快速开始指南
2. 更新 `README.md` 指向新的入口
3. 添加 `boss doctor` 诊断命令

### P2（下周）
1. 实现工作流模块（`app/workflows.py`）
2. 添加进度显示和统计
3. 优化错误提示和帮助信息

---

## 文件清单

```
boss-recruitment-system/
├── boss.py              # 🆕 统一CLI入口
├── boss.sh              # 🆕 统一启动脚本
├── .env.example         # ✏️ 更新配置模板
├── QUICKSTART.md        # 🆕 快速开始
├── README.md            # ✏️ 更新主文档
├── main.py              # 保留（兼容）
├── run_trinity.py       # 保留（三位一体）
├── start.sh             # 保留（兼容）
└── app/
    ├── workflows.py     # 🆕 工作流模块
    ├── __init__.py
    ├── config.py
    ├── screen.py
    ├── vision.py
    └── database.py
```

---

## 兼容性

- 保留所有现有入口文件（向后兼容）
- 新旧方式可以并存使用
- 渐进式迁移，不破坏现有用户习惯
