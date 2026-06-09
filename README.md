# BOSS 招聘机器人 v3.0

> **nodriver CDP 自动化 · Docker 部署 · Web 驾驶舱 · AI 批量回复**
>
> 自动化 BOSS 直聘全流程: 筛选打招呼 → 简历收集 → AI 智能回复

## 系统架构

```
┌──────────────────────────────────────────────────┐
│               Web 驾驶舱 (:8321)                   │
│  筛选配置 | 话术模板 | 岗位模板 | VNC 远程桌面      │
├──────────────────────────────────────────────────┤
│               API (:8002)                         │
│  /api/greet | /api/resume | /api/chat | /filter   │
├──────────────────────────────────────────────────┤
│          nodriver CDP 自动化 (Chrome :9222)        │
│  CDP 点击 | JS 提取 | 下载拦截 | 事件监听          │
├──────────────────────────────────────────────────┤
│          AI 服务 (DeepSeek API)                    │
│  对话阶段推算 | 冗余检测 | 模板降级                  │
└──────────────────────────────────────────────────┘
```

## 核心功能

### F5 · 筛选打招呼
- 搜索页自动扫描推荐牛人列表
- 学校白名单匹配 (132所 国内外名校)
- 学历/年限/关键词 多维度筛选
- CDP 点击 + confirm 确认对话框

### F6 · 简历收集
- 聊天列表自动扫描联系人
- 未读消息优先排序
- 4 种 Case 检测 (PDF预览/请求弹窗/请求中/沟通不足)
- CDP 下载拦截 + 事件确认
- 逐次坐标提取 + 面板切换验证

### F7 · 批量 AI 回复
- 未读消息自动回复
- 5 阶段对话推算 (early → ready_for_interview)
- 冗余回复检测 (不索要已有简历/微信)
- DeepSeek API 集成 · AI 失败自动降级模板
- 限制弹窗检测 (20+ 关键词)

## 快速开始

```bash
# Docker 部署（推荐）
docker compose up -d

# 访问
open http://localhost:8321   # 驾驶舱
open http://localhost:8000   # noVNC 远程桌面
open http://localhost:3101   # 数据总台

# API 文档
open http://localhost:8002/docs
```

## 端口映射

| 端口 | 服务 | 说明 |
|------|------|------|
| 8321 | Web 驾驶舱 | 一站式控制面板 |
| 8000 | noVNC | 浏览器远程桌面 |
| 8002 | API | FastAPI 后端 |
| 3101 | 数据总台 | 数据面板 + 学校白名单 |
| 9222 | Chrome CDP | nodriver 连接端口 |

## 驾驶舱功能面板

### 浏览器控制
- 🚀 打开BOSS · 🌐 连接桌面 · ✅ 检查登录
- 💾 导出Cookie · 📂 导入Cookie

### 批量自动化
- 👋 筛选+打招呼 (F5) → confirm 对话框确认
- 📄 批量获取简历 (F6) → CDP 下载拦截
- 💬 批量回复未读 (F7) → AI 生成 + 阶段推算

### 配置管理
- 筛选条件: 学历/年限/学校白名单/关键词 — 实时同步
- 话术模板: 打招呼/索要简历/跟进 — 可自定义
- 岗位模板: 岗位问题库 — 保存/删除

### 快捷操作
- 💬 聊天页 · 📋 候选人 — 一键导航
- 📝 弹出文本编辑器 — 大段内容编辑
- 操作日志 — 实时追踪 + 清除/展开

## 测试

```bash
# 全部测试 (156 tests)
./venv/bin/python3 -m pytest tests/test_f6_resume_collection.py \
  tests/test_f7_batch_reply.py tests/test_f7_chat_pipeline.py -v

# 视觉验收静态检查 (88 checks)
python3 tests/run_visual_checks.py -v

# 覆盖率
./venv/bin/python3 -m pytest tests/ \
  --cov=app.resume_collector --cov=app.chat_workflow \
  --cov=app.chat_stage --cov=app.chat_service --cov=app.chat_nav \
  --cov-report=term-missing
```

### 测试覆盖

| 模块 | 测试数 | 覆盖 |
|------|--------|------|
| `test_f6_resume_collection.py` | 55 | JS脚本 + mock流程 + 4Case + 错误路径 |
| `test_f7_batch_reply.py` | 49 | merge历史 + batch流程 + AI降级 + chat_nav |
| `test_f7_chat_pipeline.py` | 38 | 阶段推算 + 冗余检测 + 历史构建 + 关键词 |
| `test_chat_api.py` | 7 | ChatService + API端点 + DB表 |
| `test_resume_endpoints.py` | 4 | 简历CRUD + 统计 |
| `test_greet_button_extraction.py` | 35 | F5 打招呼按钮检测 |
| `test_dc_platform_api.py` | 40+ | 3101 数据总台 |
| `run_visual_checks.py` | 88 | JS脚本完整性 + 关键词 + 导入 |
| **总计** | **278+** | |

### 视觉验收文档

| 文档 | 内容 |
|------|------|
| `docs/tests/f6-f7-test-strategy.md` | 测试策略 + 分层 + 优先级 |
| `docs/tests/f6-resume-collection-visual.md` | F6 11步视觉验收清单 |
| `docs/tests/f7-batch-reply-visual.md` | F7 11步视觉验收清单 |
| `docs/tests/f6-f7-integration-visual.md` | F5→F6→F7 端到端 + 5场景 |
| `docs/tests/cockpit-8321-full-flow-20260609.md` | 驾驶舱 30按钮全流程测试 |

## 项目结构

```
boss-recruitment-system/
├── app/
│   ├── api.py                # FastAPI 后端 (所有端点)
│   ├── automation.py         # nodriver CDP 浏览器自动化核心
│   ├── chat_nav.py           # 聊天页导航 + 消息提取 + 限制弹窗
│   ├── chat_service.py       # DeepSeek AI 回复服务
│   ├── chat_stage.py         # 对话阶段推算 + 冗余检测
│   ├── chat_workflow.py      # F7 批量回复工作流
│   ├── resume_collector.py   # F6 简历收集器
│   ├── filter_criteria.py    # 筛选条件 + 学校白名单 (132所)
│   ├── workflows.py          # 工作流协调
│   ├── database.py           # SQLite 数据库
│   ├── config.py             # 配置管理
│   └── logging_config.py     # 日志配置
├── docs/
│   ├── tests/                # 视觉验收文档 + 截图
│   └── F6_RESUME_WORKFLOW.md # F6 完整流程 + Grill 审查
├── tests/
│   ├── test_f6_resume_collection.py  # F6 测试 (55)
│   ├── test_f7_batch_reply.py        # F7 测试 (49)
│   ├── test_f7_chat_pipeline.py      # 对话阶段测试 (38)
│   ├── run_visual_checks.py          # 静态视觉验收 (88 checks)
│   └── ...
├── scripts/
│   ├── init_filter_config.py  # 筛选配置初始化
│   └── cua_greeting_loop.py   # cua-driver 打招呼
├── data/                      # 数据库 + 简历文件
├── tools/                     # 工具脚本
└── web/                       # 驾驶舱前端
```

## API 端点

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/health` | 健康检查 |
| POST | `/api/greet/batch` | F5 批量打招呼 |
| POST | `/api/resume/batch` | F6 批量获取简历 |
| POST | `/api/chat/batch` | F7 批量AI回复 |
| GET | `/api/chat/history` | 对话历史 |
| POST | `/api/chat/template` | 保存回复模板 |
| GET | `/api/chat/templates` | 获取模板列表 |
| GET | `/api/filter/config` | 获取筛选配置 |
| PUT | `/api/filter/config` | 更新筛选配置 |
| GET | `/api/resume/list` | 简历列表 |
| GET | `/api/resume/stats` | 简历统计 |

## 防检测机制

- nodriver 真实浏览器指纹 (非 Playwright webdriver)
- 随机操作间隔 (1.5-4 秒)
- CDP 底层操作 (非 DOM 事件)
- 模拟人类鼠标轨迹
- macOS 真实 User-Agent

## 常见问题

### Q: 如何启动？
A: `docker compose up -d`，然后打开 http://localhost:8321

### Q: 简历下载到哪里？
A: `data/resumes/` 目录，由 CDP `setDownloadBehavior` 拦截

### Q: 需要 BOSS 账号吗？
A: 需要。在 VNC (8000) 中扫码登录，Cookie 可导出复用

### Q: AI 回复如何配置？
A: 在驾驶舱「话术模板」中自定义，需配置 `DEEPSEEK_API_KEY`

---

*轩辕 · 2026-06-09 · v3.0*
