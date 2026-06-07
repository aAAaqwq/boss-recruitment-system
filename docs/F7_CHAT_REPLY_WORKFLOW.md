# F7 批量AI聊天回复流程

## 触发入口

`POST /api/workflow/reply-messages` → API 线程池 → `_run_reply_in_thread()` → `_batch_reply_impl()`

兼容路由: `POST /api/chat/batch` → 委托到同一实现

## 完整步骤

```
1. 获取浏览器任务锁
   └─ _browser_task_lock.acquire(blocking=False)
       失败 → 返回"浏览器正被 {task} 占用"

2. 连接浏览器 + 登录检查
   ├─ automation.reset_for_thread()  (线程安全重置)
   ├─ automation.connect() → nodriver CDP (port 9222)
   └─ check_login()
       ├─ 已登录 → 继续
       └─ 未登录 → 返回"BOSS直聘未登录"

3. 导航到聊天页
   └─ navigate_to_chat()
       ├─ 点击左侧"沟通"导航按钮
       ├─ 备用: 直接导航 /web/geek/chat
       └─ 获取联系人列表 + 筛选有未读的

4. 筛选未读联系人
   ├─ get_contacts() → 所有联系人
   ├─ 过滤: hasUnread == true
   └─ 取前 max_count 个
       无未读 → 返回 completed (replied=0)

5. 主循环 (遍历 unread contacts)
   │
   ├─ 5a. 点击联系人
   │      └─ click_contact(name, x, y)
   │          失败 → failed++, continue
   │
   ├─ 5b. 获取候选人最新消息
   │      ├─ get_messages() → 所有消息气泡
   │      ├─ 相对定位判断发送方:
   │      │   ├─ CSS class 含 'self'/'mine'/'right' → isMe
   │      │   └─ 消息 x > 面板宽度50% → isMe
   │      └─ 从末尾找第一个 !isMe 的消息
   │          未找到 → skipped++, continue
   │
   ├─ 5c. 生成AI回复 (优先) / 模板兜底
   │      ├─ chat_service.generate_reply(name, msg, history, template)
   │      │   ├─ 有自定义 template → 直接返回模板
   │      │   ├─ DeepSeek API 调用 (system prompt + 80字限制)
   │      │   └─ 成功 → reply + generation_method="ai"
   │      │
   │      └─ AI失败 → 自动降级
   │          ├─ 从 _DEFAULT_FALLBACK_TEMPLATES 随机选取
   │          └─ generation_method="template_fallback"
   │
   ├─ 5d. 发送消息
   │      ├─ dry_run=True → 仅记录，不实际发送
   │      └─ dry_run=False → type_and_send(reply)
   │          ├─ 查找输入框 (textarea / contenteditable)
   │          ├─ 点击输入框
   │          ├─ automation.type_text(reply)  (xdotool 仿真输入)
   │          ├─ 点击"发送"按钮 或 按Enter
   │          └─ 发送失败 → failed++, continue
   │
   ├─ 5e. 保存到数据库
   │      ├─ chat_service.save_conversation()
   │      │   └─ conversations 表: candidate_name, ai_message, candidate_message
   │      └─ db.insert_contact_record(action="replied")
   │
   └─ 5f. 随机间隔 1.5-4秒 (模拟人类操作节奏)

6. 释放浏览器任务锁
   └─ _browser_task_lock.release()

7. 返回结果
   └─ {replied, failed, skipped, total_scanned, dry_run, results: [...]}
       results中每条含 generation_method: "ai" | "template_fallback"
```

## BOSS DOM 结构

```
聊天页 (左右分栏)
├── 左侧: 联系人列表
│   └── .chat-item / .contact-item
│       └── innerText:
│           ├── 第一行: 候选人姓名
│           ├── 第二行: 最新消息预览
│           └── 未读标记: '●' / '未读' 或 CSS badge
│
└── 右侧: 聊天消息区
    └── 消息气泡
        ├── 对方消息: 靠左 (x < 面板宽度50%)
        └── 我的消息: 靠右 (x > 面板宽度50%)
            或 CSS class 含 'self'/'mine'/'right'

输入区域
├── textarea / [contenteditable="true"]
└── 发送按钮: innerText == '发送'
```

## AI 回复生成

```
DeepSeek API 调用:
  model: deepseek-chat (可配置)
  temperature: 0.7
  max_tokens: 150

System Prompt 规则:
  1. 回复简洁自然，不超过80字
  2. 语气友好、专业，像真人对话
  3. 严禁索要微信/电话/转账
  4. 不承诺offer录用
  5. 针对候选人问题回复

对话历史:
  取最近10轮 (candidate_message + ai_message)
```

## 模板兜底机制

```
AI失败原因 (可能触发兜底):
  - DEEPSEEK_API_KEY 未配置
  - API 调用超时 / 429 限流
  - 网络异常
  - 返回非200状态码

兜底话术 (_DEFAULT_FALLBACK_TEMPLATES):
  1. "您好，感谢您的关注！我正在查看您的消息，稍后会给您详细回复。"
  2. "您好，感谢您对职位的关注。我会尽快了解您的情况并回复您。"
  3. "感谢您的来信！我会仔细查看并尽快给您回复。祝好！"

流程: AI失败 → logger.warning → random.choice(templates) → generation_method="template_fallback"
```

## 本次修复 (2026-06-07)

| 修复点 | 旧行为 | 新行为 |
|--------|--------|--------|
| 双路径 | /api/chat/batch 用 mock send_to_boss; /api/workflow/reply-messages 用真实浏览器 | /api/chat/batch 委托到 /api/workflow/reply-messages |
| 模板兜底 | AI失败直接跳过 → 0条回复 | 自动降级到默认模板 → 保证每条都有回复 |
| 候选人消息 | /api/chat/batch 硬编码"你好，我对这个职位很感兴趣" | 真实路径从浏览器读取实际消息 |
| isMe检测 | 硬编码 x > 500px (窄屏/缩放会误判) | 相对定位(x > 面板50%) + CSS class 检查 |
| 认证 | /api/workflow/reply-messages 无认证 | 添加 Depends(verify_token) |
| 生成方式标记 | 无字段区分AI/模板 | results含 generation_method: "ai" / "template_fallback" |
| 线程安全 | 直接设置 automation._connected=False | reset_for_thread() + _browser_task_lock |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/workflow/reply-messages` | 启动批量回复（浏览器自动化，需认证） |
| POST | `/api/chat/batch` | 兼容路由 → 委托到 reply-messages |
| GET | `/api/workflow/reply-status` | 查询回复任务进度 |
| GET | `/api/chat/history` | 对话历史记录 |
| POST | `/api/chat/template` | 保存回复模板 |
| GET | `/api/chat/templates` | 获取所有模板 |

## 已知问题

- hasUnread 检测依赖文本 '●'/'未读'，BOSS 改版可能失效
- 自定义模板绕过 DeepSeek 安全护栏（用户责任）
- boss_id 用候选人姓名代替（非唯一标识）
- conversations 表无 boss_id 索引，数据量大时查询变慢
