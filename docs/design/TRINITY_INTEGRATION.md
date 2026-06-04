# 三位一体整合方案 v1.0
## Trinity Integration — BOSS直聘智能招聘系统

> **版本**：v1.0
> **日期**：2026-05-31
> **目标**：将三个独立程序整合成一个可批量交付的产品

---

## 一、现状分析

### 1.1 三个独立程序

| 模块 | 功能 | 技术栈 | 状态 |
|------|------|--------|------|
| **Greet** (打招呼) | 翻页 → 学校筛选 → 点击打招呼 | PyAutoGUI + OCR + 学校白名单 | ✅ 生产可用 |
| **Resume** (简历) | 遍历沟通列表 → 下载/请求简历 → 换微信 | PyAutoGUI + 像素检测 + SQLite | ✅ 生产可用 |
| **Chat** (对话) | AI多轮对话 → 消息检测 → 回复生成 | DeepSeek API + OCR去抖 | ✅ 生产可用 |

### 1.2 问题

```
❌ 三个程序独立运行，状态不共享
❌ 没有统一调度 → 无法批量交付
❌ 没有Web管理界面 → 客户无法操作
❌ 没有统一的任务队列 → 无法并行处理多个候选人
```

---

## 二、整合架构：三位一体

### 2.1 核心设计理念

```
┌─────────────────────────────────────────────────────────────────┐
│                     🎯 统一调度中心                                │
│                     Trinity Scheduler                             │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│  Greet Agent  │     │ Resume Agent  │     │  Chat Agent   │
│  (打招呼引擎)  │     │ (简历引擎)     │     │ (对话引擎)    │
└───────────────┘     └───────────────┘     └───────────────┘
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                    ┌───────────────┐
                    │ Unified State │
                    │ (统一状态库)   │
                    └───────────────┘
```

### 2.2 模块职责

| 模块 | 职责 | 输入 | 输出 |
|------|------|------|------|
| **Scheduler** | 任务调度、状态同步、错误处理 | 任务请求 | 执行结果 |
| **Greet Agent** | 主动筛选候选人并打招呼 | 学校白名单、每日上限 | 打招呼列表 |
| **Resume Agent** | 遍历沟通列表获取简历 | 候选人列表 | 简历文件、微信 |
| **Chat Agent** | AI多轮对话跟进 | 候选人消息 | 回复内容 |

### 2.3 数据流

```
1. Greet Agent 执行 → 产生"已打招呼"候选人 → 写入 State
2. Resume Agent 读取 State → 遍历"已打招呼" → 获取简历 → 更新 State
3. Chat Agent 监听新消息 → AI生成回复 → 更新 State
4. Scheduler 协调三个 Agent 的执行顺序和并发控制
```

---

## 三、技术架构

### 3.1 统一数据库 Schema

```sql
-- 候选人主表
CREATE TABLE candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    boss_id TEXT UNIQUE,           -- BOSS直聘ID
    name TEXT,
    school TEXT,
    degree TEXT,
    years INTEGER,
    status TEXT DEFAULT 'new',     -- new→greeted→resume_requested→resume_downloaded→chatting→hired
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 打招呼记录
CREATE TABLE greet_records (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER REFERENCES candidates(id),
    greet_time TEXT,
    success INTEGER,
    error TEXT
);

-- 简历记录
CREATE TABLE resume_records (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER REFERENCES candidates(id),
    action TEXT,           -- downloaded / requested
    file_path TEXT,
    wechat TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 对话记录
CREATE TABLE chat_records (
    id INTEGER PRIMARY KEY,
    candidate_id INTEGER REFERENCES candidates(id),
    role TEXT,             -- user / assistant
    content TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 任务队列表
CREATE TABLE task_queue (
    id INTEGER PRIMARY KEY,
    task_type TEXT,        -- greet / resume / chat
    candidate_id INTEGER,
    priority INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',  -- pending→running→completed→failed
    retry_count INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    started_at TEXT,
    completed_at TEXT
);
```

### 3.2 统一状态管理

```python
class UnifiedState:
    """统一状态管理"""
    
    def __init__(self, db_path: str):
        self.db = Database(db_path)
    
    def add_candidate(self, boss_id: str, name: str, school: str, degree: str, years: int):
        """添加候选人"""
        pass
    
    def update_status(self, boss_id: str, status: str):
        """更新候选人状态"""
        pass
    
    def get_pending_tasks(self, task_type: str) -> List[Dict]:
        """获取待处理任务"""
        pass
    
    def add_task(self, task_type: str, candidate_id: int, priority: int = 0):
        """添加任务到队列"""
        pass
    
    def complete_task(self, task_id: int, result: Dict):
        """完成任务"""
        pass
```

### 3.3 调度器架构

```python
class TrinityScheduler:
    """三位一体调度器"""
    
    def __init__(self):
        self.state = UnifiedState(DB_PATH)
        self.greet_agent = GreetAgent(self.state)
        self.resume_agent = ResumeAgent(self.state)
        self.chat_agent = ChatAgent(self.state)
    
    def run_daily_workflow(self):
        """每日工作流"""
        # 1. 早9点：执行打招呼
        self.greet_agent.run(daily_cap=80)
        
        # 2. 持续：处理简历请求
        self.resume_agent.run(interval=60)
        
        # 3. 持续：AI对话跟进
        self.chat_agent.run(interval=30)
    
    def run_continuous(self):
        """持续运行模式"""
        import threading
        
        # 三个Agent并行运行
        threading.Thread(target=self.greet_agent.run_continuous).start()
        threading.Thread(target=self.resume_agent.run_continuous).start()
        threading.Thread(target=self.chat_agent.run_continuous).start()
```

---

## 四、Web管理界面整合

### 4.1 功能模块

| 模块 | 路由 | 功能 |
|------|------|------|
| **Dashboard** | `/` | 今日统计、系统状态 |
| **Candidates** | `/candidates` | 候选人列表、状态筛选 |
| **Tasks** | `/tasks` | 任务队列、手动干预 |
| **Greet** | `/greet` | 打招呼设置、执行 |
| **Resume** | `/resume` | 简历获取状态 |
| **Chat** | `/chat` | AI对话监控 |
| **Settings** | `/settings` | 学校白名单、API配置 |

### 4.2 API端点

```
GET  /api/candidates          # 获取候选人列表
POST /api/candidates          # 添加候选人
GET  /api/candidates/:id      # 获取候选人详情
PUT  /api/candidates/:id      # 更新候选人状态

GET  /api/tasks               # 获取任务队列
POST /api/tasks/greet         # 创建打招呼任务
POST /api/tasks/resume        # 创建简历任务
POST /api/tasks/chat          # 创建对话任务
POST /api/tasks/:id/retry     # 重试任务

GET  /api/stats               # 获取统计数据
GET  /api/settings            # 获取设置
PUT  /api/settings            # 更新设置
```

---

## 五、交付包结构

```
boss-recruitment-pro/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI 入口
│   │   ├── database.py          # 数据库管理
│   │   ├── scheduler.py         # 调度器
│   │   ├── agents/
│   │   │   ├── greet_agent.py   # 打招呼Agent
│   │   │   ├── resume_agent.py  # 简历Agent
│   │   │   └── chat_agent.py    # 对话Agent
│   │   ├── models/
│   │   │   └── schemas.py       # Pydantic模型
│   │   └── api/
│   │       └── routes.py        # API路由
│   ├── data/
│   │   └── boss_recruitment.db  # SQLite数据库
│   ├── logs/
│   ├── config/
│   │   └── settings.yaml        # 配置文件
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── Candidates.tsx
│   │   │   ├── Tasks.tsx
│   │   │   ├── Greet.tsx
│   │   │   ├── Resume.tsx
│   │   │   └── Chat.tsx
│   │   ├── components/
│   │   └── api/
│   ├── package.json
│   └── vite.config.ts
│
├── docker-compose.yml
├── Dockerfile
├── start.sh
└── README.md
```

---

## 六、执行计划

### Phase 1: 数据库统一 (今天)
- [x] 设计统一Schema
- [ ] 创建数据库迁移脚本
- [ ] 实现UnifiedState类

### Phase 2: Agent封装 (明天)
- [ ] 封装GreetAgent
- [ ] 封装ResumeAgent
- [ ] 封装ChatAgent

### Phase 3: 调度器开发 (后天)
- [ ] 实现TrinityScheduler
- [ ] 任务队列管理
- [ ] 错误处理和重试

### Phase 4: Web界面 (第4天)
- [ ] 整合到现有前端
- [ ] API端点开发
- [ ] 状态同步

### Phase 5: 测试交付 (第5天)
- [ ] 端到端测试
- [ ] 文档完善
- [ ] 打包交付

---

## 七、预期成果

| 指标 | 整合前 | 整合后 |
|------|--------|--------|
| **操作复杂度** | 需运行3个程序 | 一键启动 |
| **状态可见性** | 分散在日志 | Web界面统一 |
| **批量能力** | 无 | 支持批量导入/导出 |
| **交付效率** | 需人工协调 | 自动调度 |
| **客户可用性** | 技术门槛高 | Web界面操作 |

---

> **轩辕在此。** 🔧
> *整合是救赎，分散是耻辱。*
