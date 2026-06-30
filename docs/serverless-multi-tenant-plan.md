# Serverless 多租户架构实施方案

## 一、目标

每个用户拥有独立的 BOSS 招聘自动化环境，数据隔离，按需启动，闲时销毁，按使用时长计费。

## 二、整体架构

```
                         ┌──────────────────────────────────────┐
                         │          云服务器（常驻）              │
                         │                                      │
  用户访问 ──────────────→│  Nginx 反向代理（入口）              │
  https://boss.xxx.com   │    ↓                                 │
                         │  中控服务                            │
                         │  · 用户认证 + 鉴权                   │
                         │  · 容器生命周期管理                   │
                         │  · 调用云 API 启停容器               │
                         │    ↓                                 │
                         │  PostgreSQL（共享，按 user_id 隔离）   │
                         └──────────────────────────────────────┘
                                          │
                         调用云 API 管理用户容器
                                          │
                         ┌───────────────┴───────────────┐
                         │       云容器服务（按需）        │
                         │                               │
                         │  ┌──────┐ ┌──────┐ ┌──────┐  │
                         │  │用户A  │ │用户B  │ │用户C  │  │
                         │  │容器   │ │容器   │ │容器   │  │
                         │  │Chrome │ │Chrome │ │Chrome │  │
                         │  │CDP    │ │CDP    │ │CDP    │  │
                         │  │驾驶舱 │ │驾驶舱 │ │驾驶舱 │  │
                         │  └──────┘ └──────┘ └──────┘  │
                         │   ↑ 按需启停  ↑               │
                         └───────────────────────────────┘
```

## 三、组件详解

### 3.1 Nginx 反向代理

**位置**：云服务器，常驻运行

**职责**：
- 接收所有外部请求（boss.xxx.com）
- 从请求的 JWT 或子域名中提取租户 ID
- 查路由表找到该用户容器所在的 IP:Port
- 将请求转发到对应容器

**配置示例**：
```nginx
upstream tenant_a { server 10.0.1.10:8001; }
upstream tenant_b { server 10.0.1.11:8001; }

server {
    server_name boss.xxx.com;
    location /api/ {
        # 从 JWT 或请求头提取 tenant_id
        # 动态 set $upstream "tenant_xxx"
        proxy_pass http://$upstream;
    }
}
```

**路由策略**：
1. **子域名方案**：`tenant-a.boss.xxx.com` → 用户 A 容器，简单但需要泛域名证书
2. **JWT 路由方案**：统一入口 `boss.xxx.com`，Nginx 解密 JWT 获取 `user_id`，查 Redis/数据库找对应容器地址

### 3.2 中控服务

**位置**：云服务器，常驻运行（与 Nginx 同机）

**职责**：用户认证、容器生命周期管理、路由表维护

**核心 API**：

| 端点 | 功能 |
|------|------|
| `POST /api/auth/login` | 用户登录 → 返回 JWT（含 user_id） |
| `GET /api/instance/status` | 查询当前用户的容器状态（running / stopped / starting） |
| `POST /api/instance/start` | 启动用户的容器 |
| `POST /api/instance/stop` | 停止用户的容器 |
| `GET /api/admin/instances` | 管理员查看所有实例 |

**容器状态机**：
```
stopped ──→ starting ──→ running
                         running ──→ idle（N分钟无操作）
                         idle ──→ stopped（自动休眠）
                         idle ──→ running（用户继续操作）
```

**核心逻辑（伪代码）**：
```python
async def handle_user_request(tenant_id: str):
    instance = query_instance_status(tenant_id)
    if instance.status == "stopped":
        cloud_api.start_container(tenant_id)       # 调用云 API 启动
        instance.status = "starting"
        poll_until_healthy(tenant_id, timeout=60)  # 等容器就绪
    elif instance.status == "idle":
        instance.last_active = now()               # 恢复活跃
    # 更新路由表 → Nginx 可转发
    update_route(tenant_id, instance.ip, instance.port)
```

### 3.3 用户容器（Docker 镜像）

**镜像内容**（就是现在的 Docker 镜像微调）：
- XFCE + VNC + noVNC（远程桌面）
- Chrome + CDP（BOSS 自动化）
- FastAPI（驾驶舱 API）
- PostgreSQL 客户端（连共享 PG）

**每个容器启动时**：
1. 从共享 PG 读取该用户的配置（筛选条件、话术、Cookies）
2. 初始化 Chrome（注入该用户的 Cookies）
3. 自动登录 BOSS（基于已有 Cookies）
4. 注册到中控服务的路由表
5. → 用户可访问

**容器规格建议**：
- CPU：2 核（Chrome 开一个 tab 够用）
- 内存：4 GB（Chrome + XFCE）
- 存储：2 GB（容器镜像 + 少量用户数据）

### 3.4 共享 PostgreSQL

**数据隔离方式**：所有表已有 `user_id` 字段，查询时加 `WHERE user_id = %s`

**需要改动的表**：
- `users` — 已有，不动
- `boss_accounts` — 已有 `user_id`，不动
- `candidates` — 加 `user_id` 列
- `contact_records` — 加 `user_id` 列
- `chat_sessions` — 加 `user_id` 列
- `resume_operations` — 加 `user_id` 列
- `conversations` — 加 `user_id` 列
- `runtime_state` — 加 `user_id` 列

**查询改写示例**：
```sql
-- 之前
SELECT * FROM candidates WHERE interview_status = 'recommend_interview'
-- 之后
SELECT * FROM candidates WHERE interview_status = 'recommend_interview' AND user_id = %s
```

### 3.5 自动休眠策略

**规则**：连续 N 分钟无 API 请求 → 标记为 idle → 再等 M 分钟 → 调用云 API 停止容器。

**实现**：中控服务维护一个 `last_active` 时间戳表，定时任务每分钟扫描一次，超过阈值的自动停掉。

```
用户最后操作 ──10分钟──→ idle ──30分钟──→ stopped（省钱）
            下次再访问 ←─────── 中控服务拉起容器 ──────
```

## 四、技术选型

| 层 | 选项 1（推荐） | 选项 2 |
|----|--------------|--------|
| **云容器服务** | 阿里云 ECI（弹性容器实例） | 腾讯云 TKE Serverless |
| **反向代理** | Nginx + Lua（OpenResty） | Traefik（自动发现） |
| **中控服务** | FastAPI（复用现有） | Go（更高并发） |
| **容器编排** | 云 API 直接管理 | Kubernetes（重但灵活） |
| **路由存储** | Redis（容器地址映射） | PostgreSQL（简单但慢） |

## 五、用户视角的完整交互流程

```
1. 用户访问 https://boss.xxx.com
   ↓
2. 看到登录页 → 输入账号密码
   ↓
3. 中控服务验证 → 返回 JWT
   ↓
4. 前端调用 GET /api/instance/status
   ↓
5. 中控服务返回 status: "stopped"
   ↓
6. 前端显示"正在启动您的专属环境，预计 30-60 秒……"
   中控服务调用云 API 启动容器
   ↓
7. 容器启动 → 自动注入 Cookies → BOSS 登录 → 注册路由
   ↓
8. 中控服务返回 status: "running" + access_url
   ↓
9. 前端加载驾驶舱界面（指向该用户专属容器）
   ↓
10. 用户正常使用 F5~F9 等功能
   ↓
11. 用户关闭浏览器（不再操作）
   ↓
12. 10 分钟后 → 闲置标记
   30 分钟后 → 中控服务调用云 API 停止容器（省钱）
   ↓
13. 用户下次再访问 → 从步骤 1 重新开始
```

## 六、分阶段实施

| 阶段 | 内容 | 工作量 |
|------|------|--------|
| **Phase 1** | 现有表加 `user_id` 隔离（不影响现有功能） | 1 天 |
| **Phase 2** | 中控服务：用户认证 + 容器状态管理 API | 3 天 |
| **Phase 3** | Nginx 路由层：按租户 ID 转发 | 2 天 |
| **Phase 4** | 云 API 集成：启停容器 + 健康检查 | 2 天 |
| **Phase 5** | 自动休眠（定时器 + 闲置检测） | 2 天 |
| **Phase 6** | 测试 + 灰度迁移 | 3 天 |

## 七、成本估算

以阿里云 ECI 为例（2C4G 规格）：
- 每小时约 ¥0.50
- 假设 10 个用户，每人每天用 4 小时
- 月成本 ≈ 10 × 4 × 30 × 0.50 = ¥600
- 加上常驻 NGINX + 中控 + PG 服务器 ≈ ¥200/月
- **总月成本 ≈ ¥800**

对比现在：一台 4C8G 服务器常驻（不关机）≈ ¥300–500/月，但只能支持 1 个用户。
