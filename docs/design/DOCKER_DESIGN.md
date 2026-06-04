# BOSS直聘三位一体系统 - Docker部署方案

## 架构设计

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Compose                        │
│                                                         │
│  ┌─────────────────┐    ┌─────────────────────────────┐  │
│  │   Web管理界面    │    │      自动化容器（每个客户一个）  │  │
│  │   (React + API) │    │                             │  │
│  │                 │    │  ┌───────┐  ┌─────────────┐ │  │
│  │  - 查看状态      │◄──►│  │Chrome │  │  Ubuntu     │ │  │
│  │  - 启动/停止    │    │  │浏览器  │  │  + Python   │ │  │
│  │  - 查看日志      │    │  │       │  │  + PyAutoGUI│ │  │
│  │  - 配置参数      │    │  └──┬──┘  └──────┬──────┘ │  │
│  │                 │    │     │              │        │  │
│  │  端口: 3001     │    │  ┌──┴──────────────┴──┐    │  │
│  └─────────────────┘    │  │     VNC Server      │    │  │
│                           │  │  (远程桌面访问)      │    │  │
│                           │  │                     │    │  │
│                           │  │  端口: 5901         │    │  │
│                           │  └─────────────────────┘    │  │
│                           │                               │  │
│                           │  端口: 5901 (VNC)            │  │
│                           │       6901 (noVNC Web)       │  │
│                           └───────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## 技术栈

| 组件 | 技术 | 用途 |
|------|------|------|
| **基础镜像** | Ubuntu 22.04 | 操作系统 |
| **浏览器** | Chrome + ChromeDriver | 自动化操作 |
| **Python** | 3.10 + PyAutoGUI | 脚本执行 |
| **桌面环境** | XFCE4 | 轻量级桌面 |
| **VNC** | TigerVNC | 远程桌面 |
| **Web VNC** | noVNC | 浏览器访问桌面 |
| **Web管理** | React + FastAPI | 管理界面 |

## 部署步骤

### 1. 构建Docker镜像

```bash
docker build -t boss-recruitment-pro .
```

### 2. 启动容器

```bash
docker-compose up -d
```

### 3. 访问界面

| 服务 | 地址 | 说明 |
|------|------|------|
| Web管理 | http://localhost:3001 | 管理系统 |
| noVNC | http://localhost:6901 | 浏览器访问桌面 |
| VNC | localhost:5901 | VNC客户端访问 |

## 客户使用流程

### 1. 管理员创建客户账号

```bash
curl -X POST http://localhost:3001/api/customers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "客户A",
    "email": "customer@example.com",
    "max_instances": 1
  }'
```

### 2. 系统自动创建Docker容器

```
客户A → 创建容器 boss-recruitment-customer-a
       → 启动Chrome + VNC
       → 分配端口: 5901, 6901
```

### 3. 客户通过Web界面操作

```
1. 登录Web管理界面
2. 点击"启动浏览器"
3. 通过noVNC看到Chrome界面
4. 登录BOSS直聘
5. 点击"开始自动化"
6. 系统串行执行: 打招呼 → 获取简历 → AI对话
```

## 文件结构

```
docker/
├── Dockerfile                    # Docker镜像定义
├── docker-compose.yml           # 多容器编排
├── entrypoint.sh                # 容器启动脚本
├── supervisord.conf             # 进程管理
└── nginx.conf                   # Web代理

app/
├── web/                         # Web管理界面
│   ├── src/
│   │   ├── pages/
│   │   │   ├── Dashboard.tsx   # 主面板
│   │   │   ├── Instances.tsx   # 实例管理
│   │   │   └── VNCViewer.tsx   # VNC查看器
│   │   └── api/
│   │       └── index.ts        # API接口
│   └── package.json
│
└── api/                         # 后端API
    ├── main.py                  # FastAPI入口
    ├── docker_manager.py        # Docker管理
    └── vnc_manager.py         # VNC管理
```

## 核心代码

### Dockerfile

```dockerfile
FROM ubuntu:22.04

# 安装依赖
RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    google-chrome-stable \
    xfce4 xfce4-terminal \
    tigervnc-standalone-server tigervnc-viewer \
    novnc websockify \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# 安装Python包
RUN pip3 install pyautogui opencv-python numpy pillow

# 复制代码
COPY app/ /app/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 暴露端口
EXPOSE 5901 6901 8001

ENTRYPOINT ["/entrypoint.sh"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  web:
    build: .
    ports:
      - "3001:3001"
      - "5901:5901"
      - "6901:6901"
    environment:
      - CUSTOMER_ID=default
      - VNC_PASSWORD=boss123
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped
```

## 批量交付

### 交付包内容

```
boss-recruitment-pro-v1.0/
├── docker-compose.yml          # 一键启动
├── Dockerfile                  # 镜像定义
├── config/
│   └── settings.yaml          # 配置
├── data/                       # 数据目录
├── logs/                       # 日志目录
└── README.md                   # 使用说明
```

### 客户部署

```bash
# 1. 解压交付包
tar -xzf boss-recruitment-pro-v1.0.tar.gz
cd boss-recruitment-pro-v1.0

# 2. 启动系统
docker-compose up -d

# 3. 访问界面
# Web管理: http://localhost:3001
# noVNC: http://localhost:6901
```

## 监控

| 指标 | 说明 |
|------|------|
| 容器状态 | 运行中/已停止 |
| CPU使用率 | 容器CPU占用 |
| 内存使用 | 容器内存占用 |
| 自动化进度 | 当前步骤/总步骤 |
| 成功率 | 打招呼/简历/对话 |

## 安全

| 措施 | 说明 |
|------|------|
| 容器隔离 | 每个客户独立容器 |
| VNC密码 | 随机生成，客户独享 |
| 数据加密 | 数据库加密存储 |
| 访问控制 | JWT认证 |

---

> **轩辕在此。** 🔧
