# ISSUE-002: 筛选+打招呼无法刷新候选人页面

> 状态: **已修复** | 优先级: P0 | 发现日期: 2026-06-08 | 修复日期: 2026-06-08

## 问题描述

筛选+打招呼功能在未达到指定判断的候选人卡片数量前，无法刷新候选人页面获取新的候选人卡片列表。

## 根因分析

### 核心问题

`app/workflows.py` `_auto_contact_impl()` 主循环中，当 BOSS 推荐页面的一批候选人全部被扫描过后，系统只能依赖 iframe 内滚动(`_JS_SCROLL_IFRAME` 每次 400px)来尝试加载更多，但 BOSS 可能不会无限加载新候选人。连续 5 次无新卡片即退出循环，导致实际联系人数远低于 `daily_cap`。

修复前逻辑:
```python
if not new_cards:
    no_new += 1
    if no_new >= 5:
        break  # 直接退出 — 无页面刷新
    await automation.execute_js(_JS_SCROLL_IFRAME)
    await asyncio.sleep(2)
    continue
```

### 缺失的功能
- 没有页面刷新机制来获取 BOSS 推荐的新一批候选人
- 仅依赖 iframe 内滚动，无法突破单批次推荐池的限制

## 修复内容 (`app/workflows.py:230-245`)

```python
if not new_cards:
    no_new += 1
    # ★ 连续 3 次无新卡片 → 刷新推荐页面获取新一批候选人
    if no_new >= 3 and contacted < remaining:
        logger.info(f"[F5] 连续{no_new}次无新卡片，刷新推荐页面获取新候选人...")
        nav = await automation.navigate("https://www.zhipin.com/web/chat/recommend")
        if nav.get("status") == "error":
            logger.warning(f"[F5] 刷新导航失败: {nav.get('message')}")
        await asyncio.sleep(8)  # 等待页面+iframe 重新加载
        await automation.execute_js(_JS_SCROLL_TOP)
        await asyncio.sleep(2)
        no_new = 0  # 重置计数器
        continue
    if no_new >= 10:  # 含刷新重试仍失败则退出
        logger.error(f"[F5] 连续{no_new}次无新卡片（含刷新重试），退出")
        break
    await automation.execute_js(_JS_SCROLL_IFRAME)
    await asyncio.sleep(2)
    continue
```

新增行为:
- 连续 3 次无新卡片 → 自动 re-navigate 到推荐页面刷新候选人池
- 刷新后等待页面加载 8 秒 → 重置计数器继续扫描
- 连续 10 次（含刷新重试）→ 退出

## 相关文件

- `app/workflows.py:136-316` — `_auto_contact_impl()` 主循环
- `app/workflows.py:87-95` — `_JS_SCROLL_IFRAME`
- `docs/F5_GREET_WORKFLOW.md` — F5 规格文档
