# F6 批量获取简历 — 完整流程 & Grill

## 触发入口

`POST /api/resume/batch` → API线程池 → `_run_resume_in_thread()` → `collect_resumes()`

## 完整步骤 (当前实现)

```
1. 获取浏览器任务锁
   └─ _browser_task_lock.acquire(blocking=False)
       失败 → 返回"浏览器正被 {task} 占用"

2. 连接浏览器 + 登录检查 (两层)
   ├─ API层 _run_resume_in_thread:
   │  ├─ automation.reset_for_thread()
   │  ├─ automation.connect() → nodriver CDP :9222
   │  └─ automation.check_login()
   └─ 业务层 collect_resumes():
      └─ _ensure_session() → check_login() (再次检查)

3. CDP下载拦截
   └─ Page.setDownloadBehavior(behavior="allow", downloadPath=data/resumes/)
       ├─ 成功 → Chrome 自动保存到 data/resumes/
       └─ 失败 → 降级（文件落入Chrome默认目录，追踪不到）

4. 导航到聊天页
   └─ navigate_to_chat() → /web/chat/index
       失败 → 备用: automation.navigate("/web/chat/index")

5. 提取联系人列表 (⚠️ 一次性提取)
   └─ get_contacts() → _JS_GET_CONTACTS
       提取左侧面板 (x<450) 所有聊天项
       每项含: {name, text, x, y, w, h, hasUnread}

6. 主循环 for contact in contacts[:max_count]:
   │
   ├─ 6a. 去重检查
   │      └─ db.get_resume_ops(name) → 有 "downloaded" 记录 → skip
   │
   ├─ 6b. CDP点击联系人 ← 🔴 使用步骤5的一次性坐标
   │      └─ cdp_click_viewport(contact.x, contact.y) → sleep 2s
   │
   ├─ 6c. 查找简历按钮
   │      └─ _JS_FIND_RESUME_BTNS: 精确匹配 4 种文本
   │         '在线简历'/'附件简历'/'查看简历'/'查看附件'
   │
   ├─ 6d. 点击简历按钮 → 检测4种Case
   │      ├─ pdf_preview → 找下载按钮 → 目录diff验证
   │      ├─ request_popup → 点确认 → 再检PDF
   │      ├─ request_pending → 跳过
   │      ├─ need_reply → 跳过
   │      └─ unknown → 旧逻辑兜底
   │
   └─ 6e. Escape 关闭预览 → 下一个
```

---

## 🔴 关键问题 1: 未读判断 — hasUnread 提取了但从未使用

### 现状

`_JS_GET_CONTACTS` (chat_nav.py:55-82) **确实提取了 hasUnread 字段**:

```javascript
hasUnread: t.indexOf('●') >= 0 || t.indexOf('未读') >= 0
```

但在 `collect_resumes()` (resume_collector.py:181) **完全被忽略**:

```python
for i, contact in enumerate(contacts[:max_count]):
    # ❌ 没有 if contact.get("hasUnread") 过滤
    # ❌ 没有按 hasUnread 排序
    # ❌ 没有按时间/最新消息排序
```

### 问题

| 场景 | 当前行为 | 预期行为 |
|------|---------|---------|
| 200个联系人，10个有未读（对方发了简历） | 取前10个（可能是最老的） | 优先取有未读的10个 |
| 联系人列表中夹杂已读/未读 | 按DOM顺序盲目遍历 | 未读优先→已沟通→其他 |
| 刚打过招呼的人（F5后）还没出现在聊天列表 | F6找不到 | F6应从筛选结果页操作 |

### 严重性: 🔴 致命

**F6的核心价值是"获取对方发来的简历"，而有未读消息的联系人才是真正可能发了简历的人。** 不过滤 hasUnread 导致 F6 在处理无关联系人的同时错过了真正有简历的人。

### 修复方向

```python
# 1. 优先处理有未读消息的联系人
contacts = await get_contacts()
contacts.sort(key=lambda c: (c.get("hasUnread", False), c.get("timestamp", "")), reverse=True)

# 2. 或：严格模式 — 只处理未读
unread_contacts = [c for c in contacts if c.get("hasUnread")]
```

### hasUnread 检测本身的可靠性

当前依赖 `innerText.indexOf('●')` 或 `indexOf('未读')` — 这在BOSS UI中：
- `●` 是红点标记，不一定在所有版本中出现
- `未读` 文本可能被CSS截断或不在innerText中
- 更好的方案：检测特定class名 `[class*="unread"]`, `[class*="red-dot"]`，或检查DOM中是否有未读标记元素

---

## 🔴 关键问题 2: 下载的简历是否真的获取到？

### 当前下载链

```
CDP setDownloadBehavior("allow", data/resumes/)
  → 点击下载按钮 (cdp_click_viewport)
    → sleep 4s
      → 目录 diff (new_files - existing_files)
```

### 验证证据

data/resumes/ 目录现状:
```
张三.pdf  19 bytes  ← 仅1个测试占位文件
```

### 逐层分析

**Layer 1: CDP下载拦截是否生效？**

```python
# automation.py:1088-1093
await self.page.send(cdp_page.set_download_behavior(
    behavior="allow",
    download_path=download_dir,
    events_enabled=True,  # ← 启用了事件，但从未监听!
))
```

- `events_enabled=True` — CDP 会发送 `Browser.downloadProgress` 和 `Browser.downloadWillBegin` 事件
- **但代码中没有任何地方监听这些事件!** (没有 `page.on(...)` 或事件handler)
- 如果 `setDownloadBehavior` 本身失败 → 降级到 `status: "fallback"` → 文件去Chrome默认目录

**Layer 2: 下载按钮点击是否触发下载？**

```python
# resume_collector.py:366-367
ok = await automation.cdp_click_viewport(float(dl["x"]), float(dl["y"]))
await asyncio.sleep(4)  # ← 硬等4秒，没有事件驱动确认
```

- `cdp_click_viewport` 只保证鼠标事件发送了，不保证按钮响应了
- BOSS的下载按钮可能是 `<a download>` 链接、blob URL生成、或异步请求 — 每种触发机制不同
- 4秒固定等待对大PDF或慢网络不够

**Layer 3: 目录diff验证是否可靠？**

```python
existing_files = set(RESUMES_DIR.iterdir())
# ... click + sleep ...
new_files = set(RESUMES_DIR.iterdir())
file_appeared = bool(new_files - existing_files)
```

- 如果 CDP 拦截生效：文件出现在 data/resumes/ → diff 检测到 ✅
- 如果 CDP 拦截失效：文件去了 Chrome 默认下载目录 (~/Downloads 或容器内 /home/user/Downloads) → diff 检测不到 ❌
- 如果在处理联系人A时，联系人B的下载也完成了 → diff 会包含B的文件 → 误归属给A
- 如果下载在4秒后才完成 → diff 检测不到 → 误报失败

### 缺失的验证机制

应该通过 CDP 事件确认下载:

```python
# 缺少的代码模式:
download_completed = asyncio.Event()
download_path = None

async def on_download_progress(event):
    if event.get("state") == "completed":
        download_path = event.get("path")
        download_completed.set()

# 注册事件监听
await self.page.on("Browser.downloadProgress", on_download_progress)
# ... 点击下载按钮 ...
await asyncio.wait_for(download_completed.wait(), timeout=30)
```

### 严重性: 🔴 致命

**当前无法确认任何一份简历真正下载成功了。** 目录diff只能算"乐观估计"，在降级模式下（CDP拦截失效时）完全失效。

---

## 🔴 关键问题 3: 为什么没有点击到联系人？

### 根因1: 坐标一次性提取、循环中使用

```python
# resume_collector.py:168 — 一次性提取所有坐标
contacts = await get_contacts()  # ← 此时坐标有效

# resume_collector.py:181 — 在循环中使用可能已失效的坐标
for i, contact in enumerate(contacts[:max_count]):
    ok = await automation.cdp_click_viewport(
        float(contact["x"]), float(contact["y"])  # ← 坐标可能已偏移
    )
```

每次处理完一个联系人后:
1. Escape 关闭预览 → 回到聊天列表
2. 聊天列表 DOM 被 React 重渲染 → 元素位置变化
3. 新消息的人会冒到顶部 → 排序变化
4. 滚动位置可能变了 → 后续坐标偏出视口

### 根因2: 点击没有效果验证

```python
# cdp_click_viewport 只确认CDP消息发送成功
# 不验证点击后的页面状态
ok = await automation.cdp_click_viewport(x, y)
if not ok:
    failed += 1
    continue
await asyncio.sleep(2)  # 等2秒后直接找简历按钮
```

缺失的验证:
- 右侧聊天面板是否切换到了目标联系人？
- 联系人是否高亮了（表示选中）？
- URL 是否变化了（BOSS聊天切换通常伴随URL参数变化）？

如果点击落在了空白区域或被遮挡的元素上，`cdp_click_viewport` 仍然返回 True，但什么都没发生。2秒后找简历按钮会在旧的聊天面板里找。

### 根因3: 返回导航缺失

```python
# resume_collector.py:300-304
try:
    await automation.press_key("Escape")
    await asyncio.sleep(1)
except Exception:
    pass
# 直接进入下一个循环 — 假设已回到聊天列表
```

但 Escape 不一定能完全关闭简历预览:
- PDF预览可能是新标签页 → Escape无效
- 弹窗可能有多层 → 需要多次Escape
- 如果Escape没关掉预览 → 下一个 `cdp_click_viewport` 点在了PDF查看器上

### 根因4: JS提取的联系人坐标是 `getBoundingClientRect`

```javascript
// getBoundingClientRect 返回的是相对视口的坐标
var r = items[i].getBoundingClientRect();
x: r.x + r.width / 2,
y: r.y + r.height / 2,
```

CDP `dispatchMouseEvent` 使用的也是视口坐标（x, y参数是viewport坐标），所以这本身没问题。但如果:
- 页面有CSS transform/scale → 坐标对应不上
- 容器内有滚动 → 被滚动隐藏的联系人坐标在视口外（y可能为负数或超过视口高度）

### 严重性: 🔴 致命

点击成功率可能非常低，尤其是处理超过5-10个联系人时。每处理一个人就积累误差。

---

## 附加问题: 与 F5 完全脱节

```
用户预期流程:
  筛选 → F5 打招呼 → 对方回复 → F6 获取简历

当前实现:
  F5: 在搜索结果页操作，打完招呼就结束
  F6: 在聊天列表操作，独立运行，不知道谁刚被F5联系过
```

F5打完招呼的人可能：
- 还没出现在聊天列表（对方还没回复）
- 被埋在第3页（不在 contacts[:max_count] 范围内）
- 已经回复了但 hasUnread 没被用于过滤

---

## 总结矩阵

| # | 问题 | 文件:行号 | 严重性 | 症状 |
|---|------|----------|--------|------|
| 1 | hasUnread 提取但未使用 | resume_collector.py:181 | 🔴 致命 | 处理无关联系人，错过有简历的 |
| 2 | 下载无CDP事件确认 | resume_collector.py:366-372 | 🔴 致命 | 不知道文件是否真的下载了 |
| 3 | 坐标一次性提取后循环使用 | resume_collector.py:168→203 | 🔴 致命 | 第N个联系人坐标失效 |
| 4 | 点击后无效果验证 | resume_collector.py:203-208 | 🔴 致命 | 点击落空但继续执行 |
| 5 | 无返回导航确认 | resume_collector.py:300-304 | 🟠 高 | Escape后状态不确定 |
| 6 | F5→F6无衔接 | 架构层面 | 🟠 高 | 两个任务完全独立 |
| 7 | 固定sleep等待 | resume_collector.py:208,239 | 🟡 中 | 网络波动时不可靠 |
| 8 | 目录diff验证下载 | resume_collector.py:370-372 | 🟡 中 | 降级模式下完全失效 |
| 9 | 联系人无排序/优先级 | resume_collector.py:181 | 🟡 中 | 按DOM顺序而非业务优先级 |
