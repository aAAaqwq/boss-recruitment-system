# F5 主动打招呼流程

## 触发入口

`POST /api/filter/contact` → API 线程池 → `_auto_contact_impl()`

## 完整步骤

```
1. 连接浏览器
   └─ nodriver 连接 Chrome CDP (port 9222)

2. Cookie + 登录
   ├─ import_cookies() 恢复保存的 cookie (由调用方完成)
   ├─ 导航到 /web/chat/recommend
   ├─ _ensure_session() 健康探测
   └─ 失败 → 返回"浏览器未连接或会话失效, 请先打开BOSS直聘"

   注意: F5 流程不直接调用 check_login()，依赖调用方(前端/API层)先完成登录检查。
   当前 _auto_contact_impl 只做 _ensure_session() 健康探测 + navigate() 导航。

3. 等待页面加载 (8秒)
   └─ /web/chat/recommend 通过 JS 动态加载 iframe:
      主页面 > .frame-box > iframe(src=/web/frame/recommend/)
      候选人卡片和打招呼按钮都在 iframe 内部
      需要等 iframe 加载完成 (3秒不够, 需要8秒)

4. 主循环 (while contacted < remaining)
   │
   ├─ 4a. 提取卡片 (_JS_EXTRACT_CARDS)
   │      └─ JS 通过 iframe.contentDocument 访问 iframe 内 DOM
   │      └─ 选择器: .card-inner → .candidate-card-wrap → 模糊匹配
   │      └─ 每张卡片提取打招呼按钮坐标
   │         (向上到 .candidate-card-wrap, 按钮在兄弟节点 .operate-side 中)
   │      └─ 返回: {text, x, y, w, h, greet_x, greet_y, greet_text}
   │
   ├─ 4b. 去重 (按卡片文本前50字符指纹)
   │
   ├─ 4c. 逐卡处理
   │      ├─ 解析候选人: 姓名/年限/学历/学校
   │      ├─ 筛选 (_should_contact):
   │      │   ├─ min_years >= 3
   │      │   ├─ min_degree >= 本科
   │      │   └─ school_whitelist 匹配
   │      ├─ 无打招呼按钮 → 跳过
   │      ├─ dry_run → 仅计数, 不操作
   │      │
   │      ├─ CDP 点击打招呼按钮
   │      │   └─ cdp_click_viewport(greet_x, greet_y)
   │      │      CDP viewport 坐标点击可穿透 iframe
   │      │
   │      └─ 成功 → contacted++
│         └─ db.insert_contact_record(boss_id, action="contacted")
   │
   ├─ 4d. 滚动加载更多 (_JS_SCROLL_IFRAME)
   │      └─ 在 iframe 内滚动 .list-wrap / .candidate-body
   │
   └─ 4e. 连续5次无新卡片 → 退出循环

5. 返回结果
   └─ {status, contacted, skipped, failed, total_scanned, dry_run, cap_used}
```

## 页面结构 (/web/chat/recommend)

```
┌──────────────────────────────────────────────────┐
│  顶部导航栏                                       │
├──────────────┬───────────────────────────────────┤
│  侧边导航     │  推荐牛人                          │
│  (左侧)      │  ┌─────────────────────────────┐  │
│              │  │ iframe (/web/frame/recommend/)│  │
│              │  │                              │  │
│              │  │  .candidate-card-wrap        │  │
│              │  │  ├── .card-inner (信息)      │  │
│              │  │  └── .operate-side (按钮)    │  │
│              │  │                              │  │
│              │  └─────────────────────────────┘  │
├──────────────┴───────────────────────────────────┤
```

## BOSS 卡片 DOM 结构 (iframe 内)

```
LI.card-item
└── DIV.candidate-card-wrap
    ├── .card-inner.common-wrap    ← 候选人信息 (姓名/学历/学校)
    ├── .tooltip-wrap              ← 附加提示
    └── .operate-side              ← 打招呼按钮
        └── BUTTON.btn.btn-greet   ← "打招呼" 按钮
```

关键点:
- 候选人列表在 iframe 内, JS 通过 `iframe.contentDocument` 访问
- 打招呼按钮是 `.card-inner` 的兄弟节点, 需向上到 `.candidate-card-wrap` 搜索
- CDP viewport 点击穿透 iframe, 不需要在 iframe 内执行点击

## 简化设计

- **只点击打招呼按钮** — 不发送招呼语, BOSS 平台会自动发送默认招呼语
- **仅写 contact_record** — 保证每日上限计数准确, 不写候选人详细信息
- 每张符合筛选条件的卡片点一下按钮即可完成打招呼

## 打招呼按钮文本

代码匹配的按钮文本列表:
- 打招呼
- 立即沟通
- 开聊
- 继续沟通

## 卡片返回字段

JS 提取返回的卡片字段:
- `text`: 卡片文本内容
- `x, y, w, h`: 卡片边界矩形 (viewport 坐标)
- `cx, cy`: 卡片中心坐标 (x + w/2, y + h/2)
- `greet_x, greet_y`: 打招呼按钮中心坐标 (CDP viewport 坐标)
- `greet_text`: 打招呼按钮文本

## 容错机制

### JS 提取失败检测
- `js_fail` 计数器, 每次 JS 提取失败时 +1
- >= 3 时检测 iframe 是否存活 (`!!document.querySelector('iframe')`)
- >= 10 时退出循环

### 全局超时
- 600 秒 (10 分钟) 全局超时自动退出
- 使用 `_time.monotonic()` 计时

### iframe 坐标偏移
- JS 通过 `iframe.getBoundingClientRect()` 获取 iframe 元素偏移 (ox, oy)
- CDP viewport 坐标 = iframe 内坐标 + ox/oy
- 确保点击坐标穿透 iframe 正确

### 进度截图
- 每 5 个新增操作截图一次 (total - last_screenshot_at >= 5)
- 最终截图 `/tmp/f5_final.png`
- 截图失败不阻塞流程
