# F6 + F7 集成视觉验收

> 日期: 2026-06-08
> 范围: F5(打招呼) → F6(简历收集) → F7(AI回复) 端到端流程

## 完整集成流程

```
┌─────────┐    ┌─────────┐    ┌─────────┐
│  F5     │───▶│  F6     │───▶│  F7     │
│ 打招呼   │    │ 简历收集 │    │ AI回复   │
└─────────┘    └─────────┘    └─────────┘
 搜索+打招呼    聊天列表获取    未读消息回复
 创建联系人     下载简历       保存对话
```

## 前置条件

- [ ] BOSS 直聘已登录
- [ ] 搜索筛选条件已配置
- [ ] DeepSeek API Key 已配置
- [ ] 至少有 5 个匹配的搜索候选人

---

## 集成测试场景

### 场景 1: F5→F6 直通

**操作**: 先运行 F5 打招呼，再运行 F6 获取简历

**步骤**:
1. F5: `POST /api/greet/batch` — 对搜索结果打招呼
2. 等待 30 秒（模拟候选人回复）
3. F6: `POST /api/resume/batch` — 从聊天列表获取简历

**验证**:
- [ ] F5 创建的联系人在 F6 的聊天列表中
- [ ] F6 按 hasUnread 排序后，刚打招呼的联系人（如有回复）排在前面
- [ ] F6 日志显示联系人来源（是否来自 F5）

**已知问题**: 当前 F5 和 F6 架构完全独立。F5 在搜索结果页操作，F6 在聊天列表操作，没有数据传递。F5 打过招呼的候选人如果没有回复，不会出现在聊天列表中。

### 场景 2: F6→F7 直通

**操作**: 先运行 F6 获取简历，再运行 F7 回复

**步骤**:
1. F6: `POST /api/resume/batch` — 获取简历
2. F7: `POST /api/chat/batch` — 回复未读消息

**验证**:
- [ ] F7 使用 F6 记录的 DB 上下文（`load_candidate_context`）
- [ ] 已有简历的联系人 → stage 为 `has_resume_no_wechat` 或 `ready_for_interview`
- [ ] F7 不会索要已下载的简历（`reply_redundant` → `stage_fallback`）
- [ ] F6 下载的记录在 `resume_operations` 表中可被 F7 查询

### 场景 3: 完整三板斧

**操作**: F5 → 等待 → F6 → F7

**步骤**:
1. F5: 打招呼 5 人
2. 等待候选人在 BOSS 中回复（模拟或真实）
3. F6: 扫描聊天列表 → 下载简历 (Case 1/2/3/4)
4. F7: 回复未读消息

**截图检查点**:

| # | 阶段 | 截图内容 | 验证要素 |
|---|------|---------|---------|
| 1 | F5 完成 | 打招呼结果 | greeted/failed/skipped |
| 2 | F6-聊天 | 联系人列表（含 F5 打过招呼的） | hasUnread 标记 |
| 3 | F6-PDF | 简历预览 + 下载按钮 | CDP 事件确认 |
| 4 | F6-完成 | 汇总: downloaded/skipped/failed | `/tmp/f6_final.png` |
| 5 | F7-阶段 | 日志中的阶段推算 | 与 DB 上下文一致 |
| 6 | F7-发送 | AI 回复在聊天面板中 | isMe=true 的新消息 |
| 7 | F7-完成 | 汇总: replied/failed/skipped | `/tmp/f7_final.png` |

### 场景 4: 限制弹窗打断

**操作**: 在 F7 运行中，BOSS 弹出限制提示

**验证**:
- [ ] F7 检测到限制弹窗 → 记录日志
- [ ] 弹窗被 JS 移除 (dialog-wrap, overlay)
- [ ] F7 终止循环（不继续处理后续联系人）
- [ ] 已处理的结果正确返回

### 场景 5: 浏览器断开恢复

**操作**: 在处理过程中关闭浏览器

**验证**:
- [ ] F6 `_ensure_session()` 返回 False → 返回 error
- [ ] F7 `_ensure_session()` 返回 False → 返回 error
- [ ] 错误消息包含 "浏览器未连接"

---

## 数据库一致性检查

在集成流程结束后验证:

```sql
-- F5 创建的候选人
SELECT COUNT(*) FROM candidates WHERE status = 'active';

-- F6 下载的简历
SELECT action, COUNT(*) FROM resume_operations GROUP BY action;

-- F7 生成的回复
SELECT action, COUNT(*) FROM conversations WHERE action = 'auto_reply';

-- 关联检查: F7 回复的联系人是否有 F6 的简历下载记录
SELECT DISTINCT c.candidate_name
FROM conversations c
LEFT JOIN resume_operations r ON c.candidate_name = r.candidate_name
WHERE c.action = 'auto_reply';
```

**预期**:
- [ ] `resume_operations` 表有 downloaded/requested/need_reply/requested_pending 多种操作
- [ ] `conversations` 表有 auto_reply 记录
- [ ] 有简历下载记录的联系人 → F7 阶段不为 early_stage

---

## 已知架构问题

### F5→F6 脱节
F5 在搜索结果页操作，F6 在聊天列表操作。F5 打过招呼的人如果没回复，不会出现在聊天列表中。F6 无法知道谁刚被 F5 联系过。

**建议**: 
- F5 打完招呼后记录到 `contact_records` 表
- F6 启动前先查 `contact_records` 获取近期联系人
- 或者：F6 在聊天列表找不到时，去搜索结果页操作

### 视觉验证依赖
所有视觉验证需要真实 BOSS 账号。Dry-run 模式可验证逻辑但不触发实际浏览器交互。

---

## 通过标准

- [ ] 场景 1 (F5→F6): API 返回正常，DB 记录完整
- [ ] 场景 2 (F6→F7): 阶段推算正确，不索要已有信息
- [ ] 场景 3 (三板斧): 全流程无异常，截图完整
- [ ] 场景 4 (限制弹窗): 检测正确，终止优雅
- [ ] 场景 5 (断开恢复): 错误消息明确，不崩溃
