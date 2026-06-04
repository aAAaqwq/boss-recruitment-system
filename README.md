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
├── main.py               # 🆕 v2.0 主程序（入口）
├── app/
│   ├── __init__.py
│   ├── config.py         # 配置文件
│   ├── vision.py         # OCR识别模块 (macOS Vision)
│   ├── screen.py         # 屏幕控制模块
│   ├── database.py       # 数据库模块
│   ├── workflows.py      # 工作流模块
│   └── resume_collector.py  # 简历收集器（旧版坐标）
├── boss_rpa/
│   ├── __init__.py
│   ├── config.py         # 学校白名单/评分规则
│   ├── browser.py        # Playwright自动化（旧版）
│   └── utils.py          # 工具函数
├── data/                 # 数据库
├── tests/                # 测试
└── tools/                # 工具
```

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
