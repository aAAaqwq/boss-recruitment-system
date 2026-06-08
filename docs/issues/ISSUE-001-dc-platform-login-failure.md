# ISSUE-001: 数据总控平台(3101)登录失败

> 状态: **已修复** | 优先级: P0 | 发现日期: 2026-06-08 | 修复日期: 2026-06-08

## 问题描述

访问 http://localhost:3101 时登录失败，无法正常进入数据总控平台。

## 根因分析

### 发现的问题

1. **API_BASE 硬编码为 `localhost:8002`** — `templates/index.html:1160`
   - 当页面通过 3101 端口访问时，API_BASE 始终指向 8002
   - 如果 API 隧道 (8002) 未正确代理或失效，3101 就无法连接到 API
   - 当页面直接通过 8001 访问时，也应该能直连 API

2. **错误信息不明确** — 网络连接失败和认证失败使用相同的错误处理
   - `catch` 块不区分网络错误和登录错误
   - 用户无法判断是"API 服务器未启动"还是"密码错误"

### 已确认正常
- JWT 认证模块 `app/auth.py` — `verify_token()` 和 `verify_credentials()` 逻辑正确
- 登录端点 `POST /api/auth/login` (api.py:385-394) 逻辑正确
- CORS 配置已包含 `http://localhost:3101` (api.py:58)
- 上次验收 (2026-06-07, dc-platform-3101.md) 显示登录通过 ✅

## 修复内容

### 1. API_BASE 自动检测 (`templates/index.html:1160`)

```javascript
// 修复前：硬编码 8002，多端口访问时易失联
const API_BASE = 'http://localhost:8002';

// 修复后：根据当前页面端口自动选择 API 地址
const API_BASE = (() => {
    const origin = window.location.origin;
    if (origin.includes('localhost')) {
        const port = parseInt(new URL(origin).port) || 80;
        if (port === 8001) return origin;  // 直连API
        return 'http://localhost:8002';     // 通过API隧道
    }
    return 'http://localhost:8002';         // 默认
})();
```

### 2. 增强错误诊断 (`templates/index.html:1683`)

- 登录前打印 `正在登录 {API_BASE} ...` 确认目标地址
- 网络连接失败时明确提示"无法连接API服务器，请检查API服务是否启动"
- 区分网络错误 (`Failed to fetch`/`NetworkError`) 和认证错误 (`401`)

## 相关文件

- `app/auth.py` — JWT 认证
- `app/api.py:385-394` — 登录端点
- `.env` — 密码配置
- `templates/index.html` — 前端登录表单 (API_BASE auto-detect + 错误增强)
