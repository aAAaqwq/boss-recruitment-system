# ISSUE-003: 批量回复未读消息功能异常 — 浏览器连接检测失败

> 状态: **已修复** | 优先级: P0 | 发现日期: 2026-06-08 | 修复日期: 2026-06-08

## 问题描述

批量回复未读消息功能异常，明明浏览器已连接却说"浏览器未连接或会话失效，请先打开BOSS直聘"。

## 根因分析

### Bug: 双重 `reset_for_thread()` 破坏已建立的连接

**API 层** (`app/api.py:_run_reply_in_thread`):
```python
automation.reset_for_thread()      # ① 重置状态
conn = await automation.connect()  # ② 连接成功 → _connected=True
await automation.import_cookies()  # ③ 导入 cookie
result = await _batch_reply_impl(  # ④ 调用业务层
    max_count=max_count, ...)
```

**业务层** (`app/chat_workflow.py:_batch_reply_impl` — 修复前):
```python
automation.reset_for_thread()      # ⑤ 再次重置 → _connected=False ❌
if not await automation._ensure_session():  # ⑥ _connected=False → 直接返回 False
    return {"status": "error", "message": "浏览器未连接或会话失效"}  # ← 报错退出
```

`automation._ensure_session()` 首行检查 `self._connected`:
```python
async def _ensure_session(self, timeout=5):
    if not self._connected or not self.page:
        return False  # ← 直接 False，不尝试重连！
```

**结论**: API 层在步骤②成功连接了浏览器，但业务层在步骤⑤调用 `reset_for_thread()` 将 `_connected` 设为 `False`，步骤⑥的 `_ensure_session()` 直接返回 `False`，导致任务错误退出。

### 为什么之前验收通过

F7 上次修复 (2026-06-07) 在 API 层添加了线程安全的 `reset_for_thread() + connect() + import_cookies()`，但没有从业务层移除旧的 `reset_for_thread()` 调用。这是合并时的回归 bug。

## 修复内容 (`app/chat_workflow.py:74-77`)

```python
# 修复前：
automation.reset_for_thread()  # ← 破坏调用方已建立的连接
if not await automation._ensure_session():
    return {"status": "error", ...}

# 修复后：
# 连接由调用方 _run_reply_in_thread 统一管理，此处仅做健康检查
if not await automation._ensure_session():
    return {"status": "error", ...}
```

## 相关文件

- `app/chat_workflow.py:74-77` — 移除重复的 `reset_for_thread()`
- `app/api.py:643-703` — API 层 `_run_reply_in_thread` (连接管理)
- `app/automation.py:107-136` — `_ensure_session()` 实现
- `docs/F7_CHAT_REPLY_WORKFLOW.md` — F7 规格文档
