# BOSS直聘招聘自动化系统 — 环境配置手册

## 硬件要求

| 项目 | 最低配置 | 推荐配置 |
|------|---------|---------|
| CPU | 4核 | 8核 |
| 内存 | 8GB | 16GB+ |
| 磁盘 | 20GB 可用 | 50GB SSD |
| 操作系统 | Windows 10+ / macOS / Linux | Windows 11 |
| 网络 | 可访问 api.deepseek.com | — |

---

## 一、Docker 环境（推荐，生产运行）

### 1.1 安装 Docker Desktop

**Windows:**
```
https://www.docker.com/products/docker-desktop/
```
下载安装包，一路下一步。安装完成后重启电脑。

验证安装：
```bash
docker --version
docker-compose --version
```

**Linux (Ubuntu):**
```bash
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
# 重新登录使权限生效
```

### 1.2 项目文件结构

```
boss-recruitment-system-main/
├── app/                    # 后端代码（volume 挂载，修改实时生效）
│   ├── api.py              # FastAPI 路由
│   ├── automation.py       # 浏览器自动化（nodriver CDP）
│   ├── auth.py             # JWT 鉴权
│   ├── chat_nav.py         # 聊天页导航/联系人提取/消息提取
│   ├── chat_service.py     # AI 回复生成
│   ├── chat_workflow.py    # F7 批量AI回复
│   ├── resume_collector.py # F6 简历采集
│   ├── workflows.py        # F5 主动打招呼
│   ├── database.py         # SQLite 操作
│   ├── filter_criteria.py  # 筛选条件
│   └── config.py           # 配置读取
├── templates/
│   └── index.html          # Dashboard 前端
├── web/                    # Hub 总台
├── job_info/
│   └── company_profile.txt # 公司/岗位背景（注入 AI prompt）
├── config/
│   └── supervisord.conf
├── data/                   # 持久化数据（volume 挂载）
│   ├── boss_recruitment.db
│   ├── chrome-profile/     # Chrome 用户数据（含登录态）
│   └── resumes/            # 下载的简历文件
├── .env                    # 环境变量（API Key 等）
├── docker-compose.yml
├── Dockerfile
├── entrypoint.sh
├── requirements.txt
└── boss.py
```

### 1.3 配置 .env 文件

在项目根目录创建 `.env`：

```env
# ========== DeepSeek AI（必填）==========
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# ========== 数据库 ==========
DATABASE_PATH=data/boss_recruitment.db

# ========== 每日上限 ==========
DAILY_CONTACT_CAP=80        # 每天最多打招呼人数
DAILY_CHAT_ROUNDS_CAP=5     # 每人每天最多对话轮次

# ========== 下载目录 ==========
DOWNLOAD_DIR=~/Downloads
```

> **注意：** `.env` 中的 `DEEPSEEK_API_KEY` 是敏感信息，不要提交到 Git。已加入 `.gitignore`。

### 1.4 配置 company_profile.txt

在 `job_info/company_profile.txt` 中写入公司/岗位背景，这段文本会**自动注入到 AI 的 system_prompt**：

```
公司名称：鲲界科技
主营业务：AI智能量化交易系统研发
招聘岗位：技术合伙人
岗位要求：全栈开发能力，熟悉Python/Go，有金融系统经验优先
岗位亮点：股权激励、远程办公、技术驱动
```

### 1.5 启动服务

```bash
# 进入项目目录
cd boss-recruitment-system-main

# 构建并启动（首次需要构建，约5-10分钟）
docker-compose up -d --build

# 后续启动（代码修改后重启即可，volume 挂载无需重新构建）
docker-compose restart

# 查看日志
docker logs -f boss-recruitment-pro

# 停止
docker-compose down
```

### 1.6 端口说明

| 端口 | 用途 | 访问地址 |
|------|------|---------|
| 8321 | Dashboard 控制面板 | http://localhost:8321 |
| 3101 | Hub 总台 | http://localhost:3101 |
| 6901 | noVNC 远程桌面 | http://localhost:6901/vnc.html |
| 8002 | API 服务 | http://localhost:8002/docs |
| 5901 | VNC（本地客户端用） | localhost:5901 |

### 1.7 首次使用流程

1. 打开浏览器访问 `http://localhost:8321`（Dashboard）
2. 在 Dashboard 中点击"打开远程桌面"，进入 noVNC
3. 在 VNC 桌面的 Chrome 中打开 BOSS直聘并**扫码登录**
4. 回到 Dashboard，点击"启动浏览器"连接自动化
5. 测试各项功能：打招呼(F5) / 获取简历(F6) / 批量回复(F7)

### 1.8 常见问题

**Q: Chrome 启动失败 / 僵尸进程？**
```bash
docker exec boss-recruitment-pro bash -c '
rm -f /app/data/chrome-profile/SingletonLock
google-chrome --remote-debugging-port=9222 --no-sandbox \
  --disable-dev-shm-usage --disable-gpu \
  --user-data-dir=/app/data/chrome-profile about:blank &
'
```

**Q: 容器重启后节点失联？**
在 Dashboard 点击"启动浏览器"重新连接即可，F6/F7 任务内部也会自动重连。

**Q: 修改代码后如何生效？**
`app/`、`templates/`、`job_info/` 都通过 volume 挂载，执行 `docker-compose restart` 即可。

---

## 二、Conda 环境（本地开发/调试）

### 2.1 安装 Miniconda

**Windows:**
```
https://docs.conda.io/en/latest/miniconda.html
```
下载 Windows 安装包，安装时勾选"Add to PATH"。

**验证：**
```bash
conda --version
```

### 2.2 创建环境

```bash
# 创建 Python 3.10 环境
conda create -n boss-recruit python=3.10 -y

# 激活环境
conda activate boss-recruit

# 安装依赖
cd boss-recruitment-system-main
pip install -r requirements.txt
```

### 2.3 本地开发说明

Docker 外的本地开发主要用于：
- 编写和调试 JS 提取脚本（`test_llm.py`、`test_batch_reply.py`）
- 测试 DeepSeek API 调用
- 快速验证消息提取逻辑

**本地运行测试脚本（需要先在 Docker 中启动服务）：**

```bash
conda activate boss-recruit

# 单次消息提取 + AI 回复测试
python test_llm.py

# 批量回复流程测试
python test_batch_reply.py
```

测试脚本通过 `http://localhost:8002/api/browser/*` 调用 Docker 内的浏览器自动化服务。

### 2.4 环境变量（本地）

本地运行测试脚本时需要设置：

**Windows PowerShell:**
```powershell
$env:DEEPSEEK_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"
```

**Windows CMD:**
```cmd
set DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

**Linux/macOS:**
```bash
export DEEPSEEK_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"
```

---

## 三、API 认证

系统使用 JWT Bearer Token 认证，所有 `/api/*` 接口（除了 `/health` 和 `/api/auth/login`）都需要携带 token。

### 获取 token
```bash
curl -X POST http://localhost:8002/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"boss-recruit-2026"}'
```

### 使用 token
```bash
curl http://localhost:8002/api/stats \
  -H "Authorization: Bearer <token>"
```

### 修改密码

在 `docker-compose.yml` 中修改环境变量：
```yaml
environment:
  - API_USERNAME=admin
  - API_PASSWORD=你的强密码
```

---

## 四、目录权限

| 目录 | 用途 | 权限要求 |
|------|------|---------|
| `data/` | SQLite DB、Chrome profile、下载的简历 | 读写 |
| `logs/` | 应用日志 | 读写 |
| `job_info/` | 公司背景文件 | 只读 |
| `config/` | Supervisor 配置 | 只读 |
| `app/` | 后端源码 | 只读 |
| `templates/` | 前端 Dashboard | 只读 |

---

## 五、快速检查清单

- [ ] Docker Desktop 已安装并运行
- [ ] `.env` 文件包含 `DEEPSEEK_API_KEY`
- [ ] `job_info/company_profile.txt` 已填写公司信息
- [ ] `docker-compose up -d` 启动成功
- [ ] `docker logs boss-recruitment-pro` 显示"系统已启动"
- [ ] 浏览器能打开 `http://localhost:8321`
- [ ] VNC 能连接 `http://localhost:6901/vnc.html`
- [ ] VNC 中 Chrome 已打开 BOSS直聘并扫码登录
- [ ] Dashboard 中"启动浏览器"成功
