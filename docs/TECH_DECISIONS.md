# 技术决策记录

> 版本: 1.0 | 日期: 2026-06-04 | 状态: 已确认

---

## TD-001: 浏览器自动化操控层选型

### 背景

系统需要操控 Docker 容器内的 Chromium 浏览器，完成 BOSS直聘的自动化操作（打招呼、获取简历、AI对话）。

### 决策驱动因素

| 因素 | 优先级 | 说明 |
|------|--------|------|
| **反检测** | P0 | BOSS直聘能检测到 Playwright/Puppeteer 的 `navigator.webdriver` 标记，导致账号风控。**反对的是"被检测到自动化"这个结果**，而非某个特定库 |
| **VNC 真实可见** | P0 | 用户必须在 noVNC 中看到真实的浏览器操作画面，用于监控和人工干预 |
| **Docker 统一环境** | P0 | 跨平台一致运行，避免本地环境差异 |
| **DOM 级精确操控** | P1 | 需要精确定位按钮、输入框、弹窗等元素，不能依赖坐标估算 |

### 技术约束

- 反对的是 **"被检测到自动化"的结果**，不是 "Playwright 这个库" 本身
- 操控层必须在 Docker 容器内连接 **真实系统 Chrome**（非 Playwright 自带的 patched Chromium）
- noVNC 是「眼睛」（看），操控层是「手」（做），两者不冲突

### 评估方案

#### 方案 A: CDP 直连真实 Chrome（Playwright connect_over_cdp）

- **原理**: 启动真实 Chrome `--remote-debugging-port=9222`，用 Playwright 的 `connect_over_cdp()` 连接
- **反检测**: ✅ 好（真实 Chrome，无 webdriver 标记）
- **精确度**: ✅ DOM 级
- **复杂度**: 低
- **已有代码**: `app/browser_manager.py` 已实现此模式
- **风险**: Playwright 连接时可能注入可检测的运行时属性

#### 方案 B: nodriver（纯 Python CDP 客户端）✅ 已选

- **原理**: `nodriver` 是 `undetected-chromedriver` 的继任者，纯 Python 封装 CDP 协议连接真实 Chrome，内置反检测
- **反检测**: ✅✅ 最强（专为反检测设计，无 Selenium/Playwright 运行时注入）
- **精确度**: ✅ DOM 级（完整 CDP 协议访问）
- **复杂度**: 低（API 类似 Playwright）
- **依赖**: 纯 Python，无 Node.js 依赖
- **已有代码**: `requirements.txt` 中已包含 nodriver 依赖（之前未使用）

#### 方案 C: Selenium + undetected-chromedriver

- **反检测**: ⚠️ 一般（BOSS直聘可能已识别 uc 特征）
- **精确度**: ✅ DOM 级
- **淘汰原因**: Selenium 生态重，undetected-chromedriver 更新滞后于 Chrome 版本

#### 方案 D: 纯 X11 自动化（xdotool/pyautogui + Tesseract OCR）

- **反检测**: ✅✅✅ 完美（纯操作系统层操作，浏览器完全无感知）
- **精确度**: ❌ 脆弱（依赖坐标和 OCR，分辨率/UI 变化就失效）
- **已有代码**: `app/screen.py` + `app/vision.py`
- **淘汰原因**: 维护成本高，BOSS 改版 UI 就需要重新调坐标

#### 方案 E: CDP + X11 混合

- **主用 CDP 精确操控，X11/OCR 作为 fallback**
- **可作为 B 的未来增强方向**，但初期不引入混合复杂度

### 决策

**选定方案 B: nodriver**

### 理由

1. **反检测最强**: nodriver 是专为绕过浏览器自动化检测设计的，无 Playwright/Selenium 运行时注入
2. **纯 Python**: 不依赖 Node.js 生态，降低 Docker 镜像体积和构建复杂度
3. **DOM 级精确**: 通过 CDP 协议可精确定位元素，不依赖坐标/OCR
4. **VNC 兼容**: 连接的是真实 Chrome 进程，在 VNC 桌面中完全可见
5. **已有依赖**: `requirements.txt` 中已有 nodriver，无需新增依赖

### 最终技术栈

```
┌─────────────────────────────────────────────────────────┐
│  Web Dashboard (http://localhost:8321)                   │
│  ┌────────────────────┬──────────────────────────┐     │
│  │  noVNC 远程桌面     │  控制面板 (FastAPI API)   │     │
│  │  (VNC → WebSocket) │  连接/打开/打招呼/简历/聊天 │     │
│  └────────┬───────────┴──────────┬───────────────┘     │
└───────────┼──────────────────────┼─────────────────────┘
            │                      │
┌───────────▼──────────────────────▼─────────────────────┐
│  Docker 容器                                            │
│  ┌─────────────────────────────────────────────────┐   │
│  │  XFCE Desktop + TigerVNC                        │   │
│  │  ┌─────────────────────────────────────────┐    │   │
│  │  │  真实 Chromium (系统安装)                  │    │   │
│  │  │  --remote-debugging-port=9222            │    │   │
│  │  └──────────────────┬──────────────────────┘    │   │
│  │                     │ CDP 协议                    │   │
│  │  ┌──────────────────▼──────────────────────┐    │   │
│  │  │  Python 后端 (FastAPI + nodriver)         │    │   │
│  │  │  - 启动/连接真实 Chrome                    │    │   │
│  │  │  - DOM 级元素操控（点击/输入/截图）         │    │   │
│  │  │  - 反检测内置                             │    │   │
│  │  │  - DeepSeek AI 对话                       │    │   │
│  │  └──────────────────────────────────────────┘    │   │
│  │  supervisord: vnc + xfce + novnc + api + web     │   │
│  └─────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**技术栈**: Docker + Python(FastAPI) + noVNC + **nodriver** + SQLite + DeepSeek API

### 影响范围

| 变更项 | 说明 |
|--------|------|
| 移除 Playwright 依赖 | `requirements.txt` 删除 `playwright`，Dockerfile 不再 `playwright install chromium` |
| 移除 `app/browser_manager.py` | 基于 Playwright 的浏览器管理器，改用 nodriver 重写 |
| 保留 `app/screen.py` + `app/vision.py` | 作为备用/调试工具，不作为主操控路径 |
| 保留 `app/workflows.py` | 业务逻辑不变，底层调用从 Playwright API 改为 nodriver API |
| Dockerfile 简化 | 不需要 Playwright Chromium，使用系统 Chromium 即可 |
| `app/api.py` 浏览器端点 | `/api/browser/*` 系列端点改用 nodriver 实现 |

### 未来可选增强

- ~~**TD-001-E**: 如 nodriver 偶尔遇到无法定位的元素，可引入 X11/OCR 作为 fallback（方案 E 的混合思路）~~ → 已被 TD-004 替代

---

## TD-004: 仿真人类鼠标操作

### 背景

nodriver 默认通过 CDP 协议直接在 DOM 元素上触发 click 事件——没有鼠标移动过程、VNC 里看不到光标移动、mousemove 事件链缺失。存在两个问题：

1. **反检测风险**: BOSS直聘如果做了行为分析（检测 mousemove 事件），纯 click 会被标记
2. **VNC 体验差**: 光标不移动，画面一帧一帧跳变，不像真人在操作

### 评估方案

| 方案 | 做法 | VNC 可见光标移动 | 反检测 | 复杂度 |
|------|------|:---:|:---:|:---:|
| **B1. nodriver + CDP 仿真** | nodriver 定位 → CDP `Input.dispatchMouseEvent` 注入事件链 | ❌ | ✅ | 中 |
| **B2. nodriver + xdotool** ✅ | nodriver 获取坐标 → xdotool bezier 移动系统光标 → 点击 | ✅ | ✅✅ | 高 |

### 决策

**选定方案 B2: nodriver 定位 + xdotool 仿真移动**

### 操控流程

```
1. nodriver 通过 CSS 选择器定位元素
   element = page.select('.candidate-card')
   box = element.bounding_box()  → {x: 450, y: 320, width: 200, height: 60}

2. 计算目标坐标（元素中心 + 随机偏移，避免每次点同一像素）
   target_x = box.x + box.width/2  + random(-5, 5)
   target_y = box.y + box.height/2 + random(-5, 5)

3. Python 生成贝塞尔曲线路径（3-5个控制点，模拟人类不完美直线）
   path = bezier_curve(current_pos, target, control_points=4)

4. xdotool 沿路径移动系统光标（每步 10-30ms，总耗时 200-500ms）
   for point in path:
       subprocess.run(['xdotool', 'mousemove', '--sync', str(x), str(y)])

5. xdotool 点击
   subprocess.run(['xdotool', 'click', '1'])

6. 随机等待（200-600ms，模拟人类反应时间）
   time.sleep(random.uniform(0.2, 0.6))
```

### 输入仿真

| 操作 | 实现方式 | 仿真效果 |
|------|---------|---------|
| **点击** | xdotool 贝塞尔移动 + `xdotool click 1` | 光标沿曲线移动 → 点击 |
| **双击** | xdotool 移动 + `xdotool click --repeat 2 --delay 100 1` | 光标移动 → 两次点击（间隔100ms） |
| **输入文字** | `xdotool type --delay 50-150 "text"` | 逐字符输入，随机键间隔 |
| **滚动** | `xdotool click 4/5` 或 `xdotool key Down/Up` | 页面滚动 |
| **快捷键** | `xdotool key ctrl+a` 等 | 组合键操作 |
| **等待元素** | nodriver `page.wait_for(selector, timeout=10)` | 精确等待 DOM 元素出现 |

### 为什么这个组合最强

| 层 | 技术 | 贡献 |
|----|------|------|
| **定位层** | nodriver | DOM 级精确查找元素（CSS 选择器），获取坐标 |
| **执行层** | xdotool | 系统级光标移动 + 点击 + 输入，完全绕过浏览器 API |
| **浏览器** | 真实 Chromium | 无 `navigator.webdriver` 标记 |
| **视觉层** | VNC + noVNC | 用户看到真实光标在移动 |

**反检测链条**: 真实 Chrome（无标记）+ 系统级鼠标（非 CDP 注入）+ 贝塞尔轨迹（非直线）+ 随机延迟（非均匀节奏）= 接近人类操作

### 技术栈更新

新增依赖：
- `xdotool` — Dockerfile 中 `apt-get install xdotool`（已在现有 Dockerfile 中）
- Python 调用方式: `subprocess.run(['xdotool', ...])` — 无需额外 Python 包

### 最终技术栈

```
Docker + supervisord + TigerVNC + XFCE4 + noVNC + Chromium(真实)
+ nodriver(DOM定位) + xdotool(仿真鼠标) + FastAPI + SQLite + DeepSeek API
```

---

---

## TD-002: 代码重整策略

### 决策

**先清理归档，再基于 nodriver 重写核心模块。** 旧代码归档到统一目录，不做选择性保留。

### 理由

1. 现有代码审计发现 6 处严重问题（坏掉的入口、不存在的 import、Dockerfile 路径全错）
2. 3 个版本的简历收集器 + 6 处各自为政的数据库访问 = 技术债已无法增量修补
3. 核心操控层从 Playwright 换 nodriver，底层 API 完全不同，保留旧代码只会造成混乱
4. 归档而非删除，保留历史可追溯

### 归档方案

所有旧代码移入 `_archive/` 目录：

```
_archive/
├── boss_rpa/                    # 旧 RPA 包（已废弃）
├── app_old/                     # 旧 app 模块
│   ├── browser_manager.py       # 基于 Playwright 的浏览器管理
│   ├── resume_collector.py      # 简历收集 v1.1
│   ├── resume_collector_v2.py   # 简历收集 v2.3
│   ├── communicate_collector.py # 简历收集 v3.0
│   ├── screen.py                # macOS pyautogui
│   ├── screen_linux.py          # Linux pyautogui
│   ├── vision.py                # macOS OCR
│   ├── vision_linux.py          # Linux OCR
│   ├── vision_agent_computer_use.py  # 667行视觉Agent
│   ├── trinity_agents.py        # 三位一体Agent
│   ├── trinity_scheduler.py     # 三位一体调度器
│   └── screen_capture.py        # macOS截图
├── scripts_old/                 # 旧脚本
│   ├── find_buttons*.py         # 3个重复按钮查找
│   ├── build*.sh                # 重复构建脚本
│   └── legacy/                  # 已在legacy中的文件
├── tests_old/                   # 旧测试（基于Playwright）
└── docs_old/                    # 过时文档
```

### 保留不动的文件（作为重写基础）

| 文件 | 理由 |
|------|------|
| `app/config.py` | 配置管理，干净可用 |
| `app/auth.py` | JWT 认证，与操控层无关 |
| `app/logging_config.py` | 日志模块，通用 |
| `app/filter_criteria.py` | 132 校白名单 + `FilterCriteria`，核心业务数据 |
| `app/database.py` | 数据库层（需重整但保留结构） |
| `app/chat_service.py` | AI 对话服务（DeepSeek），与操控层无关 |
| `app/workflows.py` | 业务逻辑骨架（函数签名保留，内部改用 nodriver） |
| `app/api.py` | FastAPI 端点结构（保留路由，改底层调用） |
| `boss.py` | CLI 入口（修复 import 后保留） |
| `templates/index.html` | Dashboard UI |
| `web/index.html` | 管理 Hub UI |
| `config/chat_bot_flow.json` | 对话流配置 |
| `entrypoint.sh` | Docker 启动脚本 |
| `Dockerfile` | 修复路径后保留结构 |
| `docker-compose.yml` | 保留 |

### 执行顺序

1. 创建 `_archive/`，移动旧代码
2. 修复 P0 问题（`__init__.py`、`skill.json`、`boss.py`、`Dockerfile`、`supervisord.conf`）
3. 清理 `requirements.txt`（删无用依赖，确认 nodriver）
4. 基于 nodriver 重写核心操控模块
5. 更新 `app/workflows.py` 和 `app/api.py` 调用新模块
6. 更新文档

---

## 决策确认

- [x] 用户明确选择方案 B (nodriver)
- [x] 反对的是"被检测到自动化"的结果，而非特定库
- [x] 技术栈确认: Docker + Python + noVNC + nodriver
- [x] 代码策略：先清理归档到 `_archive/`，再重写核心模块

---

## TD-003: 重写阶段与 MVP 范围

### 决策

分两阶段，**先证明「能看见、能操控」，再做「业务自动化」**。

### Phase 1: 基础管道（F1-F3）

> 证明：Dashboard 能加载 → VNC 能连 → Chrome 能在容器里打开 zhipin.com

| 功能 | PRD编号 | 说明 |
|------|---------|------|
| Dashboard 加载 | F1 | Web UI 布局：左侧 noVNC + 右侧控制面板 |
| 连接 VNC 远程桌面 | F2 | noVNC 连接 Docker 容器 VNC Server |
| 打开浏览器进 Boss直聘 | F3 | nodriver 启动真实 Chrome → 导航到 zhipin.com |

**Phase 1 完成标志**: 用户打开 Dashboard → 点击连接VNC → 看到桌面 → 点击打开Boss直聘 → VNC 里看到 Chrome 显示 zhipin.com

### Phase 2: 业务自动化（F4-F6）

> 在 Phase 1 基础上叠加自动化能力

| 功能 | PRD编号 | 说明 |
|------|---------|------|
| Boss直聘登录 | F4 | 点击登录按钮 → 扫码/密码登录（需人工介入） |
| 批量主动打招呼 | F5 | 扫描候选人 → 学校白名单筛选 → 批量打招呼 |
| 批量获取简历 + 聊天回复 | F6 | 下载简历 + AI(DeepSeek)多轮对话 |

### 理由

1. F1-F3 是基础管道——VNC 连不上或 Chrome 起不来，后面全白做
2. F4（登录）涉及扫码，需要人工介入验证
3. F5/F6 依赖 nodriver 操控层稳定工作，必须等 Phase 1 验证通过

---

## 技术栈详解

### 组件清单与职责

```
┌─ 用户浏览器 ─────────────────────────────────────────────────┐
│  http://localhost:8321                                        │
│  ┌──────────────────────┬─────────────────────────────────┐ │
│  │  noVNC (JavaScript)  │  控制面板 (HTML/JS)              │ │
│  │  通过 WebSocket 连    │  通过 HTTP 调用 FastAPI 后端      │ │
│  │  接 VNC Server        │                                  │ │
│  └──────────┬───────────┴──────────────┬──────────────────┘ │
└─────────────┼──────────────────────────┼────────────────────┘
              │ WebSocket (:6901)        │ HTTP (:8001)
┌─────────────▼──────────────────────────▼────────────────────┐
│  Docker 容器 (Ubuntu 22.04)                                  │
│                                                              │
│  ┌─ supervisord (进程管理器) ──────────────────────────────┐ │
│  │                                                        │ │
│  │  ┌─ TigerVNC (:5901) ─────────────────────────────┐   │ │
│  │  │  Linux 虚拟帧缓冲 X11 服务器                      │   │ │
│  │  │  提供 DISPLAY=:1 虚拟桌面                         │   │ │
│  │  │  能做: 渲染完整的 Linux 桌面环境                    │   │ │
│  │  └─────────────────────────────────────────────────┘   │ │
│  │                                                        │ │
│  │  ┌─ XFCE4 ────────────────────────────────────────┐   │ │
│  │  │  轻量级桌面环境                                   │   │ │
│  │  │  能做: 任务栏、窗口管理、桌面图标                    │   │ │
│  │  └─────────────────────────────────────────────────┘   │ │
│  │                                                        │ │
│  │  ┌─ noVNC (:6901) ────────────────────────────────┐   │ │
│  │  │  VNC → WebSocket 桥接                            │   │ │
│  │  │  能做: 让用户在浏览器中看到并操作远程桌面            │   │ │
│  │  └─────────────────────────────────────────────────┘   │ │
│  │                                                        │ │
│  │  ┌─ Chromium (系统安装) ───────────────────────────┐   │ │
│  │  │  真实浏览器，在 XFCE 桌面中运行                     │   │ │
│  │  │  启动参数: --remote-debugging-port=9222           │   │ │
│  │  │  能做: 完整的浏览器功能，无自动化标记                │   │ │
│  │  │  反检测: navigator.webdriver = undefined           │   │ │
│  │  └──────────────────┬──────────────────────────────┘   │ │
│  │                     │ CDP 协议 (9222)                    │ │
│  │  ┌──────────────────▼──────────────────────────────┐   │ │
│  │  │  FastAPI (:8001) + nodriver                      │   │ │
│  │  │                                                  │   │ │
│  │  │  nodriver 能做:                                   │   │ │
│  │  │  ✅ 启动/连接真实 Chrome                           │   │ │
│  │  │  ✅ DOM 元素查找（CSS选择器、XPath）                │   │ │
│  │  │  ✅ 点击按钮、填写输入框、选择下拉                   │   │ │
│  │  │  ✅ 页面导航、等待元素加载                          │   │ │
│  │  │  ✅ 截图（用于日志/调试）                           │   │ │
│  │  │  ✅ 执行 JavaScript                               │   │ │
│  │  │  ✅ 监听网络请求/响应                              │   │ │
│  │  │  ✅ 文件下载                                      │   │ │
│  │  │  ✅ Cookie 管理                                   │   │ │
│  │  │  ✅ 多标签页管理                                   │   │ │
│  │  │  ✅ 内置反检测（无 webdriver 标记）                 │   │ │
│  │  │                                                  │   │ │
│  │  │  FastAPI 能做:                                    │   │ │
│  │  │  ✅ REST API 端点（Dashboard 调用）                │   │ │
│  │  │  ✅ JWT 认证                                      │   │ │
│  │  │  ✅ 后台任务（异步执行自动化流程）                   │   │ │
│  │  │  ✅ WebSocket（实时日志推送）                       │   │ │
│  │  └──────────────────────────────────────────────────┘   │ │
│  │                                                        │ │
│  │  ┌─ SQLite ───────────────────────────────────────┐   │ │
│  │  │  候选人、对话记录、运行状态、筛选配置               │   │ │
│  │  │  能做: 轻量级持久化，无需数据库服务                 │   │ │
│  │  └─────────────────────────────────────────────────┘   │ │
│  │                                                        │ │
│  │  ┌─ http.server (:3001) ──────────────────────────┐   │ │
│  │  │  静态文件服务，提供 web/index.html                │   │ │
│  │  └─────────────────────────────────────────────────┘   │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
         │ HTTP
         ▼
    DeepSeek API (外部)
    能做: AI 生成招聘对话回复
```

### 每个技术为什么选它

| 技术 | 选它的理由 | 它能做的事 | 它做不到的事 |
|------|-----------|-----------|-------------|
| **Docker** | 统一环境，一次构建到处运行；隔离宿主机 | 封装完整 Linux 桌面 + 浏览器 + Python 环境；`docker-compose up` 即可启动全部服务 | — |
| **supervisord** | Docker 内多进程管理（VNC+XFCE+noVNC+API+Web 需要同时运行） | 按优先级启动多个进程；自动重启崩溃进程；统一日志 | — |
| **TigerVNC** | 轻量级 X11 VNC 服务器，Docker 生态成熟 | 提供 `DISPLAY=:1` 虚拟桌面；渲染 GUI 应用 | 不提供桌面环境本身（需 XFCE） |
| **XFCE4** | 最轻量级的 Linux 桌面，Docker 友好 | 任务栏、窗口管理、右键菜单、文件管理器 | — |
| **noVNC** | 浏览器内 VNC 客户端，无需安装任何软件 | 将 VNC 画面通过 WebSocket 传输到网页；用户可在浏览器中操作远程桌面 | 延迟比原生 VNC 客户端略高 |
| **Chromium（系统安装）** | 真实浏览器，无自动化补丁，BOSS直聘无法检测 | 完整浏览器功能；渲染 zhipin.com；支持 CDP 调试端口 | — |
| **nodriver** | `undetected-chromedriver` 继任者，纯 Python，专为反检测设计 | 连接真实 Chrome；DOM 操作；截图；下载文件；Cookie 管理；**无 `navigator.webdriver` 标记** | 不提供浏览器本身（需要系统安装 Chrome） |
| **FastAPI** | Python 最快的异步 Web 框架，自带 OpenAPI 文档 | REST API；JWT 认证；后台任务；依赖注入；自动生成 `/docs` | — |
| **SQLite** | 零配置数据库，无需额外服务 | 候选人/对话/状态的持久化存储；SQL 完整功能 | 高并发写入（本项目不需要） |
| **DeepSeek API** | 性价比最高的中文 AI API | 根据候选人消息生成智能回复；多轮对话上下文 | 需要网络连接；有 API 费用 |

### 技术栈组合能做到什么

| PRD 功能 | 实现路径 | 涉及技术 |
|----------|---------|---------|
| **F1: Dashboard 加载** | `web/index.html` 由 http.server 提供；noVNC iframe 嵌入 | Docker, noVNC, http.server |
| **F2: 连接 VNC** | noVNC JS 客户端 → WebSocket → TigerVNC | noVNC, TigerVNC, XFCE |
| **F3: 打开 Boss直聘** | FastAPI 端点 → nodriver 启动 Chrome → `page.goto('zhipin.com')` | FastAPI, nodriver, Chromium |
| **F4: 登录** | nodriver 点击登录按钮 → 用户在 VNC 中扫码 | nodriver, noVNC |
| **F5: 批量打招呼** | nodriver 遍历候选人列表 → CSS 选择器定位按钮 → 学校白名单匹配 → 点击打招呼 | nodriver, FastAPI, SQLite, filter_criteria |
| **F6a: 获取简历** | nodriver 下载 PDF + 换微信按钮 | nodriver, FastAPI, SQLite |
| **F6b: AI 对话** | 读取候选人消息 → DeepSeek 生成回复 → nodriver 发送 | DeepSeek API, nodriver, FastAPI |

### 技术栈组合做不到什么（坦诚说明）

| 限制 | 说明 | 应对 |
|------|------|------|
| BOSS直聘改版 UI | CSS 选择器失效 | 选择器配置化，方便更新；加截图日志便于调试 |
| BOSS直聘加强反爬 | 行为分析（操作频率、鼠标轨迹） | 操作间加随机延迟；模拟人类操作节奏 |
| 高并发 | SQLite 单写 | 本项目单用户场景，不需要 |
| VNC 画面延迟 | noVNC 通过 WebSocket 传输，有 ~100-200ms 延迟 | 可接受，非实时游戏场景 |

---

## 最终确认的完整意图

| 维度 | 内容 |
|------|------|
| **目标** | BOSS直聘自动化招聘系统：Web Dashboard 操控 Docker 内真实 Chrome，完成打招呼/简历/对话 |
| **用户** | 招聘人员（浏览器访问 Dashboard，VNC 中监控自动化过程） |
| **技术栈** | Docker + supervisord + TigerVNC + XFCE4 + noVNC + Chromium(真实) + nodriver(DOM定位) + xdotool(仿真鼠标) + FastAPI + SQLite + DeepSeek API |
| **操控方式** | nodriver 精确定位元素坐标 → Python 生成贝塞尔曲线 → xdotool 移动系统光标 → 点击/输入。VNC 中可见光标移动轨迹 |
| **为什么现在** | 现有代码技术债过重（6处P0、3版本简历收集器、Playwright反检测风险） |
| **成功标准** | PRD F1-F6 全部验收通过，VNC 可见仿真人类操作，不被检测 |
| **约束** | Docker 部署；反检测硬约束；仿真鼠标操作 |
| **不做** | 不做 Playwright；不做纯 X11/OCR（无DOM精度）；不做 macOS 独占；不做瞬移式点击 |
| **执行** | 归档旧代码 → P0 修复 → Phase 1（F1-F3 基础管道）→ Phase 2（F4-F6 业务自动化） |

### 决策确认清单

- [x] TD-001: 选定 nodriver 作为操控层（方案 B），反对的是"被检测到自动化"的结果
- [x] TD-002: 先清理归档旧代码到 `_archive/`，再重写核心模块
- [x] TD-003: 分两阶段，Phase 1（F1-F3 基础管道）→ Phase 2（F4-F6 业务自动化）
- [x] TD-004: 选定仿真鼠标方案 B2（nodriver 定位 + xdotool 贝塞尔移动），VNC 中可见光标轨迹
- [x] 用户已确认以上完整声明 ✅ (2026-06-04)
