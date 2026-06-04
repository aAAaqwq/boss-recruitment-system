# BOSS直聘自动化系统 - 项目架构文档

> 最后更新: 2025-06-04
> 版本: v2.1.0

---

## 1. 项目概述

BOSS直聘三位一体自动化系统是一个整合**打招呼**、**获取简历**、**AI对话**的自动化招聘系统。

### 核心功能
- 🔍 **智能筛选**: 根据学历、经验、学校等条件自动筛选候选人
- 👋 **批量打招呼**: 自动发送个性化招呼消息
- 📄 **简历收集**: 自动下载简历并处理换微信
- 💬 **AI对话**: 基于DeepSeek API进行智能对话

---

## 2. 项目结构

```
boss-recruitment-system/
├── main.py                    # 主要入口 - 简历收集器
├── boss.py                    # CLI统一入口 - 支持三种模式
├── run.py                     # 简历获取轮转系统启动
├── requirements.txt           # Python依赖
├── Dockerfile                 # Docker镜像配置
├── docker-compose.yml         # Docker编排配置
├── .env.example               # 环境变量模板
│
├── app/                       # 核心模块
│   ├── api.py                # FastAPI Web API (RESTful接口)
│   ├── auth.py               # JWT认证模块
│   ├── config.py             # 配置管理
│   ├── database.py           # SQLite数据库操作
│   ├── logging_config.py     # 日志配置
│   ├── workflows.py          # 三大核心工作流
│   ├── trinity_agents.py     # 三位一体自动化整合
│   ├── trinity_scheduler.py  # 统一调度器
│   ├── resume_collector.py   # 简历自动收集
│   ├── communicate_collector.py # AI对话自动化
│   ├── vision.py             # OCR视觉识别
│   ├── screen.py             # 屏幕操作(macOS)
│   ├── screen_linux.py      # 屏幕操作(Linux)
│   └── data/                 # 数据目录
│
├── tests/                    # 测试目录
│   ├── test_*.py            # 单元测试
│   └── fixtures/            # 测试数据
│
├── data/                     # 数据文件
│   └── boss_recruitment.db   # SQLite数据库
│
├── logs/                     # 日志文件
│
├── config/                   # 配置文件
│   ├── chat_bot_flow.json   # AI对话流程配置
│   └── screen_profile.json  # 屏幕区域配置
│
├── templates/                # 前端模板
│   └── index.html           # Web控制台
│
└── static/                    # 静态资源
```

---

## 3. 分层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      入口层 (Entry Points)                       │
├─────────────────────────────────────────────────────────────────┤
│  main.py         │ 简历收集器 (34KB) - 核心逻辑                   │
│  boss.py         │ 统一CLI入口 - 支持筛选/简历/AI对话三种模式       │
│  run.py          │ 简历获取轮转系统启动入口                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                      应用层 (app/)                               │
├─────────────────────────────────────────────────────────────────┤
│  api.py              │ FastAPI Web API (RESTful接口)              │
│  auth.py            │ JWT认证模块                                 │
│  config.py          │ 配置管理                                    │
│  logging_config.py  │ 日志配置                                    │
│  database.py        │ SQLite数据库操作                             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    核心业务层 (Core Logic)                        │
├─────────────────────────────────────────────────────────────────┤
│  workflows.py        │ 三大核心工作流 (14KB)                       │
│  trinity_agents.py   │ 三位一体自动化整合 (16KB)                   │
│  trinity_scheduler.py│ 统一调度器                                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│                    功能模块层 (Modules)                           │
├─────────────────────────────────────────────────────────────────┤
│  resume_collector.py      │ 简历自动收集                        │
│  communicate_collector.py │ AI对话自动化                         │
│  vision.py               │ OCR视觉识别                          │
│  screen.py/screen_linux.py│ 屏幕操作/截图                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 核心模块说明

### 4.1 API模块 (app/api.py)

FastAPI后端，提供RESTful接口：

| 端点 | 方法 | 功能 |
|------|------|------|
| `/` | GET | Web控制台主页 |
| `/api/auth/login` | POST | 用户登录，返回JWT |
| `/api/automation/start` | POST | 启动自动化任务 |
| `/api/automation/stop` | POST | 停止自动化任务 |
| `/api/automation/status` | GET | 获取任务状态 |
| `/api/candidates` | GET | 获取候选人列表 |
| `/api/stats` | GET | 获取统计数据 |
| `/health` | GET | 健康检查 |

### 4.2 工作流模块 (app/workflows.py)

三大核心工作流：

1. **workflow_3_1_auto_contact**: 主动筛选沟通流程
   - 按条件筛选候选人
   - 批量发送招呼

2. **workflow_3_2_resume_collection**: 简历获取流程
   - 打招呼候选人
   - 获取简历链接
   - 下载简历文件

3. **workflow_3_3_ai_chat**: AI对话流程
   - 读取未读消息
   - 调用AI生成回复
   - 发送回复消息

### 4.3 数据库模块 (app/database.py)

SQLite数据库，主要表结构：

| 表名 | 用途 |
|------|------|
| `candidates` | 候选人信息 |
| `communications` | 沟通记录 |
| `conversations` | 对话记录 |
| `interviews` | 面试安排 |
| `runtime_state` | 运行时状态 |
| `processed_candidates` | 已处理候选人 |

---

## 5. Docker部署架构

### 5.1 容器架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        宿主机 (Host)                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ 客户A容器    │  │ 客户B容器    │  │ 客户C容器    │         │
│  │ Port: 3101   │  │ Port: 3102   │  │ Port: 3103   │         │
│  │ ┌──────────┐ │  │ ┌──────────┐ │  │ ┌──────────┐ │         │
│  │ │ FastAPI  │ │  │ │ FastAPI  │ │  │ │ FastAPI  │ │         │
│  │ │ Chromium │ │  │ │ Chromium │ │  │ │ Chromium │ │         │
│  │ │ Python   │ │  │ │ Python   │ │  │ │ Python   │ │         │
│  │ └──────────┘ │  │ └──────────┘ │  │ └──────────┘ │         │
│  │ /data/customer_a│  │/data/customer_b│  │/data/cust_c │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│                                                                  │
│  共享只读: ./config/  ./.env                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 端口映射

| 外部端口 | 内部端口 | 服务 | 说明 |
|---------|---------|------|------|
| 3101 | 8001 | API | Web控制台接口 |
| 5901 | 5901 | VNC | VNC服务 |
| 6901 | 6901 | noVNC | Web VNC客户端 |

### 5.3 数据持久化

```yaml
volumes:
  - ./data/${CUSTOMER_ID}:/app/data      # 数据库
  - ./logs/${CUSTOMER_ID}:/app/logs      # 日志
  - ./config:/app/config:ro              # 配置(只读)
```

---

## 6. 依赖说明

### 6.1 核心依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| fastapi | >=0.136.0 | Web框架 |
| uvicorn | >=0.49.0 | ASGI服务器 |
| jinja2 | >=3.1.0 | 模板渲染 |
| pyautogui | ==0.9.54 | 屏幕自动化 |
| opencv-python | ==4.9.0.80 | 图像处理 |
| pytesseract | ==0.3.10 | OCR识别 |
| python-jose | >=3.3.0 | JWT认证 |
| playwright | >=1.60.0 | 浏览器自动化 |
| nodriver | >=1.0.0 | Chrome控制(Linux) |

### 6.2 平台差异

| 特性 | macOS | Linux (Docker) |
|------|-------|----------------|
| 屏幕捕获 | Quartz/Vision | nodriver/screenshot |
| OCR | 原生Vision | Tesseract |
| 浏览器 | pyautogui+playwright | nodriver+chromium |
| 图形界面 | 原生桌面 | VNC/noVNC |

---

## 7. 环境配置

### 7.1 必需环境变量

```bash
# DeepSeek AI
DEEPSEEK_API_KEY=your_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com

# 系统配置
DATABASE_PATH=data/boss_recruitment.db
DAILY_CONTACT_CAP=80
DAILY_CHAT_ROUNDS_CAP=5

# API配置
API_HOST=0.0.0.0
API_PORT=8001
ALLOWED_ORIGINS=http://localhost:3000

# 认证
SECRET_KEY=your_jwt_secret_key
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_me
```

### 7.2 配置文件

**config/chat_bot_flow.json**: AI对话流程配置

**config/screen_profile.json**: 屏幕OCR区域坐标

---

## 8. 部署指南

### 8.1 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动API服务
python -m uvicorn app.api:app --host 0.0.0.0 --port 8001

# 访问
open http://localhost:8001/docs
```

### 8.2 Docker部署

```bash
# 构建镜像
docker build -t boss-automation:latest .

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

---

## 9. 外部服务依赖

| 服务 | 用途 | 必需性 |
|------|------|--------|
| DeepSeek API | AI对话生成 | ✅ 必需 |
| BOSS直聘网站 | 自动化目标 | ✅ 必需 |
| Chrome/Chromium | 浏览器自动化 | ✅ 必需 |
| VNC Server | 远程桌面 | Docker环境 |

---

## 10. 维护说明

### 10.1 日志位置
- `logs/` 目录
- 按日期自动轮转

### 10.2 数据备份
- SQLite数据库: `data/boss_recruitment.db`
- 建议每日备份

### 10.3 常见问题

**问题1**: OCR识别不准确
- 解决: 调整 `config/screen_profile.json` 坐标

**问题2**: 浏览器启动失败
- 解决: 检查Chrome/Chromium是否正确安装

**问题3**: API返回401
- 解决: 检查JWT token是否过期

---

*文档版本: v2.1.0*
*最后更新: 2025-06-04*
