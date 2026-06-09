# F7 批量AI回复 — 视觉验收清单

> 日期: 2026-06-08
> 功能: 批量AI回复未读消息 (POST /api/chat/batch)
> 环境: Docker 容器, VNC 8000, Chrome CDP 9222

## 前置条件

- [ ] Chrome 浏览器已打开并登录 BOSS 直聘
- [ ] 聊天列表中有至少 3 个联系人，其中至少 1 个有未读消息
- [ ] DeepSeek API Key 已配置
- [ ] API 服务运行中 (端口 8002)
- [ ] noVNC 可访问 (端口 8000)

---

## 视觉验证流程

### 步骤 1: API 触发

**操作**: 触发 `POST /api/chat/batch` (可先 dry_run=true)

**截图检查点 #1 — API 响应**:
- [ ] HTTP 200
- [ ] 响应包含 `replied`, `failed`, `skipped`, `total_scanned`, `dry_run`
- [ ] 日志显示 `[F7] 启动 | max={n} dry={mode} template={bool}`

### 步骤 2: 聊天页加载 + 未读筛选

**操作**: 观察导航到聊天页

**截图检查点 #2 — 聊天页 + 未读标记**:
- [ ] URL 为 `zhipin.com/web/chat/*`
- [ ] 日志显示 `[F7] 共{n}个联系人，{m}个有未读消息`
- [ ] 有未读的联系人有红点标记

**验证要素**:
| 元素 | 预期 |
|------|------|
| 未读 badge | `[class*="badge"], [class*="unread"], ●` |
| 联系人数量 | 日志中 contact_count > 0 |

### 步骤 3: 限制弹窗检测

**操作**: 观察是否触发限制弹窗

**截图检查点 #3 — 限制弹窗**:
- [ ] 如果出现: 弹窗文本匹配 LIMIT_KEYWORDS 之一
- [ ] JS 移除 `dialog-wrap`, `[class*=overlay]` 等元素
- [ ] Escape 键被按下
- [ ] 日志显示 `[F7] 检测到限制弹窗: {keyword}，终止批量回复`

### 步骤 4: 联系人点击 + 消息获取

**操作**: 观察第一个有未读的联系人被点击

**截图检查点 #4 — 聊天面板**:
- [ ] 右侧面板切换为对应联系人的聊天
- [ ] 消息列表可见
- [ ] 最新一条消息来自候选人（isMe=false）

**验证要素**:
| 检查项 | 方法 |
|--------|------|
| 面板切换 | `_JS_VERIFY_CHAT_PANEL` 返回 `{switched: true}` |
| 最后消息 | 日志 `[{name}] 的最新消息: {text[:60]}...` |
| 发送方 | `last_sender == "candidate"` (非 "boss") |

### 步骤 5: 已回复跳过

**操作**: 如果最后一条消息是我们发的

**截图检查点 #5 — 已回复联系人**:
- [ ] 日志显示 `[{name}]: 最后一条是我们发的，已回复过，跳过`
- [ ] 不生成 AI 回复
- [ ] 不发送消息

### 步骤 6: DB 上下文加载 + 阶段推算

**操作**: 观察日志中的阶段推算

**日志验证**:
```
[F7] {name} 阶段: early_stage | has_resume_no_wechat | ready_for_interview | ...
```

**验证要素**:
| 阶段 | 条件 | 策略 |
|------|------|------|
| ready_for_interview | 简历+微信都有 | 推动约面试 |
| has_resume_no_wechat | 有简历无微信 | 不重复索要简历 |
| has_wechat_no_resume | 有微信无简历 | 不重复索要微信 |
| awaiting_response | 已请求过 | 不重复请求 |
| early_stage | 无约束 | 自由对话 |

### 步骤 7: AI 回复生成

**操作**: 观察 DeepSeek API 调用

**截图检查点 #6 — AI 回复日志**:
- [ ] 日志显示 `[F7] 回复({method}): {reply[:60]}...`
- [ ] `method` 为 `ai` / `template_fallback` / `stage_fallback` 之一
- [ ] AI 回复长度 > 10 字符
- [ ] AI 回复不包含索要微信/电话的内容

**降级场景**:
| 场景 | method | 触发条件 |
|------|--------|---------|
| AI 正常 | ai | DeepSeek 返回成功 |
| AI 失败 | template_fallback | API 调用失败 |
| 冗余回复 | stage_fallback | AI 索要已有信息 |

### 步骤 8: 输入框清空 + 发送

**操作**: 观察消息输入和发送

**截图检查点 #7 — 消息发送**:
- [ ] 输入框被聚焦（JS `el.focus()`）
- [ ] 输入框内容被全选并删除（BackSpace）
- [ ] 新消息被输入（type_text）
- [ ] 发送按钮被点击 或 Return 键按下

**验证要素**:
| 元素 | 预期状态 |
|------|---------|
| 输入框 | 发送后为空 |
| 消息列表 | 新消息出现（isMe=true） |
| 发送按钮 | 未被禁用 |

### 步骤 9: DB 持久化

**操作**: 发送后检查数据库

**验证**:
- [ ] `conversations` 表有新记录 (action="auto_reply")
- [ ] `contact_records` 表有新记录 (action="replied", success=true)
- [ ] `boss_id`, `candidate_message`, `ai_message`, `created_at` 字段非空

### 步骤 10: 间隔等待 + 下一个

**操作**: 观察处理间隔

**验证**:
- [ ] 日志显示处理下一个联系人 `({i+1}/{n})`
- [ ] 间隔时间 1.5-4 秒（模拟人类操作）

### 步骤 11: 完成

**截图检查点 #8 — 完成截图**:
- [ ] `/tmp/f7_final.png` 存在
- [ ] API 返回汇总: `{replied, failed, skipped, total_scanned, dry_run}`
- [ ] `results` 数组每项包含 `name`, `success`, `reply`, `generation_method`, `stage`
- [ ] 日志显示 `[F7] 完成: 批量回复完成: 成功{n}, 失败{m}, 跳过{k}, 共扫描{t}人`

---

## 已知限制

1. **DeepSeek API 依赖**: 无 API Key 时 AI 回复降级为模板，生成方式标记为 `template_fallback`
2. **BOSS 界面变化**: 选择器和 JS 脚本依赖 BOSS DOM 结构，UI 更新可能导致选择器失效
3. **限制弹窗检测**: 弹窗样式变化时关键词匹配可能漏检
4. **消息发送确认**: 当前无消息发送后 DOM 验证（如新消息是否真的出现在聊天列表中）

## 视觉验收通过标准

- [ ] 8 个截图检查点中至少 6 个通过
- [ ] API 返回 `status: "completed"`
- [ ] 每个处理过的联系人在 `results` 中有对应条目
- [ ] `generation_method` 分布合理（ai > template_fallback > stage_fallback）
- [ ] 无未捕获异常
- [ ] 限制弹窗出现时正确终止
