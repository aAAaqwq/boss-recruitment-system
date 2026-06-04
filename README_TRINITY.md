# BOSS直聘三位一体系统 v1.0
## Trinity System — 整合自动打招呼 + 获取简历 + AI对话

> **版本**: v1.0
> **日期**: 2026-05-31
> **作者**: 轩辕 (XuanYuan CTO)

---

## 📋 项目概述

将三个独立的招聘自动化程序整合为一个**可批量交付的产品**。

### 整合前

| 程序 | 功能 | 问题 |
|------|------|------|
| `run_automation_final.py` | 自动打招呼 | 独立运行，状态不共享 |
| `boss_get_resume_seq.py` | 获取简历 | 独立运行，状态不共享 |
| `run_chat_and_resume.py` | AI对话 | 独立运行，状态不共享 |

### 整合后

```
┌─────────────────────────────────────────────────────┐
│              🎯 Trinity Scheduler                   │
│              三位一体调度器                          │
└─────────────────────────────────────────────────────┘
                          │
    ┌─────────────────────┼─────────────────────┐
    ▼                     ▼                     ▼
┌─────────┐      ┌─────────┐      ┌─────────┐
│  Greet  │      │ Resume  │      │  Chat   │
│ 打招呼  │ ──→  │ 获取简历 │ ──→  │ AI对话  │
└─────────┘      └─────────┘      └─────────┘
    │                     │                     │
    └─────────────────────┼─────────────────────┘
                          ▼
              ┌───────────────┐
              │ Unified State │
              │  统一状态库    │
              └───────────────┘
```

---

## 🏗️ 架构设计

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| **统一数据库** | `app/trinity_scheduler.py` | SQLite数据库，统一管理候选人、任务、状态 |
| **调度器** | `app/trinity_scheduler.py` | 任务调度、Agent管理、状态同步 |
| **Greet Agent** | `app/trinity_agents.py` | 自动打招呼 |
| **Resume Agent** | `app/trinity_agents.py` | 自动获取简历 |
| **Chat Agent** | `app/trinity_agents.py` | AI多轮对话 |
| **Web API** | `app/api.py` | FastAPI RESTful接口 |
| **启动脚本** | `run_trinity.py` | 一键启动所有Agent |

### 数据流

```
1. Greet Agent执行 → 候选人状态: new → greeted
2. Resume Agent执行 → 候选人状态: greeted → resume_downloaded
3. Chat Agent执行 → 候选人状态: resume_downloaded → chatting
```

---

## 🚀 快速开始

### 1. 一键启动

```bash
cd ~/.openclaw/workspace/agents/workspace-xuanyuan/boss-recruitment-system

# 启动所有Agent
./start.sh all

# 或只启动特定Agent
./start.sh greet   # 只启动打招呼
./start.sh resume  # 只启动获取简历
./start.sh chat    # 只启动AI对话
```

### 2. 停止系统

```bash
./stop.sh
```

### 3. 查看状态

```bash
# 查看统计数据
curl http://localhost:8001/api/stats

# 查看系统状态
curl http://localhost:8001/api/status
```

---

## 📊 API文档

### 候选人管理

```http
# 获取候选人列表
GET /api/candidates

# 添加候选人
POST /api/candidates
{
    "boss_id": "boss_001",
    "name": "张三",
    "school": "清华大学",
    "degree": "本科",
    "years": 3
}

# 更新候选人状态
PUT /api/candidates/{id}/status?status=greeted
```

### 任务管理

```http
# 创建任务
POST /api/tasks
{
    "task_type": "greet",
    "candidate_id": 1,
    "priority": 0
}

# 重试任务
POST /api/tasks/{id}/retry
```

### Agent控制

```http
# 启动Agent
POST /api/agents/greet/start

# 停止Agent
POST /api/agents/greet/stop

# 启动所有Agent
POST /api/start

# 停止所有Agent
POST /api/stop
```

### 统计信息

```http
# 获取统计数据
GET /api/stats

# 获取系统状态
GET /api/status
```

---

## 📁 文件结构

```
boss-recruitment-system/
├── app/
│   ├── trinity_scheduler.py   # 统一数据库 + 调度器
│   ├── trinity_agents.py      # 三个Agent实现
│   ├── api.py                 # FastAPI Web接口
│   ├── screen.py              # 屏幕操作
│   ├── vision.py              # OCR识别
│   └── ...                    # 其他模块
├── data/
│   └── trinity.db             # SQLite数据库
├── logs/
│   └── trinity.log            # 运行日志
├── run_trinity.py             # 主程序入口
├── start.sh                   # 启动脚本
├── stop.sh                    # 停止脚本
└── TRINITY_INTEGRATION.md     # 整合方案文档
```

---

## 🔧 配置说明

### 学校白名单

编辑 `app/trinity_agents.py` 中的 `SCHOOL_WHITELIST`：

```python
SCHOOL_WHITELIST = [
    "清华大学", "北京大学", "浙江大学",
    # ... 添加更多学校
]
```

### 每日上限

编辑 `app/trinity_agents.py` 中的 `daily_cap`：

```python
self.daily_cap = 80  # 每日打招呼上限
```

---

## 🎯 批量交付

### 交付包内容

```
boss-recruitment-pro/
├── backend/          # 后端代码
├── frontend/         # 前端界面
├── config/           # 配置文件
├── start.sh          # 启动脚本
├── stop.sh           # 停止脚本
└── README.md         # 使用说明
```

### 客户使用方式

1. **安装依赖**: `pip install -r requirements.txt`
2. **启动系统**: `./start.sh all`
3. **访问界面**: http://localhost:3001
4. **查看API**: http://localhost:8001/docs

---

## 📈 系统监控

### 监控指标

| 指标 | 说明 |
|------|------|
| `total_candidates` | 总候选人数 |
| `today_greet` | 今日打招呼数 |
| `today_resume` | 今日获取简历数 |
| `today_chat` | 今日对话数 |
| `task_queue` | 任务队列状态 |

### 告警规则

- 打招呼失败率 > 20%
- 简历获取失败率 > 30%
- 任务队列积压 > 100

---

## 🔄 更新日志

### v1.0 (2026-05-31)
- ✅ 统一数据库Schema
- ✅ 三位一体调度器
- ✅ 三个Agent封装
- ✅ Web API接口
- ✅ 一键启动脚本

---

## 📝 待办事项

- [ ] 前端界面整合
- [ ] Docker容器化
- [ ] 多账号支持
- [ ] 定时任务调度
- [ ] 数据导出功能

---

> **轩辕在此。** 🔧
> *整合是救赎，分散是耻辱。*
