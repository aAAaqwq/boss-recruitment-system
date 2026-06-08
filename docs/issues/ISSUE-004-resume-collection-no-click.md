# ISSUE-004: 批量获取简历无实际点击功能

> 状态: **已修复** | 优先级: P0 | 发现日期: 2026-06-08 | 修复日期: 2026-06-08

## 问题描述

批量获取简历功能无实际点击功能，疑似虚假的获取简历数据。需结合 `docs/F6_RESUME_WORKFLOW.md` 检验并补充点击按钮和获取保存的功能。

## 根因分析

### 发现的问题

**`automation.click()` 使用 xdotool 屏幕坐标点击**，但 JS 返回的是 viewport 坐标:
```python
# automation.py:939
async def click(self, x, y):
    await self.move_mouse(target_x, target_y)  # 移动到视口坐标(无chrome偏移补偿)
    subprocess.run(["xdotool", "click", "1"])   # xdotool 需要屏幕坐标！
```

对比 F5 打招呼使用的 `cdp_click_viewport()`:
```python
# automation.py:1014 — CDP Input.dispatchMouseEvent 直接使用视口坐标
async def cdp_click_viewport(self, x, y):
    await self.page.send(cdp_input.dispatch_mouse_event(
        type_="mousePressed", x=x, y=y, ...))  # ← 视口坐标，正确！
```

**问题**: xdotool 需要屏幕坐标（包含浏览器 chrome 偏移），但 JS 返回的是 viewport 内坐标。没有应用 `get_chrome_offset()` 偏移补偿，导致点击位置错误——在 Docker 环境下偏移可达 (0, 118) 像素。

### 代码逻辑完善性检查

对比 `docs/F6_RESUME_WORKFLOW.md` 规格：
- ✅ 6a. 点击联系人 — 已实现（但 xdotool 坐标有误）
- ✅ 6c. 查找简历按钮 — `_JS_FIND_RESUME_BTNS` 已实现
- ✅ 6d. Case-1~4 区分 — `_detect_resume_case()` 已实现
- ✅ CDP 下载拦截 — `enable_download_interception()` 已实现
- ❌ 点击方式 — **使用 xdotool 而非 CDP**

## 修复内容 (`app/resume_collector.py`)

### 全部 5 处 click 调用改为 CDP viewport 点击:

```python
# 修复前（xdotool — 坐标偏移问题）：
await automation.click(int(contact["x"]), int(contact["y"]))

# 修复后（CDP viewport — 坐标精确）：
ok = await automation.cdp_click_viewport(float(contact["x"]), float(contact["y"]))
if not ok:
    logger.warning(f"[F6] CDP点击失败")
```

修复位置:
1. **点击联系人** (line ~201): `automation.click()` → `cdp_click_viewport()`
2. **点击简历按钮** (line ~228): `automation.click()` → `cdp_click_viewport()`
3. **点击下载按钮** (line ~358): `automation.click()` → `cdp_click_viewport()`
4. **点击确认按钮** (line ~424): `automation.click()` → `cdp_click_viewport()`
5. **确认后下载** (line ~436): `automation.click()` → `cdp_click_viewport()`

每处都增加了点击返回值检查 (`ok`) 和失败日志。

## 相关文件

- `app/resume_collector.py` — 全部 5 处 click 修复
- `app/automation.py:939-951` — `click()` (xdotool 实现)
- `app/automation.py:1014-1051` — `cdp_click_viewport()` (CDP 实现)
- `docs/F6_RESUME_WORKFLOW.md` — F6 规格文档
