# BOSS直聘 · 简历获取轮转系统 v2.0

> **纯视觉 + Playwright 混合方案 · 自动下载简历 · 自动换微信 · 轮转到下一个候选人**

## 核心流程

```
点击左侧"沟通"
    │
    ├─ 1. 点击候选人（第一个/下一个）
    │
    ├─ 2. 获取简历
    │      ├─ 深蓝"附件简历" → 弹出PDF预览 → 点"下载" → 关预览
    │      └─ 浅蓝"在线简历"/无 → 点"求简历" → 确认弹窗 → 发送请求
    │
    ├─ 3. 点击"换微信"
    │      └─ 确认弹窗 → 绿色"确认"按钮
    │
    └─ 4. 轮转到下一位候选人
          └─ 重复1-3
```

## 快速开始

```bash
# 1. 安装依赖
pip3 install -r requirements.txt
python3 -m playwright install chromium

# 2. 运行（推荐方式 - 有界面模式）
python3 main.py --limit 10

# 3. 调试模式 - 分析页面结构
python3 main.py --debug

# 4. 无头模式（后台运行）
python3 main.py --limit 20 --headless
```

## 首次运行

首次运行会打开 Chrome 浏览器，你需要：

1. 在浏览器中 **扫码/密码登录 BOSS直聘**
2. 登录成功后，程序自动检测到并开始工作
3. 无需其他操作

**超时**：默认等待登录 5 分钟，超时后退出。

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--limit N` | 10 | 处理上限人数 |
| `--headless` | false | 无头模式（后台运行） |
| `--debug` | false | 调试模式（只分析页面结构） |
| `--slow N` | 300 | 操作延迟（毫秒） |

## 项目结构

```
boss-recruitment-system/
├── main.py                  # 🆕 v2.0 主程序（入口）
├── app/
│   ├── __init__.py
│   ├── api.py               # FastAPI 后端
│   ├── config.py            # 配置文件
│   ├── vision.py            # OCR识别模块 (macOS Vision)
│   ├── screen.py            # 屏幕控制模块
│   ├── database.py          # 数据库模块
│   ├── workflows.py         # 工作流模块
│   ├── filter_criteria.py   # 🆕 筛选条件+名校白名单
│   └── resume_collector.py  # 简历收集器（旧版坐标）
├── boss_rpa/
│   ├── __init__.py
│   ├── config.py            # 学校白名单/评分规则
│   ├── browser.py           # Playwright自动化（旧版）
│   └── utils.py             # 工具函数
├── scripts/
│   ├── init_filter_config.py  # 🆕 筛选配置初始化
│   ├── deploy_agent.py
│   └── ...
├── data/                    # 数据库
├── tests/                   # 测试
└── tools/                   # 工具
```

## 筛选系统

### 筛选打招呼

通过 `/api/filter/contact` 启动，自动扫描推荐牛人列表，匹配学校白名单后批量打招呼。

```bash
# 初始化筛选配置（写入数据库）
python scripts/init_filter_config.py

# 查看当前配置
python scripts/init_filter_config.py --show

# 重置为默认
python scripts/init_filter_config.py --reset
```

### 学校白名单（132所）

| 区域 | 数量 | 示例 |
|------|------|------|
| 国内名校 | 33 | 清华大学、北京大学、浙江大学、复旦大学... |
| 美国名校 | 41 | Harvard, MIT, Stanford, UC Berkeley, CMU... |
| 英国名校 | 17 | Oxford, Cambridge, Imperial, LSE, UCL... |
| 其他地区 | 41 | ETH Zurich, NUS, Toronto, Tokyo, HKU, Melbourne... |

完整名单见 `app/filter_criteria.py` 或 `scripts/init_filter_config.py`。

### 可扩展筛选条件

筛选条件通过 `FilterCriteria` 数据类定义，当前已启用：

| 维度 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 学校 | `school_whitelist` | multi_select | 中英文名校+缩写匹配 |
| 学历 | `min_degree` | select | 博士 > 硕士 > 本科 > 大专 |
| 年限 | `min_years` | number | 最低工作年限 |

预留扩展（`enabled: false`，后续启用即可）：

| 维度 | 字段 | 类型 |
|------|------|------|
| 年龄 | `age_range` | range |
| 技术栈 | `tech_stack` | multi_select |
| 行业 | `industry` | multi_select |
| 职位 | `job_title_keywords` | multi_select |

API `/api/filter/config` 返回 `available_filters` 列表，前端可按 `enabled` 状态动态渲染。

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/filter/config` | 获取筛选配置 |
| PUT | `/api/filter/config` | 更新筛选配置 |
| POST | `/api/filter/contact` | 启动筛选打招呼任务 |
| GET | `/api/filter/status/{task_id}` | 查询任务进度 |

### cua-driver 驱动（后台自动化）

用 cua-driver 驱动 Chrome 完成打招呼闭环 — 无需 OCR，直接通过可访问性树 + JS 操作 DOM：

```bash
# 预览模式（只扫描候选人，不打招呼）
python scripts/cua_greeting_loop.py --dry-run

# 打招呼（上限 10 人，默认全部名校白名单）
python scripts/cua_greeting_loop.py --limit 10

# 自定义学校
python scripts/cua_greeting_loop.py --schools "清华大学,北京大学,MIT,Stanford University"
```

**前置条件：**

```bash
# 1. 安装 cua-driver
brew install cua-driver

# 2. 授权可访问性 + 屏幕录制
cua-driver check_permissions

# 3. Chrome 开启 "Allow JavaScript from Apple Events"
#    关闭 Chrome → 写入配置 → 重新打开
python3 -c "
import json, os
prefs = os.path.expanduser('~/Library/Application Support/Google/Chrome/Default/Preferences')
data = json.load(open(prefs))
data.setdefault('browser', {})['allow_javascript_apple_events'] = True
json.dump(data, open(prefs, 'w'))
print('done')
"
```

**对比：OCR vs cua-driver**

| 维度 | OCR 方案 (workflows.py) | cua-driver 方案 |
|------|------------------------|-----------------|
| 定位方式 | 截图→OCR→坐标估算 | AX 树索引 + JS DOM |
| 精度 | ±5-20px | 像素级 |
| 后台运行 | 需要前台 Chrome | ✅ 完全后台 |
| 受分辨率影响 | 是 | 否 |
| 候选人信息提取 | OCR 文本解析 | JS `document.querySelectorAll` |
| 学校匹配 | OCR 文本子串 | 结构化 JSON |
| 环境要求 | macOS Vision / Tesseract | cua-driver + Chrome AX |

## 防检测机制

- 随机延迟 2-4 秒（候选人之间）
- 非无头模式默认有界面（更真实
- 注入反检测脚本（隐藏 webdriver）
- macOS 真实 User-Agent

## 常见问题

### Q: 检测不到候选人列表怎么办？
A: 先运行 `python3 main.py --debug` 分析页面结构，看选择器是否匹配。

### Q: 简历下载到哪了？
A: `~/Downloads/BossResumes/候选人名_时间戳.pdf`

### Q: 需要屏幕录制权限吗？
A: **不需要**。本系统使用 Playwright 接管浏览器，通过 DOM 操作，不需要系统截图权限。

### Q: macOS 26+ 兼容吗？
A: 兼容。因为不依赖 `screencapture`/`CGDisplayCreateImage`（这些在 macOS 26 中被废弃），所有操作通过 Playwright 完成。

---

## 技术方案

### 为什么用 Playwright 做主方案？

| 维度 | Playwright (选) | 纯视觉 OCR | ScreenCaptureKit |
|------|----------------|-------------|------------------|
| 权限需求 | 无 | 屏幕录制授权 | 屏幕录制授权 |
| macOS 26+ | ✅ 兼容 | ❌ CG废弃 | ✅ 但需授权 |
| 定位精度 | DOM级(像素级) | ±5-20px | ±3px |
| 浏览器检测 | 注入脚本 | 无影响 | 无影响 |
| 运行环境 | 全平台 | macOS only | macOS 13+ |
| 速度 | 毫秒级 | 秒级 | 秒级 |

### 决策

**主方案：Playwright（DOM 操作）**
- 不需要 macOS 隐私授权
- 精准定位元素（按钮、列表、弹窗）
- 支持下载文件
- 跨平台

**辅助方案：Vision OCR（macOS 原生）**
- 当 Playwright 无法定位元素时使用
- 检测按钮颜色（深蓝/浅蓝）
- 验证操作结果

---

*轩辕 · 2026-05-21 · v2.0*
