# 多租户用户流程设计

## 一、从注册到使用 —— 完整流程

```
用户访问网站
    │
    ▼
┌─────────────────────┐
│   中控服务 (常驻)     │
│                     │
│ POST /api/auth/register
│ POST /api/auth/login
│ GET  /api/instance/status
│ POST /api/instance/start
│ GET  /api/admin/instances
│                     │
│ 共享 PostgreSQL      │
│ ┌─────────────────┐ │
│ │ users 表         │ │
│ │ boss_accounts 表 │ │
│ └─────────────────┘ │
└─────────────────────┘
         │
         │ 按 user_id 路由到专属容器
         ▼
┌─────────────────────┐     ┌─────────────────────┐
│  用户A 容器(按需)    │     │  用户B 容器(按需)    │
│  Chrome + 驾驶舱     │     │  Chrome + 驾驶舱     │
│  连 PG 看自己的数据   │     │  连 PG 看自己的数据   │
└─────────────────────┘     └─────────────────────┘
```

## 二、第一步：用户注册

### 注册页面

用户访问 `https://boss.xxx.com/login`，看到以下页面：

```
┌──────────────────────────────┐
│      BOSS 招聘自动化系统      │
│                              │
│  [ 登录 ]  [ 注册 ]           │
│                              │
│  ┌── 注册新账号 ──────────┐  │
│  │                        │  │
│  │ 用户名  [__________]    │  │
│  │ 显示名  [__________]    │  │  ← 选填，默认同用户名
│  │ 密码    [__________]    │  │
│  │ 确认密码 [__________]   │  │
│  │                        │  │
│  │        [ 注册 ]         │  │
│  └────────────────────────┘  │
│                              │
└──────────────────────────────┘
```

### 后端处理

```
POST /api/auth/register
{
    "username": "zhangsan",
    "password": "mypassword",
    "display_name": "张三"
}
```

```python
# 后端逻辑（中控服务）
def register(username, password, display_name):
    pwd_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

    INSERT INTO users (username, password_hash, display_name, role, is_active)
    VALUES ('zhangsan', pwd_hash, '张三', 'user', true)
    RETURNING id

    → 返回 { "user_id": 3, "username": "zhangsan", "role": "user" }
```

### 数据库结果

```sql
-- users 表新增一条：
id | username  | password_hash      | display_name | role  | is_active
---+-----------+--------------------+--------------+-------+----------
 1 | admin     | $2b$12$xxx...      | 管理员        | admin | t
 2 | zhangsan  | $2b$12$yyy...      | 张三          | user  | t
```

## 三、第二步：用户登录

### 登录

```
POST /api/auth/login
{
    "username": "zhangsan",
    "password": "mypassword"
}
```

```python
def login(username, password):
    user = SELECT * FROM users WHERE username = 'zhangsan'

    if not user or not user.is_active:
        return 401

    if bcrypt.checkpw(password, user.password_hash):
        token = jwt.encode({
            "user_id": user.id,       # 3
            "username": "zhangsan",
            "role": "user",
            "exp": now() + 1小时
        })
        return { "access_token": token, "role": "user" }
```

### 前端拿到 JWT

```javascript
// 登录成功后
localStorage.setItem("token", data.access_token);

// 根据 role 跳转不同页面
if (data.role === "admin") {
    location.href = "/admin";      // 管理员后台
} else {
    location.href = "/dashboard";  // 用户驾驶舱
}
```

## 四、第三步：启动用户专属环境

用户第一次使用时，容器还没起来。

```
GET /api/instance/status
Authorization: Bearer <JWT>
→ 中控服务解码 JWT → user_id=3
→ 查实例表 → status: "stopped"
→ 返回 { "status": "stopped", "message": "环境未启动" }
```

前端显示"正在为您启动专属环境……"

```
POST /api/instance/start
Authorization: Bearer <JWT>
→ 中控服务解码 JWT → user_id=3
→ 调用云 API 启动用户 3 的容器
→ 容器启动后：
    1. 从 PG 读取用户 3 的 boss_accounts（CDP 端口、Cookies）
    2. 启动 Chrome → 注入 Cookies → BOSS 自动登录
    3. 注册到路由表
→ 返回 { "status": "running", "dashboard_url": "/dashboard" }
```

## 五、第四步：使用驾驶舱

```
                        用户访问 /dashboard
                              │
                    JWT 中 user_id = 3
                              │
              ┌───────────────┴───────────────┐
              │  用户 3 的专属容器              │
              │                               │
              │  加载 index.html 驾驶舱         │
              │                               │
              │  所有 API 调用自动带 JWT        │
              │  API 从 JWT 取 user_id = 3    │
              │                               │
              │  SELECT * FROM candidates      │
              │  WHERE user_id = 3  ←─── 只看到自己的数据
              │                               │
              │  INSERT INTO contact_records   │
              │  (boss_id, action, ..., user_id)│
              │  VALUES (..., 3)               │
              └───────────────────────────────┘
```

## 六、数据如何绑定 user_id

### 所有业务表统一加 `user_id`

```sql
candidates.user_id        → 这个候选人是谁发现的
contact_records.user_id   → 这次联系是谁操作的
resume_operations.user_id → 这次简历操作是谁做的
conversations.user_id     → 这条对话是谁产生的
chat_sessions.user_id     → 这个会话属于谁
runtime_state.user_id     → 这份配置是谁的
```

### 写入时自动注入 user_id

```python
# API 层面统一处理（FastAPI 中间件或 decorator）
def get_current_user():
    token = request.headers["Authorization"]
    payload = jwt.decode(token)
    return payload["user_id"]  # 3

# 每个端点自动注入
@app.post("/api/filter/contact")
def start_filter(req, current_user=Depends(verify_token)):
    user_id = current_user["user_id"]  # 3

    INSERT INTO candidates (boss_id, candidate_name, user_id, ...)
    VALUES ('abc123', '张三', 3, ...)
    #                         ↑ 自动绑定
```

### 读取时自动过滤 user_id

```python
@app.get("/api/candidates")
def list_candidates(current_user=Depends(verify_token)):
    user_id = current_user["user_id"]

    SELECT * FROM candidates WHERE user_id = 3
    #                                     ↑ 只看自己的

    # 张三看不到李四的候选人
```

## 七、数据库完整结构（多租户改造后）

```
users
├─ id (PK)
├─ username
├─ password_hash
├─ role (admin / user)
└─ is_active

boss_accounts
├─ id (PK)
├─ user_id (FK → users.id)  ← 绑定用户
├─ cdp_host, cdp_port, cookies_file
└─ is_default

candidates
├─ id (PK)
├─ user_id  ← 新增，绑定发现该候选人的用户
├─ boss_id, candidate_name, ...

contact_records
├─ id (PK)
├─ user_id  ← 新增
├─ boss_id, action, ...

resume_operations
├─ id (PK)
├─ user_id  ← 新增
├─ boss_id, candidate_name, action, ...

conversations
├─ id (PK)
├─ user_id  ← 新增
├─ candidate_name, ai_message, ...

runtime_state
├─ key + user_id (联合PK) ← 改造
├─ value
└─ updated_at

chat_sessions
├─ id (PK)
├─ user_id  ← 新增
├─ boss_id, candidate_name, ...
```

## 八、页面架构总览

```
boss.xxx.com
├─ /login          登录/注册页      (公开，任何人可访问)
├─ /register       注册表单          (公开)
├─ /admin          管理后台          (仅 admin 角色)
│   ├─ 用户列表（增删改禁用）
│   ├─ 实例监控（谁在跑、谁停了）
│   └─ 用量统计（每人每日联系数/简历数）
└─ /dashboard      驾驶舱           (所有登录用户)
    ├─ 浏览器控制（打开 BOSS/VNC/登录检测）
    ├─ F5 筛选+打招呼
    ├─ F6 批量获取简历
    ├─ F7 批量回复
    ├─ F8 下载已获取简历
    ├─ 🤖 AI分析简历
    ├─ 💼 批量约面试
    ├─ 筛选条件配置
    ├─ 话术模板
    ├─ 岗位模板
    └─ VNC 远程桌面
```

## 九、实施顺序

| 步骤 | 内容 | 说明 |
|------|------|------|
| 1 | 所有业务表加 `user_id` 列 + 索引 | 数据库层数据隔离 |
| 2 | 所有 API 读写加 `WHERE user_id = %s` | 代码层数据隔离 |
| 3 | 拆分前端为 login / admin / dashboard | 三个独立页面 |
| 4 | 中控服务：注册 + 登录 + 容器管理 | 核心枢纽 |
| 5 | Nginx 反向代理配置 | 按租户路由 |
| 6 | 云 API 集成 + 自动休眠 | 按需启停 |
