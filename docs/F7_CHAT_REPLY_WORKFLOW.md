# F7 批量AI聊天回复流程

## 触发入口

`POST /api/workflow/reply-messages` → API 线程池 → `_run_reply_in_thread()` → `_batch_reply_impl()`

兼容路由: `POST /api/chat/batch` → 委托到同一实现

## 完整步骤

```
1. 获取浏览器任务锁
   └─ _browser_task_lock.acquire(blocking=False)
       失败 → 返回"浏览器正被 {task} 占用"

2. 连接浏览器 + 登录检查 (两级模式)
   │
   ├─ API层: _run_reply_in_thread 负责
   │  ├─ automation.reset_for_thread()  (线程安全重置)
   │  ├─ automation.connect() → nodriver CDP (port 9222)
   │  └─ automation.import_cookies()   (恢复登录态)
   │
   └─ 业务层: _batch_reply_impl() 负责
      └─ _ensure_session() → check_login()
          ├─ 已登录 → 继续
          └─ 未登录 → 返回"BOSS直聘未登录"

   锁管理说明:
   - 锁在 reply_messages() API层获取
   - 在 _run_reply_in_thread 的 finally 块释放
   - _batch_reply_impl() 业务层无锁(已由调用者保护)

3. 导航到聊天页
   └─ navigate_to_chat()
       ├─ 点击左侧"沟通"导航按钮
       └─ 备用 fallback URL: /web/chat/index (非 /web/geek/chat)

4. 筛选未读联系人
   ├─ get_contacts() → 所有联系人
   ├─ 过滤: hasUnread == true
   └─ 取前 max_count 个
       无未读 → 返回 completed (replied=0)

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
   │      │   │   └─ API配置: DEEPSEEK_API_KEY (必需) + DEEPSEEK_BASE_URL (可选)
   │      │   └─ 成功 → reply + generation_method="ai"
   │      │
   │      └─ AI失败 → 自动降级
   │          ├─ 从 _DEFAULT_FALLBACK_TEMPLATES 随机选取
   │          └─ generation_method="template_fallback" / "stage_fallback"
   │
   ├─ 5d. 发送消息
   │      ├─ dry_run 模式说明: 通过 WorkflowRequest.dry_run 字段传入
   │      │   ├─ dry_run=True → 仅记录，不实际发送
   │      │   └─ dry_run=False → 实际发送
   │      └─ 实际发送流程:
   │          ├─ dismiss_popup() (关闭限制弹窗)
   │          ├─ 查找输入框 (textarea / contenteditable)
   │          ├─ 点击输入框
   │          ├─ automation.type_text(reply)  (xdotool 仿真输入)
   │          ├─ 查找发送按钮: 匹配 '发送'/'发 送'/indexOf/'Send'
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
       results中每条含 generation_method: "ai" | "template_fallback" | "stage_fallback"
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

## 参考 cua_chat_loop.py 的循环步骤调整

> 对比 `../cua-boss-system/scripts/cua_chat_loop.py`（已验证的 CUA 版本）与当前 F7 实现，
> 识别出 **6 项关键差距** 和对应的调整方案。

### 差距对照表

| # | 差距 | cua_chat_loop.py 做法 | 当前 F7 做法 | 调整方案 |
|---|------|----------------------|-------------|----------|
| 1 | **限制弹窗检测** | `check_limit_popup()` 扫描 20+ 关键词 ("已达上限", "次数不足"...) + `dismiss_limit_popup()` 移除弹窗DOM | 无检测，弹窗出现后静默失败 | 在每轮循环开始前加 `check_limit_popup()`，命中即 break |
| 2 | **输入框清空** | `_clear_input()`: JS聚焦 → Cmd+A全选 → Delete删除，兼容React/Vue状态 | 直接 `type_text()` 不清空，可能残留上次文本 | 发送前先执行 `_clear_input()` |
| 3 | **全量聊天历史** | `_ax_fallback_chat_history()` 通过 AX 树 `[送达]/[已读]` 标记推断发送方，取最近10条完整历史 | 只取最后一条 `!isMe` 消息，无历史上下文 | 读取完整历史，传入 DeepSeek 的 messages 数组 |
| 4 | **已回复跳过** | 检查 `last_sender == "boss"` → 已回复直接跳过 | 只检查是否有候选人消息，不判断是否已回复 | 加 `last_sender` 检查，已回复的跳过 |
| 5 | **DB上下文 + 阶段推算** | `_load_candidate_context()` 读取 has_resume/has_wechat + `_compute_stage()` 推算对话阶段 (early/has_resume_no_wechat/ready_for_interview等)，注入system prompt | 无上下文加载，每次回复都是"盲答" | 加载候选人DB记录 + 阶段推算，注入 AI prompt |
| 6 | **冗余检查** | `_reply_redundant()`: 已有简历时不问"方便发简历"，已有微信时不问"加微信" | 无检查，可能重复请求已有信息 | 生成后检查，冗余则替换为阶段兜底文本 |

### 次要差距（本轮可选）

| # | 差距 | 说明 | 优先级 |
|---|------|------|--------|
| 7 | 联系人扫描范围 | cua 扫描全部联系人(非仅未读)，F7 只扫 `hasUnread` | 低 — 当前按未读筛选合理 |
| 8 | 学校/学历筛选 | cua 不符学校直接点"不合适"，F7 无筛选 | 中 — 可后置，先保证回复质量 |
| 9 | UID 提取 | cua 从 `data-id` 属性提取加密用户ID，F7 用姓名 | 中 — 影响DB唯一性 |
| 10 | 岗位感知模板 | cua 按 `detect_job()` 匹配岗位专属模板 | 低 — 当前AI生成已覆盖 |

### 调整后的主循环步骤（建议）

```
5. 主循环 (遍历 unread contacts)
   │
   ├─ 5.0. ★ 限制弹窗检测 (新增)
   │      ├─ check_limit_popup() 扫描 DOM 弹窗文本
   │      │   关键词: "已达上限", "次数不足", "沟通人数已达",
   │      │           "明天再来", "额度不足", "会员权益" ...
   │      ├─ 命中 → dismiss_limit_popup() + break 主循环
   │      └─ 未命中 → 继续
   │
   ├─ 5a. 点击联系人
   │      ├─ click_contact(name, x, y)
   │      │   失败 → failed++, continue
   │      └─ ★ 尝试提取 data-id 作为 uid (新增)
   │
   ├─ 5b'. ★ 清空输入框 (新增)
   │      ├─ JS 聚焦 textarea/contenteditable
   │      ├─ Cmd+A 全选 + Delete 删除
   │      └─ 兼容 React/Vue 受控组件状态更新
   │
   ├─ 5c'. ★ 读取完整聊天历史 (改进)
   │      ├─ get_messages() → 所有消息气泡
   │      ├─ 发送方推断 (改进):
   │      │   ├─ AX标记: [送达]/[已读] → 下一句是 boss 发的
   │      │   ├─ CSS class: 'self'/'mine'/'right' → isMe
   │      │   └─ 相对位置: x > 面板50% → isMe
   │      ├─ ★ 检查 last_sender:
   │      │   └─ last_sender == "boss" → skipped++, continue (已回复)
   │      └─ 构建完整 history[] (最近10条)
   │
   ├─ 5d'. ★ 加载DB上下文 + 阶段推算 (新增)
   │      ├─ DB查询: SELECT has_resume, has_wechat, chat_history
   │      │         FROM candidates WHERE uid/name = ?
   │      ├─ 合并 DB历史 + AX历史 (去重保序, 保留最近20条)
   │      └─ 推算阶段:
   │          ├─ early_stage: 无数据，无约束
   │          ├─ awaiting_response: 已请求简历/微信，等回复
   │          ├─ has_resume_no_wechat: 有简历无微信
   │          ├─ has_wechat_no_resume: 有微信无简历
   │          └─ ready_for_interview: 简历+微信都有，推动面试
   │
   ├─ 5e. 生成AI回复 (改进)
   │      ├─ chat_service.generate_reply(name, msg, history, template)
   │      │   ├─ 注入 stage_context 到 system prompt
   │      │   │   例: "阶段: has_resume_no_wechat
   │      │   │        已知: 已收到简历
   │      │   │        注意: 不要再问简历，推动约面试或微信交换"
   │      │   └─ DeepSeek API 调用
   │      │
   │      ├─ ★ 冗余检查 (新增):
   │      │   ├─ has_resume 且回复含 "方便发简历" → 替换
   │      │   └─ has_wechat 且回复含 "加微信" → 替换
   │      │
   │      └─ AI失败 → 自动降级到模板
   │
   ├─ 5f. 发送消息
   │      ├─ ★ 先清空输入框 (同 5b')
   │      ├─ dry_run=True → 仅记录
   │      └─ dry_run=False → type_and_send(reply)
   │
   ├─ 5g'. ★ 保存完整历史到DB (改进)
   │      ├─ chat_service.save_conversation()
   │      ├─ ★ merge + dedup 逻辑:
   │      │   旧历史 + 新历史 → 按 (role, content) 去重保序
   │      │   保留最近 20 条
   │      └─ db.insert_contact_record(action="replied")
   │
   └─ 5h. 随机间隔 1.5-4秒
```

### 限制弹窗检测 — 具体关键词列表

```
LIMIT_KEYWORDS = [
    "已达上限", "次数已用完", "今日已达", "已达每日",
    "沟通人数已达", "打招呼次数", "超出限制",
    "明天再来", "今日上限", "已达当天",
    "每天最多", "上限了", "用完了", "今日沟通",
    "权益不足", "开料次数", "剩余次数", "次数不足",
    "会员权益", "升级会员", "额度不足", "免费次数",
    "今日剩余",
]
```

### 对话阶段推算 — 阶段定义

```
阶段                  条件                          AI prompt 约束
─────────────────────────────────────────────────────────────────────
early_stage           无DB数据，无请求信号           无约束 (自由对话)
awaiting_response     已发简历/微信请求，等回复       不重复请求
has_resume_no_wechat  DB: has_resume=1              不问简历，推动面试或微信
has_wechat_no_resume  DB: has_wechat=1              不问微信，聊岗位细节
ready_for_interview   has_resume=1 AND has_wechat=1 不问简历/微信，约面试
```

### 阶段兜底文本

```python
_STAGE_FALLBACK = {
    "ready_for_interview": "简历和微信都收到了，方便的话我们约个时间聊聊具体岗位细节？",
    "has_resume_no_wechat": "简历收到了，具体岗位细节可以进一步沟通，你觉得怎么样？",
    "has_wechat_no_resume": "好的，具体岗位细节可以进一步聊，方便说说你主要的项目经历吗？",
    "awaiting_response": "好的，等你方便回复的时候我们再继续聊～",
}
```

### 实施优先级

```
P0 — 必须立即修复 (影响回复成功率):
  [1] 限制弹窗检测 — 无此检测会导致超出限制后全部静默失败
  [2] 输入框清空 — 不清空会导致残留文本拼接到新回复中
  [3] 已回复跳过 — 不跳过会导致重复回复同一个人

P1 — 提升回复质量:
  [4] 完整聊天历史 — 让AI有上下文，回复不脱节
  [5] DB上下文 + 阶段推算 — 避免重复问已有的东西
  [6] 冗余检查 — 兜底保障，防止AI"忘记"已知信息
```

## 已知问题

- hasUnread 检测依赖文本 '●'/'未读'，BOSS 改版可能失效
- 自定义模板绕过 DeepSeek 安全护栏（用户责任）
- boss_id 用候选人姓名代替（非唯一标识）
- conversations 表无 boss_id 索引，数据量大时查询变慢
